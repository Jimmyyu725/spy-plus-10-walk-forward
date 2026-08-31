#!/usr/bin/env python3
"""Safely load a downloaded v2 archive and write its verification result."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spy_plus_10.v2.evidence import MAX_CHUNK_BYTES
from spy_plus_10.v2.verifier import MAX_ARCHIVE_OBJECTS, verify_archive


MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_TOTAL_OBJECT_BYTES = 64 * 1024 * 1024
_OBJECT_PATH = re.compile(r"^objects/[0-9]{4}\.bin$")
MAX_STRING_TRANSPORT_BYTES = len("base64-gzip:") + 4 * ((MAX_CHUNK_BYTES + 2) // 3)


class ArchiveReadError(RuntimeError):
    pass


def _inside(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise ArchiveReadError("archive symlink is forbidden")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ArchiveReadError("archive path escapes root") from error
    return resolved


def _read_bytes(root: Path, path: Path, maximum: int) -> bytes:
    try:
        resolved = _inside(root, path)
        if not resolved.is_file() or resolved.stat().st_size > maximum:
            raise ArchiveReadError("archive file size is invalid")
        return resolved.read_bytes()
    except OSError as error:
        raise ArchiveReadError("archive file cannot be read") from error


def _no_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveReadError("archive JSON contains duplicate keys")
        result[key] = value
    return result


def _read_json(root: Path, path: Path, maximum: int = MAX_JSON_BYTES):
    try:
        return json.loads(_read_bytes(root, path, maximum).decode("utf-8"), object_pairs_hook=_no_duplicate_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveReadError("archive JSON is invalid") from error


def _read_jsonl(root: Path, path: Path) -> list:
    raw = _read_bytes(root, path, MAX_JSON_BYTES)
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveReadError("archive JSONL is invalid") from error
    if len(rows) > MAX_ARCHIVE_OBJECTS:
        raise ArchiveReadError("archive JSONL has too many rows")
    return rows


def load_archive(archive_dir: Path) -> dict:
    archive_dir = Path(archive_dir)
    if archive_dir.is_symlink() or not archive_dir.is_dir():
        raise ArchiveReadError("archive directory is unavailable")
    root = archive_dir.resolve(strict=True)
    objects_dir = root / "objects"
    if objects_dir.is_symlink() or not objects_dir.is_dir():
        raise ArchiveReadError("archive objects directory is unavailable")
    key_map = _read_json(root, root / "key-map.json")
    if not isinstance(key_map, dict) or not key_map or len(key_map) > MAX_ARCHIVE_OBJECTS:
        raise ArchiveReadError("archive key map is invalid")
    paths = list(key_map.values())
    if len(paths) != len(set(paths)) or set(paths) != {f"objects/{index:04d}.bin" for index in range(1, len(paths) + 1)}:
        raise ArchiveReadError("archive object numbering is invalid")
    ordered_keys = [key for key, _ in sorted(key_map.items(), key=lambda item: item[1])]
    objects = {}
    total = 0
    for key in ordered_keys:
        relative = key_map[key]
        if type(key) is not str or type(relative) is not str or not _OBJECT_PATH.fullmatch(relative):
            raise ArchiveReadError("archive key map contains unsafe path")
        raw = _read_bytes(root, root / relative, MAX_STRING_TRANSPORT_BYTES)
        total += len(raw)
        if total > MAX_TOTAL_OBJECT_BYTES:
            raise ArchiveReadError("archive objects exceed total size limit")
        objects[key] = raw
    fetch_manifest = _read_json(root, root / "fetch-manifest.json")
    if not isinstance(fetch_manifest, dict) or not isinstance(fetch_manifest.get("objects"), list):
        raise ArchiveReadError("archive fetch manifest is invalid")
    records = fetch_manifest["objects"]
    if [record.get("key") if isinstance(record, dict) else None for record in records] != ordered_keys or len(records) != len(key_map):
        raise ArchiveReadError("archive fetch manifest order is invalid")
    return {"backtest": _read_json(root, root / "backtest.json"), "object_list": _read_json(root, root / "object-list.json"),
            "orders": _read_jsonl(root, root / "orders.jsonl"), "trades": _read_jsonl(root, root / "trades.jsonl"),
            "objects": objects, "fetch_manifest": fetch_manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify a v2 evidence archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        print("verification output already exists", file=sys.stderr)
        return 1
    try:
        result = verify_archive(load_archive(arguments.archive))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as stream:
            json.dump(result, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            temporary = Path(stream.name)
        os.replace(temporary, arguments.output)
        return 0 if result["overall_status"] in {"PASS", "PASS_WITH_STRING_FALLBACK"} else 1
    except (ArchiveReadError, OSError) as error:
        print(f"verification failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
