import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
SMOKE = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Equity Factor Smoke"


class EquitySmokeSyncTests(unittest.TestCase):
    def test_shared_modules_are_byte_identical(self):
        for relative in (
            "universe.py",
            "equity_allocation.py",
            "signals/__init__.py",
            "signals/equity_factor.py",
        ):
            self.assertEqual(
                (PRIMARY / relative).read_bytes(),
                (SMOKE / relative).read_bytes(),
            )

    def test_smoke_manifest_is_non_formal_and_non_live(self):
        manifest = json.loads(
            (SMOKE / "project-manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["formal_evaluation"])
        self.assertFalse(manifest["live_trading"])
        self.assertEqual(manifest["mode"], "equity-factor-smoke")

    def test_smoke_has_required_audit_statistics_and_delayed_execution(self):
        source = (SMOKE / "main.py").read_text(encoding="utf-8")
        for marker in (
            '"EQUITY_UNIVERSE_OBSERVATIONS"',
            '"EQUITY_MONTH_END_SIGNALS"',
            '"EQUITY_SELECTED_COUNT"',
            '"EQUITY_ORDER_COUNT"',
            '"EQUITY_FUTURE_INPUT_COUNT"',
            '"EQUITY_REJECTED_POST_CUTOFF_COUNT"',
            '"EQUITY_LICENSE_STATUS"',
            "after_market_open(self._spy, 30)",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("self._future_input_count += 1", source)


if __name__ == "__main__":
    unittest.main()
