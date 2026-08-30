from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite, sqrt


REQUIRED_SLEEVES = ("EQUITY", "FUTURES", "OPTION")


class PortfolioRiskError(RuntimeError):
    """Raised when portfolio risk cannot be verified from completed inputs."""


@dataclass(frozen=True)
class DatedReturn:
    as_of: date
    value: float


@dataclass(frozen=True)
class SleeveForecast:
    name: str
    data_cutoff: datetime
    target_volatility: float
    proposed_gross: float
    estimated_beta: float


@dataclass(frozen=True)
class PortfolioRiskAllocation:
    scales: dict[str, float]
    core_spy_weight: float
    predicted_beta: float
    conservative_annual_volatility: float
    alpha_gross: float
    total_gross: float
    drawdown: float
    drawdown_scale: float
    risk_contributions: dict[str, float]
    maximum_risk_contribution: float


def annualized_volatility(
    returns: list[DatedReturn],
    *,
    cutoff: date,
    lookback: int = 60,
) -> float:
    if lookback < 2 or not returns:
        raise PortfolioRiskError("volatility lookback is invalid")
    if any(left.as_of >= right.as_of for left, right in zip(returns, returns[1:])):
        raise PortfolioRiskError("return dates must be strictly increasing")
    eligible = [item for item in returns if item.as_of <= cutoff]
    if len(eligible) < lookback:
        raise PortfolioRiskError("completed return history is insufficient")
    values = [float(item.value) for item in eligible[-lookback:]]
    if any(not isfinite(value) or value <= -1 for value in values):
        raise PortfolioRiskError("returns must be finite and above -100%")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0 or not isfinite(variance):
        raise PortfolioRiskError("return variance must be positive and finite")
    return sqrt(variance * 252)


def _concentration_scales(
    target_risks: dict[str, float],
    maximum_share: float,
) -> dict[str, float]:
    def share(threshold: float) -> float:
        capped = [min(value, threshold) for value in target_risks.values()]
        total = sum(capped)
        return max(capped) / total if total > 0 else 1.0

    if share(max(target_risks.values())) <= maximum_share:
        return {name: 1.0 for name in target_risks}
    lower = 0.0
    upper = max(target_risks.values())
    for _ in range(120):
        midpoint = (lower + upper) / 2
        if share(midpoint) <= maximum_share:
            lower = midpoint
        else:
            upper = midpoint
    threshold = lower
    return {
        name: min(value, threshold) / value
        for name, value in target_risks.items()
    }


def _largest_uniform_feasible(predicate) -> float:
    if predicate(1.0):
        return 1.0
    if not predicate(0.0):
        raise PortfolioRiskError("portfolio constraint is infeasible without Alpha")
    lower, upper = 0.0, 1.0
    for _ in range(120):
        midpoint = (lower + upper) / 2
        if predicate(midpoint):
            lower = midpoint
        else:
            upper = midpoint
    return lower


