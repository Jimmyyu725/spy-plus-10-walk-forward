from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite


class UniverseSelectionError(RuntimeError):
    """Raised when an equity universe decision cannot be audited safely."""


@dataclass(frozen=True)
class DollarVolumePoint:
    symbol: str
    as_of: date
    dollar_volume: float


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    as_of: date
    price: float
    has_fundamental_data: bool
    roe: float | None
    gross_profit: float | None
    total_assets: float | None


@dataclass(frozen=True)
class EquityCandidate:
    symbol: str
    cutoff: date
    price: float
    average_dollar_volume: float
    roe: float
    gross_profit_to_assets: float


def _finite(value) -> bool:
    return value is not None and isfinite(float(value))


def select_equity_candidates(
    snapshots: list[FundamentalSnapshot],
    dollar_volume_history: dict[str, list[DollarVolumePoint]],
    *,
    cutoff: date,
    selection_time: date,
    top_n: int = 500,
    lookback: int = 20,
    minimum_price: float = 5.0,
) -> tuple[EquityCandidate, ...]:
    if selection_time <= cutoff:
        raise UniverseSelectionError("selection_time must be after cutoff")
    if top_n <= 0 or lookback <= 0:
        raise UniverseSelectionError("top_n and lookback must be positive")
    if minimum_price <= 0 or not isfinite(minimum_price):
        raise UniverseSelectionError("minimum_price must be finite and positive")

    symbols = [item.symbol for item in snapshots]
    if any(not symbol for symbol in symbols):
        raise UniverseSelectionError("snapshot symbol is required")
    if len(set(symbols)) != len(symbols):
        raise UniverseSelectionError("snapshot symbols must be unique")

    candidates = []
    for item in snapshots:
        if item.as_of != cutoff:
            raise UniverseSelectionError("snapshot must match the completed cutoff")
        if not item.has_fundamental_data:
            continue
        if not all(
            _finite(value)
            for value in (item.price, item.roe, item.gross_profit, item.total_assets)
        ):
            continue
        price = float(item.price)
        total_assets = float(item.total_assets)
        if price < minimum_price or total_assets <= 0:
            continue

        full_history = dollar_volume_history.get(item.symbol, [])
        eligible = [point for point in full_history if point.as_of <= cutoff]
        if any(point.symbol != item.symbol for point in eligible):
            raise UniverseSelectionError("dollar-volume symbol mismatch")
        if any(
            left.as_of >= right.as_of
            for left, right in zip(eligible, eligible[1:])
        ):
            raise UniverseSelectionError(
                "dollar-volume dates must be strictly increasing"
            )
        if len(eligible) < lookback or eligible[-1].as_of != cutoff:
            continue
        window = eligible[-lookback:]
        if any(
            not _finite(point.dollar_volume) or point.dollar_volume <= 0
            for point in window
        ):
            continue
        average = sum(float(point.dollar_volume) for point in window) / lookback
        candidates.append(
            EquityCandidate(
                item.symbol,
                cutoff,
                price,
                average,
                float(item.roe),
                float(item.gross_profit) / total_assets,
            )
        )

    candidates.sort(key=lambda item: (-item.average_dollar_volume, item.symbol))
    return tuple(candidates[:top_n])
