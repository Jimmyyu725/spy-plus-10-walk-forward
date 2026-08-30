import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
ADAPTERS = PROJECT / "cloud_adapters"


class CloudSleeveAdapterTests(unittest.TestCase):
    def test_frozen_portfolio_contract(self):
        contract = json.loads(
            (PROJECT / "portfolio-integration-contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["module_target_volatility"], {
            "EQUITY": 0.05,
            "FUTURES": 0.07,
            "OPTION": 0.03,
        })
        self.assertEqual(contract["max_alpha_risk_contribution"], 0.4)
        self.assertEqual(contract["alpha_gross_cap"], 1.0)
        self.assertEqual(contract["total_gross_cap"], 2.0)
        self.assertFalse(contract["formal_evaluation"])
        self.assertFalse(contract["live_trading"])

    def test_adapters_are_services_not_algorithms(self):
        expected = {
            "equity_sleeve.py": "class EquityFactorSleeve:",
            "futures_sleeve.py": "class FuturesTrendSleeve:",
            "option_sleeve.py": "class DefinedRiskOptionSleeve:",
        }
        for filename, class_marker in expected.items():
            source = (ADAPTERS / filename).read_text(encoding="utf-8")
            self.assertIn(class_marker, source)
            self.assertNotIn("(QCAlgorithm)", source)
            self.assertIn("def __getattr__(self, name):", source)
            self.assertIn("def statistics(self):", source)

    def test_equity_returns_hedge_to_orchestrator_and_never_liquidates_account(self):
        source = (ADAPTERS / "equity_sleeve.py").read_text(encoding="utf-8")
        self.assertIn("def execute_pending(self, scale):", source)
        self.assertIn("def spy_hedge_weight(self):", source)
        self.assertNotIn("self.set_holdings(targets, True)", source)
        self.assertNotIn("PortfolioTarget(self._spy", source)
        self.assertIn("scale >= self._last_scale", source)

    def test_futures_uses_only_actual_contracts_and_current_scale(self):
        source = (ADAPTERS / "futures_sleeve.py").read_text(encoding="utf-8")
        self.assertIn("def set_scale(self, scale):", source)
        self.assertIn("weights[root] * self._allowed_scale", source)
        self.assertIn("select_volume_contract", source)
        self.assertNotIn("market_order(future.symbol", source)
        self.assertIn("self._contract_snapshots", source)
        self.assertGreaterEqual(source.count("select_volume_contract("), 2)
        self.assertIn("def applied_scale(self):", source)
        self.assertIn("def _reduce_current_contracts(self, weights):", source)
        self.assertNotIn("self._chains[root] = chain", source)

    def test_option_retains_atomic_defined_risk_and_scale(self):
        source = (ADAPTERS / "option_sleeve.py").read_text(encoding="utf-8")
        self.assertIn("def set_scale(self, scale):", source)
        self.assertIn("combo_leg_limit_order", source)
        self.assertIn(
            "float(self.portfolio.total_portfolio_value) * self._scale",
            source,
        )
        self.assertIn('"DRAWDOWN_EXIT"', source)
        self.assertIn("combo_market_order", source)
        self.assertIn("def actual_gross(self):", source)
        self.assertIn("short_limit = max(", source)
        self.assertIn("long_limit = max(", source)
        self.assertIn("self._last_exit_attempt_date", source)
        self.assertNotIn("self.market_order(", source)


if __name__ == "__main__":
    unittest.main()
