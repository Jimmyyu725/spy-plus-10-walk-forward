from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import stdev


class AllocationError(RuntimeError):
    """Raised when past-only risk evidence is incomplete."""


@dataclass(frozen=True)
class FuturesAllocation:
    weights: dict[str, float]
    predicted_volatility: float
    gross_notional: float


def _covariance(left: list[float], right: list[float]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    ) / (len(left) - 1)


def allocate_trend(
    scores: dict[str, float],
    returns: dict[str, list[float]],
    *,
    target_volatility: float = 0.07,
    gross_cap: float = 0.70,
) -> FuturesAllocation:
    roots = sorted(scores)
    if set(roots) != set(returns):
        raise AllocationError("scores and returns roots differ")
    if any(len(returns[root]) < 252 for root in roots):
        raise AllocationError("252 daily returns are required")
    if not roots or target_volatility <= 0 or gross_cap <= 0:
        raise AllocationError("invalid allocation inputs")
    raw = {}
    for root in roots:
        volatility = stdev(returns[root][-60:]) * sqrt(252)
        if volatility <= 0:
            raise AllocationError(f"non-positive volatility: {root}")
        raw[root] = scores[root] / volatility
    raw_gross = sum(abs(value) for value in raw.values())
    if raw_gross == 0:
        return FuturesAllocation({root: 0.0 for root in roots}, 0.0, 0.0)
    unit = {root: raw[root] / raw_gross for root in roots}
    covariance = {
        (left, right): _covariance(returns[left][-252:], returns[right][-252:]) * 252
        for left in roots
        for right in roots
    }
    variance = sum(
        unit[left] * unit[right] * covariance[left, right]
        for left in roots
        for right in roots
    )
    if variance <= 0:
        raise AllocationError("non-positive portfolio variance")
    scale = min(target_volatility / sqrt(variance), gross_cap)
    weights = {root: unit[root] * scale for root in roots}
    gross = sum(abs(value) for value in weights.values())
    predicted = sqrt(variance) * scale
    return FuturesAllocation(weights, predicted, gross)


def volatility_only_control(
    scores,
    returns,
    *,
    target_volatility=0.07,
    gross_cap=0.70,
):
    controls = {root: 1.0 if score != 0 else 0.0 for root, score in scores.items()}
    return allocate_trend(
        controls,
        returns,
        target_volatility=target_volatility,
        gross_cap=gross_cap,
    )
