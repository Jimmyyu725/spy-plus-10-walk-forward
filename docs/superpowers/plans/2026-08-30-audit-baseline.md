# Audit Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 QuantConnect 云端项目中建立冻结的 SPY 基准、现实成本、守恒账本、逐年 `SPY+10` 门禁和只追加审计记录，并用纯人工夹具完成本地验证与云端编译烟雾测试。

**Architecture:** 可复用的运行时代码直接放在 `qc-workspace/SPY Plus 10 Walk-Forward/`，因此 LEAN Cloud 能直接导入；本地 `unittest` 通过显式项目路径加载相同源码，不维护第二份实现。模块只消费调用者传入的时间序列和成交数据，不访问本地或未来市场数据；正式评价仍保持关闭。

**Tech Stack:** Python 3.12 standard library, `decimal`, `dataclasses`, `unittest`, LEAN CLI, QuantConnect Cloud, Git.

---

## Scope and file map

- Create: `qc-workspace/SPY Plus 10 Walk-Forward/baseline-contract.json` — 冻结门槛、资金、成本和安全边界。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/baseline.py` — 加载并严格验证合同。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/costs.py` — 股票、期货和期权基础/双倍滑点成本。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/ledger.py` — 现金证券成交、估值、费用和守恒检查。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/benchmark.py` — 使用含分红单位价格生成独立 SPY 买入持有基准。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/metrics.py` — 对齐共同日期并计算逐年收益、10 个百分点门槛和总状态。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/audit.py` — 校验时间因果关系的只追加 JSONL 审计记录。
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/main.py` — 导入并执行无行情依赖的 baseline 自检，保留一周 smoke 范围。
- Create: `tests/project_path.py` — 本地测试加载云端项目源码的唯一适配器。
- Create: `tests/test_baseline_contract.py` — 合同失败关闭测试。
- Create: `tests/test_costs.py` — 三类资产成本与压力测试。
- Create: `tests/test_ledger_benchmark.py` — 守恒账本和 SPY 基准测试。
- Create: `tests/test_metrics.py` — 完整年、部分年、共同日期与门禁测试。
- Create: `tests/test_audit.py` — 因果顺序和 JSONL 不可变记录测试。
- Create: `scripts/verify_audit_baseline.py` — 仓库级验证入口。
- Create: `scripts/write_audit_baseline_record.py` — 从实际云端结果 URL 生成证据文档。
- Create: `spy_plus_10/audit_baseline_record.py` — 云端证据文档生成器。
- Create: `tests/test_audit_baseline_record.py` — 证据生成器测试。
- Create after cloud run: `docs/audit-baseline.md` — 实际提交、项目、编译和 backtest 证据。

权威设计：[2026-08-30-spy-plus-10-walk-forward-design.md](../specs/2026-08-30-spy-plus-10-walk-forward-design.md)。本里程碑不实现 Alpha 信号、组合风险分配、实盘或正式 2015–最新回测。

### Task 1: Freeze and validate the audit baseline contract

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/baseline-contract.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/baseline.py`
- Create: `tests/project_path.py`
- Create: `tests/test_baseline_contract.py`

- [ ] **Step 1: Write the failing contract tests**

Create `tests/project_path.py`:

```python
from pathlib import Path
import sys


PROJECT_DIR = (
    Path(__file__).resolve().parents[1]
    / "qc-workspace"
    / "SPY Plus 10 Walk-Forward"
)
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
```

Create `tests/test_baseline_contract.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from tests.project_path import PROJECT_DIR
from baseline import BaselineContractError, load_baseline_contract


class BaselineContractTests(unittest.TestCase):
    def test_repository_contract_is_frozen_and_safe(self):
        contract = load_baseline_contract(PROJECT_DIR / "baseline-contract.json")
        self.assertEqual(contract.initial_cash, "1000000")
        self.assertEqual(contract.annual_hurdle_percentage_points, "0.10")
        self.assertEqual(contract.evaluation_start, "2015-01-01")
        self.assertFalse(contract.formal_evaluation)
        self.assertFalse(contract.live_trading)

    def test_contract_rejects_live_trading(self):
        source = json.loads(
            (PROJECT_DIR / "baseline-contract.json").read_text(encoding="utf-8")
        )
        source["live_trading"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(BaselineContractError, "live_trading"):
                load_baseline_contract(path)

    def test_contract_rejects_changed_hurdle(self):
        source = json.loads(
            (PROJECT_DIR / "baseline-contract.json").read_text(encoding="utf-8")
        )
        source["annual_hurdle_percentage_points"] = "0.09"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(BaselineContractError, "contract mismatch"):
                load_baseline_contract(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```bash
