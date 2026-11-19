"""
가상 ERP 서비스 (경영 · 계획 계층, ISA-95 레벨 4).

실행 (python 폴더에서):  .venv\\Scripts\\python -m erp.app      → http://localhost:8090/erp/...
대시보드의 'ERP · 경영' 화면이 /erp 로 이 서비스를 부른다 (Vite 프록시).

이 단계(가상 ERP 최소판)에서 하는 일
- 품목 · 배합비(BOM) · 표준 원가 조회
- 판매 주문 등록 → 생산 계획: 자재 소요량 · 재고 할당 · 부족분 구매 발주 · 일정 · 납기 리스크
- 구매 입고 → 재고 반영, 그 자재를 기다리던 생산 오더의 일정 다시 계산
- 경영 요약 (미결 주문, 납기 위험, 재고 금액, 발주 금액)
- MES 연계: 생산 오더를 현장에 지시(POST 백엔드 /api/mes/jobs) → MES 가 배치마다 실적을 올리면
  원료 · 포장재를 BOM 표준량으로 출고(백플러시)하고 완제품을 입고한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import psycopg
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db, planning

app = FastAPI(title="가상 ERP (캡슐 세제)", docs_url="/erp/docs", openapi_url="/erp/openapi.json")

ACTIVE_PRODUCTION = ("PLANNED", "RELEASED", "IN_PROGRESS")


def conn() -> psycopg.Connection:
    return db.connect()


def num(v) -> float:
    return float(v) if v is not None else 0.0


def items_master(c) -> dict[str, dict]:
    rows = c.execute("SELECT * FROM erp.item ORDER BY type DESC, code").fetchall()
    return {r["code"]: {"code": r["code"], "name": r["name"], "type": r["type"], "uom": r["uom"],
                        "unitCost": num(r["unit_cost"]), "leadTimeDays": r["lead_time_days"],
                        "safetyStock": num(r["safety_stock"])} for r in rows}


def available_stock(c) -> dict[str, float]:
    return {r["item_code"]: num(r["on_hand"]) - num(r["allocated"])
            for r in c.execute("SELECT * FROM erp.inventory").fetchall()}


def line_free_from(c, today: date, exclude_id: int | None = None) -> date:
    """라인이 비는 날: 진행 중 · 계획된 생산 오더 중 가장 늦게 끝나는 날의 다음 날."""
    row = c.execute("SELECT max(planned_end) AS last FROM erp.production_order"
                    " WHERE status = ANY(%s) AND (%s::bigint IS NULL OR id <> %s)",
                    (list(ACTIVE_PRODUCTION), exclude_id, exclude_id)).fetchone()
    return max(today, row["last"] + timedelta(days=1)) if row["last"] else today


# ------------------------------------------------------------------ 조회

@app.get("/erp/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/erp/items")
def items() -> list[dict]:
    with conn() as c:
        return list(items_master(c).values())


@app.get("/erp/items/{code}/cost")
def item_cost(code: str) -> dict:
    """표준 원가: 배합비 × 단가 + 가공비 (원/파우치)."""
    with conn() as c:
        master = items_master(c)
        if code not in planning.md.BOM:
            raise HTTPException(404, f"완제품 {code} 가 없습니다")
        cost = planning.standard_cost(code, {k: v["unitCost"] for k, v in master.items()})
        for line in cost["lines"]:
            line["name"], line["uom"] = master[line["itemCode"]]["name"], master[line["itemCode"]]["uom"]
        return {**cost, "name": master[code]["name"]}


@app.get("/erp/inventory")
def inventory() -> list[dict]:
    with conn() as c:
        master = items_master(c)
        rows = c.execute("SELECT * FROM erp.inventory").fetchall()
        out = []
        for r in rows:
            m = master[r["item_code"]]
            on_hand, allocated, quarantine = num(r["on_hand"]), num(r["allocated"]), num(r["quarantine"])
            out.append({**m, "onHand": on_hand, "allocated": allocated, "available": on_hand - allocated,
                        "quarantine": quarantine, "value": round(on_hand * m["unitCost"]),
                        "belowSafety": m["type"] != "FG" and on_hand - allocated < m["safetyStock"]})
        return sorted(out, key=lambda x: (x["type"] != "FG", x["type"], x["code"]))


def order_progress(c, so: dict) -> dict:
    """
    판매 주문 1건의 생산 · 품질 상태: 생산 오더(재생산 포함)를 모아 양품 · 보류 · 폐기 수량, 종료 예정, 납기 위험.
    양품 = 생산 - 폐기 - 품질 보류. 출하하려면 양품이 주문 수량 이상이고 보류가 없어야 한다.
    """
    prods = c.execute("SELECT * FROM erp.production_order WHERE sales_order_id = %s ORDER BY id", (so["id"],)).fetchall()
    held = c.execute("""
        SELECT coalesce(sum(h.qty), 0) AS qty, count(*) AS n FROM erp.quality_hold h
          JOIN erp.production_order p ON p.id = h.production_order_id
         WHERE p.sales_order_id = %s AND h.status = 'HELD'""", (so["id"],)).fetchone()
    produced = sum(p["produced_qty"] for p in prods)
    scrapped = sum(p["scrapped_qty"] for p in prods)
    held_qty = int(held["qty"])
    good = produced - scrapped - held_qty
    reasons = [p["risk_reason"] for p in prods if p["at_risk"] and p["risk_reason"]
               and p["status"] in ("PLANNED", "RELEASED", "IN_PROGRESS")]
    if held["n"]:
        reasons.insert(0, f"품질 보류 {held_qty:,}파우치 (검사 판정 대기)")
    open_prods = [p for p in prods if p["status"] in ("PLANNED", "RELEASED", "IN_PROGRESS")]
    planned_end = max((p["planned_end"] for p in open_prods), default=None) or max(
        (p["planned_end"] for p in prods), default=None)
    late = bool(planned_end and so["status"] != "SHIPPED" and planned_end > so["due_date"] and open_prods)
    return {"productionNos": [p["order_no"] for p in prods], "plannedEnd": planned_end,
            "producedQty": produced, "scrappedQty": scrapped, "heldQty": held_qty, "goodQty": max(0, good),
            "atRisk": so["status"] != "SHIPPED" and (bool(held["n"]) or late or bool(reasons)),
            "riskReason": " · ".join(reasons) or (f"생산 종료 예정 {planned_end}가 납기보다 늦음" if late else None),
            "openProduction": len(open_prods)}


def sales_order_status(c, so: dict) -> str:
    """생산 오더 진행으로 주문 상태를 다시 정한다 (출하된 주문은 그대로)."""
    if so["status"] in ("SHIPPED", "OPEN"):
        return so["status"]
    pr = order_progress(c, so)
    if pr["openProduction"] == 0 and pr["heldQty"] == 0 and pr["goodQty"] >= so["qty"]:
        return "COMPLETED"
    if pr["producedQty"] > 0 or any(
            p["status"] != "PLANNED" for p in c.execute(
                "SELECT status FROM erp.production_order WHERE sales_order_id = %s", (so["id"],)).fetchall()):
        return "IN_PRODUCTION"
    return "PLANNED"


def refresh_sales_order(c, sales_order_id: int | None) -> None:
    if not sales_order_id:
        return
    so = c.execute("SELECT * FROM erp.sales_order WHERE id = %s", (sales_order_id,)).fetchone()
    status = sales_order_status(c, so)
    if status != so["status"]:
        c.execute("UPDATE erp.sales_order SET status = %s WHERE id = %s", (status, sales_order_id))


@app.get("/erp/sales-orders")
def sales_orders() -> list[dict]:
    with conn() as c:
        rows = c.execute("""
            SELECT s.*, i.name AS item_name FROM erp.sales_order s JOIN erp.item i ON i.code = s.item_code
             ORDER BY s.due_date, s.id""").fetchall()
        out = []
        for r in rows:
            pr = order_progress(c, r)
            out.append({"id": r["id"], "orderNo": r["order_no"], "customer": r["customer"], "itemCode": r["item_code"],
                        "itemName": r["item_name"], "qty": r["qty"], "dueDate": r["due_date"], "status": r["status"],
                        "productionNo": ", ".join(pr["productionNos"]) or None, "plannedEnd": pr["plannedEnd"],
                        "atRisk": pr["atRisk"], "riskReason": pr["riskReason"], "producedQty": pr["producedQty"],
                        "goodQty": pr["goodQty"], "heldQty": pr["heldQty"], "scrappedQty": pr["scrappedQty"],
                        "shippedAt": r["shipped_at"],
                        "canShip": r["status"] == "COMPLETED" and pr["heldQty"] == 0 and pr["goodQty"] >= r["qty"]})
        return out


@app.get("/erp/production-orders")
def production_orders() -> list[dict]:
    with conn() as c:
        orders = c.execute("""
            SELECT p.*, s.order_no AS sales_no, s.customer, s.due_date, i.name AS item_name
              FROM erp.production_order p JOIN erp.item i ON i.code = p.item_code
              LEFT JOIN erp.sales_order s ON s.id = p.sales_order_id ORDER BY p.planned_start, p.id""").fetchall()
        materials = c.execute("SELECT * FROM erp.production_material ORDER BY item_code").fetchall()
        by_order: dict[int, list] = {}
        for m in materials:
            by_order.setdefault(m["production_order_id"], []).append(
                {"itemCode": m["item_code"], "required": num(m["required"]), "allocated": num(m["allocated"]),
                 "shortage": num(m["shortage"])})
        return [{"id": p["id"], "orderNo": p["order_no"], "salesNo": p["sales_no"], "customer": p["customer"],
                 "itemCode": p["item_code"], "itemName": p["item_name"], "qty": p["qty"], "batches": p["batches"],
                 "materialReady": p["material_ready"], "plannedStart": p["planned_start"],
                 "plannedEnd": p["planned_end"], "dueDate": p["due_date"], "atRisk": p["at_risk"],
                 "riskReason": p["risk_reason"], "plannedCost": p["planned_cost"], "status": p["status"],
                 "producedQty": p["produced_qty"], "batchesDone": p["batches_done"],
                 "scrappedQty": p["scrapped_qty"], "reworkOf": p["rework_of"],
                 "materials": by_order.get(p["id"], [])} for p in orders]


@app.get("/erp/purchase-orders")
def purchase_orders() -> list[dict]:
    with conn() as c:
        rows = c.execute("""
            SELECT o.*, i.name AS item_name, i.uom, p.order_no AS production_no
              FROM erp.purchase_order o JOIN erp.item i ON i.code = o.item_code
              LEFT JOIN erp.production_order p ON p.id = o.production_order_id
             ORDER BY o.status, o.expected_date, o.id""").fetchall()
        return [{"id": r["id"], "orderNo": r["order_no"], "itemCode": r["item_code"], "itemName": r["item_name"],
                 "uom": r["uom"], "qty": num(r["qty"]), "unitCost": num(r["unit_cost"]),
                 "amount": round(num(r["qty"]) * num(r["unit_cost"])), "expectedDate": r["expected_date"],
                 "status": r["status"], "productionNo": r["production_no"], "receivedAt": r["received_at"]}
                for r in rows]


@app.get("/erp/summary")
def summary() -> dict:
    """경영 요약: 화면 상단 숫자들."""
    inv = inventory()
    so = sales_orders()
    po = purchase_orders()
    return {
        "openOrders": sum(1 for s in so if s["status"] != "SHIPPED"),
        "unplannedOrders": sum(1 for s in so if s["status"] == "OPEN"),
        "atRiskOrders": sum(1 for s in so if s["atRisk"]),
        "openOrderQty": sum(s["qty"] for s in so if s["status"] != "SHIPPED"),
        "inventoryValue": sum(i["value"] for i in inv),
        "belowSafety": [i["code"] for i in inv if i["belowSafety"]],
        "openPurchaseAmount": sum(p["amount"] for p in po if p["status"] == "OPEN"),
        "openPurchases": sum(1 for p in po if p["status"] == "OPEN"),
        "quarantineQty": sum(i["quarantine"] for i in inv if i["type"] == "FG"),
        "heldOrders": sum(1 for s in so if s["heldQty"] > 0),
    }


# ------------------------------------------------------------------ 변경

class SalesOrderRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=100)
    itemCode: str
    qty: int = Field(gt=0, le=1_000_000)
    dueDate: date


@app.post("/erp/sales-orders", status_code=201)
def create_sales_order(req: SalesOrderRequest) -> dict:
    with conn() as c:
        if req.itemCode not in planning.md.BOM:
            raise HTTPException(422, f"판매할 수 있는 완제품이 아닙니다: {req.itemCode}")
        row = c.execute("INSERT INTO erp.sales_order (customer, item_code, qty, due_date, status)"
                        " VALUES (%s, %s, %s, %s, 'OPEN') RETURNING id",
                        (req.customer.strip(), req.itemCode, req.qty, req.dueDate)).fetchone()
        c.execute("UPDATE erp.sales_order SET order_no = %s WHERE id = %s", (f"SO-{row['id']:04d}", row["id"]))
        c.commit()
    return next(s for s in sales_orders() if s["id"] == row["id"])


@app.post("/erp/sales-orders/{order_id}/plan")
def plan_sales_order(order_id: int) -> dict:
    """주문 → 생산 오더 1건: 자재 할당, 부족분 구매 발주, 일정과 납기 리스크."""
    today = date.today()
    with conn() as c:
        so = c.execute("SELECT * FROM erp.sales_order WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
        if so is None:
            raise HTTPException(404, f"주문 #{order_id} 가 없습니다")
        if so["status"] != "OPEN":
            raise HTTPException(409, f"이미 계획된 주문입니다 ({so['status']})")
        prod_id, prod_no = create_production_order(c, order_id, so["item_code"], so["qty"], so["due_date"], today)
        c.execute("UPDATE erp.sales_order SET status = 'PLANNED' WHERE id = %s", (order_id,))
        c.commit()
    return {"productionOrder": next(p for p in production_orders() if p["id"] == prod_id),
            "purchaseOrders": [p for p in purchase_orders() if p["productionNo"] == prod_no]}


def create_production_order(c, sales_order_id: int, item_code: str, qty: int, due: date, today: date,
                            rework_of: int | None = None) -> tuple[int, str]:
    """생산 오더 1건을 계획해 저장한다: 자재 할당 · 부족분 발주 · 일정 · 납기 리스크. 재생산 오더도 이 길을 쓴다."""
    master = items_master(c)
    plan = planning.plan_order(item_code, qty, due, today, available_stock(c), master, line_free_from(c, today))
    prod = c.execute("""
        INSERT INTO erp.production_order (sales_order_id, item_code, qty, batches, material_ready, planned_start,
               planned_end, at_risk, risk_reason, planned_cost, status, rework_of)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PLANNED', %s) RETURNING id""",
                     (sales_order_id, plan.item_code, plan.qty, plan.batches, plan.material_ready, plan.start, plan.end,
                      plan.at_risk, plan.risk_reason, plan.planned_cost, rework_of)).fetchone()
    prod_no = f"PRD-{prod['id']:04d}"
    c.execute("UPDATE erp.production_order SET order_no = %s WHERE id = %s", (prod_no, prod["id"]))
    for line in plan.lines:
        c.execute("INSERT INTO erp.production_material VALUES (%s, %s, %s, %s, %s)",
                  (prod["id"], line.item_code, line.required, line.allocated, line.shortage))
        if line.allocated:
            c.execute("UPDATE erp.inventory SET allocated = allocated + %s WHERE item_code = %s",
                      (line.allocated, line.item_code))
            c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'ALLOCATE', %s, %s)",
                      (line.item_code, line.allocated, prod_no))
    for line in plan.purchases:
        po = c.execute("""
            INSERT INTO erp.purchase_order (item_code, qty, unit_cost, expected_date, status, production_order_id)
            VALUES (%s, %s, %s, %s, 'OPEN', %s) RETURNING id""",
                       (line.item_code, line.purchase_qty, master[line.item_code]["unitCost"], line.ready_date,
                        prod["id"])).fetchone()
        c.execute("UPDATE erp.purchase_order SET order_no = %s WHERE id = %s", (f"PUR-{po['id']:04d}", po["id"]))
    return prod["id"], prod_no


