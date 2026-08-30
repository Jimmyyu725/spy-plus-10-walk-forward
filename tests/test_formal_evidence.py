import gzip
import json
import unittest

from tests.project_path import PROJECT_DIR  # noqa: F401
from formal_evidence import (
    FormalEvidenceError,
    build_object_store_key,
    encode_evidence,
    formal_overall_status,
)


def valid_payload():
    return {
        "schema_version": 1,
        "run": {
            "project_id": 35858890,
            "algorithm_id": "abc123",
            "run_label": "base",
            "slippage_multiplier": 1.0,
            "evaluation_mode": "frozen-evaluation",
            "start_date": "2012-01-01",
            "trading_start_date": "2015-01-02",
            "end_date": "2026-08-28",
            "timezone": "America/New_York",
        },
        "daily": [
            {
                "date": "2015-01-02",
                "strategy_equity": "1000100.00",
                "spy_equity": "1000000.00",
            },
            {
                "date": "2015-01-05",
                "strategy_equity": "1000200.00",
                "spy_equity": "1000050.00",
            },
        ],
        "audit_samples": [],
        "gate_failures": [],
        "licenses": {"equity": "AVAILABLE", "option": "AVAILABLE"},
    }


class FormalEvidenceTests(unittest.TestCase):
    def test_object_store_key_is_unique_to_run_and_algorithm(self):
        self.assertEqual(
            build_object_store_key(35858890, "base", "abc123"),
            "35858890/frozen-evaluation-v1/base-abc123.json.gz",
        )
        self.assertNotEqual(
            build_object_store_key(35858890, "base", "abc123"),
            build_object_store_key(35858890, "double", "abc123"),
        )

    def test_evidence_round_trips_as_gzip_json(self):
        encoded = encode_evidence(valid_payload())
        decoded = json.loads(gzip.decompress(encoded).decode("utf-8"))
        self.assertEqual(decoded, valid_payload())

    def test_evidence_rejects_duplicate_or_nonpositive_daily_values(self):
        duplicate = valid_payload()
        duplicate["daily"][1]["date"] = duplicate["daily"][0]["date"]
        with self.assertRaisesRegex(FormalEvidenceError, "strictly increasing"):
            encode_evidence(duplicate)
        nonpositive = valid_payload()
        nonpositive["daily"][0]["strategy_equity"] = "0"
        with self.assertRaisesRegex(FormalEvidenceError, "positive"):
            encode_evidence(nonpositive)

    def test_status_precedence_is_mechanical(self):
        self.assertEqual(formal_overall_status("PASS", "PASS", "PASS"), "PASS")
        self.assertEqual(formal_overall_status("PASS", "PASS", "FAIL"), "FAIL")
        self.assertEqual(formal_overall_status("PASS", "FAIL", "PASS"), "FAIL")
        self.assertEqual(
            formal_overall_status("UNVERIFIED", "FAIL", "FAIL"),
            "UNVERIFIED",
        )


if __name__ == "__main__":
    unittest.main()
