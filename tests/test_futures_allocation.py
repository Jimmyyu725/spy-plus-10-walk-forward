import unittest

from tests.project_path import PROJECT_DIR  # noqa: F401
from futures_allocation import AllocationError, allocate_trend, volatility_only_control


def alternating(scale, count=253):
    return [scale if i % 2 == 0 else -scale for i in range(count)]


class FuturesAllocationTests(unittest.TestCase):
    def test_lower_volatility_receives_larger_absolute_weight(self):
        result = allocate_trend(
            {"ES": 1.0, "GC": 1.0},
            {"ES": alternating(0.01), "GC": alternating(0.02)},
        )
        self.assertGreater(abs(result.weights["ES"]), abs(result.weights["GC"]))
        self.assertLessEqual(result.gross_notional, 0.70 + 1e-12)

    def test_direction_is_preserved(self):
        result = allocate_trend(
            {"ES": -1.0, "GC": 1.0},
            {
                "ES": alternating(0.01),
                "GC": [0.01 if i % 3 == 0 else -0.005 for i in range(253)],
            },
        )
        self.assertLess(result.weights["ES"], 0)
        self.assertGreater(result.weights["GC"], 0)

    def test_zero_signal_stays_zero(self):
        result = allocate_trend({"ES": 0.0}, {"ES": alternating(0.01)})
        self.assertEqual(result.weights, {"ES": 0.0})

    def test_volatility_only_control_removes_trend_direction(self):
        result = volatility_only_control(
            {"ES": -1.0, "GC": 1.0},
            {"ES": alternating(0.01), "GC": alternating(0.01)},
        )
        self.assertGreaterEqual(result.weights["ES"], 0)
        self.assertGreaterEqual(result.weights["GC"], 0)

    def test_short_history_fails_closed(self):
        with self.assertRaisesRegex(AllocationError, "252"):
            allocate_trend({"ES": 1.0}, {"ES": alternating(0.01, 251)})


if __name__ == "__main__":
    unittest.main()
