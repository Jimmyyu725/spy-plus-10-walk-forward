# Futures Trend Alpha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现固定 13 个根合约的 3/6/12 月趋势方向、60 日逆波动率和 252 日协方差缩放、成交量优先实际合约选择，并完成一个非正式、独立的 QuantConnect 云端模块回测。

**Architecture:** 纯函数信号、配置、风险缩放和换月选择放入主 QuantConnect 项目的 `signals/`，本地只用人工夹具测试；独立 smoke 项目由同步脚本复制相同模块，避免第二份手写实现。连续合约只提供平滑信号价格，订单只发往当时链中按成交量规则选出的实际合约。

**Tech Stack:** Python 3.12 standard library, `dataclasses`, `statistics`, `unittest`, LEAN CLI, QuantConnect US Futures Security Master, QuantConnect Cloud.

---

## Fixed module contract

- Roots: `ES, NQ, ZN, ZB, GC, SI, CL, NG, ZC, ZS, 6E, 6J, 6B`.
- Completed daily-bar lookbacks: `63, 126, 252` trading days; each direction is `-1, 0, +1`; score is their arithmetic mean.
- Rebalance: last completed trading day of each week; earliest order is the next tradable bar.
- Per-root sizing: inverse of trailing 60-day annualized volatility.
- Portfolio scaling: trailing 252-day covariance, `7%` annualized target, `70%` gross-notional cap.
- Roll selection: contracts with positive price/volume and more than 7 calendar days to expiry; highest current volume wins, then higher open interest, nearer expiry, lexical symbol.
- Continuous signal series: `BACKWARDS_RATIO`; actual contract orders only. The official LEAN documentation states that continuous symbols are not tradable and actual contracts must be used.
- Module smoke is never formal evaluation and never connects a live brokerage.

## File map

- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures-trend-contract.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/signals/__init__.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/signals/futures_trend.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures_allocation.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures_roll.py`
- Create: `tests/test_futures_trend.py`
- Create: `tests/test_futures_allocation.py`
- Create: `tests/test_futures_roll.py`
- Create: `scripts/sync_futures_trend_smoke.py`
- Create: `tests/test_futures_smoke_sync.py`
- Create from LEAN generator: `qc-workspace/SPY Plus 10 Walk-Forward - Futures Trend Smoke/config.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward - Futures Trend Smoke/main.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward - Futures Trend Smoke/project-manifest.json`
- Create: `docs/futures-trend-alpha.md`

Official references used for the adapter:

- <https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/requesting-data/universes>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-futures-security-master>

### Task 1: Freeze roots and implement point-in-time trend signals

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures-trend-contract.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/signals/__init__.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/signals/futures_trend.py`
- Create: `tests/test_futures_trend.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_futures_trend.py`:

```python
import unittest
from datetime import date, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from signals.futures_trend import DailyPrice, TrendSignalError, compute_trend_signal


def prices(count=260, growth=0.001):
    start = date(2014, 1, 1)
    return [DailyPrice(start + timedelta(days=i), 100 * (1 + growth) ** i) for i in range(count)]


class FuturesTrendSignalTests(unittest.TestCase):
    def test_uptrend_has_three_positive_directions(self):
        signal = compute_trend_signal("ES", prices(), prices()[-1].as_of)
        self.assertEqual(signal.directions, (1, 1, 1))
        self.assertEqual(signal.score, 1.0)

    def test_mixed_directions_are_equally_weighted(self):
        series = prices(growth=0)
        series[-64] = DailyPrice(series[-64].as_of, 110)
        series[-127] = DailyPrice(series[-127].as_of, 90)
        series[-253] = DailyPrice(series[-253].as_of, 90)
        signal = compute_trend_signal("ES", series, series[-1].as_of)
        self.assertEqual(signal.directions, (-1, 1, 1))
        self.assertAlmostEqual(signal.score, 1 / 3)

    def test_future_append_does_not_change_past_signal(self):
        series = prices()
        signal_date = series[-1].as_of
        before = compute_trend_signal("ES", series, signal_date)
        series.append(DailyPrice(signal_date + timedelta(days=1), 1))
        after = compute_trend_signal("ES", series, signal_date)
        self.assertEqual(before, after)

    def test_insufficient_history_fails_closed(self):
        with self.assertRaisesRegex(TrendSignalError, "253"):
            compute_trend_signal("ES", prices(252), date(2015, 1, 1))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests/test_futures_trend.py -v`

