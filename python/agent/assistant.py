"""
AI 작업: 자연어 질의(QUESTION)와 매뉴얼 개선 제안(MANUAL_PROPOSAL).

둘 다 지시서·인수인계와 같은 원칙을 따른다.
- 재료에 번호를 붙여 보낸다: 매뉴얼 구절 S1…, 알람 A12…, 지시서 W34….
- Claude 는 JSON 스키마로 답하고 모든 항목에 번호를 단다. 번호 검증에 실패하면 템플릿으로 쓴다.
- 숫자(건수·해결률)는 코드가 센다.
매뉴얼 개선 제안은 한 가지를 더 지킨다: 모든 변경 제안은 현장 조치 기록(W) 근거가 하나 이상 있어야 하고,
대상 섹션은 실제 매뉴얼에 있는 섹션 중에서만 고른다 (스키마의 enum).
"""
from __future__ import annotations

import re
import sys
from collections import Counter

from .handover import Facts
from .llm import LlmOutputError
from .rag import Manual, ManualIndex
from .work_order import EQUIPMENT_KO, METRIC_KO, build_query, cause_options

_ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "refs"],
    "additionalProperties": False,
}

_REF_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_-])([AWST])(\d+)(?![0-9])")


class Refs:
    """번호 → 화면 표기. 문장 속 번호도 같은 표기로 바꾼다."""

    def __init__(self):
        self.labels: dict[str, str] = {}
        self.texts: dict[str, str] = {}

    def add(self, ref: str, label: str, text: str) -> None:
        self.labels[ref] = label
        self.texts[ref] = text

    def __contains__(self, ref: str) -> bool:
        return ref in self.labels

    def cite(self, refs: list[str]) -> str:
        return " *(" + " · ".join(self.labels[r] for r in dict.fromkeys(refs)) + ")*"

    def readable(self, text: str) -> str:
        return _REF_IN_TEXT.sub(lambda m: self.labels.get(m.group(0), m.group(0)), text.strip())

    def prompt_block(self, prefix: str) -> str:
        lines = [f"{r} | {self.texts[r]}" for r in self.labels if r.startswith(prefix)]
        return "\n".join(lines) or "(없음)"


def _check_refs(items: list[dict], refs: Refs, key: str) -> None:
    """모든 항목에 근거 번호가 있고, 그 번호가 재료 목록에 있어야 한다. 아니면 전체를 버린다."""
    for item in items:
        used = item.get("refs") or []
        if not used:
            raise LlmOutputError(f"'{key}' 항목에 근거 번호가 없습니다: {item}")
        _check_known(used, refs, key)


def _cited_only(items: list[dict], refs: Refs, key: str) -> list[dict]:
    """
    참고 문장용: 근거 번호가 없는 항목("다른 설비 기록은 0건이다" 같은 부연)은 그 항목만 뺀다.
    없는 번호를 인용하면 지어낸 것으로 보고 전체를 버린다.
    """
    kept = []
    for item in items:
        used = item.get("refs") or []
        if used:
            _check_known(used, refs, key)
            kept.append(item)
    return kept


def _check_known(used: list[str], refs: Refs, key: str) -> None:
    unknown = [r for r in used if r not in refs]
    if unknown:
        raise LlmOutputError(f"'{key}' 항목이 목록에 없는 번호를 인용했습니다: {unknown}")


def _add_records(refs: Refs, facts: Facts) -> None:
    for a in facts.alarms:
        refs.add(f"A{a['id']}", f"알람 #{a['id']}", facts.alarm_line(a))
    for w in facts.work_orders:
        refs.add(f"W{w['id']}", f"WO-{w['id']}", facts.wo_line(w))


def _stat_line(s: dict) -> str:
    causes = ", ".join(f"{c['cause']} {c['count']}건" for c in s.get("topCauses") or []) or "원인 기록 없음"
    rate = f"{round(s['resolvedCount'] / s['completedCount'] * 100)}%" if s["completedCount"] else "-"
    return (f"{s['equipmentId']} {METRIC_KO.get(s['metric'], s['metric'])}: 알람 {s['alarmCount']}건"
            f"(위험 {s['criticalCount']}), 조치 완료 {s['completedCount']}건, 해결률 {rate}, 주요 원인 {causes}")


def _stats_lines(stats: list[dict]) -> str:
    return "\n".join(_stat_line(s) for s in stats) or "(없음)"


# ---------------------------------------------------------------- 자연어 질의

