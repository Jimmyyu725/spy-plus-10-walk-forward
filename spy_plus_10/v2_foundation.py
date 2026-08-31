"""Validate the isolated v2 evidence-capability project boundary."""

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
REQUIRED_SOURCE = (
    "class SpyPlusTenV2EvidenceCapability(QCAlgorithm):",
    "self.set_start_date(2015, 1, 2)",
    "self.set_end_date(2015, 1, 5)",
    "self.set_cash(1_000_000)",
    'self.get_parameter("v2_git_commit")',
    'self.get_parameter("evidence_run_label")',
)


class V2FoundationError(RuntimeError):
    """Raised when the v2 evidence project boundary is not intact."""


@dataclass(frozen=True)
class V2FoundationStatus:
    project_name: str
    mode: str
    live_trading: bool


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise V2FoundationError(f"missing required file: {path}") from error
    except json.JSONDecodeError as error:
        raise V2FoundationError(f"invalid JSON: {path}") from error

    if not isinstance(value, dict):
        raise V2FoundationError(f"JSON object required: {path}")
    return value


def validate_v2_foundation(root: Path | str) -> V2FoundationStatus:
    repository_root = Path(root).resolve()
    workspace = repository_root / "qc-workspace"
    project = workspace / PROJECT_NAME

    _read_object(workspace / "lean.json")
    _read_object(project / "config.json")
    manifest = _read_object(project / "project-manifest.json")
    if manifest != EXPECTED_MANIFEST:
        raise V2FoundationError("manifest mismatch")

    main_path = project / "main.py"
    try:
        source = main_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise V2FoundationError(f"missing required file: {main_path}") from error

    for marker in REQUIRED_SOURCE:
        if marker not in source:
            raise V2FoundationError(f"missing required source marker: {marker}")
    lower_source = source.lower()
    for marker in FORBIDDEN_SOURCE:
        if marker in lower_source:
            raise V2FoundationError(f"forbidden source marker: {marker}")

    return V2FoundationStatus(PROJECT_NAME, manifest["mode"], False)
