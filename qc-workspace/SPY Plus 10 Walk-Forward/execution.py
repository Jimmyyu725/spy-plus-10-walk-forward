from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as PythonDecimal

from costs import equity_execution, futures_execution, option_execution


SECTION31_MAX_RATE_PER_DOLLAR = PythonDecimal("0.0000278")
EQUITY_TAF_PER_SHARE = PythonDecimal("0.000195")
EQUITY_TAF_MAXIMUM = PythonDecimal("9.79")
OPTION_TAF_PER_CONTRACT = PythonDecimal("0.00329")
FUTURE_REGULATORY_PER_CONTRACT = PythonDecimal("0.02")
REGULATORY_POLICY_STATUS = "CONSERVATIVE_MAX_2015_2026_SELL_SIDE_OVERLAY"


def _d(value) -> PythonDecimal:
    return value if isinstance(value, PythonDecimal) else PythonDecimal(str(value))


@dataclass(frozen=True)
class IntegratedExecution:
    fill_price: PythonDecimal | None
    commission: PythonDecimal
    section31_fee: PythonDecimal
    taf_fee: PythonDecimal
    other_regulatory_fee: PythonDecimal
    regulatory_fee: PythonDecimal
    slippage: PythonDecimal

    @property
    def total_cost(self) -> PythonDecimal:
        return self.commission + self.regulatory_fee + self.slippage


def integrated_execution(
    asset_class: str,
    side: str,
    filled_quantity,
    *,
    reference_price=None,
    bid=None,
    ask=None,
    tick_size=None,
    min_tick=None,
    contract_multiplier=1,
    slippage_multiplier=1,
) -> IntegratedExecution:
    asset = asset_class.upper()
    side = side.upper()
    if asset not in {"EQUITY", "FUTURE", "OPTION"}:
        raise ValueError("unsupported asset class")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    quantity = _d(filled_quantity)
    multiplier = _d(contract_multiplier)
    slip = _d(slippage_multiplier)
    if quantity < 0 or multiplier <= 0:
        raise ValueError("quantity and multiplier are invalid")
    if slip not in {PythonDecimal("1"), PythonDecimal("2")}:
        raise ValueError("slippage multiplier must be 1 or 2")
    if quantity == 0:
        zero = PythonDecimal("0")
        return IntegratedExecution(None, zero, zero, zero, zero, zero, zero)

    section31 = PythonDecimal("0")
    taf = PythonDecimal("0")
    other = PythonDecimal("0")
    if asset == "EQUITY":
        reference = _d(reference_price)
        if reference <= 0:
            raise ValueError("reference price must be positive")
        if side == "SELL":
            section31 = quantity * reference * SECTION31_MAX_RATE_PER_DOLLAR
            taf = min(quantity * EQUITY_TAF_PER_SHARE, EQUITY_TAF_MAXIMUM)
        regulatory = section31 + taf
        cost = equity_execution(
            side,
            quantity,
            reference,
            bid=bid,
            ask=ask,
            regulatory_fee=regulatory,
            slippage_multiplier=slip,
        )
        monetary_slippage = cost.slippage
    elif asset == "FUTURE":
        other = quantity * FUTURE_REGULATORY_PER_CONTRACT
        regulatory = other
        cost = futures_execution(
            side,
            quantity,
            reference_price,
            tick_size=tick_size,
            multiplier=multiplier,
            regulatory_fee=regulatory,
            slippage_multiplier=slip,
        )
        monetary_slippage = cost.slippage
    else:
        bid_value, ask_value = _d(bid), _d(ask)
        if bid_value <= 0 or ask_value < bid_value:
            raise ValueError("option quote is invalid")
        mid = (bid_value + ask_value) / 2
        if side == "SELL":
            notional = quantity * mid * multiplier
            section31 = notional * SECTION31_MAX_RATE_PER_DOLLAR
            taf = quantity * OPTION_TAF_PER_CONTRACT
        regulatory = section31 + taf
        cost = option_execution(
            side,
            quantity,
            bid=bid_value,
            ask=ask_value,
            min_tick=min_tick,
            regulatory_fee=regulatory,
            slippage_multiplier=slip,
        )
        monetary_slippage = quantity * abs(cost.fill_price - mid) * multiplier
    return IntegratedExecution(
        cost.fill_price,
        cost.commission,
        section31,
        taf,
        other,
        regulatory,
        monetary_slippage,
    )
