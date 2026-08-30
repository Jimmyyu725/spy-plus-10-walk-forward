import unittest
from datetime import date, datetime, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from option_chain import (
    OptionChainError,
    OptionContractSnapshot,
    select_bull_put_spread,
)


ENTRY = datetime(2015, 1, 6, 10, 0)


def contract(symbol, dte, strike, delta, *, bid=1.0, ask=1.1, volume=10, oi=500):
    return OptionContractSnapshot(
        symbol, ENTRY, ENTRY.date() + timedelta(days=dte), strike, "PUT",
        bid, ask, volume, oi, delta, 0.25, 100, 0.01,
    )


class OptionChainTests(unittest.TestCase):
    def test_selects_same_expiry_delta_targets_and_long_protection(self):
        chain = [
            contract("S20", 45, 95, -0.20),
            contract("L10", 45, 90, -0.10),
            contract("OTHER", 50, 94, -0.19),
        ]
        spread = select_bull_put_spread(chain, entry_time=ENTRY, underlying_price=100)
        self.assertEqual((spread.short_put.symbol, spread.long_put.symbol), ("S20", "L10"))
        self.assertEqual(spread.short_put.expiry, spread.long_put.expiry)
        self.assertLess(spread.long_put.strike, spread.short_put.strike)

    def test_invalid_quotes_and_liquidity_are_rejected(self):
        chain = [
            contract("BADSPREAD", 45, 95, -0.20, bid=0.1, ask=1.0),
            contract("NOVOL", 45, 95, -0.20, volume=0),
            contract("LOWOI", 45, 90, -0.10, oi=99),
        ]
        with self.assertRaisesRegex(OptionChainError, "eligible"):
            select_bull_put_spread(chain, entry_time=ENTRY, underlying_price=100)

    def test_delta_ties_use_higher_open_interest_then_lower_strike(self):
        chain = [
            contract("SHORT-HIGH", 45, 96, -0.20, oi=200),
            contract("SHORT-LOW", 45, 95, -0.20, oi=300),
            contract("LONG-HIGH", 45, 91, -0.10, oi=200),
            contract("LONG-LOW", 45, 90, -0.10, oi=300),
        ]
        spread = select_bull_put_spread(chain, entry_time=ENTRY, underlying_price=100)
        self.assertEqual(spread.short_put.symbol, "SHORT-LOW")
        self.assertEqual(spread.long_put.symbol, "LONG-LOW")

    def test_future_chain_rows_are_ignored(self):
        chain = [contract("S", 45, 95, -0.20), contract("L", 45, 90, -0.10)]
        before = select_bull_put_spread(chain, entry_time=ENTRY, underlying_price=100)
        future = contract("F", 45, 94, -0.20)
        future = OptionContractSnapshot(
            future.symbol, datetime(2030, 1, 1), future.expiry, future.strike,
            future.right, future.bid, future.ask, future.volume, future.open_interest,
            future.delta, future.implied_volatility, future.multiplier, future.minimum_tick,
        )
        after = select_bull_put_spread(chain + [future], entry_time=ENTRY, underlying_price=100)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
