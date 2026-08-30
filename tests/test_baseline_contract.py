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


if __name__ == "__main__":
    unittest.main()
