"""권장 설정값 변경 테스트: 템플릿 규칙, LLM 제안 검증(가짜 클라이언트), 에이전트의 저장 흐름."""
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stderr

from agent.agent import Agent
from agent.llm import LlmGenerator
from agent.rag import ManualIndex, load_manuals
from agent.work_order import TemplateGenerator
from tests.test_llm import GOOD, FakeClient
from tests.test_work_order import ALARM, past

WARNING = {**ALARM, "severity": "WARNING", "thresholdValue": 4.5, "lastValue": 5.6, "peakValue": 5.7}
SPEED = {"equipmentId": "MIXER-01", "tag": "speed_sp", "label": "교반 회전수 설정값", "unit": "rpm",
         "min": 40, "max": 66, "maxStep": 15, "nominal": 60, "currentValue": 60.0}
TEMP = {"equipmentId": "TANK-02", "tag": "temp_sp", "label": "온도 설정값", "unit": "C",
        "min": 30, "max": 45, "maxStep": 20, "nominal": 40, "currentValue": 55.0}
TANK_ALARM = {**WARNING, "equipmentId": "TANK-02", "equipmentType": "RAW_TANK", "metric": "temperature",
              "unit": "C", "thresholdValue": 50, "lastValue": 52}


class TemplateProposalTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def test_mixer_warning_lowers_speed_by_manual_percentage(self):
        wo = TemplateGenerator().generate(WARNING, self.index, [], [SPEED])
        p = wo["setpointChange"]
        self.assertEqual((p["tag"], p["currentValue"], p["proposedValue"]), ("speed_sp", 60.0, 51))  # 10~20% → 15%
        self.assertIn("10~20% 낮추", p["reason"])
        self.assertEqual(p["sources"], "MAN-MIX-VIB-01 조치 - 경고(WARNING)")

    def test_no_proposal_without_live_setpoint_or_in_critical(self):
        self.assertIsNone(TemplateGenerator().generate(WARNING, self.index, [], [])["setpointChange"])
        offline = {**SPEED, "currentValue": None}  # 게이트웨이가 끊겨 현재값을 모름
        self.assertIsNone(TemplateGenerator().generate(WARNING, self.index, [], [offline])["setpointChange"])
        # 위험 단계 매뉴얼 조치는 '즉시 정지'라 설정값 제안을 하지 않는다
        self.assertIsNone(TemplateGenerator().generate(ALARM, self.index, [], [SPEED])["setpointChange"])

    def test_tank_misentry_restores_nominal(self):
        p = TemplateGenerator().generate(TANK_ALARM, self.index, [], [TEMP])["setpointChange"]
        self.assertEqual(p["proposedValue"], 40)
        self.assertIn("기준값", p["reason"])
        normal = {**TEMP, "currentValue": 40.0}  # 이미 기준값이면 제안 없음
        self.assertIsNone(TemplateGenerator().generate(TANK_ALARM, self.index, [], [normal])["setpointChange"])


class LlmProposalTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def generate(self, changes, setpoints=(SPEED,)):
        client = FakeClient({**GOOD, "setpoint_changes": changes})
        with redirect_stderr(io.StringIO()) as err:
            history = [past(12, "RESOLVED", "베어링 마모·윤활 부족")]  # GOOD 이 H1 을 인용한다
            wo = LlmGenerator(client=client, model="m", effort="low").generate(WARNING, self.index, history,
                                                                               list(setpoints))
        return wo, client, err.getvalue()

    def test_valid_proposal_is_cited(self):
        wo, client, _ = self.generate([{"tag": "speed_sp", "proposed_value": 50, "reason": "공진 의심",
                                        "sources": ["S1"]}])
        p = wo["setpointChange"]
        self.assertEqual((p["proposedValue"], p["currentValue"]), (50, 60.0))
        self.assertTrue(p["sources"].startswith("MAN-MIX-VIB-01 "))
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("speed_sp (교반 회전수 설정값): 현재 60rpm, 운전 범위 40~66, 한 번에 최대 15 변경", prompt)
        self.assertIn("setpoint_changes", json.dumps(client.calls[0]["output_config"]["format"]["schema"]))

    def test_invalid_proposal_is_dropped_but_work_order_kept(self):
        for change, reason in [
            ({"tag": "speed_sp", "proposed_value": 30, "reason": "r", "sources": ["S1"]}, "운전 범위"),
            ({"tag": "speed_sp", "proposed_value": 42, "reason": "r", "sources": ["S1"]}, "한 번에"),
            ({"tag": "speed_sp", "proposed_value": 50, "reason": "r", "sources": []}, "근거가 없습니다"),
            ({"tag": "speed_sp", "proposed_value": 50, "reason": "r", "sources": ["S99"]}, "목록에 없는 근거"),
            ({"tag": "temp_sp", "proposed_value": 40, "reason": "r", "sources": ["S1"]}, "조정 가능한 설정값이 아닙니다"),
        ]:
            with self.subTest(reason=reason):
                wo, _, err = self.generate([change])
                self.assertIsNone(wo["setpointChange"])
                self.assertEqual(wo["generator"], "llm")
                self.assertIn(reason, err)

    def test_no_setpoints_means_empty_list_instruction(self):
        wo, client, _ = self.generate([], setpoints=())
        self.assertIsNone(wo["setpointChange"])
        self.assertIn("(없음: setpoint_changes 는 빈 배열로 둡니다)", client.calls[0]["messages"][0]["content"])


class FakeBackend:
    def __init__(self, setpoints, reject_proposal=False):
        self.setpoints = setpoints
        self.reject_proposal = reject_proposal
        self.saved_work_orders, self.proposals = [], []

    def get_history(self, alarm):
        return []

    def get_setpoints(self, equipment_id):
        return [s for s in self.setpoints if s["equipmentId"] == equipment_id]

    def save_work_order(self, alarm_id, wo):
        self.saved_work_orders.append(wo)
        return {"id": 41, "title": wo["title"]}

    def save_setpoint_proposal(self, work_order_id, proposal):
        if self.reject_proposal:
            raise urllib.error.HTTPError("url", 422, "Unprocessable", {}, io.BytesIO("운전 범위 밖".encode()))
        self.proposals.append((work_order_id, proposal))
        return {"id": 5}


class AgentProposalTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def test_agent_saves_work_order_then_proposal(self):
        backend = FakeBackend([SPEED])
        with redirect_stderr(io.StringIO()), redirect_stdout_quiet():
            Agent(self.index, backend).handle(WARNING, "RAISED")
        self.assertNotIn("setpointChange", backend.saved_work_orders[0])
        work_order_id, proposal = backend.proposals[0]
        self.assertEqual(work_order_id, 41)
        self.assertEqual(proposal["proposedValue"], 51)
        self.assertEqual(proposal["generator"], "template")

    def test_backend_rejection_keeps_work_order(self):
        backend = FakeBackend([SPEED], reject_proposal=True)
        with redirect_stderr(io.StringIO()) as err, redirect_stdout_quiet():
            Agent(self.index, backend).handle(WARNING, "RAISED")
        self.assertEqual(len(backend.saved_work_orders), 1)
        self.assertIn("422", err.getvalue())


def redirect_stdout_quiet():
    from contextlib import redirect_stdout
    return redirect_stdout(io.StringIO())


if __name__ == "__main__":
    unittest.main()
