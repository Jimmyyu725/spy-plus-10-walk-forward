import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
SMOKE = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Futures Trend Smoke"


class FuturesSmokeSyncTests(unittest.TestCase):
    def test_shared_modules_are_byte_identical(self):
        for relative in (
            "futures_allocation.py",
            "futures_roll.py",
            "signals/__init__.py",
            "signals/futures_trend.py",
        ):
            self.assertEqual(
                (PRIMARY / relative).read_bytes(),
                (SMOKE / relative).read_bytes(),
            )

    def test_smoke_manifest_is_non_formal_and_non_live(self):
        text = (SMOKE / "project-manifest.json").read_text(encoding="utf-8")
        self.assertIn('"formal_evaluation": false', text)
        self.assertIn('"live_trading": false', text)

    def test_smoke_uses_lean_slippage_interface(self):
        source = (SMOKE / "main.py").read_text(encoding="utf-8")
        self.assertIn("class OneTickSlippageModel(ISlippageModel):", source)
        self.assertNotIn("class OneTickSlippageModel(SlippageModel):", source)


if __name__ == "__main__":
    unittest.main()
