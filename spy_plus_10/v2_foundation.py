"""Validate the isolated v2 evidence-capability project boundary."""

import ast
import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_NAME = "SPY Plus 10 Walk-Forward v2"
EXPECTED_MANIFEST = {
    "benchmark": "NONE",
    "end_date": "2015-01-05",
    "formal_evaluation": False,
    "initial_cash": 1000000,
    "language": "Python",
    "live_trading": False,
    "mode": "evidence-capability-smoke",
    "name": "SPY Plus 10 Walk-Forward v2",
    "start_date": "2015-01-02",
}
FORBIDDEN_SOURCE = (
    "add_equity(",
    "add_future(",
    "add_option(",
    "market_order(",
    "set_holdings(",
    "set_brokerage_model(",
    "set_live_mode(",
)
EXPECTED_MAIN_SOURCE = """from AlgorithmImports import *
import json

from evidence import (
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


class BytesCapabilityError(RuntimeError):
    \"\"\"Raised only for expected bytes Object Store capability failures.\"\"\"


class SpyPlusTenV2EvidenceCapability(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 5)
        self.set_cash(1_000_000)
        self._git_commit = self.get_parameter("v2_git_commit")
        self._run_label = self.get_parameter("evidence_run_label")
        self._status = {
            "string": "UNVERIFIED",
            "bytes": "UNVERIFIED",
            "chunk": "UNVERIFIED",
            "manifest": "UNVERIFIED",
        }
        self._on_end_finalized = False

    def _save_unique_string(self, key: str, value: str) -> None:
        if self.object_store.contains_key(key):
            raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")
        if not self.object_store.save(key, value):
            raise RuntimeError(f"OBJECT_STORE_STRING_SAVE_FAILED:{key}")
        round_trip = self.object_store.read(key)
        if (
            round_trip != value
            or sha256_b64(round_trip.encode("utf-8"))
            != sha256_b64(value.encode("utf-8"))
        ):
            raise RuntimeError(f"OBJECT_STORE_STRING_ROUND_TRIP_FAILED:{key}")

    def _save_unique_bytes(self, key: str, value: bytes) -> None:
        if self.object_store.contains_key(key):
            raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")
        try:
            saved = self.object_store.save_bytes(key, value)
        except NotImplementedError as error:
            raise BytesCapabilityError(f"OBJECT_STORE_BYTES_UNSUPPORTED:{key}") from error
        if not saved:
            raise BytesCapabilityError(f"OBJECT_STORE_BYTES_SAVE_FAILED:{key}")
        try:
            round_trip = bytes(self.object_store.read_bytes(key))
        except NotImplementedError as error:
            raise BytesCapabilityError(f"OBJECT_STORE_BYTES_UNSUPPORTED:{key}") from error
        if round_trip != value or sha256_b64(round_trip) != sha256_b64(value):
            raise BytesCapabilityError(f"OBJECT_STORE_BYTES_ROUND_TRIP_FAILED:{key}")

    def _synthetic_row(self, day: str) -> dict:
        sleeves = {
            name: {
                "daily_pnl": "0",
                "cumulative_pnl": "0",
                "fees": "0",
                "slippage": "0",
            }
            for name in ("core", "equity", "futures", "defensive_option")
        }
        return {
            "date": day,
            "strategy_equity": "1000000.00",
            "spy_equity": "1000000.00",
            "sleeves": sleeves,
            "positions": [],
            "cash": "1000000.00",
            "margin_used": "0",
            "margin_remaining": "1000000.00",
            "option_max_loss": "0",
            "total_gross": "0",
            "alpha_gross": "0",
            "beta": "0",
            "risk_contributions": {"core": "0", "equity": "0", "futures": "0"},
            "drawdown": "0",
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

    def _run_capability_smoke(self) -> None:
        probes = build_probe_keys(
            self._project, self._git_commit, self._run_label, self._algorithm
        )
        chunk_key = build_chunk_key(
            self._project, self._git_commit, self._run_label, self._algorithm, 2015
        )
        manifest_key = build_manifest_key(
            self._project, self._git_commit, self._run_label, self._algorithm
        )
        string_value = "S" * 1024
        bytes_value = bytes(index % 251 for index in range(1024))
        daily = [
            self._synthetic_row("2015-01-02"),
            self._synthetic_row("2015-01-05"),
        ]
        payload = {
            "schema_version": 2,
            "kind": "annual-evidence",
            "run_variant": "full",
            "year": 2015,
            "synthetic": True,
            "daily": daily,
        }
        encoded = encode_chunk(payload)
        descriptor = chunk_descriptor(2015, chunk_key, encoded, daily)
        manifest = build_manifest(
            self._project,
            self._git_commit,
            self._run_label,
            self._algorithm,
            "full",
            "bytes",
            [descriptor],
        )
        fallback_manifest = build_manifest(
            self._project,
            self._git_commit,
            self._run_label,
            self._algorithm,
            "full",
            "base64-gzip-string",
            [descriptor],
        )
        manifest_texts = {
            "bytes": canonical_json_bytes(manifest).decode("utf-8"),
            "base64-gzip-string": canonical_json_bytes(fallback_manifest).decode("utf-8"),
        }
        all_keys = (*probes.values(), chunk_key, manifest_key)
        for key in all_keys:
            if self.object_store.contains_key(key):
                raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")

        self._save_unique_string(probes["string"], string_value)
        self._status["string"] = "PASS"
        transport = "bytes"
        try:
            self._save_unique_bytes(probes["bytes"], bytes_value)
            self._status["bytes"] = "PASS"
        except BytesCapabilityError as error:
            self._status["bytes"] = "FAIL"
            self.debug(f"BYTES_PROBE_FAILED:{type(error).__name__}")
            transport = "base64-gzip-string"

        if transport == "bytes":
            self._save_unique_bytes(chunk_key, encoded)
        else:
            self._save_unique_string(chunk_key, encode_string_transport(encoded))
        self._status["chunk"] = "PASS"
        self._save_unique_string(manifest_key, manifest_texts[transport])
        self._status["manifest"] = "PASS"
        self.set_runtime_statistic(
            "V2_EVIDENCE_PREFIX", chunk_key.rsplit("/evidence/", 1)[0]
        )
        self.set_runtime_statistic("V2_MANIFEST_KEY", manifest_key)
        self.set_runtime_statistic("V2_STRING_KEY", probes["string"])
        self.set_runtime_statistic("V2_BYTES_KEY", probes["bytes"])
        self.set_runtime_statistic(
            "V2_STRING_SHA256", sha256_b64(string_value.encode("utf-8"))
        )
        self.set_runtime_statistic("V2_BYTES_SHA256", sha256_b64(bytes_value))
        self.set_runtime_statistic("V2_TRANSPORT", transport)

    def on_end_of_algorithm(self) -> None:
        if self._on_end_finalized:
            raise RuntimeError("CAPABILITY_SMOKE_ALREADY_FINALIZED")
        self._on_end_finalized = True
        try:
            self._algorithm = str(self.algorithm_id)
            self._project = str(self.project_id)
            self._run_capability_smoke()
        finally:
            required = (
                self._status["string"],
                self._status["chunk"],
                self._status["manifest"],
            )
            overall = "UNVERIFIED"
            if all(value == "PASS" for value in required):
                overall = (
                    "PASS"
                    if self._status["bytes"] == "PASS"
                    else "PASS_WITH_STRING_FALLBACK"
                )
            self.set_runtime_statistic("V2_CAPABILITY_STATUS", overall)
            for key, value in self._status.items():
                self.set_runtime_statistic(f"V2_{key.upper()}_STATUS", value)
"""
EXPECTED_MAIN_AST = ast.dump(ast.parse(EXPECTED_MAIN_SOURCE), include_attributes=False)
EXPECTED_CONFIG = {
    "algorithm-language": "Python",
    "parameters": {},
    "description": "",
}
OPTIONAL_CONFIG_KEYS = frozenset({"cloud-id", "organization-id"})


