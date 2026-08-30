from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from signals.equity_factor import EquityFactorScore


class AllocationError(RuntimeError):
    """Raised when an equity factor allocation cannot be verified."""


@dataclass(frozen=True)
class EquityAllocation:
    stock_weights: dict[str, float]
    spy_weight: float
    long_gross: float
    gross_exposure: float
    beta_before_hedge: float
    beta_after_hedge: float
    expected_annual_volatility: float
    gross_cap_binding: bool


def _annual_volatility(returns: tuple[float, ...]) -> float:
    if len(returns) < 2:
        raise AllocationError("return history is too short")
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (
        len(returns) - 1
    )
    if variance <= 0 or not isfinite(variance):
        raise AllocationError("portfolio variance must be positive and finite")
    return sqrt(variance * 252)


def allocate_equity_factors(
    scores: list[EquityFactorScore],
    *,
    max_positions: int = 30,
    target_annual_volatility: float = 0.05,
    gross_notional_cap: float = 0.50,
) -> EquityAllocation:
    if not scores:
        raise AllocationError("at least one factor score is required")
    if max_positions <= 0:
        raise AllocationError("max_positions must be positive")
    if (
        not isfinite(target_annual_volatility)
        or target_annual_volatility <= 0
        or not isfinite(gross_notional_cap)
        or gross_notional_cap <= 0
    ):
        raise AllocationError("risk targets must be finite and positive")
    symbols = [item.symbol for item in scores]
    if len(set(symbols)) != len(symbols):
        raise AllocationError("factor symbols must be unique")

    selected = sorted(scores, key=lambda item: (-item.composite, item.symbol))[
        :max_positions
    ]
    if any(
        not isfinite(item.total_volatility) or item.total_volatility <= 0
        for item in selected
    ):
        raise AllocationError("stock volatility must be finite and positive")
    if any(
        len(item.stock_returns) != 126 or len(item.spy_returns) != 126
        for item in selected
    ):
        raise AllocationError("exactly 126 aligned returns are required")
    spy_returns = selected[0].spy_returns
    if any(item.spy_returns != spy_returns for item in selected[1:]):
        raise AllocationError("SPY return histories must match")
    if any(
        not isfinite(value)
        for item in selected
        for value in (*item.stock_returns, *item.spy_returns, item.beta)
    ):
        raise AllocationError("returns and betas must be finite")

    inverse_volatility = {
        item.symbol: 1.0 / item.total_volatility for item in selected
    }
    inverse_sum = sum(inverse_volatility.values())
    base_long_weights = {
        symbol: value / inverse_sum
        for symbol, value in inverse_volatility.items()
    }
    beta_before = sum(
        base_long_weights[item.symbol] * item.beta for item in selected
    )
    base_spy_weight = -beta_before
    base_returns = tuple(
        sum(
            base_long_weights[item.symbol] * item.stock_returns[index]
            for item in selected
        )
        + base_spy_weight * spy_returns[index]
        for index in range(126)
    )
    base_volatility = _annual_volatility(base_returns)
    volatility_scale = target_annual_volatility / base_volatility
    base_gross = 1.0 + abs(base_spy_weight)
    cap_scale = gross_notional_cap / base_gross
    scale = min(volatility_scale, cap_scale)
    if scale <= 0 or not isfinite(scale):
        raise AllocationError("allocation scale must be finite and positive")

    stock_weights = {
        symbol: value * scale for symbol, value in base_long_weights.items()
    }
    spy_weight = base_spy_weight * scale
    long_gross = sum(stock_weights.values())
    gross_exposure = long_gross + abs(spy_weight)
    beta_after = sum(
        stock_weights[item.symbol] * item.beta for item in selected
    ) + spy_weight
    return EquityAllocation(
        stock_weights,
        spy_weight,
        long_gross,
        gross_exposure,
        beta_before * scale,
        beta_after,
        base_volatility * scale,
        cap_scale <= volatility_scale,
    )