@app.post("/erp/purchase-orders/{order_id}/receive")
def receive_purchase(order_id: int) -> dict:
    """구매 입고: 재고에 더하고, 그 자재가 모자랐던 생산 오더에 할당한 뒤 일정을 다시 계산한다."""
    today = date.today()
    with conn() as c:
        po = c.execute("SELECT * FROM erp.purchase_order WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
        if po is None:
            raise HTTPException(404, f"발주 #{order_id} 가 없습니다")
        if po["status"] != "OPEN":
            raise HTTPException(409, "이미 입고된 발주입니다")
        code, qty = po["item_code"], num(po["qty"])
        c.execute("UPDATE erp.inventory SET on_hand = on_hand + %s WHERE item_code = %s", (qty, code))
        c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'RECEIPT', %s, %s)",
                  (code, qty, po["order_no"]))
        c.execute("UPDATE erp.purchase_order SET status = 'RECEIVED', received_at = now() WHERE id = %s", (order_id,))
        # 이 자재를 기다리던 생산 오더(먼저 만든 순)에 부족분을 채운다
        waiting = c.execute("""
            SELECT m.* FROM erp.production_material m JOIN erp.production_order p ON p.id = m.production_order_id
             WHERE m.item_code = %s AND m.shortage > 0 AND p.status = ANY(%s) ORDER BY p.id""",
                            (code, list(ACTIVE_PRODUCTION))).fetchall()
        free = available_stock(c)[code]
        touched = []
        for m in waiting:
            fill = min(free, num(m["shortage"]))
            if fill <= 0:
                break
            free -= fill
            c.execute("UPDATE erp.production_material SET allocated = allocated + %s, shortage = shortage - %s"
                      " WHERE production_order_id = %s AND item_code = %s",
                      (fill, fill, m["production_order_id"], code))
            c.execute("UPDATE erp.inventory SET allocated = allocated + %s WHERE item_code = %s", (fill, code))
            touched.append(m["production_order_id"])
        for pid in touched:
            _reschedule(c, pid, today)
        c.commit()
    return {"purchaseOrder": next(p for p in purchase_orders() if p["id"] == order_id), "rescheduled": touched}


