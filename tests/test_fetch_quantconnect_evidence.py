import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.fetch_quantconnect_evidence import (
    QuantConnectApiError,
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

    def test_loading_backtest_rows_are_polled_before_pagination(self):
        sleep = Mock()
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=sleep)
        client._post_json = Mock(
            side_effect=[
                {"success": True, "status": "loading", "progress": 0.5},
                {"success": True, "status": "completed", "orders": [{"id": 1}]},
            ]
        )

        self.assertEqual(
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt"),
            [{"id": 1}],
        )
        sleep.assert_called_once_with(1)

    def test_terminal_response_without_rows_is_rejected(self):
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=Mock())
        client._post_json = Mock(return_value={"success": True, "status": "completed"})

        with self.assertRaises(QuantConnectApiError):
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

    def test_rows_response_with_non_list_field_is_rejected(self):
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=Mock())
        client._post_json = Mock(return_value={"success": True, "orders": {"id": 1}})

        with self.assertRaises(QuantConnectApiError):
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

    def test_loading_rows_time_out_after_thirty_requests_and_twenty_nine_sleeps(self):
        sleep = Mock()
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=sleep)
        client._post_json = Mock(
            return_value={"success": True, "status": "loading", "progress": 0.5}
        )

        with self.assertRaises(QuantConnectApiError):
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

        self.assertEqual(client._post_json.call_count, 30)
        self.assertEqual(sleep.call_count, 29)

    def test_loading_second_page_retries_the_same_page_before_continuing(self):
        sleep = Mock()
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=sleep)
        client._post_json = Mock(
            side_effect=[
                {"success": True, "orders": [{"id": index} for index in range(99)]},
                {"success": True, "status": "loading"},
                {"success": True, "orders": [{"id": 99}]},
            ]
        )

        rows = client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

        self.assertEqual(len(rows), 100)
        self.assertEqual(sleep.call_count, 1)
        payloads = [call.args[1] for call in client._post_json.call_args_list]
        self.assertEqual([payload["start"] for payload in payloads], [0, 99, 99])

    def test_object_list_reads_all_pages(self):
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(
            side_effect=[
                {
                    "success": True,
                    "page": 1,
                    "totalPages": 2,
                    "objects": [{"key": "a"}],
                },
                {
                    "success": True,
                    "page": 2,
                    "totalPages": 2,
                    "objects": [{"key": "b"}],
                    "objectStorageUsed": 2048,
                },
            ]
        )

        result = client.list_objects("org", "123/v2")

        self.assertEqual([item["key"] for item in result["objects"]], ["a", "b"])
        self.assertEqual(result["object_storage_used"], 2048)
        self.assertEqual(
            [call.args for call in client._post_json.call_args_list],
            [
                ("object/list", {"organizationId": "org", "path": "123/v2", "page": 1}),
                ("object/list", {"organizationId": "org", "path": "123/v2", "page": 2}),
            ],
        )

    def test_object_list_rejects_malicious_or_malformed_pagination(self):
        cases = [
            {"page": True, "totalPages": 1, "objects": []},
            {"page": 2, "totalPages": 2, "objects": []},
            {"page": 1, "totalPages": True, "objects": []},
            {"page": 1, "totalPages": "2", "objects": []},
            {"page": 1, "totalPages": 0, "objects": []},
        ]
        for response in cases:
            with self.subTest(response=response):
                client = QuantConnectClient("123", "secret", session=Mock())
                client._post_json = Mock(return_value={"success": True, **response})
                with self.assertRaises(QuantConnectApiError):
                    client.list_objects("org", "path")

    def test_object_list_rejects_total_pages_that_change_mid_stream(self):
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(
            side_effect=[
                {"success": True, "page": 1, "totalPages": 2, "objects": [{"key": "a"}]},
                {"success": True, "page": 2, "totalPages": 3, "objects": [{"key": "b"}]},
            ]
        )

        with self.assertRaises(QuantConnectApiError):
            client.list_objects("org", "path")

    def test_object_list_rejects_invalid_objects_or_storage_used_types(self):
        cases = [
            {"page": 1, "totalPages": 1, "objects": {"key": "a"}},
            {"page": 1, "totalPages": 1, "objects": ["not-a-mapping"]},
            {"page": 1, "totalPages": 1, "objects": [], "objectStorageUsed": True},
        ]
        for response in cases:
            with self.subTest(response=response):
                client = QuantConnectClient("123", "secret", session=Mock())
                client._post_json = Mock(return_value={"success": True, **response})
                with self.assertRaises(QuantConnectApiError):
                    client.list_objects("org", "path")

    def test_download_object_uses_injected_sleep_while_job_is_pending(self):
        session = Mock()
        response = Mock(content=b"payload")
        response.raise_for_status = Mock()
        session.get.return_value = response
        sleep = Mock()
        client = QuantConnectClient("123", "secret", session=session, sleep=sleep)
        client._post_json = Mock(
            side_effect=[
                {"success": True, "jobId": "job", "url": None},
                {"success": True, "jobId": "job", "url": None},
                {"success": True, "jobId": "job", "url": "https://download.invalid/file"},
            ]
        )

        self.assertEqual(client.download_object("org", "evidence-key"), b"payload")
        sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
