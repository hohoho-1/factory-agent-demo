"""
알람 + 검색된 매뉴얼 → 조치 지시서.

TemplateGenerator 는 LLM 없이 매뉴얼 섹션을 골라 조립한다 (심각도에 맞는 조치 섹션 선택).
같은 설비·지표에서 작업자가 조치를 마친 기록(history)이 있으면 '과거 유사 조치 이력'으로 앞쪽에 넣는다.
LLM 을 붙일 때는 같은 generate(alarm, index, history) 인터페이스로 생성기만 추가하면 된다.
"""
from __future__ import annotations

import re
from datetime import datetime

from .rag import Hit, ManualIndex

EQUIPMENT_KO = {"RAW_TANK": "원료 탱크", "MIXER": "배합기", "FILLER": "충진기"}
METRIC_KO = {"temperature": "온도", "level": "레벨", "vibration": "진동", "current": "전류", "speed": "속도"}

# 검색 질의 확장: 지표·방향을 현장 용어로 풀어 쓴다
SYMPTOM_KEYWORDS = {
    ("temperature", "HIGH"): "온도 상승 과열 스팀 가열",
    ("level", "LOW"): "레벨 저하 원료 부족 보충 누출",
    ("vibration", "HIGH"): "진동 상승 베어링 불균형 소음",
    ("current", "HIGH"): "과전류 전류 상승 모터 부하 점도",
    ("speed", "LOW"): "속도 저하 충진 정체 노즐 막힘",
}

ACTION_SECTION = {"WARNING": "조치 - 경고(WARNING)", "CRITICAL": "조치 - 위험(CRITICAL)"}

SEVERITY_KO = {"WARNING": "경고", "CRITICAL": "위험"}
OUTCOME_KO = {"RESOLVED": "해결", "PARTIAL": "부분 해결", "UNRESOLVED": "미해결"}