def _reschedule(c, production_id: int, today: date) -> None:
    """자재가 들어온 생산 오더의 시작 · 종료 · 납기 리스크를 다시 계산한다 (아직 다른 자재를 기다리면 그 입고 예정일)."""
    p = c.execute("SELECT p.*, s.due_date FROM erp.production_order p LEFT JOIN erp.sales_order s"
                  " ON s.id = p.sales_order_id WHERE p.id = %s", (production_id,)).fetchone()
    open_pos = c.execute("SELECT item_code, expected_date FROM erp.purchase_order"
                         " WHERE production_order_id = %s AND status = 'OPEN'", (production_id,)).fetchall()
    pending = max((po["expected_date"] for po in open_pos), default=None)
    material_ready = max(today, pending) if pending else today
    line_free = line_free_from(c, today, exclude_id=production_id)
    start = max(material_ready, line_free)
    days = planning.production_days(p["item_code"], p["qty"])
    end = start + timedelta(days=days - 1)
    due = p["due_date"]
    at_risk = bool(due and end > due)
    reason = None
    if at_risk:
        blockers = [po["item_code"] for po in open_pos if po["expected_date"] == pending]
        reason = (f"자재 입고 대기({', '.join(blockers)})로 납기보다 {(end - due).days}일 늦게 끝남"
                  if pending and material_ready >= line_free and blockers
                  else f"라인 일정이 밀려 납기보다 {(end - due).days}일 늦게 끝남")
    c.execute("UPDATE erp.production_order SET material_ready = %s, planned_start = %s, planned_end = %s,"
              " at_risk = %s, risk_reason = %s WHERE id = %s",
              (material_ready, start, end, at_risk, reason, production_id))