python3 -m unittest tests/test_baseline_contract.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'baseline'`.

- [ ] **Step 3: Add the frozen contract and strict loader**

Create `qc-workspace/SPY Plus 10 Walk-Forward/baseline-contract.json`:

```json
{
  "annual_hurdle_percentage_points": "0.10",
  "benchmark": "SPY",
  "costs": {
    "equity": {
      "commission_per_share": "0.005",
      "minimum_order_commission": "1.00",
      "minimum_slippage_bps": "5"
    },
    "future": {
      "commission_per_contract_per_side": "2.50",
      "minimum_slippage_ticks": "1"
    },
    "option": {
      "commission_per_contract_per_side": "0.65",
      "minimum_order_commission": "1.00",
      "spread_fraction": "0.25"
    }
  },
  "current_year_label": "PARTIAL_YEAR",
  "evaluation_start": "2015-01-01",
  "formal_evaluation": false,
  "initial_cash": "1000000",
  "live_trading": false,
  "project_name": "SPY Plus 10 Walk-Forward",
  "schema_version": 1,
  "taxes_included": false
}
```

Create `qc-workspace/SPY Plus 10 Walk-Forward/baseline.py`:

```python
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
```

- [ ] **Step 4: Run the contract tests**

Run: `python3 -m unittest tests/test_baseline_contract.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit the frozen contract**

```bash
git add tests/project_path.py tests/test_baseline_contract.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/baseline-contract.json" \
  "qc-workspace/SPY Plus 10 Walk-Forward/baseline.py"
git diff --cached --check
git commit -m "feat: freeze audit baseline contract"
```

### Task 2: Implement deterministic transaction costs

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/costs.py`
- Create: `tests/test_costs.py`

- [ ] **Step 1: Write failing cost tests**

Create `tests/test_costs.py`:

```python
import unittest
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from costs import (
    equity_execution,
    futures_execution,
    option_execution,
)


class CostModelTests(unittest.TestCase):
    def test_equity_commission_floor_and_half_spread(self):
        cost = equity_execution("BUY", 10, "100", bid="99.90", ask="100.10")
        self.assertEqual(cost.commission, Decimal("1.00"))
        self.assertEqual(cost.fill_price, Decimal("100.10"))
        self.assertEqual(cost.slippage, Decimal("1.00"))

    def test_equity_uses_five_bps_when_larger(self):
        cost = equity_execution("SELL", 1000, "100", bid="99.99", ask="100.01")
        self.assertEqual(cost.commission, Decimal("5.000"))
        self.assertEqual(cost.fill_price, Decimal("99.9500"))
        self.assertEqual(cost.slippage, Decimal("50.0000"))

    def test_double_slippage_changes_slippage_not_commission(self):
        base = equity_execution("BUY", 10, "100")
        stress = equity_execution("BUY", 10, "100", slippage_multiplier="2")
        self.assertEqual(stress.commission, base.commission)
        self.assertEqual(stress.slippage, base.slippage * 2)

    def test_futures_cost_has_fee_floor_and_one_tick(self):
        cost = futures_execution("BUY", 2, "5000", tick_size="0.25", multiplier="50")
        self.assertEqual(cost.commission, Decimal("5.00"))
        self.assertEqual(cost.fill_price, Decimal("5000.25"))
        self.assertEqual(cost.slippage, Decimal("25.00"))

    def test_option_cost_uses_quarter_spread_and_tick(self):
        cost = option_execution("SELL", 1, bid="1.00", ask="1.20", min_tick="0.01")
        self.assertEqual(cost.commission, Decimal("1.00"))
        self.assertEqual(cost.fill_price, Decimal("1.05"))
        self.assertEqual(cost.slippage, Decimal("5.00"))

    def test_regulatory_fee_is_explicit(self):
        cost = equity_execution("SELL", 100, "10", regulatory_fee="0.03")
        self.assertEqual(cost.regulatory_fee, Decimal("0.03"))
        self.assertEqual(cost.total_cost, cost.commission + cost.regulatory_fee + cost.slippage)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run: `python3 -m unittest tests/test_costs.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'costs'`.

- [ ] **Step 3: Implement the minimal cost module**

