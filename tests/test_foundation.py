import json
import tempfile
import unittest
from pathlib import Path

from spy_plus_10.foundation import FoundationValidationError, validate_foundation


VALID_MAIN = """from AlgorithmImports import *

class SpyPlusTenWalkForward(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 9)
        self.set_cash(1_000_000)
        self.spy = self.add_equity(\"SPY\", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)
"""


class FoundationValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_valid_tree(self):
        workspace = self.root / "qc-workspace"
        project = workspace / "SPY Plus 10 Walk-Forward"
        project.mkdir(parents=True)
        (workspace / "lean.json").write_text("{}\n", encoding="utf-8")
        (project / "config.json").write_text("{}\n", encoding="utf-8")
        (project / "main.py").write_text(VALID_MAIN, encoding="utf-8")
        manifest = {
            "benchmark": "SPY",
            "end_date": "2015-01-09",
            "formal_evaluation": False,
            "initial_cash": 1_000_000,
            "language": "Python",
            "live_trading": False,
            "mode": "foundation-smoke",
            "name": "SPY Plus 10 Walk-Forward",
            "start_date": "2015-01-02",
        }
        (project / "project-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_missing_workspace_fails_closed(self):
        with self.assertRaisesRegex(FoundationValidationError, "lean.json"):
            validate_foundation(self.root)

    def test_valid_foundation_passes(self):
        self.create_valid_tree()
        result = validate_foundation(self.root)
        self.assertEqual(result.project_name, "SPY Plus 10 Walk-Forward")
        self.assertEqual(result.mode, "foundation-smoke")
        self.assertFalse(result.formal_evaluation)

    def test_plaintext_token_pattern_fails(self):
        self.create_valid_tree()
        leaked = "a" * 64
        (self.root / "leak.txt").write_text(leaked, encoding="utf-8")
        with self.assertRaisesRegex(FoundationValidationError, "credential-like"):
            validate_foundation(self.root)

    def test_live_trading_marker_fails(self):
        self.create_valid_tree()
        project = self.root / "qc-workspace" / "SPY Plus 10 Walk-Forward"
        manifest = json.loads((project / "project-manifest.json").read_text())
        manifest["live_trading"] = True
        (project / "project-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(FoundationValidationError, "live_trading"):
            validate_foundation(self.root)

    def test_repository_foundation_contract(self):
        repository_root = Path(__file__).resolve().parents[1]
        status = validate_foundation(repository_root)
        self.assertEqual(status.project_name, "SPY Plus 10 Walk-Forward")
        self.assertEqual(status.mode, "frozen-evaluation")
        self.assertTrue(status.formal_evaluation)


if __name__ == "__main__":
    unittest.main()
