import copy
import unittest
from decimal import Decimal

import spy_plus_10.v2.attribution as attribution
from spy_plus_10.v2.attribution import (
    ABLATION_VARIANTS,
    AttributionError,
    RUN_VARIANTS,
    SleeveLedger,
    enabled_sleeves,
)


SLEEVES = ("core", "equity", "futures", "defensive_option")


def marks(core="0", equity="0", futures="0", defensive_option="0"):
    return {
        "core": core,
        "equity": equity,
        "futures": futures,
        "defensive_option": defensive_option,
    }


class V2AttributionTests(unittest.TestCase):
    def test_daily_pnl_reconciles_to_equity_change_after_external_deposit(self):
        ledger = SleeveLedger(initial_equity="1000000")
        ledger.record_day(
            "2015-01-02",
            marks("600000", "150000", "100000", "0"),
            cash="150000",
            external_flow="0",
            fees={},
            slippage={},
        )
        row = ledger.record_day(
            "2015-01-05",
            marks("606000", "148000", "101000", "0"),
            cash="200000",
            external_flow="50000",
            fees={"equity": "25"},
            slippage={"futures": "10"},
        )
        self.assertEqual(row["equity"], Decimal("1055000"))
        self.assertEqual(row["portfolio_daily_pnl"], Decimal("5000"))
        self.assertEqual(sum(row["sleeve_daily_pnl"].values()), Decimal("5000"))
        self.assertEqual(row["fees"]["equity"], Decimal("25"))
        self.assertEqual(row["slippage"]["futures"], Decimal("10"))

    def test_component_and_ablation_variants_are_fixed_immutable_configurations(self):
        self.assertEqual(len(ABLATION_VARIANTS), 9)
        self.assertEqual(tuple(ABLATION_VARIANTS), RUN_VARIANTS)
        self.assertEqual(enabled_sleeves("full"), SLEEVES)
        self.assertEqual(
            enabled_sleeves("without_core"),
            ("equity", "futures", "defensive_option"),
        )
        self.assertEqual(enabled_sleeves("equity_only"), ("equity",))
        with self.assertRaises(TypeError):
            ABLATION_VARIANTS["full"] = ()
        for value in ("unknown", None, 1, True):
            with self.subTest(value=value):
                with self.assertRaises(AttributionError):
                    enabled_sleeves(value)

    def test_without_futures_rejects_nonzero_disabled_sleeve_inputs(self):
        for changes in (
            {"marked_values": marks("100", "0", "1", "0")},
            {"fees": {"futures": "1"}},
            {"slippage": {"futures": "1"}},
            {"sleeve_cash_flows": {"futures": "1"}},
        ):
            with self.subTest(changes=changes):
                ledger = SleeveLedger(initial_equity="100", run_variant="without_futures")
                args = {
                    "marked_values": marks("100", "0", "0", "0"),
                    "cash": "0",
                    "external_flow": "0",
                    "fees": {},
                    "slippage": {},
                    "sleeve_cash_flows": {"futures": "0"},
                }
                args.update(changes)
                with self.assertRaisesRegex(AttributionError, "disabled sleeve"):
                    ledger.record_day("2015-01-02", **args)
        row = SleeveLedger("100", "without_futures").record_day(
            "2015-01-02",
            marks("100", "0", "0", "0"),
            cash="0",
            external_flow="0",
            fees={"futures": "0"},
            slippage={"futures": "0"},
            sleeve_cash_flows={"futures": "0"},
        )
        self.assertEqual(row["equity"], Decimal("100"))

    def test_mapping_shape_unknown_sleeves_and_negative_costs_fail_closed(self):
        ledger = SleeveLedger("100")
        invalid_marked_values = (
            {"core": "100"},
            dict(marks("100"), extra="0"),
            ["not", "a", "mapping"],
        )
        for value in invalid_marked_values:
            with self.subTest(value=value):
                with self.assertRaises(AttributionError):
                    ledger.record_day(
                        "2015-01-02", value, cash="0", external_flow="0", fees={}, slippage={}
                    )
        for keyword, value in (
            ("fees", {"unknown": "0"}),
            ("slippage", {"unknown": "0"}),
            ("sleeve_cash_flows", {"unknown": "0"}),
            ("fees", {"equity": "-0.01"}),
            ("slippage", {"equity": "-0.01"}),
        ):
            with self.subTest(keyword=keyword, value=value):
                kwargs = {"fees": {}, "slippage": {}, "sleeve_cash_flows": None}
                kwargs[keyword] = value
                with self.assertRaises(AttributionError):
                    SleeveLedger("100").record_day(
                        "2015-01-02", marks("100"), cash="0", external_flow="0", **kwargs
                    )

    def test_dates_and_invalid_numbers_are_rejected(self):
        ledger = SleeveLedger("100")
        ledger.record_day("2015-01-02", marks("100"), cash="0", external_flow="0", fees={}, slippage={})
        for day in ("2015-01-02", "2015-01-01", "2015-1-03", "2015-02-30", None):
            with self.subTest(day=day):
                with self.assertRaises(AttributionError):
                    ledger.record_day(day, marks("100"), cash="0", external_flow="0", fees={}, slippage={})
        invalid_numbers = (True, float("nan"), float("inf"), float("-inf"), object())
        for value in invalid_numbers:
            with self.subTest(value=value):
                with self.assertRaises(AttributionError):
                    SleeveLedger(value)
                with self.assertRaises(AttributionError):
                    SleeveLedger("100").record_day(
                        "2015-01-02", marks(value), cash="0", external_flow="0", fees={}, slippage={}
                    )
        for value in ("0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(AttributionError):
                    SleeveLedger(value)
                with self.assertRaises(AttributionError):
                    SleeveLedger("100").record_day(
                        "2015-01-02", marks(value), cash="0", external_flow="0", fees={}, slippage={}
                    )

    def test_trade_cash_flow_then_mark_change_tracks_sleeve_pnl(self):
        ledger = SleeveLedger("100")
        ledger.record_day("2015-01-02", marks("0"), cash="100", external_flow="0", fees={}, slippage={})
        bought = ledger.record_day(
            "2015-01-05",
            marks(equity="10"),
            cash="90",
            external_flow="0",
            fees={},
            slippage={},
            sleeve_cash_flows={"equity": "10"},
        )
        self.assertEqual(bought["portfolio_daily_pnl"], Decimal("0"))
        self.assertEqual(bought["sleeve_daily_pnl"]["equity"], Decimal("0"))
        marked = ledger.record_day(
            "2015-01-06",
            marks(equity="12"),
            cash="90",
            external_flow="0",
            fees={},
            slippage={},
        )
        self.assertEqual(marked["portfolio_daily_pnl"], Decimal("2"))
        self.assertEqual(marked["sleeve_daily_pnl"]["equity"], Decimal("2"))

    def test_core_owns_exact_global_cash_residual_without_other_bucket(self):
        ledger = SleeveLedger("100")
        ledger.record_day("2015-01-02", marks("0"), cash="100", external_flow="0", fees={}, slippage={})
        row = ledger.record_day(
            "2015-01-05", marks(equity="10"), cash="92", external_flow="0", fees={}, slippage={}
        )
        self.assertEqual(row["portfolio_daily_pnl"], Decimal("2"))
        self.assertEqual(row["sleeve_daily_pnl"]["equity"], Decimal("10"))
        self.assertEqual(row["sleeve_daily_pnl"]["core"], Decimal("-8"))
        self.assertNotIn("other", row["sleeve_daily_pnl"])
        self.assertFalse(hasattr(attribution, "ablation_paths"))

    def test_cumulative_pnl_equals_daily_sum_across_three_dates(self):
        ledger = SleeveLedger("100")
        rows = [
            ledger.record_day("2015-01-02", marks("0"), cash="100", external_flow="0", fees={}, slippage={}),
            ledger.record_day("2015-01-05", marks(equity="10"), cash="92", external_flow="0", fees={}, slippage={}),
            ledger.record_day("2015-01-06", marks(equity="12", futures="5"), cash="86", external_flow="0", fees={}, slippage={}),
        ]
        for sleeve in SLEEVES:
            self.assertEqual(
                rows[-1]["sleeve_cumulative_pnl"][sleeve],
                sum((row["sleeve_daily_pnl"][sleeve] for row in rows), Decimal("0")),
            )

    def test_external_deposits_and_withdrawals_do_not_become_pnl(self):
        ledger = SleeveLedger("100")
        ledger.record_day("2015-01-02", marks("0"), cash="100", external_flow="0", fees={}, slippage={})
        deposit = ledger.record_day("2015-01-05", marks("0"), cash="150", external_flow="50", fees={}, slippage={})
        withdrawal = ledger.record_day("2015-01-06", marks("0"), cash="130", external_flow="-20", fees={}, slippage={})
        self.assertEqual(deposit["portfolio_daily_pnl"], Decimal("0"))
        self.assertEqual(withdrawal["portfolio_daily_pnl"], Decimal("0"))

    def test_returned_rows_are_isolated_from_internal_state(self):
        ledger = SleeveLedger("100")
        first = ledger.record_day("2015-01-02", marks("0"), cash="100", external_flow="0", fees={}, slippage={})
        first["sleeve_daily_pnl"]["core"] = Decimal("999")
        first["sleeve_cumulative_pnl"]["core"] = Decimal("999")
        first["fees"]["core"] = Decimal("999")
        first["enabled_sleeves"] += ("made_up",)
        self.assertEqual(ledger.equity_path(), [Decimal("100")])
        second = ledger.record_day("2015-01-05", marks("0"), cash="100", external_flow="0", fees={}, slippage={})
        self.assertEqual(second["sleeve_cumulative_pnl"]["core"], Decimal("0"))
        self.assertEqual(second["enabled_sleeves"], SLEEVES)
        second_copy = copy.deepcopy(second)
        second_copy["sleeve_daily_pnl"]["equity"] = Decimal("999")
        self.assertEqual(ledger.equity_path(), [Decimal("100"), Decimal("100")])


if __name__ == "__main__":
    unittest.main()
