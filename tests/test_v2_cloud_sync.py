import ast
import contextlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from spy_plus_10.v2.evidence import (
    build_manifest_key,
    build_probe_keys,
)


COMMIT = "a" * 40
PROJECT = "project"
RUN_LABEL = "run"
ALGORITHM = "algorithm"


class FakeObjectStore:
    def __init__(
        self,
        *,
        false_suffix=None,
        write_then_false_suffix=None,
        type_error_suffix=None,
        mismatch_suffix=None,
        not_implemented_save_suffix=None,
        not_implemented_read_suffix=None,
    ):
        self.values = {}
        self.writes = []
        self.false_suffix = false_suffix
        self.write_then_false_suffix = write_then_false_suffix
        self.type_error_suffix = type_error_suffix
        self.mismatch_suffix = mismatch_suffix
        self.not_implemented_save_suffix = not_implemented_save_suffix
        self.not_implemented_read_suffix = not_implemented_read_suffix

    def contains_key(self, key):
        return key in self.values

    def save(self, key, value):
        self.writes.append(("string", key))
        if key.endswith(self.false_suffix or "\0"):
            return False
        self.values[key] = value
        if key.endswith(self.write_then_false_suffix or "\0"):
            return False
        return True

    def read(self, key):
        return self.values[key]

    def save_bytes(self, key, value):
        self.writes.append(("bytes", key))
        if key.endswith(self.type_error_suffix or "\0"):
            raise TypeError("unexpected Object Store binding error")
        if key.endswith(self.not_implemented_save_suffix or "\0"):
            raise NotImplementedError("bytes save unsupported")
        if key.endswith(self.false_suffix or "\0"):
            return False
        self.values[key] = bytes(value)
        if key.endswith(self.write_then_false_suffix or "\0"):
            return False
        return True

    def read_bytes(self, key):
        value = self.values[key]
        if key.endswith(self.not_implemented_read_suffix or "\0"):
            raise NotImplementedError("bytes read unsupported")
        if key.endswith(self.mismatch_suffix or "\0"):
            return b"mismatch"
        return value


class FakeQCAlgorithm:
    next_store = None

    def __init__(self):
        self.object_store = type(self).next_store
        self.algorithm_id = ALGORITHM
        self.project_id = PROJECT
        self.statistics = {}

    def set_start_date(self, *args):
        self.start_date = args

    def set_end_date(self, *args):
        self.end_date = args

    def set_cash(self, value):
        self.cash = value

    def get_parameter(self, name):
        return {"v2_git_commit": COMMIT, "evidence_run_label": RUN_LABEL}[name]

    def debug(self, message):
        self.debug_message = message

    def set_runtime_statistic(self, key, value):
        self.statistics[key] = value


