import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.fetch_quantconnect_evidence import (
    QuantConnectClient,
    load_credentials,
)


class FetchQuantConnectEvidenceTests(unittest.TestCase):
    def test_credentials_are_loaded_without_becoming_request_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials"
            path.write_text(
                json.dumps({"user-id": 123, "api-token": "secret-token"}),
                encoding="utf-8",
            )
            user_id, token = load_credentials(path)
        self.assertEqual(user_id, "123")
        self.assertEqual(token, "secret-token")

    def test_pagination_reads_until_a_short_page(self):
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(
            side_effect=[
                {"success": True, "orders": [{"id": index} for index in range(99)]},
                {"success": True, "orders": [{"id": 99}]},
            ]
        )
        rows = client.read_all_backtest_rows(
            "backtests/orders/read", "orders", 35858890, "backtest-id"
        )
        self.assertEqual(len(rows), 100)
        self.assertEqual(client._post_json.call_count, 2)
        self.assertEqual(client._post_json.call_args_list[1].args[1]["start"], 99)

    def test_object_download_job_uses_returned_url(self):
        session = Mock()
        response = Mock(content=b"\x1f\x8bcompressed")
        response.raise_for_status = Mock()
        session.get.return_value = response
        client = QuantConnectClient("123", "secret", session=session)
        client._post_json = Mock(
            side_effect=[
                {"success": True, "jobId": "job", "url": None},
                {"success": True, "jobId": "job", "url": "https://download.invalid/file"},
            ]
        )
        result = client.download_object("org", "evidence-key")
        self.assertEqual(result, b"\x1f\x8bcompressed")
        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
