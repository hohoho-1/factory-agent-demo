"""
같은 알람 처리 흐름을 LangGraph 로 다시 짠 버전 (비교용, 실습 12-1 선택 항목).

직접 만든 orchestrator.Orchestrator 와 같은 부품(라우터 classify, handoff_order, trace_section)을 쓰고,
흐름 제어만 LangGraph 에 맡긴다. 두 구현이 같은 알람에 같은 경로·자율성 단계를 내는지는
tests/test_orchestrator_graph.py 가 확인한다. 비교 정리는 docs/orchestrator-langgraph.md.

  START → route → diagnose → propose ─┬→ quality → save ─┬→ approve ─┬→ record_quality → END
                                      └→ handoff ─┘        └───────────┴→ END
  (quality 와 record_quality 는 배치 진행 중 알람에서만 일한다: 두 번째 에이전트인 품질 에이전트)

LangGraph 로 바뀌는 것
- 흐름이 코드가 아니라 그래프(노드 + 조건 엣지)로 선언된다. graph.get_graph().draw_mermaid() 로 그림이 나온다.
- 공유 상태는 TypedDict 이고, 노드는 바뀐 필드만 돌려준다. 로그·결정 목록은 리듀서(operator.add)로 쌓인다.
- 재시도: 저장 노드는 RetryPolicy 로 선언한다. 단, RetryPolicy 는 상한을 넘으면 그래프를 예외로 멈추므로
  '상한을 넘으면 사람에게 넘김'은 조치 제안 노드 안에서 시도하고 조건 엣지로 handoff 노드에 보낸다.
- 타임아웃: 노드별 타임아웃은 없다 (그래프 전체 step_timeout 만 있음). 그래서 직접 구현과 같은 도우미를 쓴다.
- 승인: human_in_loop=True 면 승인 노드가 interrupt() 로 그래프를 멈추고, 작업자 결정이 오면
  Command(resume=...) 로 이어서 끝낸다 (체크포인터에 상태가 저장돼 있어 프로세스가 바뀌어도 이어 갈 수 있다).
  기본값(False)은 직접 구현과 같이 '승인 대기로 저장하고 끝'이며, 실제 승인은 대시보드 → 백엔드가 처리한다.
"""
from __future__ import annotations

import operator
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Annotated, Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

from .orchestrator import (ALERT, APPROVE, DEFAULT_POLICIES, HANDOFF, RECOMMEND, AlarmState, Route, StepLog,
                           StepPolicy, classify, handoff_order, trace_section)
from .quality import HOLD as QUALITY_HOLD, QualityAgent, in_batch
from .rag import ManualIndex


class GraphState(TypedDict, total=False):
    alarm: dict
    event: str
    route: Route
    history: list[dict]
    setpoints: list[dict]
    work_order: dict
    proposal: dict | None
    autonomy: str
    approval: str
    handoff_reason: str | None
    failure: str | None          # 조치 제안이 상한을 넘으면 이유가 들어가고, 조건 엣지가 handoff 로 보낸다
    quality: dict | None
    quality_status: str
    saved_id: int | None
    log: Annotated[list[StepLog], operator.add]
    decisions: Annotated[list[str], operator.add]


_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="graph-step")


