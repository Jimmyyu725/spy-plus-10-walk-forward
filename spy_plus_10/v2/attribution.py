"""Daily sleeve attribution for separately executed v2 component runs.

``sleeve_cash_flows`` is net portfolio cash invested in a sleeve during the
day: positive moves cash into positions and negative returns cash from them.
It is neither an external deposit nor PnL.  Each component and removal
ablation is an independent ``run_variant`` configuration; this module never
derives an ablation by subtracting a sleeve from a full-portfolio path.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping

from .evidence import RUN_VARIANTS, SLEEVES


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZERO = Decimal("0")

ABLATION_VARIANTS = MappingProxyType(
    {
        "full": SLEEVES,
        "core_only": ("core",),
        "equity_only": ("equity",),
        "futures_only": ("futures",),
        "defensive_option_only": ("defensive_option",),
        "without_core": ("equity", "futures", "defensive_option"),
        "without_equity": ("core", "futures", "defensive_option"),
        "without_futures": ("core", "equity", "defensive_option"),
        "without_defensive_option": ("core", "equity", "futures"),
    }
)


class AttributionError(RuntimeError):
    """Raised when a daily sleeve ledger row is invalid or cannot reconcile."""


def _d(value: object, label: str) -> Decimal:
    """Convert the explicitly supported numeric types to a finite Decimal."""
    if type(value) not in (str, int, float, Decimal):
        raise AttributionError(f"{label} is not numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AttributionError(f"{label} is not numeric") from error
    if not result.is_finite():
        raise AttributionError(f"{label} is not finite")
    return result


def enabled_sleeves(run_variant: str) -> tuple[str, ...]:
    """Return the fixed sleeve set for one separately executed run variant."""
    if type(run_variant) is not str:
        raise AttributionError("unknown component or ablation variant")
    try:
        return ABLATION_VARIANTS[run_variant]
    except KeyError as error:
        raise AttributionError("unknown component or ablation variant") from error


def _parse_day(value: object) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        raise AttributionError("invalid ledger date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise AttributionError("invalid ledger date") from error


def _sleeve_mapping(value: object, label: str, *, complete: bool) -> dict[str, Decimal]:
    if not isinstance(value, Mapping):
        raise AttributionError(f"{label} must be a mapping")
    keys = set(value)
    unknown = keys - set(SLEEVES)
    if unknown:
        raise AttributionError(f"{label} contains unknown sleeves")
    if complete and keys != set(SLEEVES):
        raise AttributionError(f"{label} must contain exactly four sleeves")
    return {name: _d(value.get(name, _ZERO), f"{label}.{name}") for name in SLEEVES}


class SleeveLedger:
    """Reconcile daily total equity with per-sleeve PnL for one run variant.

    Cash is owned by ``core``.  Therefore, after position-mark PnL and sleeve
    cash flows are attributed, the exact unallocated cash residual is assigned
    to ``core`` instead of an implicit ``other`` bucket.
    """

    def __init__(self, initial_equity, run_variant: str = "full") -> None:
        self._initial_equity = _d(initial_equity, "initial equity")
        if self._initial_equity <= _ZERO:
            raise AttributionError("initial equity must be positive")
        self._run_variant = run_variant
        self._enabled = enabled_sleeves(run_variant)
        self._last_date: date | None = None
        self._last_values: dict[str, Decimal] | None = None
        self._last_equity: Decimal | None = None
        self._cumulative = {name: _ZERO for name in SLEEVES}
        self._rows: list[dict] = []

    def record_day(
        self,
        day,
        marked_values,
        *,
        cash,
        external_flow,
        fees,
        slippage,
        sleeve_cash_flows=None,
    ) -> dict:
        """Record one strictly later mark and return an isolated attribution row."""
        current_date = _parse_day(day)
        if self._last_date is not None and current_date <= self._last_date:
            raise AttributionError("ledger dates must be strictly increasing")

        current = _sleeve_mapping(marked_values, "marked values", complete=True)
        current_cash = _d(cash, "cash")
        flow = _d(external_flow, "external flow")
        fee_map = _sleeve_mapping(fees, "fees", complete=False)
        slippage_map = _sleeve_mapping(slippage, "slippage", complete=False)
        cash_flow_map = _sleeve_mapping(
            {} if sleeve_cash_flows is None else sleeve_cash_flows,
            "sleeve cash flows",
            complete=False,
        )
        if any(value < _ZERO for value in fee_map.values()):
            raise AttributionError("fees must be nonnegative")
        if any(value < _ZERO for value in slippage_map.values()):
            raise AttributionError("slippage must be nonnegative")

        for sleeve in set(SLEEVES) - set(self._enabled):
            if any(
                value != _ZERO
                for value in (
                    current[sleeve],
                    fee_map[sleeve],
                    slippage_map[sleeve],
                    cash_flow_map[sleeve],
                )
            ):
                raise AttributionError(f"disabled sleeve has exposure or cost: {sleeve}")

        equity = current_cash + sum(current.values(), _ZERO)
        if equity <= _ZERO:
            raise AttributionError("total equity must be positive")

        if self._last_values is None:
            if equity - flow != self._initial_equity:
                raise AttributionError("opening ledger does not match initial equity")
            portfolio_pnl = _ZERO
            daily_pnl = {name: _ZERO for name in SLEEVES}
        else:
            portfolio_pnl = equity - self._last_equity - flow
            daily_pnl = {
                name: current[name] - self._last_values[name] - cash_flow_map[name]
                for name in SLEEVES
            }
            cash_residual = portfolio_pnl - sum(daily_pnl.values(), _ZERO)
            daily_pnl["core"] += cash_residual
            if sum(daily_pnl.values(), _ZERO) != portfolio_pnl:
                raise AttributionError("sleeve PnL does not reconcile")

        for name in SLEEVES:
            self._cumulative[name] += daily_pnl[name]
        row = {
            "date": day,
            "run_variant": self._run_variant,
            "enabled_sleeves": self._enabled,
            "equity": equity,
            "external_flow": flow,
            "portfolio_daily_pnl": portfolio_pnl,
            "sleeve_daily_pnl": daily_pnl,
            "sleeve_cumulative_pnl": dict(self._cumulative),
            "fees": fee_map,
            "slippage": slippage_map,
        }
        self._rows.append(row)
        self._last_date = current_date
        self._last_values = current
        self._last_equity = equity
        return self._copy_row(row)

    def equity_path(self) -> list[Decimal]:
        """Return a fresh list of recorded daily total-equity marks."""
        return [row["equity"] for row in self._rows]

    @staticmethod
    def _copy_row(row: dict) -> dict:
        return {
            **row,
            "sleeve_daily_pnl": dict(row["sleeve_daily_pnl"]),
            "sleeve_cumulative_pnl": dict(row["sleeve_cumulative_pnl"]),
            "fees": dict(row["fees"]),
            "slippage": dict(row["slippage"]),
        }