def build_query(alarm: dict) -> str:
    eq = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
    metric = METRIC_KO.get(alarm["metric"], alarm["metric"])
    symptom = SYMPTOM_KEYWORDS.get((alarm["metric"], alarm["direction"]), "")
    return f"{eq} {metric} {symptom} 원인 점검 조치"


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _local_time(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone().strftime("%m/%d %H:%M")


def cause_options(cause_section: str) -> list[str]:
    """매뉴얼 '가능 원인' 목록을 작업자가 고를 짧은 이름으로: ':' 뒤 설명과 괄호 설명은 뺀다."""
    options = []
    for line in cause_section.splitlines():
        if not line.startswith("- "):
            continue
        label = re.sub(r"\s*\([^)]*\)", "", line[2:].split(":")[0]).strip()
        if label and label not in options:
            options.append(label)
    return options


def _history_line(h: dict, show_equipment: bool) -> str:
    where = f"{h['equipmentId']} · " if show_equipment else ""
    return (f"- {_local_time(h.get('completedAt'))} · {where}WO-{h['id']}"
            f" ({SEVERITY_KO.get(h['severity'], h['severity'])})"
            f" · **{OUTCOME_KO.get(h.get('outcome'), h.get('outcome') or '-')}** · {h.get('worker') or '-'}"
            f" — 원인: {h.get('rootCause') or '미확인'} / 조치: {h.get('actionTaken') or '-'}")


def _first_resolved(history: list[dict]) -> dict | None:
    return next((h for h in history if h.get("outcome") == "RESOLVED" and h.get("rootCause")), None)


def history_section(history: list[dict], equipment_id: str | None = None) -> list[str]:
    """
    작업자가 남긴 조치 결과를 지시서 앞쪽에 붙일 마크다운 줄로 만든다. 이력이 없으면 빈 목록.
    equipment_id 를 주면 같은 설비 기록과 같은 유형 다른 설비 기록을 나눠 보여 준다.
    """
    if not history:
        return []
    same = [h for h in history if equipment_id is None or h.get("equipmentId", equipment_id) == equipment_id]
    others = [h for h in history if h not in same]

    counts = " · ".join(part for part in (
        f"같은 설비 {len(same)}건" if same else "",
        f"같은 유형 다른 설비 {len(others)}건" if others else "",
    ) if part)
    lines = [
        f"## 과거 유사 조치 이력 ({counts})",
        "작업자가 조치를 마친 기록입니다. 매뉴얼 절차와 함께 참고하세요.",
        "",
    ]
    resolved = _first_resolved(same)
    if resolved:
        lines += [f"> **우선 확인**: 지난번 해결된 원인 '{resolved['rootCause']}'"
                  f" (WO-{resolved['id']}, {_local_time(resolved.get('completedAt'))})", ""]
    elif (other := _first_resolved(others)) is not None:
        lines += [f"> **참고**: 같은 유형 설비 {other['equipmentId']}에서 해결된 원인 '{other['rootCause']}'"
                  f" (WO-{other['id']}, {_local_time(other.get('completedAt'))})", ""]

    if others:
        if same:
            lines += [f"**같은 설비 ({equipment_id})**", *[_history_line(h, False) for h in same], ""]
        lines += ["**같은 유형 다른 설비**", *[_history_line(h, True) for h in others]]
    else:
        lines += [_history_line(h, False) for h in same]
    lines.append("")
    return lines


class TemplateGenerator:
    name = "template"

    def generate(self, alarm: dict, index: ManualIndex, history: list[dict] | None = None) -> dict:
        history = history or []
        query = build_query(alarm)
        hits = index.search(query, alarm["equipmentType"], alarm["metric"], k=6)
        manual = index.best_manual(hits)
        if manual is None:
            raise RuntimeError(f"관련 매뉴얼을 찾지 못했습니다: {query}")

        eq_ko = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
        metric_ko = METRIC_KO.get(alarm["metric"], alarm["metric"])
        unit = alarm.get("unit") or ""
        severity = alarm["severity"]
        op = ">=" if alarm["direction"] == "HIGH" else "<="
        action_key = ACTION_SECTION.get(severity, ACTION_SECTION["WARNING"])

        def section(name: str) -> str:
            return manual.sections.get(name, "- (매뉴얼에 해당 항목 없음)")

        title = f"[{severity}] {alarm['equipmentId']} {eq_ko} {metric_ko} 이상 조치 지시"
        summary = (f"{alarm['equipmentId']}({eq_ko}) {metric_ko} {_fmt(alarm['lastValue'])}{unit}, "
                   f"기준 {op} {_fmt(alarm['thresholdValue'])}{unit} ({severity}). "
                   f"{manual.id} 기준으로 조치 바랍니다.")
        if history:
            summary += f" 과거 유사 조치 {len(history)}건 참고."

        body = "\n".join([
            f"# {title}",
            "",
            f"- 설비: {alarm['equipmentId']} ({eq_ko})",
            f"- 지표: {metric_ko} ({alarm['metric']})",
            f"- 심각도: {severity}",
            f"- 발생값 {_fmt(alarm['triggerValue'])}{unit} → 현재 {_fmt(alarm['lastValue'])}{unit}"
            f" (최악 {_fmt(alarm['peakValue'])}{unit}), 기준 {op} {_fmt(alarm['thresholdValue'])}{unit}",
            f"- 최초 발생: {alarm['raisedAt']}",
            f"- 근거 매뉴얼: {manual.id} {manual.title}",
            "",
            *history_section(history, alarm["equipmentId"]),
            "## 추정 원인",
            section("가능 원인"),
            "",
            "## 점검 절차",
            section("점검 절차"),
            "",
            f"## 즉시 조치 ({severity})",
            section(action_key),
            "",
            "## 안전 주의사항",
            section("안전 주의사항"),
            "",
            "## 에스컬레이션",
            section("에스컬레이션 기준"),
            "",
            "## 참고 문서 (검색 결과)",
            *[f"- {h.chunk.manual.id} / {h.chunk.section} (score {h.score:.3f})" for h in hits],
        ])

        return {
            "title": title,
            "summary": summary,
            "body": body,
            "generator": self.name,
            "references": [_reference(h) for h in hits],
            "causeOptions": cause_options(manual.sections.get("가능 원인", "")),
        }


def _reference(h: Hit) -> dict:
    return {
        "manualId": h.chunk.manual.id,
        "title": h.chunk.manual.title,
        "section": h.chunk.section,
        "score": round(h.score, 4),
    }
