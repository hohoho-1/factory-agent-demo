"""AI 질의·매뉴얼 개선 제안 테스트 (LLM 은 가짜 클라이언트)."""
import unittest

from agent.assistant import AssistantWriter
from agent.llm import LlmGenerator
from agent.rag import ManualIndex, load_manuals
from tests.test_handover import alarm, wo
from tests.test_llm import FakeClient

STATS = [{"equipmentId": "MIXER-01", "metric": "vibration", "alarmCount": 2, "criticalCount": 2, "completedCount": 2,
          "resolvedCount": 2, "avgHandleMinutes": 3.0, "lastRaisedAt": None,
          "topCauses": [{"cause": "베어링 마모·윤활 부족", "count": 2}]}]

QUESTION_CTX = {
    "task": {"id": 7, "type": "QUESTION", "question": "배합기 진동 원인이 주로 뭐였어?"},
    "alarms": [alarm(1), alarm(2)],
    "workOrders": [wo(10, 1), wo(11, 2)],
}

PROPOSAL_CTX = {
    "task": {"id": 8, "type": "MANUAL_PROPOSAL", "equipmentId": "MIXER-01", "metric": "vibration"},
    "alarms": [alarm(1), alarm(2), alarm(3)],
    "workOrders": [wo(10, 1), wo(11, 2), wo(12, 3, cause="모터 베이스 균열", outcome="PARTIAL")],
}


def item(text, *refs):
    return {"text": text, "refs": list(refs)}


class AssistantTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def writer(self, data, stop_reason="end_turn"):
        llm = LlmGenerator(client=FakeClient(data, stop_reason), model="m", effort="low")
        return AssistantWriter(self.index, llm)

    # ---- 질의

    def test_question_answer_is_cited(self):
        data = {"answer": "주로 베어링 윤활 부족이었다. W10, W11 모두 해결됐다.",
                "details": [item("두 번 모두 그리스 보충으로 해결했다.", "W10", "W11", "S1"),
                            item("전체 기간 해결률은 100%다.", "T1")], "unanswerable": False}
        result = self.writer(data).write(QUESTION_CTX, STATS)
        self.assertEqual(result["generator"], "llm")
        self.assertIn("WO-10, WO-11 모두 해결됐다", result["body"])  # 문장 속 번호도 화면 표기로
        self.assertIn("*(WO-10 · WO-11 · MAN-", result["body"])
        self.assertIn("*(MIXER-01 진동 통계)*", result["body"])

    def test_unanswerable_needs_no_details(self):
        data = {"answer": "작년 기록은 재료에 없어 답할 수 없다.", "details": [], "unanswerable": True}
        result = self.writer(data).write(QUESTION_CTX, STATS)
        self.assertEqual(result["generator"], "llm")
        self.assertNotIn("## 근거", result["body"])

    def test_question_with_unknown_ref_falls_back(self):
        data = {"answer": "x", "details": [item("없는 기록", "W99")], "unanswerable": False}
        result = self.writer(data).write(QUESTION_CTX, STATS)
        self.assertEqual(result["generator"], "template")
        self.assertIn("## 관련 매뉴얼", result["body"])

    # ---- 매뉴얼 개선 제안

    def proposal(self, changes):
        return {"summary": "베어링 원인이 반복됐다.", "findings": [item("베어링 원인 2건", "W10", "W11")],
                "changes": changes}

    def change(self, section="가능 원인", *refs):
        return {"section": section, "kind": "추가", "proposal": "모터 베이스 균열을 가능 원인에 추가한다.",
                "reason": "W12 에서 확인됐다.", "refs": list(refs or ("W12",))}

    def test_proposal_is_rendered_and_cites_field_records(self):
        result = self.writer(self.proposal([self.change()])).write(PROPOSAL_CTX, STATS)
        self.assertEqual(result["generator"], "llm")
        body = result["body"]
        self.assertIn("매뉴얼 개선 제안(초안) MAN-MIX-VIB-01", result["title"])
        self.assertIn("### 1. 「가능 원인」 추가", body)
        self.assertIn("WO-12 에서 확인됐다", body)
        self.assertIn("조치 완료 3건 (해결률 67%)", body)  # 집계는 코드가 센 값

    def test_uncited_finding_is_dropped_but_proposal_kept(self):
        data = self.proposal([self.change()])
        data["findings"].append(item("다른 설비 기록은 0건이다."))
        result = self.writer(data).write(PROPOSAL_CTX, STATS)
        self.assertEqual(result["generator"], "llm")
        self.assertNotIn("다른 설비 기록은 0건", result["body"])

    def test_change_without_field_record_is_rejected(self):
        only_manual = self.change("가능 원인", "S1")
        self.assertEqual(self.writer(self.proposal([only_manual])).write(PROPOSAL_CTX, STATS)["generator"], "template")

    def test_template_flags_unknown_cause_and_unresolved(self):
        body = AssistantWriter(self.index, None).write(PROPOSAL_CTX, STATS)["body"]
        self.assertIn("「가능 원인」 추가 — '모터 베이스 균열'", body)
        self.assertIn("「점검 절차」 순서 변경 — '베어링 마모·윤활 부족'", body)
        self.assertIn("「에스컬레이션 기준」 수정 검토 — 미해결·부분 해결 1건 (WO-12)", body)

    def test_proposal_without_records_does_not_call_llm(self):
        client = FakeClient(self.proposal([]))
        writer = AssistantWriter(self.index, LlmGenerator(client=client, model="m", effort="low"))
        empty = dict(PROPOSAL_CTX, alarms=[alarm(1)], workOrders=[])
        self.assertIn("아직 조치 완료 기록이 없어", writer.write(empty, STATS)["body"])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
