"""
품질 영향 에이전트.

배치 진행 중에 난 알람이면, 지시서 에이전트 다음에 이 에이전트가 "이 배치의 품질에 영향이 있는가"를 판정한다.

- 판정은 규칙(아래 CRITERIA 표)으로 한다: 같은 상황이면 늘 같은 판정이 나와야 품질 판정을 믿을 수 있다.
    NO_IMPACT 영향 없음 / INSPECT 추가 검사 필요 / HOLD 배치 홀드 · 출하 보류 권고
- LLM 은 판정 이유 설명만 쓴다. 판정 근거(Q1 품질 기준, Q2 알람, Q3 지시서)에 번호를 붙여 주고,
  설명이 근거 번호를 달지 않거나 판정을 바꿔 말하면 버리고 템플릿 설명을 쓴다.
- HOLD 는 백엔드에서 '품질팀 승인 대기'로 저장되고, 품질팀이 대시보드에서 승인해야 확정된다.

CRITERIA 는 데모용 가상 기준이다. 실제 공장에서는 품질팀의 핵심 공정 변수(CPP) 목록과 허용 범위로 바꿔야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .work_order import EQUIPMENT_KO, METRIC_KO, PHASE_KO, SEVERITY_KO

NO_IMPACT, INSPECT, HOLD = "NO_IMPACT", "INSPECT", "HOLD"
LEVEL_KO = {NO_IMPACT: "영향 없음", INSPECT: "추가 검사 필요", HOLD: "배치 홀드 · 출하 보류 권고"}
ACTION_KO = {
    NO_IMPACT: "품질 조치는 필요 없습니다. 설비 조치만 진행합니다.",
    INSPECT: "배치가 끝나면 이 배치 샘플의 추가 검사(점도 · 외관 · 상 분리)를 품질팀에 요청합니다.",
    HOLD: "배치를 다음 단계로 넘기지 말고 멈춥니다. 품질팀이 승인하면 출하를 보류하고, 검사 결과로 재작업 · 폐기를 정합니다.",
}
NO_BATCH = {None, "", "IDLE"}


@dataclass(frozen=True)
class Criterion:
    """품질 기준 한 줄: 이 설비 · 지표 · 단계에서 알람이 나면 심각도별로 어떤 판정을 내리나."""
    equipment_type: str
    metric: str
    phases: tuple[str, ...]
    name: str           # 품질 관점의 이름 (예: 유화 온도)
    why: str            # 품질에 어떤 영향을 주나
    on_warning: str
    on_critical: str


CRITERIA = [
    Criterion("MIXER", "temperature", ("EMULSIFYING",), "유화 온도",
              "유화 온도는 유화 안정성(상 분리)과 점도를 정하는 핵심 공정 변수다", INSPECT, HOLD),
    Criterion("MIXER", "temperature", ("HEATING", "COOLING"), "가열 · 냉각 온도",
              "가열 · 냉각 중 과열은 원료 열변성과 향 손실을 일으킬 수 있다", INSPECT, HOLD),
    Criterion("MIXER", "vibration", ("CHARGING", "HEATING", "EMULSIFYING", "COOLING"), "교반 상태",
              "교반이 불안정하면 균질도와 입자 크기에 영향을 줄 수 있다", NO_IMPACT, INSPECT),
    Criterion("MIXER", "current", ("CHARGING", "HEATING", "EMULSIFYING", "COOLING"), "교반 부하",
              "교반 부하 이상은 점도 이상이나 교반 부족의 신호일 수 있다", NO_IMPACT, INSPECT),
    Criterion("RAW_TANK", "level", ("CHARGING",), "원료 투입량",
              "원료 투입 중 원료가 모자라면 배합비가 틀어진다", INSPECT, HOLD),
]


def find_criterion(alarm: dict) -> Criterion | None:
    phase = alarm.get("batchPhase")
    return next((c for c in CRITERIA if c.equipment_type == alarm["equipmentType"] and c.metric == alarm["metric"]
                 and phase in c.phases), None)


def in_batch(alarm: dict) -> bool:
    return alarm.get("batchPhase") not in NO_BATCH


@dataclass
class Judgement:
    level: str
    basis: str                   # 규칙 판정 근거 한 줄 (백엔드에 그대로 저장)
    criterion: Criterion | None


def judge(alarm: dict) -> Judgement:
    """규칙 판정. 배치 중이 아닌 알람에는 부르지 않는다."""
    phase_ko = PHASE_KO.get(alarm.get("batchPhase"), alarm.get("batchPhase"))
    metric_ko = METRIC_KO.get(alarm["metric"], alarm["metric"])
    severity = alarm["severity"]
    c = find_criterion(alarm)
    if c is None:
        return Judgement(NO_IMPACT, f"{phase_ko} 단계 {metric_ko}: 품질 기준표의 핵심 공정 변수가 아님", None)
    level = c.on_critical if severity == "CRITICAL" else c.on_warning
    return Judgement(level, f"{phase_ko} 단계 {c.name} {SEVERITY_KO.get(severity, severity)} 이탈 → "
                            f"{LEVEL_KO[level]} (품질 기준: {c.name})", c)


def _fmt(v) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)


def sources(alarm: dict, work_order: dict | None, j: Judgement) -> dict[str, str]:
    """LLM 에 줄 근거 목록 (번호 → 내용). 템플릿 설명도 같은 사실을 쓴다."""
    unit = alarm.get("unit") or ""
    op = "이상" if alarm["direction"] == "HIGH" else "이하"
    facts = {
        "Q1": (f"품질 기준 '{j.criterion.name}': {j.criterion.why}. 경고면 {LEVEL_KO[j.criterion.on_warning]},"
               f" 위험이면 {LEVEL_KO[j.criterion.on_critical]}.") if j.criterion
        else "품질 기준표: 이 단계 · 지표는 품질 핵심 공정 변수 목록에 없다.",
        "Q2": (f"알람: {alarm['equipmentId']} {METRIC_KO.get(alarm['metric'], alarm['metric'])}"
               f" {_fmt(alarm.get('lastValue'))}{unit} (기준 {_fmt(alarm.get('thresholdValue'))}{unit} {op},"
               f" 최악 {_fmt(alarm.get('peakValue'))}{unit}), 심각도 {alarm['severity']},"
               f" 배치 {alarm.get('batchId') or '-'} {PHASE_KO.get(alarm.get('batchPhase'), alarm.get('batchPhase'))} 단계."),
    }
    if work_order:
        facts["Q3"] = f"설비 조치 지시서 요약: {work_order.get('summary', '')}"
    return facts


def template_reason(alarm: dict, j: Judgement) -> str:
    phase_ko = PHASE_KO.get(alarm.get("batchPhase"), alarm.get("batchPhase"))
    why = j.criterion.why if j.criterion else "이 단계 · 지표는 품질 핵심 공정 변수가 아니다"
    return (f"{phase_ko} 단계 중 {METRIC_KO.get(alarm['metric'], alarm['metric'])} {alarm['severity']} 알람."
            f" {why}. 판정: {LEVEL_KO[j.level]}. {ACTION_KO[j.level]}")


SYSTEM = """당신은 화장품 · 세제 배치 공장의 품질 담당 보조입니다.
품질 판정은 이미 규칙으로 정해졌습니다. 당신은 그 판정의 이유를 품질팀이 읽을 2~4문장으로 설명합니다.
- 판정을 바꾸거나 다른 판정을 권하지 않습니다.
- 주어진 근거(Q1, Q2, Q3)에 있는 사실만 쓰고, 쓴 근거 번호를 refs 에 넣습니다. 본문에는 [Q1] 같은 표시를 넣지 않습니다.
- 수치는 근거에 있는 값만 씁니다.
- 권고 조치 문장은 뒤에 따로 붙으므로 쓰지 않습니다. 왜 이 판정인지만 씁니다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "description": "판정 이유 2~4문장"},
        "refs": {"type": "array", "items": {"type": "string"}, "description": "쓴 근거 번호 (Q1 등)"},
    },
    "required": ["reason", "refs"],
    "additionalProperties": False,
}

