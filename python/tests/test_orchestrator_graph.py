"""
LangGraph 버전이 직접 구현(Orchestrator)과 같은 결과를 내는지, 그리고 LangGraph 에만 있는 기능
(그래프 그림, interrupt 로 승인 대기 후 이어 가기)을 확인한다.
실행 (python 폴더에서, langgraph 설치 필요: pip install -r requirements-langgraph.txt):
  .venv\\Scripts\\python -m unittest tests.test_orchestrator_graph
"""
import json
import unittest
import urllib.error

try:
    from agent.orchestrator_graph import build_graph, initial_state, resume
    HAVE_LANGGRAPH = True
except ImportError:  # 데모 실행에는 langgraph 가 필요 없다
    HAVE_LANGGRAPH = False

from agent.orchestrator import ALERT, APPROVE, HANDOFF, RECOMMEND, Orchestrator, StepPolicy
from agent.work_order import TemplateGenerator
from eval.run_eval import SET_FILE, to_alarm
from eval.run_router_eval import EXTRA_FILE
from tests.test_orchestrator import INDEX, SPEED_SP, TEMP_SP, FakeBackend, FlakyGenerator, SlowGenerator, alarm


def run_graph(backend, a, generator=None, **policies):
    graph = build_graph(INDEX, backend, generator or TemplateGenerator(),
                        policies={k: StepPolicy(**v) for k, v in policies.items()})
    return graph.invoke(initial_state(a, "RAISED"))


@unittest.skipUnless(HAVE_LANGGRAPH, "langgraph 미설치")
class ParityTest(unittest.TestCase):
    """평가셋 28문항 + 설정값 유무로, 두 구현의 경로·자율성·승인 상태·지시서가 같은지."""

    def cases(self):
        base = json.loads(SET_FILE.read_text(encoding="utf-8"))["cases"]
        extra = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))["cases"]
        return base + extra

    def test_same_outcome_as_hand_written_orchestrator(self):
        for case in self.cases():
            for setpoints in ([], [SPEED_SP, TEMP_SP]):
                a = to_alarm(case)
                with self.subTest(case=case["id"], setpoints=bool(setpoints)):
                    b1, b2 = FakeBackend(setpoints=setpoints), FakeBackend(setpoints=setpoints)
                    s1 = Orchestrator(INDEX, b1, TemplateGenerator(), out=lambda *_: None).run(dict(a), "RAISED")
                    s2 = run_graph(b2, dict(a))
                    self.assertEqual(s2["route"].kind, s1.route.kind)
                    self.assertEqual(s2["autonomy"], s1.autonomy)
                    self.assertEqual(s2["approval"], s1.approval)
                    self.assertEqual(s2["decisions"], s1.decisions)
                    self.assertEqual(b2.saved[0]["body"], b1.saved[0]["body"])
                    self.assertEqual(b2.proposals, b1.proposals)


@unittest.skipUnless(HAVE_LANGGRAPH, "langgraph 미설치")
class GraphFailureTest(unittest.TestCase):

    def test_retries_exhausted_go_to_handoff_node(self):
        backend = FakeBackend()
        gen = FlakyGenerator(failures=5)
        s = run_graph(backend, alarm(), gen, propose={"timeout": 5, "retries": 1, "required": True})
        self.assertEqual(gen.calls, 2)
        self.assertEqual(s["autonomy"], ALERT)
        self.assertEqual(backend.saved[0]["generator"], "handoff")

    def test_timeout_goes_to_handoff_node(self):
        backend = FakeBackend()
        s = run_graph(backend, alarm(), SlowGenerator(1.0), propose={"timeout": 0.1, "retries": 0, "required": True})
        self.assertEqual([x.status for x in s["log"] if x.step == "propose"], ["timeout"])
        self.assertEqual(backend.saved[0]["generator"], "handoff")

    def test_save_is_retried_by_retry_policy(self):
        class FlakySave(FakeBackend):
            fails = 2

            def save_work_order(self, alarm_id, wo):
                if self.fails:
                    self.fails -= 1
                    raise urllib.error.URLError("backend restarting")
                return super().save_work_order(alarm_id, wo)

        backend = FlakySave()
        s = run_graph(backend, alarm(), save={"timeout": 5, "retries": 2, "required": True})
        self.assertEqual(s["saved_id"], 101)
        self.assertEqual(s["autonomy"], RECOMMEND)


@unittest.skipUnless(HAVE_LANGGRAPH, "langgraph 미설치")
class LangGraphOnlyTest(unittest.TestCase):

    def test_graph_can_be_drawn(self):
        graph = build_graph(INDEX, FakeBackend(), TemplateGenerator())
        mermaid = graph.get_graph().draw_mermaid()
        for node in ("route", "diagnose", "propose", "handoff", "save", "approve"):
            self.assertIn(node, mermaid)

    def test_interrupt_waits_for_worker_then_resumes(self):
        backend = FakeBackend(setpoints=[SPEED_SP])
        graph = build_graph(INDEX, backend, TemplateGenerator(), human_in_loop=True)
        config = {"configurable": {"thread_id": "alarm-7"}}
        paused = graph.invoke(initial_state(alarm(), "RAISED"), config)
        self.assertIn("__interrupt__", paused)  # 승인 노드에서 멈춤
        self.assertEqual(paused["__interrupt__"][0].value["setpointChangeId"], 500)
        self.assertEqual(graph.get_state(config).next, ("approve",))

        done = resume(graph, "alarm-7", "APPROVED", "kim")
        self.assertEqual(done["autonomy"], APPROVE)
        self.assertEqual(done["approval"], "APPROVED")
        self.assertEqual(done["decisions"][-1], "작업자 kim 결정: APPROVED")

    def test_handoff_route(self):
        s = run_graph(FakeBackend(), alarm(metric="temperature", direction="HIGH", unit="C"))
        self.assertEqual((s["route"].kind, s["autonomy"]), (HANDOFF, ALERT))


if __name__ == "__main__":
    unittest.main()
