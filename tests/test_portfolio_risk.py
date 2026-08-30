import math
import unittest
from datetime import date, datetime, timedelta, timezone

from tests.project_path import PROJECT_DIR  # noqa: F401

from risk import (
    DatedReturn,
    PortfolioRiskError,
    SleeveForecast,
    annualized_volatility,
    coordinate_portfolio_risk,
)


UTC = timezone.utc
CUTOFF = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
DECISION = datetime(2024, 1, 3, 14, 59, tzinfo=UTC)


def forecasts(*, gross=0.1, beta=None):
    beta = beta or {"EQUITY": 0.0, "FUTURES": 0.0, "OPTION": 0.0}
    targets = {"EQUITY": 0.05, "FUTURES": 0.07, "OPTION": 0.03}
    return [
        SleeveForecast(name, CUTOFF, targets[name], gross, beta[name])
        for name in ("EQUITY", "FUTURES", "OPTION")
    ]


class PortfolioRiskTests(unittest.TestCase):
    def test_risk_budget_water_filling_caps_each_sleeve_at_forty_percent(self):
        result = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.04,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        self.assertAlmostEqual(result.risk_contributions["EQUITY"], 0.375)
        self.assertAlmostEqual(result.risk_contributions["FUTURES"], 0.4)
        self.assertAlmostEqual(result.risk_contributions["OPTION"], 0.225)
        self.assertAlmostEqual(result.scales["EQUITY"], 1.0)
        self.assertAlmostEqual(result.scales["FUTURES"], 16 / 21)
        self.assertAlmostEqual(result.scales["OPTION"], 1.0)

    def test_conservative_portfolio_volatility_only_reduces_alpha(self):
        result = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.15,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        self.assertLessEqual(result.conservative_annual_volatility, 0.18 + 1e-10)
        self.assertTrue(all(0 <= scale <= 1 for scale in result.scales.values()))
        self.assertLess(result.scales["EQUITY"], 1.0)

        core_only = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.25,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        self.assertAlmostEqual(core_only.conservative_annual_volatility, 0.25)
        self.assertTrue(all(scale < 1e-8 for scale in core_only.scales.values()))

    def test_alpha_and_total_gross_caps_bind_without_beta_drift(self):
        alpha_capped = coordinate_portfolio_risk(
            forecasts(gross=1.0),
            decision_time=DECISION,
            spy_annual_volatility=0.01,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        self.assertLessEqual(alpha_capped.alpha_gross, 1.0 + 1e-10)
        self.assertLessEqual(alpha_capped.total_gross, 2.0 + 1e-10)

        beta = {"EQUITY": 0.0, "FUTURES": -2.0, "OPTION": -1.0}
        leverage_capped = coordinate_portfolio_risk(
            forecasts(gross=0.8, beta=beta),
            decision_time=DECISION,
            spy_annual_volatility=0.01,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        self.assertLessEqual(leverage_capped.total_gross, 2.0 + 1e-10)
        self.assertAlmostEqual(leverage_capped.predicted_beta, 1.0)
        self.assertGreaterEqual(leverage_capped.core_spy_weight, 0.0)

    def test_core_exactly_corrects_sleeve_beta(self):
        beta = {"EQUITY": 0.0, "FUTURES": 0.25, "OPTION": 0.05}
        result = coordinate_portfolio_risk(
            forecasts(beta=beta),
            decision_time=DECISION,
            spy_annual_volatility=0.04,
            peak_equity=1_000_000,
            current_equity=1_000_000,
        )
        alpha_beta = sum(result.scales[name] * beta[name] for name in beta)
        self.assertAlmostEqual(result.core_spy_weight, 1.0 - alpha_beta)
        self.assertAlmostEqual(result.predicted_beta, 1.0)
        self.assertGreaterEqual(result.predicted_beta, 0.8)
        self.assertLessEqual(result.predicted_beta, 1.2)

    def test_drawdown_states_are_normal_half_and_zero(self):
        normal = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.04,
            peak_equity=1_000_000,
            current_equity=850_000.01,
        )
        half = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.04,
            peak_equity=1_000_000,
            current_equity=850_000,
        )
        zero = coordinate_portfolio_risk(
            forecasts(),
            decision_time=DECISION,
            spy_annual_volatility=0.04,
            peak_equity=1_000_000,
            current_equity=750_000,
        )
        self.assertEqual(normal.drawdown_scale, 1.0)
        self.assertEqual(half.drawdown_scale, 0.5)
        self.assertEqual(zero.drawdown_scale, 0.0)
        self.assertTrue(all(scale == 0 for scale in zero.scales.values()))
        self.assertAlmostEqual(zero.core_spy_weight, 1.0)

    def test_missing_duplicate_future_or_nonfinite_forecasts_fail_closed(self):
        cases = [
            forecasts()[:-1],
            forecasts() + [forecasts()[0]],
            [
                SleeveForecast(
                    item.name,
                    DECISION,
                    item.target_volatility,
                    item.proposed_gross,
                    item.estimated_beta,
                )
                for item in forecasts()
            ],
            [
                SleeveForecast(
                    item.name,
                    item.data_cutoff,
                    item.target_volatility,
                    item.proposed_gross,
                    math.nan if item.name == "OPTION" else item.estimated_beta,
                )
                for item in forecasts()
            ],
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(PortfolioRiskError):
                coordinate_portfolio_risk(
                    case,
                    decision_time=DECISION,
                    spy_annual_volatility=0.04,
                    peak_equity=1_000_000,
                    current_equity=1_000_000,
                )

    def test_spy_volatility_uses_only_completed_points_through_cutoff(self):
        start = date(2023, 1, 1)
        past = [
            DatedReturn(start + timedelta(days=index), (-1) ** index * 0.01)
            for index in range(60)
        ]
        cutoff = past[-1].as_of
        original = annualized_volatility(past, cutoff=cutoff, lookback=60)
        future = past + [DatedReturn(cutoff + timedelta(days=1), 0.90)]
        appended = annualized_volatility(future, cutoff=cutoff, lookback=60)
        self.assertAlmostEqual(original, appended)
        self.assertGreater(original, 0)


if __name__ == "__main__":
    unittest.main()
