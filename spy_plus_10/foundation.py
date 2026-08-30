from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_NAME = "SPY Plus 10 Walk-Forward"
TOKEN_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.IGNORECASE)
TEXT_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".txt", ".yml", ".yaml"}


class FoundationValidationError(RuntimeError):
    """Raised when the cloud foundation is incomplete or unsafe."""


@dataclass(frozen=True)
class FoundationStatus:
    project_name: str
    mode: str
    formal_evaluation: bool


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FoundationValidationError(f"missing required file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundationValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FoundationValidationError(f"expected JSON object: {path}")
    return value


def _scan_for_credentials(root: Path) -> None:
    excluded_parts = {".git", "__pycache__", "data", "storage"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if TOKEN_PATTERN.search(text):
            raise FoundationValidationError(f"credential-like token found: {path}")


def validate_foundation(root: Path) -> FoundationStatus:
    root = root.resolve()
    workspace = root / "qc-workspace"
    project = workspace / PROJECT_NAME
    _read_json(workspace / "lean.json")
    _read_json(project / "config.json")
    manifest = _read_json(project / "project-manifest.json")
    main_path = project / "main.py"
    if not main_path.is_file():
        raise FoundationValidationError("missing required file: main.py")
    main_source = main_path.read_text(encoding="utf-8")

    expected_manifests = {
        "foundation-smoke": {
            "benchmark": "SPY",
            "end_date": "2015-01-09",
            "formal_evaluation": False,
            "initial_cash": 1_000_000,
            "language": "Python",
            "live_trading": False,
            "mode": "foundation-smoke",
            "name": PROJECT_NAME,
            "start_date": "2015-01-02",
        },
        "portfolio-integration-smoke": {
            "benchmark": "SPY",
            "end_date": "2015-03-31",
            "formal_evaluation": False,
            "initial_cash": 1_000_000,
            "language": "Python",
            "live_trading": False,
            "mode": "portfolio-integration-smoke",
            "name": PROJECT_NAME,
            "start_date": "2012-01-01",
            "trading_start_date": "2013-01-02",
        },
        "frozen-evaluation": {
            "benchmark": "SPY",
            "end_date": "2026-08-28",
            "formal_evaluation": True,
            "initial_cash": 1_000_000,
            "language": "Python",
            "live_trading": False,
            "mode": "frozen-evaluation",
            "name": PROJECT_NAME,
            "start_date": "2012-01-01",
            "trading_start_date": "2015-01-02",
        },
    }
    expected_manifest = expected_manifests.get(manifest.get("mode"))
    if expected_manifest is None:
        raise FoundationValidationError(f"unsupported project mode: {manifest.get('mode')}")
    if manifest != expected_manifest:
        differing = sorted(set(manifest.items()) ^ set(expected_manifest.items()))
        raise FoundationValidationError(f"project manifest mismatch: {differing}")
    if manifest["live_trading"]:
        raise FoundationValidationError("live_trading must remain false")

    required_markers_by_mode = {
        "foundation-smoke": (
            "class SpyPlusTenWalkForward(QCAlgorithm)",
            "self.set_start_date(2015, 1, 2)",
            "self.set_end_date(2015, 1, 9)",
            "self.set_cash(1_000_000)",
            'self.add_equity("SPY", Resolution.DAILY)',
            "self.set_benchmark(self.spy)",
        ),
        "portfolio-integration-smoke": (
            "class SpyPlusTenWalkForward(QCAlgorithm)",
            "self.set_start_date(2012, 1, 1)",
            "self.set_end_date(2015, 3, 31)",
            "self.set_cash(1_000_000)",
            "self.set_benchmark(self._spy)",
            "BrokerageName.QUANT_CONNECT_BROKERAGE",
            'mode != "integration-smoke"',
        ),
        "frozen-evaluation": (
            "class SpyPlusTenWalkForward(QCAlgorithm)",
            "self.set_start_date(2012, 1, 1)",
            "self.set_end_date(2026, 8, 28)",
            "self.set_cash(1_000_000)",
            "self.set_benchmark(self._spy)",
            "BrokerageName.QUANT_CONNECT_BROKERAGE",
            'mode != "frozen-evaluation"',
            'run_label not in {"base", "double"}',
            "self._trading_start = date(2015, 1, 2)",
        ),
    }
    required_markers = required_markers_by_mode[manifest["mode"]]
    missing = [marker for marker in required_markers if marker not in main_source]
    if missing:
        raise FoundationValidationError(f"main.py missing markers: {missing}")
    if manifest["mode"] == "foundation-smoke":
        forbidden_markers = (
            "set_brokerage_model",
            "set_live_mode",
            "add_option",
            "add_future",
        )
        present = [marker for marker in forbidden_markers if marker in main_source]
        if present:
            raise FoundationValidationError(
                f"foundation smoke contains forbidden markers: {present}"
            )

    _scan_for_credentials(root)
    return FoundationStatus(
        project_name=manifest["name"],
        mode=manifest["mode"],
        formal_evaluation=manifest["formal_evaluation"],
    )
