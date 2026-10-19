"""
LLM 지시서 생성기 (Claude).

검색은 그대로 TF-IDF 가 하고, Claude 는 '주어진 근거로 문장만' 쓴다.
- 근거 목록: 가장 관련 높은 매뉴얼의 모든 섹션 + 그 매뉴얼이 언급하는 매뉴얼(LOTO 등) + 검색 상위 청크,
  그리고 작업자가 남긴 과거 조치 이력. 각각 S1, S2… / H1, H2… 로 번호를 붙여 보낸다.
- 응답은 JSON 스키마로 고정하고, 모든 항목에 근거 번호를 달게 한다.
- 근거가 없거나 목록에 없는 번호를 쓰면 지시서를 버린다 (FallbackGenerator 가 템플릿으로 대신 쓴다).

모델·노력 수준은 환경변수 ANTHROPIC_MODEL / ANTHROPIC_EFFORT 로 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

from .rag import Hit, Manual, ManualIndex
from .work_order import (
    EQUIPMENT_KO, METRIC_KO, TemplateGenerator, _fmt, _reference, build_query, cause_options, history_section,
)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT = 60.0

MANUAL_ID = re.compile(r"MAN-[A-Z]+(?:-[A-Z]+)*-\d+")

SYSTEM_PROMPT = """\
당신은 화장품·세제 공장의 설비 정비 지시서를 쓰는 보조자입니다. 현장 작업자가 바로 따라 할 수 있는 한국어 지시서를 씁니다.

