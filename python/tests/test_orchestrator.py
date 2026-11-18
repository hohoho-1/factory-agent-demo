"""
오케스트레이터 테스트: 라우터 · 자율성 단계 · 승인 요청 · 타임아웃/재시도 후 handoff · 결정 로그.
실행 (python 폴더에서):
  .venv\\Scripts\\python -m unittest discover -s tests -t .
"""
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

from agent.orchestrator import (ALERT, APPROVE, BATCH, EQUIPMENT, HANDOFF, PROCESS, RECOMMEND, Orchestrator,
                                StepPolicy, classify)
from agent.rag import ManualIndex, load_manuals
from agent.work_order import TemplateGenerator

INDEX = ManualIndex(load_manuals())


def alarm(**kw):
    base = {"id": 7, "equipmentId": "MIXER-01", "equipmentType": "MIXER", "metric": "vibration", "unit": "mm/s",
            "severity": "WARNING", "direction": "HIGH", "thresholdValue": 4.5, "triggerValue": 5.0,
            "peakValue": 5.0, "lastValue": 5.0, "raisedAt": "2026-11-18T05:00:00Z", "message": "test"}
    base.update(kw)
    return base


SPEED_SP = {"equipmentId": "MIXER-01", "tag": "speed_sp", "label": "교반 회전수 설정값", "unit": "rpm",
            "min": 40, "max": 66, "maxStep": 15, "nominal": 60, "currentValue": 60}


class FakeBackend:
    def __init__(self, setpoints=None, history_error=None, reject_proposal=False):
        self.setpoints = setpoints or []
        self.history_error = history_error
        self.reject_proposal = reject_proposal
        self.history_calls = 0
        self.saved = []
        self.proposals = []
        self.quality = []

    def get_history(self, alarm):
        self.history_calls += 1
        if self.history_error:
            raise self.history_error
        return []

    def get_setpoints(self, equipment_id):
        return [s for s in self.setpoints if s["equipmentId"] == equipment_id]

    def save_work_order(self, alarm_id, wo):
        self.saved.append(wo)
        return {"id": 100 + len(self.saved), "title": wo["title"]}

    def save_quality_assessment(self, wo_id, assessment):
        self.quality.append((wo_id, assessment))
        return {"id": 700 + len(self.quality), "status": "PENDING" if assessment["level"] == "HOLD" else "RECORDED"}

    def save_setpoint_proposal(self, wo_id, proposal):
        if self.reject_proposal:
            raise urllib.error.HTTPError("u", 422, "out of range", {}, None)
        self.proposals.append((wo_id, proposal))
        return {"id": 500}


class SlowGenerator:
    name = "slow"

    def __init__(self, seconds):
        self.seconds = seconds
        self.calls = 0

    def generate(self, *args):
        self.calls += 1
        time.sleep(self.seconds)
        return TemplateGenerator().generate(*args)


class FlakyGenerator:
    """처음 n번은 실패하고 그다음부터 템플릿으로 쓴다."""
    name = "flaky"

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def generate(self, *args):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("LLM 응답 없음")
        return TemplateGenerator().generate(*args)


def orchestrator(backend, generator=None, **policies):
    return Orchestrator(INDEX, backend, generator or TemplateGenerator(),
                        policies={k: StepPolicy(**v) for k, v in policies.items()}, out=lambda *_: None)


class RouterTest(unittest.TestCase):

    def test_routes(self):
        self.assertEqual(classify(alarm(), INDEX).kind, EQUIPMENT)
        self.assertEqual(classify(alarm(metric="temperature", direction="LOW", batchPhase="EMULSIFYING",
                                        thresholdValue=68), INDEX).kind, BATCH)
        self.assertEqual(classify(alarm(equipmentId="TANK-01", equipmentType="RAW_TANK", metric="level",
                                        direction="LOW"), INDEX).kind, PROCESS)

    def test_no_manual_goes_to_handoff_even_in_a_batch(self):
        route = classify(alarm(metric="temperature", direction="HIGH", batchPhase="EMULSIFYING"), INDEX)
        self.assertEqual(route.kind, HANDOFF)
        self.assertIn("매뉴얼 없음", route.reason)

    def test_idle_phase_is_not_a_batch(self):
        route = classify(alarm(equipmentId="TANK-01", equipmentType="RAW_TANK", metric="level", direction="LOW",
                               batchPhase="IDLE"), INDEX)
        self.assertEqual(route.kind, PROCESS)