Expected: import failure for `signals.futures_trend`.

- [ ] **Step 3: Add the frozen JSON contract**

Create `futures-trend-contract.json` with this exact JSON:

```json
{
  "contract_expiry_buffer_days": 7,
  "covariance_lookback_days": 252,
  "formal_evaluation": false,
  "gross_notional_cap": 0.70,
  "live_trading": false,
  "rebalance": "weekly-last-complete-trading-day-next-bar",
  "roots": ["ES", "NQ", "ZN", "ZB", "GC", "SI", "CL", "NG", "ZC", "ZS", "6E", "6J", "6B"],
  "signal_lookbacks_days": [63, 126, 252],
  "signal_price_normalization": "BACKWARDS_RATIO",
  "target_annual_volatility": 0.07,
  "volatility_lookback_days": 60
}
```

- [ ] **Step 4: Implement the signal**

Create empty `signals/__init__.py` and `signals/futures_trend.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


LOOKBACKS = (63, 126, 252)


class TrendSignalError(RuntimeError):
    """Raised when a point-in-time trend signal cannot be verified."""


@dataclass(frozen=True)
class DailyPrice:
    as_of: date
    close: float


@dataclass(frozen=True)
class TrendSignal:
    root: str
    as_of: date
    directions: tuple[int, int, int]
    score: float


def compute_trend_signal(root: str, series: list[DailyPrice], signal_date: date) -> TrendSignal:
    if not root:
        raise TrendSignalError("root is required")
    if any(left.as_of >= right.as_of for left, right in zip(series, series[1:])):
        raise TrendSignalError("price dates must be strictly increasing")
    eligible = [point for point in series if point.as_of <= signal_date]
    if len(eligible) < 253:
        raise TrendSignalError("253 completed daily prices are required")
    if any(point.close <= 0 for point in eligible):
        raise TrendSignalError("prices must be positive")
    current = eligible[-1].close
    returns = [current / eligible[-(lookback + 1)].close - 1 for lookback in LOOKBACKS]
    directions = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in returns)
    return TrendSignal(root, eligible[-1].as_of, directions, sum(directions) / 3)
```

- [ ] **Step 5: Verify GREEN and commit**

Run: `python3 -m unittest tests/test_futures_trend.py -v`

Expected: 4 tests PASS.

```bash
git add tests/test_futures_trend.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/futures-trend-contract.json" \
  "qc-workspace/SPY Plus 10 Walk-Forward/signals/__init__.py" \
  "qc-workspace/SPY Plus 10 Walk-Forward/signals/futures_trend.py"
git commit -m "feat: add point-in-time futures trend signals"
```

### Task 2: Implement volatility and covariance allocation

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures_allocation.py`
- Create: `tests/test_futures_allocation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_futures_allocation.py`:

```python
import unittest

from tests.project_path import PROJECT_DIR  # noqa: F401
from futures_allocation import AllocationError, allocate_trend, volatility_only_control


def alternating(scale, count=253):
    return [scale if i % 2 == 0 else -scale for i in range(count)]


