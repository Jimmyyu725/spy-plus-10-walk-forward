from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite, sqrt


class OptionSignalError(RuntimeError):
    """Raised when a weekly option regime cannot be verified."""


@dataclass(frozen=True)
class DailyClose:
    as_of: date
    close: float


@dataclass(frozen=True)
class AtmIvObservation:
    as_of: date
    expiry: date
    strike: float
    underlying_price: float
    implied_volatility: float
    open_interest: int


@dataclass(frozen=True)
class OptionRegimeSignal:
    cutoff: date
    signal_time: date
    close: float
    sma_200: float
    realized_volatility: float
    implied_volatility: float
    iv_premium: float
    eligible: bool


def _completed_closes(
    prices: list[DailyClose],
    cutoff: date,
) -> list[DailyClose]:
    if any(left.as_of >= right.as_of for left, right in zip(prices, prices[1:])):
        raise OptionSignalError("close dates must be strictly increasing")
    completed = [point for point in prices if point.as_of <= cutoff]
    if len(completed) < 200:
        raise OptionSignalError("200 completed closes are required")
    if completed[-1].as_of != cutoff:
        raise OptionSignalError("a completed close is required at cutoff")
    if any(not isfinite(point.close) or point.close <= 0 for point in completed):
        raise OptionSignalError("closes must be finite and positive")
    return completed


def realized_volatility(
    prices: list[DailyClose],
    *,
    cutoff: date,
    lookback: int = 20,
) -> float:
    if lookback < 2:
        raise OptionSignalError("realized-volatility lookback must be at least two")
    if any(left.as_of >= right.as_of for left, right in zip(prices, prices[1:])):
        raise OptionSignalError("close dates must be strictly increasing")
    completed = [point for point in prices if point.as_of <= cutoff]
    if len(completed) < lookback + 1:
        raise OptionSignalError(f"{lookback + 1} completed closes are required")
    window = completed[-(lookback + 1):]
    if any(not isfinite(point.close) or point.close <= 0 for point in window):
        raise OptionSignalError("closes must be finite and positive")
    returns = [
        current.close / previous.close - 1
        for previous, current in zip(window, window[1:])
    ]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (
        len(returns) - 1
    )
    if variance < 0 or not isfinite(variance):
        raise OptionSignalError("realized variance must be finite")
    return sqrt(variance * 252)


def select_atm_iv(
    observations: list[AtmIvObservation],
    *,
    cutoff: date,
) -> AtmIvObservation:
    eligible = []
    for item in observations:
        if item.as_of > cutoff:
            continue
        if item.as_of != cutoff:
            continue
        dte = (item.expiry - cutoff).days
        if not 30 <= dte <= 60:
            continue
        if not all(
            isfinite(value) and value > 0
            for value in (
                item.strike,
                item.underlying_price,
                item.implied_volatility,
            )
        ):
            continue
        if item.open_interest < 0:
            continue
        eligible.append(item)
    if not eligible:
        raise OptionSignalError("no eligible ATM IV observation")
    eligible.sort(
        key=lambda item: (
            abs((item.expiry - cutoff).days - 45),
            item.expiry,
            abs(item.strike - item.underlying_price),
            -item.open_interest,
            item.strike,
        )
    )
    return eligible[0]


def compute_option_regime(
    prices: list[DailyClose],
    observations: list[AtmIvObservation],
    *,
    cutoff: date,
    signal_time: date,
) -> OptionRegimeSignal:
    if signal_time <= cutoff:
        raise OptionSignalError("signal_time must be after cutoff")
    completed = _completed_closes(prices, cutoff)
    sma_200 = sum(point.close for point in completed[-200:]) / 200
    realized = realized_volatility(completed, cutoff=cutoff, lookback=20)
    atm = select_atm_iv(observations, cutoff=cutoff)
    premium = atm.implied_volatility - realized
    return OptionRegimeSignal(
        cutoff,
        signal_time,
        completed[-1].close,
        sma_200,
        realized,
        atm.implied_volatility,
        premium,
        completed[-1].close > sma_200 and premium >= 0.05,
    )
