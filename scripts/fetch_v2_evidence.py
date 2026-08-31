#!/usr/bin/env python3
"""Read-only downloader for a complete v2 capability archive."""

from __future__ import annotations

import argparse
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
from spy_plus_10.v2.verifier import decode_manifest, extract_runtime_statistics, verify_archive


class FetchV2EvidenceError(RuntimeError):
    """Raised when a v2 archive cannot be completely downloaded and verified."""


_SENSITIVE = ("authorization", "token", "secret", "credential", "signed", "url", "user")
_SENSITIVE_VALUE = re.compile(r"(?i)(?:authorization\s*[:=]|(?:api[-_ ]?token|token|secret|credential|password)\s*[:=]|https?://\S+(?:[?&](?:sig|signature|token|key)=))")


def _safe_value(value):
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items() if not any(marker in str(key).lower() for marker in _SENSITIVE)}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    return value


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
        object_list = client.list_objects(organization_id, runtime["prefix"])
        if not isinstance(object_list, dict) or not isinstance(object_list.get("objects"), list):
            raise FetchV2EvidenceError("Object Store listing is invalid")
        listed = {item.get("key") for item in object_list["objects"] if isinstance(item, dict)}
        keys = [runtime["string_key"]]
        if runtime["transport"] == "bytes":
            keys.append(runtime["bytes_key"])
        keys.append(runtime["manifest_key"])
        downloaded: dict[str, object] = {}

        def download(key: str):
            _prefix_bound(key, runtime["prefix"])
            if key not in listed:
                raise FetchV2EvidenceError("required object is absent from Object Store listing")
            if key not in downloaded:
                value = client.download_object(organization_id, key)
                _storage_bytes(value)
                downloaded[key] = value
            return downloaded[key]

        for key in keys:
            download(key)
        manifest = decode_manifest(downloaded[runtime["manifest_key"]])
        if manifest["status"] != "PASS" or manifest["transport"] != runtime["transport"]:
            raise FetchV2EvidenceError("v2 manifest is invalid or transport-mismatched")
        for descriptor in manifest["chunks"]:
            key = _prefix_bound(descriptor["key"], runtime["prefix"])
            download(key)
        archive = {"backtest": backtest, "object_list": object_list, "orders": orders, "trades": trades, "objects": downloaded}
        verification = verify_archive(archive)
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
            object_records.append({"key": key, "bytes": len(value), "sha256": __import__("base64").b64encode(hashlib.sha256(value).digest()).decode("ascii")})
        _write_json(temporary / "backtest.json", backtest)
        _write_jsonl(temporary / "orders.jsonl", orders)
        _write_jsonl(temporary / "trades.jsonl", trades)
        _write_json(temporary / "object-list.json", object_list)
        _write_json(temporary / "key-map.json", key_map)
        _write_json(temporary / "fetch-manifest.json", {
            "project_id": int(project_id), "backtest_id": str(backtest_id), "organization_id": str(organization_id),
            "algorithm_id": manifest["algorithm_id"], "order_count": len(orders), "trade_count": len(trades),
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "objects": object_records,
        })
        os.replace(temporary, output_dir)
        return {"verification": verification, "fetch_manifest": {"object_count": len(object_records), "order_count": len(orders), "trade_count": len(trades)}}
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
