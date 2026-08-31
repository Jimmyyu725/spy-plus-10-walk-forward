import ast
import subprocess
import sys
import unittest
from pathlib import Path


class V2CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.cloud = self.root / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
        self.canonical = self.root / "spy_plus_10" / "v2"

    def test_cloud_pure_modules_match_canonical_sources(self):
        for name in ("evidence.py", "attribution.py"):
            with self.subTest(name=name):
                self.assertEqual(
                    (self.cloud / name).read_bytes(),
                    (self.canonical / name).read_bytes(),
                )

    def test_sync_script_repairs_a_cloud_copy_from_canonical_source(self):
        from scripts.sync_v2_cloud_modules import sync_modules

        cloud_evidence = self.cloud / "evidence.py"
        original = cloud_evidence.read_bytes()
        try:
            cloud_evidence.write_bytes(b"drift\n")
            self.assertEqual(sync_modules(), ("evidence.py", "attribution.py"))
            self.assertEqual(cloud_evidence.read_bytes(), (self.canonical / "evidence.py").read_bytes())
        finally:
            cloud_evidence.write_bytes(original)

    def test_cloud_attribution_supports_top_level_evidence_import(self):
        result = subprocess.run(
            [sys.executable, "-c", "import attribution; print(attribution.SLEEVES)"],
            cwd=self.cloud,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("defensive_option", result.stdout)

    def test_main_source_has_exact_capability_contract(self):
        source = (self.cloud / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ]

        self.assertIn("_run_capability_smoke", calls)
        self.assertIn("contains_key", calls)
        self.assertIn("save", calls)
        self.assertIn("read", calls)
        self.assertIn("save_bytes", calls)
        self.assertIn("read_bytes", calls)
        self.assertIn("set_runtime_statistic", calls)
        self.assertIn("SYNTHETIC_CAPABILITY_FIXTURE", source)
        self.assertIn('"2015-01-02"', source)
        self.assertIn('"2015-01-05"', source)
        self.assertLess(source.index("encoded = encode_chunk(payload)"), source.index("descriptor = chunk_descriptor("))
        self.assertLess(source.index("descriptor = chunk_descriptor("), source.index("manifest = build_manifest("))
        self.assertLess(source.index("manifest = build_manifest("), source.index("for key in all_keys:"))
        self.assertLess(
            source.rindex("manifest = build_manifest("),
            source.index('self._save_unique_string(probes["string"], string_value)'),
        )
        self.assertNotIn("add_equity(", source)
        self.assertNotIn("add_future(", source)
        self.assertNotIn("add_option(", source)
        self.assertNotIn("market_order(", source)
        self.assertNotIn("set_holdings(", source)
        self.assertNotIn("set_brokerage_model(", source)
        self.assertNotIn("set_live_mode(", source)


if __name__ == "__main__":
    unittest.main()
