# Equity Factor Alpha Implementation Plan

> Scope: implement and independently cloud-verify only the approved Equity Factor Alpha. This is not the frozen 2015-current evaluation and cannot establish the annual SPY+10 objective.

**Goal:** Build a point-in-time US equity factor module that ranks the historically available liquid universe with fixed momentum, quality, and residual-volatility rules; converts the top 30 into a beta-neutral, volatility-scaled allocation; and proves the adapter against QuantConnect Cloud without live trading.

**Architecture:** Pure standard-library modules own validation, cross-sectional scoring, ranking, and allocation. A separate QuantConnect smoke project is only an adapter for point-in-time fundamental-universe data, completed daily price history, delayed execution, and cloud evidence. The adapter fails closed on missing fundamentals, insufficient history, invalid timestamps, or unavailable licensing.

**Tech stack:** Python 3.12 standard library, `unittest`, LEAN CLI 1.0.229, QuantConnect Cloud LEAN, Git.

Official adapter references:

- <https://www.quantconnect.com/docs/v2/writing-algorithms/universes/equity/fundamental-universes>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/universe-data>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-fundamentals>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data>

## Frozen contract

Create `qc-workspace/SPY Plus 10 Walk-Forward/equity-factor-contract.json` before any cloud result with exactly these material choices:

- point-in-time QuantConnect US fundamental universe; no current constituent list;
- signal on the last completed trading day of each month, earliest execution 30 minutes after the next regular-session open;
- price at least 5 USD;
- top 500 by the mean of the prior 20 completed daily dollar-volume observations;
- 253 completed adjusted-price observations, with 12-1 momentum `price[-22] / price[-253] - 1`;
- quality `50% ROE + 50% gross-profit / total-assets`, with each raw quality input independently winsorized and standardized;
- residual volatility from an intercept-plus-SPY OLS over 126 completed daily returns, annualized with 252 trading days, scored negatively;
- final score `50% momentum + 25% quality + 25% negative residual volatility`; each final component is independently winsorized at 1%/99% and converted to a population z-score;
- deterministic symbol tie-breaks and top 30 holdings;
- inverse 126-day total-volatility long weights, SPY beta hedge, 5% target module volatility, and 50% total gross-notional cap;
- no short individual equities, no live trading, no formal evaluation.

Percentiles use deterministic linear interpolation between adjacent sorted observations. Zero-dispersion cross sections score zero. OLS fails closed when SPY variance is zero or fewer than 126 aligned completed returns exist.

## Task 1: Point-in-time universe filter

**Files:**

- Create: `qc-workspace/SPY Plus 10 Walk-Forward/equity-factor-contract.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/universe.py`
- Create: `tests/test_equity_universe.py`

1. Write failing fixture tests for price, fundamental completeness, positive total assets, exactly 20 prior dollar-volume observations, deterministic top-500 ranking, cutoff enforcement, duplicate dates, and future-data mutation invariance.
2. Run `python3 -m unittest tests/test_equity_universe.py -v`; expect failure because the module is absent.
3. Implement immutable `FundamentalSnapshot`, `DollarVolumePoint`, and `EquityCandidate` records plus `select_equity_candidates(...)`. Reject non-finite numbers, future/same-time decision inputs, duplicate/non-increasing dates, non-positive dollar volume, and incomplete 20-day windows.
4. Re-run the focused and complete suites; expect PASS.
5. Commit `feat: add point-in-time equity universe filter`.

## Task 2: Factor signals and ranking

**Files:**

- Create: `qc-workspace/SPY Plus 10 Walk-Forward/signals/equity_factor.py`
- Create: `tests/test_equity_factor.py`

1. Write failing fixture tests for percentile interpolation, 1%/99% winsorization, population z-score, 12-1 momentum indices, ROE/GPA quality construction, 126-day OLS beta and residual volatility, weighted composite, deterministic ties, missing-history rejection, and future-append invariance.
2. Run the focused test; expect import failure.
3. Implement immutable price-series and factor-score records and pure functions. Every input point must have `as_of <= signal_cutoff`; the recorded signal timestamp must be strictly later than the data cutoff.
4. Re-run focused and complete tests; expect PASS.
5. Commit `feat: add equity factor scoring`.

## Task 3: Beta-neutral risk allocation

**Files:**

- Create: `qc-workspace/SPY Plus 10 Walk-Forward/equity_allocation.py`
- Create: `tests/test_equity_allocation.py`

1. Write failing tests that prove: only the top 30 are selected; lower-volatility stocks receive larger pre-hedge weights; no individual stock weight is negative; the SPY hedge neutralizes ex-ante beta; scaling targets 5% annualized volatility when feasible; gross exposure never exceeds 50%; zero/invalid variance fails closed; and changing post-cutoff returns cannot alter a past allocation.
2. Run the focused test; expect import failure.
3. Implement inverse-volatility long weights, individual OLS betas, a SPY hedge, covariance-based module volatility, and a single common scale bounded by the 50% gross cap. Return explicit diagnostics for long gross, hedge weight, beta before/after, expected volatility, and cap binding.
4. Re-run focused and complete tests; expect PASS.
5. Commit `feat: add beta-neutral equity allocation`.

