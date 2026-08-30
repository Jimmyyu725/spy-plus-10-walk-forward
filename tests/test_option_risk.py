import unittest
from datetime import date, datetime, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from option_chain import BullPutSpreadSelection, OptionContractSnapshot
from option_risk import (
    OptionRiskError,
    RealizedOptionLoss,
    size_defined_risk_spread,
)


ENTRY = datetime(2015, 1, 6, 10, 0)


def leg(symbol, strike, delta, bid, ask):
    return OptionContractSnapshot(
        symbol, ENTRY, ENTRY.date() + timedelta(days=45), strike, "PUT",
        bid, ask, 100, 1000, delta, 0.25, 100, 0.01,
    )


def spread():
    return BullPutSpreadSelection(
        ENTRY,
        leg("SHORT", 100, -0.20, 2.0, 2.2),
        leg("LONG", 95, -0.10, 0.8, 1.0),
    )


class OptionRiskTests(unittest.TestCase):
    def test_adverse_credit_fees_and_maximum_loss(self):
        sizing = size_defined_risk_spread(
            spread(), equity=100_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
        )
        self.assertEqual(sizing.contracts, 1)
        self.assertAlmostEqual(sizing.short_fill, 2.05)
        self.assertAlmostEqual(sizing.long_fill, 0.95)
        self.assertAlmostEqual(sizing.credit_per_share, 1.10)
        self.assertAlmostEqual(sizing.entry_fees, 2.0)
        self.assertAlmostEqual(sizing.total_max_loss, 392.0)
        self.assertLessEqual(sizing.total_max_loss, 500.0)

    def test_position_size_obeys_half_percent_and_three_percent_budgets(self):
        losses = [RealizedOptionLoss(ENTRY.date() - timedelta(days=10), 29_600)]
        sizing = size_defined_risk_spread(
            spread(), equity=1_000_000, as_of=ENTRY,
            realized_losses=losses, per_contract_annual_pnl_volatility=500,
        )
        self.assertEqual(sizing.contracts, 1)
        self.assertLessEqual(sizing.total_max_loss, 400)

    def test_old_and_future_losses_do_not_change_current_budget(self):
        base = size_defined_risk_spread(
            spread(), equity=1_000_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
        )
        ignored = size_defined_risk_spread(
            spread(), equity=1_000_000, as_of=ENTRY,
            realized_losses=[
                RealizedOptionLoss(ENTRY.date() - timedelta(days=366), 999_999),
                RealizedOptionLoss(date(2030, 1, 1), 999_999),
            ],
            per_contract_annual_pnl_volatility=500,
        )
        self.assertEqual(base, ignored)

    def test_non_credit_or_reversed_spread_fails_closed(self):
        reversed_spread = BullPutSpreadSelection(
            ENTRY,
            leg("SHORT", 95, -0.20, 0.8, 1.0),
            leg("LONG", 100, -0.10, 2.0, 2.2),
        )
        with self.assertRaisesRegex(OptionRiskError, "protection"):
            size_defined_risk_spread(
                reversed_spread, equity=100_000, as_of=ENTRY,
                realized_losses=[], per_contract_annual_pnl_volatility=500,
            )

    def test_double_slippage_never_improves_credit_or_risk(self):
        base = size_defined_risk_spread(
            spread(), equity=1_000_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
        )
        stress = size_defined_risk_spread(
            spread(), equity=1_000_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
            slippage_multiplier=2,
        )
        self.assertLess(stress.credit_per_share, base.credit_per_share)
        self.assertLessEqual(stress.contracts, base.contracts)

    def test_regulatory_reserve_is_inside_defined_maximum_loss(self):
        base = size_defined_risk_spread(
            spread(), equity=100_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
        )
        reserved = size_defined_risk_spread(
            spread(), equity=100_000, as_of=ENTRY,
            realized_losses=[], per_contract_annual_pnl_volatility=500,
            regulatory_fee_per_contract=3,
        )
        self.assertEqual(reserved.contracts, 1)
        self.assertAlmostEqual(reserved.entry_fees, base.entry_fees + 3)
        self.assertAlmostEqual(reserved.total_max_loss, base.total_max_loss + 3)


if __name__ == "__main__":
    unittest.main()
