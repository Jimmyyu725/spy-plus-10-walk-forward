from AlgorithmImports import *

from execution import (
    EQUITY_TAF_MAXIMUM,
    EQUITY_TAF_PER_SHARE,
    FUTURE_REGULATORY_PER_CONTRACT,
    OPTION_TAF_PER_CONTRACT,
    SECTION31_MAX_RATE_PER_DOLLAR,
)


class IntegratedFeeModel(FeeModel):
    """Frozen commissions plus a conservative 2015-2026 regulatory overlay."""

    def get_order_fee(self, parameters):
        security = parameters.security
        order = parameters.order
        quantity = abs(float(order.quantity))
        if quantity == 0:
            return OrderFee(CashAmount(0, "USD"))
        is_sell = float(order.quantity) < 0
        price = max(0.0, float(security.price))
        if security.type == SecurityType.EQUITY:
            commission = max(quantity * 0.005, 1.0)
            regulatory = 0.0
            if is_sell:
                regulatory += (
                    quantity * price * float(SECTION31_MAX_RATE_PER_DOLLAR)
                )
                regulatory += min(
                    quantity * float(EQUITY_TAF_PER_SHARE),
                    float(EQUITY_TAF_MAXIMUM),
                )
        elif security.type == SecurityType.FUTURE:
            commission = quantity * 2.50
            regulatory = quantity * float(FUTURE_REGULATORY_PER_CONTRACT)
        elif security.type == SecurityType.OPTION:
            commission = max(quantity * 0.65, 1.0)
            regulatory = 0.0
            if is_sell:
                multiplier = float(security.symbol_properties.contract_multiplier)
                regulatory += (
                    quantity
                    * price
                    * multiplier
                    * float(SECTION31_MAX_RATE_PER_DOLLAR)
                )
                regulatory += quantity * float(OPTION_TAF_PER_CONTRACT)
        else:
            raise ValueError(f"unsupported integrated fee security: {security.type}")
        return OrderFee(CashAmount(commission + regulatory, "USD"))


class EquityAdverseSlippageModel:
    def __init__(self, multiplier):
        self._multiplier = float(multiplier)
        if self._multiplier not in {1.0, 2.0}:
            raise ValueError("slippage multiplier must be 1 or 2")

    def get_slippage_approximation(self, asset, order):
        half_spread = 0.0
        if asset.bid_price > 0 and asset.ask_price >= asset.bid_price:
            half_spread = float(asset.ask_price - asset.bid_price) / 2
        adverse = max(float(asset.price) * 0.0005, half_spread)
        return adverse * self._multiplier


class FutureOneTickSlippageModel:
    def __init__(self, multiplier):
        self._multiplier = float(multiplier)
        if self._multiplier not in {1.0, 2.0}:
            raise ValueError("slippage multiplier must be 1 or 2")

    def get_slippage_approximation(self, asset, order):
        tick = float(asset.symbol_properties.minimum_price_variation)
        return tick * self._multiplier


class OptionAdverseSlippageModel:
    """Adverse per-leg slippage for the near-expiry atomic market fallback."""

    def __init__(self, multiplier):
        self._multiplier = float(multiplier)
        if self._multiplier not in {1.0, 2.0}:
            raise ValueError("slippage multiplier must be 1 or 2")

    def get_slippage_approximation(self, asset, order):
        tick = float(asset.symbol_properties.minimum_price_variation)
        spread_fraction = 0.0
        if asset.bid_price >= 0 and asset.ask_price >= asset.bid_price:
            spread_fraction = float(asset.ask_price - asset.bid_price) * 0.25
        return max(tick, spread_fraction) * self._multiplier
