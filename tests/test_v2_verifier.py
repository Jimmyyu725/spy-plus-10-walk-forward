import copy
import json
import os
import subprocess
import sys
import unittest

from spy_plus_10.v2.evidence import (
    build_chunk_key,
    build_manifest,
    build_manifest_key,
    build_probe_keys,
    canonical_json_bytes,
    chunk_descriptor,
    encode_chunk,
    encode_string_transport,
    sha256_b64,
)
from spy_plus_10.v2.verifier import (
    decode_manifest,
    extract_runtime_statistics,
    recompute_attribution,
    verify_archive,
    verify_chunk,
    verify_probe,
)


PROJECT = "123"
COMMIT = "a" * 40
RUN_LABEL = "phase-a-capability"
ALGORITHM = "algo-7"


def daily_row(day):
    return {
        "date": day,
        "strategy_equity": "1000000.00",
        "spy_equity": "1000000.00",
        "sleeves": {
            name: {"daily_pnl": "0", "cumulative_pnl": "0", "fees": "0", "slippage": "0"}
            for name in ("core", "equity", "futures", "defensive_option")
        },
        "positions": [], "cash": "1000000.00", "margin_used": "0",
        "margin_remaining": "1000000.00", "option_max_loss": "0",
        "total_gross": "0", "alpha_gross": "0", "beta": "0",
        "risk_contributions": {"core": "0", "equity": "0", "futures": "0"},
        "drawdown": "0", "drawdown_state": "NORMAL",
        "walk_forward": {"training_start": None, "training_end": None,
                         "execution_year": 2015, "selected_parameters": None,
                         "selection_reason": "SYNTHETIC_CAPABILITY_FIXTURE"},
        "chronology": {"data_cutoff": None, "signal_time": None,
                       "order_time": None, "fill_time": None},
        "gates": {"data_license": "NOT_APPLICABLE", "data_missing": 0,
                  "order_rejected": 0, "partial_fill": 0, "cancelled": 0,
                  "exercise": 0, "assignment": 0, "future_data": 0,
                  "failures": []},
    }


def archive_fixture(*, fallback=False):
    probes = build_probe_keys(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
    string_key, bytes_key = probes["string"], probes["bytes"]
    chunk_key = build_chunk_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, 2015)
    manifest_key = build_manifest_key(PROJECT, COMMIT, RUN_LABEL, ALGORITHM)
    daily = [daily_row("2015-01-02"), daily_row("2015-01-05")]
    chunk = encode_chunk({"schema_version": 2, "kind": "annual-evidence", "run_variant": "full",
                          "year": 2015, "synthetic": True, "daily": daily})
    descriptor = chunk_descriptor(2015, chunk_key, chunk, daily)
    transport = "base64-gzip-string" if fallback else "bytes"
    manifest = build_manifest(PROJECT, COMMIT, RUN_LABEL, ALGORITHM, "full", transport, [descriptor])
    string_probe = b"S" * 1024
    bytes_probe = bytes(index % 251 for index in range(1024))
    objects = {string_key: string_probe, chunk_key: encode_string_transport(chunk) if fallback else chunk,
               manifest_key: canonical_json_bytes(manifest)}
    prefix = chunk_key.rsplit("/evidence/", 1)[0]
    root_listed = [{"key": manifest_key, "size": len(objects[manifest_key]), "folder": False},
                   {"key": prefix + "/capability", "size": 0, "folder": True},
                   {"key": prefix + "/evidence", "size": 0, "folder": True}]
    capability_listed = [{"key": string_key, "size": len(string_probe), "folder": False}]
    evidence_listed = [{"key": chunk_key, "size": len(objects[chunk_key]), "folder": False}]
    if not fallback:
        objects[bytes_key] = bytes_probe
        capability_listed.append({"key": bytes_key, "size": len(bytes_probe), "folder": False})
    statistics = {
        "V2_CAPABILITY_STATUS": "PASS_WITH_STRING_FALLBACK" if fallback else "PASS",
        "V2_TRANSPORT": transport,
        "V2_EVIDENCE_PREFIX": prefix,
        "V2_STRING_KEY": string_key, "V2_BYTES_KEY": bytes_key, "V2_MANIFEST_KEY": manifest_key,
        "V2_STRING_SHA256": sha256_b64(string_probe), "V2_BYTES_SHA256": sha256_b64(bytes_probe),
        "V2_STRING_STATUS": "PASS", "V2_BYTES_STATUS": "FAIL" if fallback else "PASS",
        "V2_CHUNK_STATUS": "PASS", "V2_MANIFEST_STATUS": "PASS",
    }
    fetch_manifest = {
        "project_id": int(PROJECT), "backtest_id": "bt", "organization_id": "org", "algorithm_id": ALGORITHM,
        "order_count": 0, "trade_count": 0, "downloaded_at_utc": "2026-08-31T00:00:00Z",
        "objects": [{"key": key, "bytes": len(value.encode("utf-8") if type(value) is str else value), "sha256": sha256_b64(value.encode("utf-8") if type(value) is str else value)} for key, value in objects.items()],
    }
    object_lists = {name: {"path": path, "listed_paths": [item["key"] for item in entries], "objects": entries, "object_storage_used": 4096} for name, path, entries in (("root", prefix, root_listed), ("capability", prefix + "/capability", capability_listed), ("evidence", prefix + "/evidence", evidence_listed))}
    return {"backtest": {"backtest": {"backtestId": "bt", "projectId": int(PROJECT), "organizationId": "org", "runtimeStatistics": statistics}}, "object_list": {"objects": [*root_listed, *capability_listed, *evidence_listed], "object_storage_used": 4096}, "object_lists": object_lists,
            "orders": [], "trades": [], "objects": objects, "fetch_manifest": fetch_manifest}


