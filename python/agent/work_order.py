"""
알람 + 검색된 매뉴얼 → 조치 지시서.

TemplateGenerator 는 LLM 없이 매뉴얼 섹션을 골라 조립한다 (심각도에 맞는 조치 섹션 선택).
LLM 을 붙일 때는 같은 generate(alarm, index) 인터페이스로 생성기만 추가하면 된다.
"""
from __future__ import annotations

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


def build_query(alarm: dict) -> str:
    eq = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
    metric = METRIC_KO.get(alarm["metric"], alarm["metric"])
    symptom = SYMPTOM_KEYWORDS.get((alarm["metric"], alarm["direction"]), "")
    return f"{eq} {metric} {symptom} 원인 점검 조치"


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


class TemplateGenerator:
    name = "template"

    def generate(self, alarm: dict, index: ManualIndex) -> dict:
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
        }


def _reference(h: Hit) -> dict:
    return {
        "manualId": h.chunk.manual.id,
        "title": h.chunk.manual.title,
        "section": h.chunk.section,
        "score": round(h.score, 4),
    }
