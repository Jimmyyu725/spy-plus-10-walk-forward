import json
import tempfile
import unittest
from pathlib import Path

from tests.project_path import PROJECT_DIR
from baseline import BaselineContractError, load_baseline_contract


class BaselineContractTests(unittest.TestCase):
    def test_repository_contract_is_frozen_and_safe(self):
        contract = load_baseline_contract(PROJECT_DIR / "baseline-contract.json")
        self.assertEqual(contract.initial_cash, "1000000")
        self.assertEqual(contract.annual_hurdle_percentage_points, "0.10")
        self.assertEqual(contract.evaluation_start, "2015-01-01")
        self.assertFalse(contract.formal_evaluation)
        self.assertFalse(contract.live_trading)

    def test_contract_rejects_live_trading(self):
        source = json.loads(
            (PROJECT_DIR / "baseline-contract.json").read_text(encoding="utf-8")
        )
        source["live_trading"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(BaselineContractError, "live_trading"):
                load_baseline_contract(path)

    def test_contract_rejects_changed_hurdle(self):
        source = json.loads(
            (PROJECT_DIR / "baseline-contract.json").read_text(encoding="utf-8")
        )
        source["annual_hurdle_percentage_points"] = "0.09"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(BaselineContractError, "contract mismatch"):
                load_baseline_contract(path)

    def test_explicit_embedded_fallback_supports_cloud_source_deployments(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-deployed.json"
            contract = load_baseline_contract(missing, allow_embedded=True)
        self.assertEqual(contract.initial_cash, "1000000")
        self.assertFalse(contract.formal_evaluation)
        self.assertFalse(contract.live_trading)

    def test_cloud_main_imports_every_baseline_module(self):
        source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
        for marker in (
            "from audit import AuditTrail",
            "from baseline import load_baseline_contract",
            "from benchmark import PricePoint",
            "from costs import equity_execution",
            "from ledger import CashLedger",
            "from metrics import EquityPoint",
        ):
            self.assertIn(marker, source)

    def test_decimal_imports_do_not_collide_with_algorithm_imports(self):
        for name in ("benchmark.py", "costs.py", "ledger.py", "metrics.py", "main.py"):
            source = (PROJECT_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("from decimal import Decimal\n", source)
            self.assertIn("from decimal import Decimal as PythonDecimal", source)


if __name__ == "__main__":
    unittest.main()
