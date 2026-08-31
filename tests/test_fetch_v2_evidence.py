import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_v2_verifier import archive_fixture


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_v2_evidence", ROOT / "scripts" / "fetch_v2_evidence.py")
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)
VERIFY_SPEC = importlib.util.spec_from_file_location("verify_v2_evidence", ROOT / "scripts" / "verify_v2_evidence.py")
verifier_cli = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verifier_cli)


class FakeClient:
    def __init__(self, archive, *, fail_at=None):
        self.archive = archive
        self.fail_at = fail_at
        self.calls = []

    def _call(self, name, value):
        self.calls.append((name, value))
        if self.fail_at == name:
            raise RuntimeError("synthetic API failure")

    def read_backtest(self, project_id, backtest_id):
        self._call("backtest", backtest_id)
        return self.archive["backtest"]

    def read_all_backtest_rows(self, endpoint, field, project_id, backtest_id):
        self._call(field, endpoint)
        return self.archive[field]

    def list_objects(self, organization_id, prefix):
        self._call("list", prefix)
        entries = self.archive["object_list"]["objects"]
        direct = [item for item in entries if item["key"].rsplit("/", 1)[0] == prefix]
        if prefix.endswith("/capability") or prefix.endswith("/evidence"):
            return {"objects": direct, "object_storage_used": self.archive["object_list"]["object_storage_used"]}
        return {"objects": [item for item in direct if item["key"].endswith("manifest.json")] + [
            {"key": prefix + "/capability", "size": 0, "folder": True},
            {"key": prefix + "/evidence", "size": 0, "folder": True},
        ], "object_storage_used": self.archive["object_list"]["object_storage_used"]}

    def download_object(self, organization_id, key):
        self._call("download", key)
        return self.archive["objects"][key]


class FlattenedClient(FakeClient):
    """Regression double for the old, invalid descendant-flattened assumption."""
    def list_objects(self, organization_id, prefix):
        self._call("list", prefix)
        if prefix.endswith(("/capability", "/evidence")):
            return {"objects": [], "object_storage_used": self.archive["object_list"]["object_storage_used"]}
        return self.archive["object_list"]


