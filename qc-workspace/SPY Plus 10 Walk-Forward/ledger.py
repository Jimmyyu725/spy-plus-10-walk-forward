from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as PythonDecimal


def _d(value) -> PythonDecimal:
    return value if isinstance(value, PythonDecimal) else PythonDecimal(str(value))


class LedgerError(RuntimeError):
    """Raised when prices or account identities cannot be reconciled."""


@dataclass(frozen=True)
class LedgerSnapshot:
    as_of: date
    cash: PythonDecimal
    market_value: PythonDecimal
    equity: PythonDecimal
    fees: PythonDecimal
    margin_used: PythonDecimal


class CashLedger:
    def __init__(self, initial_cash):
        self.cash = _d(initial_cash)
        if self.cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.positions: dict[str, PythonDecimal] = {}
        self.total_fees = PythonDecimal("0")
        self.margin_used = PythonDecimal("0")

    def book_fill(
        self,
        symbol: str,
        quantity,
        fill_price,
        *,
        commission="0",
        regulatory_fee="0",
    ) -> None:
        quantity_value = _d(quantity)
        price = _d(fill_price)
        fees = _d(commission) + _d(regulatory_fee)
        if not symbol or quantity_value == 0 or price <= 0 or fees < 0:
            raise LedgerError("invalid fill")
        self.cash -= quantity_value * price + fees
        new_quantity = self.positions.get(symbol, PythonDecimal("0")) + quantity_value
        if new_quantity == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = new_quantity
        self.total_fees += fees

    def set_margin_used(self, amount) -> None:
        amount = _d(amount)
        if amount < 0:
            raise LedgerError("margin_used must be non-negative")
        self.margin_used = amount

    def mark_to_market(self, prices: dict[str, object], as_of: date) -> LedgerSnapshot:
        market_value = PythonDecimal("0")
        for symbol, quantity in self.positions.items():
            if symbol not in prices:
                raise LedgerError(f"missing mark for held security: {symbol}")
            price = _d(prices[symbol])
            if price <= 0:
                raise LedgerError(f"non-positive mark for held security: {symbol}")
            market_value += quantity * price
        equity = self.cash + market_value
        if equity <= 0 or self.margin_used > equity:
            raise LedgerError("account equity or margin invariant failed")
        return LedgerSnapshot(
            as_of,
            self.cash,
            market_value,
            equity,
            self.total_fees,
            self.margin_used,
        )