class FlowTest(unittest.TestCase):

    def test_recommend_when_no_setpoint_to_adjust(self):
        backend = FakeBackend()
        state = orchestrator(backend).run(alarm(), "RAISED")
        self.assertEqual(state.autonomy, RECOMMEND)
        self.assertEqual(state.approval, "NOT_NEEDED")
        self.assertEqual(len(backend.saved), 1)
        self.assertIn("## 처리 기록 (오케스트레이터)", backend.saved[0]["body"])
        self.assertIn("자율성 단계: 추천", backend.saved[0]["body"])
        self.assertEqual(backend.saved[0]["severity"], "WARNING")
        self.assertNotIn("setpointChange", backend.saved[0])

    def test_approve_reuses_setpoint_approval(self):
        # 진동 경고 매뉴얼: '회전수를 10~20% 낮추고' → 교반 회전수 설정값 변경 제안 → 작업자 승인 대기
        backend = FakeBackend(setpoints=[SPEED_SP])
        state = orchestrator(backend).run(alarm(), "RAISED")
        self.assertEqual(state.autonomy, APPROVE)
        self.assertEqual(state.approval, "PENDING")
        self.assertEqual(backend.proposals[0][0], state.saved_id)
        self.assertEqual(backend.proposals[0][1]["tag"], "speed_sp")

    def test_backend_rejection_falls_back_to_recommend(self):
        backend = FakeBackend(setpoints=[SPEED_SP], reject_proposal=True)
        state = orchestrator(backend).run(alarm(), "RAISED")
        self.assertEqual(state.approval, "REJECTED")
        self.assertEqual(state.autonomy, RECOMMEND)
        self.assertEqual(len(backend.saved), 1)

    def test_handoff_route_alerts_only(self):
        backend = FakeBackend(setpoints=[SPEED_SP])
        state = orchestrator(backend).run(alarm(metric="temperature", direction="HIGH", unit="C",
                                                thresholdValue=50, lastValue=52), "RAISED")
        self.assertEqual(state.route.kind, HANDOFF)
        self.assertEqual(state.autonomy, ALERT)
        self.assertEqual(backend.proposals, [])
        self.assertIn("매뉴얼 없음, 담당자 확인", backend.saved[0]["title"])


