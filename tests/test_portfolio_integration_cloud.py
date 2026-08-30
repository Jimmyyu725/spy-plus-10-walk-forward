import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"


class PortfolioIntegrationCloudTests(unittest.TestCase):
    def test_manifest_is_nonformal_integration_smoke(self):
        manifest = json.loads(
            (PROJECT / "project-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["mode"], "portfolio-integration-smoke")
        self.assertEqual(manifest["start_date"], "2012-01-01")
        self.assertEqual(manifest["end_date"], "2015-03-31")
        self.assertFalse(manifest["formal_evaluation"])
        self.assertFalse(manifest["live_trading"])

    def test_main_is_orchestration_only_with_raw_spy_and_daily_evidence(self):
        source = (PROJECT / "main.py").read_text(encoding="utf-8")
        for marker in (
            "EquityFactorSleeve",
            "FuturesTrendSleeve",
            "DefinedRiskOptionSleeve",
            "coordinate_portfolio_risk",
            "DataNormalizationMode.RAW",
            "DataNormalizationMode.TOTAL_RETURN",
            'self.plot("Daily Evidence", "Strategy Equity"',
            'self.plot("Daily Evidence", "SPY Total Return"',
            "def can_trade_now(self):",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("compute_trend_signal", source)
        self.assertNotIn("compute_raw_equity_factor", source)
        self.assertNotIn("select_bull_put_spread", source)

    def test_main_has_irreversible_portfolio_and_margin_gates(self):
        source = (PROJECT / "main.py").read_text(encoding="utf-8")
        for marker in (
            '"PORTFOLIO_GATE_STATUS"',
            '"PORTFOLIO_GATE_FAILURES"',
            '"PORTFOLIO_MAX_ALPHA_GROSS"',
            '"PORTFOLIO_MAX_TOTAL_GROSS"',
            '"PORTFOLIO_MAX_RISK_CONTRIBUTION"',
            '"PORTFOLIO_MIN_BETA"',
            '"PORTFOLIO_MAX_BETA"',
            '"PORTFOLIO_MAX_MARGIN_USED_FRACTION"',
            '"PORTFOLIO_DAILY_EVIDENCE_COUNT"',
            '"PORTFOLIO_REGULATORY_FEE_STATUS"',
            "def on_margin_call(self, requests):",
            "def on_margin_call_warning(self):",
        ):
            self.assertIn(marker, source)
        self.assertIn("self._gate_failures.add", source)

    def test_reality_models_apply_frozen_costs_and_only_allowed_slippage(self):
        source = (
            PROJECT / "cloud_adapters" / "reality_models.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "class IntegratedFeeModel(FeeModel):",
            "SECTION31_MAX_RATE_PER_DOLLAR",
            "EQUITY_TAF_PER_SHARE",
            "OPTION_TAF_PER_CONTRACT",
            "FUTURE_REGULATORY_PER_CONTRACT",
            "class EquityAdverseSlippageModel:",
            "class FutureOneTickSlippageModel:",
            "multiplier not in {1.0, 2.0}",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
