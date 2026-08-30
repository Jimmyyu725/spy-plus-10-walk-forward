import unittest
from datetime import date, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from signals.equity_factor import (
    EquityPrice,
    FactorSignalError,
    RawEquityFactor,
    compute_raw_equity_factor,
    linear_percentile,
    rank_equity_factors,
    winsorized_zscores,
)
from universe import EquityCandidate


START = date(2014, 1, 1)


def prices(symbol, returns):
    value = 100.0
    result = [EquityPrice(symbol, START, value)]
    for index, daily_return in enumerate(returns, 1):
        value *= 1 + daily_return
        result.append(EquityPrice(symbol, START + timedelta(days=index), value))
    return result


def candidate(symbol, roe=0.2, gpa=0.2):
    return EquityCandidate(symbol, START + timedelta(days=252), 10, 1_000_000, roe, gpa)


class EquityFactorTests(unittest.TestCase):
    def setUp(self):
        self.spy_returns = [0.001 + ((i % 5) - 2) * 0.0005 for i in range(252)]
        self.spy = prices("SPY", self.spy_returns)
        self.cutoff = self.spy[-1].as_of

    def test_linear_percentile_and_winsorized_zscore(self):
        self.assertEqual(linear_percentile([0.0, 10.0], 0.25), 2.5)
        scores = winsorized_zscores({"A": 0.0, "B": 10.0, "C": 20.0})
        self.assertAlmostEqual(sum(scores.values()), 0.0)
        self.assertLess(scores["A"], scores["B"])
        self.assertLess(scores["B"], scores["C"])

    def test_momentum_uses_day_252_to_day_21(self):
        stock = prices("MOM", [0.0] * 252)
        stock[0] = EquityPrice("MOM", stock[0].as_of, 100)
        stock[-22] = EquityPrice("MOM", stock[-22].as_of, 120)
        stock[-1] = EquityPrice("MOM", stock[-1].as_of, 999)
        raw = compute_raw_equity_factor(
            candidate("MOM"), stock, self.spy, cutoff=self.cutoff
        )
        self.assertAlmostEqual(raw.momentum, 0.2)

    def test_ols_beta_and_residual_volatility(self):
        residual = [0.0003 if i % 2 else -0.0003 for i in range(252)]
        stock_returns = [
            2 * market + noise
            for market, noise in zip(self.spy_returns, residual)
        ]
        raw = compute_raw_equity_factor(
            candidate("OLS"),
            prices("OLS", stock_returns),
            self.spy,
            cutoff=self.cutoff,
        )
        self.assertAlmostEqual(raw.beta, 2.0, delta=0.02)
        self.assertGreater(raw.residual_volatility, 0)

    def test_quality_and_final_weights_rank_deterministically(self):
        raw = [
            RawEquityFactor("B", self.cutoff, 0.1, 0.1, 0.1, 0.30, 1.0, 0.20, (), ()),
            RawEquityFactor("A", self.cutoff, 0.3, 0.3, 0.3, 0.10, 1.0, 0.20, (), ()),
            RawEquityFactor("C", self.cutoff, 0.2, 0.2, 0.2, 0.20, 1.0, 0.20, (), ()),
        ]
        ranked = rank_equity_factors(raw)
        self.assertEqual([item.symbol for item in ranked], ["A", "C", "B"])
        self.assertGreater(ranked[0].composite, ranked[-1].composite)

    def test_insufficient_history_fails_closed(self):
        with self.assertRaisesRegex(FactorSignalError, "253"):
            compute_raw_equity_factor(
                candidate("SHORT"),
                prices("SHORT", self.spy_returns[:-1]),
                self.spy,
                cutoff=self.cutoff,
            )

    def test_future_append_does_not_change_past_signal(self):
        stock = prices("SAFE", [1.1 * value for value in self.spy_returns])
        before = compute_raw_equity_factor(
            candidate("SAFE"), stock, self.spy, cutoff=self.cutoff
        )
        stock.append(EquityPrice("SAFE", date(2030, 1, 1), 1))
        self.spy.append(EquityPrice("SPY", date(2030, 1, 1), 999999))
        after = compute_raw_equity_factor(
            candidate("SAFE"), stock, self.spy, cutoff=self.cutoff
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