def real_dual_statistics_fixture():
    runtime = copy.deepcopy(archive_fixture()["backtest"]["backtest"]["runtimeStatistics"])
    del runtime["V2_STRING_SHA256"]
    del runtime["V2_BYTES_SHA256"]
    runtime.update({f"engine statistic {index}": "0" for index in range(8)})
    statistics = {f"summary statistic {index}": "0" for index in range(27)}
    return {"statistics": statistics, "runtimeStatistics": runtime}


class V2VerifierTests(unittest.TestCase):
    def test_bytes_archive_passes_with_json_serializable_result(self):
        result = verify_archive(archive_fixture())
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["object_store"]["string_round_trip"], "PASS")
        self.assertEqual(result["object_store"]["bytes_round_trip"], "PASS")
        self.assertEqual(result["attribution"]["reconciliation"], "PASS")
        json.dumps(result, allow_nan=False)

    def test_string_fallback_passes_without_bytes_object(self):
        result = verify_archive(archive_fixture(fallback=True))
        self.assertEqual(result["overall_status"], "PASS_WITH_STRING_FALLBACK")
        self.assertEqual(result["object_store"]["bytes_round_trip"], "FAIL")

    def test_string_fallback_allows_only_an_optional_residual_bytes_listing(self):
        archive = archive_fixture(fallback=True)
        runtime = archive["backtest"]["backtest"]["runtimeStatistics"]
        residual = {"key": runtime["V2_BYTES_KEY"], "size": 1024, "folder": False}
        archive["object_lists"]["capability"]["objects"].append(residual)
        archive["object_lists"]["capability"]["listed_paths"].append(residual["key"])
        archive["object_list"]["objects"].insert(-1, residual)
        self.assertEqual(verify_archive(archive)["overall_status"], "PASS_WITH_STRING_FALLBACK")
        extra = copy.deepcopy(archive)
        extra["object_lists"]["capability"]["objects"].append({"key": "unexpected", "size": 1, "folder": False})
        extra["object_lists"]["capability"]["listed_paths"].append("unexpected")
        extra["object_list"]["objects"].insert(-1, extra["object_lists"]["capability"]["objects"][-1])
        self.assertEqual(verify_archive(extra)["overall_status"], "UNVERIFIED")

    def test_string_transport_downloaded_as_bytes_and_metadata_size_must_match(self):
        archive = archive_fixture(fallback=True)
        chunk_key = next(key for key in archive["objects"] if key.endswith(".jsonGz"))
        archive["objects"][chunk_key] = archive["objects"][chunk_key].encode("utf-8")
        self.assertEqual(verify_archive(archive)["overall_status"], "PASS_WITH_STRING_FALLBACK")
        archive = archive_fixture()
        archive["object_list"]["objects"][0]["size"] = 1
        self.assertEqual(verify_archive(archive)["overall_status"], "UNVERIFIED")

    def test_all_invalid_archives_are_unverified_and_keep_diagnostics(self):
        cases = []
        missing = archive_fixture(); del missing["objects"][next(key for key in missing["objects"] if key.endswith("manifest.json"))]
        cases.append(missing)
        duplicate = archive_fixture(); duplicate["object_list"]["objects"].append(copy.deepcopy(duplicate["object_list"]["objects"][0]))
        cases.append(duplicate)
        hash_wrong = archive_fixture(); hash_wrong["backtest"]["backtest"]["runtimeStatistics"]["V2_STRING_SHA256"] = sha256_b64(b"wrong")
        cases.append(hash_wrong)
        bad_date = archive_fixture(); chunk_key = next(key for key in bad_date["objects"] if key.endswith(".jsonGz"));
        # Make malformed compressed content after a valid descriptor was recorded.
        bad_date["objects"][chunk_key] = b"not a gzip stream"
        cases.append(bad_date)
        nonempty_orders = archive_fixture(); nonempty_orders["orders"] = [{"id": 1}]
        cases.append(nonempty_orders)
        malformed_runtime = archive_fixture(); malformed_runtime["backtest"]["backtest"]["runtimeStatistics"]["V2_TRANSPORT"] = "bad"
        cases.append(malformed_runtime)
        mismatch = archive_fixture(); manifest_key = next(key for key in mismatch["objects"] if key.endswith("manifest.json"));
        manifest = json.loads(mismatch["objects"][manifest_key]); manifest["transport"] = "base64-gzip-string"; mismatch["objects"][manifest_key] = canonical_json_bytes(manifest)
        cases.append(mismatch)
        for archive in cases:
            with self.subTest(case=len(cases)):
                result = verify_archive(archive)
                self.assertEqual(result["overall_status"], "UNVERIFIED")
                self.assertTrue(result["errors"])

    def test_malformed_metadata_and_bombs_are_bounded(self):
        archive = archive_fixture()
        archive["object_list"]["objects"][0]["size"] = True
        archive["objects"][next(key for key in archive["objects"] if key.endswith(".jsonGz"))] = b"\x1f\x8b" + b"x" * (5 * 1024 * 1024)
        result = verify_archive(archive)
        self.assertEqual(result["overall_status"], "UNVERIFIED")
        self.assertLessEqual(len(result["errors"]), 64)

    def test_malformed_untrusted_types_never_raise(self):
        archive = archive_fixture()
        archive["objects"][next(iter(archive["objects"]))] = object()
        result = verify_archive(archive)
        self.assertEqual(result["overall_status"], "UNVERIFIED")

    def test_invalid_runtime_or_manifest_keeps_independent_diagnostics(self):
        archive = archive_fixture()
        archive["backtest"]["backtest"]["runtimeStatistics"]["V2_TRANSPORT"] = "bad"
        archive["object_list"]["objects"][0]["size"] = True
        archive["orders"] = [{"id": 1}]
        result = verify_archive(archive)
        self.assertEqual(result["overall_status"], "UNVERIFIED")
        self.assertIn("RUNTIME_STATUS_OR_TRANSPORT_INVALID", result["errors"])
        self.assertIn("OBJECT_METADATA_INVALID", result["errors"])
        self.assertIn("ORDERS_OR_TRADES_NONEMPTY", result["errors"])
        self.assertEqual(result["object_store"]["status"], "UNAVAILABLE")
        self.assertEqual(result["attribution"]["reconciliation"], "UNAVAILABLE")
        archive = archive_fixture()
        archive["objects"][next(key for key in archive["objects"] if key.endswith("manifest.json"))] = b"not-json"
        archive["trades"] = [{"id": 1}]
        result = verify_archive(archive)
        self.assertIn("MANIFEST_MALFORMED", result["errors"])
        self.assertIn("ORDERS_OR_TRADES_NONEMPTY", result["errors"])

    def test_public_helpers_fail_closed_without_leaking_raw_values(self):
        archive = archive_fixture()
        statistics = extract_runtime_statistics(archive["backtest"])
        self.assertEqual(statistics["transport"], "bytes")
        self.assertEqual(decode_manifest(next(value for key, value in archive["objects"].items() if key.endswith("manifest.json")))["kind"], "evidence-manifest")
        self.assertEqual(verify_probe("string", b"S" * 1024, 1024, sha256_b64(b"S" * 1024))["status"], "PASS")
        descriptor = decode_manifest(next(value for key, value in archive["objects"].items() if key.endswith("manifest.json")))["chunks"][0]
        chunk_key = descriptor["key"]
        self.assertEqual(verify_chunk(archive["objects"][chunk_key], "bytes", descriptor)["status"], "PASS")
        self.assertEqual(recompute_attribution([daily_row("2015-01-02"), daily_row("2015-01-05")])["status"], "PASS")

    def test_runtime_extraction_accepts_real_backtest_wrappers_and_statistics_spellings(self):
        statistics = archive_fixture()["backtest"]["backtest"]["runtimeStatistics"]
        for key in ("statistics", "runtimeStatistics", "runtime_statistics"):
            for response in ({key: statistics}, {"backtest": {key: statistics}}):
                with self.subTest(key=key, response=response):
                    self.assertEqual(extract_runtime_statistics(response)["status"], "PASS")

    def test_runtime_extraction_selects_complete_v2_statistics_mapping(self):
        real = real_dual_statistics_fixture()
        self.assertEqual(len(real["statistics"]), 27)
        self.assertFalse(any(key.startswith("V2_") for key in real["statistics"]))
        self.assertEqual(len(real["runtimeStatistics"]), 18)
        self.assertEqual(sum(key.startswith("V2_") for key in real["runtimeStatistics"]), 10)
        self.assertEqual(extract_runtime_statistics(real)["status"], "PASS")

        runtime_only = {"runtimeStatistics": copy.deepcopy(real["runtimeStatistics"])}
        self.assertEqual(extract_runtime_statistics(runtime_only)["status"], "PASS")
        statistics_only = {"statistics": copy.deepcopy(real["runtimeStatistics"])}
        self.assertEqual(extract_runtime_statistics(statistics_only)["status"], "PASS")

        both = copy.deepcopy(real)
        alternate = copy.deepcopy(real["runtimeStatistics"])
        original_prefix = alternate["V2_EVIDENCE_PREFIX"]
        alternate_prefix = "alternate/v2/evidence"
        for field in ("V2_EVIDENCE_PREFIX", "V2_STRING_KEY", "V2_BYTES_KEY", "V2_MANIFEST_KEY"):
            alternate[field] = alternate[field].replace(original_prefix, alternate_prefix, 1)
        both["statistics"] = alternate
        self.assertEqual(extract_runtime_statistics(both)["prefix"], real["runtimeStatistics"]["V2_EVIDENCE_PREFIX"])

        neither = {"runtimeStatistics": {"ordinary": "value"}, "statistics": {"summary": "value"}}
        self.assertEqual(extract_runtime_statistics(neither)["errors"], ["RUNTIME_MISSING_FIELDS"])

    def test_ten_field_runtime_statistics_recompute_canonical_probe_hashes(self):
        archive = archive_fixture()
        statistics = archive["backtest"]["backtest"]["runtimeStatistics"]
        del statistics["V2_STRING_SHA256"]
        del statistics["V2_BYTES_SHA256"]
        runtime = extract_runtime_statistics(archive["backtest"])
        self.assertEqual(runtime["status"], "PASS")
        self.assertEqual(runtime["string_sha256"], sha256_b64(b"S" * 1024))
        self.assertEqual(runtime["bytes_sha256"], sha256_b64(bytes(index % 251 for index in range(1024))))
        self.assertEqual(verify_archive(archive)["overall_status"], "PASS")

        fallback = archive_fixture(fallback=True)
        fallback_statistics = fallback["backtest"]["backtest"]["runtimeStatistics"]
        del fallback_statistics["V2_STRING_SHA256"]
        del fallback_statistics["V2_BYTES_SHA256"]
        self.assertEqual(verify_archive(fallback)["overall_status"], "PASS_WITH_STRING_FALLBACK")

    def test_runtime_optional_hashes_must_match_canonical_probes(self):
        correct = archive_fixture()["backtest"]
        self.assertEqual(extract_runtime_statistics(correct)["status"], "PASS")
        for updates, code in (
            ({"V2_STRING_SHA256": sha256_b64(b"wrong")}, "RUNTIME_SHA256_MISMATCH"),
            ({"V2_BYTES_SHA256": sha256_b64(b"wrong")}, "RUNTIME_SHA256_MISMATCH"),
            ({"V2_STRING_SHA256": sha256_b64(b"wrong"), "V2_BYTES_SHA256": sha256_b64(b"wrong")}, "RUNTIME_SHA256_MISMATCH"),
            ({"V2_STRING_SHA256": "not-base64"}, "RUNTIME_SHA256_INVALID"),
            ({"V2_BYTES_SHA256": sha256_b64(bytes(index % 251 for index in range(1024))) + "\n"}, "RUNTIME_SHA256_INVALID"),
        ):
            with self.subTest(updates=updates):
                response = copy.deepcopy(correct)
                response["backtest"]["runtimeStatistics"].update(updates)
                result = extract_runtime_statistics(response)
                self.assertEqual(result["status"], "UNVERIFIED")
                self.assertEqual(result["errors"], [code])

    def test_runtime_hash_diagnostic_order_is_stable_across_hash_seeds(self):
        program = """
from tests.test_v2_verifier import archive_fixture
from spy_plus_10.v2.evidence import sha256_b64
from spy_plus_10.v2.verifier import extract_runtime_statistics
archive = archive_fixture()
statistics = archive[\"backtest\"][\"backtest\"][\"runtimeStatistics\"]
statistics[\"V2_STRING_SHA256\"] = \"not-base64\"
statistics[\"V2_BYTES_SHA256\"] = sha256_b64(b\"wrong\")
print(extract_runtime_statistics(archive[\"backtest\"])[\"errors\"][0])
"""
        for seed in ("0", "1", "2", "3", "42", "123"):
            with self.subTest(seed=seed):
                environment = {**os.environ, "PYTHONHASHSEED": seed}
                result = subprocess.run([sys.executable, "-c", program], capture_output=True,
                                        check=False, cwd=".", env=environment, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "RUNTIME_SHA256_INVALID")

    def test_runtime_requires_each_non_hash_field(self):
        statistics = archive_fixture()["backtest"]["backtest"]["runtimeStatistics"]
        for field in tuple(statistics):
            if field.endswith("SHA256"):
                continue
            with self.subTest(field=field):
                response = {"runtimeStatistics": copy.deepcopy(statistics)}
                del response["runtimeStatistics"][field]
                self.assertEqual(extract_runtime_statistics(response)["errors"], ["RUNTIME_MISSING_FIELDS"])

    def test_recomputed_cumulative_pnl_must_equal_each_declared_sleeve_total(self):
        daily = [daily_row("2015-01-02"), daily_row("2015-01-05")]
        daily[1]["sleeves"]["equity"]["cumulative_pnl"] = "1"
        result = recompute_attribution(daily)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIn("ATTRIBUTION_CUMULATIVE_PNL_MISMATCH", result["errors"])

    def test_fetch_manifest_is_required_and_untrusted_public_inputs_never_raise(self):
        archive = archive_fixture(); del archive["fetch_manifest"]
        self.assertEqual(verify_archive(archive)["overall_status"], "UNVERIFIED")
        deeply_nested_json = (b"[" * 3000) + (b"]" * 3000)
        self.assertEqual(decode_manifest(deeply_nested_json)["status"], "UNVERIFIED")

        class ExplodingMapping(dict):
            def get(self, *args, **kwargs):
                raise RecursionError("synthetic")

        for result in (extract_runtime_statistics(ExplodingMapping()),
                       verify_chunk(b"x", "bytes", ExplodingMapping()),
                       recompute_attribution(ExplodingMapping())):
            self.assertEqual(result["status"], "UNVERIFIED")

    def test_fetch_manifest_and_official_object_metadata_are_bound_to_archive(self):
        archive = archive_fixture()
        archive["object_list"]["objects"][0].update({"name": "string-1kb.txt", "mime": "text/plain", "folder": False,
                                                          "modified": "2026-08-31T00:00:00Z", "lastModified": "2026-08-31T00:00:00Z"})
        self.assertEqual(verify_archive(archive)["overall_status"], "PASS")
        for mutation, code in (
            (lambda value: value.__setitem__("order_count", 1), "FETCH_MANIFEST_COUNTS_MISMATCH"),
            (lambda value: value["objects"][0].__setitem__("sha256", sha256_b64(b"wrong")), "FETCH_MANIFEST_OBJECT_HASH_OR_SIZE_MISMATCH"),
            (lambda value: value.__setitem__("algorithm_id", "wrong"), "FETCH_MANIFEST_IDENTITY_MISMATCH"),
        ):
            changed = archive_fixture(); mutation(changed["fetch_manifest"])
            result = verify_archive(changed)
            self.assertEqual(result["overall_status"], "UNVERIFIED")
            self.assertIn(code, result["errors"])

    def test_fetch_manifest_ids_bind_to_real_wrapped_backtest_metadata(self):
        archive = archive_fixture()
        self.assertEqual(verify_archive(archive)["overall_status"], "PASS")
        for field, code in (("backtest_id", "FETCH_BACKTEST_ID_MISMATCH"),
                            ("project_id", "FETCH_PROJECT_ID_MISMATCH"),
                            ("organization_id", "FETCH_ORGANIZATION_ID_MISMATCH")):
            changed = copy.deepcopy(archive)
            changed["fetch_manifest"][field] = "wrong" if field != "project_id" else 999
            result = verify_archive(changed)
            self.assertEqual(result["overall_status"], "UNVERIFIED")
            self.assertIn(code, result["errors"])

    def test_direct_object_lists_are_required_and_bound_to_the_aggregate(self):
        archive = archive_fixture()
        del archive["object_lists"]["capability"]["objects"][0]
        result = verify_archive(archive)
        self.assertEqual(result["overall_status"], "UNVERIFIED")
        self.assertIn("OBJECT_LISTS_LISTED_PATHS_INVALID", result["errors"])
        archive = archive_fixture()
        archive["object_lists"]["root"]["objects"][0]["folder"] = True
        result = verify_archive(archive)
        self.assertEqual(result["overall_status"], "UNVERIFIED")
        self.assertIn("OBJECT_LISTS_ROOT_PLACEMENT_INVALID", result["errors"])

    def test_external_identity_anchor_rejects_coordinated_internal_tampering(self):
        archive = archive_fixture()
        anchor = {"project_id": 123, "backtest_id": "bt", "organization_id": "org"}
        self.assertEqual(verify_archive(archive)["identity_assurance"], "INTERNAL_ONLY")
        self.assertEqual(verify_archive(archive, expected_identity=anchor)["identity_assurance"], "EXTERNALLY_ANCHORED")
        changed = copy.deepcopy(archive)
        changed["backtest"]["backtest"]["organizationId"] = "evil-org"
        changed["fetch_manifest"]["organization_id"] = "evil-org"
        result = verify_archive(changed, expected_identity=anchor)
        self.assertEqual(result["overall_status"], "UNVERIFIED")
        self.assertIn("EXPECTED_IDENTITY_MISMATCH", result["errors"])

    def test_manifest_rejects_duplicate_keys_and_noncanonical_bytes(self):
        archive = archive_fixture()
        raw = next(value for key, value in archive["objects"].items() if key.endswith("manifest.json"))
        duplicate = b'{"schema_version":2,' + raw[1:]
        self.assertEqual(decode_manifest(duplicate)["errors"], ["MANIFEST_DUPLICATE_KEY"])
        for candidate in (b" " + raw, json.dumps(json.loads(raw), indent=2).encode("utf-8")):
            self.assertEqual(decode_manifest(candidate)["errors"], ["MANIFEST_NONCANONICAL_BYTES"])


if __name__ == "__main__":
    unittest.main()
