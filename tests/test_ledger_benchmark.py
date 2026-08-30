import unittest
from datetime import date
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from benchmark import PricePoint, build_spy_buy_hold
from ledger import CashLedger, LedgerError


class LedgerAndBenchmarkTests(unittest.TestCase):
    def test_buy_mark_sell_conserves_cash_and_equity(self):
        ledger = CashLedger("1000")
        ledger.book_fill("SPY", 5, "100", commission="1")
        first = ledger.mark_to_market({"SPY": "100"}, date(2015, 1, 2))
        self.assertEqual(first.cash, Decimal("499"))
        self.assertEqual(first.equity, Decimal("999"))
        marked = ledger.mark_to_market({"SPY": "105"}, date(2015, 1, 5))
        self.assertEqual(marked.equity, Decimal("1024"))
        ledger.book_fill("SPY", -5, "105", commission="1")
        final = ledger.mark_to_market({}, date(2015, 1, 6))
        self.assertEqual(final.cash, Decimal("1023"))
        self.assertEqual(final.equity, Decimal("1023"))
        self.assertEqual(ledger.total_fees, Decimal("2"))

    def test_missing_held_price_fails_closed(self):
        ledger = CashLedger("1000")
        ledger.book_fill("SPY", 1, "100")
        with self.assertRaisesRegex(LedgerError, "missing mark"):
            ledger.mark_to_market({}, date(2015, 1, 2))

    def test_benchmark_charges_entry_and_reports_exit_sensitivity(self):
        result = build_spy_buy_hold(
            [PricePoint(date(2015, 1, 2), "100"), PricePoint(date(2015, 12, 31), "110")],
            initial_cash="1000",
        )
        self.assertEqual(result.shares, Decimal("9"))
        self.assertEqual(result.equity[0].value, Decimal("998.5500"))
        self.assertEqual(result.equity[-1].value, Decimal("1088.5500"))
        self.assertLess(result.liquidation_value, result.equity[-1].value)

    def test_benchmark_rejects_duplicate_or_non_increasing_dates(self):
        points = [PricePoint(date(2015, 1, 2), "100"), PricePoint(date(2015, 1, 2), "101")]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_spy_buy_hold(points, initial_cash="1000")


if __name__ == "__main__":
    unittest.main()
