"""
교대 인수인계 리포트.

백엔드가 준 시간대 재료(알람, 지시서 요약)로 다음 교대가 읽을 리포트를 쓴다.
- 숫자(알람 몇 건, 남은 지시서 몇 건)는 코드가 직접 센다. LLM 이 숫자를 지어내지 않게.
- LLM 은 알람(A12)·지시서(W34) 번호를 근거로 문장만 쓰고, 모든 항목에 번호를 단다. 번호 검증에 실패하면 템플릿으로 쓴다.
- 재료가 비어 있으면 LLM 을 부르지 않는다 ("특이사항 없음").
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime

from .llm import LlmOutputError
from .work_order import EQUIPMENT_KO, METRIC_KO, OUTCOME_KO, SEVERITY_KO, _fmt

OPEN_STATUSES = {"OPEN", "ACKNOWLEDGED"}
STATUS_KO = {"OPEN": "미확인", "ACKNOWLEDGED": "조치 중", "COMPLETED": "완료", "SUPERSEDED": "함께 처리"}

SYSTEM_PROMPT = """\
당신은 화장품·세제 공장 생산 라인의 교대 인수인계서를 쓰는 보조자입니다. 다음 교대 작업자와 설비 담당자가 3분 안에 읽고 상황을 파악하게 합니다.