# ------------------------------------------------------------------ MES 연계 (ISA-95 레벨 4 ↔ 3)

MES_BASE_URL = os.environ.get("MES_BASE_URL", "http://localhost:8080")


@app.post("/erp/production-orders/{order_id}/release")
def release_to_mes(order_id: int) -> dict:
    """
    생산 오더를 현장(MES)에 지시한다. 자재가 다 할당된 오더만 내려보낸다 (모자라면 입고 뒤에).
    MES 가 받으면 RELEASED. MES 가 꺼져 있으면 502 이고 오더는 그대로 계획 상태로 남는다.
    """
    with conn() as c:
        p = c.execute("SELECT p.*, i.name AS item_name FROM erp.production_order p JOIN erp.item i ON i.code = p.item_code"
                      " WHERE p.id = %s FOR UPDATE OF p", (order_id,)).fetchone()
        if p is None:
            raise HTTPException(404, f"생산 오더 #{order_id} 가 없습니다")
        if p["status"] != "PLANNED":
            raise HTTPException(409, f"이미 현장에 지시한 오더입니다 ({p['status']})")
        short = c.execute("SELECT item_code FROM erp.production_material WHERE production_order_id = %s AND shortage > 0",
                          (order_id,)).fetchall()
        if short:
            raise HTTPException(409, "자재가 모자라 지시할 수 없습니다 (입고 뒤에 지시): "
                                     + ", ".join(r["item_code"] for r in short))
        payload = {"erpOrderNo": p["order_no"], "itemCode": p["item_code"], "itemName": p["item_name"],
                   "qty": p["qty"], "batches": p["batches"], "plannedStart": p["planned_start"].isoformat()}
        try:
            req = urllib.request.Request(f"{MES_BASE_URL}/api/mes/jobs", method="POST",
                                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json; charset=utf-8"})
            with urllib.request.urlopen(req, timeout=5) as r:
                job = json.load(r)
        except (urllib.error.URLError, ValueError) as e:
            raise HTTPException(502, f"MES(현장 시스템)에 지시하지 못했습니다: {e}") from e
        c.execute("UPDATE erp.production_order SET status = 'RELEASED' WHERE id = %s", (order_id,))
        if p["sales_order_id"]:
            c.execute("UPDATE erp.sales_order SET status = 'IN_PRODUCTION' WHERE id = %s", (p["sales_order_id"],))
        c.commit()
    return {"productionOrder": next(x for x in production_orders() if x["id"] == order_id), "mesJobId": job.get("id")}


class ActualRequest(BaseModel):
    batchId: str = Field(min_length=1, max_length=32)
    seq: int = Field(ge=1)
    qty: int = Field(gt=0)
    completedAt: datetime | None = None


@app.post("/erp/production-orders/{order_no}/actuals")
def receive_actual(order_no: str, req: ActualRequest) -> dict:
    """
    MES 가 올린 배치 1개의 생산 실적. 원료 · 포장재는 BOM 표준량으로 출고(백플러시)하고 완제품을 입고한다.
    같은 배치 번호가 다시 오면 아무것도 하지 않는다 (MES 가 다시 보내도 재고가 두 번 빠지지 않게).
    """
    with conn() as c:
        p = c.execute("SELECT * FROM erp.production_order WHERE order_no = %s FOR UPDATE", (order_no,)).fetchone()
        if p is None:
            raise HTTPException(404, f"생산 오더 {order_no} 가 없습니다")
        if c.execute("SELECT 1 FROM erp.production_actual WHERE batch_id = %s", (req.batchId,)).fetchone():
            return {"duplicate": True, "batchId": req.batchId}
        c.execute("INSERT INTO erp.production_actual (batch_id, production_order_id, seq, qty, completed_at)"
                  " VALUES (%s, %s, %s, %s, %s)", (req.batchId, p["id"], req.seq, req.qty, req.completedAt))
        for code, used in planning.requirements(p["item_code"], req.qty).items():
            # 이 오더에 할당해 둔 수량에서 먼저 빼고, 현재고에서 출고한다
            m = c.execute("SELECT allocated FROM erp.production_material WHERE production_order_id = %s"
                          " AND item_code = %s", (p["id"], code)).fetchone()
            release = min(used, num(m["allocated"])) if m else 0.0
            if m:
                c.execute("UPDATE erp.production_material SET allocated = allocated - %s"
                          " WHERE production_order_id = %s AND item_code = %s", (release, p["id"], code))
            c.execute("UPDATE erp.inventory SET on_hand = on_hand - %s, allocated = allocated - %s WHERE item_code = %s",
                      (used, release, code))
            c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'ISSUE', %s, %s)",
                      (code, used, req.batchId))
        c.execute("UPDATE erp.inventory SET on_hand = on_hand + %s WHERE item_code = %s", (req.qty, p["item_code"]))
        c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'RECEIPT', %s, %s)",
                  (p["item_code"], req.qty, req.batchId))
        produced = p["produced_qty"] + req.qty
        status = "COMPLETED" if produced >= p["qty"] else "IN_PROGRESS"
        c.execute("UPDATE erp.production_order SET produced_qty = %s, batches_done = batches_done + 1, status = %s"
                  " WHERE id = %s", (produced, status, p["id"]))
        # 품질팀이 배치가 끝나기 전에 홀드를 확정했으면 그 기록을 적용한다 (보류 · 해제 · 폐기)
        hold = c.execute("SELECT * FROM erp.quality_hold WHERE batch_id = %s", (req.batchId,)).fetchone()
        if hold:
            c.execute("UPDATE erp.quality_hold SET qty = %s, production_order_id = %s WHERE batch_id = %s",
                      (req.qty, p["id"], req.batchId))
            if hold["status"] in ("HELD", "SCRAPPED"):
                _quarantine(c, p["item_code"], req.qty, req.batchId)
            if hold["status"] == "SCRAPPED":
                _scrap(c, p, req.qty, req.batchId, date.today())
        refresh_sales_order(c, p["sales_order_id"])
        c.commit()
    print(f"[ERP] actual {req.batchId}: {order_no} +{req.qty} ({produced}/{p['qty']}, {status})", flush=True)
    return {"duplicate": False, "batchId": req.batchId, "producedQty": produced, "status": status}


