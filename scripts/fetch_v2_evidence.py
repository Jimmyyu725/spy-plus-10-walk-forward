#!/usr/bin/env python3
"""Read-only downloader for a complete v2 capability archive."""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fetch_quantconnect_evidence import QuantConnectApiError, QuantConnectClient, load_credentials
from spy_plus_10.v2.evidence import MAX_CHUNK_BYTES
from spy_plus_10.v2.verifier import decode_manifest, extract_runtime_statistics, verify_archive
from verify_v2_evidence import load_archive


class FetchV2EvidenceError(RuntimeError):
    """Raised when a v2 archive cannot be completely downloaded and verified."""


_SENSITIVE = frozenset({"authorization", "proxy_authorization", "cookie", "set_cookie", "token", "api_token", "api_key", "auth_token", "key", "password", "secret", "credentials", "credential", "client_secret", "access_token", "refresh_token", "private_key", "access_key", "access_key_id", "secret_key", "secret_access_key"})
_SENSITIVE_SUFFIXES = ("_token", "_secret", "_password", "_credential", "_credentials")
_SENSITIVE_COMPOUND_SUFFIXES = ("_api_key", "_access_key", "_access_key_id", "_secret_key", "_secret_access_key", "_private_key")
_SENSITIVE_VALUE = re.compile(r"(?i)(?:\bauthorization\s*[:=]\s*\S+|\b(?:bearer|basic)\s+\S+|\b(?:(?:api|access|refresh|auth)\s*[-_ ]?\s*(?:token|key)|client\s*[-_ ]?\s*secret|(?:private|secret)\s*[-_ ]?\s*key|key|token|password|secret|cookie)\s*[:=]\s*\S+|[?&](?:x-amz-[^=]+|x-goog-(?:signature|credential|security-token|algorithm|date|expires|signedheaders)|signature|sig|token|password|api[-_]?key|key)=[^&\s]+)")
_MAX_TRANSPORT_BYTES = len("base64-gzip:") + 4 * ((MAX_CHUNK_BYTES + 2) // 3)


def _sensitive_key(key: object, *, object_record: bool) -> bool:
    if type(key) is not str:
        return False
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    normalized = re.sub(r"[-\s]+", "_", normalized).lower()
    if normalized == "key" and object_record:
        return False
    return normalized in _SENSITIVE or normalized.endswith(_SENSITIVE_SUFFIXES + _SENSITIVE_COMPOUND_SUFFIXES)


def _safe_value(value):
    if isinstance(value, dict):
        object_record = ("key" in value and (("size" in value and "folder" in value) or ("bytes" in value and "sha256" in value)))
        return {str(key): ("[REDACTED]" if _sensitive_key(key, object_record=object_record) else _safe_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    return value


def _rename_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a directory only when the target name is absent."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as error:  # Linux is an explicit deployment contract.
        raise FetchV2EvidenceError("atomic non-overwrite publish is unavailable") from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:  # RENAME_NOREPLACE
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FetchV2EvidenceError("output directory already exists")
        raise FetchV2EvidenceError("atomic evidence publish failed") from OSError(error_number, os.strerror(error_number))


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(_safe_value(value), sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list) -> None:
    path.write_text("".join(json.dumps(_safe_value(row), sort_keys=True, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def _storage_bytes(value) -> bytes:
    if type(value) is bytes:
        return value
    if type(value) is str:
        return value.encode("utf-8")
    raise FetchV2EvidenceError("downloaded object has invalid type")


def _prefix_bound(key: object, prefix: str) -> str:
    if type(key) is not str or not key.startswith(prefix + "/") or ".." in key.split("/"):
        raise FetchV2EvidenceError("runtime or manifest object key escapes evidence prefix")
    return key


def _fetch_manifest(*, project_id: int, backtest_id: str, organization_id: str, algorithm_id: str, orders: list, trades: list, objects: dict[str, object]) -> dict:
    records = []
    for key, raw in objects.items():
        value = _storage_bytes(raw)
        records.append({"key": key, "bytes": len(value), "sha256": base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")})
    return {"project_id": int(project_id), "backtest_id": str(backtest_id), "organization_id": str(organization_id),
            "algorithm_id": str(algorithm_id), "order_count": len(orders), "trade_count": len(trades),
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "objects": records}


def _require_direct_files(listing: object, expected: dict[str, bool]) -> None:
    """Reject flattened Object Store replies before downloading any raw object."""
    if not isinstance(listing, dict) or not isinstance(listing.get("objects"), list):
        raise FetchV2EvidenceError("Object Store listing is invalid")
    entries = listing["objects"]
    if any(not isinstance(item, dict) or type(item.get("key")) is not str or type(item.get("size")) is not int or item["size"] < 0 or type(item.get("folder")) is not bool for item in entries):
        raise FetchV2EvidenceError("Object Store listing metadata is invalid")
    actual = {item["key"]: item for item in entries}
    if len(actual) != len(entries) or set(actual) != set(expected) or any(actual[key]["folder"] is not folder for key, folder in expected.items()):
        raise FetchV2EvidenceError("Object Store listing has invalid direct placement")


def fetch_v2_evidence(client, *, project_id: int, backtest_id: str, organization_id: str, output_dir: Path) -> dict:
    """Fetch exactly one archive, validate it offline, then atomically publish it."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FetchV2EvidenceError("output directory already exists")
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
    try:
        backtest = client.read_backtest(project_id, backtest_id)
        orders = client.read_all_backtest_rows("backtests/orders/read", "orders", project_id, backtest_id)
        trades = client.read_all_backtest_rows("backtests/trades/read", "trades", project_id, backtest_id)
        runtime = extract_runtime_statistics(backtest)
        if runtime["status"] != "PASS":
            raise FetchV2EvidenceError("v2 runtime statistics are invalid")
        root_list = client.list_objects(organization_id, runtime["prefix"])
        capability_list = client.list_objects(organization_id, runtime["prefix"] + "/capability")
        if not all(isinstance(value, dict) and isinstance(value.get("objects"), list) for value in (root_list, capability_list)):
            raise FetchV2EvidenceError("Object Store listing is invalid")
        used = [value.get("object_storage_used") for value in (root_list, capability_list)]
        if any(value != used[0] for value in used[1:]):
            raise FetchV2EvidenceError("Object Store storage-used values disagree")
        _require_direct_files(root_list, {runtime["manifest_key"]: False, runtime["prefix"] + "/capability": True, runtime["prefix"] + "/evidence": True})
        known_capability = {runtime["string_key"]: False}
        if runtime["transport"] == "bytes":
            known_capability[runtime["bytes_key"]] = False
        _require_direct_files(capability_list, known_capability)
        listed_items = {item.get("key"): item for listing in (root_list, capability_list) for item in listing["objects"] if isinstance(item, dict) and type(item.get("key")) is str}
        keys = [runtime["string_key"]]
        if runtime["transport"] == "bytes":
            keys.append(runtime["bytes_key"])
        keys.append(runtime["manifest_key"])
        downloaded: dict[str, object] = {}

        def download(key: str):
            _prefix_bound(key, runtime["prefix"])
            item = listed_items.get(key)
            if item is None or item.get("folder") is not False:
                raise FetchV2EvidenceError("required object is absent from Object Store listing")
            if key not in downloaded:
                try:
                    value = client.download_object(organization_id, key, max_transport_bytes=_MAX_TRANSPORT_BYTES,
                                                   max_uncompressed_bytes=_MAX_TRANSPORT_BYTES)
                except TypeError:  # Test doubles and legacy caller-owned clients retain the v1 method shape.
                    value = client.download_object(organization_id, key)
                _storage_bytes(value)
                downloaded[key] = value
            return downloaded[key]

        for key in keys:
            download(key)
        manifest = decode_manifest(downloaded[runtime["manifest_key"]])
        if manifest["status"] != "PASS" or manifest["transport"] != runtime["transport"]:
            raise FetchV2EvidenceError("v2 manifest is invalid or transport-mismatched")
        evidence_list = client.list_objects(organization_id, runtime["prefix"] + "/evidence")
        if not isinstance(evidence_list, dict) or not isinstance(evidence_list.get("objects"), list) or evidence_list.get("object_storage_used") != used[0]:
            raise FetchV2EvidenceError("Object Store evidence listing is invalid")
        _require_direct_files(evidence_list, {descriptor["key"]: False for descriptor in manifest["chunks"]})
        for item in evidence_list["objects"]:
            if isinstance(item, dict) and type(item.get("key")) is str:
                listed_items[item["key"]] = item
        object_list = {"objects": [*root_list["objects"], *capability_list["objects"], *evidence_list["objects"]], "object_storage_used": used[0]}
        object_lists = {
            "root": {**root_list, "path": runtime["prefix"], "listed_paths": [item.get("key") for item in root_list["objects"] if isinstance(item, dict)]},
            "capability": {**capability_list, "path": runtime["prefix"] + "/capability", "listed_paths": [item.get("key") for item in capability_list["objects"] if isinstance(item, dict)]},
            "evidence": {**evidence_list, "path": runtime["prefix"] + "/evidence", "listed_paths": [item.get("key") for item in evidence_list["objects"] if isinstance(item, dict)]},
        }
        for descriptor in manifest["chunks"]:
            key = _prefix_bound(descriptor["key"], runtime["prefix"])
            download(key)
        archive = {"backtest": _safe_value(backtest), "object_list": _safe_value(object_list), "object_lists": _safe_value(object_lists),
                   "orders": _safe_value(orders), "trades": _safe_value(trades), "objects": downloaded}
        archive["fetch_manifest"] = _fetch_manifest(project_id=project_id, backtest_id=backtest_id,
                                                      organization_id=organization_id, algorithm_id=manifest["algorithm_id"],
                                                      orders=archive["orders"], trades=archive["trades"], objects=downloaded)
        verification = verify_archive(archive, expected_identity={"project_id": int(project_id), "backtest_id": str(backtest_id), "organization_id": str(organization_id)})
        if verification["overall_status"] not in {"PASS", "PASS_WITH_STRING_FALLBACK"}:
            raise FetchV2EvidenceError("downloaded v2 archive failed independent verification")
        objects_dir = temporary / "objects"
        objects_dir.mkdir()
        key_map = {}
        object_records = []
        for index, (key, raw) in enumerate(downloaded.items(), 1):
            relative = f"objects/{index:04d}.bin"
            value = _storage_bytes(raw)
            (temporary / relative).write_bytes(value)
            key_map[key] = relative
            object_records.append({"key": key, "bytes": len(value), "sha256": base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")})
        _write_json(temporary / "backtest.json", archive["backtest"])
        _write_jsonl(temporary / "orders.jsonl", archive["orders"])
        _write_jsonl(temporary / "trades.jsonl", archive["trades"])
        _write_json(temporary / "object-list.json", archive["object_list"])
        _write_json(temporary / "object-lists.json", archive["object_lists"])
        _write_json(temporary / "key-map.json", key_map)
        if object_records != archive["fetch_manifest"]["objects"]:
            raise FetchV2EvidenceError("archive object manifest drifted before publish")
        _write_json(temporary / "fetch-manifest.json", archive["fetch_manifest"])
        disk_verification = verify_archive(load_archive(temporary), expected_identity={"project_id": int(project_id), "backtest_id": str(backtest_id), "organization_id": str(organization_id)})
        if disk_verification["overall_status"] not in {"PASS", "PASS_WITH_STRING_FALLBACK"}:
            raise FetchV2EvidenceError("written v2 archive failed independent verification")
        _rename_noreplace(temporary, output_dir)
        return {"verification": disk_verification, "fetch_manifest": {"object_count": len(object_records), "order_count": len(orders), "trade_count": len(trades)}}
    except (FetchV2EvidenceError, QuantConnectApiError):
        raise
    except Exception as error:
        raise FetchV2EvidenceError("v2 evidence download failed") from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch v2 capability evidence without modifying QuantConnect")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--backtest-id", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, default=Path.home() / ".lean" / "credentials")
    arguments = parser.parse_args()
    try:
        user_id, token = load_credentials(arguments.credentials)
        result = fetch_v2_evidence(QuantConnectClient(user_id, token), project_id=arguments.project_id,
                                   backtest_id=arguments.backtest_id, organization_id=arguments.organization_id,
                                   output_dir=arguments.output_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (FetchV2EvidenceError, QuantConnectApiError) as error:
        print(f"v2 evidence fetch failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
