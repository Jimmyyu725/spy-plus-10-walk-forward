from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


INITIAL_EQUITY = Decimal("1000000")
HURDLE = Decimal("0.10")
RECONCILIATION_TOLERANCE = Decimal("0.0001")


def _decimal(value, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{label} is not numeric") from error
    if not result.is_finite():
        raise ValueError(f"{label} is not finite")
    return result


def _parse_cloud_row(value: str) -> dict:
    pieces = str(value).split(",")
    if len(pieces) != 5:
        raise ValueError("cloud annual row has an invalid shape")
    parsed = {"period": pieces[0]}
    for piece in pieces[1:]:
        key, separator, raw = piece.partition("=")
        if not separator:
            raise ValueError("cloud annual row field is invalid")
        parsed[key] = raw
    return parsed


def _expected_run(payload: dict, errors: list[str]) -> None:
    if payload.get("schema_version") != 1:
        errors.append("SCHEMA_VERSION")
    run = payload.get("run")
    if not isinstance(run, dict):
        errors.append("RUN_IDENTITY")
        return
    expected = {
        "evaluation_mode": "frozen-evaluation",
        "start_date": "2012-01-01",
        "trading_start_date": "2015-01-02",
        "end_date": "2026-08-28",
        "timezone": "America/New_York",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        errors.append("FROZEN_PARAMETERS")
    label = run.get("run_label")
    expected_slippage = 1.0 if label == "base" else 2.0 if label == "double" else None
    try:
        slippage = float(run.get("slippage_multiplier"))
    except (TypeError, ValueError):
        slippage = None
    if expected_slippage is None or slippage != expected_slippage:
        errors.append("RUN_LABEL_SLIPPAGE_PAIR")
    if not str(run.get("project_id", "")) or not str(run.get("algorithm_id", "")):
        errors.append("RUN_IDENTITY")


def _recompute_daily(payload: dict, errors: list[str]):
    daily = payload.get("daily")
    if not isinstance(daily, list) or not daily:
        errors.append("DAILY_EVIDENCE_MISSING")
        return [], [], Decimal("0")
    parsed = []
    for raw in daily:
        try:
            day = date.fromisoformat(raw["date"])
            strategy = _decimal(raw["strategy_equity"], "strategy equity")
            spy = _decimal(raw["spy_equity"], "SPY equity")
        except (KeyError, TypeError, ValueError):
            errors.append("DAILY_ROW_INVALID")
            return [], [], Decimal("0")
        if strategy <= 0 or spy <= 0:
            errors.append("NON_POSITIVE_EQUITY")
        if parsed and day <= parsed[-1][0]:
            errors.append("DAILY_DATES_NOT_STRICT")
        parsed.append((day, strategy, spy))
    if parsed and (parsed[0][0] != date(2015, 1, 2) or parsed[-1][0] != date(2026, 8, 28)):
        errors.append("FORMAL_DATE_COVERAGE")
    years = sorted({row[0].year for row in parsed})
    if years != list(range(2015, 2027)):
        errors.append("CALENDAR_YEAR_COVERAGE")

    annual_rows = []
    strategy_prior = spy_prior = INITIAL_EQUITY
    for year in years:
        year_rows = [row for row in parsed if row[0].year == year]
        day, strategy, spy = year_rows[-1]
        strategy_return = strategy / strategy_prior - 1
        spy_return = spy / spy_prior - 1
        hurdle = spy_return + HURDLE
        status = "PASS" if strategy_return >= hurdle else "FAIL"
        annual_rows.append(
            {
                "year": year,
                "period": "PARTIAL_YEAR" if year == 2026 else "FULL_YEAR",
                "start_date": year_rows[0][0].isoformat(),
                "end_date": day.isoformat(),
                "strategy_return": str(strategy_return),
                "spy_return": str(spy_return),
                "excess_return": str(strategy_return - spy_return),
                "hurdle_return": str(hurdle),
                "status": status,
            }
        )
        strategy_prior, spy_prior = strategy, spy

    peak = Decimal("0")
    maximum_drawdown = Decimal("0")
    for _, strategy, _ in parsed:
        peak = max(peak, strategy)
        maximum_drawdown = max(maximum_drawdown, Decimal("1") - strategy / peak)
    return parsed, annual_rows, maximum_drawdown


def _verify_audits(payload: dict, errors: list[str]) -> None:
    samples = payload.get("audit_samples")
    if not isinstance(samples, list) or len(samples) < 10:
        errors.append("AUDIT_SAMPLE_COUNT")
        return
    prior_fill = None
    for index, sample in enumerate(samples, start=1):
        try:
            times = [
                datetime.fromisoformat(sample[field])
                for field in (
                    "data_cutoff",
                    "signal_time",
                    "order_time",
                    "fill_time",
                )
            ]
        except (KeyError, TypeError, ValueError):
            errors.append("AUDIT_TIMESTAMP_INVALID")
            return
        if sample.get("sequence") != index or not sample.get("module"):
            errors.append("AUDIT_SEQUENCE")
        if any(moment.tzinfo is None for moment in times):
            errors.append("AUDIT_TIMEZONE")
        if not times[0] < times[1] < times[2] < times[3]:
            errors.append("AUDIT_CAUSALITY")
        if prior_fill is not None and times[3] < prior_fill:
            errors.append("AUDIT_TIME_REVERSED")
        prior_fill = times[3]


def _reconcile_cloud(
    annual_rows: list[dict],
    maximum_drawdown: Decimal,
    statistics: dict,
    errors: list[str],
    tolerance: Decimal,
) -> None:
    for row in annual_rows:
        key = f"FORMAL_YEAR_{row['year']}"
        try:
            cloud = _parse_cloud_row(statistics[key])
            if cloud["period"] != row["period"] or cloud["status"] != row["status"]:
                errors.append(f"ANNUAL_RECONCILIATION_{row['year']}")
                continue
            for cloud_key, local_key in (
                ("strategy", "strategy_return"),
                ("spy", "spy_return"),
                ("excess", "excess_return"),
            ):
                difference = abs(
                    _decimal(cloud[cloud_key], cloud_key)
                    - _decimal(row[local_key], local_key)
                )
                if difference > tolerance:
                    errors.append(f"ANNUAL_RECONCILIATION_{row['year']}")
                    break
        except (KeyError, ValueError):
            errors.append(f"ANNUAL_RECONCILIATION_{row['year']}")
    try:
        cloud_drawdown = _decimal(
            statistics["PORTFOLIO_MAX_DRAWDOWN"],
            "cloud maximum drawdown",
        )
        if abs(cloud_drawdown - maximum_drawdown) > tolerance:
            errors.append("DRAWDOWN_RECONCILIATION")
    except (KeyError, ValueError):
        errors.append("DRAWDOWN_RECONCILIATION")


def verify_frozen_evidence(
    payload: dict,
    cloud_statistics: dict,
    *,
    tolerance: Decimal = RECONCILIATION_TOLERANCE,
) -> dict:
    errors: list[str] = []
    _expected_run(payload, errors)
    _, annual_rows, maximum_drawdown = _recompute_daily(payload, errors)
    _verify_audits(payload, errors)
    if payload.get("licenses") != {"equity": "AVAILABLE", "option": "AVAILABLE"}:
        errors.append("LICENSE_STATUS")
    gate_failures = payload.get("gate_failures")
    if not isinstance(gate_failures, list):
        errors.append("GATE_FAILURES_INVALID")
        gate_failures = []
    _reconcile_cloud(
        annual_rows,
        maximum_drawdown,
        cloud_statistics,
        errors,
        tolerance,
    )
    if cloud_statistics.get("FORMAL_DATA_AUDIT_STATUS") != "PASS":
        errors.append("CLOUD_DATA_AUDIT_STATUS")
    if cloud_statistics.get("FORMAL_EVIDENCE_SAVE_STATUS") != "PASS":
        errors.append("CLOUD_EVIDENCE_SAVE_STATUS")

    annual_status = (
        "PASS"
        if annual_rows and all(row["status"] == "PASS" for row in annual_rows)
        else "FAIL"
    )
    if cloud_statistics.get("FORMAL_ANNUAL_GATE_STATUS") != annual_status:
        errors.append("CLOUD_ANNUAL_STATUS")
    safety_failed = bool(gate_failures) or cloud_statistics.get(
        "FORMAL_SAFETY_GATE_STATUS"
    ) != "PASS"
    expected_cloud_overall = "FAIL" if safety_failed or annual_status == "FAIL" else "PASS"
    if cloud_statistics.get("FORMAL_OVERALL_STATUS") != expected_cloud_overall:
        errors.append("CLOUD_OVERALL_STATUS")

    if errors:
        status = "UNVERIFIED"
    elif safety_failed or annual_status == "FAIL":
        status = "FAIL"
    else:
        status = "PASS"
    return {
        "status": status,
        "run_label": payload.get("run", {}).get("run_label"),
        "annual_rows": annual_rows,
        "failed_years": [
            row["year"] for row in annual_rows if row["status"] == "FAIL"
        ],
        "maximum_drawdown": str(maximum_drawdown),
        "audit_sample_count": len(payload.get("audit_samples", []))
        if isinstance(payload.get("audit_samples"), list)
        else 0,
        "reconciliation_tolerance": str(tolerance),
        "errors": sorted(set(errors)),
        "gate_failures": gate_failures,
    }


def extract_cloud_statistics(backtest_response: dict) -> dict:
    backtest = backtest_response.get("backtest", backtest_response)
    if not isinstance(backtest, dict):
        return {}
    for key in ("statistics", "runtimeStatistics", "runtime_statistics"):
        value = backtest.get(key)
        if isinstance(value, dict):
            return value
    return {}