# ------------------------------------------------------------------ 품질 연계 · 출하

def _quarantine(c, item_code: str, qty: int, ref: str) -> None:
    """완제품을 가용 재고에서 품질 보류 재고로 옮긴다."""
    c.execute("UPDATE erp.inventory SET on_hand = on_hand - %s, quarantine = quarantine + %s WHERE item_code = %s",
              (qty, qty, item_code))
    c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'QUARANTINE', %s, %s)",
              (item_code, qty, ref))


def _scrap(c, prod: dict, qty: int, batch_id: str, today: date) -> str | None:
    """보류 재고를 폐기하고, 그 수량만큼 재생산 오더를 계획한다. 재생산 오더 번호를 돌려준다."""
    c.execute("UPDATE erp.inventory SET quarantine = quarantine - %s WHERE item_code = %s", (qty, prod["item_code"]))
    c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'SCRAP', %s, %s)",
              (prod["item_code"], qty, batch_id))
    c.execute("UPDATE erp.production_order SET scrapped_qty = scrapped_qty + %s WHERE id = %s", (qty, prod["id"]))
    if not prod["sales_order_id"]:
        return None
    so = c.execute("SELECT * FROM erp.sales_order WHERE id = %s", (prod["sales_order_id"],)).fetchone()
    _, rework_no = create_production_order(c, so["id"], prod["item_code"], qty, so["due_date"], today,
                                           rework_of=prod["id"])
    print(f"[ERP] batch {batch_id} scrapped: {qty} pouches, rework order {rework_no} planned", flush=True)
    return rework_no