class V2FoundationError(RuntimeError):
    """Raised when the v2 evidence project boundary is not intact."""


class _DuplicateJsonKeyError(ValueError):
    pass


@dataclass(frozen=True)
class V2FoundationStatus:
    project_name: str
    mode: str
    live_trading: bool


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as error:
        raise V2FoundationError(f"cannot read JSON {path}: {error}") from error

    if type(value) is not dict:
        raise V2FoundationError(f"JSON object required: {path}")
    return value


def _has_exact_values(actual: dict, expected: dict) -> bool:
    return actual.keys() == expected.keys() and all(
        type(actual[key]) is type(expected[key]) and actual[key] == expected[key]
        for key in expected
    )


def _validate_config(config: dict, path: Path) -> None:
    allowed_keys = set(EXPECTED_CONFIG) | OPTIONAL_CONFIG_KEYS
    if set(config) - allowed_keys:
        raise V2FoundationError(f"config mismatch: unknown key in {path}")
    for key, expected in EXPECTED_CONFIG.items():
        if key not in config or type(config[key]) is not type(expected) or config[key] != expected:
            raise V2FoundationError(f"config mismatch: {key} in {path}")

    has_cloud_id = "cloud-id" in config
    has_organization_id = "organization-id" in config
    if has_cloud_id != has_organization_id:
        raise V2FoundationError(f"config mismatch: cloud fields must be paired in {path}")
    if has_cloud_id and (type(config["cloud-id"]) is not int or config["cloud-id"] <= 0):
        raise V2FoundationError(f"config mismatch: cloud-id in {path}")
    if has_organization_id and (
        type(config["organization-id"]) is not str or not config["organization-id"]
    ):
        raise V2FoundationError(f"config mismatch: organization-id in {path}")


def _validate_main(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise V2FoundationError(f"cannot read main source {path}: {error}") from error
    try:
        actual_ast = ast.dump(ast.parse(source, filename=str(path)), include_attributes=False)
    except (SyntaxError, ValueError) as error:
        raise V2FoundationError(f"invalid Python source {path}: {error}") from error

    if actual_ast != EXPECTED_MAIN_AST:
        raise V2FoundationError(f"main source AST mismatch: {path}")


def validate_v2_foundation(root: Path | str) -> V2FoundationStatus:
    repository_root = Path(root).resolve()
    workspace = repository_root / "qc-workspace"
    project = workspace / PROJECT_NAME

    _read_object(workspace / "lean.json")
    config_path = project / "config.json"
    _validate_config(_read_object(config_path), config_path)
    manifest_path = project / "project-manifest.json"
    manifest = _read_object(manifest_path)
    if not _has_exact_values(manifest, EXPECTED_MANIFEST):
        raise V2FoundationError(f"manifest mismatch: {manifest_path}")

    _validate_main(project / "main.py")
    return V2FoundationStatus(PROJECT_NAME, manifest["mode"], False)