_OTHER_LEVEL = {lvl: [LEVEL_KO[o] for o in LEVEL_KO if o != lvl] for lvl in LEVEL_KO}


class QualityExplainError(ValueError):
    pass


def llm_reason(llm, alarm: dict, work_order: dict | None, j: Judgement) -> str:
    facts = sources(alarm, work_order, j)
    prompt = "\n".join([
        f"판정: {LEVEL_KO[j.level]} ({j.level})",
        f"판정 근거 규칙: {j.basis}",
        f"권고 조치: {ACTION_KO[j.level]}",
        "",
        "근거",
        *[f"[{k}] {v}" for k, v in facts.items()],
    ])
    data = llm.call_json(SYSTEM, prompt, SCHEMA)
    reason = re.sub(r"\s*\[Q\d+\]", "", data.get("reason") or "").strip()
    refs = data.get("refs") or []
    if not reason or not refs:
        raise QualityExplainError("설명이나 근거 번호가 비어 있습니다")
    unknown = [r for r in refs if r not in facts]
    if unknown:
        raise QualityExplainError(f"목록에 없는 근거 번호: {unknown}")
    if any(other in reason for other in _OTHER_LEVEL[j.level]):
        raise QualityExplainError("설명이 규칙 판정과 다른 판정을 말합니다")
    cited = ", ".join(dict.fromkeys(re.sub(r"[^Q0-9]", "", r) for r in refs))
    return f"{reason[:900]} (근거: {cited}) {ACTION_KO[j.level]}"


class QualityAgent:
    """배치 진행 중 알람의 품질 영향을 판정한다. llm 이 있으면 이유 설명을 Claude 가, 없거나 실패하면 템플릿이 쓴다."""

    def __init__(self, llm=None):
        self.llm = llm

    def assess(self, alarm: dict, work_order: dict | None) -> dict | None:
        """배치 중이 아니면 None. 판정은 {'level','basis','reason','generator'} (백엔드 저장 형식)."""
        if not in_batch(alarm):
            return None
        j = judge(alarm)
        generator, reason = "template", None
        if self.llm is not None:
            try:
                reason = llm_reason(self.llm, alarm, work_order, j)
                generator = "llm"
            except Exception as e:  # noqa: BLE001 - 설명이 실패해도 규칙 판정은 그대로 낸다
                print(f"[QUALITY] llm explanation failed, using template: {e!r}")
        return {"level": j.level, "basis": j.basis, "reason": reason or template_reason(alarm, j),
                "generator": generator}
