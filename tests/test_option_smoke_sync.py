import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
SMOKE = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Defined Risk Option Smoke"


class OptionSmokeSyncTests(unittest.TestCase):
    def test_shared_modules_are_byte_identical(self):
        for relative in (
            "option_chain.py",
            "option_risk.py",
            "option_lifecycle.py",
            "signals/__init__.py",
            "signals/option_signal.py",
        ):
            self.assertEqual(
                (PRIMARY / relative).read_bytes(),
                (SMOKE / relative).read_bytes(),
            )

    def test_manifest_is_non_formal_and_non_live(self):
        manifest = json.loads(
            (SMOKE / "project-manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["formal_evaluation"])
        self.assertFalse(manifest["live_trading"])
        self.assertEqual(manifest["mode"], "defined-risk-option-smoke")

    def test_adapter_uses_atomic_combo_and_required_statistics(self):
        source = (SMOKE / "main.py").read_text(encoding="utf-8")
        self.assertIn("BrokerageName.QUANT_CONNECT_BROKERAGE", source)
        self.assertNotIn("BrokerageName.QUANTCONNECT_BROKERAGE", source)
        self.assertIn("combo_leg_limit_order", source)
        self.assertNotIn("market_order(", source)
        for marker in (
            '"OPTION_CHAIN_OBSERVATIONS"',
            '"OPTION_ELIGIBLE_SIGNALS"',
            '"OPTION_SPREADS_OPENED"',
            '"OPTION_SPREADS_CLOSED"',
            '"OPTION_NAKED_LEG_COUNT"',
            '"OPTION_MAX_LOSS_BREACH_COUNT"',
            '"OPTION_FUTURE_INPUT_COUNT"',
            '"OPTION_COMBO_STALE_CANCELED"',
            '"OPTION_COMBO_INVALID"',
            '"OPTION_LICENSE_STATUS"',
        ):
            self.assertIn(marker, source)

        self.assertNotIn("statistics.update(", source)


if __name__ == "__main__":
    unittest.main()
