import base64
import copy
import gzip
import hashlib
import json
import re
import unittest
import zlib
from decimal import Decimal

from spy_plus_10.v2.evidence import (
    MAX_CHUNK_BYTES,
    RUN_VARIANTS,
    SCHEMA_VERSION,
    SLEEVES,
    EvidenceError,
    build_chunk_key,
    build_manifest,
    build_manifest_key,
    build_probe_keys,
    canonical_json_bytes,
    chunk_descriptor,
    decode_transport,
    encode_chunk,
    encode_string_transport,
    sha256_b64,
    validate_chunk,
    validate_daily_row,
)


PROJECT = "spy-plus-10"
COMMIT = "a" * 40
RUN_LABEL = "capability-2015"
ALGORITHM = "spy-plus-10-v2"
LEAN_LOCAL_OBJECT_STORE_PATH_RE = re.compile(r"^\.?[a-zA-Z0-9\\/_#\-\$= ]+\.?[a-zA-Z0-9]*$")


def valid_row(day="2015-01-02"):
    return {
        "date": day,
        "strategy_equity": "1000000.00",
        "spy_equity": "1000000.00",
        "sleeves": {
            sleeve: {"daily_pnl": 0, "cumulative_pnl": 0, "fees": 0, "slippage": 0}
            for sleeve in SLEEVES
        },
        "positions": [],
        "cash": "1000000.00",
        "margin_used": 0,
        "margin_remaining": 1000000,
        "option_max_loss": 0,
        "total_gross": 0,
        "alpha_gross": 0,
        "beta": 0,
        "risk_contributions": {"core": 0, "equity": 0, "futures": 0},
        "drawdown": 0,
        "drawdown_state": "NORMAL",
        "walk_forward": {
            "training_start": None,
            "training_end": None,
            "execution_year": 2015,
            "selected_parameters": None,
            "selection_reason": "SYNTHETIC_CAPABILITY_FIXTURE",
        },
        "chronology": {
            "data_cutoff": None,
            "signal_time": None,
            "order_time": None,
            "fill_time": None,
        },
        "gates": {
            "data_license": "NOT_APPLICABLE",
            "data_missing": 0,
            "order_rejected": 0,
            "partial_fill": 0,
            "cancelled": 0,
            "exercise": 0,
            "assignment": 0,
            "future_data": 0,
            "failures": [],
        },
    }


def valid_payload():
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "annual-evidence",
        "run_variant": "full",
        "year": 2015,
        "synthetic": True,
        "daily": [valid_row(), valid_row("2015-01-05")],
    }