규칙
- 제공된 근거(S 번호: 설비 매뉴얼 구절, H 번호: 작업자가 남긴 과거 조치 기록)에 있는 내용만 씁니다. 근거에 없는 수치·절차·부품을 지어내지 않습니다.
- 모든 항목의 sources 에 실제로 근거로 삼은 번호를 적습니다. 목록에 없는 번호는 쓰지 않습니다.
- 추정 원인의 cause 는 '원인 선택지'에 있는 이름을 글자 그대로 씁니다. 선택지에 없는 원인이 근거에 있을 때만 새 이름을 씁니다.
- 과거 조치 기록에 '해결'된 원인이 있으면 그 원인을 추정 원인 맨 앞에 두고, situation 에서 먼저 확인하라고 말합니다. 같은 유형의 다른 설비 기록은 참고로만 다룹니다.
- 즉시 조치는 현재 심각도에 맞는 매뉴얼 조치를 따릅니다. 안전 주의사항(잠금·표지 등)은 빠뜨리지 않으며, 안전장치를 우회하라는 지시는 절대 쓰지 않습니다.
- 문장은 짧은 명령형으로 씁니다 ("~한다", "~확인한다"). situation 은 2~3문장, summary 는 한 문장입니다.
"""

_ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "sources"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "situation": {"type": "string"},
        "causes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cause": {"type": "string"},
                    "reason": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["cause", "reason", "sources"],
                "additionalProperties": False,
            },
        },
        "inspection_steps": {"type": "array", "items": _ITEM},
        "immediate_actions": {"type": "array", "items": _ITEM},
        "safety": {"type": "array", "items": _ITEM},
        "escalation": {"type": "array", "items": _ITEM},
    },
    "required": ["summary", "situation", "causes", "inspection_steps", "immediate_actions", "safety", "escalation"],
    "additionalProperties": False,
}


class LlmOutputError(ValueError):
    """LLM 응답을 지시서로 쓸 수 없음 (형식 오류, 근거 누락, 거절 등)."""


@dataclass
class Source:
    id: str
    label: str  # 지시서에 보여 줄 짧은 근거 표시
    text: str


def collect_sources(manual: Manual, index: ManualIndex, hits: list[Hit], history: list[dict]) -> list[Source]:
    """근거 목록을 만든다: 주 매뉴얼 전체 → 주 매뉴얼이 언급한 매뉴얼 → 나머지 검색 청크 → 과거 조치."""
    seen: set[tuple[str, str]] = set()
    sources: list[Source] = []

    def add_section(m: Manual, section: str, body: str) -> None:
        if (m.id, section) in seen:
            return
        seen.add((m.id, section))
        label = section if m.id == manual.id else f"{m.id} · {section}"
        sources.append(Source(f"S{len(sources) + 1}", label, f"[{m.id} {m.title}] {section}\n{body}"))

    for section, body in manual.sections.items():
        add_section(manual, section, body)
    for ref_id in dict.fromkeys(MANUAL_ID.findall("\n".join(manual.sections.values()))):
        ref = index.manuals.get(ref_id)
        if ref and ref.id != manual.id:
            for section, body in ref.sections.items():
                add_section(ref, section, body)
    for h in hits:
        add_section(h.chunk.manual, h.chunk.section, h.chunk.manual.sections.get(h.chunk.section, ""))

    for i, h in enumerate(history, start=1):
        sources.append(Source(
            f"H{i}", f"과거 조치 WO-{h['id']}",
            f"{h.get('completedAt')} {h.get('equipmentId')} WO-{h['id']} ({h.get('severity')}) 결과 {h.get('outcome')}"
            f" / 원인: {h.get('rootCause') or '미확인'} / 조치: {h.get('actionTaken') or '-'}",
        ))
    return sources


def build_user_prompt(alarm: dict, manual: Manual, sources: list[Source], options: list[str]) -> str:
    unit = alarm.get("unit") or ""
    op = ">=" if alarm["direction"] == "HIGH" else "<="
    facts = "\n".join([
        f"- 설비: {alarm['equipmentId']} ({EQUIPMENT_KO.get(alarm['equipmentType'], alarm['equipmentType'])})",
        f"- 지표: {METRIC_KO.get(alarm['metric'], alarm['metric'])} ({alarm['metric']})",
        f"- 심각도: {alarm['severity']}",
        f"- 현재 {_fmt(alarm['lastValue'])}{unit}, 최악 {_fmt(alarm['peakValue'])}{unit},"
        f" 기준 {op} {_fmt(alarm['thresholdValue'])}{unit}",
        f"- 주 매뉴얼: {manual.id} {manual.title}",
    ])
    source_text = "\n\n".join(f"<{s.id}>\n{s.text}\n</{s.id}>" for s in sources)
    option_text = "\n".join(f"- {o}" for o in options) or "- (없음)"
    return (f"알람\n{facts}\n\n원인 선택지\n{option_text}\n\n근거\n{source_text}\n\n"
            f"위 알람에 대한 조치 지시서를 JSON 으로 작성하세요.")


def validate(data: dict, sources: list[Source]) -> None:
    valid = {s.id for s in sources}
    for key in ("causes", "inspection_steps", "immediate_actions", "safety"):
        if not data.get(key):
            raise LlmOutputError(f"'{key}' 항목이 비어 있습니다")
    for key in ("causes", "inspection_steps", "immediate_actions", "safety", "escalation"):
        for item in data.get(key, []):
            used = item.get("sources") or []
            if not used:
                raise LlmOutputError(f"'{key}' 항목에 근거가 없습니다: {item}")
            unknown = [u for u in used if u not in valid]
            if unknown:
                raise LlmOutputError(f"'{key}' 항목이 목록에 없는 근거를 인용했습니다: {unknown}")


def render_body(title: str, alarm: dict, manual: Manual, data: dict, sources: list[Source],
                history: list[dict], hits: list[Hit]) -> str:
    labels = {s.id: s.label for s in sources}

    def cite(ids: list[str]) -> str:
        return " *(근거: " + ", ".join(dict.fromkeys(labels[i] for i in ids)) + ")*"

    def bullets(items: list[dict], numbered: bool = False) -> list[str]:
        return [f"{f'{n}.' if numbered else '-'} {it['text']}{cite(it['sources'])}"
                for n, it in enumerate(items, start=1)]

    unit = alarm.get("unit") or ""
    op = ">=" if alarm["direction"] == "HIGH" else "<="
    eq_ko = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
    metric_ko = METRIC_KO.get(alarm["metric"], alarm["metric"])
    return "\n".join([
        f"# {title}",
        "",
        f"- 설비: {alarm['equipmentId']} ({eq_ko})",
        f"- 지표: {metric_ko} ({alarm['metric']})",
        f"- 심각도: {alarm['severity']}",
        f"- 발생값 {_fmt(alarm['triggerValue'])}{unit} → 현재 {_fmt(alarm['lastValue'])}{unit}"
        f" (최악 {_fmt(alarm['peakValue'])}{unit}), 기준 {op} {_fmt(alarm['thresholdValue'])}{unit}",
        f"- 최초 발생: {alarm['raisedAt']}",
        f"- 근거 매뉴얼: {manual.id} {manual.title}",
        "",
        *history_section(history, alarm["equipmentId"]),
        "## 상황 판단",
        data["situation"],
        "",
        "## 추정 원인",
        *[f"- **{c['cause']}** — {c['reason']}{cite(c['sources'])}" for c in data["causes"]],
        "",
        "## 점검 절차",
        *bullets(data["inspection_steps"], numbered=True),
        "",
        f"## 즉시 조치 ({alarm['severity']})",
        *bullets(data["immediate_actions"]),
        "",
        "## 안전 주의사항",
        *bullets(data["safety"]),
        "",
        "## 에스컬레이션",
        *(bullets(data["escalation"]) or ["- (근거 매뉴얼에 해당 항목 없음)"]),
        "",
        "## 참고 문서 (검색 결과)",
        *[f"- {h.chunk.manual.id} / {h.chunk.section} (score {h.score:.3f})" for h in hits],
    ])


class LlmGenerator:
    """Claude 로 지시서 문장을 쓴다. 근거 검증에 실패하면 LlmOutputError 를 던진다."""
    name = "llm"

    def __init__(self, client=None, model: str | None = None, effort: str | None = None,
                 timeout: float | None = None):
        if client is None:
            import anthropic  # 키가 없으면 이 생성기를 만들지 않으므로, 템플릿만 쓸 때는 SDK 가 없어도 된다
            client = anthropic.Anthropic(timeout=timeout or float(os.environ.get("LLM_TIMEOUT", DEFAULT_TIMEOUT)),
                                         max_retries=1)
        self.client = client
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("ANTHROPIC_EFFORT", DEFAULT_EFFORT)

    def generate(self, alarm: dict, index: ManualIndex, history: list[dict] | None = None) -> dict:
        history = history or []
        hits = index.search(build_query(alarm), alarm["equipmentType"], alarm["metric"], k=6)
        manual = index.best_manual(hits)
        if manual is None:
            raise LlmOutputError(f"관련 매뉴얼을 찾지 못했습니다: {build_query(alarm)}")

        options = cause_options(manual.sections.get("가능 원인", ""))
        sources = collect_sources(manual, index, hits, history)
        data = self._call(build_user_prompt(alarm, manual, sources, options))
        validate(data, sources)

        eq_ko = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
        metric_ko = METRIC_KO.get(alarm["metric"], alarm["metric"])
        title = f"[{alarm['severity']}] {alarm['equipmentId']} {eq_ko} {metric_ko} 이상 조치 지시"
        return {
            "title": title,
            "summary": data["summary"].strip()[:500],
            "body": render_body(title, alarm, manual, data, sources, history, hits),
            "generator": self.name,
            "references": [_reference(h) for h in hits],
            "causeOptions": options,
        }

    def _call(self, user_prompt: str) -> dict:
        return self.call_json(SYSTEM_PROMPT, user_prompt, OUTPUT_SCHEMA)

    def call_json(self, system: str, user_prompt: str, schema: dict) -> dict:
        """JSON 스키마로 고정한 응답을 받아 dict 로 돌려준다. 인수인계 리포트도 이 호출을 쓴다."""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            # 안전 분류기가 거절하면 서버가 다른 모델로 다시 돌린다 (그래도 거절이면 stop_reason 이 refusal)
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LlmOutputError(f"LLM 응답이 끝까지 오지 않았습니다 (stop_reason={response.stop_reason})")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LlmOutputError("LLM 응답에 텍스트가 없습니다")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LlmOutputError(f"LLM 응답이 JSON 이 아닙니다: {e}") from e


class FallbackGenerator:
    """먼저 LLM 으로 쓰고, 실패하면(키 오류·네트워크·근거 검증 실패) 템플릿으로 쓴다. 데모가 멈추지 않게."""

    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback or TemplateGenerator()
        self.name = primary.name

    def generate(self, alarm: dict, index: ManualIndex, history: list[dict] | None = None) -> dict:
        try:
            return self.primary.generate(alarm, index, history)
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 지시서는 나가야 한다
            print(f"[AGENT] {self.primary.name} generator failed, using template: {e!r}", file=sys.stderr)
            return self.fallback.generate(alarm, index, history)
