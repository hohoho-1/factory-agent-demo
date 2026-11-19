"""
SuperAgent: 경영 질문 하나에 ERP · MES · 품질 · 설비 도구를 Claude 가 스스로 골라 불러 답한다 (IR 의 NEXA Command 역할).

지금까지의 오케스트레이터(python/agent/orchestrator.py)는 사람이 정한 순서로 도는 워크플로였다.
SuperAgent 는 처음으로 LLM 이 흐름을 정한다: 무엇을 먼저 조회할지, 결과를 보고 무엇을 더 볼지, 언제 답할지.
대신 코드가 울타리를 친다.
- 읽기 전용: 도구는 모두 조회다. 실행 · 승인은 사람이 화면에서 한다 (답에는 '사람이 할 일'로만 쓴다).
- 상한: 도구 호출 MAX_TOOL_CALLS 번, 모델 왕복 MAX_TURNS 번. 넘으면 도구 없이 지금까지 본 것으로 답하게 한다.
- 실행 기록: 어느 묶음의 어떤 도구를 어떤 입력으로, 몇 ms 에 불렀는지 남겨 화면에 보여 준다.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

from .tools import BY_NAME, TOOLS, run_tool

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
MAX_TOOL_CALLS = 12
MAX_TURNS = 8

SYSTEM = """\
당신은 캡슐 세제 공장의 운영 총괄 보조(SuperAgent)입니다. 경영진 · 관리자의 질문에, 도구로 조회한 사실만으로 답합니다.

시스템 구성 (도구 묶음)
- ERP: 판매 주문 · 납기, 생산 오더, 재고(품질 보류 포함), 구매 발주, 표준 원가
- MES: 현장 생산 지시와 배치 진행, 배합기 상태(세정 · 제품 전환), 배치 기록
- 품질: 품질 판정 · 홀드 · 검사 판정
- 설비: 알람, AI 조치 지시서, 조치 이력 통계

일하는 방식
- 질문에 필요한 도구만 고릅니다. 서로 기다릴 필요 없는 조회는 한 번에 여러 개 부릅니다.
- 한 시스템의 결과가 다른 시스템을 가리키면(예: 주문의 납기 위험 → 품질 보류 → 그 배치의 품질 판정) 이어서 조회합니다.
- 숫자 · 번호 · 날짜는 도구 결과에 있는 것만 씁니다. 결과에 없으면 "확인되지 않음"이라고 씁니다.
- 당신은 조회만 할 수 있습니다. 승인 · 출하 · 지시 같은 실행은 하지 못하므로, 필요하면 '사람이 할 일'로 제안합니다.

답 형식 (한국어, 짧게)
1. 결론: 질문에 대한 답 1~2문장
2. 근거: 어느 시스템에서 무엇을 확인했는지 3~6줄 (주문 · 배치 · 오더 번호를 함께)
3. 사람이 할 일: 다음 행동 1~3개 (담당: 생산 · 품질 · 구매 · 영업 중 누구인지)
"""


@dataclass
class Step:
    tool: str
    group: str
    input: dict
    ms: int
    ok: bool
    summary: str          # 결과 앞부분 (화면 표시용)


@dataclass
class Answer:
    question: str
    answer: str
    steps: list[Step] = field(default_factory=list)
    turns: int = 0
    stopped: str | None = None     # 상한에 걸렸으면 이유
    model: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {**asdict(self), "steps": [asdict(s) for s in self.steps]}


class SuperAgentError(RuntimeError):
    pass


class SuperAgent:
    def __init__(self, client=None, model: str | None = None, effort: str | None = None,
                 max_tool_calls: int = MAX_TOOL_CALLS, max_turns: int = MAX_TURNS):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(timeout=float(os.environ.get("LLM_TIMEOUT", "90")), max_retries=1)
        self.client = client
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("ANTHROPIC_EFFORT", DEFAULT_EFFORT)
        self.max_tool_calls = max_tool_calls
        self.max_turns = max_turns
        self.tools = [t.schema() for t in TOOLS]

    def _call(self, messages: list, allow_tools: bool):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            tools=self.tools,
            tool_choice={"type": "auto" if allow_tools else "none"},
            messages=messages,
            output_config={"effort": self.effort},
            # 안전 분류기가 거절하면 서버가 다른 모델로 다시 돌린다
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def ask(self, question: str) -> Answer:
        started = time.perf_counter()
        result = Answer(question=question, answer="", model=self.model)
        messages: list = [{"role": "user", "content": question}]
        calls = 0
        allow_tools = True
        while True:
            result.turns += 1
            response = self._call(messages, allow_tools)
            if response.stop_reason == "refusal":
                raise SuperAgentError("모델이 답하기를 거절했습니다")
            if response.stop_reason == "max_tokens":
                raise SuperAgentError("답이 너무 길어 끝까지 받지 못했습니다")
            # 응답 블록은 thinking 블록까지 그대로 다음 요청에 돌려준다
            messages.append({"role": "assistant", "content": response.content})
            uses = [b for b in response.content if b.type == "tool_use"]
            # 상한 뒤에는 도구를 다시 부르더라도 실행하지 않고 그 응답의 글로 끝낸다
            if response.stop_reason != "tool_use" or not uses or not allow_tools:
                result.answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
                break
            tool_results = []
            for use in uses:
                calls += 1
                t0 = time.perf_counter()
                text, is_error = run_tool(use.name, dict(use.input or {}))
                tool = BY_NAME.get(use.name)
                result.steps.append(Step(use.name, tool.group if tool else "?", dict(use.input or {}),
                                         int((time.perf_counter() - t0) * 1000), not is_error, text[:240]))
                tool_results.append({"type": "tool_result", "tool_use_id": use.id, "content": text,
                                     **({"is_error": True} if is_error else {})})
            if calls >= self.max_tool_calls or result.turns >= self.max_turns:
                # 상한: 더 조회하지 못하게 하고 지금까지 본 것으로 답하게 한다 (도구 결과와 같은 메시지에 덧붙인다)
                result.stopped = (f"도구 호출 상한 {self.max_tool_calls}번" if calls >= self.max_tool_calls
                                  else f"왕복 상한 {self.max_turns}번")
                tool_results.append({"type": "text", "text": f"조회 상한({result.stopped})에 도달했습니다. 더 조회하지 말고"
                                                             " 지금까지 확인한 사실로 답하세요. 확인하지 못한 부분은 그렇다고 쓰세요."})
                allow_tools = False
            messages.append({"role": "user", "content": tool_results})
        result.seconds = round(time.perf_counter() - started, 1)
        return result


def _demo() -> None:
    import sys
    from agent.agent import load_env_file
    sys.stdout.reconfigure(encoding="utf-8")
    load_env_file()
    q = " ".join(sys.argv[1:]) or "지금 납기에 위험한 주문이 있어? 이유와 우리가 해야 할 일을 알려줘"
    a = SuperAgent().ask(q)
    for s in a.steps:
        print(f"  [{s.group}] {s.tool} {json.dumps(s.input, ensure_ascii=False)} {s.ms}ms {'ok' if s.ok else 'ERROR'}")
    print(f"\n{a.answer}\n\n({a.turns}왕복, 도구 {len(a.steps)}번, {a.seconds}초, {a.model})")


if __name__ == "__main__":
    _demo()
