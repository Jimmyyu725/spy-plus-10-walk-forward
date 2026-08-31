"""Deterministic, local-only v2 annual evidence encoding and validation.

Persist a verified annual chunk only in this order: ``encode_chunk(payload)``,
``chunk_descriptor(year, key, encoded, payload["daily"])``, then
``build_manifest(...)``. Object-store writes occur only after those local gates.
Descriptors carry the decoded chunk ``run_variant`` so manifests cannot relabel
annual evidence from a different run variant.
"""

import base64
import binascii
import gzip
import hashlib
import io
import json
import re
import zlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping


SCHEMA_VERSION = 2
MAX_CHUNK_BYTES = 5 * 1024 * 1024
SLEEVES = ("core", "equity", "futures", "defensive_option")
RUN_VARIANTS = (
    "full",
    "core_only",
    "equity_only",
    "futures_only",
    "defensive_option_only",
    "without_core",
    "without_equity",
    "without_futures",
    "without_defensive_option",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_TRANSPORT_PREFIX = "base64-gzip:"
_MAX_TRANSPORT_B64_CHARS = 4 * ((MAX_CHUNK_BYTES + 2) // 3)
_MAX_RAW_CHUNK_BYTES = 64 * 1024 * 1024
_DAILY_FIELDS = frozenset(
    {
        "date",
        "strategy_equity",
        "spy_equity",
        "sleeves",
        "positions",
        "cash",
        "margin_used",
        "margin_remaining",
        "option_max_loss",
        "total_gross",
        "alpha_gross",
        "beta",
        "risk_contributions",
        "drawdown",
        "drawdown_state",
        "walk_forward",
        "chronology",
        "gates",
    }
)
_SLEEVE_FIELDS = frozenset({"daily_pnl", "cumulative_pnl", "fees", "slippage"})
_WALK_FORWARD_FIELDS = frozenset(
    {"training_start", "training_end", "execution_year", "selected_parameters", "selection_reason"}
)
_CHRONOLOGY_FIELDS = ("data_cutoff", "signal_time", "order_time", "fill_time")
_GATE_COUNTERS = (
    "data_missing",
    "order_rejected",
    "partial_fill",
    "cancelled",
    "exercise",
    "assignment",
    "future_data",
)
_GATE_FIELDS = frozenset({"data_license", "failures", *_GATE_COUNTERS})
_DESCRIPTOR_FIELDS = frozenset(
    {"year", "run_variant", "key", "encoded_bytes", "sha256", "first_date", "last_date", "rows"}
)


class EvidenceError(RuntimeError):
    """Raised when evidence does not meet the frozen v2 protocol."""


def _fail(message: str) -> None:
    raise EvidenceError(message)


def _require_mapping(value: object, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return value


def _validate_identifier(value: object, label: str) -> str:
    if type(value) is not str or not value or value in {".", ".."} or not _IDENTIFIER_RE.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _validate_commit(value: object) -> str:
    if type(value) is not str or not _COMMIT_RE.fullmatch(value):
        _fail("invalid frozen commit")
    return value


def _validate_year(value: object, label: str = "year") -> int:
    if type(value) is not int or not 2015 <= value <= 2100:
        _fail(f"invalid {label}")
    return value


def _prefix(project_id: object, commit: object, run_label: object, algorithm_id: object) -> str:
    project = _validate_identifier(project_id, "project_id")
    frozen_commit = _validate_commit(commit)
    label = _validate_identifier(run_label, "run_label")
    algorithm = _validate_identifier(algorithm_id, "algorithm_id")
    return f"{project}/v2/{frozen_commit}/{label}/{algorithm}"


def build_probe_keys(project_id: object, commit: object, run_label: object, algorithm_id: object) -> dict:
    prefix = _prefix(project_id, commit, run_label, algorithm_id)
    return {
        "string": f"{prefix}/capability/string-1kb.txt",
        "bytes": f"{prefix}/capability/bytes-1kb.bin",
    }


def build_chunk_key(project_id: object, commit: object, run_label: object, algorithm_id: object, year: object) -> str:
    return f"{_prefix(project_id, commit, run_label, algorithm_id)}/evidence/{_validate_year(year)}.json.gz"


def build_manifest_key(project_id: object, commit: object, run_label: object, algorithm_id: object) -> str:
    return f"{_prefix(project_id, commit, run_label, algorithm_id)}/manifest.json"


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise EvidenceError(f"cannot serialize canonical JSON: {error}") from error


def sha256_b64(value: object) -> str:
    if type(value) is not bytes:
        _fail("sha256 input must be bytes")
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def _canonical_b64_decode(value: object, label: str) -> bytes:
    if type(value) is not str:
        _fail(f"{label} invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError(f"{label} invalid") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        _fail(f"{label} invalid")
    return decoded


def _validate_encoded_chunk(value: object, label: str) -> bytes:
    if type(value) is not bytes or not value or len(value) > MAX_CHUNK_BYTES:
        _fail(f"{label} invalid")
    return value


def _parse_date(value: object, label: str) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        _fail(f"invalid {label}")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise EvidenceError(f"invalid {label}") from error


def _finite_number(value: object, label: str, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
    if type(value) is bool or not isinstance(value, (str, int, float, Decimal)):
        _fail(f"{label} must be numeric")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise EvidenceError(f"{label} must be numeric") from error
    if not numeric.is_finite():
        _fail(f"{label} must be finite")
    if positive and numeric <= 0:
        _fail(f"{label} must be positive")
    if nonnegative and numeric < 0:
        _fail(f"{label} must be nonnegative")
    return numeric


def _require_fields(value: Mapping, required: frozenset[str], label: str, *, exact: bool = False) -> None:
    missing = required - set(value)
    if missing:
        _fail(f"{label} missing required fields")
    if exact and set(value) != required:
        _fail(f"{label} has invalid fields")


def _parse_timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not _TIMESTAMP_RE.match(value):
        _fail(f"invalid {label}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"invalid {label}") from error


def _validate_walk_forward(value: object, expected_year: int, current_date: date) -> None:
    walk_forward = _require_mapping(value, "walk_forward")
    _require_fields(walk_forward, _WALK_FORWARD_FIELDS, "walk_forward")
    if type(walk_forward["execution_year"]) is not int or walk_forward["execution_year"] != expected_year:
        _fail("walk_forward execution_year mismatch")
    if type(walk_forward["selection_reason"]) is not str or not walk_forward["selection_reason"]:
        _fail("walk_forward selection_reason invalid")
    parameters = walk_forward["selected_parameters"]
    if parameters is not None and not isinstance(parameters, Mapping):
        _fail("walk_forward selected_parameters invalid")
    start, end = walk_forward["training_start"], walk_forward["training_end"]
    if (start is None) != (end is None):
        _fail("walk_forward training dates must be paired")
    if start is not None:
        training_start = _parse_date(start, "walk_forward training_start")
        training_end = _parse_date(end, "walk_forward training_end")
        if training_start > training_end or training_end >= current_date:
            _fail("walk_forward training chronology invalid")


def _validate_chronology(value: object) -> None:
    chronology = _require_mapping(value, "chronology")
    _require_fields(chronology, frozenset(_CHRONOLOGY_FIELDS), "chronology")
    previous = None
    for field in _CHRONOLOGY_FIELDS:
        timestamp = chronology[field]
        if timestamp is None:
            continue
        parsed = _parse_timestamp(timestamp, f"chronology {field}")
        if previous is not None:
            try:
                ordered = parsed > previous
            except TypeError as error:
                raise EvidenceError("chronology timestamps must use a consistent timezone") from error
            if not ordered:
                _fail("chronology is not strictly increasing")
        previous = parsed


def _validate_gates(value: object) -> None:
    gates = _require_mapping(value, "gates")
    _require_fields(gates, _GATE_FIELDS, "gates")
    if type(gates["data_license"]) is not str or not gates["data_license"]:
        _fail("gates data_license invalid")
    if type(gates["failures"]) is not list:
        _fail("gates failures must be a list")
    for counter in _GATE_COUNTERS:
        if type(gates[counter]) is not int or gates[counter] < 0:
            _fail(f"gates {counter} invalid")


def validate_daily_row(row: object, expected_year: object) -> date:
    year = _validate_year(expected_year, "expected_year")
    daily = _require_mapping(row, "daily row")
    _require_fields(daily, _DAILY_FIELDS, "daily row")
    daily_date = _parse_date(daily["date"], "daily date")
    if daily_date.year != year:
        _fail("daily date year mismatch")
    _finite_number(daily["strategy_equity"], "strategy_equity", positive=True)
    _finite_number(daily["spy_equity"], "spy_equity", positive=True)
    sleeves = _require_mapping(daily["sleeves"], "sleeves")
    if set(sleeves) != set(SLEEVES):
        _fail("sleeves must contain exactly the protocol sleeves")
    for sleeve in SLEEVES:
        values = _require_mapping(sleeves[sleeve], f"sleeve {sleeve}")
        _require_fields(values, _SLEEVE_FIELDS, f"sleeve {sleeve}", exact=True)
        _finite_number(values["daily_pnl"], f"sleeve {sleeve} daily_pnl")
        _finite_number(values["cumulative_pnl"], f"sleeve {sleeve} cumulative_pnl")
        _finite_number(values["fees"], f"sleeve {sleeve} fees", nonnegative=True)
        _finite_number(values["slippage"], f"sleeve {sleeve} slippage", nonnegative=True)
    if type(daily["positions"]) is not list:
        _fail("positions must be a list")
    _finite_number(daily["cash"], "cash")
    for field in ("margin_used", "margin_remaining", "option_max_loss", "total_gross", "alpha_gross"):
        _finite_number(daily[field], field, nonnegative=True)
    _finite_number(daily["beta"], "beta")
    _finite_number(daily["drawdown"], "drawdown")
    risk = _require_mapping(daily["risk_contributions"], "risk_contributions")
    _require_fields(risk, frozenset({"core", "equity", "futures"}), "risk_contributions")
    for sleeve in ("core", "equity", "futures"):
        _finite_number(risk[sleeve], f"risk_contributions {sleeve}")
    if type(daily["drawdown_state"]) is not str or not daily["drawdown_state"]:
        _fail("drawdown_state invalid")
    _validate_walk_forward(daily["walk_forward"], year, daily_date)
    _validate_chronology(daily["chronology"])
    _validate_gates(daily["gates"])
    return daily_date


def validate_chunk(payload: object) -> None:
    chunk = _require_mapping(payload, "chunk")
    required = frozenset({"schema_version", "kind", "run_variant", "year", "synthetic", "daily"})
    _require_fields(chunk, required, "chunk")
    if type(chunk["schema_version"]) is not int or chunk["schema_version"] != SCHEMA_VERSION:
        _fail("chunk schema_version invalid")
    if chunk["kind"] != "annual-evidence":
        _fail("chunk kind invalid")
    if type(chunk["run_variant"]) is not str or chunk["run_variant"] not in RUN_VARIANTS:
        _fail("chunk run_variant invalid")
    year = _validate_year(chunk["year"])
    if type(chunk["synthetic"]) is not bool:
        _fail("chunk synthetic invalid")
    if type(chunk["daily"]) is not list or not chunk["daily"]:
        _fail("chunk daily must be a non-empty list")
    previous = None
    for row in chunk["daily"]:
        row_date = validate_daily_row(row, year)
        if previous is not None and row_date <= previous:
            _fail("chunk daily dates must be strictly increasing")
        if not chunk["synthetic"]:
            walk_forward = row["walk_forward"]
            if walk_forward["training_start"] is None:
                _fail("non-synthetic chunk requires walk_forward training dates")
        previous = row_date
    canonical_json_bytes(chunk)


def encode_chunk(payload: object) -> bytes:
    validate_chunk(payload)
    serialized = canonical_json_bytes(payload)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=9, mtime=0, filename="") as compressed:
        compressed.write(serialized)
    return _validate_encoded_chunk(output.getvalue(), "encoded chunk")


def encode_string_transport(value: object) -> str:
    encoded = _validate_encoded_chunk(value, "string transport input")
    return _TRANSPORT_PREFIX + base64.b64encode(encoded).decode("ascii")


def decode_transport(value: object) -> bytes:
    if type(value) is bytes:
        return _validate_encoded_chunk(value, "evidence transport")
    if type(value) is not str or not value.startswith(_TRANSPORT_PREFIX):
        _fail("invalid evidence transport")
    encoded_text = value[len(_TRANSPORT_PREFIX):]
    if len(encoded_text) > _MAX_TRANSPORT_B64_CHARS:
        _fail("invalid base64-gzip transport")
    decoded = _canonical_b64_decode(encoded_text, "base64-gzip transport")
    return _validate_encoded_chunk(decoded, "evidence transport")


def _decode_canonical_chunk(encoded: bytes) -> dict:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(encoded), mode="rb") as compressed:
            raw = compressed.read(_MAX_RAW_CHUNK_BYTES + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise EvidenceError(f"invalid gzip chunk: {error}") from error
    if len(raw) > _MAX_RAW_CHUNK_BYTES:
        _fail("gzip chunk exceeds raw size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid gzip JSON chunk: {error}") from error
    if type(payload) is not dict:
        _fail("gzip chunk payload must be an object")
    return payload


def chunk_descriptor(year: object, key: object, encoded: object, daily: object) -> dict:
    chunk_year = _validate_year(year)
    if type(key) is not str or not key:
        _fail("chunk descriptor key invalid")
    compressed = _validate_encoded_chunk(encoded, "chunk descriptor encoded bytes")
    if type(daily) is not list or not daily:
        _fail("chunk descriptor daily must be a non-empty list")
    payload = _decode_canonical_chunk(compressed)
    validate_chunk(payload)
    if payload["year"] != chunk_year or payload["daily"] != daily:
        _fail("chunk descriptor does not match encoded payload")
    if encode_chunk(payload) != compressed:
        _fail("chunk descriptor encoded payload is not canonical")
    dates = [validate_daily_row(row, chunk_year) for row in payload["daily"]]
    if any(right <= left for left, right in zip(dates, dates[1:])):
        _fail("chunk descriptor daily dates must be strictly increasing")
    return {
        "year": chunk_year,
        "run_variant": payload["run_variant"],
        "key": key,
        "encoded_bytes": len(compressed),
        "sha256": sha256_b64(compressed),
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "rows": len(daily),
    }


def _validate_sha256(value: object) -> None:
    decoded = _canonical_b64_decode(value, "descriptor sha256")
    if len(decoded) != 32:
        _fail("descriptor sha256 invalid")


def _validate_descriptor(descriptor: object, project_id: str, commit: str, run_label: str, algorithm_id: str, run_variant: str) -> dict:
    item = _require_mapping(descriptor, "chunk descriptor")
    _require_fields(item, _DESCRIPTOR_FIELDS, "chunk descriptor", exact=True)
    year = _validate_year(item["year"], "descriptor year")
    if type(item["run_variant"]) is not str or item["run_variant"] != run_variant:
        _fail("descriptor run_variant does not match manifest")
    expected_key = build_chunk_key(project_id, commit, run_label, algorithm_id, year)
    if type(item["key"]) is not str or item["key"] != expected_key:
        _fail("descriptor key does not match manifest identity")
    if type(item["encoded_bytes"]) is not int or not 0 < item["encoded_bytes"] <= MAX_CHUNK_BYTES:
        _fail("descriptor encoded_bytes invalid")
    _validate_sha256(item["sha256"])
    first = _parse_date(item["first_date"], "descriptor first_date")
    last = _parse_date(item["last_date"], "descriptor last_date")
    if first.year != year or last.year != year or first > last:
        _fail("descriptor date range invalid")
    if type(item["rows"]) is not int or item["rows"] <= 0:
        _fail("descriptor rows invalid")
    return dict(item)


def build_manifest(project_id: object, commit: object, run_label: object, algorithm_id: object, run_variant: object, transport: object, chunks: object) -> dict:
    project = _validate_identifier(project_id, "project_id")
    frozen_commit = _validate_commit(commit)
    label = _validate_identifier(run_label, "run_label")
    algorithm = _validate_identifier(algorithm_id, "algorithm_id")
    if type(run_variant) is not str or run_variant not in RUN_VARIANTS:
        _fail("manifest run_variant invalid")
    if type(transport) is not str or transport not in {"bytes", "base64-gzip-string"}:
        _fail("manifest transport invalid")
    if type(chunks) is not list or not chunks:
        _fail("manifest chunks must be a non-empty list")
    validated = [
        _validate_descriptor(item, project, frozen_commit, label, algorithm, run_variant)
        for item in chunks
    ]
    years = [item["year"] for item in validated]
    keys = [item["key"] for item in validated]
    if len(years) != len(set(years)) or len(keys) != len(set(keys)):
        _fail("manifest chunks must have unique years and keys")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "evidence-manifest",
        "project_id": project,
        "version": "v2",
        "frozen_commit": frozen_commit,
        "run_label": label,
        "algorithm_id": algorithm,
        "run_variant": run_variant,
        "transport": transport,
        "chunks": sorted(validated, key=lambda item: item["year"]),
    }
