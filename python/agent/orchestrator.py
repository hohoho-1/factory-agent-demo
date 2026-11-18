"""
알람 처리 오케스트레이터.

알람 1건이 들어오면 아래 순서로 처리한다. 모든 단계는 같은 공유 상태(AlarmState)를 읽고 쓴다.

  단일 입구(run) → 라우터(route) → 진단(diagnose) → 조치 제안(propose) → 승인 요청(approve) → 단일 출구(finish)

- 라우터: 알람을 설비 이상 / 배치 공정 / 공정값 이탈 / 사람에게 넘김(handoff) 중 하나로 나눈다 (규칙 기반).
  다룰 매뉴얼이 없는 알람은 유형과 상관없이 handoff 로 보낸다.
- 자율성 단계: 알림(ALERT) → 추천(RECOMMEND) → 승인 후 실행(APPROVE). handoff 는 알림까지만,
  지시서만 쓰면 추천, 설정값 변경 제안이 붙으면 승인 후 실행이다. 설비에 내려가는 것은 작업자가
  대시보드에서 승인한 뒤이며 (기존 OPC UA 승인형 제어), 에이전트가 직접 설비를 바꾸지 않는다.
- 실패 처리: 단계마다 타임아웃과 재시도 상한을 둔다. 필수 단계(조치 제안)가 상한을 넘으면
  자동 지시 대신 '자동 처리 실패, 담당자 확인' 지시서로 사람에게 넘긴다. 보조 단계(이력·설정값 조회)는
  실패해도 그 정보 없이 계속한다.
- 결정 로그: 단계마다 무엇을 왜 정했는지 state.decisions 에 남기고, 끝나면 logs/decisions.jsonl 에 한 줄로 쓴다.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .quality import LEVEL_KO, HOLD as QUALITY_HOLD, QualityAgent, in_batch
from .rag import ManualIndex
from .work_order import EQUIPMENT_KO, METRIC_KO, alarm_facts, build_query, history_section

# ---------------------------------------------------------------- 라우터

EQUIPMENT = "EQUIPMENT"  # 설비 이상: 진동·전류·속도처럼 설비 상태를 보여 주는 지표
BATCH = "BATCH"          # 배치 공정: 배치 단계마다 기준이 다른 지표가 그 단계 기준을 벗어남
PROCESS = "PROCESS"      # 공정값 이탈: 탱크 온도·레벨처럼 공정 조건을 보여 주는 지표
HANDOFF = "HANDOFF"      # 사람에게 넘김: 다룰 매뉴얼이 없다

ROUTE_KO = {EQUIPMENT: "설비 이상", BATCH: "배치 공정", PROCESS: "공정값 이탈", HANDOFF: "사람에게 넘김"}

EQUIPMENT_METRICS = {"vibration", "current", "speed"}
# 배치 단계별 기준이 있는 (설비 유형, 지표). 백엔드 application.yml 의 factory.alarm.phase-rules 와 맞춘다
PHASE_RULED = {("MIXER", "temperature")}
NO_PHASE = {None, "", "IDLE"}

ALERT, RECOMMEND, APPROVE = "ALERT", "RECOMMEND", "APPROVE"
AUTONOMY_KO = {ALERT: "알림", RECOMMEND: "추천", APPROVE: "승인 후 실행"}


@dataclass
class Route:
    kind: str
    reason: str
    manual_id: str | None = None


def classify(alarm: dict, index: ManualIndex) -> Route:
    """규칙 기반 라우터. 먼저 '다룰 매뉴얼이 있는가'를 보고, 있으면 지표·배치 단계로 유형을 나눈다."""
    eq, metric, direction = alarm["equipmentType"], alarm["metric"], alarm["direction"]
    hits = index.search(build_query(alarm), eq, metric, k=6)
    manual = index.manual_for(hits, eq, metric, direction)
    what = f"{EQUIPMENT_KO.get(eq, eq)} {METRIC_KO.get(metric, metric)} {'상승' if direction == 'HIGH' else '저하'}"
    if manual is None:
        nearest = hits[0].chunk.manual.id if hits else "없음"
        return Route(HANDOFF, f"{what} 알람을 다루는 매뉴얼 없음 (가장 비슷한 문서 {nearest}: 범위 다름)")
    phase = alarm.get("batchPhase")
    if phase not in NO_PHASE and (eq, metric) in PHASE_RULED:
        return Route(BATCH, f"배치 {phase} 단계 기준 이탈", manual.id)
    if metric in EQUIPMENT_METRICS:
        return Route(EQUIPMENT, f"{METRIC_KO.get(metric, metric)}: 설비 상태 지표", manual.id)
    return Route(PROCESS, f"{METRIC_KO.get(metric, metric)}: 공정 조건 지표", manual.id)


def classify_naive(alarm: dict) -> str:
    """비교용: 매뉴얼 범위를 보지 않고 지표만으로 나누는 라우터 (평가에서 '매뉴얼 확인'의 효과를 보려고 둔다)."""
    if alarm.get("batchPhase") not in NO_PHASE and (alarm["equipmentType"], alarm["metric"]) in PHASE_RULED:
        return BATCH
    return EQUIPMENT if alarm["metric"] in EQUIPMENT_METRICS else PROCESS


# ---------------------------------------------------------------- 공유 상태


@dataclass
class StepLog:
    step: str
    status: str        # ok / retry / timeout / error / skipped / degraded / handoff
    attempt: int
    ms: int
    note: str = ""


@dataclass
class AlarmState:
    """알람 1건을 처리하는 동안 모든 단계가 읽고 쓰는 객체."""
    alarm: dict
    event: str
    route: Route | None = None                    # 라우터: 분류 결과
    history: list[dict] = field(default_factory=list)    # 진단: 과거 조치 이력
    setpoints: list[dict] = field(default_factory=list)  # 진단: 조정 가능한 설정값
    work_order: dict | None = None                # 조치 제안: 지시서
    proposal: dict | None = None                  # 조치 제안: 설정값 변경 제안
    autonomy: str = ALERT                          # 이 건의 자율성 단계
    approval: str = "NOT_NEEDED"                  # NOT_NEEDED / PENDING (작업자 승인 대기) / REJECTED (백엔드 검사 거부)
    handoff_reason: str | None = None
    quality: dict | None = None                   # 품질 에이전트: 배치 중 알람의 품질 영향 판정
    quality_status: str = "NOT_NEEDED"            # NOT_NEEDED / RECORDED / PENDING (품질팀 승인 대기) / FAILED
    saved_id: int | None = None
    log: list[StepLog] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def decide(self, text: str) -> None:
        self.decisions.append(text)


@dataclass
class StepPolicy:
    timeout: float    # 시도 1번의 상한 (초)
    retries: int      # 실패 후 다시 시도할 횟수
    required: bool    # True: 상한을 넘으면 사람에게 넘김 / False: 그 정보 없이 계속


# 조치 제안은 LLM 이면 12~16초(실측), 클라이언트 타임아웃 60초 + 재시도 1번 → 한 번에 150초까지 기다린다
DEFAULT_POLICIES = {
    "route": StepPolicy(timeout=5, retries=0, required=True),
    "history": StepPolicy(timeout=6, retries=1, required=False),
    "setpoints": StepPolicy(timeout=6, retries=1, required=False),
    "propose": StepPolicy(timeout=150, retries=1, required=True),
    "save": StepPolicy(timeout=10, retries=2, required=True),
    "quality": StepPolicy(timeout=90, retries=0, required=False),
    "quality_save": StepPolicy(timeout=10, retries=2, required=False),
}


class StepFailed(RuntimeError):
    def __init__(self, step: str, reason: str):
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


# ---------------------------------------------------------------- 사람에게 넘기는 지시서


def handoff_order(alarm: dict, reason: str, history: list[dict]) -> dict:
    """자동 처리가 끝까지 가지 못했을 때의 지시서: 조치를 지어내지 않고 담당자 확인을 요청한다."""
    eq_ko = EQUIPMENT_KO.get(alarm["equipmentType"], alarm["equipmentType"])
    metric_ko = METRIC_KO.get(alarm["metric"], alarm["metric"])
    title = f"[{alarm['severity']}] {alarm['equipmentId']} {eq_ko} {metric_ko} 이상 — 자동 처리 실패, 담당자 확인"
    body = "\n".join([
        f"# {title}",
        "",
        *alarm_facts(alarm),
        "- 근거 매뉴얼: 없음 (자동 처리 중단)",
        "",
        *history_section(history, alarm["equipmentId"]),
        "## 자동 처리 중단",
        f"AI 조치 지시를 만드는 중 문제가 생겨 사람에게 넘깁니다: {reason}",
        "설비 담당자가 매뉴얼과 현장을 직접 확인하고 조치 내용을 남겨 주세요.",
        "",
        "## 안전 주의사항",
        "- 설비 내부 점검·정비가 필요하면 MAN-SAFE-LOTO-01 의 잠금·표지 절차를 따른다.",
    ])
    return {
        "title": title,
        "summary": f"{alarm['equipmentId']}({eq_ko}) {metric_ko} 알람의 자동 지시서 작성이 실패해 담당자 확인이 필요합니다.",
        "body": body,
        "generator": "handoff",
        "references": [],
        "causeOptions": [],
        "setpointChange": None,
    }


def trace_section(state: AlarmState) -> list[str]:
    """지시서 끝에 붙이는 처리 기록: 화면에서 '왜 이렇게 처리됐나'를 볼 수 있게."""
    route = state.route
    lines = ["", "## 처리 기록 (오케스트레이터)"]
    if route:
        lines.append(f"- 분류: {ROUTE_KO[route.kind]} — {route.reason}")
    lines.append(f"- 자율성 단계: {AUTONOMY_KO[state.autonomy]}"
                 + (" (설정값 변경은 작업자 승인 후 설비에 반영)" if state.autonomy == APPROVE else ""))
    if state.handoff_reason:
        lines.append(f"- 사람에게 넘긴 이유: {state.handoff_reason}")
    if state.quality:
        q = state.quality
        lines.append(f"- 품질 판정: {LEVEL_KO[q['level']]} — {q['basis']}"
                     + (" (품질팀 승인 대기)" if q["level"] == QUALITY_HOLD else ""))
    steps = " → ".join(f"{s.step} {s.status}" + (f"({s.attempt}회)" if s.attempt > 1 else "") for s in state.log)
    lines.append(f"- 단계: {steps}")
    return lines


# ---------------------------------------------------------------- 오케스트레이터


class Orchestrator:
    """
    backend 는 get_history / get_setpoints / save_work_order / save_setpoint_proposal / save_quality_assessment 를
    가진 객체 (agent.Backend 또는 테스트용 가짜). generator 는 generate(alarm, index, history, setpoints) 를 가진 생성기.
    quality 는 배치 중 알람의 품질 영향을 판정하는 두 번째 에이전트 (없으면 템플릿 설명만 쓰는 QualityAgent).
    """

    def __init__(self, index: ManualIndex, backend, generator, policies: dict[str, StepPolicy] | None = None,
                 decision_log: Path | None = None, dry_run: bool = False, out=print, quality: QualityAgent | None = None):
        self.index = index
        self.backend = backend
        self.generator = generator
        self.quality = quality or QualityAgent()
        self.policies = {**DEFAULT_POLICIES, **(policies or {})}
        self.decision_log = decision_log
        self.dry_run = dry_run
        self.out = out
        # 타임아웃을 걸려고 단계를 작업 스레드에서 돌린다. 시간을 넘긴 시도는 끝까지 기다리지 않고 버린다
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="orchestrator-step")

    # ------------------------------------------------------------ 단일 입구

    def run(self, alarm: dict, event: str) -> AlarmState:
        state = AlarmState(alarm=alarm, event=event)
        try:
            self._route(state)
            self._diagnose(state)
            self._propose(state)
        except StepFailed as e:
            self._handoff(state, f"{e.step} 단계 실패 — {e.reason}")
        self._judge_quality(state)
        self._approve_and_finish(state)
        return state

    # ------------------------------------------------------------ 단계

    def _route(self, state: AlarmState) -> None:
        state.route = self._step(state, "route", lambda: classify(state.alarm, self.index))
        state.decide(f"분류 {state.route.kind}: {state.route.reason}")

    def _diagnose(self, state: AlarmState) -> None:
        alarm = state.alarm
        state.history = self._step(state, "history", lambda: self.backend.get_history(alarm), default=[])
        if state.route.kind == HANDOFF:
            state.log.append(StepLog("setpoints", "skipped", 0, 0, "사람에게 넘기는 건은 설정값 제안 안 함"))
            return
        state.setpoints = self._step(state, "setpoints", lambda: self.backend.get_setpoints(alarm["equipmentId"]),
                                     default=[])

    def _propose(self, state: AlarmState) -> None:
        if state.route.kind == HANDOFF:
            # 생성기도 매뉴얼이 없으면 '매뉴얼 없음, 담당자 확인' 지시서를 쓴다 (LLM 을 부르지 않음)
            state.work_order = self._step(state, "propose", lambda: self.generator.generate(
                state.alarm, self.index, state.history, []))
            state.work_order.pop("setpointChange", None)
            state.handoff_reason = state.route.reason
            state.autonomy = ALERT
            state.decide("자율성 알림: 근거 매뉴얼이 없어 조치를 추천하지 않고 담당자에게 넘김")
            return
        wo = self._step(state, "propose", lambda: self.generator.generate(
            state.alarm, self.index, state.history, state.setpoints))
        state.proposal = wo.pop("setpointChange", None)
        state.work_order = wo
        if getattr(self.generator, "name", None) == "llm" and wo.get("generator") != "llm" and wo.get("references"):
            # FallbackGenerator 가 LLM 실패를 템플릿으로 덮었다: 지시서는 나갔지만 기록은 남긴다
            state.decide("LLM 생성기 실패: 매뉴얼 템플릿 지시서로 대체 (원인은 에이전트 콘솔 로그)")
        if not wo.get("references"):
            # 라우터는 매뉴얼이 있다고 봤는데 생성기가 근거를 못 찾은 경우: 사람에게 넘긴 것으로 기록한다
            state.handoff_reason = "생성기가 근거 매뉴얼을 찾지 못함"
            state.autonomy = ALERT
            state.decide("자율성 알림: 지시서에 근거가 없어 담당자 확인으로 처리")
        elif state.proposal:
            state.autonomy = APPROVE
            state.decide(f"자율성 승인 후 실행: {state.proposal['tag']} {state.proposal['currentValue']}"
                         f" → {state.proposal['proposedValue']} 제안 ({state.proposal['sources']})")
        else:
            state.autonomy = RECOMMEND
            state.decide("자율성 추천: 매뉴얼 근거 지시서만 냄 (조정할 설정값 없음)")

    def _handoff(self, state: AlarmState, reason: str) -> None:
        state.work_order = handoff_order(state.alarm, reason, state.history)
        state.proposal = None
        state.autonomy = ALERT
        state.handoff_reason = reason
        state.log.append(StepLog("handoff", "handoff", 1, 0, reason))
        state.decide(f"사람에게 넘김: {reason}")

    def _judge_quality(self, state: AlarmState) -> None:
        """
        두 번째 에이전트: 배치 진행 중 알람이면 품질 영향을 판정한다. 지시서 경로와 상관없이 한다
        (매뉴얼이 없어 사람에게 넘긴 알람도 배치 품질에는 영향이 있을 수 있다).
        """
        if not in_batch(state.alarm):
            return
        q = self._step(state, "quality", lambda: self.quality.assess(state.alarm, state.work_order), default=None)
        if q is None:
            state.quality_status = "FAILED"
            state.decide("품질 판정 실패: 품질팀이 직접 확인해야 함")
            return
        state.quality = q
        state.decide(f"품질 판정 {q['level']}: {q['basis']}"
                     + (" — 품질팀 승인 필요" if q["level"] == QUALITY_HOLD else ""))

    def _record_quality(self, state: AlarmState, work_order_id: int) -> None:
        saved = self._step(state, "quality_save",
                           lambda: self.backend.save_quality_assessment(work_order_id, state.quality), default=None)
        if saved is None:
            state.quality_status = "FAILED"
            state.decide("품질 판정 저장 실패: 품질팀이 직접 확인해야 함")
            return
        state.quality_status = saved["status"]
        state.decide(f"품질 판정 #{saved['id']} 저장 ({saved['status']})")
        self.out(f"        -> quality assessment #{saved['id']} {state.quality['level']} ({saved['status']})")

    def _approve_and_finish(self, state: AlarmState) -> None:
        """단일 출구: 지시서 저장 → (제안이 있으면) 승인 요청 → (배치 중이면) 품질 판정 저장 → 결정 로그."""
        wo = state.work_order
        wo["severity"] = state.alarm["severity"]  # LLM 이 쓰는 동안 알람 심각도가 바뀔 수 있다
        wo["body"] = wo["body"] + "\n" + "\n".join(trace_section(state))
        self._print(state)
        if self.dry_run:
            self.out(wo["body"])
            self._write_decisions(state)
            return
        try:
            saved = self._step(state, "save", lambda: self.backend.save_work_order(state.alarm["id"], wo))
        except StepFailed as e:
            # 저장까지 실패하면 화면에 남길 곳이 없다: 결정 로그와 콘솔에만 남긴다
            state.decide(f"지시서 저장 실패: {e.reason}")
            print(f"[ORCH] alarm #{state.alarm['id']} work order not saved: {e.reason}", file=sys.stderr)
            self._write_decisions(state)
            return
        state.saved_id = saved["id"]
        self.out(f"        -> work order #{saved['id']} saved: {saved['title']}")
        if state.proposal:
            self._request_approval(state, saved["id"])
        if state.quality:
            self._record_quality(state, saved["id"])
        self._write_decisions(state)

    def _request_approval(self, state: AlarmState, work_order_id: int) -> None:
        """기존 승인형 제어 재사용: 제안을 저장하면 PENDING 이 되고, 작업자가 승인해야 설비에 내려간다."""
        import urllib.error
        p = state.proposal
        started = time.perf_counter()
        try:
            saved = self.backend.save_setpoint_proposal(work_order_id, {
                "tag": p["tag"], "proposedValue": p["proposedValue"], "reason": p["reason"],
                "sources": p["sources"], "generator": state.work_order["generator"],
            })
            state.approval = "PENDING"
            state.log.append(StepLog("approve", "ok", 1, _ms(started), f"setpoint change #{saved['id']} 승인 대기"))
            state.decide(f"승인 요청: 설정값 변경 #{saved['id']} 작업자 승인 대기")
            self.out(f"        -> setpoint change #{saved['id']} proposed (waiting for approval)")
        except urllib.error.HTTPError as e:
            # 백엔드가 운전 범위를 다시 검사해 거부함(422): 지시서만 남는다
            state.approval = "REJECTED"
            state.autonomy = RECOMMEND
            detail = e.read().decode("utf-8", "replace")
            state.log.append(StepLog("approve", "error", 1, _ms(started), f"{e.code} {detail}"))
            state.decide(f"설정값 제안이 백엔드 검사에서 거부됨({e.code}): 지시서만 남김")
            print(f"[AGENT] setpoint proposal rejected by backend: {e.code} {detail}", file=sys.stderr)
        except (urllib.error.URLError, ValueError) as e:
            state.approval = "REJECTED"
            state.autonomy = RECOMMEND
            state.log.append(StepLog("approve", "error", 1, _ms(started), repr(e)))
            state.decide(f"설정값 제안 저장 실패: {e!r}")
            print(f"[AGENT] setpoint proposal not saved: {e!r}", file=sys.stderr)

    # ------------------------------------------------------------ 실행·기록 도우미

    _MISSING = object()

    def _step(self, state: AlarmState, name: str, fn: Callable, default=_MISSING):
        """타임아웃·재시도 상한으로 한 단계를 돌린다. 필수 단계가 상한을 넘으면 StepFailed."""
        policy = self.policies[name]
        last = ""
        for attempt in range(1, policy.retries + 2):
            started = time.perf_counter()
            future = self._pool.submit(fn)
            try:
                result = future.result(timeout=policy.timeout)
                state.log.append(StepLog(name, "ok", attempt, _ms(started)))
                return result
            except FutureTimeout:
                future.cancel()
                last = f"{policy.timeout:g}초 안에 끝나지 않음"
                status = "timeout"
            except Exception as e:  # noqa: BLE001 - 어떤 실패든 상한까지 다시 하고, 넘으면 넘긴다
                last = f"{type(e).__name__}: {e}"
                status = "error"
            state.log.append(StepLog(name, status, attempt, _ms(started), last))
            if attempt <= policy.retries:
                state.decide(f"{name} {attempt}번째 시도 실패({last}), 다시 시도")
        if not policy.required and default is not self._MISSING:
            state.log[-1].status += "→degraded"
            state.decide(f"{name} 재시도 상한 초과: 그 정보 없이 계속 ({last})")
            return default
        raise StepFailed(name, f"재시도 {policy.retries}번 후에도 실패 ({last})")

    def _print(self, state: AlarmState) -> None:
        a, wo, route = state.alarm, state.work_order, state.route
        self.out(f"[AGENT] {state.event} alarm #{a.get('id')} {a.get('message', '')}")
        if route:
            self.out(f"        -> route {route.kind} ({route.reason}), autonomy {state.autonomy}")
        if wo["references"]:
            top = wo["references"][0]
            self.out(f"        -> {top['manualId']} / {top['section']} (score {top['score']}), generator {wo['generator']}")
        else:
            self.out(f"        -> no manual-based order ({state.handoff_reason}), generator {wo['generator']}")
        if state.quality:
            self.out(f"        -> quality {state.quality['level']} ({state.quality['basis']}), generator {state.quality['generator']}")
        if state.history:
            self.out(f"        -> past actions: {len(state.history)} (latest WO-{state.history[0]['id']})")
        if state.proposal:
            p = state.proposal
            self.out(f"        -> setpoint proposal: {p['tag']} {p['currentValue']} -> {p['proposedValue']} ({p['sources']})")

    def _write_decisions(self, state: AlarmState) -> None:
        if self.decision_log is None:
            return
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "alarmId": state.alarm.get("id"),
            "equipmentId": state.alarm["equipmentId"],
            "metric": state.alarm["metric"],
            "severity": state.alarm["severity"],
            "event": state.event,
            "route": state.route.kind if state.route else None,
            "autonomy": state.autonomy,
            "approval": state.approval,
            "quality": state.quality["level"] if state.quality else None,
            "qualityStatus": state.quality_status,
            "handoffReason": state.handoff_reason,
            "workOrderId": state.saved_id,
            "generator": state.work_order["generator"] if state.work_order else None,
            "steps": [asdict(s) for s in state.log],
            "decisions": state.decisions,
        }
        try:
            self.decision_log.parent.mkdir(parents=True, exist_ok=True)
            with self.decision_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[ORCH] decision log not written: {e!r}", file=sys.stderr)


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
