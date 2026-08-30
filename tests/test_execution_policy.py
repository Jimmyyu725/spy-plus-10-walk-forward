import unittest
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401

from execution import integrated_execution


class IntegratedExecutionPolicyTests(unittest.TestCase):
    def test_equity_sell_includes_commission_section31_and_capped_taf(self):
        result = integrated_execution(
            "EQUITY",
            "SELL",
            1_000,
            reference_price=100,
            bid=99.98,
            ask=100.02,
        )
        self.assertEqual(result.commission, Decimal("5.000"))
        self.assertEqual(result.section31_fee, Decimal("2.7800000"))
        self.assertEqual(result.taf_fee, Decimal("0.195000"))
        self.assertEqual(result.regulatory_fee, Decimal("2.9750000"))
        self.assertEqual(result.fill_price, Decimal("99.9500"))

        capped = integrated_execution(
            "EQUITY",
            "SELL",
            100_000,
            reference_price=10,
        )
        self.assertEqual(capped.taf_fee, Decimal("9.79"))

    def test_equity_buy_has_no_sell_side_regulatory_fee(self):
        result = integrated_execution(
            "EQUITY",
            "BUY",
            100,
            reference_price=50,
        )
        self.assertEqual(result.regulatory_fee, Decimal("0"))
        self.assertEqual(result.commission, Decimal("1.00"))

    def test_option_sell_charges_each_leg_commission_and_regulatory_overlay(self):
        result = integrated_execution(
            "OPTION",
            "SELL",
            10,
            bid=1.90,
            ask=2.10,
            min_tick=0.01,
            contract_multiplier=100,
        )
        self.assertEqual(result.commission, Decimal("6.50"))
        self.assertEqual(result.section31_fee, Decimal("0.0556000"))
        self.assertEqual(result.taf_fee, Decimal("0.03290"))
        self.assertEqual(result.regulatory_fee, Decimal("0.0885000"))
        self.assertEqual(result.fill_price, Decimal("1.95"))

    def test_future_charges_floor_plus_regulatory_fee_per_contract(self):
        result = integrated_execution(
            "FUTURE",
            "BUY",
            3,
            reference_price=5000,
            tick_size=0.25,
            contract_multiplier=50,
        )
        self.assertEqual(result.commission, Decimal("7.50"))
        self.assertEqual(result.regulatory_fee, Decimal("0.06"))
        self.assertEqual(result.fill_price, Decimal("5000.25"))

    def test_double_slippage_changes_only_fill_and_slippage(self):
        base = integrated_execution(
            "OPTION",
            "BUY",
            4,
            bid=0.90,
            ask=1.10,
            min_tick=0.01,
            contract_multiplier=100,
            slippage_multiplier=1,
        )
        stressed = integrated_execution(
            "OPTION",
            "BUY",
            4,
            bid=0.90,
            ask=1.10,
            min_tick=0.01,
            contract_multiplier=100,
            slippage_multiplier=2,
        )
        self.assertEqual(base.commission, stressed.commission)
        self.assertEqual(base.regulatory_fee, stressed.regulatory_fee)
        self.assertGreater(stressed.fill_price, base.fill_price)
        self.assertGreater(stressed.slippage, base.slippage)

    def test_canceled_unfilled_order_has_no_cost(self):
        result = integrated_execution(
            "EQUITY",
            "SELL",
            0,
            reference_price=100,
        )
        self.assertIsNone(result.fill_price)
        self.assertEqual(result.commission, Decimal("0"))
        self.assertEqual(result.regulatory_fee, Decimal("0"))
        self.assertEqual(result.slippage, Decimal("0"))

    def test_invalid_asset_or_slippage_multiplier_fails_closed(self):
        with self.assertRaises(ValueError):
            integrated_execution("CRYPTO", "BUY", 1, reference_price=100)
        with self.assertRaises(ValueError):
            integrated_execution(
                "EQUITY",
                "BUY",
                1,
                reference_price=100,
                slippage_multiplier=1.5,
            )


if __name__ == "__main__":
    unittest.main()