QUESTION_SYSTEM = """\
당신은 화장품·세제 공장 생산 라인의 설비 담당자를 돕는 보조자입니다. 작업자의 질문에 한국어로 답합니다.

규칙
- 제공된 재료(설비 매뉴얼 구절 S, 설비별 통계 T, 최근 7일 알람 A, 조치 지시서 W)에 있는 사실만 씁니다. 지어내지 않습니다.
- refs 에는 재료 앞에 붙은 번호(S1, T1, A12, W34 형식)만 씁니다.
- answer 는 질문에 대한 직접적인 답 2~4문장입니다. details 는 그 답을 뒷받침하는 사실이고, 각 항목의 refs 에 근거 번호를 적습니다.
- 재료로 답할 수 없는 질문(재료에 없는 기간·설비, 공장 밖 일반 지식, 설비 조작 지시 요구 등)이면 unanswerable 을 true 로 하고,
  answer 에 무엇이 없어서 답할 수 없는지 한 문장으로 쓰고 details 는 비웁니다.
- 설비를 직접 조작하라는 답은 하지 않습니다. 필요한 조치는 매뉴얼 절차와 담당자 확인을 안내합니다.
"""

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "details": {"type": "array", "items": _ITEM},
        "unanswerable": {"type": "boolean"},
    },
    "required": ["answer", "details", "unanswerable"],
    "additionalProperties": False,
}


def question_refs(question: str, index: ManualIndex, facts: Facts, stats: list[dict]) -> tuple[Refs, list]:
    refs = Refs()
    hits = index.search(question, k=6)
    for i, h in enumerate(hits, start=1):
        m = h.chunk.manual
        refs.add(f"S{i}", f"{m.id} · {h.chunk.section}",
                 f"[{m.id} {m.title}] {h.chunk.section}: {m.sections.get(h.chunk.section, '')}".replace("\n", " "))
    for i, s in enumerate(stats, start=1):
        refs.add(f"T{i}", f"{s['equipmentId']} {METRIC_KO.get(s['metric'], s['metric'])} 통계", _stat_line(s))
    _add_records(refs, facts)
    return refs, hits


def question_title(question: str) -> str:
    return question if len(question) <= 60 else question[:59] + "…"


def question_template(task: dict, hits: list, stats: list[dict]) -> dict:
    body = "\n".join([
        f"# {question_title(task['question'])}", "",
        "## 답변",
        "LLM 키가 없거나 응답을 쓸 수 없어 문장 답변은 만들지 못했습니다. 질문과 관련 있어 보이는 자료입니다.", "",
        "## 관련 매뉴얼",
        *[f"- {h.chunk.manual.id} · {h.chunk.section} (score {h.score:.3f})" for h in hits[:3]], "",
        "## 설비별 기록", *[f"- {line}" for line in _stats_lines(stats).splitlines()], "",
    ])
    return {"title": question_title(task["question"]), "body": body, "generator": "template"}


def answer_question(task: dict, ctx: dict, index: ManualIndex, stats: list[dict], llm) -> dict:
    facts = Facts(ctx)
    refs, hits = question_refs(task["question"], index, facts, stats)
    if llm is None:
        return question_template(task, hits, stats)
    prompt = "\n\n".join([
        f"질문\n{task['question']}",
        f"설비 매뉴얼 (S)\n{refs.prompt_block('S')}",
        f"설비별 통계, 전체 기간 (T)\n{refs.prompt_block('T')}",
        f"최근 7일 알람 (A)\n{refs.prompt_block('A')}",
        f"최근 7일 조치 지시서 (W)\n{refs.prompt_block('W')}",
        "위 재료로 질문에 답하세요.",
    ])
    data = llm.call_json(QUESTION_SYSTEM, prompt, QUESTION_SCHEMA)
    if not data.get("unanswerable"):
        data["details"] = _cited_only(data.get("details") or [], refs, "details")
        if not data["details"]:
            raise LlmOutputError("근거 번호가 달린 답변 근거(details)가 없습니다")
    lines = [f"# {question_title(task['question'])}", "", "## 답변", refs.readable(data["answer"]), ""]
    if data.get("details") and not data.get("unanswerable"):
        lines += ["## 근거", *[f"- {refs.readable(d['text'])}{refs.cite(d['refs'])}" for d in data["details"]], ""]
    lines += ["*최근 7일 알람·조치 기록과 설비 매뉴얼만 근거로 답합니다.*", ""]
    return {"title": question_title(task["question"]), "body": "\n".join(lines), "generator": "llm"}


# ---------------------------------------------------------------- 매뉴얼 개선 제안