def _attempts(name: str, fn: Callable, policy: StepPolicy) -> tuple[Any, list[StepLog], list[str], str | None]:
    """타임아웃·재시도 상한으로 fn 을 돌린다. (결과, 로그, 결정, 실패 이유) — 실패 이유가 있으면 결과는 None."""
    logs, decisions, last = [], [], ""
    for attempt in range(1, policy.retries + 2):
        started = time.perf_counter()
        future = _pool.submit(fn)
        try:
            result = future.result(timeout=policy.timeout)
            logs.append(StepLog(name, "ok", attempt, _ms(started)))
            return result, logs, decisions, None
        except FutureTimeout:
            future.cancel()
            last, status = f"{policy.timeout:g}초 안에 끝나지 않음", "timeout"
        except Exception as e:  # noqa: BLE001
            last, status = f"{type(e).__name__}: {e}", "error"
        logs.append(StepLog(name, status, attempt, _ms(started), last))
        if attempt <= policy.retries:
            decisions.append(f"{name} {attempt}번째 시도 실패({last}), 다시 시도")
    return None, logs, decisions, f"재시도 {policy.retries}번 후에도 실패 ({last})"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def build_graph(index: ManualIndex, backend, generator, policies: dict[str, StepPolicy] | None = None,
                human_in_loop: bool = False, checkpointer=None, quality: QualityAgent | None = None):
    """컴파일한 LangGraph 를 돌려준다. human_in_loop 면 체크포인터가 필요하다 (없으면 메모리 체크포인터)."""
    pol = {**DEFAULT_POLICIES, **(policies or {})}
    quality_agent = quality or QualityAgent()

    # ---------------------------------------------------------- 노드: 바뀐 필드만 돌려준다

    def route(state: GraphState) -> dict:
        started = time.perf_counter()
        r = classify(state["alarm"], index)
        return {"route": r, "log": [StepLog("route", "ok", 1, _ms(started))],
                "decisions": [f"분류 {r.kind}: {r.reason}"]}

    def diagnose(state: GraphState) -> dict:
        alarm, out = state["alarm"], {"log": [], "decisions": []}
        history, logs, decs, fail = _attempts("history", lambda: backend.get_history(alarm), pol["history"])
        out["log"] += logs
        out["decisions"] += decs
        if fail:
            logs[-1].status += "→degraded"
            out["decisions"].append(f"history 재시도 상한 초과: 그 정보 없이 계속 ({fail})")
        out["history"] = history or []
        if state["route"].kind == HANDOFF:
            out["log"].append(StepLog("setpoints", "skipped", 0, 0, "사람에게 넘기는 건은 설정값 제안 안 함"))
            out["setpoints"] = []
            return out
        setpoints, logs, decs, fail = _attempts(
            "setpoints", lambda: backend.get_setpoints(alarm["equipmentId"]), pol["setpoints"])
        out["log"] += logs
        out["decisions"] += decs
        if fail:
            logs[-1].status += "→degraded"
            out["decisions"].append(f"setpoints 재시도 상한 초과: 그 정보 없이 계속 ({fail})")
        out["setpoints"] = setpoints or []
        return out

    def propose(state: GraphState) -> dict:
        handoff_route = state["route"].kind == HANDOFF
        setpoints = [] if handoff_route else state["setpoints"]
        wo, logs, decs, fail = _attempts("propose", lambda: generator.generate(
            state["alarm"], index, state["history"], setpoints), pol["propose"])
        out = {"log": logs, "decisions": decs}
        if fail:
            return {**out, "failure": f"propose 단계 실패 — {fail}"}
        proposal = wo.pop("setpointChange", None)
        out["work_order"] = wo
        if handoff_route:
            return {**out, "proposal": None, "autonomy": ALERT, "handoff_reason": state["route"].reason,
                    "decisions": decs + ["자율성 알림: 근거 매뉴얼이 없어 조치를 추천하지 않고 담당자에게 넘김"]}
        if getattr(generator, "name", None) == "llm" and wo.get("generator") != "llm" and wo.get("references"):
            out["decisions"] = out["decisions"] + ["LLM 생성기 실패: 매뉴얼 템플릿 지시서로 대체 (원인은 에이전트 콘솔 로그)"]
        if not wo.get("references"):
            return {**out, "proposal": None, "autonomy": ALERT, "handoff_reason": "생성기가 근거 매뉴얼을 찾지 못함",
                    "decisions": out["decisions"] + ["자율성 알림: 지시서에 근거가 없어 담당자 확인으로 처리"]}
        if proposal:
            return {**out, "proposal": proposal, "autonomy": APPROVE,
                    "decisions": out["decisions"] + [
                        f"자율성 승인 후 실행: {proposal['tag']} {proposal['currentValue']} → {proposal['proposedValue']}"
                        f" 제안 ({proposal['sources']})"]}
        return {**out, "proposal": None, "autonomy": RECOMMEND,
                "decisions": out["decisions"] + ["자율성 추천: 매뉴얼 근거 지시서만 냄 (조정할 설정값 없음)"]}

    def handoff(state: GraphState) -> dict:
        reason = state["failure"]
        return {"work_order": handoff_order(state["alarm"], reason, state.get("history") or []),
                "proposal": None, "autonomy": ALERT, "handoff_reason": reason,
                "log": [StepLog("handoff", "handoff", 1, 0, reason)], "decisions": [f"사람에게 넘김: {reason}"]}

    def judge_quality(state: GraphState) -> dict:
        # 두 번째 에이전트. 지시서 경로(정상 · handoff)와 상관없이 배치 중 알람이면 판정한다
        if not in_batch(state["alarm"]):
            return {}
        q, logs, decs, fail = _attempts("quality", lambda: quality_agent.assess(state["alarm"], state.get("work_order")),
                                        pol["quality"])
        if fail:
            logs[-1].status += "→degraded"
            return {"quality_status": "FAILED", "log": logs,
                    "decisions": decs + [f"quality 재시도 상한 초과: 그 정보 없이 계속 ({fail})",
                                         "품질 판정 실패: 품질팀이 직접 확인해야 함"]}
        return {"quality": q, "log": logs, "decisions": decs + [
            f"품질 판정 {q['level']}: {q['basis']}" + (" — 품질팀 승인 필요" if q["level"] == QUALITY_HOLD else "")]}

    def record_quality(state: GraphState) -> dict:
        saved, logs, decs, fail = _attempts(
            "quality_save", lambda: backend.save_quality_assessment(state["saved_id"], state["quality"]),
            pol["quality_save"])
        if fail:
            logs[-1].status += "→degraded"
            return {"quality_status": "FAILED", "log": logs,
                    "decisions": decs + [f"quality_save 재시도 상한 초과: 그 정보 없이 계속 ({fail})",
                                         "품질 판정 저장 실패: 품질팀이 직접 확인해야 함"]}
        return {"quality_status": saved["status"], "log": logs,
                "decisions": decs + [f"품질 판정 #{saved['id']} 저장 ({saved['status']})"]}

    def save(state: GraphState) -> dict:
        # 이 노드는 RetryPolicy 가 다시 돌린다. 상한을 넘으면 예외가 그래프 밖으로 나간다
        wo = dict(state["work_order"])
        wo["severity"] = state["alarm"]["severity"]
        wo["body"] = wo["body"] + "\n" + "\n".join(trace_section(_as_alarm_state(state)))
        started = time.perf_counter()
        saved = backend.save_work_order(state["alarm"]["id"], wo)
        return {"work_order": wo, "saved_id": saved["id"], "log": [StepLog("save", "ok", 1, _ms(started))]}

    def approve(state: GraphState) -> dict:
        p = state["proposal"]
        started = time.perf_counter()
        try:
            saved = backend.save_setpoint_proposal(state["saved_id"], {
                "tag": p["tag"], "proposedValue": p["proposedValue"], "reason": p["reason"],
                "sources": p["sources"], "generator": state["work_order"]["generator"],
            })
        except (urllib.error.URLError, ValueError) as e:  # HTTPError(422 운전 범위 거부)도 여기
            return {"approval": "REJECTED", "autonomy": RECOMMEND,
                    "log": [StepLog("approve", "error", 1, _ms(started), repr(e))],
                    "decisions": [f"설정값 제안이 백엔드에서 거부·실패됨: 지시서만 남김 ({e!r})"]}
        out = {"approval": "PENDING", "log": [StepLog("approve", "ok", 1, _ms(started), f"#{saved['id']} 승인 대기")],
               "decisions": [f"승인 요청: 설정값 변경 #{saved['id']} 작업자 승인 대기"]}
        if not human_in_loop:
            return out
        # 그래프를 여기서 멈춘다. 상태는 체크포인터에 남고, Command(resume={"decision": ..., "worker": ...}) 로 이어진다
        answer = interrupt({"setpointChangeId": saved["id"], "proposal": p})
        decision = answer.get("decision", "REJECTED")
        return {**out, "approval": decision,
                "decisions": out["decisions"] + [f"작업자 {answer.get('worker') or '-'} 결정: {decision}"]}

    # ---------------------------------------------------------- 엣지

    g = StateGraph(GraphState)
    g.add_node("route", route)
    g.add_node("diagnose", diagnose)
    g.add_node("propose", propose)
    g.add_node("handoff", handoff)
    g.add_node("save", save, retry_policy=RetryPolicy(max_attempts=pol["save"].retries + 1, initial_interval=0.2,
                                                       retry_on=(urllib.error.URLError, OSError)))
    g.add_node("approve", approve)
    g.add_node("quality", judge_quality)
    g.add_node("record_quality", record_quality)
    g.add_edge(START, "route")
    g.add_edge("route", "diagnose")
    g.add_edge("diagnose", "propose")
    g.add_conditional_edges("propose", lambda s: "handoff" if s.get("failure") else "quality", ["handoff", "quality"])
    g.add_edge("handoff", "quality")
    g.add_edge("quality", "save")

    def after_save(s: GraphState) -> str:
        if s.get("proposal"):
            return "approve"
        return "record_quality" if s.get("quality") else END

    g.add_conditional_edges("save", after_save, ["approve", "record_quality", END])
    g.add_conditional_edges("approve", lambda s: "record_quality" if s.get("quality") else END,
                            ["record_quality", END])
    g.add_edge("record_quality", END)
    if human_in_loop and checkpointer is None:
        checkpointer = InMemorySaver(serde=checkpoint_serde())
    return g.compile(checkpointer=checkpointer)


