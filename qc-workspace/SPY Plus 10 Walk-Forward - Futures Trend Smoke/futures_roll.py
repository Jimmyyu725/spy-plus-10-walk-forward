from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


class RollSelectionError(RuntimeError):
    """Raised when no presently tradable actual contract can be selected."""


@dataclass(frozen=True)
class ContractSnapshot:
    symbol: str
    expiry: date
    price: float
    volume: int
    open_interest: int


def select_volume_contract(
    contracts: list[ContractSnapshot],
    as_of: date,
    *,
    expiry_buffer_days: int = 7,
) -> ContractSnapshot:
    cutoff = as_of + timedelta(days=expiry_buffer_days)
    valid = [
        contract
        for contract in contracts
        if contract.symbol
        and contract.expiry > cutoff
        and contract.price > 0
        and contract.volume > 0
        and contract.open_interest >= 0
    ]
    if not valid:
        raise RollSelectionError("no valid actual contract")
    return sorted(
        valid,
        key=lambda contract: (
            -contract.volume,
            -contract.open_interest,
            contract.expiry,
            contract.symbol,
        ),
    )[0]
