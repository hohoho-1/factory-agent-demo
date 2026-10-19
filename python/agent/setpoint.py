"""
권장 설정값 변경 (승인형 제어).

설비가 원격 설정값(PLC SP 태그)을 제공하고 그 현재값을 알 때만, 지시서에 설정값 변경 1건을 붙인다.
- 템플릿: 매뉴얼의 현재 심각도 조치 문장에서 규칙으로 뽑는다 ("회전수를 10~20% 낮추고" → 15% 하향,
  "설정값을 기준값으로 재입력" → 기준값).
- LLM: Claude 가 근거 번호를 달아 제안한다.
어느 쪽이든 운전 범위 · 한 번 변경폭 · 근거를 검증하고, 통과하지 못하면 제안 없이 지시서만 낸다.
작업자가 대시보드에서 승인해야 설비에 내려가고, 마지막으로 PLC 인터록이 다시 검사한다.

setpoints 는 백엔드 GET /api/setpoints?equipmentId= 응답:
  [{"equipmentId","tag","label","unit","min","max","maxStep","nominal","currentValue"}]
"""
from __future__ import annotations

import math
import re

# 템플릿 규칙: 설정값 태그 → 매뉴얼 조치 문장에서 찾을 패턴
_PERCENT_DOWN = re.compile(r"회전수를\s*(\d+)\s*~\s*(\d+)\s*%\s*낮추")
_RESTORE_NOMINAL = re.compile(r"설정값을\s*기준값으로")

ACTION_SECTION = {"WARNING": "조치 - 경고(WARNING)", "CRITICAL": "조치 - 위험(CRITICAL)"}


class SetpointProposalError(ValueError):
    """제안을 쓸 수 없음 (범위 밖, 근거 없음 등). 지시서는 제안 없이 낸다."""


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def available(setpoints: list[dict] | None, equipment_id: str) -> list[dict]:
    """현재값을 아는(게이트웨이가 연결된) 같은 설비의 설정값만."""
    return [s for s in setpoints or [] if s.get("equipmentId") == equipment_id and s.get("currentValue") is not None]


def check(setpoint: dict, proposed: float) -> None:
    """백엔드 운전 범위와 같은 검사. 통과하지 못하면 SetpointProposalError."""
    current, unit = setpoint["currentValue"], setpoint.get("unit") or ""
    if not isinstance(proposed, (int, float)) or not math.isfinite(proposed):
        raise SetpointProposalError(f"제안값이 숫자가 아닙니다: {proposed!r}")
    if not setpoint["min"] <= proposed <= setpoint["max"]:
        raise SetpointProposalError(f"{setpoint['label']} 운전 범위 {_fmt(setpoint['min'])}~{_fmt(setpoint['max'])}"
                                    f"{unit} 밖입니다 ({_fmt(proposed)})")
    if abs(proposed - current) < 1e-9:
        raise SetpointProposalError(f"현재값과 같습니다 ({_fmt(current)})")
    if abs(proposed - current) > setpoint["maxStep"] + 1e-9:
        raise SetpointProposalError(f"한 번에 {_fmt(setpoint['maxStep'])}{unit} 넘게 바꾸는 제안입니다"
                                    f" ({_fmt(current)} → {_fmt(proposed)})")


def proposal(setpoint: dict, proposed: float, reason: str, sources: str) -> dict:
    return {
        "tag": setpoint["tag"],
        "label": setpoint["label"],
        "unit": setpoint.get("unit"),
        "currentValue": setpoint["currentValue"],
        "proposedValue": round(float(proposed), 1),
        "reason": reason.strip(),
        "sources": sources,
    }


def template_proposal(alarm: dict, manual, setpoints: list[dict] | None) -> dict | None:
    """매뉴얼의 현재 심각도 조치 문장에 설정값 조정이 있으면 규칙으로 제안을 만든다. 없으면 None."""
    section = ACTION_SECTION.get(alarm["severity"])
    text = manual.sections.get(section, "") if section else ""
    for sp in available(setpoints, alarm["equipmentId"]):
        current = sp["currentValue"]
        for line in text.splitlines():
            line = line.lstrip("- ").strip()
            if sp["tag"] == "speed_sp" and (m := _PERCENT_DOWN.search(line)):
                pct = (int(m.group(1)) + int(m.group(2))) / 2  # 범위의 가운데 (10~20% → 15%)
                proposed = round(current * (1 - pct / 100))
            elif sp["tag"] == "temp_sp" and _RESTORE_NOMINAL.search(line) and current > sp["nominal"]:
                proposed = sp["nominal"]
            else:
                continue
            try:
                check(sp, proposed)
            except SetpointProposalError:
                continue
            return proposal(sp, proposed, f"매뉴얼 조치: {line}", f"{manual.id} {section}")
    return None


def prompt_section(setpoints: list[dict]) -> str:
    """LLM 프롬프트에 넣을 '조정 가능한 설정값' 목록."""
    if not setpoints:
        return "조정 가능한 설정값\n- (없음: setpoint_changes 는 빈 배열로 둡니다)"
    lines = [f"- {s['tag']} ({s['label']}): 현재 {_fmt(s['currentValue'])}{s.get('unit') or ''},"
             f" 운전 범위 {_fmt(s['min'])}~{_fmt(s['max'])}, 한 번에 최대 {_fmt(s['maxStep'])} 변경,"
             f" 평소 기준값 {_fmt(s['nominal'])}" for s in setpoints]
    return "조정 가능한 설정값 (작업자가 승인해야 설비에 반영됨)\n" + "\n".join(lines)


def from_llm(items: list[dict], setpoints: list[dict], labels: dict[str, str]) -> dict | None:
    """LLM 의 setpoint_changes 중 첫 건을 검증해 제안으로 만든다. 검증에 실패하면 SetpointProposalError."""
    if not items:
        return None
    item = items[0]
    sp = next((s for s in setpoints if s["tag"] == item.get("tag")), None)
    if sp is None:
        raise SetpointProposalError(f"조정 가능한 설정값이 아닙니다: {item.get('tag')!r}")
    used = item.get("sources") or []
    if not used:
        raise SetpointProposalError("설정값 제안에 근거가 없습니다")
    unknown = [u for u in used if u not in labels]
    if unknown:
        raise SetpointProposalError(f"설정값 제안이 목록에 없는 근거를 인용했습니다: {unknown}")
    proposed = item.get("proposed_value")
    check(sp, proposed)
    return proposal(sp, proposed, item.get("reason") or "",
                    ", ".join(dict.fromkeys(labels[u] for u in used)))
