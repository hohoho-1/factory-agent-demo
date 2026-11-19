"""
가상 ERP 기초 데이터: 캡슐 세제 품목 · 배합비(BOM) · 단가 · 기초 재고 · 예시 주문.

모두 데모용 가상 값이다. 실제 KMPC 제품 · 배합비 · 원가가 아니다.
- 완제품(FG)은 '파우치' 단위로 판다. 캡슐 1개 = 액상 15 g + PVA 필름 0.9 g.
- 원료(RM)는 kg, 포장재(PM)는 개(EA).
- 배합기 1배치 = 액상 1,000 kg (MES 연계 단계에서 생산 오더 → 배치 수 계산에 쓴다).
"""
from __future__ import annotations

ITEMS = [
    # code, name, type, uom, unit_cost(원), lead_time_days, safety_stock
    ("CAP-A30", "캡슐 세제 A 30개입 (프레시 향)", "FG", "파우치", 0, 0, 0),
    ("CAP-B15", "캡슐 세제 B 15개입 (라벤더 향)", "FG", "파우치", 0, 0, 0),
    ("RM-AS", "음이온 계면활성제", "RM", "kg", 2100, 5, 500),
    ("RM-NS", "비이온 계면활성제", "RM", "kg", 2600, 5, 300),
    ("RM-PG", "프로필렌글리콜 (용제)", "RM", "kg", 1900, 4, 300),
    ("RM-GL", "글리세린", "RM", "kg", 1400, 4, 150),
    ("RM-EZ", "효소 블렌드", "RM", "kg", 18000, 10, 40),
    ("RM-FA", "향료 프레시", "RM", "kg", 32000, 14, 30),
    ("RM-FB", "향료 라벤더", "RM", "kg", 35000, 14, 20),
    ("RM-WT", "정제수", "RM", "kg", 5, 0, 0),
    ("PM-PVA", "PVA 수용성 필름", "PM", "kg", 9500, 12, 60),
    ("PM-P30", "스탠딩 파우치 30개입", "PM", "EA", 180, 7, 3000),
    ("PM-P15", "스탠딩 파우치 15개입", "PM", "EA", 130, 7, 2000),
    ("PM-LB", "라벨", "PM", "EA", 25, 3, 5000),
]

# 완제품 1파우치당 소요량. 액상 배합은 캡슐 1개 15 g 기준 (계면활성제 50%, 용제 · 보습 35%, 효소 · 향 5%, 물 10%)
_LIQUID_PER_CAPSULE = {  # kg
    "RM-AS": 0.0045, "RM-NS": 0.0030, "RM-PG": 0.00375, "RM-GL": 0.0015, "RM-EZ": 0.00045, "RM-WT": 0.0015,
}
_FRAGRANCE_PER_CAPSULE = 0.0003  # kg
_FILM_PER_CAPSULE = 0.0009       # kg


def _bom(capsules: int, fragrance: str, pouch: str) -> list[tuple[str, float]]:
    lines = [(code, round(q * capsules, 6)) for code, q in _LIQUID_PER_CAPSULE.items()]
    lines += [(fragrance, round(_FRAGRANCE_PER_CAPSULE * capsules, 6)),
              ("PM-PVA", round(_FILM_PER_CAPSULE * capsules, 6)),
              (pouch, 1.0), ("PM-LB", 1.0)]
    return lines


BOM = {
    "CAP-A30": _bom(30, "RM-FA", "PM-P30"),
    "CAP-B15": _bom(15, "RM-FB", "PM-P15"),
}

# 완제품별 가공비 (원/파우치: 배합 · 성형 · 충진 · 포장 인건비와 설비비를 뭉뚱그린 가상 값)
CONVERSION_COST = {"CAP-A30": 420, "CAP-B15": 260}

# 생산 능력: 라인 1개, 하루 캡슐 360,000개 (= A30 12,000파우치). 배합기 1배치 = 액상 1,000 kg
CAPSULES_PER_DAY = 360_000
CAPSULES_PER_POUCH = {"CAP-A30": 30, "CAP-B15": 15}
BATCH_LIQUID_KG = 1000.0
LIQUID_KG_PER_CAPSULE = sum(_LIQUID_PER_CAPSULE.values()) + _FRAGRANCE_PER_CAPSULE  # 0.015

# 기초 재고 (kg 또는 EA). 효소 · 필름 · 향료는 일부러 적게 두어 큰 주문이 들어오면 발주가 나가게 한다
OPENING_STOCK = {
    "RM-AS": 4200, "RM-NS": 2600, "RM-PG": 3100, "RM-GL": 1300, "RM-EZ": 120, "RM-FA": 70, "RM-FB": 40,
    "RM-WT": 100000, "PM-PVA": 260, "PM-P30": 9000, "PM-P15": 6000, "PM-LB": 20000,
}

# 예시 판매 주문: (고객, 품목, 수량, 오늘부터 며칠 뒤 납기)
SAMPLE_ORDERS = [
    ("한빛마트 물류센터", "CAP-A30", 6000, 5),
    ("온라인몰 정기배송", "CAP-B15", 4000, 7),
]