class FailureTest(unittest.TestCase):

    def test_retry_then_succeed(self):
        gen = FlakyGenerator(failures=1)
        state = orchestrator(FakeBackend(), gen, propose={"timeout": 5, "retries": 1, "required": True}).run(
            alarm(), "RAISED")
        self.assertEqual(gen.calls, 2)
        self.assertEqual(state.autonomy, RECOMMEND)
        self.assertEqual([s.status for s in state.log if s.step == "propose"], ["error", "ok"])

    def test_retries_exhausted_hands_off_to_a_person(self):
        backend = FakeBackend()
        gen = FlakyGenerator(failures=5)
        state = orchestrator(backend, gen, propose={"timeout": 5, "retries": 1, "required": True}).run(
            alarm(), "RAISED")
        self.assertEqual(gen.calls, 2)  # 재시도 상한 1번
        self.assertEqual(state.autonomy, ALERT)
        self.assertIn("propose 단계 실패", state.handoff_reason)
        self.assertEqual(backend.saved[0]["generator"], "handoff")
        self.assertIn("자동 처리 실패, 담당자 확인", backend.saved[0]["title"])

    def test_timeout_hands_off(self):
        backend = FakeBackend()
        started = time.perf_counter()
        state = orchestrator(backend, SlowGenerator(1.0), propose={"timeout": 0.1, "retries": 0, "required": True}
                             ).run(alarm(), "RAISED")
        self.assertLess(time.perf_counter() - started, 0.9)  # 느린 생성기를 끝까지 기다리지 않는다
        self.assertEqual([s.status for s in state.log if s.step == "propose"], ["timeout"])
        self.assertEqual(backend.saved[0]["generator"], "handoff")

    def test_llm_fallback_is_recorded(self):
        from agent.llm import FallbackGenerator

        class BrokenLlm:
            name = "llm"

            def generate(self, *args):
                raise RuntimeError("401 invalid x-api-key")

        state = orchestrator(FakeBackend(), FallbackGenerator(BrokenLlm())).run(alarm(), "RAISED")
        self.assertEqual(state.work_order["generator"], "template")
        self.assertTrue(any("LLM 생성기 실패" in d for d in state.decisions))

    def test_optional_step_failure_degrades(self):
        backend = FakeBackend(history_error=urllib.error.URLError("down"))
        state = orchestrator(backend, history={"timeout": 1, "retries": 1, "required": False}).run(alarm(), "RAISED")
        self.assertEqual(backend.history_calls, 2)
        self.assertEqual(state.autonomy, RECOMMEND)  # 이력 없이도 지시서는 나간다
        self.assertTrue(any("그 정보 없이 계속" in d for d in state.decisions))

    def test_decision_log_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "decisions.jsonl"
            orch = Orchestrator(INDEX, FakeBackend(), TemplateGenerator(), decision_log=path, out=lambda *_: None)
            orch.run(alarm(), "RAISED")
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["route"], EQUIPMENT)
        self.assertEqual(record["autonomy"], RECOMMEND)
        self.assertEqual(record["workOrderId"], 101)
        self.assertTrue(record["decisions"][0].startswith("분류 EQUIPMENT"))


TEMP_SP = {"equipmentId": "TANK-02", "tag": "temp_sp", "label": "온도 설정값", "unit": "C",
           "min": 30, "max": 45, "maxStep": 20, "nominal": 40, "currentValue": 45}


class DemoScenarioTest(unittest.TestCase):
    """데모 장면(scripts/inject.ps1)이 만드는 알람이 오케스트레이터에서 예전과 같은 결과로 끝나는지."""

    def run_scenario(self, a, setpoints=()):
        backend = FakeBackend(setpoints=list(setpoints))
        return orchestrator(backend).run(a, "RAISED"), backend

    def test_mixer_resonance_proposes_speed_change_for_approval(self):
        state, backend = self.run_scenario(alarm(lastValue=5.2), [SPEED_SP])
        self.assertEqual((state.route.kind, state.autonomy, state.approval), (EQUIPMENT, APPROVE, "PENDING"))
        self.assertEqual(backend.proposals[0][1]["proposedValue"], 51)

    def test_batch_underheat_goes_through_batch_route(self):
        state, backend = self.run_scenario(alarm(metric="temperature", direction="LOW", unit="C", thresholdValue=68,
                                                 lastValue=66, batchPhase="EMULSIFYING", batchId="B-1118-01"),
                                           [SPEED_SP])
        self.assertEqual((state.route.kind, state.autonomy), (BATCH, RECOMMEND))
        self.assertIn("MAN-MIX-TEMP-01", backend.saved[0]["body"])

    def test_tank_overfill_is_handed_to_a_person(self):
        state, backend = self.run_scenario(alarm(equipmentId="TANK-01", equipmentType="RAW_TANK", metric="level",
                                                 unit="%", thresholdValue=95, lastValue=97))
        self.assertEqual((state.route.kind, state.autonomy), (HANDOFF, ALERT))
        self.assertEqual(backend.saved[0]["references"], [])

    def test_tank_setpoint_misentry_restores_nominal(self):
        state, backend = self.run_scenario(alarm(equipmentId="TANK-02", equipmentType="RAW_TANK", metric="temperature",
                                                 unit="C", thresholdValue=50, lastValue=51), [TEMP_SP])
        self.assertEqual((state.route.kind, state.autonomy), (PROCESS, APPROVE))
        self.assertEqual(backend.proposals[0][1]["proposedValue"], 40)


