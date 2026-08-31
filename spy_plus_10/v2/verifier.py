"""Fail-closed, local-only verifier for v2 capability evidence archives."""

from __future__ import annotations

import gzip
import io
import base64
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from .evidence import (
    MAX_CHUNK_BYTES,
    SLEEVES,
    EvidenceError,
    build_chunk_key,
    build_manifest,
    build_manifest_key,
    build_probe_keys,
    canonical_json_bytes,
    decode_transport,
    encode_chunk,
    sha256_b64,
    validate_chunk,
)


MAX_ARCHIVE_OBJECTS = 1024
MAX_ERRORS = 64
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_GZIP_RAW_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ARCHIVE_OBJECT_BYTES = 64 * 1024 * 1024
MAX_DECIMAL_CHARS = 256
MAX_DECIMAL_DIGITS = 128
MAX_DECIMAL_EXPONENT = 128
_RUNTIME_FIELDS = frozenset({
    "V2_CAPABILITY_STATUS", "V2_TRANSPORT", "V2_EVIDENCE_PREFIX",
    "V2_STRING_KEY", "V2_BYTES_KEY", "V2_MANIFEST_KEY",
    "V2_STRING_SHA256", "V2_BYTES_SHA256", "V2_STRING_STATUS",
    "V2_BYTES_STATUS", "V2_CHUNK_STATUS", "V2_MANIFEST_STATUS",
})
_STATUSES = frozenset({"PASS", "PASS_WITH_STRING_FALLBACK", "UNVERIFIED"})


def _result(status: str, *errors: str, **values) -> dict:
    return {"status": status, "errors": list(errors)[:MAX_ERRORS], **values}


def _storage_bytes(value: object) -> bytes:
    if type(value) is bytes:
        return value
    if type(value) is str:
        return value.encode("utf-8")
    raise ValueError("object content type")


def _decimal(value: object) -> Decimal:
    if type(value) is bool or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("not numeric")
    text = str(value)
    if len(text) > MAX_DECIMAL_CHARS:
        raise ValueError("numeric text too long")
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("not numeric") from error
    if not result.is_finite():
        raise ValueError("not finite")
    digits = result.as_tuple().digits
    if len(digits) > MAX_DECIMAL_DIGITS or abs(result.as_tuple().exponent) > MAX_DECIMAL_EXPONENT:
        raise ValueError("numeric value outside safe bounds")
    return result


def _read_statistics(backtest: object) -> object:
    candidate = _unwrap_backtest(backtest)
    if not isinstance(candidate, Mapping):
        raise ValueError("backtest wrapper")
    for key in ("statistics", "runtimeStatistics", "runtime_statistics"):
        value = candidate.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _unwrap_backtest(backtest: object) -> Mapping:
    if not isinstance(backtest, Mapping):
        raise ValueError("backtest")
    candidate = backtest.get("backtest", backtest)
    if not isinstance(candidate, Mapping):
        raise ValueError("backtest wrapper")
    return candidate


def _backtest_identity(backtest: object) -> dict | None:
    try:
        candidate = _unwrap_backtest(backtest)
        backtest_id, project_id, organization_id = candidate.get("backtestId"), candidate.get("projectId"), candidate.get("organizationId")
        if type(backtest_id) is not str or not backtest_id or type(project_id) is not int or isinstance(project_id, bool) or project_id < 0 or type(organization_id) is not str or not organization_id:
            return None
        return {"backtest_id": backtest_id, "project_id": project_id, "organization_id": organization_id}
    except Exception:
        return None


