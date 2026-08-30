from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite


class OptionChainError(RuntimeError):
    """Raised when a defined-risk option spread cannot be selected."""


@dataclass(frozen=True)
class OptionContractSnapshot:
    symbol: str
    as_of: datetime
    expiry: date
    strike: float
    right: str
    bid: float
    ask: float
    volume: int
    open_interest: int
    delta: float
    implied_volatility: float
    multiplier: int
    minimum_tick: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class BullPutSpreadSelection:
    entry_time: datetime
    short_put: OptionContractSnapshot
    long_put: OptionContractSnapshot

    @property
    def width(self) -> float:
        return self.short_put.strike - self.long_put.strike

    @property
    def mid_credit(self) -> float:
        return self.short_put.mid - self.long_put.mid


def _valid_contract(
    item: OptionContractSnapshot,
    entry_time: datetime,
) -> bool:
    if item.as_of > entry_time or item.right.upper() != "PUT":
        return False
    dte = (item.expiry - entry_time.date()).days
    if not 30 <= dte <= 60:
        return False
    numeric = (
        item.strike,
        item.bid,
        item.ask,
        item.delta,
        item.implied_volatility,
        item.minimum_tick,
    )
    if not all(isfinite(float(value)) for value in numeric):
        return False
    if (
        item.strike <= 0
        or item.bid <= 0
        or item.ask < item.bid
        or item.implied_volatility <= 0
        or item.minimum_tick <= 0
        or item.multiplier <= 0
        or item.volume < 1
        or item.open_interest < 100
    ):
        return False
    mid = item.mid
    return mid > 0 and (item.ask - item.bid) / mid <= 0.20


def select_bull_put_spread(
    contracts: list[OptionContractSnapshot],
    *,
    entry_time: datetime,
    underlying_price: float,
) -> BullPutSpreadSelection:
    if not isfinite(underlying_price) or underlying_price <= 0:
        raise OptionChainError("underlying price must be finite and positive")
    eligible = [
        item for item in contracts if _valid_contract(item, entry_time)
    ]
    if not eligible:
        raise OptionChainError("no eligible put contracts")
    expiries = sorted(
        {item.expiry for item in eligible},
        key=lambda expiry: (
            abs((expiry - entry_time.date()).days - 45),
            expiry,
        ),
    )
    expiry = expiries[0]
    same_expiry = [item for item in eligible if item.expiry == expiry]
    short_candidates = sorted(
        same_expiry,
        key=lambda item: (
            abs(item.delta - (-0.20)),
            -item.open_interest,
            item.strike,
        ),
    )
    for short_put in short_candidates:
        long_candidates = [
            item
            for item in same_expiry
            if item.symbol != short_put.symbol and item.strike < short_put.strike
        ]
        long_candidates.sort(
            key=lambda item: (
                abs(item.delta - (-0.10)),
                -item.open_interest,
                item.strike,
            )
        )
        if long_candidates:
            return BullPutSpreadSelection(entry_time, short_put, long_candidates[0])
    raise OptionChainError("no eligible long protection contract")