class HoldRequest(BaseModel):
    batchId: str = Field(min_length=1, max_length=32)
    assessmentId: int | None = None
    reason: str | None = None
    approvedBy: str | None = None


@app.post("/erp/quality-holds")
def quality_hold(req: HoldRequest) -> dict:
    """
    MES: 품질팀이 배치 홀드를 확정했다. 그 배치의 완제품을 품질 보류 재고로 옮긴다.
    배치 실적이 아직 안 왔으면 기억해 두었다가 실적이 올 때 보류로 받는다. 같은 배치를 다시 보내면 무시한다.
    """
    with conn() as c:
        if c.execute("SELECT 1 FROM erp.quality_hold WHERE batch_id = %s", (req.batchId,)).fetchone():
            return {"duplicate": True, "batchId": req.batchId}
        actual = c.execute("SELECT a.*, p.item_code, p.sales_order_id FROM erp.production_actual a"
                           " JOIN erp.production_order p ON p.id = a.production_order_id WHERE a.batch_id = %s",
                           (req.batchId,)).fetchone()
        c.execute("INSERT INTO erp.quality_hold (batch_id, assessment_id, reason, approved_by, status, qty,"
                  " production_order_id) VALUES (%s, %s, %s, %s, 'HELD', %s, %s)",
                  (req.batchId, req.assessmentId, (req.reason or "")[:500], req.approvedBy,
                   actual["qty"] if actual else None, actual["production_order_id"] if actual else None))
        if actual:
            _quarantine(c, actual["item_code"], actual["qty"], req.batchId)
            refresh_sales_order(c, actual["sales_order_id"])
        c.commit()
    print(f"[ERP] quality hold {req.batchId}" + (f": {actual['qty']} pouches quarantined" if actual else
                                                 " (batch not reported yet)"), flush=True)
    return {"duplicate": False, "batchId": req.batchId, "quarantined": actual["qty"] if actual else 0}