def extract_runtime_statistics(backtest) -> dict:
    """Return checked v2 runtime fields without propagating raw backtest data."""
    try:
        statistics = _read_statistics(backtest)
        if not isinstance(statistics, Mapping) or not _RUNTIME_FIELDS.issubset(statistics):
            return _result("UNVERIFIED", "RUNTIME_MISSING_FIELDS")
        values = {field: statistics[field] for field in _RUNTIME_FIELDS}
        if any(type(value) is not str or not value for value in values.values()):
            return _result("UNVERIFIED", "RUNTIME_FIELD_INVALID")
        capability = values["V2_CAPABILITY_STATUS"]
        transport = values["V2_TRANSPORT"]
        if capability not in _STATUSES or transport not in {"bytes", "base64-gzip-string"}:
            return _result("UNVERIFIED", "RUNTIME_STATUS_OR_TRANSPORT_INVALID")
        for field in ("V2_STRING_STATUS", "V2_BYTES_STATUS", "V2_CHUNK_STATUS", "V2_MANIFEST_STATUS"):
            if values[field] not in {"PASS", "FAIL", "UNVERIFIED"}:
                return _result("UNVERIFIED", "RUNTIME_COMPONENT_STATUS_INVALID")
        for field in ("V2_STRING_SHA256", "V2_BYTES_SHA256"):
            try:
                digest = base64.b64decode(values[field], validate=True)
            except (ValueError, TypeError):
                return _result("UNVERIFIED", "RUNTIME_SHA256_INVALID")
            if len(digest) != 32 or base64.b64encode(digest).decode("ascii") != values[field]:
                return _result("UNVERIFIED", "RUNTIME_SHA256_INVALID")
        if capability == "PASS" and (transport != "bytes" or any(values[field] != "PASS" for field in ("V2_STRING_STATUS", "V2_BYTES_STATUS", "V2_CHUNK_STATUS", "V2_MANIFEST_STATUS"))):
            return _result("UNVERIFIED", "RUNTIME_PASS_INCONSISTENT")
        if capability == "PASS_WITH_STRING_FALLBACK" and (transport != "base64-gzip-string" or values["V2_STRING_STATUS"] != "PASS" or values["V2_BYTES_STATUS"] != "FAIL" or values["V2_CHUNK_STATUS"] != "PASS" or values["V2_MANIFEST_STATUS"] != "PASS"):
            return _result("UNVERIFIED", "RUNTIME_FALLBACK_INCONSISTENT")
        if capability == "UNVERIFIED":
            return _result("UNVERIFIED", "RUNTIME_CAPABILITY_UNVERIFIED")
        string_key, bytes_key, manifest_key, prefix = (values[name] for name in ("V2_STRING_KEY", "V2_BYTES_KEY", "V2_MANIFEST_KEY", "V2_EVIDENCE_PREFIX"))
        if any("/../" in key or key.startswith("/") or key.endswith("/") for key in (string_key, bytes_key, manifest_key, prefix)):
            return _result("UNVERIFIED", "RUNTIME_KEY_INVALID")
        if not string_key.startswith(prefix + "/") or not bytes_key.startswith(prefix + "/") or manifest_key != prefix + "/manifest.json":
            return _result("UNVERIFIED", "RUNTIME_PREFIX_MISMATCH")
        return _result("PASS", capability_status=capability, transport=transport, prefix=prefix,
                       string_key=string_key, bytes_key=bytes_key, manifest_key=manifest_key,
                       string_sha256=values["V2_STRING_SHA256"], bytes_sha256=values["V2_BYTES_SHA256"])
    except Exception:
        return _result("UNVERIFIED", "RUNTIME_MALFORMED")


def decode_manifest(raw) -> dict:
    """Decode and validate a bounded manifest; returned values are JSON-native."""
    try:
        if type(raw) is str:
            raw = raw.encode("utf-8")
        if type(raw) is not bytes or not raw or len(raw) > MAX_MANIFEST_BYTES:
            return _result("UNVERIFIED", "MANIFEST_SIZE_OR_TYPE_INVALID")
        def rejecting_pairs(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise KeyError("duplicate manifest key")
                result[key] = item
            return result
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=rejecting_pairs)
        except KeyError:
            return _result("UNVERIFIED", "MANIFEST_DUPLICATE_KEY")
        if type(value) is not dict:
            return _result("UNVERIFIED", "MANIFEST_NOT_OBJECT")
        manifest = build_manifest(value.get("project_id"), value.get("frozen_commit"), value.get("run_label"),
                                  value.get("algorithm_id"), value.get("run_variant"), value.get("transport"),
                                  value.get("chunks"))
        if value != manifest or value.get("schema_version") != 2 or value.get("kind") != "evidence-manifest" or value.get("version") != "v2":
            return _result("UNVERIFIED", "MANIFEST_PROTOCOL_INVALID")
        if len(manifest["chunks"]) > MAX_ARCHIVE_OBJECTS:
            return _result("UNVERIFIED", "MANIFEST_TOO_MANY_CHUNKS")
        if raw != canonical_json_bytes(manifest):
            return _result("UNVERIFIED", "MANIFEST_NONCANONICAL_BYTES")
        return _result("PASS", **manifest)
    except Exception:
        return _result("UNVERIFIED", "MANIFEST_MALFORMED")