class QualityAgentTest(unittest.TestCase):
    """두 번째 에이전트: 배치 중 알람이면 지시서 다음에 품질 영향을 판정한다."""

    def batch_alarm(self, **kw):
        base = dict(metric="temperature", direction="LOW", unit="C", thresholdValue=68, lastValue=66,
                    peakValue=65.5, batchPhase="EMULSIFYING", batchId="B-1119-01")
        base.update(kw)
        return alarm(**base)

    def test_no_quality_step_outside_a_batch(self):
        backend = FakeBackend()
        state = orchestrator(backend).run(alarm(), "RAISED")
        self.assertIsNone(state.quality)
        self.assertEqual(backend.quality, [])
        self.assertNotIn("quality", [s.step for s in state.log])

    def test_emulsifying_underheat_warning_needs_inspection(self):
        backend = FakeBackend()
        state = orchestrator(backend).run(self.batch_alarm(), "RAISED")
        self.assertEqual(state.quality["level"], "INSPECT")
        self.assertEqual(state.quality_status, "RECORDED")
        self.assertEqual(backend.quality[0][0], state.saved_id)  # 지시서 저장 뒤 그 번호로 판정을 남긴다
        self.assertIn("품질 판정: 추가 검사 필요", backend.saved[0]["body"])

    def test_critical_underheat_asks_quality_team_to_approve_a_hold(self):
        backend = FakeBackend()
        state = orchestrator(backend).run(self.batch_alarm(severity="CRITICAL", thresholdValue=62, lastValue=61),
                                          "ESCALATED")
        self.assertEqual(state.quality["level"], "HOLD")
        self.assertEqual(state.quality_status, "PENDING")
        self.assertIn("(품질팀 승인 대기)", backend.saved[0]["body"])
        self.assertTrue(any("품질팀 승인 필요" in d for d in state.decisions))

    def test_quality_is_judged_even_when_the_alarm_is_handed_off(self):
        # 유화 중 과열: 매뉴얼이 없어 지시서는 사람에게 넘기지만, 품질 기준으로는 홀드 권고
        backend = FakeBackend()
        state = orchestrator(backend).run(self.batch_alarm(direction="HIGH", severity="CRITICAL",
                                                           thresholdValue=88, lastValue=89), "RAISED")
        self.assertEqual(state.route.kind, HANDOFF)
        self.assertEqual(state.quality["level"], "HOLD")

    def test_filler_speed_during_discharge_has_no_quality_impact(self):
        state = orchestrator(FakeBackend()).run(alarm(equipmentId="FILLER-01", equipmentType="FILLER", metric="speed",
                                                      direction="LOW", unit="bpm", thresholdValue=100, lastValue=95,
                                                      batchPhase="DISCHARGING", batchId="B-1"), "RAISED")
        self.assertEqual(state.quality["level"], "NO_IMPACT")

    def test_quality_save_failure_is_recorded(self):
        class Broken(FakeBackend):
            def save_quality_assessment(self, wo_id, assessment):
                raise urllib.error.URLError("down")

        state = orchestrator(Broken(), quality_save={"timeout": 1, "retries": 0, "required": False}).run(
            self.batch_alarm(), "RAISED")
        self.assertEqual(state.quality_status, "FAILED")
        self.assertTrue(any("품질 판정 저장 실패" in d for d in state.decisions))


if __name__ == "__main__":
    unittest.main()