class DispositionRequest(BaseModel):
    result: str = Field(pattern="^(PASS|FAIL)$")
    by: str | None = None
    note: str | None = None


@app.post("/erp/quality-holds/{batch_id}/disposition")
def quality_disposition(batch_id: str, req: DispositionRequest) -> dict:
    """
    MES: 홀드 배치의 검사 판정. 합격이면 보류 재고를 가용 재고로 돌리고, 불합격이면 폐기하고
    모자란 수량만큼 재생산 오더를 계획한다 (자재 할당 · 발주 · 일정 · 납기 위험을 다시 계산).
    """
    today = date.today()
    rework_no = None
    with conn() as c:
        hold = c.execute("SELECT * FROM erp.quality_hold WHERE batch_id = %s FOR UPDATE", (batch_id,)).fetchone()
        if hold is None:
            raise HTTPException(404, f"보류 중인 배치가 아닙니다: {batch_id}")
        if hold["status"] != "HELD":
            return {"duplicate": True, "batchId": batch_id, "status": hold["status"]}
        status = "RELEASED" if req.result == "PASS" else "SCRAPPED"
        c.execute("UPDATE erp.quality_hold SET status = %s, decided_at = now(), note = %s WHERE batch_id = %s",
                  (status, (req.note or "")[:500], batch_id))
        if hold["qty"]:   # 실적이 이미 와서 보류 재고에 있다 (아니면 실적이 올 때 적용된다)
            prod = c.execute("SELECT * FROM erp.production_order WHERE id = %s", (hold["production_order_id"],)).fetchone()
            if status == "RELEASED":
                c.execute("UPDATE erp.inventory SET quarantine = quarantine - %s, on_hand = on_hand + %s"
                          " WHERE item_code = %s", (hold["qty"], hold["qty"], prod["item_code"]))
                c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'RELEASE', %s, %s)",
                          (prod["item_code"], hold["qty"], batch_id))
            else:
                rework_no = _scrap(c, prod, hold["qty"], batch_id, today)
            refresh_sales_order(c, prod["sales_order_id"])
        c.commit()
    print(f"[ERP] quality disposition {batch_id}: {req.result}", flush=True)
    return {"duplicate": False, "batchId": batch_id, "status": status, "reworkOrder": rework_no}


