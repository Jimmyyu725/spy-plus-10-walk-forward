from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


EXPECTED_CONTRACT = {
    "annual_hurdle_percentage_points": "0.10",
    "benchmark": "SPY",
    "costs": {
        "equity": {
            "commission_per_share": "0.005",
            "minimum_order_commission": "1.00",
            "minimum_slippage_bps": "5",
        },
        "future": {
            "commission_per_contract_per_side": "2.50",
            "minimum_slippage_ticks": "1",
        },
        "option": {
            "commission_per_contract_per_side": "0.65",
            "minimum_order_commission": "1.00",
            "spread_fraction": "0.25",
        },
    },
    "current_year_label": "PARTIAL_YEAR",
    "evaluation_start": "2015-01-01",
    "formal_evaluation": False,
    "initial_cash": "1000000",
    "live_trading": False,
    "project_name": "SPY Plus 10 Walk-Forward",
    "schema_version": 1,
    "taxes_included": False,
}


class BaselineContractError(RuntimeError):
    """Raised when the frozen audit contract is absent or changed."""


@dataclass(frozen=True)
class BaselineContract:
    initial_cash: str
    annual_hurdle_percentage_points: str
    evaluation_start: str
    formal_evaluation: bool
    live_trading: bool


def load_baseline_contract(path: Path) -> BaselineContract:
    if not path.is_file():
        raise BaselineContractError(f"missing contract: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineContractError(f"invalid contract JSON: {path}") from exc
    if raw != EXPECTED_CONTRACT:
        if isinstance(raw, dict) and raw.get("live_trading") is True:
            raise BaselineContractError("live_trading must remain false")
        raise BaselineContractError("contract mismatch")
    return BaselineContract(
        initial_cash=raw["initial_cash"],
        annual_hurdle_percentage_points=raw["annual_hurdle_percentage_points"],
        evaluation_start=raw["evaluation_start"],
        formal_evaluation=raw["formal_evaluation"],
        live_trading=raw["live_trading"],
    )
