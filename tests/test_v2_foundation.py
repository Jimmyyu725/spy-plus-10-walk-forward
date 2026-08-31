import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spy_plus_10.v2_foundation import (
    EXPECTED_MAIN_SOURCE,
    EXPECTED_MANIFEST,
    FORBIDDEN_SOURCE,
    PROJECT_NAME,
    V2FoundationError,
    validate_v2_foundation,
)


VALID_MAIN = EXPECTED_MAIN_SOURCE
VALID_CONFIG = {
    "algorithm-language": "Python",
    "parameters": {},
    "description": "",
}


class V2FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "qc-workspace"
        self.project = self.workspace / PROJECT_NAME
        self.create_valid_tree()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_valid_tree(self):
        self.project.mkdir(parents=True, exist_ok=True)
        for name in ("config.json", "project-manifest.json", "main.py"):
            path = self.project / name
            if path.is_dir():
                path.rmdir()
        (self.workspace / "lean.json").write_text("{}\n", encoding="utf-8")
        self.write_json("config.json", VALID_CONFIG)
        self.write_json("project-manifest.json", EXPECTED_MANIFEST)
        self.write_project_file("main.py", VALID_MAIN)

    def write_json(self, name, value):
        self.write_project_file(name, json.dumps(value) + "\n")

    def write_project_file(self, name, text):
        (self.project / name).write_text(text, encoding="utf-8")

    def replace_config_with_directory(self):
        config_path = self.project / "config.json"
        config_path.unlink()
        config_path.mkdir()

    def test_repository_v2_foundation_contract(self):
        repository_root = Path(__file__).resolve().parents[1]

        status = validate_v2_foundation(repository_root)

        self.assertEqual(status.project_name, "SPY Plus 10 Walk-Forward v2")
        self.assertEqual(status.mode, "evidence-capability-smoke")
        self.assertFalse(status.live_trading)

    def test_exact_main_contract_is_the_final_capability_algorithm(self):
        tree = ast.parse(EXPECTED_MAIN_SOURCE)
        algorithm = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "SpyPlusTenV2EvidenceCapability"
        )
        initialize = next(
            node for node in algorithm.body
            if isinstance(node, ast.FunctionDef) and node.name == "initialize"
        )
        on_end = next(
            node for node in algorithm.body
            if isinstance(node, ast.FunctionDef) and node.name == "on_end_of_algorithm"
        )
        initialize_attributes = {
            node.attr for node in ast.walk(initialize)
            if isinstance(node, ast.Attribute)
        }
        source_lines = EXPECTED_MAIN_SOURCE.splitlines()
        on_end_source = "\n".join(source_lines[on_end.lineno - 1:on_end.end_lineno])

        self.assertIn("def _run_capability_smoke", EXPECTED_MAIN_SOURCE)
        self.assertIn("SYNTHETIC_CAPABILITY_FIXTURE", EXPECTED_MAIN_SOURCE)
        self.assertIn("for key in all_keys:", EXPECTED_MAIN_SOURCE)
        self.assertNotIn("_run_capability_smoke", initialize_attributes)
        self.assertNotIn("algorithm_id", initialize_attributes)
        self.assertNotIn("project_id", initialize_attributes)
        self.assertLess(
            on_end_source.index("self._run_capability_smoke()"),
            on_end_source.index("self.set_runtime_statistic"),
        )
        self.assertIn("CAPABILITY_SMOKE_ALREADY_FINALIZED", on_end_source)
        self.assertLess(
            EXPECTED_MAIN_SOURCE.index("encoded = encode_chunk(payload)"),
            EXPECTED_MAIN_SOURCE.index("descriptor = chunk_descriptor("),
        )
        self.assertLess(
            EXPECTED_MAIN_SOURCE.index("descriptor = chunk_descriptor("),
            EXPECTED_MAIN_SOURCE.index("manifest = build_manifest("),
        )
        self.assertLess(
            EXPECTED_MAIN_SOURCE.index("manifest = build_manifest("),
            EXPECTED_MAIN_SOURCE.index("for key in all_keys:"),
        )

    def test_valid_temporary_project_passes(self):
        status = validate_v2_foundation(self.root)

        self.assertEqual(status.project_name, PROJECT_NAME)
        self.assertEqual(status.mode, "evidence-capability-smoke")
        self.assertFalse(status.live_trading)

    def test_valid_paired_cloud_config_is_allowed(self):
        self.write_json(
            "config.json",
            {**VALID_CONFIG, "cloud-id": 1, "organization-id": "organization"},
        )

        validate_v2_foundation(self.root)

    def test_mutated_project_is_rejected(self):
        mutations = (
            ("commented required call", lambda: self.write_project_file(
                "main.py", VALID_MAIN.replace(
                    'self.get_parameter("v2_git_commit")',
                    '# self.get_parameter("v2_git_commit")',
                )
            )),
            ("extra buy call", lambda: self.write_project_file(
                "main.py", VALID_MAIN + "        self.buy()\n"
            )),
            ("extra limit order call", lambda: self.write_project_file(
                "main.py", VALID_MAIN + "        self.limit_order()\n"
            )),
            ("extra arbitrary call", lambda: self.write_project_file(
                "main.py", VALID_MAIN + "        self.debug(\"extra\")\n"
            )),
            ("invalid Python", lambda: self.write_project_file("main.py", "class (\n")),
            ("missing lean.json", lambda: (self.workspace / "lean.json").unlink()),
            ("missing config.json", lambda: (self.project / "config.json").unlink()),
            ("missing manifest", lambda: (self.project / "project-manifest.json").unlink()),
            ("missing main", lambda: (self.project / "main.py").unlink()),
            ("invalid lean JSON", lambda: (self.workspace / "lean.json").write_text(
                "{", encoding="utf-8"
            )),
            ("invalid UTF-8 main", lambda: (self.project / "main.py").write_bytes(b"\xff")),
            ("config path raises OSError", self.replace_config_with_directory),
            ("non-object config JSON", lambda: self.write_project_file("config.json", "[]\n")),
            ("duplicate manifest key", lambda: self.write_project_file(
                "project-manifest.json",
                json.dumps(EXPECTED_MANIFEST)[:-1] + ', "live_trading": false}\n',
            )),
            ("manifest bool replaced by zero", lambda: self.write_json(
                "project-manifest.json",
                {**EXPECTED_MANIFEST, "live_trading": 0},
            )),
            ("CSharp config", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "algorithm-language": "CSharp"}
            )),
            ("empty config", lambda: self.write_json("config.json", {})),
            ("invalid parameters", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "parameters": []}
            )),
            ("invalid description", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "description": False}
            )),
            ("unknown config key", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "extra": True}
            )),
            ("invalid cloud id", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "cloud-id": True, "organization-id": "org"}
            )),
            ("unpaired cloud id", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "cloud-id": 1}
            )),
            ("empty organization id", lambda: self.write_json(
                "config.json", {**VALID_CONFIG, "cloud-id": 1, "organization-id": ""}
            )),
        )

        for label, mutate in mutations:
            with self.subTest(label=label):
                self.create_valid_tree()
                mutate()
                with self.assertRaises(V2FoundationError):
                    validate_v2_foundation(self.root)

    def test_every_forbidden_call_is_rejected_with_spacing(self):
        for marker in FORBIDDEN_SOURCE:
            with self.subTest(marker=marker):
                self.create_valid_tree()
                call_name = marker[:-1]
                self.write_project_file(
                    "main.py", VALID_MAIN + f"        self.{call_name} )\n"
                )
                with self.assertRaises(V2FoundationError):
                    validate_v2_foundation(self.root)

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