class FetchV2EvidenceTests(unittest.TestCase):
    def test_success_publishes_only_after_full_download_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capability"
            fixture = archive_fixture()
            fixture["backtest"]["message"] = "Authorization: Bearer secret-value https://example.invalid/file?sig=secret-value"
            fixture["backtest"]["metadata"] = {"access-token": "structured-secret", "clientSecret": "camel-secret", "user": "alice", "url": "https://example.invalid/plain"}
            client = FakeClient(fixture)
            result = fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=target)
            self.assertTrue(target.is_dir())
            self.assertEqual(result["verification"]["overall_status"], "PASS")
            self.assertEqual([name for name, _ in client.calls[:6]], ["backtest", "orders", "trades", "list", "list", "download"])
            prefix = fixture["backtest"]["backtest"]["runtimeStatistics"]["V2_EVIDENCE_PREFIX"]
            self.assertEqual([value for name, value in client.calls if name == "list"], [prefix, prefix + "/capability", prefix + "/evidence"])
            key_map = json.loads((target / "key-map.json").read_text())
            list_records = json.loads((target / "object-lists.json").read_text())
            self.assertEqual(set(list_records), {"root", "capability", "evidence"})
            self.assertTrue(all(record["object_storage_used"] == fixture["object_list"]["object_storage_used"] and isinstance(record["listed_paths"], list) for record in list_records.values()))
            downloaded_keys = [value for name, value in client.calls if name == "download"]
            self.assertEqual(key_map, {key: f"objects/{index:04d}.bin" for index, key in enumerate(downloaded_keys, 1)})
            archived_text = "\n".join(path.read_text(errors="ignore") for path in target.glob("*.json"))
            self.assertNotIn("secret-value", archived_text)
            self.assertNotIn("structured-secret", archived_text)
            self.assertNotIn("camel-secret", archived_text)
            self.assertIn("https://example.invalid/plain", archived_text)
            self.assertEqual(fetcher._safe_value({"user": "alice", "url": "https://example.invalid/plain"}), {"user": "alice", "url": "https://example.invalid/plain"})
            self.assertEqual(verifier_cli.verify_archive(verifier_cli.load_archive(target), expected_identity={"project_id": 123, "backtest_id": "bt", "organization_id": "org"}), result["verification"])

    def test_existing_target_causes_zero_api_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capability"; target.mkdir()
            client = FakeClient(archive_fixture())
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=target)
            self.assertEqual(client.calls, [])

    def test_flattened_root_listing_is_rejected_before_any_download(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FlattenedClient(archive_fixture())
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=Path(directory) / "capability")
            self.assertNotIn("download", [name for name, _ in client.calls])

    def test_atomic_publish_never_clobbers_a_racing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capability"
            original = fetcher._rename_noreplace
            def race(source, destination):
                destination.mkdir()
                (destination / "owner.txt").write_text("other writer")
                return original(source, destination)
            with mock.patch.object(fetcher, "_rename_noreplace", side_effect=race):
                with self.assertRaises(fetcher.FetchV2EvidenceError):
                    fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=target)
            self.assertEqual((target / "owner.txt").read_text(), "other writer")

    def test_archive_reader_rejects_hardlinks_and_extra_object_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            key_map = json.loads((archive / "key-map.json").read_text())
            target = archive / next(iter(key_map.values()))
            os.link(target, archive / "objects" / "extra.bin")
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)

    def test_api_or_verification_failure_cleans_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            client = FakeClient(archive_fixture(), fail_at="list")
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=parent / "capability")
            self.assertFalse((parent / "capability").exists())
            self.assertEqual(list(parent.iterdir()), [])

    def test_disk_corruption_before_publish_is_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            original = fetcher._write_json
            def corrupt(path, value):
                original(path, value)
                if path.name == "fetch-manifest.json":
                    path.write_text("{invalid", encoding="utf-8")
            with mock.patch.object(fetcher, "_write_json", side_effect=corrupt), self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=parent / "capability")
            self.assertEqual(list(parent.iterdir()), [])

    def test_verifier_cli_exit_and_output_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            output = archive / "verification.json"
            self.assertFalse(output.exists())
            command = ["verify_v2_evidence.py", "--archive", str(archive), "--output", str(output), "--expected-project-id", "123", "--expected-backtest-id", "bt", "--expected-organization-id", "org"]
            with mock.patch("sys.argv", command):
                self.assertEqual(verifier_cli.main(), 0)
            self.assertEqual(json.loads(output.read_text())["overall_status"], "PASS")
            with mock.patch("sys.argv", command):
                self.assertEqual(verifier_cli.main(), 1)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); archive = archive_fixture(); archive["orders"] = [{"id": 1}]
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(FakeClient(archive), project_id=123, backtest_id="bt", organization_id="org", output_dir=parent / "capability")
            self.assertEqual(list(parent.iterdir()), [])

    def test_downloaded_fetch_manifest_is_verified_and_archive_paths_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            loaded = verifier_cli.load_archive(archive)
            self.assertEqual(loaded["fetch_manifest"]["algorithm_id"], "algo-7")
            self.assertEqual(verifier_cli.verify_archive(loaded)["overall_status"], "PASS")
            key_map = json.loads((archive / "key-map.json").read_text())
            target = archive / key_map[next(iter(key_map))]
            outside = Path(directory) / "same-content.bin"
            outside.write_bytes(target.read_bytes())
            target.unlink()
            os.symlink(outside, target)
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)

    def test_local_reader_rejects_duplicate_json_keys_and_accepts_string_transport_limit(self):
        self.assertGreater(verifier_cli.MAX_STRING_TRANSPORT_BYTES, verifier_cli.MAX_CHUNK_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            (archive / "key-map.json").write_text('{"x":"objects/0001.bin","x":"objects/0001.bin"}')
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)

    def test_object_lists_are_required_and_sanitization_is_precise(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            (archive / "object-lists.json").unlink()
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)
        sensitive = ["Authorization: abc123", "authorization=abc123", "api_token=abc123", "api-key: abc123", "api key=abc123", "key=abc123", "cookie: abc123", "Basic abc123", "Bearer abc123", "https://host.invalid/a?X-Goog-Signature=abc", "https://host.invalid/a?X-Amz-Credential=abc", "https://host.invalid/a?signature=abc"]
        self.assertTrue(all(fetcher._safe_value(value) == "[REDACTED]" for value in sensitive))
        self.assertEqual(fetcher._safe_value({"user": "alice", "url": "https://host.invalid/plain", "key": "abc"}), {"user": "alice", "url": "https://host.invalid/plain", "key": "[REDACTED]"})
        self.assertEqual(fetcher._safe_value({"key": "evidence/path", "size": 1, "folder": False}), {"key": "evidence/path", "size": 1, "folder": False})

    def test_deep_json_and_jsonl_are_archive_errors_and_cli_publishes_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            (archive / "key-map.json").write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)
            output = Path(directory) / "deep-verification.json"
            command = ["verify_v2_evidence.py", "--archive", str(archive), "--output", str(output), "--expected-project-id", "123", "--expected-backtest-id", "bt", "--expected-organization-id", "org"]
            with mock.patch("sys.argv", command):
                self.assertEqual(verifier_cli.main(), 1)
            self.assertEqual(json.loads(output.read_text())["overall_status"], "UNVERIFIED")
            self.assertFalse(list(Path(directory).glob(".tmp*")))
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            (archive / "orders.jsonl").write_text("[" * 10_000 + "]" * 10_000 + "\n", encoding="utf-8")
            with self.assertRaises(verifier_cli.ArchiveReadError):
                verifier_cli.load_archive(archive)

    def test_structured_credential_keys_are_redacted_without_breaking_object_records(self):
        values = {"access-token": "a", "refresh token": "b", "client_secret": "c", "accessToken": "d", "refreshToken": "e", "clientSecret": "f", "apiToken": "g", "authToken": "h", "privateKey": "i", "apiKey": "j", "accessKey": "k", "secretKey": "l", "vendor_token": "m", "vendor secret": "n", "db_password": "o", "cloud_credentials": "p", "authorization": "q", "cookie": "r", "user": "alice", "url": "https://host.invalid/plain"}
        cleaned = fetcher._safe_value(values)
        self.assertTrue(all(cleaned[key] == "[REDACTED]" for key in values if key not in {"user", "url"}))
        self.assertEqual(cleaned["user"], "alice")
        self.assertEqual(cleaned["url"], "https://host.invalid/plain")
        record = {"key": "evidence/object", "bytes": 1, "sha256": "hash", "access_token": "secret"}
        self.assertEqual(fetcher._safe_value(record)["key"], "evidence/object")
        self.assertEqual(fetcher._safe_value(record)["access_token"], "[REDACTED]")

    def test_json_structure_scanner_ignores_quoted_brackets_and_bounds_nodes(self):
        self.assertLess(verifier_cli._scan_json_structure(json.dumps({"note": '[{}]\\" still text'})), verifier_cli.MAX_JSON_STRUCTURAL_TOKENS)
        with self.assertRaises(verifier_cli.ArchiveReadError):
            verifier_cli._scan_json_structure("[" * (verifier_cli.MAX_JSON_DEPTH + 1) + "]" * (verifier_cli.MAX_JSON_DEPTH + 1))
        with self.assertRaises(verifier_cli.ArchiveReadError):
            verifier_cli._scan_json_structure("[" + "0," * verifier_cli.MAX_JSON_STRUCTURAL_TOKENS + "0]")


if __name__ == "__main__":
    unittest.main()
