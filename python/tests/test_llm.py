"""LLM 생성기 테스트: 실제 API 대신 가짜 클라이언트로 응답을 흉내 낸다."""
import json
import unittest
from types import SimpleNamespace

from agent.llm import FallbackGenerator, LlmGenerator, LlmOutputError
from agent.rag import ManualIndex, load_manuals
from tests.test_work_order import ALARM, past


def item(text, *sources):
    return {"text": text, "sources": list(sources)}


GOOD = {
    "summary": "배합기 진동이 위험 단계라 즉시 정지 후 베어링을 점검한다.",
    "situation": "진동이 7.1mm/s 를 넘었다. 지난번 해결된 원인인 베어링 윤활 상태부터 확인한다.",
    "causes": [{"cause": "베어링 마모·윤활 부족", "reason": "가장 흔한 원인이고 지난번에도 해결됐다.",
                "sources": ["S1", "H1"]}],
    "inspection_steps": [item("최근 윤활 일자를 확인한다.", "S1")],
    "immediate_actions": [item("배합기를 정지한다.", "S1")],
    "safety": [item("잠금·표지 후 점검한다.", "S1")],
    "escalation": [],
}


class FakeClient:
    def __init__(self, data=None, stop_reason="end_turn"):
        self.calls = []
        text = json.dumps(data if data is not None else GOOD, ensure_ascii=False)
        self.response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class LlmGeneratorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex(load_manuals())

    def generate(self, client, history=None):
        return LlmGenerator(client=client, model="test-model", effort="low").generate(ALARM, self.index, history)

    def test_valid_response_becomes_cited_work_order(self):
        client = FakeClient()
        wo = self.generate(client, [past(12, "RESOLVED", "베어링 마모·윤활 부족")])
        self.assertEqual(wo["generator"], "llm")
        self.assertEqual(wo["references"][0]["manualId"], "MAN-MIX-VIB-01")
        self.assertIn("베어링 마모·윤활 부족", wo["causeOptions"])
        body = wo["body"]
        self.assertIn("## 상황 판단", body)
        self.assertIn("**베어링 마모·윤활 부족**", body)
        self.assertIn("과거 조치 WO-12", body)  # H1 근거 표시
        self.assertIn("(근거 매뉴얼에 해당 항목 없음)", body)  # 에스컬레이션이 비었을 때
        # 프롬프트에 근거 번호·원인 선택지·과거 이력이 들어간다
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("<S1>", prompt)
        self.assertIn("<H1>", prompt)
        self.assertIn("- 베어링 마모·윤활 부족", prompt)
        self.assertIn("MAN-SAFE-LOTO-01", prompt)  # 주 매뉴얼이 언급한 LOTO 매뉴얼도 근거로
        self.assertEqual(client.calls[0]["model"], "test-model")

    def test_unknown_or_missing_source_is_rejected(self):
        bad = dict(GOOD, immediate_actions=[item("근거 없는 조치", "S99")])
        with self.assertRaises(LlmOutputError):
            self.generate(FakeClient(bad))
        no_source = dict(GOOD, safety=[item("근거 없음")])
        with self.assertRaises(LlmOutputError):
            self.generate(FakeClient(no_source))
        # 과거 이력이 없는데 H1 을 인용하면 거부
        with self.assertRaises(LlmOutputError):
            self.generate(FakeClient(GOOD), history=[])

    def test_refusal_is_rejected(self):
        with self.assertRaises(LlmOutputError):
            self.generate(FakeClient(stop_reason="refusal"), [past(12, "RESOLVED", "x")])

    def test_fallback_uses_template_when_llm_fails(self):
        bad = dict(GOOD, safety=[])
        gen = FallbackGenerator(LlmGenerator(client=FakeClient(bad), model="m", effort="low"))
        wo = gen.generate(ALARM, self.index, [past(12, "RESOLVED", "x")])
        self.assertEqual(wo["generator"], "template")
        self.assertIn("## 추정 원인", wo["body"])


if __name__ == "__main__":
    unittest.main()