def coordinate_portfolio_risk(
    forecasts: list[SleeveForecast],
    *,
    decision_time: datetime,
    spy_annual_volatility: float,
    peak_equity: float,
    current_equity: float,
    beta_target: float = 1.0,
    beta_minimum: float = 0.8,
    beta_maximum: float = 1.2,
    portfolio_volatility_target: float = 0.18,
    alpha_gross_cap: float = 1.0,
    total_gross_cap: float = 2.0,
    maximum_alpha_risk_contribution: float = 0.40,
) -> PortfolioRiskAllocation:
    if decision_time.tzinfo is None:
        raise PortfolioRiskError("decision time must be timezone-aware")
    by_name = {item.name: item for item in forecasts}
    if len(by_name) != len(forecasts) or tuple(sorted(by_name)) != tuple(
        sorted(REQUIRED_SLEEVES)
    ):
        raise PortfolioRiskError("exactly one forecast per required sleeve is required")
    numeric = (
        spy_annual_volatility,
        peak_equity,
        current_equity,
        beta_target,
        beta_minimum,
        beta_maximum,
        portfolio_volatility_target,
        alpha_gross_cap,
        total_gross_cap,
        maximum_alpha_risk_contribution,
    )
    if any(not isfinite(value) for value in numeric):
        raise PortfolioRiskError("portfolio risk inputs must be finite")
    if (
        spy_annual_volatility <= 0
        or peak_equity <= 0
        or current_equity <= 0
        or current_equity > peak_equity
        or beta_minimum > beta_target
        or beta_target > beta_maximum
        or portfolio_volatility_target <= 0
        or alpha_gross_cap <= 0
        or total_gross_cap < 1
        or not (1 / len(REQUIRED_SLEEVES) <= maximum_alpha_risk_contribution < 1)
    ):
        raise PortfolioRiskError("portfolio limits are invalid")

    for item in forecasts:
        if item.data_cutoff.tzinfo is None or item.data_cutoff >= decision_time:
            raise PortfolioRiskError("sleeve evidence must be completed before decision")
        if (
            not isfinite(item.target_volatility)
            or item.target_volatility <= 0
            or not isfinite(item.proposed_gross)
            or item.proposed_gross < 0
            or not isfinite(item.estimated_beta)
        ):
            raise PortfolioRiskError("sleeve forecast is invalid")

    target_risks = {
        name: by_name[name].target_volatility for name in REQUIRED_SLEEVES
    }
    scales = _concentration_scales(
        target_risks,
        maximum_alpha_risk_contribution,
    )
    drawdown = 1 - current_equity / peak_equity
    if drawdown >= 0.25:
        drawdown_scale = 0.0
    elif drawdown >= 0.15:
        drawdown_scale = 0.5
    else:
        drawdown_scale = 1.0
    scales = {name: value * drawdown_scale for name, value in scales.items()}

    def alpha_gross(scale_map: dict[str, float]) -> float:
        return sum(
            scale_map[name] * by_name[name].proposed_gross
            for name in REQUIRED_SLEEVES
        )

    gross = alpha_gross(scales)
    if gross > alpha_gross_cap:
        factor = alpha_gross_cap / gross
        scales = {name: value * factor for name, value in scales.items()}

    def scaled(factor: float) -> dict[str, float]:
        return {name: value * factor for name, value in scales.items()}

    def core_weight(scale_map: dict[str, float]) -> float:
        alpha_beta = sum(
            scale_map[name] * by_name[name].estimated_beta
            for name in REQUIRED_SLEEVES
        )
        return beta_target - alpha_beta

    leverage_factor = _largest_uniform_feasible(
        lambda factor: abs(core_weight(scaled(factor)))
        + alpha_gross(scaled(factor))
        <= total_gross_cap + 1e-12
    )
    scales = scaled(leverage_factor)

    volatility_limit = max(portfolio_volatility_target, spy_annual_volatility)

    def conservative_volatility(scale_map: dict[str, float]) -> float:
        return abs(core_weight(scale_map)) * spy_annual_volatility + sum(
            scale_map[name] * by_name[name].target_volatility
            for name in REQUIRED_SLEEVES
        )

    volatility_factor = _largest_uniform_feasible(
        lambda factor: conservative_volatility(scaled(factor))
        <= volatility_limit + 1e-12
    )
    scales = scaled(volatility_factor)

    core = core_weight(scales)
    alpha_beta = sum(
        scales[name] * by_name[name].estimated_beta for name in REQUIRED_SLEEVES
    )
    predicted_beta = core + alpha_beta
    gross = alpha_gross(scales)
    total_gross = abs(core) + gross
    predicted_volatility = conservative_volatility(scales)
    risk_amounts = {
        name: scales[name] * by_name[name].target_volatility
        for name in REQUIRED_SLEEVES
    }
    total_alpha_risk = sum(risk_amounts.values())
    contributions = {
        name: (risk_amounts[name] / total_alpha_risk if total_alpha_risk > 0 else 0.0)
        for name in REQUIRED_SLEEVES
    }
    maximum_contribution = max(contributions.values())

    if (
        any(scale < -1e-12 or scale > 1 + 1e-12 for scale in scales.values())
        or not beta_minimum - 1e-12 <= predicted_beta <= beta_maximum + 1e-12
        or gross > alpha_gross_cap + 1e-10
        or total_gross > total_gross_cap + 1e-10
        or predicted_volatility > volatility_limit + 1e-10
        or maximum_contribution
        > maximum_alpha_risk_contribution + 1e-10
    ):
        raise PortfolioRiskError("coordinated portfolio violates a frozen limit")
    return PortfolioRiskAllocation(
        scales,
        core,
        predicted_beta,
        predicted_volatility,
        gross,
        total_gross,
        drawdown,
        drawdown_scale,
        contributions,
        maximum_contribution,
    )