class FuturesAllocationTests(unittest.TestCase):
    def test_lower_volatility_receives_larger_absolute_weight(self):
        result = allocate_trend(
            {"ES": 1.0, "GC": 1.0},
            {"ES": alternating(0.01), "GC": alternating(0.02)},
        )
        self.assertGreater(abs(result.weights["ES"]), abs(result.weights["GC"]))
        self.assertLessEqual(result.gross_notional, 0.70 + 1e-12)

    def test_direction_is_preserved(self):
        result = allocate_trend(
            {"ES": -1.0, "GC": 1.0},
            {
                "ES": alternating(0.01),
                "GC": [0.01 if i % 3 == 0 else -0.005 for i in range(253)],
            },
        )
        self.assertLess(result.weights["ES"], 0)
        self.assertGreater(result.weights["GC"], 0)

    def test_zero_signal_stays_zero(self):
        result = allocate_trend({"ES": 0.0}, {"ES": alternating(0.01)})
        self.assertEqual(result.weights, {"ES": 0.0})

    def test_volatility_only_control_removes_trend_direction(self):
        result = volatility_only_control(
            {"ES": -1.0, "GC": 1.0},
            {"ES": alternating(0.01), "GC": alternating(0.01)},
        )
        self.assertGreaterEqual(result.weights["ES"], 0)
        self.assertGreaterEqual(result.weights["GC"], 0)

    def test_short_history_fails_closed(self):
        with self.assertRaisesRegex(AllocationError, "252"):
            allocate_trend({"ES": 1.0}, {"ES": alternating(0.01, 251)})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests/test_futures_allocation.py -v`

Expected: missing `futures_allocation`.

- [ ] **Step 3: Implement allocation**

Create `futures_allocation.py`:

```python
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
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    return sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right)) / (len(left) - 1)


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
    variance = sum(unit[left] * unit[right] * covariance[left, right] for left in roots for right in roots)
    if variance <= 0:
        raise AllocationError("non-positive portfolio variance")
    scale = min(target_volatility / sqrt(variance), gross_cap)
    weights = {root: unit[root] * scale for root in roots}
    gross = sum(abs(value) for value in weights.values())
    predicted = sqrt(variance) * scale
    return FuturesAllocation(weights, predicted, gross)


def volatility_only_control(scores, returns, *, target_volatility=0.07, gross_cap=0.70):
    controls = {root: 1.0 if score != 0 else 0.0 for root, score in scores.items()}
    return allocate_trend(
        controls,
        returns,
        target_volatility=target_volatility,
        gross_cap=gross_cap,
    )
```

- [ ] **Step 4: Verify GREEN and commit**

Run: `python3 -m unittest tests/test_futures_allocation.py -v`

Expected: 5 tests PASS.

```bash
git add tests/test_futures_allocation.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/futures_allocation.py"
git commit -m "feat: add futures volatility allocation"
```

### Task 3: Implement volume-priority actual-contract selection

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/futures_roll.py`
- Create: `tests/test_futures_roll.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_futures_roll.py`:

```python
import unittest
from datetime import date

from tests.project_path import PROJECT_DIR  # noqa: F401
from futures_roll import ContractSnapshot, RollSelectionError, select_volume_contract


class FuturesRollTests(unittest.TestCase):
    def test_highest_volume_valid_contract_wins(self):
        contracts = [
            ContractSnapshot("ESH15", date(2015, 3, 20), 100, 200, 2000),
            ContractSnapshot("ESM15", date(2015, 6, 19), 101, 500, 1000),
        ]
        self.assertEqual(select_volume_contract(contracts, date(2015, 1, 5)).symbol, "ESM15")

    def test_expiry_buffer_excludes_near_contract(self):
        contracts = [
            ContractSnapshot("ESH15", date(2015, 1, 10), 100, 1000, 2000),
            ContractSnapshot("ESM15", date(2015, 3, 20), 101, 100, 1000),
        ]
        self.assertEqual(select_volume_contract(contracts, date(2015, 1, 5)).symbol, "ESM15")

    def test_ties_use_open_interest_then_expiry(self):
        contracts = [
            ContractSnapshot("ESM15", date(2015, 6, 19), 101, 500, 1000),
            ContractSnapshot("ESH15", date(2015, 3, 20), 100, 500, 2000),
        ]
        self.assertEqual(select_volume_contract(contracts, date(2015, 1, 5)).symbol, "ESH15")

    def test_missing_valid_contract_fails_closed(self):
        with self.assertRaisesRegex(RollSelectionError, "no valid"):
            select_volume_contract([], date(2015, 1, 5))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests/test_futures_roll.py -v`

Expected: missing `futures_roll`.

- [ ] **Step 3: Implement selection**

Create `futures_roll.py`:

```python
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
```

- [ ] **Step 4: Verify GREEN and commit**

Run: `python3 -m unittest tests/test_futures_roll.py -v`

