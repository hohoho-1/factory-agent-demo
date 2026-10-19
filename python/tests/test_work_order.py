"""
지시서 생성기 테스트. 실행 (python 폴더에서):
  .venv\\Scripts\\python -m unittest discover -s tests -t .
"""
import unittest

from agent.rag import ManualIndex, load_manuals
from agent.work_order import TemplateGenerator, history_section

ALARM = {
    "id": 99, "equipmentId": "MIXER-01", "equipmentType": "MIXER", "metric": "vibration",
    "unit": "mm/s", "severity": "CRITICAL", "direction": "HIGH", "thresholdValue": 7.1,
    "triggerValue": 4.6, "peakValue": 8.2, "lastValue": 7.9,
    "raisedAt": "2026-10-19T05:00:00Z", "message": "MIXER-01 vibration",
}


def past(id_, outcome, cause, completed="2026-10-19T05:32:10.123456Z"):
    return {"id": id_, "severity": "CRITICAL", "outcome": outcome, "rootCause": cause,
            "actionTaken": "그리스 보충", "worker": "kim", "completedAt": completed}


class HistorySectionTest(unittest.TestCase):

    def test_empty_history_adds_nothing(self):
        self.assertEqual(history_section([]), [])

    def test_latest_resolved_cause_is_highlighted(self):
        lines = history_section([
            past(13, "UNRESOLVED", "센서 오류"),
            past(12, "RESOLVED", "베어링 윤활 부족"),
        ])
        text = "\n".join(lines)
        self.assertIn("과거 유사 조치 이력 (2건)", text)
        # 미해결 건은 건너뛰고 가장 최근 '해결' 원인을 우선 확인으로
        self.assertIn("우선 확인**: 지난번 해결된 원인 '베어링 윤활 부족' (WO-12", text)
        self.assertIn("**미해결**", text)

    def test_missing_cause_is_shown_as_unknown(self):
        text = "\n".join(history_section([past(12, "PARTIAL", None, completed=None)]))
        self.assertNotIn("우선 확인", text)
        self.assertIn("원인: 미확인", text)


class TemplateGeneratorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def test_finds_vibration_manual_and_critical_action(self):
        wo = TemplateGenerator().generate(ALARM, self.index)
        self.assertEqual(wo["references"][0]["manualId"], "MAN-MIX-VIB-01")
        self.assertIn("## 즉시 조치 (CRITICAL)", wo["body"])
        self.assertNotIn("과거 유사 조치", wo["body"])

    def test_history_goes_before_causes_and_into_summary(self):
        wo = TemplateGenerator().generate(ALARM, self.index, [past(12, "RESOLVED", "베어링 윤활 부족")])
        body = wo["body"]
        self.assertLess(body.index("## 과거 유사 조치 이력"), body.index("## 추정 원인"))
        self.assertTrue(wo["summary"].endswith("과거 유사 조치 1건 참고."))


if __name__ == "__main__":
    unittest.main()