def verify_probe(name, raw, expected_size, expected_sha256) -> dict:
    try:
        if type(name) is not str or type(raw) is not bytes or type(expected_size) is not int or expected_size != 1024 or type(expected_sha256) is not str:
            return _result("UNVERIFIED", "PROBE_ARGUMENT_INVALID")
        expected = b"S" * 1024 if name == "string" else bytes(index % 251 for index in range(1024)) if name == "bytes" else None
        if expected is None:
            return _result("UNVERIFIED", "PROBE_NAME_INVALID")
        if len(raw) != expected_size or raw != expected:
            return _result("FAIL", "PROBE_CONTENT_INVALID", size=len(raw))
        if sha256_b64(raw) != expected_sha256:
            return _result("FAIL", "PROBE_SHA256_MISMATCH", size=len(raw))
        return _result("PASS", size=len(raw), sha256=sha256_b64(raw))
    except Exception:
        return _result("UNVERIFIED", "PROBE_MALFORMED")


def _gunzip_json(encoded: bytes) -> dict:
    with gzip.GzipFile(fileobj=io.BytesIO(encoded), mode="rb") as stream:
        decompressed = stream.read(MAX_GZIP_RAW_BYTES + 1)
    if len(decompressed) > MAX_GZIP_RAW_BYTES:
        raise EvidenceError("gzip bomb")
    payload = json.loads(decompressed.decode("utf-8"))
    if type(payload) is not dict:
        raise EvidenceError("chunk payload")
    return payload


def verify_chunk(raw_transport, transport, descriptor) -> dict:
    try:
        if transport not in {"bytes", "base64-gzip-string"} or not isinstance(descriptor, Mapping):
            return _result("UNVERIFIED", "CHUNK_ARGUMENT_INVALID")
        if transport == "bytes":
            if type(raw_transport) is not bytes:
                return _result("UNVERIFIED", "CHUNK_TRANSPORT_TYPE_INVALID")
            encoded = decode_transport(raw_transport)
        else:
            if type(raw_transport) is bytes:
                raw_transport = raw_transport.decode("utf-8")
            if type(raw_transport) is not str:
                return _result("UNVERIFIED", "CHUNK_TRANSPORT_TYPE_INVALID")
            encoded = decode_transport(raw_transport)
        if len(encoded) != descriptor.get("encoded_bytes") or sha256_b64(encoded) != descriptor.get("sha256"):
            return _result("FAIL", "CHUNK_DESCRIPTOR_HASH_OR_SIZE_MISMATCH")
        payload = _gunzip_json(encoded)
        validate_chunk(payload)
        if encode_chunk(payload) != encoded:
            return _result("FAIL", "CHUNK_NONCANONICAL_GZIP")
        daily = payload["daily"]
        if (payload["year"] != descriptor.get("year") or payload["run_variant"] != descriptor.get("run_variant") or
                len(daily) != descriptor.get("rows") or daily[0]["date"] != descriptor.get("first_date") or daily[-1]["date"] != descriptor.get("last_date")):
            return _result("FAIL", "CHUNK_DESCRIPTOR_METADATA_MISMATCH")
        return _result("PASS", year=payload["year"], run_variant=payload["run_variant"], synthetic=payload["synthetic"], daily=daily)
    except Exception:
        return _result("UNVERIFIED", "CHUNK_MALFORMED")


