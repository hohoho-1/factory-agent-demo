"""
가상 ERP 계획 로직 테스트 (DB 없이). 실행 (python 폴더에서):
  .venv\\Scripts\\python -m unittest tests.test_erp_planning
"""
import unittest
from datetime import date, timedelta

from erp import masterdata as md
from erp import planning

TODAY = date(2026, 11, 19)
ITEMS = {code: {"unitCost": cost, "leadTimeDays": lead, "safetyStock": safety}
         for code, _, _, _, cost, lead, safety in md.ITEMS}


def plenty() -> dict[str, float]:
    return {code: 1e9 for code in ITEMS}


class BomTest(unittest.TestCase):

    def test_liquid_per_capsule_is_15g(self):
        self.assertAlmostEqual(md.LIQUID_KG_PER_CAPSULE, 0.015)

    def test_requirements_scale_with_qty(self):
        req = planning.requirements("CAP-A30", 1000)
        self.assertAlmostEqual(req["RM-AS"], 135.0)       # 4.5 g × 30 캡슐 × 1,000 파우치
        self.assertAlmostEqual(req["PM-PVA"], 27.0)
        self.assertEqual(req["PM-P30"], 1000)
        self.assertNotIn("RM-FB", req)                    # A 는 프레시 향만

    def test_batches_round_up_by_mixer_capacity(self):
        # 2,222 파우치 × 30 × 15 g = 999.9 kg → 1배치, 2,223 → 2배치
        self.assertEqual(planning.batches_for("CAP-A30", 2222), 1)
        self.assertEqual(planning.batches_for("CAP-A30", 2223), 2)

    def test_standard_cost(self):
        cost = planning.standard_cost("CAP-A30", {k: v["unitCost"] for k, v in ITEMS.items()})
        self.assertEqual(cost["conversion"], 420)
        self.assertAlmostEqual(cost["total"], cost["material"] + 420)
        self.assertTrue(1500 < cost["material"] < 2500)


class PlanTest(unittest.TestCase):

    def test_enough_stock_starts_today_without_purchases(self):
        p = planning.plan_order("CAP-A30", 6000, TODAY + timedelta(days=5), TODAY, plenty(), ITEMS, TODAY)
        self.assertEqual(p.purchases, [])
        self.assertEqual(p.start, TODAY)
        self.assertEqual(p.end, TODAY)                    # 6,000 × 30 = 18만 캡슐 < 하루 36만
        self.assertFalse(p.at_risk)
        self.assertTrue(all(line.allocated == line.required for line in p.lines))

    def test_shortage_creates_purchase_with_safety_stock_and_waits_for_it(self):
        stock = plenty()
        stock["RM-EZ"] = 10.0
        p = planning.plan_order("CAP-A30", 6000, TODAY + timedelta(days=5), TODAY, stock, ITEMS, TODAY)
        ez = next(line for line in p.lines if line.item_code == "RM-EZ")
        self.assertAlmostEqual(ez.required, 81.0)
        self.assertAlmostEqual(ez.allocated, 10.0)
        self.assertEqual(ez.purchase_qty, 71 + 40)        # 부족분 71 + 안전재고 40
        self.assertEqual(p.material_ready, TODAY + timedelta(days=10))
        self.assertEqual(p.start, TODAY + timedelta(days=10))
        self.assertTrue(p.at_risk)
        self.assertIn("자재 입고 대기(RM-EZ)", p.risk_reason)

    def test_busy_line_pushes_start(self):
        p = planning.plan_order("CAP-B15", 4000, TODAY + timedelta(days=1), TODAY, plenty(), ITEMS,
                                TODAY + timedelta(days=3))
        self.assertEqual(p.start, TODAY + timedelta(days=3))
        self.assertTrue(p.at_risk)
        self.assertIn("라인 일정", p.risk_reason)


if __name__ == "__main__":
    unittest.main()