Create `qc-workspace/SPY Plus 10 Walk-Forward/costs.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _side(value: str) -> str:
    value = value.upper()
    if value not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return value


def _positive(value, name: str) -> Decimal:
    result = _d(value)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


@dataclass(frozen=True)
class ExecutionCost:
    fill_price: Decimal
    commission: Decimal
    regulatory_fee: Decimal
    slippage: Decimal

    @property
    def total_cost(self) -> Decimal:
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
    half_spread = Decimal("0")
    if bid is not None and ask is not None:
        bid_value, ask_value = _d(bid), _d(ask)
        if bid_value <= 0 or ask_value < bid_value:
            raise ValueError("invalid bid/ask")
        half_spread = (ask_value - bid_value) / 2
    adverse = max(reference * Decimal("0.0005"), half_spread) * multiplier
    fill = reference + adverse if side == "BUY" else reference - adverse
    commission = max(quantity * Decimal("0.005"), Decimal("1.00"))
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
    commission = contracts * Decimal("2.50")
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
    adverse = (ask_value - bid_value) * Decimal("0.25")
    raw = mid + adverse * _positive(slippage_multiplier, "slippage_multiplier")
    rounding = ROUND_CEILING
    if side == "SELL":
        raw = mid - adverse * _positive(slippage_multiplier, "slippage_multiplier")
        rounding = ROUND_FLOOR
    fill = (raw / tick).to_integral_value(rounding=rounding) * tick
    commission = max(contracts * Decimal("0.65"), Decimal("1.00"))
    regulatory = _d(regulatory_fee)
    if regulatory < 0:
        raise ValueError("regulatory_fee must be non-negative")
    slippage = contracts * abs(fill - mid) * Decimal("100")
    return ExecutionCost(fill, commission, regulatory, slippage)
```

- [ ] **Step 4: Run the cost tests**

Run: `python3 -m unittest tests/test_costs.py -v`

Expected: 6 tests PASS.

- [ ] **Step 5: Commit the cost module**

```bash
git add tests/test_costs.py "qc-workspace/SPY Plus 10 Walk-Forward/costs.py"
git diff --cached --check
git commit -m "feat: add deterministic transaction costs"
```

### Task 3: Implement the conserving ledger and SPY benchmark

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/ledger.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/benchmark.py`
- Create: `tests/test_ledger_benchmark.py`

- [ ] **Step 1: Write failing ledger and benchmark tests**

Create `tests/test_ledger_benchmark.py`:

```python
import unittest
from datetime import date
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from benchmark import PricePoint, build_spy_buy_hold
from ledger import CashLedger, LedgerError


class LedgerAndBenchmarkTests(unittest.TestCase):
    def test_buy_mark_sell_conserves_cash_and_equity(self):
        ledger = CashLedger("1000")
        ledger.book_fill("SPY", 5, "100", commission="1")
        first = ledger.mark_to_market({"SPY": "100"}, date(2015, 1, 2))
        self.assertEqual(first.cash, Decimal("499"))
        self.assertEqual(first.equity, Decimal("999"))
        marked = ledger.mark_to_market({"SPY": "105"}, date(2015, 1, 5))
        self.assertEqual(marked.equity, Decimal("1024"))
        ledger.book_fill("SPY", -5, "105", commission="1")
        final = ledger.mark_to_market({}, date(2015, 1, 6))
        self.assertEqual(final.cash, Decimal("1023"))
        self.assertEqual(final.equity, Decimal("1023"))
        self.assertEqual(ledger.total_fees, Decimal("2"))

    def test_missing_held_price_fails_closed(self):
        ledger = CashLedger("1000")
        ledger.book_fill("SPY", 1, "100")
        with self.assertRaisesRegex(LedgerError, "missing mark"):
            ledger.mark_to_market({}, date(2015, 1, 2))

    def test_benchmark_charges_entry_and_reports_exit_sensitivity(self):
        result = build_spy_buy_hold(
            [PricePoint(date(2015, 1, 2), "100"), PricePoint(date(2015, 12, 31), "110")],
            initial_cash="1000",
        )
        self.assertEqual(result.shares, Decimal("9"))
        self.assertEqual(result.equity[0].value, Decimal("998.5500"))
        self.assertEqual(result.equity[-1].value, Decimal("1088.5500"))
        self.assertLess(result.liquidation_value, result.equity[-1].value)

    def test_benchmark_rejects_duplicate_or_non_increasing_dates(self):
        points = [PricePoint(date(2015, 1, 2), "100"), PricePoint(date(2015, 1, 2), "101")]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_spy_buy_hold(points, initial_cash="1000")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run: `python3 -m unittest tests/test_ledger_benchmark.py -v`

Expected: FAIL because `benchmark` or `ledger` is missing.

- [ ] **Step 3: Implement the ledger**