def recompute_attribution(daily) -> dict:
    try:
        if type(daily) is not list or not daily or len(daily) > 10000:
            return _result("UNVERIFIED", "ATTRIBUTION_DAILY_INVALID")
        previous_equity = None
        cumulative = {sleeve: Decimal("0") for sleeve in SLEEVES}
        fees = {sleeve: Decimal("0") for sleeve in SLEEVES}
        slippage = {sleeve: Decimal("0") for sleeve in SLEEVES}
        for row in daily:
            if not isinstance(row, Mapping) or not isinstance(row.get("sleeves"), Mapping):
                return _result("UNVERIFIED", "ATTRIBUTION_ROW_INVALID")
            current = _decimal(row.get("strategy_equity"))
            sleeves = row["sleeves"]
            if set(sleeves) != set(SLEEVES):
                return _result("UNVERIFIED", "ATTRIBUTION_SLEEVES_INVALID")
            total = Decimal("0")
            for sleeve in SLEEVES:
                values = sleeves[sleeve]
                if not isinstance(values, Mapping):
                    return _result("UNVERIFIED", "ATTRIBUTION_SLEEVE_ROW_INVALID")
                pnl, fee, slip = _decimal(values.get("daily_pnl")), _decimal(values.get("fees")), _decimal(values.get("slippage"))
                if fee < 0 or slip < 0:
                    return _result("UNVERIFIED", "ATTRIBUTION_COST_INVALID")
                total += pnl; cumulative[sleeve] += pnl; fees[sleeve] += fee; slippage[sleeve] += slip
                if _decimal(values.get("cumulative_pnl")) != cumulative[sleeve]:
                    return _result("UNVERIFIED", "ATTRIBUTION_CUMULATIVE_PNL_MISMATCH")
            change = Decimal("0") if previous_equity is None else current - previous_equity
            if total != change:
                return _result("UNVERIFIED", "ATTRIBUTION_NOT_CONSERVED")
            previous_equity = current
        return _result("PASS", reconciliation="PASS", rows=len(daily),
                       cumulative_pnl={key: str(value) for key, value in cumulative.items()},
                       fees={key: str(value) for key, value in fees.items()},
                       slippage={key: str(value) for key, value in slippage.items()})
    except Exception:
        return _result("UNVERIFIED", "ATTRIBUTION_MALFORMED")


def _add_error(errors: list[str], code: str) -> None:
    if code not in errors and len(errors) < MAX_ERRORS:
        errors.append(code)


def _object_metadata(value: object) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    if not isinstance(value, Mapping) or not isinstance(value.get("objects"), list) or len(value["objects"]) > MAX_ARCHIVE_OBJECTS:
        return {}, ["OBJECT_LIST_INVALID"]
    used = value.get("object_storage_used")
    if used is not None and (type(used) is not int or used < 0):
        _add_error(errors, "OBJECT_STORAGE_USED_INVALID")
    items: dict[str, dict] = {}
    optional_types = {"name": str, "mime": str, "mimeType": str, "modified": str, "lastModified": str, "folder": bool}
    for item in value["objects"]:
        if not isinstance(item, Mapping) or type(item.get("key")) is not str or not item["key"] or type(item.get("size")) is not int or item["size"] < 0 or len(item["key"]) > 1024 or any(key in item and type(item[key]) is not expected for key, expected in optional_types.items()):
            _add_error(errors, "OBJECT_METADATA_INVALID")
            continue
        if item["key"] in items:
            _add_error(errors, "OBJECT_KEY_DUPLICATE")
            continue
        items[item["key"]] = dict(item)
    return items, errors


def _synthetic_fixture(chunk: dict) -> list[str]:
    errors: list[str] = []
    daily = chunk.get("daily", [])
    if not chunk.get("synthetic") or chunk.get("year") != 2015 or [row.get("date") for row in daily] != ["2015-01-02", "2015-01-05"]:
        return ["SYNTHETIC_FIXTURE_DATES_INVALID"]
    for row in daily:
        if row.get("strategy_equity") not in {"1000000", "1000000.0", "1000000.00"} or row.get("spy_equity") not in {"1000000", "1000000.0", "1000000.00"} or row.get("positions") != []:
            _add_error(errors, "SYNTHETIC_FIXTURE_EQUITY_OR_POSITIONS_INVALID")
        gates = row.get("gates")
        if not isinstance(gates, Mapping) or gates.get("failures") != [] or any(gates.get(name) != 0 for name in ("data_missing", "order_rejected", "partial_fill", "cancelled", "exercise", "assignment", "future_data")):
            _add_error(errors, "SYNTHETIC_FIXTURE_GATES_INVALID")
    return errors


