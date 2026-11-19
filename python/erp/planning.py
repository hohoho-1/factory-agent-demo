"""
가상 ERP 계획 로직 (DB 없이 계산만): 자재 소요량 · 재고 할당 · 부족분 발주 · 일정 · 납기 리스크 · 표준 원가.

실제 ERP의 MRP(자재 소요 계획)를 아주 단순하게 줄인 것이다.
- 소요량 = 주문 수량 × BOM
- 가용 재고 = 현재고 - 다른 생산 오더에 이미 묶인 수량. 가용분만큼 할당하고 모자라면 발주를 만든다
- 발주 수량 = 부족분 + 안전재고 (자재가 다 떨어지지 않게), 입고 예정일 = 오늘 + 리드타임
- 생산 시작 = 앞 생산 오더가 끝나는 날과 자재가 다 들어오는 날 중 늦은 날. 라인은 1개
- 생산 종료 > 납기 이면 납기 리스크
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import masterdata as md


@dataclass
class MaterialLine:
    item_code: str
    required: float
    available: float
    allocated: float
    shortage: float
    purchase_qty: float          # 0 이면 발주 없음
    ready_date: date             # 이 자재가 다 갖춰지는 날


@dataclass
class Plan:
    item_code: str
    qty: int
    batches: int                 # 배합기 배치 수 (액상 1,000 kg 단위)
    lines: list[MaterialLine]
    material_ready: date
    start: date
    end: date
    due: date
    at_risk: bool
    risk_reason: str | None
    planned_cost: int            # 표준 원가 × 수량 (원)
    purchases: list[MaterialLine] = field(default_factory=list)


def requirements(item_code: str, qty: int) -> dict[str, float]:
    return {code: round(per * qty, 4) for code, per in md.BOM[item_code]}


def batches_for(item_code: str, qty: int) -> int:
    liquid = qty * md.CAPSULES_PER_POUCH[item_code] * md.LIQUID_KG_PER_CAPSULE
    return max(1, math.ceil(liquid / md.BATCH_LIQUID_KG))


def production_days(item_code: str, qty: int) -> int:
    return max(1, math.ceil(qty * md.CAPSULES_PER_POUCH[item_code] / md.CAPSULES_PER_DAY))


def standard_cost(item_code: str, unit_cost: dict[str, float]) -> dict:
    """표준 원가 (원/파우치): 자재비 줄별 + 가공비."""
    lines = [{"itemCode": code, "qty": per, "unitCost": unit_cost[code], "amount": round(per * unit_cost[code], 2)}
             for code, per in md.BOM[item_code]]
    material = round(sum(line["amount"] for line in lines), 2)
    conversion = md.CONVERSION_COST[item_code]
    return {"itemCode": item_code, "lines": lines, "material": material, "conversion": conversion,
            "total": round(material + conversion, 2)}


def plan_order(item_code: str, qty: int, due: date, today: date, available: dict[str, float],
               items: dict[str, dict], line_free_from: date) -> Plan:
    """
    주문 1건의 생산 계획. available 은 품목별 가용 재고(현재고 - 할당), items 는 품목 마스터(unitCost,
    leadTimeDays, safetyStock), line_free_from 은 라인이 비는 날(앞 생산 오더의 종료 다음 날).
    """
    lines = []
    for code, need in requirements(item_code, qty).items():
        have = max(0.0, available.get(code, 0.0))
        alloc = min(have, need)
        short = round(need - alloc, 4)
        purchase = 0.0
        ready = today
        if short > 0:
            purchase = math.ceil(short + items[code]["safetyStock"])
            ready = today + timedelta(days=items[code]["leadTimeDays"])
        lines.append(MaterialLine(code, need, round(have, 4), round(alloc, 4), short, purchase, ready))

    material_ready = max(line.ready_date for line in lines)
    start = max(today, line_free_from, material_ready)
    end = start + timedelta(days=production_days(item_code, qty) - 1)
    at_risk = end > due
    reason = None
    if at_risk:
        late = (end - due).days
        blockers = [line.item_code for line in lines if line.ready_date == material_ready and line.purchase_qty]
        if material_ready > max(today, line_free_from) and blockers:
            reason = f"자재 입고 대기({', '.join(blockers)})로 납기보다 {late}일 늦게 끝남"
        else:
            reason = f"라인 일정이 밀려 납기보다 {late}일 늦게 끝남"
    unit_cost = {code: items[code]["unitCost"] for code in items}
    cost = standard_cost(item_code, unit_cost)["total"] * qty
    return Plan(item_code, qty, batches_for(item_code, qty), lines, material_ready, start, end, due, at_risk, reason,
                round(cost), [line for line in lines if line.purchase_qty > 0])