Create `qc-workspace/SPY Plus 10 Walk-Forward/ledger.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class LedgerError(RuntimeError):
    """Raised when prices or account identities cannot be reconciled."""


@dataclass(frozen=True)
class LedgerSnapshot:
    as_of: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    fees: Decimal
    margin_used: Decimal


class CashLedger:
    def __init__(self, initial_cash):
        self.cash = _d(initial_cash)
        if self.cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.positions: dict[str, Decimal] = {}
        self.total_fees = Decimal("0")
        self.margin_used = Decimal("0")

    def book_fill(self, symbol: str, quantity, fill_price, *, commission="0", regulatory_fee="0"):
        quantity_value = _d(quantity)
        price = _d(fill_price)
        fees = _d(commission) + _d(regulatory_fee)
        if not symbol or quantity_value == 0 or price <= 0 or fees < 0:
            raise LedgerError("invalid fill")
        self.cash -= quantity_value * price + fees
        new_quantity = self.positions.get(symbol, Decimal("0")) + quantity_value
        if new_quantity == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = new_quantity
        self.total_fees += fees

    def set_margin_used(self, amount):
        amount = _d(amount)
        if amount < 0:
            raise LedgerError("margin_used must be non-negative")
        self.margin_used = amount

    def mark_to_market(self, prices: dict[str, object], as_of: date) -> LedgerSnapshot:
        market_value = Decimal("0")
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
        return LedgerSnapshot(as_of, self.cash, market_value, equity, self.total_fees, self.margin_used)
```

- [ ] **Step 4: Implement the independent SPY benchmark**

Create `qc-workspace/SPY Plus 10 Walk-Forward/benchmark.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR

from costs import equity_execution


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class PricePoint:
    as_of: date
    total_return_price: Decimal

    def __init__(self, as_of: date, total_return_price):
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "total_return_price", _d(total_return_price))


@dataclass(frozen=True)
class EquityPoint:
    as_of: date
    value: Decimal


@dataclass(frozen=True)
class BenchmarkResult:
    shares: Decimal
    entry_cash: Decimal
    equity: tuple[EquityPoint, ...]
    liquidation_value: Decimal


def build_spy_buy_hold(points: list[PricePoint], *, initial_cash) -> BenchmarkResult:
    if not points:
        raise ValueError("at least one SPY price is required")
    if any(point.total_return_price <= 0 for point in points):
        raise ValueError("SPY prices must be positive")
    if any(left.as_of >= right.as_of for left, right in zip(points, points[1:])):
        raise ValueError("SPY dates must be strictly increasing")
    cash = _d(initial_cash)
    entry = equity_execution("BUY", 1, points[0].total_return_price)
    shares = ((cash - entry.commission) / entry.fill_price).to_integral_value(
        rounding=ROUND_FLOOR
    )
    actual_entry = equity_execution("BUY", shares, points[0].total_return_price)
    entry_cash = cash - shares * actual_entry.fill_price - actual_entry.commission
    equity = tuple(
        EquityPoint(point.as_of, entry_cash + shares * point.total_return_price)
        for point in points
    )
    exit_cost = equity_execution("SELL", shares, points[-1].total_return_price)
    liquidation = entry_cash + shares * exit_cost.fill_price - exit_cost.commission
    return BenchmarkResult(shares, entry_cash, equity, liquidation)
```

- [ ] **Step 5: Run the ledger and benchmark tests**

Run: `python3 -m unittest tests/test_ledger_benchmark.py -v`

Expected: 4 tests PASS.

- [ ] **Step 6: Commit ledger and benchmark**

```bash
git add tests/test_ledger_benchmark.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/ledger.py" \
  "qc-workspace/SPY Plus 10 Walk-Forward/benchmark.py"
git diff --cached --check
git commit -m "feat: add conserving ledger and SPY benchmark"
```

### Task 4: Implement annual returns and the SPY plus 10 gate

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write failing annual-gate tests**

Create `tests/test_metrics.py`:

```python
import unittest
from datetime import date
from decimal import Decimal

from tests.project_path import PROJECT_DIR  # noqa: F401
from metrics import EquityPoint, MetricsError, evaluate_annual_gates


class AnnualGateTests(unittest.TestCase):
    def test_negative_ten_spy_requires_zero_strategy(self):
        strategy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 31), "100")]
        spy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 31), "90")]
        result = evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2015, 12, 31))
        self.assertEqual(result.rows[0].hurdle_return, Decimal("0.00"))
        self.assertEqual(result.rows[0].status, "PASS")

    def test_positive_ten_spy_requires_positive_twenty(self):
        strategy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 31), "119.99")]
        spy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 31), "110")]
        result = evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2015, 12, 31))
        self.assertEqual(result.rows[0].hurdle_return, Decimal("0.20"))
        self.assertEqual(result.rows[0].status, "FAIL")
        self.assertEqual(result.overall_status, "FAIL")

    def test_current_year_is_marked_partial(self):
        strategy = [EquityPoint(date(2026, 1, 2), "100"), EquityPoint(date(2026, 8, 28), "120")]
        spy = [EquityPoint(date(2026, 1, 2), "100"), EquityPoint(date(2026, 8, 28), "109")]
        result = evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2026, 8, 30))
        self.assertEqual(result.rows[0].period, "PARTIAL_YEAR")
        self.assertEqual(result.rows[0].status, "PASS")

    def test_historical_year_uses_last_common_trading_date(self):
        strategy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 30), "120")]
        spy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 30), "110")]
        result = evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2026, 8, 30))
        self.assertEqual(result.rows[0].period, "FULL_YEAR")

    def test_missing_calendar_year_fails_closed(self):
        strategy = [EquityPoint(date(2015, 12, 31), "100"), EquityPoint(date(2017, 12, 29), "120")]
        spy = [EquityPoint(date(2015, 12, 31), "100"), EquityPoint(date(2017, 12, 29), "110")]
        with self.assertRaisesRegex(MetricsError, "missing calendar year"):
            evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2017, 12, 31))

    def test_series_use_only_common_dates(self):
        strategy = [
            EquityPoint(date(2015, 1, 2), "100"),
            EquityPoint(date(2015, 12, 30), "150"),
            EquityPoint(date(2015, 12, 31), "120"),
        ]
        spy = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 12, 31), "110")]
        result = evaluate_annual_gates(strategy, spy, initial_value="100", as_of=date(2015, 12, 31))
        self.assertEqual(result.rows[0].strategy_return, Decimal("0.20"))

    def test_duplicate_dates_fail_closed(self):
        duplicate = [EquityPoint(date(2015, 1, 2), "100"), EquityPoint(date(2015, 1, 2), "101")]
        with self.assertRaisesRegex(MetricsError, "strictly increasing"):
            evaluate_annual_gates(duplicate, duplicate, initial_value="100", as_of=date(2015, 12, 31))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run: `python3 -m unittest tests/test_metrics.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'metrics'`.

- [ ] **Step 3: Implement the annual gate**

Create `qc-workspace/SPY Plus 10 Walk-Forward/metrics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class MetricsError(RuntimeError):
    """Raised when aligned equity evidence is insufficient or inconsistent."""


@dataclass(frozen=True)
class EquityPoint:
    as_of: date
    value: Decimal

    def __init__(self, as_of: date, value):
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "value", _d(value))


@dataclass(frozen=True)
class AnnualGateRow:
    year: int
    period: str
    start_date: date
    end_date: date
    strategy_return: Decimal
    spy_return: Decimal
    excess_return: Decimal
    hurdle_return: Decimal
    status: str


@dataclass(frozen=True)
class AnnualGateResult:
    rows: tuple[AnnualGateRow, ...]
    overall_status: str


def _validated_map(points: list[EquityPoint], label: str) -> dict[date, Decimal]:
    if not points:
        raise MetricsError(f"missing {label} equity")
    if any(left.as_of >= right.as_of for left, right in zip(points, points[1:])):
        raise MetricsError(f"{label} dates must be strictly increasing")
    if any(point.value <= 0 for point in points):
        raise MetricsError(f"{label} equity must be positive")
    return {point.as_of: point.value for point in points}


def evaluate_annual_gates(
    strategy: list[EquityPoint],
    spy: list[EquityPoint],
    *,
    initial_value,
    as_of: date,
) -> AnnualGateResult:
    strategy_map = _validated_map(strategy, "strategy")
    spy_map = _validated_map(spy, "SPY")
    common_dates = sorted(set(strategy_map) & set(spy_map))
    if not common_dates:
        raise MetricsError("no common valuation dates")
    initial = _d(initial_value)
    if initial <= 0:
        raise MetricsError("initial_value must be positive")
    years = sorted({day.year for day in common_dates})
    if years != list(range(years[0], years[-1] + 1)):
        raise MetricsError("missing calendar year in common equity series")
    rows = []
    prior_strategy = prior_spy = initial
    for year in years:
        year_dates = [day for day in common_dates if day.year == year]
        start, end = year_dates[0], year_dates[-1]
        strategy_return = strategy_map[end] / prior_strategy - 1
        spy_return = spy_map[end] / prior_spy - 1
        hurdle = spy_return + Decimal("0.10")
        period = (
            "PARTIAL_YEAR"
            if year == as_of.year and as_of < date(year, 12, 31)
            else "FULL_YEAR"
        )
        status = "PASS" if strategy_return >= hurdle else "FAIL"
        rows.append(
            AnnualGateRow(
                year,
                period,
                start,
                end,
                strategy_return,
                spy_return,
                strategy_return - spy_return,
                hurdle,
                status,
            )
        )
        prior_strategy, prior_spy = strategy_map[end], spy_map[end]
    overall = "PASS" if all(row.status == "PASS" for row in rows) else "FAIL"
    return AnnualGateResult(tuple(rows), overall)
