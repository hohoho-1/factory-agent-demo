"""교대 인수인계 리포트 테스트 (LLM 은 가짜 클라이언트)."""
import unittest

from agent.handover import HandoverWriter, template_report
from agent.llm import LlmGenerator
from tests.test_llm import FakeClient


def alarm(id_, eq="MIXER-01", type_="MIXER", metric="vibration", severity="CRITICAL", status="CLEARED"):
    return {"id": id_, "equipmentId": eq, "equipmentType": type_, "metric": metric, "unit": "mm/s",
            "severity": severity, "status": status, "direction": "HIGH", "thresholdValue": 7.1, "peakValue": 9.2,
            "raisedAt": "2026-10-19T05:00:00Z",
            "clearedAt": None if status == "ACTIVE" else "2026-10-19T05:00:31Z"}


def wo(id_, alarm_id, status="COMPLETED", outcome="RESOLVED", cause="베어링 마모·윤활 부족", eq="MIXER-01"):
    return {"id": id_, "alarmId": alarm_id, "equipmentId": eq, "metric": "vibration", "severity": "CRITICAL",
            "status": status, "generator": "llm", "createdAt": "2026-10-19T05:00:15Z",
            "worker": "kim" if status != "OPEN" else None, "rootCause": cause if status == "COMPLETED" else None,
            "actionTaken": "그리스 보충" if status == "COMPLETED" else None,
            "outcome": outcome if status == "COMPLETED" else None,
            "completedAt": "2026-10-19T05:10:00Z" if status == "COMPLETED" else None, "supersededBy": None}


CTX = {
    "from": "2026-10-18T21:00:00Z", "to": "2026-10-19T05:30:00Z",
    "alarms": [alarm(1), alarm(2), alarm(3, eq="TANK-02", type_="RAW_TANK", metric="temperature", status="ACTIVE")],
    "workOrders": [wo(10, 1), wo(11, 2), wo(12, 3, status="OPEN", eq="TANK-02")],
}


class TemplateReportTest(unittest.TestCase):

    def test_counts_open_items_and_repeats(self):
        body = template_report(CTX)["body"]
        self.assertIn("알람 3건 (위험 3건, 진행 중 1건) · 조치 완료 2건 (해결 2건) · 남은 지시서 1건", body)
        self.assertIn("WO-12 미확인", body)
        self.assertIn("알람 #3", body)
        self.assertIn("이 시간대에 2회 발생 (주요 원인: 베어링 마모·윤활 부족)", body)

    def test_empty_window_says_nothing_happened(self):
        report = template_report({"from": CTX["from"], "to": CTX["to"], "alarms": [], "workOrders": []})
        self.assertIn("특이사항 없음", report["body"])
        self.assertEqual(report["generator"], "template")


def item(text, *refs):
    return {"text": text, "refs": list(refs)}


GOOD = {
    "headline": "배합기 진동이 두 번 났고 모두 베어링 윤활로 해결했다.",
    "overview": "배합기 진동 위험 알람이 2건 있었다. 탱크 2 온도는 아직 진행 중이다.",
    "events": [item("배합기 진동 위험 2회, 그리스 보충으로 해결했다.", "A1", "A2", "W10", "W11")],
    "open_items": [item("탱크 2 온도 지시서 W12가 아직 미확인이다 (A3 진행 중).", "W12", "A3")],
    "watch": [item("배합기 베어링 윤활 주기를 확인할 필요가 있다.", "A1", "A2")],
}


class LlmHandoverTest(unittest.TestCase):

    def writer(self, data, stop_reason="end_turn"):
        return HandoverWriter(LlmGenerator(client=FakeClient(data, stop_reason), model="m", effort="low"))

    def test_valid_response_is_rendered_with_refs_and_code_counts(self):
        report = self.writer(GOOD).write(CTX)
        self.assertEqual(report["generator"], "llm")
        body = report["body"]
        self.assertIn("**배합기 진동이 두 번 났고", body)
        self.assertIn("*(알람 #1 · 알람 #2 · WO-10 · WO-11)*", body)
        self.assertIn("남은 지시서 1건", body)  # 집계는 코드가 센 값
        self.assertIn("지시서 WO-12가 아직 미확인이다 (알람 #3 진행 중)", body)  # 문장 속 내부 번호도 화면 표기로
        self.assertNotIn("TANK-02 WO", body)  # 설비 ID 같은 다른 글자는 건드리지 않는다

    def test_unknown_ref_or_missing_events_fall_back_to_template(self):
        bad = dict(GOOD, open_items=[item("없는 지시서", "W99")])
        self.assertEqual(self.writer(bad).write(CTX)["generator"], "template")
        no_events = dict(GOOD, events=[])
        self.assertEqual(self.writer(no_events).write(CTX)["generator"], "template")

    def test_empty_window_does_not_call_llm(self):
        client = FakeClient(GOOD)
        writer = HandoverWriter(LlmGenerator(client=client, model="m", effort="low"))
        writer.write({"from": CTX["from"], "to": CTX["to"], "alarms": [], "workOrders": []})
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
