import unittest

from tests.project_path import PROJECT_DIR  # noqa: F401
from equity_allocation import AllocationError, allocate_equity_factors
from signals.equity_factor import EquityFactorScore


SPY_RETURNS = tuple(0.001 + ((i % 7) - 3) * 0.001 for i in range(126))


def score(symbol, composite, *, volatility=0.20, beta=1.0, residual_scale=0.002):
    stock_returns = tuple(
        beta * market + (residual_scale if i % 2 else -residual_scale)
        for i, market in enumerate(SPY_RETURNS)
    )
    return EquityFactorScore(
        symbol=symbol,
        cutoff=__import__("datetime").date(2014, 12, 31),
        composite=composite,
        momentum_z=0,
        quality_z=0,
        low_residual_volatility_z=0,
        beta=beta,
        total_volatility=volatility,
        stock_returns=stock_returns,
        spy_returns=SPY_RETURNS,
    )


class EquityAllocationTests(unittest.TestCase):
    def test_selects_only_top_thirty_with_deterministic_ties(self):
        scores = [score(f"S{i:02d}", 1.0) for i in range(35)]
        allocation = allocate_equity_factors(scores)
        self.assertEqual(len(allocation.stock_weights), 30)
        self.assertEqual(tuple(allocation.stock_weights), tuple(f"S{i:02d}" for i in range(30)))

    def test_lower_volatility_receives_larger_long_weight(self):
        allocation = allocate_equity_factors(
            [
                score("LOWVOL", 2, volatility=0.10),
                score("HIGHVOL", 1, volatility=0.30),
            ]
        )
        self.assertGreater(
            allocation.stock_weights["LOWVOL"],
            allocation.stock_weights["HIGHVOL"],
        )
        self.assertTrue(all(value >= 0 for value in allocation.stock_weights.values()))

    def test_spy_hedge_neutralizes_beta_and_gross_cap(self):
        allocation = allocate_equity_factors(
            [score("A", 2, beta=1.2), score("B", 1, beta=0.8)]
        )
        self.assertAlmostEqual(allocation.beta_after_hedge, 0.0, places=12)
        self.assertLess(allocation.spy_weight, 0)
        self.assertLessEqual(allocation.gross_exposure, 0.50 + 1e-12)

    def test_hits_volatility_target_when_cap_does_not_bind(self):
        allocation = allocate_equity_factors(
            [score("A", 1, beta=0, residual_scale=0.02)],
            target_annual_volatility=0.05,
        )
        self.assertFalse(allocation.gross_cap_binding)
        self.assertAlmostEqual(allocation.expected_annual_volatility, 0.05)

    def test_gross_cap_binds_for_low_volatility_book(self):
        allocation = allocate_equity_factors(
            [score("A", 1, beta=1, residual_scale=0.00001)],
            target_annual_volatility=0.05,
        )
        self.assertTrue(allocation.gross_cap_binding)
        self.assertAlmostEqual(allocation.gross_exposure, 0.50)

    def test_zero_variance_fails_closed(self):
        item = score("FLAT", 1, beta=0)
        item = EquityFactorScore(
            item.symbol,
            item.cutoff,
            item.composite,
            item.momentum_z,
            item.quality_z,
            item.low_residual_volatility_z,
            item.beta,
            item.total_volatility,
            (0.0,) * 126,
            SPY_RETURNS,
        )
        with self.assertRaisesRegex(AllocationError, "variance"):
            allocate_equity_factors([item])


if __name__ == "__main__":
    unittest.main()
