import unittest
from datetime import date
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from metrics import EquityPoint, MetricsError, evaluate_annual_gates


class AnnualGateTests(unittest.TestCase):
    def test_negative_ten_spy_requires_zero_strategy(self):
        strategy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 31), "100"),
        ]
        spy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 31), "90"),
        ]
        result = evaluate_annual_gates(
            strategy,
            spy,
            initial_value="100",
            as_of=date(2015, 12, 31),
        )
        self.assertEqual(result.rows[0].hurdle_return, Decimal("0.00"))
        self.assertEqual(result.rows[0].status, "PASS")

    def test_positive_ten_spy_requires_positive_twenty(self):
        strategy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 31), "119.99"),
        ]
        spy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 31), "110"),
        ]
        result = evaluate_annual_gates(
            strategy,
            spy,
            initial_value="100",
            as_of=date(2015, 12, 31),
        )
        self.assertEqual(result.rows[0].hurdle_return, Decimal("0.20"))
        self.assertEqual(result.rows[0].status, "FAIL")
        self.assertEqual(result.overall_status, "FAIL")

    def test_current_year_is_marked_partial(self):
        strategy = [
            EquityPoint(date(2026, 1, 2), "100"),
            EquityPoint(date(2026, 8, 28), "120"),
        ]
        spy = [
            EquityPoint(date(2026, 1, 2), "100"),
            EquityPoint(date(2026, 8, 28), "109"),
        ]
        result = evaluate_annual_gates(
            strategy,
            spy,
            initial_value="100",
            as_of=date(2026, 8, 30),
        )
        self.assertEqual(result.rows[0].period, "PARTIAL_YEAR")
        self.assertEqual(result.rows[0].status, "PASS")

    def test_historical_year_uses_last_common_trading_date(self):
        strategy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 30), "120"),
        ]
        spy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 30), "110"),
        ]
        result = evaluate_annual_gates(
            strategy,
            spy,
            initial_value="100",
            as_of=date(2026, 8, 30),
        )
        self.assertEqual(result.rows[0].period, "FULL_YEAR")

    def test_missing_calendar_year_fails_closed(self):
        strategy = [
            EquityPoint(date(2015, 12, 31), "100"),
            EquityPoint(date(2017, 12, 29), "120"),
        ]
        spy = [
            EquityPoint(date(2015, 12, 31), "100"),
            EquityPoint(date(2017, 12, 29), "110"),
        ]
        with self.assertRaisesRegex(MetricsError, "missing calendar year"):
            evaluate_annual_gates(
                strategy,
                spy,
                initial_value="100",
                as_of=date(2017, 12, 31),
            )

    def test_series_use_only_common_dates(self):
        strategy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 30), "150"),
            EquityPoint(date(2015, 12, 31), "120"),
        ]
        spy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 31), "110"),
        ]
        result = evaluate_annual_gates(
            strategy,
            spy,
            initial_value="100",
            as_of=date(2015, 12, 31),
        )
        self.assertEqual(result.rows[0].strategy_return, Decimal("0.20"))

    def test_duplicate_dates_fail_closed(self):
        duplicate = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 1, 2), "101"),
        ]
        with self.assertRaisesRegex(MetricsError, "strictly increasing"):
            evaluate_annual_gates(
                duplicate,
                duplicate,
                initial_value="100",
                as_of=date(2015, 12, 31),
            )


if __name__ == "__main__":
    unittest.main()
