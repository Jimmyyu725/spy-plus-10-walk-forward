from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as PythonDecimal


def _d(value) -> PythonDecimal:
    return value if isinstance(value, PythonDecimal) else PythonDecimal(str(value))


class MetricsError(RuntimeError):
    """Raised when aligned equity evidence is insufficient or inconsistent."""


@dataclass(frozen=True)
class EquityPoint:
    as_of: date
    value: PythonDecimal

    def __init__(self, as_of: date, value):
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "value", _d(value))


@dataclass(frozen=True)
class AnnualGateRow:
    year: int
    period: str
    start_date: date
    end_date: date
    strategy_return: PythonDecimal
    spy_return: PythonDecimal
    excess_return: PythonDecimal
    hurdle_return: PythonDecimal
    status: str


@dataclass(frozen=True)
class AnnualGateResult:
    rows: tuple[AnnualGateRow, ...]
    overall_status: str


def _validated_map(points: list[EquityPoint], label: str) -> dict[date, PythonDecimal]:
    if not points:
        raise MetricsError(f"missing {label} equity")
    if any(left.as_of >= right.as_of for left, right in zip(points, points[1:])):
        raise MetricsError(f"{label} dates must be strictly increasing")
    if any(point.value <= 0 for point in points):
        raise MetricsError(f"{label} equity must be positive")
    return {point.as_of: point.value for point in points}


def evaluate_annual_gates(
    strategy: list[EquityPoint],
    spy: list[EquityPoint],
    *,
    initial_value,
    as_of: date,
) -> AnnualGateResult:
    strategy_map = _validated_map(strategy, "strategy")
    spy_map = _validated_map(spy, "SPY")
    common_dates = sorted(set(strategy_map) & set(spy_map))
    if not common_dates:
        raise MetricsError("no common valuation dates")
    initial = _d(initial_value)
    if initial <= 0:
        raise MetricsError("initial_value must be positive")
    years = sorted({day.year for day in common_dates})
    if years != list(range(years[0], years[-1] + 1)):
        raise MetricsError("missing calendar year in common equity series")
    rows = []
    prior_strategy = prior_spy = initial
    for year in years:
        year_dates = [day for day in common_dates if day.year == year]
        start, end = year_dates[0], year_dates[-1]
        strategy_return = strategy_map[end] / prior_strategy - 1
        spy_return = spy_map[end] / prior_spy - 1
        hurdle = spy_return + PythonDecimal("0.10")
        period = (
            "PARTIAL_YEAR"
            if year == as_of.year and as_of < date(year, 12, 31)
            else "FULL_YEAR"
        )
        status = "PASS" if strategy_return >= hurdle else "FAIL"
        rows.append(
            AnnualGateRow(
                year,
                period,
                start,
                end,
                strategy_return,
                spy_return,
                strategy_return - spy_return,
                hurdle,
                status,
            )
        )
        prior_strategy, prior_spy = strategy_map[end], spy_map[end]
    overall = "PASS" if all(row.status == "PASS" for row in rows) else "FAIL"
    return AnnualGateResult(tuple(rows), overall)
