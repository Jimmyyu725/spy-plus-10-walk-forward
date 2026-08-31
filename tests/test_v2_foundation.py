import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spy_plus_10.v2_foundation import (
    EXPECTED_MANIFEST,
    FORBIDDEN_SOURCE,
    PROJECT_NAME,
    V2FoundationError,
    validate_v2_foundation,
)


class V2FoundationTests(unittest.TestCase):
    def test_repository_v2_foundation_contract(self):
        repository_root = Path(__file__).resolve().parents[1]

        status = validate_v2_foundation(repository_root)

        self.assertEqual(status.project_name, "SPY Plus 10 Walk-Forward v2")
        self.assertEqual(status.mode, "evidence-capability-smoke")
        self.assertFalse(status.live_trading)

    def test_live_trading_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "qc-workspace"
            project = workspace / PROJECT_NAME
            project.mkdir(parents=True)
            (workspace / "lean.json").write_text("{}\n", encoding="utf-8")
            (project / "config.json").write_text("{}\n", encoding="utf-8")
            (project / "main.py").write_text(
                "\n".join(
                    (
                        "from AlgorithmImports import *",
                        "",
                        "class SpyPlusTenV2EvidenceCapability(QCAlgorithm):",
                        "    def initialize(self) -> None:",
                        "        self.set_start_date(2015, 1, 2)",
                        "        self.set_end_date(2015, 1, 5)",
                        "        self.set_cash(1_000_000)",
                        "        self._git_commit = self.get_parameter(\"v2_git_commit\")",
                        "        self._run_label = self.get_parameter(\"evidence_run_label\")",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = dict(EXPECTED_MANIFEST)
            manifest["live_trading"] = True
            (project / "project-manifest.json").write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(V2FoundationError, "manifest mismatch"):
                validate_v2_foundation(root)

    def test_repository_v2_main_source_has_no_trading_markers(self):
        repository_root = Path(__file__).resolve().parents[1]
        source = (
            repository_root / "qc-workspace" / PROJECT_NAME / "main.py"
        ).read_text(encoding="utf-8").lower()

        for marker in FORBIDDEN_SOURCE:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_verification_script_reports_v2_foundation_status(self):
        repository_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/verify_v2_foundation.py"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("V2_FOUNDATION_OK project="))


if __name__ == "__main__":
    unittest.main()