class V2CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.cloud = self.root / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
        self.canonical = self.root / "spy_plus_10" / "v2"

    @contextlib.contextmanager
    def load_cloud_main(self, store):
        algorithm_imports = types.ModuleType("AlgorithmImports")
        algorithm_imports.QCAlgorithm = FakeQCAlgorithm
        module_name = "v2_cloud_main_test_module"
        previous_evidence = sys.modules.pop("evidence", None)
        previous_main = sys.modules.pop(module_name, None)
        FakeQCAlgorithm.next_store = store
        sys.path.insert(0, str(self.cloud))
        try:
            with mock.patch.dict(sys.modules, {"AlgorithmImports": algorithm_imports}):
                spec = importlib.util.spec_from_file_location(module_name, self.cloud / "main.py")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                yield module.SpyPlusTenV2EvidenceCapability()
        finally:
            sys.path.pop(0)
            sys.modules.pop("evidence", None)
            sys.modules.pop(module_name, None)
            if previous_evidence is not None:
                sys.modules["evidence"] = previous_evidence
            if previous_main is not None:
                sys.modules[module_name] = previous_main
            FakeQCAlgorithm.next_store = None

    def test_cloud_pure_modules_match_canonical_sources(self):
        for name in ("evidence.py", "attribution.py"):
            with self.subTest(name=name):
                self.assertEqual(
                    (self.cloud / name).read_bytes(),
                    (self.canonical / name).read_bytes(),
                )

    def test_sync_script_repairs_a_cloud_copy_from_temporary_canonical_source(self):
        from scripts.sync_v2_cloud_modules import sync_modules

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "evidence.py").write_bytes(b"new evidence\n")
            (source / "attribution.py").write_bytes(b"new attribution\n")
            (target / "evidence.py").write_bytes(b"old evidence\n")
            (target / "attribution.py").write_bytes(b"old attribution\n")

            self.assertEqual(
                sync_modules(source=source, target=target),
                ("evidence.py", "attribution.py"),
            )
            self.assertEqual((target / "evidence.py").read_bytes(), b"new evidence\n")
            self.assertEqual((target / "attribution.py").read_bytes(), b"new attribution\n")

    def test_sync_preserves_existing_target_modes_and_uses_source_modes_for_new_targets(self):
        from scripts.sync_v2_cloud_modules import sync_modules

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            existing_target = root / "existing-target"
            new_target = root / "new-target"
            source.mkdir()
            existing_target.mkdir()
            new_target.mkdir()
            for name, mode in (("evidence.py", 0o640), ("attribution.py", 0o600)):
                path = source / name
                path.write_bytes(f"new {name}\n".encode())
                path.chmod(mode)
            for name, mode in (("evidence.py", 0o644), ("attribution.py", 0o640)):
                path = existing_target / name
                path.write_bytes(f"old {name}\n".encode())
                path.chmod(mode)

            sync_modules(source=source, target=existing_target)
            sync_modules(source=source, target=new_target)

            self.assertEqual((existing_target / "evidence.py").stat().st_mode & 0o777, 0o644)
            self.assertEqual((existing_target / "attribution.py").stat().st_mode & 0o777, 0o640)
            self.assertEqual((new_target / "evidence.py").stat().st_mode & 0o777, 0o640)
            self.assertEqual((new_target / "attribution.py").stat().st_mode & 0o777, 0o600)

    def test_sync_preflight_missing_second_source_never_changes_temporary_target(self):
        from scripts.sync_v2_cloud_modules import sync_modules

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "evidence.py").write_bytes(b"new evidence\n")
            (target / "evidence.py").write_bytes(b"old evidence\n")
            (target / "attribution.py").write_bytes(b"old attribution\n")

            with self.assertRaisesRegex(RuntimeError, "attribution.py"):
                sync_modules(source=source, target=target)
            self.assertEqual((target / "evidence.py").read_bytes(), b"old evidence\n")
            self.assertEqual((target / "attribution.py").read_bytes(), b"old attribution\n")
            self.assertEqual(list(target.glob(".*.sync.tmp")), [])

    def test_sync_replace_failure_restores_temporary_target_without_half_sync(self):
        from scripts import sync_v2_cloud_modules

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "evidence.py").write_bytes(b"new evidence\n")
            (source / "attribution.py").write_bytes(b"new attribution\n")
            (target / "evidence.py").write_bytes(b"old evidence\n")
            (target / "attribution.py").write_bytes(b"old attribution\n")
            real_replace = os.replace
            failed = False

            def fail_second_replace(source_path, target_path):
                nonlocal failed
                if Path(target_path) == target / "attribution.py" and not failed:
                    failed = True
                    raise OSError("staged replace failed")
                return real_replace(source_path, target_path)

            with mock.patch.object(sync_v2_cloud_modules.os, "replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(RuntimeError, "atomic sync failed"):
                    sync_v2_cloud_modules.sync_modules(source=source, target=target)
            self.assertEqual((target / "evidence.py").read_bytes(), b"old evidence\n")
            self.assertEqual((target / "attribution.py").read_bytes(), b"old attribution\n")
            self.assertEqual(list(target.glob(".*.sync.tmp")), [])

    def test_sync_base_exception_restores_target_cleans_temps_and_reraises_same_interrupt(self):
        from scripts import sync_v2_cloud_modules

        for exception_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception_type=exception_type.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                target = root / "target"
                source.mkdir()
                target.mkdir()
                (source / "evidence.py").write_bytes(b"new evidence\n")
                (source / "attribution.py").write_bytes(b"new attribution\n")
                (target / "evidence.py").write_bytes(b"old evidence\n")
                (target / "attribution.py").write_bytes(b"old attribution\n")
                real_replace = os.replace
                interrupt = exception_type("stop during replacement")

                def interrupt_second_replace(source_path, target_path):
                    if Path(target_path) == target / "attribution.py":
                        raise interrupt
                    return real_replace(source_path, target_path)

                with mock.patch.object(
                    sync_v2_cloud_modules.os, "replace", side_effect=interrupt_second_replace
                ):
                    with self.assertRaises(exception_type) as caught:
                        sync_v2_cloud_modules.sync_modules(source=source, target=target)
                self.assertIs(caught.exception, interrupt)
                self.assertEqual((target / "evidence.py").read_bytes(), b"old evidence\n")
                self.assertEqual((target / "attribution.py").read_bytes(), b"old attribution\n")
                self.assertEqual(list(target.glob(".*.sync.tmp")), [])

    def test_sync_post_replace_base_exception_restores_previously_unrecorded_target(self):
        from scripts import sync_v2_cloud_modules

        for exception_type in (KeyboardInterrupt, SystemExit):
            for target_existed in (True, False):
                with self.subTest(
                    exception_type=exception_type.__name__, target_existed=target_existed
                ), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / "source"
                    target = root / "target"
                    source.mkdir()
                    target.mkdir()
                    (source / "evidence.py").write_bytes(b"new evidence\n")
                    (source / "attribution.py").write_bytes(b"new attribution\n")
                    evidence_target = target / "evidence.py"
                    if target_existed:
                        evidence_target.write_bytes(b"old evidence\n")
                    real_replace = os.replace
                    interrupt = exception_type("stop after replacement")

                    def replace_then_interrupt(source_path, target_path):
                        result = real_replace(source_path, target_path)
                        if Path(target_path) == evidence_target:
                            raise interrupt
                        return result

                    with mock.patch.object(
                        sync_v2_cloud_modules.os, "replace", side_effect=replace_then_interrupt
                    ):
                        with self.assertRaises(exception_type) as caught:
                            sync_v2_cloud_modules.sync_modules(source=source, target=target)
                    self.assertIs(caught.exception, interrupt)
                    if target_existed:
                        self.assertEqual(evidence_target.read_bytes(), b"old evidence\n")
                    else:
                        self.assertFalse(evidence_target.exists())
                    self.assertFalse((target / "attribution.py").exists())
                    self.assertEqual(list(target.glob(".*.sync.tmp")), [])

    def test_cloud_main_success_records_pass_statuses(self):
        store = FakeObjectStore()
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            algorithm.on_end_of_algorithm()

        self.assertEqual(algorithm._status, {
            "string": "PASS", "bytes": "PASS", "chunk": "PASS", "manifest": "PASS",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "PASS")
        self.assertEqual(algorithm.statistics["V2_TRANSPORT"], "bytes")

    def test_cloud_main_defers_empty_algorithm_id_until_engine_sets_it_on_end(self):
        store = FakeObjectStore()
        with self.load_cloud_main(store) as algorithm:
            algorithm.algorithm_id = ""

            algorithm.initialize()

            self.assertEqual(store.writes, [])
            self.assertEqual(algorithm._status, {
                "string": "UNVERIFIED", "bytes": "UNVERIFIED",
                "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
            })
            algorithm.algorithm_id = ALGORITHM
            algorithm.on_end_of_algorithm()

        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "PASS")
        self.assertEqual(len(store.writes), 4)

    def test_cloud_main_empty_algorithm_id_on_end_fails_closed_without_writes(self):
        store = FakeObjectStore()
        with self.load_cloud_main(store) as algorithm:
            algorithm.algorithm_id = ""
            algorithm.initialize()

            with self.assertRaisesRegex(Exception, "invalid algorithm_id"):
                algorithm.on_end_of_algorithm()

        self.assertEqual(store.writes, [])
        self.assertEqual(algorithm._status, {
            "string": "UNVERIFIED", "bytes": "UNVERIFIED",
            "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "UNVERIFIED")

    def test_cloud_main_on_end_runs_capability_smoke_once(self):
        store = FakeObjectStore()
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            algorithm.on_end_of_algorithm()
            writes_after_first_end = list(store.writes)
            statistics_after_first_end = dict(algorithm.statistics)

            with self.assertRaisesRegex(RuntimeError, "CAPABILITY_SMOKE_ALREADY_FINALIZED"):
                algorithm.on_end_of_algorithm()

        self.assertEqual(store.writes, writes_after_first_end)
        self.assertEqual(algorithm.statistics, statistics_after_first_end)

    def test_cloud_main_expected_bytes_failure_uses_string_fallback(self):
        store = FakeObjectStore(false_suffix="capability/bytes-1kb.bin")
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            algorithm.on_end_of_algorithm()

        self.assertEqual(algorithm._status, {
            "string": "PASS", "bytes": "FAIL", "chunk": "PASS", "manifest": "PASS",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "PASS_WITH_STRING_FALLBACK")
        self.assertEqual(algorithm.statistics["V2_TRANSPORT"], "base64-gzip-string")

    def test_cloud_main_bytes_save_and_read_not_implemented_are_legal_fallbacks(self):
        cases = (
            ("save", FakeObjectStore(not_implemented_save_suffix="capability/bytes-1kb.bin")),
            ("read", FakeObjectStore(not_implemented_read_suffix="capability/bytes-1kb.bin")),
        )
        for label, store in cases:
            with self.subTest(label=label), self.load_cloud_main(store) as algorithm:
                algorithm.initialize()
                algorithm.on_end_of_algorithm()
                self.assertEqual(algorithm._status, {
                    "string": "PASS", "bytes": "FAIL", "chunk": "PASS", "manifest": "PASS",
                })
                self.assertEqual(
                    algorithm.statistics["V2_CAPABILITY_STATUS"], "PASS_WITH_STRING_FALLBACK"
                )

    def test_cloud_main_type_error_does_not_fallback(self):
        store = FakeObjectStore(type_error_suffix="capability/bytes-1kb.bin")
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            with self.assertRaisesRegex(TypeError, "binding error"):
                algorithm.on_end_of_algorithm()

        self.assertEqual(algorithm._status, {
            "string": "PASS", "bytes": "UNVERIFIED", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "UNVERIFIED")
        self.assertEqual(len(store.writes), 2)

    def test_cloud_main_existing_key_performs_zero_writes(self):
        store = FakeObjectStore()
        manifest_key = build_manifest_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
        store.values[manifest_key] = "already present"
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            with self.assertRaisesRegex(RuntimeError, "OBJECT_STORE_KEY_EXISTS"):
                algorithm.on_end_of_algorithm()

        self.assertEqual(store.writes, [])
        self.assertEqual(algorithm._status, {
            "string": "UNVERIFIED", "bytes": "UNVERIFIED", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "UNVERIFIED")

    def test_cloud_main_string_chunk_and_manifest_failures_remain_unverified(self):
        cases = (
            ("string", FakeObjectStore(false_suffix="capability/string-1kb.txt"), {
                "string": "UNVERIFIED", "bytes": "UNVERIFIED", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
            }),
            ("chunk", FakeObjectStore(false_suffix="evidence/2015.jsonGz"), {
                "string": "PASS", "bytes": "PASS", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
            }),
            ("manifest", FakeObjectStore(false_suffix="manifest.json"), {
                "string": "PASS", "bytes": "PASS", "chunk": "PASS", "manifest": "UNVERIFIED",
            }),
        )
        for label, store, expected_status in cases:
            with self.subTest(label=label), self.load_cloud_main(store) as algorithm:
                algorithm.initialize()
                with self.assertRaises(RuntimeError):
                    algorithm.on_end_of_algorithm()
                self.assertEqual(algorithm._status, expected_status)
                self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "UNVERIFIED")

    def test_cloud_main_persisted_false_save_results_never_report_pass(self):
        cases = (
            ("string", "capability/string-1kb.txt", {
                "string": "UNVERIFIED", "bytes": "UNVERIFIED", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
            }),
            ("chunk", "evidence/2015.jsonGz", {
                "string": "PASS", "bytes": "PASS", "chunk": "UNVERIFIED", "manifest": "UNVERIFIED",
            }),
            ("manifest", "manifest.json", {
                "string": "PASS", "bytes": "PASS", "chunk": "PASS", "manifest": "UNVERIFIED",
            }),
        )
        for label, suffix, expected_status in cases:
            store = FakeObjectStore(write_then_false_suffix=suffix)
            with self.subTest(label=label), self.load_cloud_main(store) as algorithm:
                algorithm.initialize()
                with self.assertRaises(RuntimeError):
                    algorithm.on_end_of_algorithm()
                self.assertEqual(algorithm._status, expected_status)
                self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "UNVERIFIED")
                self.assertTrue(any(key.endswith(suffix) for _, key in store.writes))
                self.assertTrue(any(key.endswith(suffix) for key in store.values))

    def test_cloud_main_persisted_bytes_mismatch_falls_back_but_records_bytes_failure(self):
        store = FakeObjectStore(mismatch_suffix="capability/bytes-1kb.bin")
        probes = build_probe_keys(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
        with self.load_cloud_main(store) as algorithm:
            algorithm.initialize()
            algorithm.on_end_of_algorithm()

        self.assertIn(probes["bytes"], store.values)
        self.assertEqual(algorithm._status, {
            "string": "PASS", "bytes": "FAIL", "chunk": "PASS", "manifest": "PASS",
        })
        self.assertEqual(algorithm.statistics["V2_CAPABILITY_STATUS"], "PASS_WITH_STRING_FALLBACK")

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

    def test_attribution_preserves_an_internal_relative_evidence_import_error(self):
        source = (self.canonical / "attribution.py").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "attribution.py").write_bytes(source)
            (package / "evidence.py").write_text(
                'raise ImportError("inside evidence")\n', encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, "-c", "import package.attribution"],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.rstrip().endswith("ImportError: inside evidence"), result.stderr)

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
