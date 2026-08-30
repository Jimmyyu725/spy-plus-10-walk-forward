from __future__ import annotations

from dataclasses import dataclass
from datetime import date


LOOKBACKS = (63, 126, 252)


class TrendSignalError(RuntimeError):
    """Raised when a point-in-time trend signal cannot be verified."""


@dataclass(frozen=True)
class DailyPrice:
    as_of: date
    close: float


@dataclass(frozen=True)
class TrendSignal:
    root: str
    as_of: date
    directions: tuple[int, int, int]
    score: float


def compute_trend_signal(
    root: str,
    series: list[DailyPrice],
    signal_date: date,
) -> TrendSignal:
    if not root:
        raise TrendSignalError("root is required")
    if any(left.as_of >= right.as_of for left, right in zip(series, series[1:])):
        raise TrendSignalError("price dates must be strictly increasing")
    eligible = [point for point in series if point.as_of <= signal_date]
    if len(eligible) < 253:
        raise TrendSignalError("253 completed daily prices are required")
    if any(point.close <= 0 for point in eligible):
        raise TrendSignalError("prices must be positive")
    current = eligible[-1].close
    returns = [
        current / eligible[-(lookback + 1)].close - 1 for lookback in LOOKBACKS
    ]
    directions = tuple(
        1 if value > 0 else -1 if value < 0 else 0 for value in returns
    )
    return TrendSignal(root, eligible[-1].as_of, directions, sum(directions) / 3)
