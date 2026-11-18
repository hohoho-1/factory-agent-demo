"""
품질 에이전트 테스트: 규칙 판정과 LLM 설명 검증.
실행 (python 폴더에서):
  .venv\\Scripts\\python -m unittest tests.test_quality
"""
import unittest

from agent.quality import HOLD, INSPECT, NO_IMPACT, QualityAgent, judge

BASE = {"id": 1, "equipmentId": "MIXER-01", "equipmentType": "MIXER", "metric": "temperature", "unit": "C",
        "severity": "WARNING", "direction": "LOW", "thresholdValue": 68, "triggerValue": 66, "peakValue": 65.5,
        "lastValue": 66, "batchPhase": "EMULSIFYING", "batchId": "B-1"}
WO = {"summary": "MIXER-01 유화 온도 저하, MAN-MIX-TEMP-01 기준 조치"}


class FakeLlm:
    def __init__(self, data):
        self.data = data
        self.prompt = None

    def call_json(self, system, prompt, schema):
        self.prompt = prompt
        return self.data


class JudgeTest(unittest.TestCase):

    def test_rule_table(self):
        self.assertEqual(judge(BASE).level, INSPECT)
        self.assertEqual(judge({**BASE, "severity": "CRITICAL"}).level, HOLD)
        self.assertEqual(judge({**BASE, "metric": "vibration"}).level, NO_IMPACT)
        self.assertEqual(judge({**BASE, "metric": "vibration", "severity": "CRITICAL"}).level, INSPECT)
        self.assertEqual(judge({**BASE, "equipmentType": "RAW_TANK", "metric": "level", "batchPhase": "CHARGING",
                                "severity": "CRITICAL"}).level, HOLD)
        self.assertEqual(judge({**BASE, "equipmentType": "FILLER", "metric": "speed"}).level, NO_IMPACT)

    def test_same_input_same_verdict(self):
        self.assertEqual({judge(BASE).level for _ in range(20)}, {INSPECT})

    def test_not_in_batch_is_skipped(self):
        self.assertIsNone(QualityAgent().assess({**BASE, "batchPhase": None}, WO))
        self.assertIsNone(QualityAgent().assess({**BASE, "batchPhase": "IDLE"}, WO))


class ExplainTest(unittest.TestCase):

    def test_template_without_llm(self):
        q = QualityAgent().assess(BASE, WO)
        self.assertEqual((q["level"], q["generator"]), (INSPECT, "template"))
        self.assertIn("추가 검사", q["reason"])

    def test_llm_explains_with_refs(self):
        llm = FakeLlm({"reason": "유화 단계 온도가 66C로 기준 68C 아래로 내려갔습니다.", "refs": ["Q1", "Q2"]})
        q = QualityAgent(llm).assess(BASE, WO)
        self.assertEqual(q["generator"], "llm")
        self.assertIn("(근거: Q1, Q2)", q["reason"])
        self.assertIn("판정: 추가 검사 필요", llm.prompt)
        self.assertEqual(q["level"], INSPECT)  # 판정은 규칙이 정한다

    def test_llm_output_rejected_falls_back(self):
        cases = [
            {"reason": "설명", "refs": []},
            {"reason": "설명", "refs": ["Q9"]},
            {"reason": "배치 홀드 · 출하 보류 권고가 맞습니다", "refs": ["Q1"]},
        ]
        for data in cases:
            with self.subTest(data=data):
                q = QualityAgent(FakeLlm(data)).assess(BASE, WO)
                self.assertEqual((q["level"], q["generator"]), (INSPECT, "template"))


if __name__ == "__main__":
    unittest.main()
