from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as PythonDecimal, ROUND_CEILING, ROUND_FLOOR


def _d(value) -> PythonDecimal:
    return value if isinstance(value, PythonDecimal) else PythonDecimal(str(value))


def _side(value: str) -> str:
    value = value.upper()
    if value not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return value


def _positive(value, name: str) -> PythonDecimal:
    result = _d(value)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


@dataclass(frozen=True)
class ExecutionCost:
    fill_price: PythonDecimal
    commission: PythonDecimal
    regulatory_fee: PythonDecimal
    slippage: PythonDecimal

    @property
    def total_cost(self) -> PythonDecimal:
        return self.commission + self.regulatory_fee + self.slippage


def equity_execution(
    side: str,
    quantity,
    reference_price,
    *,
    bid=None,
    ask=None,
    regulatory_fee="0",
    slippage_multiplier="1",
) -> ExecutionCost:
    side = _side(side)
    quantity = _positive(quantity, "quantity")
    reference = _positive(reference_price, "reference_price")
    multiplier = _positive(slippage_multiplier, "slippage_multiplier")
    half_spread = PythonDecimal("0")
    if bid is not None and ask is not None:
        bid_value, ask_value = _d(bid), _d(ask)
        if bid_value <= 0 or ask_value < bid_value:
            raise ValueError("invalid bid/ask")
        half_spread = (ask_value - bid_value) / 2
    adverse = max(reference * PythonDecimal("0.0005"), half_spread) * multiplier
    fill = reference + adverse if side == "BUY" else reference - adverse
    commission = max(quantity * PythonDecimal("0.005"), PythonDecimal("1.00"))
    regulatory = _d(regulatory_fee)
    if regulatory < 0:
        raise ValueError("regulatory_fee must be non-negative")
    return ExecutionCost(fill, commission, regulatory, quantity * adverse)


def futures_execution(
    side: str,
    contracts,
    reference_price,
    *,
    tick_size,
    multiplier,
    regulatory_fee="0",
    slippage_multiplier="1",
) -> ExecutionCost:
    side = _side(side)
    contracts = _positive(contracts, "contracts")
    reference = _positive(reference_price, "reference_price")
    tick = _positive(tick_size, "tick_size")
    contract_multiplier = _positive(multiplier, "multiplier")
    adverse = tick * _positive(slippage_multiplier, "slippage_multiplier")
    fill = reference + adverse if side == "BUY" else reference - adverse
    commission = contracts * PythonDecimal("2.50")
    regulatory = _d(regulatory_fee)
    if regulatory < 0:
        raise ValueError("regulatory_fee must be non-negative")
    slippage = contracts * adverse * contract_multiplier
    return ExecutionCost(fill, commission, regulatory, slippage)


def option_execution(
    side: str,
    contracts,
    *,
    bid,
    ask,
    min_tick,
    regulatory_fee="0",
    slippage_multiplier="1",
) -> ExecutionCost:
    side = _side(side)
    contracts = _positive(contracts, "contracts")
    bid_value, ask_value = _positive(bid, "bid"), _positive(ask, "ask")
    if ask_value < bid_value:
        raise ValueError("ask must not be below bid")
    tick = _positive(min_tick, "min_tick")
    mid = (bid_value + ask_value) / 2
    multiplier = _positive(slippage_multiplier, "slippage_multiplier")
    adverse = (ask_value - bid_value) * PythonDecimal("0.25") * multiplier
    raw = mid + adverse
    rounding = ROUND_CEILING
    if side == "SELL":
        raw = mid - adverse
        rounding = ROUND_FLOOR
    fill = (raw / tick).to_integral_value(rounding=rounding) * tick
    commission = max(contracts * PythonDecimal("0.65"), PythonDecimal("1.00"))
    regulatory = _d(regulatory_fee)
    if regulatory < 0:
        raise ValueError("regulatory_fee must be non-negative")
    slippage = contracts * abs(fill - mid) * PythonDecimal("100")
    return ExecutionCost(fill, commission, regulatory, slippage)
