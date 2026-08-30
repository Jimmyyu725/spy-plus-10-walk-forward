from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite, sqrt

from universe import EquityCandidate


class FactorSignalError(RuntimeError):
    """Raised when an equity factor signal cannot be verified."""


@dataclass(frozen=True)
class EquityPrice:
    symbol: str
    as_of: date
    close: float


@dataclass(frozen=True)
class RawEquityFactor:
    symbol: str
    cutoff: date
    momentum: float
    roe: float
    gross_profit_to_assets: float
    residual_volatility: float
    beta: float
    total_volatility: float
    stock_returns: tuple[float, ...]
    spy_returns: tuple[float, ...]


@dataclass(frozen=True)
class EquityFactorScore:
    symbol: str
    cutoff: date
    composite: float
    momentum_z: float
    quality_z: float
    low_residual_volatility_z: float
    beta: float
    total_volatility: float
    stock_returns: tuple[float, ...]
    spy_returns: tuple[float, ...]


def linear_percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise FactorSignalError("percentile requires values")
    if not 0 <= percentile <= 1:
        raise FactorSignalError("percentile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    if any(not isfinite(value) for value in ordered):
        raise FactorSignalError("percentile values must be finite")
    position = percentile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def winsorized_zscores(
    values: dict[str, float],
    lower_percentile: float = 0.01,
    upper_percentile: float = 0.99,
) -> dict[str, float]:
    if not values:
        raise FactorSignalError("z-score requires values")
    if lower_percentile > upper_percentile:
        raise FactorSignalError("winsor percentiles are reversed")
    raw = [float(value) for value in values.values()]
    lower = linear_percentile(raw, lower_percentile)
    upper = linear_percentile(raw, upper_percentile)
    clipped = {
        symbol: min(max(float(value), lower), upper)
        for symbol, value in values.items()
    }
    mean = sum(clipped.values()) / len(clipped)
    variance = sum((value - mean) ** 2 for value in clipped.values()) / len(clipped)
    if variance == 0:
        return {symbol: 0.0 for symbol in clipped}
    standard_deviation = sqrt(variance)
    return {
        symbol: (value - mean) / standard_deviation
        for symbol, value in clipped.items()
    }


def _completed_prices(
    symbol: str,
    series: list[EquityPrice],
    cutoff: date,
) -> list[EquityPrice]:
    if any(left.as_of >= right.as_of for left, right in zip(series, series[1:])):
        raise FactorSignalError(f"{symbol} price dates must be strictly increasing")
    completed = [point for point in series if point.as_of <= cutoff]
    if len(completed) < 253:
        raise FactorSignalError(f"{symbol} requires 253 completed prices")
    if completed[-1].as_of != cutoff:
        raise FactorSignalError(f"{symbol} has no price at cutoff")
    if any(point.symbol != symbol for point in completed):
        raise FactorSignalError(f"{symbol} price symbol mismatch")
    if any(not isfinite(point.close) or point.close <= 0 for point in completed):
        raise FactorSignalError(f"{symbol} prices must be finite and positive")
    return completed


def _returns_by_date(series: list[EquityPrice]) -> dict[date, float]:
    return {
        current.as_of: current.close / previous.close - 1
        for previous, current in zip(series, series[1:])
    }


def compute_raw_equity_factor(
    candidate: EquityCandidate,
    stock_prices: list[EquityPrice],
    spy_prices: list[EquityPrice],
    *,
    cutoff: date,
) -> RawEquityFactor:
    if candidate.cutoff != cutoff:
        raise FactorSignalError("candidate cutoff mismatch")
    stock = _completed_prices(candidate.symbol, stock_prices, cutoff)
    spy = _completed_prices("SPY", spy_prices, cutoff)
    momentum = stock[-22].close / stock[-253].close - 1

    stock_by_date = _returns_by_date(stock)
    spy_by_date = _returns_by_date(spy)
    common_dates = sorted(set(stock_by_date).intersection(spy_by_date))
    if len(common_dates) < 126:
        raise FactorSignalError("126 aligned completed returns are required")
    common_dates = common_dates[-126:]
    stock_returns = tuple(stock_by_date[day] for day in common_dates)
    spy_returns = tuple(spy_by_date[day] for day in common_dates)

    stock_mean = sum(stock_returns) / len(stock_returns)
    spy_mean = sum(spy_returns) / len(spy_returns)
    market_variance_sum = sum((value - spy_mean) ** 2 for value in spy_returns)
    if market_variance_sum <= 0:
        raise FactorSignalError("SPY variance must be positive")
    covariance_sum = sum(
        (stock_value - stock_mean) * (spy_value - spy_mean)
        for stock_value, spy_value in zip(stock_returns, spy_returns)
    )
    beta = covariance_sum / market_variance_sum
    residuals = tuple(
        (stock_value - stock_mean) - beta * (spy_value - spy_mean)
        for stock_value, spy_value in zip(stock_returns, spy_returns)
    )
    residual_variance = sum(value * value for value in residuals) / (
        len(residuals) - 2
    )
    total_variance = sum(
        (value - stock_mean) ** 2 for value in stock_returns
    ) / (len(stock_returns) - 1)
    residual_volatility = sqrt(max(residual_variance, 0.0) * 252)
    total_volatility = sqrt(max(total_variance, 0.0) * 252)
    if total_volatility <= 0 or not all(
        isfinite(value)
        for value in (momentum, beta, residual_volatility, total_volatility)
    ):
        raise FactorSignalError("factor estimates must be finite with positive volatility")
    return RawEquityFactor(
        candidate.symbol,
        cutoff,
        momentum,
        candidate.roe,
        candidate.gross_profit_to_assets,
        residual_volatility,
        beta,
        total_volatility,
        stock_returns,
        spy_returns,
    )


def rank_equity_factors(
    raw_factors: list[RawEquityFactor],
) -> tuple[EquityFactorScore, ...]:
    if not raw_factors:
        raise FactorSignalError("at least one raw factor is required")
    symbols = [item.symbol for item in raw_factors]
    if len(set(symbols)) != len(symbols):
        raise FactorSignalError("factor symbols must be unique")
    cutoffs = {item.cutoff for item in raw_factors}
    if len(cutoffs) != 1:
        raise FactorSignalError("factor cutoffs must match")

    roe_z = winsorized_zscores({item.symbol: item.roe for item in raw_factors})
    gpa_z = winsorized_zscores(
        {item.symbol: item.gross_profit_to_assets for item in raw_factors}
    )
    quality = {
        symbol: 0.5 * roe_z[symbol] + 0.5 * gpa_z[symbol]
        for symbol in symbols
    }
    momentum_z = winsorized_zscores(
        {item.symbol: item.momentum for item in raw_factors}
    )
    quality_z = winsorized_zscores(quality)
    low_residual_z = winsorized_zscores(
        {item.symbol: -item.residual_volatility for item in raw_factors}
    )
    by_symbol = {item.symbol: item for item in raw_factors}
    scored = []
    for symbol in symbols:
        item = by_symbol[symbol]
        composite = (
            0.50 * momentum_z[symbol]
            + 0.25 * quality_z[symbol]
            + 0.25 * low_residual_z[symbol]
        )
        scored.append(
            EquityFactorScore(
                symbol,
                item.cutoff,
                composite,
                momentum_z[symbol],
                quality_z[symbol],
                low_residual_z[symbol],
                item.beta,
                item.total_volatility,
                item.stock_returns,
                item.spy_returns,
            )
        )
    scored.sort(key=lambda item: (-item.composite, item.symbol))
    return tuple(scored)
