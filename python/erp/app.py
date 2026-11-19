"""
가상 ERP 서비스 (경영 · 계획 계층, ISA-95 레벨 4).

실행 (python 폴더에서):  .venv\\Scripts\\python -m erp.app      → http://localhost:8090/erp/...
대시보드의 'ERP · 경영' 화면이 /erp 로 이 서비스를 부른다 (Vite 프록시).

이 단계(가상 ERP 최소판)에서 하는 일
- 품목 · 배합비(BOM) · 표준 원가 조회
- 판매 주문 등록 → 생산 계획: 자재 소요량 · 재고 할당 · 부족분 구매 발주 · 일정 · 납기 리스크
- 구매 입고 → 재고 반영, 그 자재를 기다리던 생산 오더의 일정 다시 계산
- 경영 요약 (미결 주문, 납기 위험, 재고 금액, 발주 금액)
MES(백엔드)와의 연계(생산 오더 → 작업 지시 → 배치 실적)는 다음 단계에서 붙인다.
"""
from __future__ import annotations

from datetime import date, timedelta

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
            on_hand, allocated = num(r["on_hand"]), num(r["allocated"])
            out.append({**m, "onHand": on_hand, "allocated": allocated, "available": on_hand - allocated,
                        "value": round(on_hand * m["unitCost"]),
                        "belowSafety": m["type"] != "FG" and on_hand - allocated < m["safetyStock"]})
        return sorted(out, key=lambda x: (x["type"] != "FG", x["type"], x["code"]))


@app.get("/erp/sales-orders")
def sales_orders() -> list[dict]:
    with conn() as c:
        rows = c.execute("""
            SELECT s.*, i.name AS item_name, p.order_no AS production_no, p.planned_end, p.at_risk, p.risk_reason
              FROM erp.sales_order s JOIN erp.item i ON i.code = s.item_code
              LEFT JOIN erp.production_order p ON p.sales_order_id = s.id
             ORDER BY s.due_date, s.id""").fetchall()
        return [{"id": r["id"], "orderNo": r["order_no"], "customer": r["customer"], "itemCode": r["item_code"],
                 "itemName": r["item_name"], "qty": r["qty"], "dueDate": r["due_date"], "status": r["status"],
                 "productionNo": r["production_no"], "plannedEnd": r["planned_end"], "atRisk": bool(r["at_risk"]),
                 "riskReason": r["risk_reason"]} for r in rows]


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
        master = items_master(c)
        plan = planning.plan_order(so["item_code"], so["qty"], so["due_date"], today, available_stock(c), master,
                                   line_free_from(c, today))
        prod = c.execute("""
            INSERT INTO erp.production_order (sales_order_id, item_code, qty, batches, material_ready, planned_start,
                   planned_end, at_risk, risk_reason, planned_cost, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PLANNED') RETURNING id""",
                         (order_id, plan.item_code, plan.qty, plan.batches, plan.material_ready, plan.start, plan.end,
                          plan.at_risk, plan.risk_reason, plan.planned_cost)).fetchone()
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
        c.execute("UPDATE erp.sales_order SET status = 'PLANNED' WHERE id = %s", (order_id,))
        c.commit()
    return {"productionOrder": next(p for p in production_orders() if p["id"] == prod["id"]),
            "purchaseOrders": [p for p in purchase_orders() if p["productionNo"] == prod_no]}


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