def _check_orders_and_trades(archive: Mapping, errors: list[str]) -> None:
    orders, trades = archive.get("orders"), archive.get("trades")
    if type(orders) is not list or type(trades) is not list:
        _add_error(errors, "ORDERS_OR_TRADES_NOT_COMPLETE_LIST")
    elif orders or trades:
        _add_error(errors, "ORDERS_OR_TRADES_NONEMPTY")


def _validate_fetch_manifest(value: object, objects: Mapping, manifest: Mapping | None, backtest_identity: dict | None, orders: object, trades: object) -> list[str]:
    """Bind the archive's recorded download provenance to its exact raw objects."""
    try:
        required = {"project_id", "backtest_id", "organization_id", "algorithm_id", "order_count", "trade_count", "downloaded_at_utc", "objects"}
        if not isinstance(value, Mapping) or set(value) != required:
            return ["FETCH_MANIFEST_FIELDS_INVALID"]
        if type(value["project_id"]) is not int or value["project_id"] < 0 or any(type(value[key]) is not str or not value[key] for key in ("backtest_id", "organization_id", "algorithm_id", "downloaded_at_utc")):
            return ["FETCH_MANIFEST_TYPES_INVALID"]
        if type(value["order_count"]) is not int or type(value["trade_count"]) is not int or value["order_count"] < 0 or value["trade_count"] < 0:
            return ["FETCH_MANIFEST_COUNTS_INVALID"]
        parsed = datetime.fromisoformat(value["downloaded_at_utc"].replace("Z", "+00:00"))
        if not value["downloaded_at_utc"].endswith("Z") or parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            return ["FETCH_MANIFEST_TIMESTAMP_INVALID"]
        if type(value["objects"]) is not list or len(value["objects"]) != len(objects) or len(objects) > MAX_ARCHIVE_OBJECTS:
            return ["FETCH_MANIFEST_OBJECTS_INVALID"]
        errors: list[str] = []
        seen = set()
        records = value["objects"]
        for index, record in enumerate(records):
            if not isinstance(record, Mapping) or set(record) != {"key", "bytes", "sha256"} or type(record.get("key")) is not str or type(record.get("bytes")) is not int or record["bytes"] < 0 or type(record.get("sha256")) is not str:
                _add_error(errors, "FETCH_MANIFEST_OBJECT_RECORD_INVALID"); continue
            key = record["key"]
            if key in seen or index >= len(objects) or key != list(objects)[index] or key not in objects:
                _add_error(errors, "FETCH_MANIFEST_OBJECT_ORDER_OR_DUPLICATE")
                continue
            seen.add(key)
            raw = _storage_bytes(objects[key])
            if record["bytes"] != len(raw) or record["sha256"] != sha256_b64(raw):
                _add_error(errors, "FETCH_MANIFEST_OBJECT_HASH_OR_SIZE_MISMATCH")
        if set(objects) != seen:
            _add_error(errors, "FETCH_MANIFEST_OBJECT_SET_MISMATCH")
        if type(orders) is list and value["order_count"] != len(orders) or type(trades) is list and value["trade_count"] != len(trades):
            _add_error(errors, "FETCH_MANIFEST_COUNTS_MISMATCH")
        if manifest is not None and (str(value["project_id"]) != manifest.get("project_id") or value["algorithm_id"] != manifest.get("algorithm_id")):
            _add_error(errors, "FETCH_MANIFEST_IDENTITY_MISMATCH")
        if backtest_identity is None:
            _add_error(errors, "BACKTEST_IDENTITY_UNAVAILABLE")
        else:
            if value["backtest_id"] != backtest_identity["backtest_id"]:
                _add_error(errors, "FETCH_BACKTEST_ID_MISMATCH")
            if value["project_id"] != backtest_identity["project_id"]:
                _add_error(errors, "FETCH_PROJECT_ID_MISMATCH")
            if value["organization_id"] != backtest_identity["organization_id"]:
                _add_error(errors, "FETCH_ORGANIZATION_ID_MISMATCH")
        return errors
    except Exception:
        return ["FETCH_MANIFEST_MALFORMED"]