def checkpoint_serde() -> JsonPlusSerializer:
    """체크포인터가 상태 안의 StepLog · Route 를 다시 읽을 수 있게 허용 목록에 올린다."""
    return JsonPlusSerializer(allowed_msgpack_modules=[("agent.orchestrator", "StepLog"),
                                                       ("agent.orchestrator", "Route")])


def initial_state(alarm: dict, event: str) -> GraphState:
    return {"alarm": alarm, "event": event, "autonomy": ALERT, "approval": "NOT_NEEDED", "proposal": None,
            "handoff_reason": None, "failure": None, "quality": None, "quality_status": "NOT_NEEDED",
            "saved_id": None, "log": [], "decisions": []}


def _as_alarm_state(s: GraphState) -> AlarmState:
    """처리 기록(trace_section)은 직접 구현의 AlarmState 를 받는다: 같은 문구를 쓰려고 옮겨 담는다."""
    return AlarmState(alarm=s["alarm"], event=s.get("event", ""), route=s.get("route"), quality=s.get("quality"),
                      autonomy=s.get("autonomy", ALERT), handoff_reason=s.get("handoff_reason"),
                      log=list(s.get("log") or []))


def resume(graph, thread_id: str, decision: str, worker: str | None = None) -> dict:
    """human_in_loop 그래프를 작업자 결정으로 이어서 끝낸다."""
    return graph.invoke(Command(resume={"decision": decision, "worker": worker}),
                        {"configurable": {"thread_id": thread_id}})