PROPOSAL_SYSTEM = """\
당신은 화장품·세제 공장의 설비 매뉴얼을 관리하는 정비 엔지니어를 돕습니다. 현장 조치 기록을 보고 매뉴얼 개선안 초안을 씁니다.

규칙
- 제공된 매뉴얼 구절(S)과 현장 조치 기록(W)에 있는 사실만 씁니다. 수치·부품·절차를 지어내지 않습니다.
- refs 에는 재료 앞에 붙은 번호(S1, W34 형식)만 씁니다.
- findings: 현장 기록에서 확인된 점 (반복 원인, 매뉴얼 '가능 원인'에 없는 원인, 매뉴얼에 없는 조치, 미해결·부분 해결 사례).
- changes: 매뉴얼을 이렇게 바꾸자는 제안. 각 제안은 반드시 현장 기록(W) 근거를 하나 이상 포함하고, 고칠 섹션은 주어진 섹션 이름 중에서 고릅니다.
  현장 기록이 매뉴얼과 일치해 바꿀 것이 없으면 changes 는 빈 목록입니다.
- proposal 은 매뉴얼에 그대로 넣을 수 있는 문장으로 씁니다 ("~한다" 체). 안전 절차를 약하게 바꾸는 제안은 하지 않습니다.
- summary 는 2문장입니다.
"""


def proposal_schema(sections: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": _ITEM},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "enum": sections},
                        "kind": {"type": "string", "enum": ["추가", "수정", "순서 변경", "삭제"]},
                        "proposal": {"type": "string"},
                        "reason": {"type": "string"},
                        "refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["section", "kind", "proposal", "reason", "refs"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "findings", "changes"],
        "additionalProperties": False,
    }


class ProposalFacts:
    """제안 대상 설비·지표의 기록 요약 (코드가 센 값)."""

    def __init__(self, task: dict, ctx: dict):
        self.task = task
        self.facts = Facts(ctx)
        own = [w for w in self.facts.work_orders if w["equipmentId"] == task["equipmentId"]]
        self.own_done = own
        self.others_done = [w for w in self.facts.work_orders if w["equipmentId"] != task["equipmentId"]]
        self.causes = Counter(w["rootCause"].strip() for w in own if w.get("rootCause"))
        self.unresolved = [w for w in own if w.get("outcome") in ("PARTIAL", "UNRESOLVED")]

    def where(self) -> str:
        a = self.facts.alarms[0] if self.facts.alarms else None
        eq_type = a["equipmentType"] if a else ""
        return (f"{EQUIPMENT_KO.get(eq_type, eq_type)}({self.task['equipmentId']}) "
                f"{METRIC_KO.get(self.task['metric'], self.task['metric'])}")

    def stats_line(self) -> str:
        resolved = sum(1 for w in self.own_done if w.get("outcome") == "RESOLVED")
        rate = f"{round(resolved / len(self.own_done) * 100)}%" if self.own_done else "-"
        causes = ", ".join(f"{c} {n}건" for c, n in self.causes.most_common()) or "원인 기록 없음"
        return (f"알람 {len(self.facts.alarms)}건 · 조치 완료 {len(self.own_done)}건 (해결률 {rate}) · "
                f"같은 유형 다른 설비 조치 {len(self.others_done)}건 · 원인별: {causes}")


def find_manual(pf: ProposalFacts, index: ManualIndex) -> Manual | None:
    if not pf.facts.alarms:
        return None
    hits = index.search(build_query(pf.facts.alarms[0]), pf.facts.alarms[0]["equipmentType"], pf.task["metric"], k=6)
    return index.best_manual(hits)


def proposal_title(manual: Manual | None, pf: ProposalFacts) -> str:
    target = manual.id if manual else pf.task["equipmentId"]
    return f"매뉴얼 개선 제안(초안) {target} — {pf.where()}"


def _proposal_head(manual: Manual | None, pf: ProposalFacts) -> list[str]:
    return [
        f"# {proposal_title(manual, pf)}", "",
        f"> 설비 담당자가 검토한 뒤 반영하는 **초안**입니다. 대상 매뉴얼: "
        f"{manual.id + ' ' + manual.title if manual else '(찾지 못함)'}", "",
        f"- {pf.stats_line()}", "",
    ]