def _verify_archive(archive, expected_identity=None) -> dict:
    """Verify an in-memory archive, collecting all bounded diagnostic codes."""
    errors: list[str] = []
    if not isinstance(archive, Mapping):
        return {"overall_status": "UNVERIFIED", "errors": ["ARCHIVE_INVALID"], "object_store": {}, "attribution": {}}
    objects = archive.get("objects")
    if not isinstance(objects, Mapping) or len(objects) > MAX_ARCHIVE_OBJECTS:
        _add_error(errors, "ARCHIVE_OBJECTS_INVALID")
        objects = {}
    else:
        try:
            total_object_bytes = sum(len(_storage_bytes(raw)) for raw in objects.values())
            if total_object_bytes > MAX_TOTAL_ARCHIVE_OBJECT_BYTES:
                _add_error(errors, "ARCHIVE_OBJECTS_TOTAL_SIZE_EXCEEDED")
        except Exception:
            _add_error(errors, "ARCHIVE_OBJECTS_INVALID")
    backtest_identity = _backtest_identity(archive.get("backtest"))
    expected_valid = False
    if expected_identity is not None:
        if not isinstance(expected_identity, Mapping) or set(expected_identity) != {"project_id", "backtest_id", "organization_id"} or type(expected_identity["project_id"]) is not int or type(expected_identity["backtest_id"]) is not str or type(expected_identity["organization_id"]) is not str:
            _add_error(errors, "EXPECTED_IDENTITY_INVALID")
        elif backtest_identity is None or any(backtest_identity[key] != expected_identity[key] for key in expected_identity):
            _add_error(errors, "EXPECTED_IDENTITY_MISMATCH")
        else:
            expected_valid = True
    for error in _validate_fetch_manifest(archive.get("fetch_manifest"), objects, None, backtest_identity, archive.get("orders"), archive.get("trades")):
        _add_error(errors, error)
    if expected_valid:
        fetch = archive.get("fetch_manifest")
        if not isinstance(fetch, Mapping) or any(fetch.get(key) != expected_identity[key] for key in expected_identity):
            _add_error(errors, "EXPECTED_FETCH_IDENTITY_MISMATCH")
    runtime = extract_runtime_statistics(archive.get("backtest"))
    if runtime["status"] != "PASS":
        for error in runtime["errors"]: _add_error(errors, error)
        _, metadata_errors = _object_metadata(archive.get("object_list"))
        for error in metadata_errors: _add_error(errors, error)
        _check_orders_and_trades(archive, errors)
        return {"overall_status": "UNVERIFIED", "errors": errors, "runtime": runtime,
                "object_store": {"status": "UNAVAILABLE"}, "attribution": {"reconciliation": "UNAVAILABLE"}}
    metadata, metadata_errors = _object_metadata(archive.get("object_list"))
    for error in metadata_errors: _add_error(errors, error)
    required = [runtime["string_key"], runtime["manifest_key"]]
    if runtime["transport"] == "bytes": required.insert(1, runtime["bytes_key"])
    for key in required:
        if key not in metadata or key not in objects: _add_error(errors, "REQUIRED_OBJECT_MISSING")
        elif metadata[key].get("folder") is not False or type(objects[key]) not in (bytes, str) or metadata[key]["size"] != len(_storage_bytes(objects[key])):
            _add_error(errors, "OBJECT_METADATA_SIZE_MISMATCH")
    string_probe = verify_probe("string", objects.get(runtime["string_key"]), 1024, runtime["string_sha256"])
    if string_probe["status"] != "PASS": _add_error(errors, string_probe["errors"][0])
    bytes_probe = verify_probe("bytes", objects.get(runtime["bytes_key"]), 1024, runtime["bytes_sha256"]) if runtime["transport"] == "bytes" else _result("FAIL", "BYTES_FALLBACK_EXPECTED")
    if runtime["transport"] == "bytes" and bytes_probe["status"] != "PASS": _add_error(errors, bytes_probe["errors"][0])
    manifest_result = decode_manifest(objects.get(runtime["manifest_key"]))
    if manifest_result["status"] != "PASS":
        _add_error(errors, manifest_result["errors"][0])
        _check_orders_and_trades(archive, errors)
        return {"overall_status": "UNVERIFIED", "errors": errors, "runtime": runtime,
                "object_store": {"status": "UNVERIFIED", "string_round_trip": string_probe["status"], "bytes_round_trip": bytes_probe["status"]},
                "attribution": {"reconciliation": "UNAVAILABLE"}}
    for error in _validate_fetch_manifest(archive.get("fetch_manifest"), objects, manifest_result, backtest_identity, archive.get("orders"), archive.get("trades")):
        _add_error(errors, error)
    if manifest_result["transport"] != runtime["transport"]: _add_error(errors, "MANIFEST_TRANSPORT_MISMATCH")
    expected_prefix = f"{manifest_result['project_id']}/v2/{manifest_result['frozen_commit']}/{manifest_result['run_label']}/{manifest_result['algorithm_id']}"
    if expected_prefix != runtime["prefix"] or build_manifest_key(manifest_result["project_id"], manifest_result["frozen_commit"], manifest_result["run_label"], manifest_result["algorithm_id"]) != runtime["manifest_key"]:
        _add_error(errors, "MANIFEST_IDENTITY_MISMATCH")
    expected_probes = build_probe_keys(manifest_result["project_id"], manifest_result["frozen_commit"], manifest_result["run_label"], manifest_result["algorithm_id"])
    if runtime["string_key"] != expected_probes["string"] or runtime["bytes_key"] != expected_probes["bytes"]:
        _add_error(errors, "RUNTIME_PROBE_IDENTITY_MISMATCH")
    chunks: list[dict] = []
    for descriptor in manifest_result["chunks"]:
        key = descriptor["key"]
        if key not in metadata or key not in objects: _add_error(errors, "CHUNK_OBJECT_MISSING"); continue
        if metadata[key].get("folder") is not False or type(objects[key]) not in (bytes, str) or metadata[key]["size"] != len(_storage_bytes(objects[key])):
            _add_error(errors, "OBJECT_METADATA_SIZE_MISMATCH"); continue
        if key != build_chunk_key(manifest_result["project_id"], manifest_result["frozen_commit"], manifest_result["run_label"], manifest_result["algorithm_id"], descriptor["year"]): _add_error(errors, "CHUNK_KEY_IDENTITY_MISMATCH"); continue
        checked = verify_chunk(objects[key], runtime["transport"], descriptor)
        if checked["status"] != "PASS": _add_error(errors, checked["errors"][0]); continue
        chunks.append(checked)
        for error in _synthetic_fixture(checked): _add_error(errors, error)
    if len(chunks) != len(manifest_result["chunks"]): _add_error(errors, "CHUNK_VERIFICATION_INCOMPLETE")
    all_daily = [row for chunk in chunks for row in chunk["daily"]]
    attribution = recompute_attribution(all_daily)
    if attribution["status"] != "PASS": _add_error(errors, attribution["errors"][0])
    _check_orders_and_trades(archive, errors)
    status = "UNVERIFIED" if errors else runtime["capability_status"]
    if status not in {"PASS", "PASS_WITH_STRING_FALLBACK"}: status = "UNVERIFIED"
    return {"overall_status": status, "identity_assurance": "EXTERNALLY_ANCHORED" if expected_valid else "INTERNAL_ONLY", "errors": errors, "runtime": runtime,
            "object_store": {"string_round_trip": string_probe["status"], "bytes_round_trip": bytes_probe["status"], "manifest": manifest_result["status"], "chunks": len(chunks)},
            "attribution": {"reconciliation": "PASS" if attribution["status"] == "PASS" else "UNVERIFIED", **{key: value for key, value in attribution.items() if key not in {"status", "errors"}}}}


def verify_archive(archive, expected_identity=None) -> dict:
    """Never raise for untrusted archive input; return a bounded UNVERIFIED report."""
    try:
        return _verify_archive(archive, expected_identity)
    except Exception:
        return {"overall_status": "UNVERIFIED", "errors": ["ARCHIVE_MALFORMED"], "object_store": {}, "attribution": {}}
