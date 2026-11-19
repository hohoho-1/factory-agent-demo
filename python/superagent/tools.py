"""
SuperAgent 가 부를 수 있는 도구 (모두 읽기 전용). 네 묶음이 IR 의 하위 에이전트 · 플랫폼에 대응한다.

  ERP  (경영 · 계획, 가상 ERP :8090)   주문 · 생산 오더 · 재고 · 구매 발주 · 표준 원가
  MES  (현장 실행, 백엔드 :8080)        생산 지시 · 배치 · 배합기 상태(세정 · 전환) · 배치 기록
  품질 (백엔드)                         품질 판정 · 홀드 · 검사 판정
  설비 (백엔드)                         알람 · AI 조치 지시서 · 조치 이력 통계

도구는 각 시스템의 API 를 GET 으로만 부르고, 응답을 Claude 가 읽기 좋게 줄여서 돌려준다.
쓰기 · 승인 · 실행 도구는 일부러 없다: SuperAgent 는 조회와 분석 · 제안만 하고, 실행은 사람이 화면에서 한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

# Windows 에서 localhost 는 IPv6(::1)를 먼저 시도해 요청마다 약 2초 늦어진다. ERP(uvicorn)는 127.0.0.1 에만 열려 있다
ERP = os.environ.get("ERP_BASE_URL", "http://127.0.0.1:8090")
MES = os.environ.get("MES_BASE_URL", "http://127.0.0.1:8080")
MAX_RESULT_CHARS = 6000  # 도구 결과 1건의 최대 길이 (긴 목록이 문맥을 다 차지하지 않게)


def _get(base: str, path: str, params: dict | None = None):
    url = base + path + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v}) if params else "")
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.load(r)


def _pick(rows: list[dict], keys: list[str], limit: int = 30) -> list[dict]:
    return [{k: r.get(k) for k in keys} for r in rows[:limit]]


@dataclass(frozen=True)
class Tool:
    name: str
    group: str            # ERP / MES / 품질 / 설비 (화면 실행 기록에 표시)
    description: str
    properties: dict
    run: Callable[[dict], object]

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "strict": True,
                "input_schema": {"type": "object", "properties": self.properties,
                                 "required": list(self.properties), "additionalProperties": False}}


def _opt_str(desc: str) -> dict:
    return {"type": ["string", "null"], "description": desc}


TOOLS = [
    # ------------------------------------------------------------------ ERP
    Tool("erp_sales_orders", "ERP",
         "판매 주문 목록: 고객, 품목, 수량, 납기, 상태(계획 전/생산 계획됨/생산 중/생산 완료/출하), 생산 오더 번호, "
         "양품 · 품질 보류 · 폐기 수량, 납기 위험 여부와 이유, 출하 가능 여부.", {},
         lambda a: _pick(_get(ERP, "/erp/sales-orders"),
                         ["orderNo", "customer", "itemName", "qty", "dueDate", "status", "productionNo", "plannedEnd",
                          "goodQty", "heldQty", "scrappedQty", "atRisk", "riskReason", "canShip"])),
    Tool("erp_production_orders", "ERP",
         "생산 오더 목록: 주문, 품목, 수량, 배합 배치 수, 자재 확보일, 계획 시작 · 종료, 납기, 납기 위험 이유, 계획 원가, "
         "상태, 생산 · 폐기 수량, 재생산 오더 여부(reworkOf), 부족 자재.", {},
         lambda a: [{**{k: p.get(k) for k in ["orderNo", "salesNo", "itemName", "qty", "batches", "batchesDone",
                                              "materialReady", "plannedStart", "plannedEnd", "dueDate", "atRisk",
                                              "riskReason", "plannedCost", "status", "producedQty", "scrappedQty",
                                              "reworkOf"]},
                     "shortages": [f"{m['itemCode']} {m['shortage']}" for m in p.get("materials", []) if m["shortage"]]}
                    for p in _get(ERP, "/erp/production-orders")[:30]]),
    Tool("erp_inventory", "ERP",
         "재고: 품목별 현재고, 생산 오더에 할당된 수량, 가용, 품질 보류(완제품), 안전재고 미달 여부, 재고 금액. "
         "item_code 를 주면 그 품목만.", {"item_code": _opt_str("품목 코드 (예: RM-EZ, CAP-A30). 전체면 null")},
         lambda a: [s for s in _pick(_get(ERP, "/erp/inventory"),
                                     ["code", "name", "type", "uom", "onHand", "allocated", "available", "quarantine",
                                      "safetyStock", "belowSafety", "value"], 60)
                    if not a.get("item_code") or s["code"] == a["item_code"]]),
    Tool("erp_purchase_orders", "ERP",
         "구매 발주 목록: 자재, 수량, 금액, 입고 예정일, 상태(미입고/입고), 어느 생산 오더 때문에 나갔는지. "
         "발주 수량 = 부족분 + 그 자재의 안전재고 (부족분보다 많은 것이 정상), 입고 예정일 = 발주일 + 리드타임.", {},
         lambda a: _pick(_get(ERP, "/erp/purchase-orders"),
                         ["orderNo", "itemName", "qty", "uom", "amount", "expectedDate", "status", "productionNo"])),
    Tool("erp_standard_cost", "ERP",
         "완제품 1파우치의 표준 원가: 자재비(배합비 × 단가) 줄별 금액, 가공비, 합계.",
         {"item_code": {"type": "string", "description": "완제품 코드: CAP-A30 또는 CAP-B15"}},
         lambda a: _get(ERP, f"/erp/items/{urllib.parse.quote(a['item_code'])}/cost")),
    # ------------------------------------------------------------------ MES
    Tool("mes_jobs", "MES",
         "현장 생산 지시(ERP 생산 오더를 MES 가 받은 것): 계획 시작일, 배치 진행(완료/전체), 생산 수량, 배치별 상태 "
         "(PLC 요청 중/진행/완료/PLC 거부), ERP 실적 보고 여부, 순서 변경 · 책임자 승인 기록.", {},
         lambda a: [{**{k: j.get(k) for k in ["erpOrderNo", "itemName", "qty", "plannedStart", "batchesDone",
                                              "batchesTotal", "producedQty", "status"]},
                     "batches": [{k: b.get(k) for k in ["batchId", "qty", "status", "message", "completedAt",
                                                        "reportedAt", "outOfOrder", "supervisorBy", "supervisorReason"]}
                                 for b in j.get("batches", [])]}
                    for j in _get(MES, "/api/mes/jobs")]),
    Tool("mes_line_state", "MES",
         "배합기 상태: 진행 중 배치(단계 · 레시피), 마지막으로 만든 품목, 제품 전환 상태"
         "(같은 품목만 가능/세정 중/세정 완료 · 클리어런스 대기/어떤 품목이든 가능).", {},
         lambda a: {"batch": next((s for s in _get(MES, "/api/batch/state") if s["equipmentId"] == "MIXER-01"), None),
                    "line": _get(MES, "/api/mes/line")}),
    Tool("mes_batch_record", "MES",
         "배치 기록 한 장: 단계별 소요 시간과 지표 범위, 배치 중 알람 · 지시서 · 설정값 변경 · 품질 판정, 판정 요약(출하 보류 등).",
         {"batch_id": {"type": "string", "description": "배치 번호 (예: PRD-0001-02)"}},
         lambda a: _batch_record(a["batch_id"])),
    # ------------------------------------------------------------------ 품질
    Tool("quality_assessments", "품질",
         "품질 에이전트 판정: 배치, 단계, 지표, 판정(영향 없음/추가 검사/홀드), 근거 규칙, 품질팀 승인 상태, 검사 판정"
         "(합격/불합격), ERP 반영 여부. batch_id 를 주면 그 배치만.",
         {"batch_id": _opt_str("배치 번호. 최근 전체면 null")},
         lambda a: _pick(_get(MES, "/api/quality-assessments", {"batchId": a.get("batch_id")}),
                         ["id", "batchId", "batchPhase", "equipmentId", "metric", "level", "basis", "status",
                          "decidedBy", "disposition", "dispositionNote", "holdReportedAt", "workOrderId", "createdAt"])),
    # ------------------------------------------------------------------ 설비
    Tool("equipment_alarms", "설비",
         "알람 목록: 설비, 지표, 심각도, 상태(진행/해제), 값, 기준, 발생 시각, 배치 · 단계. active_only 가 true 면 진행 중만.",
         {"active_only": {"type": "boolean", "description": "진행 중 알람만 보려면 true"}},
         lambda a: _pick(_get(MES, "/api/alarms", {"status": "ACTIVE" if a.get("active_only") else None}),
                         ["id", "equipmentId", "metric", "severity", "status", "lastValue", "peakValue",
                          "thresholdValue", "raisedAt", "clearedAt", "batchId", "batchPhase"], 20)),
    Tool("equipment_work_orders", "설비",
         "AI 조치 지시서 최근 목록: 알람, 제목, 요약, 상태(미확인/조치 중/완료), 작업자가 남긴 원인 · 조치 · 결과.", {},
         lambda a: _pick(_get(MES, "/api/work-orders"),
                         ["id", "alarmId", "severity", "title", "summary", "status", "rootCause", "actionTaken",
                          "outcome", "createdAt"], 15)),
    Tool("equipment_action_stats", "설비",
         "설비 · 지표별 조치 이력 통계: 이상 횟수, 위험 횟수, 해결률, 평균 처리 시간, 주요 원인.", {},
         lambda a: _get(MES, "/api/action-stats")),
]

BY_NAME = {t.name: t for t in TOOLS}


def _batch_record(batch_id: str) -> object:
    run = next((b for b in _get(MES, "/api/batches") if b["batchId"] == batch_id), None)
    if run is None:
        return {"error": f"배치 기록이 없습니다: {batch_id}"}
    rec = _get(MES, f"/api/batches/{run['id']}/record")
    return {"batch": {k: rec["batch"].get(k) for k in ["batchId", "recipe", "status", "startedAt", "endedAt", "phases"]},
            "alarms": _pick(rec.get("alarms", []), ["id", "metric", "severity", "batchPhase", "peakValue"]),
            "workOrders": _pick(rec.get("workOrders", []), ["id", "title", "status", "rootCause", "outcome"]),
            "quality": _pick(rec.get("qualityAssessments", []), ["level", "status", "disposition", "basis"]),
            "verdict": rec.get("verdict")}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """도구를 실행해 (결과 JSON 문자열, 오류 여부)를 돌려준다. 결과가 너무 길면 자른다고 알린다."""
    tool = BY_NAME.get(name)
    if tool is None:
        return json.dumps({"error": f"없는 도구: {name}"}, ensure_ascii=False), True
    try:
        text = json.dumps(tool.run(args or {}), ensure_ascii=False, default=str)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        return json.dumps({"error": f"{tool.group} 시스템을 조회하지 못했습니다: {e}"}, ensure_ascii=False), True
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f' ... (결과가 길어 {MAX_RESULT_CHARS}자까지만 보냄)'
    return text, False