def proposal_template(pf: ProposalFacts, manual: Manual | None) -> dict:
    lines = _proposal_head(manual, pf)
    if manual is None or not pf.own_done:
        lines += ["## 요약", "이 설비·지표에는 아직 조치 완료 기록이 없어 매뉴얼과 비교할 근거가 없다.", ""]
        return {"title": proposal_title(manual, pf), "body": "\n".join(lines), "generator": "template"}

    known = cause_options(manual.sections.get("가능 원인", ""))
    changes = []
    for cause, n in pf.causes.most_common():
        if cause not in known:
            changes.append(f"「가능 원인」 추가 — '{cause}' (현장 기록 {n}건, 매뉴얼에 없는 원인)")
    top = pf.causes.most_common(1)
    if top and top[0][1] >= 2:
        changes.append(f"「점검 절차」 순서 변경 — '{top[0][0]}' 관련 점검을 앞쪽으로 (가장 많은 원인, {top[0][1]}건)")
    if pf.unresolved:
        ids = ", ".join(f"WO-{w['id']}" for w in pf.unresolved)
        changes.append(f"「에스컬레이션 기준」 수정 검토 — 미해결·부분 해결 {len(pf.unresolved)}건 ({ids})")
    lines += ["## 변경 제안", *([f"- {c}" for c in changes] or ["- 변경 제안 없음 — 현장 기록이 매뉴얼과 일치한다"]), ""]
    return {"title": proposal_title(manual, pf), "body": "\n".join(lines), "generator": "template"}


def write_proposal(task: dict, ctx: dict, index: ManualIndex, llm) -> dict:
    pf = ProposalFacts(task, ctx)
    manual = find_manual(pf, index)
    if llm is None or manual is None or not pf.own_done:
        return proposal_template(pf, manual)

    refs = Refs()
    sections = list(manual.sections)
    for i, (section, body) in enumerate(manual.sections.items(), start=1):
        refs.add(f"S{i}", section, f"{section}: {body}".replace("\n", " "))
    _add_records(refs, Facts({"alarms": [], "workOrders": pf.own_done + pf.others_done}))
    prompt = "\n\n".join([
        f"대상: {pf.where()} / 매뉴얼 {manual.id} {manual.title}",
        f"집계: {pf.stats_line()}",
        f"매뉴얼 섹션 (S, 섹션 이름: {', '.join(sections)})\n{refs.prompt_block('S')}",
        f"현장 조치 기록 (W, 같은 설비 {len(pf.own_done)}건 + 같은 유형 다른 설비 {len(pf.others_done)}건)\n"
        f"{refs.prompt_block('W')}",
        "위 기록으로 매뉴얼 개선안 초안을 JSON 으로 작성하세요.",
    ])
    data = llm.call_json(PROPOSAL_SYSTEM, prompt, proposal_schema(sections))
    data["findings"] = _cited_only(data["findings"], refs, "findings")
    _check_refs(data["changes"], refs, "changes")
    for c in data["changes"]:
        if not any(r.startswith("W") for r in c["refs"]):
            raise LlmOutputError(f"현장 기록 근거 없는 변경 제안입니다: {c['proposal']}")
        if c["section"] not in manual.sections:
            raise LlmOutputError(f"매뉴얼에 없는 섹션입니다: {c['section']}")

    lines = _proposal_head(manual, pf)
    lines += ["## 요약", refs.readable(data["summary"]), "",
              "## 현장 기록에서 확인된 점",
              *([f"- {refs.readable(f['text'])}{refs.cite(f['refs'])}" for f in data["findings"]] or ["- 없음"]), "",
              "## 변경 제안"]
    if not data["changes"]:
        lines.append("- 변경 제안 없음 — 현장 기록이 매뉴얼과 일치한다")
    for n, c in enumerate(data["changes"], start=1):
        lines += [f"### {n}. 「{c['section']}」 {c['kind']}", refs.readable(c["proposal"]), "",
                  f"- 이유: {refs.readable(c['reason'])}{refs.cite(c['refs'])}", ""]
    return {"title": proposal_title(manual, pf), "body": "\n".join(lines), "generator": "llm"}


class AssistantWriter:
    """llm 이 있으면 Claude 로, 없거나 실패하면 템플릿으로 쓴다. llm 은 LlmGenerator (call_json 사용)."""

    def __init__(self, index: ManualIndex, llm=None):
        self.index = index
        self.llm = llm

    def write(self, ctx: dict, stats: list[dict]) -> dict:
        task = ctx["task"]
        try:
            if task["type"] == "QUESTION":
                return answer_question(task, ctx, self.index, stats, self.llm)
            return write_proposal(task, ctx, self.index, self.llm)
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 결과는 나가야 한다
            print(f"[AGENT] assistant #{task['id']} llm failed, using template: {e!r}", file=sys.stderr)
            if task["type"] == "QUESTION":
                return question_template(task, self.index.search(task["question"], k=3), stats)
            pf = ProposalFacts(task, ctx)
            return proposal_template(pf, find_manual(pf, self.index))