class V2EvidenceTests(unittest.TestCase):
    def test_constants_are_frozen_protocol_values(self):
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(MAX_CHUNK_BYTES, 5 * 1024 * 1024)
        self.assertEqual(SLEEVES, ("core", "equity", "futures", "defensive_option"))
        self.assertEqual(
            RUN_VARIANTS,
            (
                "full", "core_only", "equity_only", "futures_only", "defensive_option_only",
                "without_core", "without_equity", "without_futures", "without_defensive_option",
            ),
        )

    def test_key_layout_contains_all_immutable_identity(self):
        prefix = f"{PROJECT}/v2/{COMMIT}/{RUN_LABEL}/{ALGORITHM}"
        probes = build_probe_keys(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
        self.assertEqual(probes, {
            "string": f"{prefix}/capability/string-1kb.txt",
            "bytes": f"{prefix}/capability/bytes-1kb.bin",
        })
        chunk = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)
        manifest = build_manifest_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
        for key in (*probes.values(), chunk, manifest):
            with self.subTest(key=key):
                self.assertIsNotNone(LEAN_LOCAL_OBJECT_STORE_PATH_RE.fullmatch(key))
        self.assertEqual(chunk, f"{prefix}/evidence/2015.jsonGz")
        self.assertEqual(manifest, f"{prefix}/manifest.json")

    def test_invalid_identity_commit_and_year_are_rejected(self):
        for value in ("", ".", "..", "bad/path", "space here", True, 1):
            with self.subTest(value=value):
                with self.assertRaises(EvidenceError):
                    build_manifest_key(value, COMMIT, RUN_LABEL, ALGORITHM)
        for commit in ("A" * 40, "a" * 39, "g" * 40, True):
            with self.subTest(commit=commit):
                with self.assertRaises(EvidenceError):
                    build_manifest_key(PROJECT, commit, RUN_LABEL, ALGORITHM)
        for year in (2014, 2101, True, "2015"):
            with self.subTest(year=year):
                with self.assertRaises(EvidenceError):
                    build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, year)

    def test_canonical_json_and_deterministic_gzip_round_trip(self):
        payload = valid_payload()
        self.assertEqual(canonical_json_bytes({"z": "中文", "a": 1}), b'{"a":1,"z":"\xe4\xb8\xad\xe6\x96\x87"}')
        encoded_a = encode_chunk(payload)
        encoded_b = encode_chunk(copy.deepcopy(payload))
        self.assertEqual(encoded_a, encoded_b)
        self.assertEqual(json.loads(gzip.decompress(encoded_a)), payload)
        with self.assertRaises(EvidenceError):
            canonical_json_bytes({"not_json": {1, 2}})
        with self.assertRaises(EvidenceError):
            canonical_json_bytes({"not_json": float("nan")})

    def test_transport_is_bytes_passthrough_or_strict_base64_gzip_string(self):
        encoded = encode_chunk(valid_payload())
        self.assertIs(decode_transport(encoded), encoded)
        transport = encode_string_transport(encoded)
        self.assertTrue(transport.startswith("base64-gzip:"))
        self.assertEqual(decode_transport(transport), encoded)
        for value in ("base64:YWJj", "base64-gzip:not base64", "base64-gzip:YWJj=", 1, bytearray(encoded)):
            with self.subTest(value=value):
                with self.assertRaises(EvidenceError):
                    decode_transport(value)

    def test_transport_base64_golden_vectors_are_canonical_on_all_supported_pythons(self):
        self.assertEqual(decode_transport("base64-gzip:YWJj"), b"abc")
        for noncanonical in ("base64-gzip:YWJj=", "base64-gzip:YWJj=="):
            with self.subTest(noncanonical=noncanonical):
                with self.assertRaises(EvidenceError):
                    decode_transport(noncanonical)

    def test_valid_daily_row_chunk_descriptor_and_manifest(self):
        payload = valid_payload()
        self.assertEqual(validate_daily_row(payload["daily"][0], 2015).isoformat(), "2015-01-02")
        validate_chunk(payload)
        encoded = encode_chunk(payload)
        key = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)
        descriptor = chunk_descriptor(2015, key, encoded, payload["daily"])
        self.assertEqual(descriptor["run_variant"], "full")
        manifest = build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [descriptor])
        self.assertEqual(
            manifest,
            {
                "schema_version": 2,
                "kind": "evidence-manifest",
                "project_id": PROJECT,
                "version": "v2",
                "frozen_commit": COMMIT,
                "run_label": RUN_LABEL,
                "algorithm_id": ALGORITHM,
                "run_variant": "full",
                "transport": "bytes",
                "chunks": [descriptor],
            },
        )

    def test_manifest_sorts_chunks_and_rejects_duplicate_year_or_key(self):
        payload = valid_payload()
        encoded = encode_chunk(payload)
        first = chunk_descriptor(2015, build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015), encoded, payload["daily"])
        next_payload = copy.deepcopy(payload)
        next_payload["year"] = 2016
        next_payload["daily"] = [valid_row("2016-01-04")]
        next_payload["daily"][0]["walk_forward"]["execution_year"] = 2016
        second = chunk_descriptor(2016, build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2016), encode_chunk(next_payload), next_payload["daily"])
        manifest = build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [second, first])
        self.assertEqual([item["year"] for item in manifest["chunks"]], [2015, 2016])
        with self.assertRaises(EvidenceError):
            build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [first, first])
        duplicate_key = dict(second, year=2017, key=first["key"])
        with self.assertRaises(EvidenceError):
            build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [first, duplicate_key])

    def test_manifest_descriptor_limits_and_strict_shape(self):
        payload = valid_payload()
        encoded = encode_chunk(payload)
        key = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)
        descriptor = chunk_descriptor(2015, key, encoded, payload["daily"])
        exact_limit = dict(descriptor, encoded_bytes=MAX_CHUNK_BYTES)
        build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [exact_limit])
        invalid_descriptors = (
            dict(descriptor, encoded_bytes=MAX_CHUNK_BYTES + 1),
            dict(descriptor, encoded_bytes=True),
            dict(descriptor, sha256="not-base64"),
            dict(descriptor, sha256=base64.b64encode(b"short").decode("ascii")),
            dict(descriptor, key="wrong"),
            dict(descriptor, rows=0),
            dict(descriptor, first_date="2015-1-2"),
            dict(descriptor, extra=True),
        )
        for bad in invalid_descriptors:
            with self.subTest(bad=bad):
                with self.assertRaises(EvidenceError):
                    build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "bytes", [bad])
        with self.assertRaises(EvidenceError):
            chunk_descriptor(2015, key, encoded, [])
        with self.assertRaises(EvidenceError):
            build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", "invalid", [descriptor])
        with self.assertRaises(EvidenceError):
            build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", [], [descriptor])
        with self.assertRaises(EvidenceError):
            build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "core_only", "bytes", [descriptor])

    def test_chunk_rejects_strict_dates_and_cross_year_rows(self):
        bad_payloads = []
        out_of_order = valid_payload()
        out_of_order["daily"] = [valid_row("2015-01-05"), valid_row("2015-01-02")]
        bad_payloads.append(out_of_order)
        duplicate_date = valid_payload()
        duplicate_date["daily"] = [valid_row(), valid_row()]
        bad_payloads.append(duplicate_date)
        cross_year = valid_payload()
        cross_year["daily"] = [valid_row("2016-01-04")]
        bad_payloads.append(cross_year)
        malformed_date = valid_payload()
        malformed_date["daily"] = [valid_row("2015-1-2")]
        bad_payloads.append(malformed_date)
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(EvidenceError):
                    validate_chunk(payload)

    def test_daily_row_rejects_required_field_and_numeric_violations(self):
        invalid_rows = []
        missing_sleeve = valid_row()
        del missing_sleeve["sleeves"]["core"]
        invalid_rows.append(missing_sleeve)
        missing_nested = valid_row()
        del missing_nested["sleeves"]["core"]["fees"]
        invalid_rows.append(missing_nested)
        for key, value in (("strategy_equity", "NaN"), ("margin_used", -1), ("cash", float("inf")), ("margin_remaining", True)):
            row = valid_row()
            row[key] = value
            invalid_rows.append(row)
        bad_chronology = valid_row()
        bad_chronology["chronology"]["signal_time"] = "2015-01-02T10:00:00"
        bad_chronology["chronology"]["order_time"] = "2015-01-02T09:00:00"
        invalid_rows.append(bad_chronology)
        bad_gate = valid_row()
        bad_gate["gates"]["order_rejected"] = True
        invalid_rows.append(bad_gate)
        bad_execution_year = valid_row()
        bad_execution_year["walk_forward"]["execution_year"] = True
        invalid_rows.append(bad_execution_year)
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(EvidenceError):
                    validate_daily_row(row, 2015)

    def test_daily_row_accepts_sleeve_mapping_independent_of_insertion_order(self):
        row = valid_row()
        row["sleeves"] = {sleeve: row["sleeves"][sleeve] for sleeve in reversed(SLEEVES)}

        self.assertEqual(validate_daily_row(row, 2015).isoformat(), "2015-01-02")

    def test_chunk_requires_exact_protocol_types_and_nonempty_daily(self):
        for field, value in (("schema_version", True), ("synthetic", 1), ("year", True), ("daily", []), ("run_variant", "unknown")):
            payload = valid_payload()
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaises(EvidenceError):
                    validate_chunk(payload)

    def test_chunk_encoding_and_transport_enforce_real_five_mib_limit(self):
        payload = valid_payload()
        blocks = (hashlib.sha256(index.to_bytes(8, "big")).digest() for index in range(225_000))
        payload["padding"] = base64.b64encode(b"".join(blocks)).decode("ascii")
        actual_gzip = gzip.compress(canonical_json_bytes(payload), compresslevel=9, mtime=0)
        self.assertGreater(len(actual_gzip), MAX_CHUNK_BYTES)

        with self.assertRaises(EvidenceError):
            encode_chunk(payload)
        for value in (b"", b"x" * (MAX_CHUNK_BYTES + 1)):
            with self.subTest(value_length=len(value)):
                with self.assertRaises(EvidenceError):
                    encode_string_transport(value)
                with self.assertRaises(EvidenceError):
                    decode_transport(value)
        max_base64_chars = 4 * ((MAX_CHUNK_BYTES + 2) // 3)
        with self.assertRaises(EvidenceError):
            decode_transport("base64-gzip:" + "A" * (max_base64_chars + 1))

    def test_descriptor_is_bound_to_the_exact_canonical_chunk(self):
        payload = valid_payload()
        encoded = encode_chunk(payload)
        key = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)
        chunk_descriptor(2015, key, encoded, payload["daily"])
        alternate_daily = copy.deepcopy(payload["daily"])
        alternate_daily[0]["cash"] = "999999.00"
        noncanonical = gzip.compress(canonical_json_bytes(payload), compresslevel=9, mtime=1)
        for year, candidate, daily in (
            (2015, b"not gzip", payload["daily"]),
            (2015, encoded, alternate_daily),
            (2016, encoded, payload["daily"]),
            (2015, noncanonical, payload["daily"]),
        ):
            with self.subTest(year=year, candidate=candidate[:10]):
                with self.assertRaises(EvidenceError):
                    chunk_descriptor(year, key, candidate, daily)

    def test_descriptor_wraps_real_corrupt_deflate_as_evidence_error(self):
        payload = valid_payload()
        encoded = encode_chunk(payload)
        corrupted = bytearray(encoded)
        corrupted[10] ^= 0xFF
        key = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)

        with self.assertRaises(zlib.error):
            gzip.decompress(corrupted)
        with self.assertRaises(EvidenceError):
            chunk_descriptor(2015, key, bytes(corrupted), payload["daily"])

    def test_validate_chunk_rejects_non_json_native_values_before_encode(self):
        payload = valid_payload()
        payload["daily"][0]["walk_forward"]["selected_parameters"] = {"threshold": Decimal("1.0")}

        with self.assertRaises(EvidenceError):
            validate_chunk(payload)
        with self.assertRaises(EvidenceError):
            encode_chunk(payload)

    def test_sha256_b64_is_standard_digest_encoding(self):
        self.assertEqual(sha256_b64(b"abc"), "ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0=")
        with self.assertRaises(EvidenceError):
            sha256_b64("abc")


if __name__ == "__main__":
    unittest.main()