## Task 4: Independent QuantConnect adapter

**Files:**

- Create: `qc-workspace/SPY Plus 10 Walk-Forward - Equity Factor Smoke/config.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward - Equity Factor Smoke/project-manifest.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward - Equity Factor Smoke/main.py`
- Create: `scripts/sync_equity_factor_smoke.py`
- Create: `tests/test_equity_smoke_sync.py`

1. Write failing sync and manifest tests. Require byte-identical copies of `universe.py`, `signals/equity_factor.py`, and `equity_allocation.py`; require `formal_evaluation=false`, `live_trading=false`, and explicit custom statistics.
2. Create the local LEAN project and use a deterministic sync script; never hand-edit shared copies.
3. Implement a daily fundamental universe that stores only data received before the decision timestamp. It keeps rolling 20-day dollar-volume observations, detects the first trading day of a new month, ranks using the prior completed month-end snapshot, requests 253 completed adjusted daily bars for the frozen top-500 candidates and SPY, computes signals, returns the selected universe, and submits pending targets 30 minutes after the regular-session open.
4. Access quality as point-in-time properties from the received `Fundamental` objects: `operation_ratios.roe.value`, `financial_statements.income_statement.gross_profit.twelve_months`, and `financial_statements.balance_sheet.total_assets.twelve_months`. Do not substitute a different metric if a field or license is unavailable.
5. Apply the approved equity commission floor and adverse-slippage model. Record the regulatory-fee limitation separately if the cloud adapter cannot expose it without replacing the frozen commission schedule; formal integration must account for it explicitly.
6. Add custom statistics: `EQUITY_UNIVERSE_OBSERVATIONS`, `EQUITY_MONTH_END_SIGNALS`, `EQUITY_SELECTED_COUNT`, `EQUITY_ORDER_COUNT`, `EQUITY_FUTURE_INPUT_COUNT`, `EQUITY_MISSING_FUNDAMENTAL_COUNT`, `EQUITY_BETA_AFTER`, `EQUITY_GROSS_EXPOSURE`, and `EQUITY_LICENSE_STATUS`.
7. Smoke range is fixed to 2012-01-01 through 2015-03-31, with initial cash 1,000,000 USD. This range validates warm-up and several pre-evaluation rebalances without becoming the formal test.
8. Run the sync tests and full local suite; commit `feat: add independent equity factor smoke project`.

## Task 5: Cloud verification and immutable evidence

**Files:**

- Create: `docs/equity-factor-alpha.md`

1. Run the full local suite, foundation validator, audit-baseline validator, `git diff --check`, and a plaintext-secret scan.
2. From `qc-workspace/`, run `lean cloud backtest 'SPY Plus 10 Walk-Forward - Equity Factor Smoke' --push --name "equity-factor-smoke-$(git -C .. rev-parse --short HEAD)"`.
3. Treat a CLI exit code of zero as insufficient: inspect compile/runtime output and all custom statistics. If Morningstar data is denied, record the exact license error and status `UNVERIFIED`; do not purchase anything or remove quality.
4. A valid smoke requires: completed cloud run; `EQUITY_LICENSE_STATUS=AVAILABLE`; at least 20 universe observations, one month-end signal, one selected stock, and one strategy order; `EQUITY_FUTURE_INPUT_COUNT=0`; selected count no greater than 30; and absolute beta-after within numerical tolerance.
5. Record exact Git hash, project/compile/backtest IDs, URL, period, LEAN versions, frozen rules, data/license status, custom statistics, costs, and limitations in `docs/equity-factor-alpha.md`. State explicitly that this is not SPY+10 evidence.
6. Re-run all tests/validators, commit the evidence, verify the exact GitHub repository is `PRIVATE`, push the feature branch, compare hashes, merge locally to `main`, re-test, remove the clean worktree, verify privacy again, push `main`, and compare local/remote hashes.

## Completion gate

```text
The contract is committed before the independent cloud result.
The universe is historical and point-in-time, never today's constituent list.
All factor and risk inputs are completed and no later than the recorded cutoff.
Appending future fixtures cannot change a past universe, score, rank, or allocation.
The exact 20/500/253/252/21/126/30 windows and 50/25/25 score are tested.
The long book has no individual shorts; the hedge targets beta zero.
The 5% volatility target and 50% gross cap are both enforced.
Missing quality data or licensing fails closed instead of changing the strategy.
The cloud smoke is independent, non-live, non-formal, and archived.
The final commit is synchronized to a freshly verified private repository.
```