```

- [ ] **Step 4: Run the metrics tests**

Run: `python3 -m unittest tests/test_metrics.py -v`

Expected: 7 tests PASS.

- [ ] **Step 5: Commit the annual gate**

```bash
git add tests/test_metrics.py "qc-workspace/SPY Plus 10 Walk-Forward/metrics.py"
git diff --cached --check
git commit -m "feat: add annual SPY plus ten gate"
```

### Task 5: Implement causal append-only audit records

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write failing audit tests**

Create `tests/test_audit.py`:

```python
import json
import unittest
from datetime import datetime, timezone

from tests.project_path import PROJECT_DIR  # noqa: F401
from audit import AuditError, AuditEvent, AuditTrail


def moment(hour):
    return datetime(2015, 1, 5, hour, tzinfo=timezone.utc)


class AuditTrailTests(unittest.TestCase):
    def test_valid_event_serializes_deterministically(self):
        event = AuditEvent(
            sequence=1,
            module="benchmark",
            data_cutoff=moment(16),
            signal_time=moment(17),
            order_time=moment(18),
            fill_time=moment(19),
            inputs={"symbol": "SPY"},
            target={"weight": "1.0"},
            order={"quantity": "10"},
            risk={"live_trading": False},
        )
        trail = AuditTrail()
        trail.append(event)
        payload = json.loads(trail.to_jsonl())
        self.assertEqual(payload["sequence"], 1)
        self.assertEqual(payload["module"], "benchmark")

    def test_future_data_or_same_time_order_fails(self):
        event = AuditEvent(
            1, "benchmark", moment(17), moment(16), moment(16), moment(19), {}, {}, {}, {}
        )
        with self.assertRaisesRegex(AuditError, "causal order"):
            AuditTrail().append(event)

    def test_sequence_and_time_cannot_move_backwards(self):
        first = AuditEvent(1, "benchmark", moment(15), moment(16), moment(17), moment(18), {}, {}, {}, {})
        second = AuditEvent(1, "benchmark", moment(16), moment(17), moment(18), moment(19), {}, {}, {}, {})
        trail = AuditTrail()
        trail.append(first)
        with self.assertRaisesRegex(AuditError, "sequence"):
            trail.append(second)

    def test_returned_events_cannot_mutate_serialized_history(self):
        trail = AuditTrail()
        event = AuditEvent(1, "benchmark", moment(15), moment(16), moment(17), moment(18), {"x": 1}, {}, {}, {})
        trail.append(event)
        self.assertIsInstance(trail.events, tuple)
        trail.events[0]["inputs"]["x"] = 99
        self.assertEqual(json.loads(trail.to_jsonl())["inputs"]["x"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run: `python3 -m unittest tests/test_audit.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'audit'`.

- [ ] **Step 3: Implement the audit trail**

Create `qc-workspace/SPY Plus 10 Walk-Forward/audit.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime


class AuditError(RuntimeError):
    """Raised when an audit event violates ordering or immutability rules."""


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    module: str
    data_cutoff: datetime
    signal_time: datetime
    order_time: datetime
    fill_time: datetime
    inputs: dict
    target: dict
    order: dict
    risk: dict


class AuditTrail:
    def __init__(self):
        self._lines: list[str] = []
        self._last_sequence = 0
        self._last_fill_time: datetime | None = None

    @property
    def events(self) -> tuple[dict, ...]:
        return tuple(json.loads(line) for line in self._lines)

    def append(self, event: AuditEvent) -> None:
        if event.sequence <= 0 or not event.module:
            raise AuditError("invalid event identity")
        if not (
            event.data_cutoff < event.signal_time < event.order_time < event.fill_time
        ):
            raise AuditError("event violates causal order")
        if any(value.tzinfo is None for value in (
            event.data_cutoff, event.signal_time, event.order_time, event.fill_time
        )):
            raise AuditError("timestamps must be timezone-aware")
        if event.sequence != self._last_sequence + 1:
            raise AuditError("event sequence must increase by one")
        if self._last_fill_time is not None and event.fill_time < self._last_fill_time:
            raise AuditError("event time moved backwards")
        payload = asdict(event)
        for field in ("data_cutoff", "signal_time", "order_time", "fill_time"):
            payload[field] = payload[field].isoformat()
        try:
            line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise AuditError("event payload is not JSON serializable") from exc
        self._lines.append(line)
        self._last_sequence = event.sequence
        self._last_fill_time = event.fill_time

    def to_jsonl(self) -> str:
        return "\n".join(self._lines) + ("\n" if self._lines else "")
```

- [ ] **Step 4: Run the audit tests**

Run: `python3 -m unittest tests/test_audit.py -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit the audit trail**

```bash
git add tests/test_audit.py "qc-workspace/SPY Plus 10 Walk-Forward/audit.py"
git diff --cached --check
git commit -m "feat: add causal append-only audit trail"
```

### Task 6: Add repository validation and cloud evidence

**Files:**
- Create: `scripts/verify_audit_baseline.py`
- Create: `scripts/write_audit_baseline_record.py`
- Create: `spy_plus_10/audit_baseline_record.py`
- Create: `tests/test_audit_baseline_record.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/main.py`
- Create after run: `docs/audit-baseline.md`

- [ ] **Step 1: Write the failing repository and evidence tests**

Create `tests/test_audit_baseline_record.py`:

```python
import unittest

from spy_plus_10.audit_baseline_record import render_audit_baseline_record


class AuditBaselineRecordTests(unittest.TestCase):
    def test_record_is_non_formal_and_identifies_cloud_run(self):
        text = render_audit_baseline_record(
            lean_version="lean 1.0.229",
            git_commit="a" * 40,
            project_id="123456",
            backtest_id="abc-def",
            result_url="https://www.quantconnect.com/project/123456/abc-def",
            test_count=26,
        )
        self.assertIn("Formal evaluation: false", text)
        self.assertIn("Local fixture tests: 26 passed", text)
        self.assertIn("QuantConnect backtest ID: abc-def", text)


if __name__ == "__main__":
    unittest.main()
```

Append this test to `tests/test_baseline_contract.py` inside `BaselineContractTests`:

```python
    def test_cloud_main_imports_every_baseline_module(self):
        source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
        for marker in (
            "from audit import AuditTrail",
            "from baseline import load_baseline_contract",
            "from benchmark import PricePoint",
            "from costs import equity_execution",
            "from ledger import CashLedger",
            "from metrics import EquityPoint",
        ):
            self.assertIn(marker, source)
```

- [ ] **Step 2: Run the new tests and verify both fail for missing integration**

Run:

```bash
python3 -m unittest tests/test_audit_baseline_record.py -v
python3 -m unittest tests.test_baseline_contract.BaselineContractTests.test_cloud_main_imports_every_baseline_module -v
```

Expected: first FAILS with missing `spy_plus_10.audit_baseline_record`; second FAILS because imports are absent.

- [ ] **Step 3: Implement the evidence generator**

Create `spy_plus_10/audit_baseline_record.py`:

```python
from __future__ import annotations

import re


ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def render_audit_baseline_record(
    *,
    lean_version: str,
    git_commit: str,
    project_id: str,
    backtest_id: str,
    result_url: str,
    test_count: int,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", git_commit):
        raise ValueError("expected a full Git commit hash")
    if not ID_PATTERN.fullmatch(project_id) or not ID_PATTERN.fullmatch(backtest_id):
        raise ValueError("invalid cloud identifier")
    expected_url = f"https://www.quantconnect.com/project/{project_id}/{backtest_id}"
    if result_url != expected_url:
        raise ValueError("result URL does not match cloud identifiers")
    if test_count <= 0:
        raise ValueError("test_count must be positive")
    return f"""# QuantConnect Audit Baseline

- Purpose: baseline module compilation and bounded smoke test only
- Formal evaluation: false
- Live trading: disabled
- Initial cash: 1,000,000 USD
- Smoke range: 2015-01-02 through 2015-01-09
- LEAN CLI version: {lean_version.strip()}
- Git commit: {git_commit}
- Local fixture tests: {test_count} passed
- QuantConnect project ID: {project_id}
- QuantConnect backtest ID: {backtest_id}
- Result URL: {result_url}
- Cloud status: completed
"""
```

- [ ] **Step 4: Integrate the modules into the bounded cloud main**

Add these imports after `AlgorithmImports` in `qc-workspace/SPY Plus 10 Walk-Forward/main.py`:

```python
from audit import AuditTrail
from baseline import load_baseline_contract
from benchmark import PricePoint
from costs import equity_execution
from ledger import CashLedger
from metrics import EquityPoint
```

Add this pure self-check as the first statement of `initialize`:

```python
        assert equity_execution("BUY", 1, "100").commission == Decimal("1.00")
```

Also import `Decimal` from `decimal`. Do not extend the date range, add assets, enable formal evaluation, configure a brokerage, or place live orders.

- [ ] **Step 5: Add the repository validator**

Create `scripts/verify_audit_baseline.py`:

```python
#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
sys.path.insert(0, str(PROJECT))

from baseline import load_baseline_contract


def main() -> int:
    required = (
        "audit.py",
        "baseline.py",
        "baseline-contract.json",
        "benchmark.py",
        "costs.py",
        "ledger.py",
        "metrics.py",
    )
    missing = [name for name in required if not (PROJECT / name).is_file()]
    if missing:
        print(f"audit-baseline:FAIL:missing={','.join(missing)}")
        return 1
    contract = load_baseline_contract(PROJECT / "baseline-contract.json")
    main_source = (PROJECT / "main.py").read_text(encoding="utf-8")
    if contract.formal_evaluation or contract.live_trading:
        print("audit-baseline:FAIL:unsafe-contract")
        return 1
    if "self.set_end_date(2015, 1, 9)" not in main_source:
        print("audit-baseline:FAIL:unbounded-smoke")
        return 1
    print("audit-baseline:PASS:formal_evaluation=false:live_trading=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/write_audit_baseline_record.py`:

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spy_plus_10.audit_baseline_record import render_audit_baseline_record
from spy_plus_10.foundation_record import parse_result_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean-version", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--result-url", required=True)
    parser.add_argument("--test-count", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    project_id, backtest_id = parse_result_url(args.result_url)
    text = render_audit_baseline_record(
        lean_version=args.lean_version,
        git_commit=args.git_commit,
        project_id=project_id,
        backtest_id=backtest_id,
        result_url=args.result_url,
        test_count=args.test_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"audit-baseline-record:wrote:{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run all local tests and validators**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
python3 scripts/verify_audit_baseline.py
```

Expected: 35 tests PASS, foundation PASS, and audit baseline PASS.

- [ ] **Step 7: Commit the cloud-ready audit baseline before running it**

```bash
git add tests/test_baseline_contract.py tests/test_audit_baseline_record.py \
  spy_plus_10/audit_baseline_record.py scripts/verify_audit_baseline.py \
  scripts/write_audit_baseline_record.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/main.py"
git diff --cached --check
git commit -m "feat: integrate audit baseline cloud smoke"
```

- [ ] **Step 8: Synchronize and run the bounded cloud smoke**

From `qc-workspace/`, run:

```bash
lean cloud push --project "SPY Plus 10 Walk-Forward"
```

Expected: exact project name and organization are updated without a duplicate project. Do not use `--force` or `--open`.

- [ ] **Step 9: Generate and verify the actual cloud evidence**

From `qc-workspace/`, run:

```bash
set -euo pipefail
smoke_log=$(mktemp)
lean cloud backtest "SPY Plus 10 Walk-Forward" --push \
  --name "audit-baseline-smoke-$(git -C .. rev-parse --short HEAD)" | tee "$smoke_log"
backtest_url=$(rg -o 'https://www\.quantconnect\.com/[^[:space:]]+' "$smoke_log" | tail -n 1 | sed 's/[),.;]*$//')
test -n "$backtest_url"
python3 ../scripts/write_audit_baseline_record.py \
  --lean-version "$(lean --version | head -n 1)" \
  --git-commit "$(git -C .. rev-parse HEAD)" \
  --result-url "$backtest_url" \
  --test-count 35 \
  --output ../docs/audit-baseline.md
```

Expected: successful compile, 2015-01-02 through 2015-01-09 execution, and a parsed result URL. The temporary log is non-secret disposable evidence under `/tmp`; do not run a formal 2015–latest backtest. Then run:

```bash
if rg -n '[a-f0-9]{64}' docs/audit-baseline.md; then exit 1; fi
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
python3 scripts/verify_audit_baseline.py
git diff --check
```

Expected: the cloud IDs match the result URL, all local tests pass, both validators pass, and the evidence file contains `Formal evaluation: false`.

- [ ] **Step 10: Commit evidence, verify privacy, and push the feature branch**

```bash
git add docs/audit-baseline.md \
  "qc-workspace/SPY Plus 10 Walk-Forward/config.json"
git diff --cached --check
git commit -m "docs: record verified audit baseline smoke"
gh repo view Jimmyyu725/spy-plus-10-walk-forward --json visibility,nameWithOwner,url
git push -u origin feature/audit-baseline
```

Expected: GitHub reports exactly `PRIVATE`; local and remote feature hashes match. Then use `superpowers:finishing-a-development-branch`, re-run all tests on merged `main`, verify privacy again, push `main`, and prove the remote hash equals local.

## Milestone completion gate

All statements must be supported before starting Alpha Modules:

```text
The frozen contract preserves initial_cash=1000000 and the 0.10 percentage-point hurdle.
Base and double-slippage costs are deterministic and tested for equities, futures, and options.
The cash ledger fails closed on missing held prices and conserves cash, positions, fees, and equity.
The independent SPY benchmark includes initial transaction costs and exit-cost sensitivity.
Annual metrics use common dates, retain failed years, and mark an unfinished current year PARTIAL_YEAR.
Audit events require data cutoff < signal < order < fill and serialize deterministically.
No module reads local historical market data or enables live trading.
The bounded cloud smoke compiles and completes without becoming a formal evaluation.
All fixture tests and both repository validators pass.
The final commit is synchronized to a GitHub repository verified PRIVATE.
```

If any statement is false or unsupported, Audit Baseline remains incomplete and Alpha Modules must not begin.