@app.post("/erp/sales-orders/{order_id}/ship")
def ship(order_id: int) -> dict:
    """출하: 생산이 끝나고, 품질 보류가 없고, 양품 · 가용 완제품이 주문 수량 이상이어야 한다."""
    with conn() as c:
        so = c.execute("SELECT * FROM erp.sales_order WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
        if so is None:
            raise HTTPException(404, f"주문 #{order_id} 가 없습니다")
        if so["status"] == "SHIPPED":
            raise HTTPException(409, "이미 출하한 주문입니다")
        pr = order_progress(c, so)
        if pr["heldQty"]:
            raise HTTPException(409, f"출하 보류: 품질 보류 {pr['heldQty']:,}파우치가 검사 판정을 기다립니다")
        if so["status"] != "COMPLETED" or pr["goodQty"] < so["qty"]:
            raise HTTPException(409, f"출하할 양품이 모자랍니다 (양품 {pr['goodQty']:,} / 주문 {so['qty']:,}파우치)")
        stock = c.execute("SELECT on_hand FROM erp.inventory WHERE item_code = %s", (so["item_code"],)).fetchone()
        if num(stock["on_hand"]) < so["qty"]:
            raise HTTPException(409, f"가용 완제품이 모자랍니다 ({num(stock['on_hand']):,.0f}파우치)")
        c.execute("UPDATE erp.inventory SET on_hand = on_hand - %s WHERE item_code = %s", (so["qty"], so["item_code"]))
        c.execute("INSERT INTO erp.inventory_txn (item_code, kind, qty, ref) VALUES (%s, 'SHIP', %s, %s)",
                  (so["item_code"], so["qty"], so["order_no"]))
        c.execute("UPDATE erp.sales_order SET status = 'SHIPPED', shipped_at = now() WHERE id = %s", (order_id,))
        c.commit()
    return next(s for s in sales_orders() if s["id"] == order_id)


@app.post("/erp/reset")
def reset() -> dict:
    """데모용: 기초 데이터로 되돌린다."""
    with conn() as c:
        db.reset(c)
    return {"status": "reset"}


def main() -> None:
    with db.connect() as c:
        created = db.ensure_schema(c)
    print(f"erp schema {'created with seed data' if created else 'ready'}")
    uvicorn.run(app, host="127.0.0.1", port=8090, log_level="info")


if __name__ == "__main__":
    main()
