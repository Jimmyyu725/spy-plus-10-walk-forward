import importlib.util
import json
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
        return self.archive["object_list"]

    def download_object(self, organization_id, key):
        self._call("download", key)
        return self.archive["objects"][key]


class FetchV2EvidenceTests(unittest.TestCase):
    def test_success_publishes_only_after_full_download_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capability"
            fixture = archive_fixture()
            fixture["backtest"]["message"] = "Authorization: Bearer secret-value https://example.invalid/file?sig=secret-value"
            client = FakeClient(fixture)
            result = fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=target)
            self.assertTrue(target.is_dir())
            self.assertEqual(result["verification"]["overall_status"], "PASS")
            self.assertEqual([name for name, _ in client.calls[:5]], ["backtest", "orders", "trades", "list", "download"])
            key_map = json.loads((target / "key-map.json").read_text())
            downloaded_keys = [value for name, value in client.calls if name == "download"]
            self.assertEqual(key_map, {key: f"objects/{index:04d}.bin" for index, key in enumerate(downloaded_keys, 1)})
            archived_text = "\n".join(path.read_text(errors="ignore") for path in target.glob("*.json"))
            self.assertNotIn("secret-value", archived_text)

    def test_existing_target_causes_zero_api_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capability"; target.mkdir()
            client = FakeClient(archive_fixture())
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=target)
            self.assertEqual(client.calls, [])

    def test_api_or_verification_failure_cleans_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            client = FakeClient(archive_fixture(), fail_at="list")
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(client, project_id=123, backtest_id="bt", organization_id="org", output_dir=parent / "capability")
            self.assertFalse((parent / "capability").exists())
            self.assertEqual(list(parent.iterdir()), [])

    def test_verifier_cli_exit_and_output_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capability"
            fetcher.fetch_v2_evidence(FakeClient(archive_fixture()), project_id=123, backtest_id="bt", organization_id="org", output_dir=archive)
            output = archive / "verification.json"
            self.assertFalse(output.exists())
            with mock.patch("sys.argv", ["verify_v2_evidence.py", "--archive", str(archive), "--output", str(output)]):
                self.assertEqual(verifier_cli.main(), 0)
            self.assertEqual(json.loads(output.read_text())["overall_status"], "PASS")
            with mock.patch("sys.argv", ["verify_v2_evidence.py", "--archive", str(archive), "--output", str(output)]):
                self.assertEqual(verifier_cli.main(), 1)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); archive = archive_fixture(); archive["orders"] = [{"id": 1}]
            with self.assertRaises(fetcher.FetchV2EvidenceError):
                fetcher.fetch_v2_evidence(FakeClient(archive), project_id=123, backtest_id="bt", organization_id="org", output_dir=parent / "capability")
            self.assertEqual(list(parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
