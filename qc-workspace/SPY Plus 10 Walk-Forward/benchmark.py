from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as PythonDecimal, ROUND_FLOOR

from costs import equity_execution


def _d(value) -> PythonDecimal:
    return value if isinstance(value, PythonDecimal) else PythonDecimal(str(value))


@dataclass(frozen=True)
class PricePoint:
    as_of: date
    total_return_price: PythonDecimal

    def __init__(self, as_of: date, total_return_price):
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "total_return_price", _d(total_return_price))


@dataclass(frozen=True)
class EquityPoint:
    as_of: date
    value: PythonDecimal


@dataclass(frozen=True)
class BenchmarkResult:
    shares: PythonDecimal
    entry_cash: PythonDecimal
    equity: tuple[EquityPoint, ...]
    liquidation_value: PythonDecimal


def build_spy_buy_hold(points: list[PricePoint], *, initial_cash) -> BenchmarkResult:
    if not points:
        raise ValueError("at least one SPY price is required")
    if any(point.total_return_price <= 0 for point in points):
        raise ValueError("SPY prices must be positive")
    if any(left.as_of >= right.as_of for left, right in zip(points, points[1:])):
        raise ValueError("SPY dates must be strictly increasing")
    cash = _d(initial_cash)
    entry = equity_execution("BUY", 1, points[0].total_return_price)
    shares = ((cash - entry.commission) / entry.fill_price).to_integral_value(
        rounding=ROUND_FLOOR
    )
    actual_entry = equity_execution("BUY", shares, points[0].total_return_price)
    entry_cash = cash - shares * actual_entry.fill_price - actual_entry.commission
    equity = tuple(
        EquityPoint(point.as_of, entry_cash + shares * point.total_return_price)
        for point in points
    )
    exit_cost = equity_execution("SELL", shares, points[-1].total_return_price)
    liquidation = entry_cash + shares * exit_cost.fill_price - exit_cost.commission
    return BenchmarkResult(shares, entry_cash, equity, liquidation)
