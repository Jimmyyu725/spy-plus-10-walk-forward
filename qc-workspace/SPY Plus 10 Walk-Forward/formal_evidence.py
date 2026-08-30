from __future__ import annotations

import gzip
import json
import re
from datetime import date
from decimal import Decimal as PythonDecimal, InvalidOperation


EVIDENCE_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")


class FormalEvidenceError(RuntimeError):
    """Raised when formal evidence is incomplete or internally inconsistent."""


def build_object_store_key(project_id, run_label: str, algorithm_id: str) -> str:
    project = str(project_id)
    algorithm = str(algorithm_id)
    if (
        run_label not in {"base", "double"}
        or not _IDENTIFIER.fullmatch(project)
        or not _IDENTIFIER.fullmatch(algorithm)
    ):
        raise FormalEvidenceError("object store identity is invalid")
    return (
        f"{project}/frozen-evaluation-v{EVIDENCE_SCHEMA_VERSION}/"
        f"{run_label}-{algorithm}.json.gz"
    )


def _positive_decimal(value, label: str) -> PythonDecimal:
    try:
        result = PythonDecimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise FormalEvidenceError(f"{label} must be numeric") from error
    if not result.is_finite() or result <= 0:
        raise FormalEvidenceError(f"{label} must be positive")
    return result


def _validate_payload(payload: dict) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise FormalEvidenceError("evidence schema version is invalid")
    run = payload.get("run")
    if not isinstance(run, dict):
        raise FormalEvidenceError("run identity is missing")
    required_run = {
        "project_id",
        "algorithm_id",
        "run_label",
        "slippage_multiplier",
        "evaluation_mode",
        "start_date",
        "trading_start_date",
        "end_date",
        "timezone",
    }
    if not required_run.issubset(run):
        raise FormalEvidenceError("run identity is incomplete")
    build_object_store_key(
        run["project_id"],
        run["run_label"],
        run["algorithm_id"],
    )
    expected_slippage = 1.0 if run["run_label"] == "base" else 2.0
    if (
        run["evaluation_mode"] != "frozen-evaluation"
        or float(run["slippage_multiplier"]) != expected_slippage
        or run["start_date"] != "2012-01-01"
        or run["trading_start_date"] != "2015-01-02"
        or run["end_date"] != "2026-08-28"
        or run["timezone"] != "America/New_York"
    ):
        raise FormalEvidenceError("run parameters do not match the frozen protocol")
    daily = payload.get("daily")
    if not isinstance(daily, list) or not daily:
        raise FormalEvidenceError("daily evidence is missing")
    last_date = None
    for row in daily:
        if not isinstance(row, dict):
            raise FormalEvidenceError("daily evidence row is invalid")
        try:
            current = date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError) as error:
            raise FormalEvidenceError("daily date is invalid") from error
        if last_date is not None and current <= last_date:
            raise FormalEvidenceError("daily dates must be strictly increasing")
        _positive_decimal(row.get("strategy_equity"), "strategy equity")
        _positive_decimal(row.get("spy_equity"), "SPY equity")
        last_date = current
    if not isinstance(payload.get("audit_samples"), list):
        raise FormalEvidenceError("audit samples are invalid")
    if not isinstance(payload.get("gate_failures"), list):
        raise FormalEvidenceError("gate failures are invalid")
    if not isinstance(payload.get("licenses"), dict):
        raise FormalEvidenceError("license evidence is invalid")


def encode_evidence(payload: dict) -> bytes:
    _validate_payload(payload)
    try:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FormalEvidenceError("evidence is not JSON serializable") from error
    return gzip.compress(raw, compresslevel=9, mtime=0)


def formal_overall_status(
    data_audit_status: str,
    safety_status: str,
    annual_status: str,
) -> str:
    statuses = (data_audit_status, safety_status, annual_status)
    if any(status not in {"PASS", "FAIL"} for status in statuses):
        return "UNVERIFIED"
    if data_audit_status != "PASS":
        return "UNVERIFIED"
    if safety_status == "FAIL" or annual_status == "FAIL":
        return "FAIL"
    return "PASS"
