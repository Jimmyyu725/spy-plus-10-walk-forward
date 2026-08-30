from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil, floor, isfinite

from option_chain import BullPutSpreadSelection


class OptionRiskError(RuntimeError):
    """Raised when a spread cannot be sized within defined-risk limits."""


@dataclass(frozen=True)
class RealizedOptionLoss:
    realized_at: date
    loss: float


@dataclass(frozen=True)
class DefinedRiskSizing:
    contracts: int
    short_fill: float
    long_fill: float
    credit_per_share: float
    entry_fees: float
    max_loss_per_contract: float
    total_max_loss: float
    available_risk_budget: float
    trailing_realized_loss: float
    volatility_budget_contracts: int


def _round_up(value: float, tick: float) -> float:
    return ceil((value - 1e-12) / tick) * tick


def _round_down(value: float, tick: float) -> float:
    return floor((value + 1e-12) / tick) * tick


def _entry_fees(contracts: int, regulatory_fee_per_contract: float = 0.0) -> float:
    return (
        2 * max(contracts * 0.65, 1.0)
        + contracts * regulatory_fee_per_contract
    )


def size_defined_risk_spread(
    spread: BullPutSpreadSelection,
    *,
    equity: float,
    as_of: datetime,
    realized_losses: list[RealizedOptionLoss],
    per_contract_annual_pnl_volatility: float,
    slippage_multiplier: float = 1.0,
    regulatory_fee_per_contract: float = 0.0,
) -> DefinedRiskSizing:
    short_put, long_put = spread.short_put, spread.long_put
    if as_of < spread.entry_time:
        raise OptionRiskError("sizing time cannot precede entry selection")
    if (
        short_put.expiry != long_put.expiry
        or long_put.strike >= short_put.strike
        or short_put.symbol == long_put.symbol
    ):
        raise OptionRiskError("long protection must be lower strike and same expiry")
    if short_put.multiplier != long_put.multiplier:
        raise OptionRiskError("leg multipliers must match")
    if (
        not all(
            isfinite(value) and value > 0
            for value in (
                equity,
                per_contract_annual_pnl_volatility,
                slippage_multiplier,
                short_put.minimum_tick,
                long_put.minimum_tick,
            )
        )
        or not isfinite(regulatory_fee_per_contract)
        or regulatory_fee_per_contract < 0
    ):
        raise OptionRiskError("risk inputs must be finite and positive")

    short_adverse = (short_put.ask - short_put.bid) * 0.25 * slippage_multiplier
    long_adverse = (long_put.ask - long_put.bid) * 0.25 * slippage_multiplier
    short_fill = _round_down(short_put.mid - short_adverse, short_put.minimum_tick)
    long_fill = _round_up(long_put.mid + long_adverse, long_put.minimum_tick)
    credit = short_fill - long_fill
    width = short_put.strike - long_put.strike
    if credit <= 0 or credit >= width:
        raise OptionRiskError("spread must have positive credit below its width")
    multiplier = short_put.multiplier
    max_loss_per_contract = (width - credit) * multiplier

    window_start = as_of.date() - timedelta(days=365)
    trailing_loss = sum(
        item.loss
        for item in realized_losses
        if window_start <= item.realized_at <= as_of.date() and item.loss > 0
    )
    if any(not isfinite(item.loss) or item.loss < 0 for item in realized_losses):
        raise OptionRiskError("realized losses must be finite and non-negative")
    trade_budget = equity * 0.005
    rolling_remaining = max(0.0, equity * 0.03 - trailing_loss)
    available_budget = min(trade_budget, rolling_remaining)
    volatility_contracts = floor(
        equity * 0.03 / per_contract_annual_pnl_volatility
    )
    if available_budget <= 0 or volatility_contracts <= 0:
        raise OptionRiskError("option loss or volatility budget is exhausted")

    approximate = floor(available_budget / max_loss_per_contract)
    contracts = min(approximate, volatility_contracts)
    while contracts > 0:
        total_loss = contracts * max_loss_per_contract + _entry_fees(
            contracts,
            regulatory_fee_per_contract,
        )
        if total_loss <= available_budget + 1e-9:
            break
        contracts -= 1
    if contracts <= 0:
        raise OptionRiskError("no whole spread fits the defined-risk budget")
    entry_fees = _entry_fees(contracts, regulatory_fee_per_contract)
    total_max_loss = contracts * max_loss_per_contract + entry_fees
    return DefinedRiskSizing(
        contracts,
        short_fill,
        long_fill,
        credit,
        entry_fees,
        max_loss_per_contract,
        total_max_loss,
        available_budget,
        trailing_loss,
        volatility_contracts,
    )
