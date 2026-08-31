#!/usr/bin/env python3
"""Safely load a downloaded v2 archive and write its verification result."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
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
_ROOT_FILES = frozenset({"backtest.json", "orders.jsonl", "trades.jsonl", "object-list.json", "object-lists.json", "key-map.json", "fetch-manifest.json", "verification.json", "objects"})


class ArchiveReadError(RuntimeError):
    pass


def _open_directory(path: Path, *, dir_fd: int | None = None) -> int:
    try:
        return os.open(str(path) if dir_fd is None else path.name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
    except OSError as error:
        raise ArchiveReadError("archive directory is unavailable") from error


def _read_bytes(directory_fd: int, name: str, maximum: int) -> bytes:
    descriptor = None
    try:
        if type(name) is not str or not name or "/" in name:
            raise ArchiveReadError("archive path is invalid")
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ArchiveReadError("archive file metadata is invalid")
        parts, remaining = [], maximum + 1
        while remaining:
            part = os.read(descriptor, min(65536, remaining))
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        raw = b"".join(parts)
        if len(raw) > maximum:
            raise ArchiveReadError("archive file size is invalid")
        return raw
    except OSError as error:
        raise ArchiveReadError("archive file cannot be read") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _no_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveReadError("archive JSON contains duplicate keys")
        result[key] = value
    return result


def _read_json(directory_fd: int, name: str, maximum: int = MAX_JSON_BYTES):
    try:
        return json.loads(_read_bytes(directory_fd, name, maximum).decode("utf-8"), object_pairs_hook=_no_duplicate_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveReadError("archive JSON is invalid") from error


def _read_jsonl(directory_fd: int, name: str) -> list:
    raw = _read_bytes(directory_fd, name, MAX_JSON_BYTES)
    try:
        rows = [json.loads(line, object_pairs_hook=_no_duplicate_object) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveReadError("archive JSONL is invalid") from error
    if len(rows) > MAX_ARCHIVE_OBJECTS:
        raise ArchiveReadError("archive JSONL has too many rows")
    return rows


def load_archive(archive_dir: Path) -> dict:
    archive_dir = Path(archive_dir)
    root_fd = _open_directory(archive_dir)
    objects_fd = None
    try:
        names = set(os.listdir(root_fd))
        required = {"backtest.json", "orders.jsonl", "trades.jsonl", "object-list.json", "key-map.json", "fetch-manifest.json", "objects"}
        if not required.issubset(names) or not names.issubset(_ROOT_FILES):
            raise ArchiveReadError("archive root entries are invalid")
        objects_fd = _open_directory(Path("objects"), dir_fd=root_fd)
        key_map = _read_json(root_fd, "key-map.json")
        if not isinstance(key_map, dict) or not key_map or len(key_map) > MAX_ARCHIVE_OBJECTS:
            raise ArchiveReadError("archive key map is invalid")
        entries = list(key_map.items())
        if any(type(key) is not str or type(path) is not str or not _OBJECT_PATH.fullmatch(path) for key, path in entries):
            raise ArchiveReadError("archive key map contains unsafe path")
        paths = [path for _, path in entries]
        expected_paths = [f"objects/{index:04d}.bin" for index in range(1, len(paths) + 1)]
        if len(set(paths)) != len(paths) or sorted(paths) != expected_paths:
            raise ArchiveReadError("archive object numbering is invalid")
        if set(os.listdir(objects_fd)) != {path.rsplit("/", 1)[1] for path in paths}:
            raise ArchiveReadError("archive object directory entries are invalid")
        ordered_keys = [key for key, _ in sorted(entries, key=lambda item: item[1])]
        objects, total = {}, 0
        for key in ordered_keys:
            raw = _read_bytes(objects_fd, key_map[key].rsplit("/", 1)[1], MAX_STRING_TRANSPORT_BYTES)
            total += len(raw)
            if total > MAX_TOTAL_OBJECT_BYTES:
                raise ArchiveReadError("archive objects exceed total size limit")
            objects[key] = raw
        fetch_manifest = _read_json(root_fd, "fetch-manifest.json")
        if not isinstance(fetch_manifest, dict) or not isinstance(fetch_manifest.get("objects"), list):
            raise ArchiveReadError("archive fetch manifest is invalid")
        records = fetch_manifest["objects"]
        if [record.get("key") if isinstance(record, dict) else None for record in records] != ordered_keys or len(records) != len(key_map):
            raise ArchiveReadError("archive fetch manifest order is invalid")
        return {"backtest": _read_json(root_fd, "backtest.json"), "object_list": _read_json(root_fd, "object-list.json"),
                "orders": _read_jsonl(root_fd, "orders.jsonl"), "trades": _read_jsonl(root_fd, "trades.jsonl"),
                "objects": objects, "fetch_manifest": fetch_manifest}
    finally:
        if objects_fd is not None:
            os.close(objects_fd)
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify a v2 evidence archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-project-id", type=int, required=True)
    parser.add_argument("--expected-backtest-id", required=True)
    parser.add_argument("--expected-organization-id", required=True)
    arguments = parser.parse_args()
    temporary = None
    try:
        result = verify_archive(load_archive(arguments.archive), expected_identity={"project_id": arguments.expected_project_id, "backtest_id": arguments.expected_backtest_id, "organization_id": arguments.expected_organization_id})
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as stream:
            json.dump(result, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            temporary = Path(stream.name)
        # link(2) creates the final name only if it does not already exist.
        # Unlike replace(), it cannot clobber a concurrent verifier's result.
        os.link(temporary, arguments.output)
        temporary.unlink()
        temporary = None
        return 0 if result["overall_status"] in {"PASS", "PASS_WITH_STRING_FALLBACK"} else 1
    except (ArchiveReadError, OSError) as error:
        print(f"verification failed: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
