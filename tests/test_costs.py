import unittest
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from costs import (
    equity_execution,
    futures_execution,
    option_execution,
)


class CostModelTests(unittest.TestCase):
    def test_equity_commission_floor_and_half_spread(self):
        cost = equity_execution("BUY", 10, "100", bid="99.90", ask="100.10")
        self.assertEqual(cost.commission, Decimal("1.00"))
        self.assertEqual(cost.fill_price, Decimal("100.10"))
        self.assertEqual(cost.slippage, Decimal("1.00"))

    def test_equity_uses_five_bps_when_larger(self):
        cost = equity_execution("SELL", 1000, "100", bid="99.99", ask="100.01")
        self.assertEqual(cost.commission, Decimal("5.000"))
        self.assertEqual(cost.fill_price, Decimal("99.9500"))
        self.assertEqual(cost.slippage, Decimal("50.0000"))

    def test_double_slippage_changes_slippage_not_commission(self):
        base = equity_execution("BUY", 10, "100")
        stress = equity_execution("BUY", 10, "100", slippage_multiplier="2")
        self.assertEqual(stress.commission, base.commission)
        self.assertEqual(stress.slippage, base.slippage * 2)

    def test_futures_cost_has_fee_floor_and_one_tick(self):
        cost = futures_execution("BUY", 2, "5000", tick_size="0.25", multiplier="50")
        self.assertEqual(cost.commission, Decimal("5.00"))
        self.assertEqual(cost.fill_price, Decimal("5000.25"))
        self.assertEqual(cost.slippage, Decimal("25.00"))

    def test_option_cost_uses_quarter_spread_and_tick(self):
        cost = option_execution("SELL", 1, bid="1.00", ask="1.20", min_tick="0.01")
        self.assertEqual(cost.commission, Decimal("1.00"))
        self.assertEqual(cost.fill_price, Decimal("1.05"))
        self.assertEqual(cost.slippage, Decimal("5.00"))

    def test_regulatory_fee_is_explicit(self):
        cost = equity_execution("SELL", 100, "10", regulatory_fee="0.03")
        self.assertEqual(cost.regulatory_fee, Decimal("0.03"))
        self.assertEqual(cost.total_cost, cost.commission + cost.regulatory_fee + cost.slippage)


if __name__ == "__main__":
    unittest.main()
