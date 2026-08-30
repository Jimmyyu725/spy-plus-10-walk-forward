import unittest
from datetime import date, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from signals.futures_trend import DailyPrice, TrendSignalError, compute_trend_signal


def prices(count=260, growth=0.001):
    start = date(2014, 1, 1)
    return [
        DailyPrice(start + timedelta(days=i), 100 * (1 + growth) ** i)
        for i in range(count)
    ]


class FuturesTrendSignalTests(unittest.TestCase):
    def test_uptrend_has_three_positive_directions(self):
        series = prices()
        signal = compute_trend_signal("ES", series, series[-1].as_of)
        self.assertEqual(signal.directions, (1, 1, 1))
        self.assertEqual(signal.score, 1.0)

    def test_mixed_directions_are_equally_weighted(self):
        series = prices(growth=0)
        series[-64] = DailyPrice(series[-64].as_of, 110)
        series[-127] = DailyPrice(series[-127].as_of, 90)
        series[-253] = DailyPrice(series[-253].as_of, 90)
        signal = compute_trend_signal("ES", series, series[-1].as_of)
        self.assertEqual(signal.directions, (-1, 1, 1))
        self.assertAlmostEqual(signal.score, 1 / 3)

    def test_future_append_does_not_change_past_signal(self):
        series = prices()
        signal_date = series[-1].as_of
        before = compute_trend_signal("ES", series, signal_date)
        series.append(DailyPrice(signal_date + timedelta(days=1), 1))
        after = compute_trend_signal("ES", series, signal_date)
        self.assertEqual(before, after)

    def test_insufficient_history_fails_closed(self):
        with self.assertRaisesRegex(TrendSignalError, "253"):
            compute_trend_signal("ES", prices(252), date(2015, 1, 1))


if __name__ == "__main__":
    unittest.main()
