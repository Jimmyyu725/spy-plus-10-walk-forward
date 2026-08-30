from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import ceil, floor, isfinite


class OptionLifecycleError(RuntimeError):
    """Raised when a spread lifecycle transition is unsafe or unauditable."""


@dataclass(frozen=True)
class SpreadPosition:
    short_symbol: str
    long_symbol: str
    entry_time: datetime
    expiry: date
    short_strike: float
    long_strike: float
    entry_credit: float
    contracts: int
    multiplier: int
    entry_fees: float
    status: str

    def __post_init__(self):
        if (
            not self.short_symbol
            or not self.long_symbol
            or self.short_symbol == self.long_symbol
            or self.long_strike >= self.short_strike
            or self.expiry <= self.entry_time.date()
        ):
            raise OptionLifecycleError("long protection must be lower strike and same structure")
        if (
            self.entry_credit <= 0
            or self.contracts <= 0
            or self.multiplier <= 0
            or self.entry_fees < 0
        ):
            raise OptionLifecycleError("position economics must be positive")
        if self.status not in {"OPEN", "CLOSED"}:
            raise OptionLifecycleError("position status is invalid")


@dataclass(frozen=True)
class ExitQuote:
    as_of: datetime
    short_bid: float
    short_ask: float
    long_bid: float
    long_ask: float
    minimum_tick: float


@dataclass(frozen=True)
class ExitDecision:
    as_of: datetime
    action: str
    exit_debit: float
    dte: int


def _round_up(value: float, tick: float) -> float:
    return ceil((value - 1e-12) / tick) * tick


def _round_down(value: float, tick: float) -> float:
    return floor((value + 1e-12) / tick) * tick


def validate_decision_timeline(
    data_cutoff: datetime,
    signal_time: datetime,
    order_time: datetime,
) -> None:
    if not data_cutoff < signal_time < order_time:
        raise OptionLifecycleError(
            "data cutoff, signal, and order times must be strictly increasing"
        )


def can_open_new_spread(position: SpreadPosition | None) -> bool:
    return position is None or position.status == "CLOSED"


def decide_exit(
    position: SpreadPosition,
    quote: ExitQuote,
    *,
    slippage_multiplier: float = 1.0,
) -> ExitDecision:
    if position.status != "OPEN":
        raise OptionLifecycleError("only open positions can be evaluated")
    if quote.as_of <= position.entry_time:
        raise OptionLifecycleError("exit quote must follow entry")
    if not isfinite(slippage_multiplier) or slippage_multiplier <= 0:
        raise OptionLifecycleError("slippage multiplier must be positive")
    if (
        quote.short_bid <= 0
        or quote.short_ask < quote.short_bid
        or quote.long_bid <= 0
        or quote.long_ask < quote.long_bid
        or quote.minimum_tick <= 0
    ):
        raise OptionLifecycleError("exit quotes must be valid")
    short_mid = (quote.short_bid + quote.short_ask) / 2
    long_mid = (quote.long_bid + quote.long_ask) / 2
    short_buy = _round_up(
        short_mid
        + (quote.short_ask - quote.short_bid) * 0.25 * slippage_multiplier,
        quote.minimum_tick,
    )
    long_sell = _round_down(
        long_mid
        - (quote.long_ask - quote.long_bid) * 0.25 * slippage_multiplier,
        quote.minimum_tick,
    )
    exit_debit = max(0.0, short_buy - long_sell)
    dte = (position.expiry - quote.as_of.date()).days
    if exit_debit <= position.entry_credit * 0.50:
        action = "TAKE_PROFIT"
    elif dte <= 21:
        action = "TIME_EXIT"
    else:
        action = "HOLD"
    return ExitDecision(quote.as_of, action, exit_debit, dte)
