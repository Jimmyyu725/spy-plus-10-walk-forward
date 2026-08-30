import unittest
from datetime import date, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from signals.option_signal import (
    AtmIvObservation,
    DailyClose,
    OptionSignalError,
    compute_option_regime,
    realized_volatility,
    select_atm_iv,
)


START = date(2014, 1, 1)


def closes(count=200, drift=0.001):
    value = 100.0
    result = []
    for index in range(count):
        value *= 1 + drift + (0.0005 if index % 2 else -0.0005)
        result.append(DailyClose(START + timedelta(days=index), value))
    return result


class OptionSignalTests(unittest.TestCase):
    def test_regime_requires_price_above_sma_and_five_point_iv_premium(self):
        prices = closes()
        cutoff = prices[-1].as_of
        iv = [AtmIvObservation(cutoff, cutoff + timedelta(days=45), 121, 122, 0.25, 500)]
        signal = compute_option_regime(prices, iv, cutoff=cutoff, signal_time=cutoff + timedelta(days=1))
        self.assertTrue(signal.eligible)
        self.assertGreaterEqual(signal.implied_volatility - signal.realized_volatility, 0.05)

        low_iv = [AtmIvObservation(cutoff, cutoff + timedelta(days=45), 121, 122, 0.01, 500)]
        self.assertFalse(
            compute_option_regime(prices, low_iv, cutoff=cutoff, signal_time=cutoff + timedelta(days=1)).eligible
        )

    def test_realized_volatility_uses_twenty_completed_returns(self):
        prices = closes(30)
        value = realized_volatility(prices, cutoff=prices[-1].as_of)
        self.assertGreater(value, 0)

    def test_atm_iv_ties_use_earlier_expiry_then_higher_oi_then_lower_strike(self):
        cutoff = date(2015, 1, 2)
        observations = [
            AtmIvObservation(cutoff, cutoff + timedelta(days=46), 101, 100, 0.20, 1000),
            AtmIvObservation(cutoff, cutoff + timedelta(days=44), 101, 100, 0.21, 100),
            AtmIvObservation(cutoff, cutoff + timedelta(days=44), 99, 100, 0.22, 200),
        ]
        self.assertEqual(select_atm_iv(observations, cutoff=cutoff).implied_volatility, 0.22)

    def test_signal_must_follow_cutoff(self):
        prices = closes()
        cutoff = prices[-1].as_of
        with self.assertRaisesRegex(OptionSignalError, "after cutoff"):
            compute_option_regime(prices, [], cutoff=cutoff, signal_time=cutoff)

    def test_future_append_does_not_change_past_signal(self):
        prices = closes()
        cutoff = prices[-1].as_of
        observations = [AtmIvObservation(cutoff, cutoff + timedelta(days=45), 120, 120, 0.25, 100)]
        before = compute_option_regime(prices, observations, cutoff=cutoff, signal_time=cutoff + timedelta(days=1))
        prices.append(DailyClose(date(2030, 1, 1), 1))
        observations.append(AtmIvObservation(date(2030, 1, 1), date(2030, 3, 1), 1, 1, 9, 9999))
        after = compute_option_regime(prices, observations, cutoff=cutoff, signal_time=cutoff + timedelta(days=1))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