규칙
- 제공된 알람(A 번호)과 조치 지시서(W 번호)에 있는 사실만 씁니다. 수치·원인·작업자 이름을 지어내지 않습니다.
- 모든 항목의 refs 에 근거가 된 번호를 적습니다. 목록에 없는 번호는 쓰지 않습니다.
- events: 시간대에 있었던 주요 이상과 그 조치 결과를 설비별로 묶어 씁니다. 같은 알람의 경고·위험 지시서는 한 항목으로 씁니다.
- open_items: 다음 교대가 이어서 해야 할 일만 씁니다 (아직 확인 안 된 지시서, 조치 중인 지시서, 진행 중인 알람, 미해결·부분 해결로 끝난 조치). 없으면 빈 목록입니다.
- watch: 반복해서 이상이 난 설비나, 원인이 확인되지 않은 이상처럼 주의해서 볼 점만 씁니다. 없으면 빈 목록입니다.
- headline 은 한 문장, overview 는 2~3문장입니다. 문장은 짧게, "~했다 / ~필요하다" 체로 씁니다.
"""

_ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "refs"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "overview": {"type": "string"},
        "events": {"type": "array", "items": _ITEM},
        "open_items": {"type": "array", "items": _ITEM},
        "watch": {"type": "array", "items": _ITEM},
    },
    "required": ["headline", "overview", "events", "open_items", "watch"],
    "additionalProperties": False,
}


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso).astimezone() if iso else None


def _hm(iso: str | None) -> str:
    d = _dt(iso)
    return d.strftime("%H:%M") if d else "-"


def _duration(a: dict) -> str:
    start, end = _dt(a.get("raisedAt")), _dt(a.get("clearedAt"))
    if not start or not end:
        return "진행 중"
    s = int((end - start).total_seconds())
    return f"{s}초" if s < 60 else f"{s // 60}분 {s % 60}초"


def _where(a: dict) -> str:
    eq = EQUIPMENT_KO.get(a.get("equipmentType"), a.get("equipmentType") or "")
    return f"{eq}({a['equipmentId']}) {METRIC_KO.get(a['metric'], a['metric'])}"


class Facts:
    """재료를 읽기 좋게 정리하고 숫자를 센다."""

    def __init__(self, ctx: dict):
        self.ctx = ctx
        self.alarms: list[dict] = ctx.get("alarms") or []
        self.work_orders: list[dict] = ctx.get("workOrders") or []
        self.alarm_by_id = {a["id"]: a for a in self.alarms}
        self.wos_by_alarm: dict[int, list[dict]] = {}
        for w in self.work_orders:
            self.wos_by_alarm.setdefault(w["alarmId"], []).append(w)
        self.open_wos = [w for w in self.work_orders if w["status"] in OPEN_STATUSES]
        self.active_alarms = [a for a in self.alarms if a["status"] == "ACTIVE"]
        self.completed = [w for w in self.work_orders if w["status"] == "COMPLETED"]
        self.repeats = Counter((a["equipmentId"], a["metric"]) for a in self.alarms)

    @property
    def empty(self) -> bool:
        return not self.alarms and not self.work_orders

    def ref_ids(self) -> set[str]:
        return {f"A{a['id']}" for a in self.alarms} | {f"W{w['id']}" for w in self.work_orders}

    def stats_line(self) -> str:
        critical = sum(1 for a in self.alarms if a["severity"] == "CRITICAL")
        resolved = sum(1 for w in self.completed if w.get("outcome") == "RESOLVED")
        return (f"알람 {len(self.alarms)}건 (위험 {critical}건, 진행 중 {len(self.active_alarms)}건) · "
                f"조치 완료 {len(self.completed)}건 (해결 {resolved}건) · 남은 지시서 {len(self.open_wos)}건")

    def wo_line(self, w: dict) -> str:
        status = STATUS_KO.get(w["status"], w["status"])
        if w["status"] == "COMPLETED":
            status += f"({OUTCOME_KO.get(w.get('outcome'), w.get('outcome') or '-')})"
        if w["status"] == "SUPERSEDED" and w.get("supersededBy"):
            status += f"(W{w['supersededBy']} 로)"
        parts = [f"W{w['id']}", f"알람 A{w['alarmId']}", SEVERITY_KO.get(w["severity"], w["severity"]), status]
        if w.get("worker"):
            parts.append(f"작업자 {w['worker']}")
        if w.get("rootCause"):
            parts.append(f"원인 {w['rootCause']}")
        if w.get("actionTaken"):
            parts.append(f"조치 {w['actionTaken']}")
        parts.append(f"작성 {_hm(w.get('createdAt'))}")
        if w.get("completedAt"):
            parts.append(f"완료 {_hm(w['completedAt'])}")
        return " | ".join(parts)

    def alarm_line(self, a: dict) -> str:
        unit = a.get("unit") or ""
        op = "≥" if a["direction"] == "HIGH" else "≤"
        return " | ".join([
            f"A{a['id']}", _where(a), SEVERITY_KO.get(a["severity"], a["severity"]),
            f"발생 {_hm(a['raisedAt'])}", f"최악 {_fmt(a['peakValue'])}{unit} (기준 {op} {_fmt(a['thresholdValue'])})",
            "진행 중" if a["status"] == "ACTIVE" else f"해제 {_hm(a.get('clearedAt'))} (지속 {_duration(a)})",
        ])


def report_title(ctx: dict) -> str:
    start, end = _dt(ctx["from"]), _dt(ctx["to"])
    return f"교대 인수인계 {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%H:%M')}"


def template_report(ctx: dict) -> dict:
    """LLM 없이 쓰는 인수인계서. 키가 없거나 LLM 이 실패했을 때."""
    f = Facts(ctx)
    lines = [f"# {report_title(ctx)}", "", f"- {f.stats_line()}", ""]
    if f.empty:
        lines += ["## 요약", "이 시간대에는 알람과 조치 지시서가 없었다. 특이사항 없음.", ""]
        return {"title": report_title(ctx), "body": "\n".join(lines), "generator": "template"}

    lines += ["## 주요 이상과 조치"]
    for a in f.alarms:
        done = [w for w in f.wos_by_alarm.get(a["id"], []) if w["status"] == "COMPLETED"]
        action = "; ".join(f"원인 {w.get('rootCause') or '미확인'} / 조치 {w.get('actionTaken')}"
                           f" ({OUTCOME_KO.get(w.get('outcome'), '-')}, {w.get('worker') or '-'})" for w in done)
        lines.append(f"- {_hm(a['raisedAt'])} {_where(a)} {SEVERITY_KO.get(a['severity'], a['severity'])} — "
                     f"최악 {_fmt(a['peakValue'])}{a.get('unit') or ''}, "
                     f"{'진행 중' if a['status'] == 'ACTIVE' else _duration(a) + ' 뒤 해제'}. "
                     f"{'조치: ' + action if action else '조치 기록 없음'} *(알람 #{a['id']})*")
    lines += ["", "## 다음 교대가 이어서 할 일"]
    todo = [f"- WO-{w['id']} {STATUS_KO[w['status']]}"
            f"{' (' + w['worker'] + ')' if w.get('worker') else ''} — 알람 #{w['alarmId']} "
            f"{_where(f.alarm_by_id[w['alarmId']]) if w['alarmId'] in f.alarm_by_id else w['equipmentId']}"
            for w in f.open_wos]
    todo += [f"- 알람 #{a['id']} {_where(a)} 아직 진행 중" for a in f.active_alarms]
    lines += todo or ["- 없음"]
    lines += ["", "## 주의해서 볼 설비"]
    watch = []
    for (eq, metric), n in f.repeats.items():
        if n >= 2:
            causes = Counter(w["rootCause"] for w in f.completed
                             if w["equipmentId"] == eq and w["metric"] == metric and w.get("rootCause"))
            top = f" (주요 원인: {causes.most_common(1)[0][0]})" if causes else ""
            sample = next(a for a in f.alarms if a["equipmentId"] == eq and a["metric"] == metric)
            watch.append(f"- {_where(sample)}: 이 시간대에 {n}회 발생{top}")
    lines += watch or ["- 반복된 이상 없음"]
    lines.append("")
    return {"title": report_title(ctx), "body": "\n".join(lines), "generator": "template"}


def build_user_prompt(ctx: dict, f: Facts) -> str:
    alarms = "\n".join(f.alarm_line(a) for a in f.alarms) or "(없음)"
    wos = "\n".join(f.wo_line(w) for w in f.work_orders) or "(없음)"
    return (f"시간대: {report_title(ctx)}\n집계: {f.stats_line()}\n\n알람\n{alarms}\n\n조치 지시서\n{wos}\n\n"
            f"위 내용으로 교대 인수인계서를 JSON 으로 작성하세요.")


def validate(data: dict, f: Facts) -> None:
    valid = f.ref_ids()
    if f.alarms and not data.get("events"):
        raise LlmOutputError("알람이 있는데 events 가 비어 있습니다")
    for key in ("events", "open_items", "watch"):
        for item in data.get(key, []):
            refs = item.get("refs") or []
            if not refs:
                raise LlmOutputError(f"'{key}' 항목에 근거 번호가 없습니다: {item}")
            unknown = [r for r in refs if r not in valid]
            if unknown:
                raise LlmOutputError(f"'{key}' 항목이 목록에 없는 번호를 인용했습니다: {unknown}")


# 한국어 조사가 바로 붙으므로(W12가) \b 대신 영문·숫자 경계로 본다. TANK-02 같은 설비 ID 는 건드리지 않는다
_REF_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_-])([AW])(\d+)(?![0-9])")


def readable(text: str) -> str:
    """문장 속 내부 번호(A12, W34)를 화면 표기(알람 #12, WO-34)로 바꾼다."""
    return _REF_IN_TEXT.sub(lambda m: f"알람 #{m.group(2)}" if m.group(1) == "A" else f"WO-{m.group(2)}", text.strip())


def render(ctx: dict, f: Facts, data: dict) -> str:
    def label(ref: str) -> str:
        return readable(ref)

    def bullets(items: list[dict], empty: str) -> list[str]:
        if not items:
            return [f"- {empty}"]
        return [f"- {readable(it['text'])} *({' · '.join(label(r) for r in dict.fromkeys(it['refs']))})*"
                for it in items]

    return "\n".join([
        f"# {report_title(ctx)}", "", f"- {f.stats_line()}", "",
        "## 요약", f"**{readable(data['headline'])}**", "", readable(data["overview"]), "",
        "## 주요 이상과 조치", *bullets(data["events"], "없음"), "",
        "## 다음 교대가 이어서 할 일", *bullets(data["open_items"], "없음"), "",
        "## 주의해서 볼 설비", *bullets(data["watch"], "반복된 이상 없음"), "",
    ])


class HandoverWriter:
    """llm 이 있으면 Claude 로, 없거나 실패하면 템플릿으로 쓴다. llm 은 LlmGenerator (call_json 사용)."""

    def __init__(self, llm=None):
        self.llm = llm

    def write(self, ctx: dict) -> dict:
        f = Facts(ctx)
        if self.llm is None or f.empty:
            return template_report(ctx)
        try:
            data = self.llm.call_json(SYSTEM_PROMPT, build_user_prompt(ctx, f), OUTPUT_SCHEMA)
            validate(data, f)
            return {"title": report_title(ctx), "body": render(ctx, f, data), "generator": "llm"}
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 리포트는 나가야 한다
            print(f"[AGENT] handover llm failed, using template: {e!r}", file=sys.stderr)
            return template_report(ctx)
