"""
SuperAgent 루프 테스트 (가짜 Claude 클라이언트, 도구는 가짜 실행). 실행 (python 폴더에서):
  .venv\\Scripts\\python -m unittest tests.test_superagent
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from superagent import agent as sa
from superagent.tools import TOOLS


def block(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


def reply(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class FakeClient:
    """정해 둔 응답을 차례로 돌려주고, 받은 요청을 기록한다."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return self.replies.pop(0)


def fake_run(name, args):
    return f'{{"tool": "{name}"}}', False


class SuperAgentTest(unittest.TestCase):

    def test_tools_are_read_only_and_strict(self):
        names = {t.name for t in TOOLS}
        self.assertEqual({t.group for t in TOOLS}, {"ERP", "MES", "품질", "설비"})
        # 실행 · 승인 · 쓰기 도구는 없다
        self.assertFalse(any(w in n for n in names for w in ("approve", "release", "ship", "create", "start", "write")))
        for t in TOOLS:
            s = t.schema()
            self.assertTrue(s["strict"])
            self.assertFalse(s["input_schema"]["additionalProperties"])

    def test_parallel_calls_then_answer_with_trace(self):
        client = FakeClient([
            reply("tool_use",
                  block("text", text="주문과 품질을 함께 볼게요"),
                  block("tool_use", id="t1", name="erp_sales_orders", input={}),
                  block("tool_use", id="t2", name="quality_assessments", input={"batch_id": None})),
            reply("end_turn", block("text", text="1. 결론: SO-0005 납기 위험")),
        ])
        with mock.patch.object(sa, "run_tool", side_effect=fake_run):
            a = sa.SuperAgent(client=client, model="m", effort="medium").ask("납기 위험?")
        self.assertEqual(a.answer, "1. 결론: SO-0005 납기 위험")
        self.assertEqual([(s.group, s.tool) for s in a.steps], [("ERP", "erp_sales_orders"), ("품질", "quality_assessments")])
        self.assertEqual(a.turns, 2)
        # 두 도구 결과는 한 메시지로 돌려준다
        second = client.requests[1]["messages"]
        self.assertEqual([r["tool_use_id"] for r in second[-1]["content"]], ["t1", "t2"])
        self.assertEqual(client.requests[0]["tool_choice"], {"type": "auto"})
        self.assertEqual(client.requests[0]["fallbacks"], "default")

    def test_cap_stops_tool_use_and_forces_an_answer(self):
        loop = [reply("tool_use", block("tool_use", id=f"t{i}", name="mes_jobs", input={})) for i in range(2)]
        client = FakeClient(loop + [reply("end_turn", block("text", text="지금까지 본 것으로 답"))])
        with mock.patch.object(sa, "run_tool", side_effect=fake_run):
            a = sa.SuperAgent(client=client, model="m", effort="low", max_tool_calls=2).ask("q")
        self.assertEqual(len(a.steps), 2)
        self.assertIn("도구 호출 상한 2번", a.stopped)
        last = client.requests[-1]
        self.assertEqual(last["tool_choice"], {"type": "none"})
        self.assertEqual(last["messages"][-1]["content"][-1]["type"], "text")   # 상한 안내는 도구 결과와 같은 메시지

    def test_tool_errors_are_reported_not_raised(self):
        client = FakeClient([
            reply("tool_use", block("tool_use", id="t1", name="erp_inventory", input={"item_code": None})),
            reply("end_turn", block("text", text="ERP 를 조회하지 못했습니다")),
        ])
        with mock.patch.object(sa, "run_tool", return_value=('{"error": "down"}', True)):
            a = sa.SuperAgent(client=client, model="m", effort="low").ask("재고?")
        self.assertFalse(a.steps[0].ok)
        self.assertTrue(client.requests[1]["messages"][-1]["content"][0]["is_error"])

    def test_refusal_raises(self):
        client = FakeClient([reply("refusal")])
        with self.assertRaises(sa.SuperAgentError):
            sa.SuperAgent(client=client, model="m", effort="low").ask("q")


if __name__ == "__main__":
    unittest.main()