Expected: 4 tests PASS.

```bash
git add tests/test_futures_roll.py \
  "qc-workspace/SPY Plus 10 Walk-Forward/futures_roll.py"
git commit -m "feat: add volume-priority futures roll selection"
```

### Task 4: Build the independent cloud smoke project

**Files:**
- Create: `scripts/sync_futures_trend_smoke.py`
- Create: `tests/test_futures_smoke_sync.py`
- Create generated project: `qc-workspace/SPY Plus 10 Walk-Forward - Futures Trend Smoke/`

- [ ] **Step 1: Add a failing sync contract test**

Create `tests/test_futures_smoke_sync.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
SMOKE = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Futures Trend Smoke"


class FuturesSmokeSyncTests(unittest.TestCase):
    def test_shared_modules_are_byte_identical(self):
        for relative in (
            "futures_allocation.py",
            "futures_roll.py",
            "signals/__init__.py",
            "signals/futures_trend.py",
        ):
            self.assertEqual((PRIMARY / relative).read_bytes(), (SMOKE / relative).read_bytes())

    def test_smoke_manifest_is_non_formal_and_non_live(self):
        text = (SMOKE / "project-manifest.json").read_text(encoding="utf-8")
        self.assertIn('"formal_evaluation": false', text)
        self.assertIn('"live_trading": false', text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED and check the cloud name**

Run:

```bash
python3 -m unittest tests/test_futures_smoke_sync.py -v
cd qc-workspace
lean cloud pull --project "SPY Plus 10 Walk-Forward - Futures Trend Smoke"
```

Expected: tests fail because the local project is absent; cloud pull reports no such project. If it exists, inspect and stop before overwriting.

- [ ] **Step 3: Generate the project and deterministic sync script**

Run from `qc-workspace/`:

```bash
lean project-create "SPY Plus 10 Walk-Forward - Futures Trend Smoke" --language python
```

Create `scripts/sync_futures_trend_smoke.py`:

```python
#!/usr/bin/env python3
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = (ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward").resolve()
SMOKE = (ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Futures Trend Smoke").resolve()
RELATIVE_PATHS = (
    Path("futures_allocation.py"),
    Path("futures_roll.py"),
    Path("signals/__init__.py"),
    Path("signals/futures_trend.py"),
)


def main() -> int:
    for relative in RELATIVE_PATHS:
        source = (PRIMARY / relative).resolve()
        try:
            source.relative_to(PRIMARY)
        except ValueError as exc:
            raise RuntimeError(f"source escaped primary project: {source}") from exc
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = SMOKE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"futures-smoke-sync:copied:{relative.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Replace the generated manifest with:

```json
{
  "formal_evaluation": false,
  "live_trading": false,
  "mode": "futures-trend-smoke",
  "name": "SPY Plus 10 Walk-Forward - Futures Trend Smoke",
  "start_date": "2012-01-01",
  "end_date": "2015-03-31"
}
```

- [ ] **Step 4: Implement the cloud adapter**

Replace the smoke `main.py` with this complete algorithm:

```python
from AlgorithmImports import *
from collections import deque
from datetime import date

from futures_allocation import AllocationError, allocate_trend
from futures_roll import ContractSnapshot, RollSelectionError, select_volume_contract
from signals.futures_trend import DailyPrice, TrendSignalError, compute_trend_signal


ROOT_CONSTANTS = {
    "ES": Futures.Indices.SP_500_E_MINI,
    "NQ": Futures.Indices.NASDAQ_100_E_MINI,
    "ZN": Futures.Financials.Y_10_TREASURY_NOTE,
    "ZB": Futures.Financials.Y_30_TREASURY_BOND,
    "GC": Futures.Metals.GOLD,
    "SI": Futures.Metals.SILVER,
    "CL": Futures.Energy.CRUDE_OIL_WTI,
    "NG": Futures.Energy.NATURAL_GAS,
    "ZC": Futures.Grains.CORN,
    "ZS": Futures.Grains.SOYBEANS,
    "6E": Futures.Currencies.EUR,
    "6J": Futures.Currencies.JPY,
    "6B": Futures.Currencies.GBP,
}


class PerContractFeeModel(FeeModel):
    def get_order_fee(self, parameters):
        fee = abs(parameters.order.quantity) * 2.50
        return OrderFee(CashAmount(fee, "USD"))


class OneTickSlippageModel(SlippageModel):
    def get_slippage_approximation(self, asset, order):
        return asset.symbol_properties.minimum_price_variation


class FuturesTrendSmokeAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2012, 1, 1)
        self.set_end_date(2015, 3, 31)
        self.set_cash(1_000_000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_security_initializer(self._initialize_security)

        self._futures = {}
        self._root_by_continuous = {}
        self._prices = {root: deque(maxlen=253) for root in ROOT_CONSTANTS}
        self._returns = {root: deque(maxlen=252) for root in ROOT_CONSTANTS}
        self._chains = {}
        self._pending = None
        self._current_contract = {}
        self._last_observed_week = None
        self._signal_count = 0
        self._order_count = 0
        self._continuous_order_count = 0
        self._coverage = {
            root: {"history": False, "contract": False, "signal": False, "order": False}
            for root in ROOT_CONSTANTS
        }

        for root, constant in ROOT_CONSTANTS.items():
            future = self.add_future(
                constant,
                Resolution.DAILY,
                extended_market_hours=True,
                data_mapping_mode=DataMappingMode.OPEN_INTEREST,
                data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO,
                contract_depth_offset=0,
            )
            future.set_filter(0, 180)
            self._futures[root] = future
            self._root_by_continuous[future.symbol] = root

    def _initialize_security(self, security):
        if security.type == SecurityType.FUTURE:
            security.set_fee_model(PerContractFeeModel())
            security.set_slippage_model(OneTickSlippageModel())

    def on_data(self, data: Slice):
        self._capture_chains(data)
        current_week = self.time.date().isocalendar()[:2]
        if self._last_observed_week is not None and current_week != self._last_observed_week:
            self._compute_weekly_targets()
            self._execute_pending_if_due()
        self._capture_completed_prices(data)
        self._last_observed_week = current_week

    def _capture_chains(self, data):
        for root, future in self._futures.items():
            chain = data.future_chains.get(future.symbol)
            if chain:
                self._chains[root] = chain

    def _capture_completed_prices(self, data):
        for root, future in self._futures.items():
            bar = data.bars.get(future.symbol)
            if bar is None or bar.close <= 0:
                continue
            history = self._prices[root]
            if history and history[-1].as_of >= self.time.date():
                continue
            if history:
                self._returns[root].append(float(bar.close / history[-1].close - 1))
            history.append(DailyPrice(self.time.date(), float(bar.close)))
            self._coverage[root]["history"] = len(history) == 253

    def _compute_weekly_targets(self):
        if any(not self._prices[root] for root in ROOT_CONSTANTS):
            return
        signal_date = min(self._prices[root][-1].as_of for root in ROOT_CONSTANTS)
        scores = {}
        histories = {}
        for root in ROOT_CONSTANTS:
            try:
                signal = compute_trend_signal(root, list(self._prices[root]), signal_date)
            except TrendSignalError:
                return
            scores[root] = signal.score
            histories[root] = list(self._returns[root])
            self._coverage[root]["signal"] = True
        try:
            allocation = allocate_trend(scores, histories)
        except AllocationError:
            return
        self._pending = (signal_date, allocation.weights)
        self._signal_count += 1

    def _execute_pending_if_due(self):
        if self._pending is None or self.time.date() <= self._pending[0]:
            return
        _, weights = self._pending
        if not all(root in self._chains for root in ROOT_CONSTANTS):
            return
        selected = {}
        for root, chain in self._chains.items():
            snapshots = []
            symbols = {}
            for contract in chain.contracts.values():
                snapshot = ContractSnapshot(
                    str(contract.symbol),
                    contract.expiry.date(),
                    float(contract.last_price),
                    int(contract.volume),
                    int(contract.open_interest),
                )
                snapshots.append(snapshot)
                symbols[snapshot.symbol] = contract.symbol
            try:
                choice = select_volume_contract(snapshots, self.time.date())
            except RollSelectionError:
                return
            selected[root] = (symbols[choice.symbol], choice)
            self._coverage[root]["contract"] = True
        for root, (symbol, snapshot) in selected.items():
            old = self._current_contract.get(root)
            if old is not None and old != symbol and self.portfolio[old].invested:
                self.liquidate(old, tag=f"roll-out:{root}")
                self._order_count += 1
            multiplier = float(self.securities[symbol].symbol_properties.contract_multiplier)
            target_notional = weights[root] * float(self.portfolio.total_portfolio_value)
            target_quantity = int(target_notional / (snapshot.price * multiplier))
            current_quantity = int(self.portfolio[symbol].quantity)
            delta = target_quantity - current_quantity
            if delta:
                self.market_order(symbol, delta, tag=f"trend:{root}")
                self._order_count += 1
                self._coverage[root]["order"] = True
            self._current_contract[root] = symbol
        self._pending = None

    def on_end_of_algorithm(self):
        self.set_summary_statistic("TREND_SIGNAL_COUNT", str(self._signal_count))
        self.set_summary_statistic("TREND_ORDER_COUNT", str(self._order_count))
        self.set_summary_statistic("CONTINUOUS_ORDER_COUNT", str(self._continuous_order_count))
        for root, status in self._coverage.items():
            encoded = ",".join(f"{key}={str(value).lower()}" for key, value in status.items())
            self.set_summary_statistic(f"ROOT_{root}", encoded)
```

Run `python3 scripts/sync_futures_trend_smoke.py` after writing `main.py`, then run `python3 -m unittest tests/test_futures_smoke_sync.py -v`. Expected: 2 tests PASS. Run the complete suite; expected total after this plan is 51 tests. Commit the generated project and sync script with `feat: add independent futures trend smoke project`.

### Task 5: Run and archive the independent cloud backtest

- [ ] **Step 1: Verify locally**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
python3 scripts/verify_audit_baseline.py
git diff --check
git status --short --branch
```

Expected: all tests and validators PASS; worktree clean.

- [ ] **Step 2: Push the exact smoke project and backtest**

From `qc-workspace/`:

```bash
lean cloud push --project "SPY Plus 10 Walk-Forward - Futures Trend Smoke"
lean cloud backtest "SPY Plus 10 Walk-Forward - Futures Trend Smoke" --push \
  --name "futures-trend-smoke-$(git -C .. rev-parse --short HEAD)"
```

Expected: compile succeeds, the result covers only 2012-01-01 through 2015-03-31, `CONTINUOUS_ORDER_COUNT=0`, and there is at least one verified signal. If no whole contract fits the 1,000,000 USD account or data coverage is incomplete, record `UNVERIFIED` rather than weakening rules.

- [ ] **Step 3: Record immutable evidence**

Create `docs/futures-trend-alpha.md` with the actual Git hash, cloud project/backtest IDs, URL, period, LEAN version, all three custom statistics, fixed roots, and `Formal evaluation: false`. Include a table listing every root and whether it had 253 bars, a valid actual contract, a signal, and an order. Do not claim the SPY+10 objective passed.

- [ ] **Step 4: Final verification and private integration**

Run the complete test suite and both existing validators, scan the evidence for 64-hex secrets, and commit with `docs: record futures trend cloud evidence`. Verify the exact GitHub destination is `PRIVATE`, push `feature/futures-trend-alpha`, use `superpowers:finishing-a-development-branch`, re-test merged `main`, verify privacy again, push `main`, and compare local/remote hashes.

## Completion gate

```text
All 13 roots and parameters are frozen before the independent cloud backtest.
Signals use only completed prices at or before the recorded signal date.
Future data mutation does not change a past signal.
Risk weights use 60-day volatility and 252-day covariance with 7% target and 70% cap.
The volatility-only control removes direction without changing the risk engine.
Actual contracts use the fixed current-volume rule and a 7-day expiry buffer.
No order targets a continuous symbol.
The cloud backtest is independent, non-live, and non-formal.
All results, including missing data or zero orders, are retained without parameter changes.
The final commit is synchronized to a verified private repository.
```
