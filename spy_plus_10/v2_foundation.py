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


class SpyPlusTenV2EvidenceCapability(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 5)
        self.set_cash(1_000_000)
        self._git_commit = self.get_parameter("v2_git_commit")
        self._run_label = self.get_parameter("evidence_run_label")
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
