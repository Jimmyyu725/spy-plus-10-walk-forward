import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.fetch_quantconnect_evidence import (
    MAX_BACKTEST_ROW_PAGES,
    MAX_API_JSON_BYTES,
    MAX_OBJECT_LIST_OBJECTS,
    MAX_OBJECT_LIST_PAGES,
    MAX_OBJECT_LIST_PAGE_OBJECTS,
    QuantConnectApiError,
    QuantConnectClient,
    _UrllibResponse,
    load_credentials,
)


class FetchQuantConnectEvidenceTests(unittest.TestCase):
    def test_urllib_json_response_reads_at_most_the_bounded_limit(self):
        response = Mock()
        response.read.return_value = b"x" * (MAX_API_JSON_BYTES + 1)
        with self.assertRaises(OSError):
            _UrllibResponse(response, max_bytes=MAX_API_JSON_BYTES)
        response.read.assert_called_once_with(MAX_API_JSON_BYTES + 1)

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

    def test_row_and_object_list_responses_have_bounded_page_and_total_sizes(self):
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(return_value={"success": True, "orders": [{"id": index} for index in range(100)]})
        with self.assertRaises(QuantConnectApiError):
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(return_value={"success": True, "page": 1, "totalPages": 1, "objects": [{"key": str(index)} for index in range(MAX_OBJECT_LIST_PAGE_OBJECTS + 1)]})
        with self.assertRaises(QuantConnectApiError):
            client.list_objects("org", "prefix")
        client = QuantConnectClient("123", "secret", session=Mock())
        pages = [{"success": True, "page": page, "totalPages": 11, "objects": [{"key": f"{page}-{index}"} for index in range(MAX_OBJECT_LIST_PAGE_OBJECTS)]} for page in range(1, 12)]
        client._post_json = Mock(side_effect=pages)
        with self.assertRaises(QuantConnectApiError):
            client.list_objects("org", "prefix")

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

    def test_object_download_rejects_transport_larger_than_caller_bound(self):
        session = Mock()
        response = Mock(content=b"oversized")
        response.raise_for_status = Mock()
        session.get.return_value = response
        client = QuantConnectClient("123", "secret", session=session)
        client._post_json = Mock(return_value={"success": True, "url": "https://download.invalid/file"})
        with self.assertRaises(QuantConnectApiError):
            client.download_object("org", "evidence-key", max_transport_bytes=4, max_uncompressed_bytes=4)

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

    def test_backtest_rows_allow_nine_hundred_ninety_nine_full_pages_then_a_short_page(self):
        sleep = Mock()
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=sleep)
        full_page = [{"id": "full"}] * 99
        calls_for_last_page = 0

        def rows_page(_endpoint, payload):
            nonlocal calls_for_last_page
            page = payload["start"] // 99 + 1
            if page < MAX_BACKTEST_ROW_PAGES:
                return {"success": True, "orders": full_page}
            if page == MAX_BACKTEST_ROW_PAGES:
                calls_for_last_page += 1
                if calls_for_last_page == 1:
                    return {"success": True, "status": "loading"}
                return {"success": True, "orders": [{"id": "last"}]}
            self.fail("the client requested a page after the allowed maximum")

        client._post_json = Mock(side_effect=rows_page)

        rows = client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

        self.assertEqual(len(rows), (MAX_BACKTEST_ROW_PAGES - 1) * 99 + 1)
        self.assertEqual(client._post_json.call_count, MAX_BACKTEST_ROW_PAGES + 1)
        sleep.assert_called_once_with(1)

    def test_backtest_rows_reject_a_thousandth_full_page_without_requesting_another(self):
        client = QuantConnectClient("123", "secret", session=Mock(), sleep=Mock())
        client._post_json = Mock(return_value={"success": True, "orders": [{"id": "full"}] * 99})

        with self.assertRaises(QuantConnectApiError):
            client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

        self.assertEqual(client._post_json.call_count, MAX_BACKTEST_ROW_PAGES)
        self.assertEqual(
            client._post_json.call_args.args[1]["start"],
            (MAX_BACKTEST_ROW_PAGES - 1) * 99,
        )

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

    def test_object_list_accepts_a_zero_page_terminal_response_with_objects(self):
        client = QuantConnectClient("123", "secret", session=Mock())
        client._post_json = Mock(
            return_value={
                "success": True,
                "page": 0,
                "totalPages": 0,
                "objects": [{"key": "pre-existing"}],
                "objectStorageUsed": 2048,
            }
        )

        result = client.list_objects("org", "path")

        self.assertEqual(result, {"objects": [{"key": "pre-existing"}], "object_storage_used": 2048})
        client._post_json.assert_called_once_with(
            "object/list", {"organizationId": "org", "path": "path", "page": 1}
        )

    def test_object_list_rejects_malicious_or_malformed_pagination(self):
        cases = [
            {"page": True, "totalPages": 1, "objects": []},
            {"page": 0, "totalPages": 1, "objects": []},
            {"page": 2, "totalPages": 2, "objects": []},
            {"page": 1, "totalPages": True, "objects": []},
            {"page": 1, "totalPages": "2", "objects": []},
            {"page": 1, "totalPages": 0, "objects": []},
            {"page": -1, "totalPages": 1, "objects": []},
            {"page": 1, "totalPages": -1, "objects": []},
        ]
        for response in cases:
            with self.subTest(response=response):
                client = QuantConnectClient("123", "secret", session=Mock())
                client._post_json = Mock(return_value={"success": True, **response})
                with self.assertRaises(QuantConnectApiError):
                    client.list_objects("org", "path")

    def test_object_list_rejects_page_counts_above_the_hard_limit(self):
        for total_pages in [MAX_OBJECT_LIST_PAGES + 1, 10**100]:
            with self.subTest(total_pages=total_pages):
                client = QuantConnectClient("123", "secret", session=Mock())
                client._post_json = Mock(
                    return_value={
                        "success": True,
                        "page": 1,
                        "totalPages": total_pages,
                        "objects": [],
                    }
                )

                with self.assertRaises(QuantConnectApiError):
                    client.list_objects("org", "path")

                client._post_json.assert_called_once()

    def test_object_list_allows_exactly_the_hard_page_limit(self):
        client = QuantConnectClient("123", "secret", session=Mock())

        def object_page(_endpoint, payload):
            page = payload["page"]
            return {
                "success": True,
                "page": page,
                "totalPages": MAX_OBJECT_LIST_PAGES,
                "objects": [{"key": "last"}] if page == MAX_OBJECT_LIST_PAGES else [],
            }

        client._post_json = Mock(side_effect=object_page)

        result = client.list_objects("org", "path")

        self.assertEqual(result, {"objects": [{"key": "last"}], "object_storage_used": None})
        self.assertEqual(client._post_json.call_count, MAX_OBJECT_LIST_PAGES)

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
