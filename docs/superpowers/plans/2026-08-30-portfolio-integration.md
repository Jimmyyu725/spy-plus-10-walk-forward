# Portfolio Integration Implementation Plan

> Scope: combine the three independently verified Alpha sleeves with a raw-SPY beta core, frozen portfolio risk coordination, complete costs, and an auditable non-formal cloud smoke. The 2015-current frozen evaluation remains a separate final milestone.

**Goal:** Produce one QuantConnect algorithm whose sleeves share one account without overwriting each other's targets, whose predicted beta, drawdown scaling, leverage, Alpha gross, risk-contribution, margin, and cost gates fail closed, and whose daily portfolio/benchmark evidence can later be independently recomputed.

**Architecture:** Pure `risk.py` and `execution.py` modules own deterministic portfolio coordination and cost policy. Thin cloud sleeve services adapt the already-verified equity, futures, and option modules and expose target/risk state to a small `main.py` orchestrator. A single SPY target aggregates the beta core and the equity hedge. Options remain atomic and defined-risk. Integration smoke parameters and formal-evaluation parameters are explicit and mutually exclusive.

Official implementation references:

- <https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/history-requests>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/equity-options/handling-data>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/transaction-fees/supported-models>
- <https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2>
- <https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule>

## Frozen integration contract

- SPY core beta target 1.00; accepted portfolio range 0.80-1.20.
- Module standalone volatility budgets remain Equity 5%, Futures 7%, Option 3%; no module may exceed 40% of total Alpha risk budget.
- Risk-budget concentration is reduced by deterministic water-filling; no module is levered above its standalone target.
- Portfolio volatility target is 18%. A conservative sum-of-standalone-risk forecast can only reduce Alpha. When SPY alone exceeds 18%, the core is retained and Alpha is reduced toward zero.
- Alpha gross cap 1.00x, total gross cap 2.00x. A single uniform reduction preserves sleeve ordering when either cap binds.
- Peak-to-current drawdown below 15% uses normal Alpha scale; 15%-25% uses 50%; at or above 25% uses zero. Defined-risk options may only be closed, not enlarged, during forced reduction.
- Portfolio beta is corrected with the raw-SPY core after including the equity SPY hedge and frozen/dynamic sleeve beta estimates.
- SPY and option strike comparisons use raw data. Point-in-time equity-factor history requests explicitly use `SCALED_RAW`; benchmark evidence uses a separate total-return history request.
- Base costs retain the approved commissions and slippage. A conservative regulatory overlay charges sell-side Section 31 at 27.80 USD per million, 2026 FINRA TAF at 0.000195 USD/share capped at 9.79 USD/trade, option TAF at 0.00329 USD/contract, and 0.02 USD/futures contract. Applying the maximum known 2015-2026 rates to the whole period can understate returns, never increase them.
- `slippage_multiplier` is frozen to the allowed values 1 or 2. It changes only adverse slippage, not signal or commission logic.
- Integration smoke: 2012-01-01 through 2015-03-31, 1,000,000 USD, non-live and non-formal.
- No broker connection, live node, cryptocurrency, parameter search, annual-gap chasing, or formal conclusion in this milestone.

## Task 1: Pure portfolio coordinator

- Create `portfolio-integration-contract.json`, `risk.py`, and `tests/test_portfolio_risk.py`.
- First write failing artificial fixtures for 40% risk-contribution water-filling, 18% conservative volatility reduction, 1.00x Alpha gross, 2.00x total gross, exact beta correction, 15%/25% drawdown states, invalid/missing forecasts, and invariance to appended future evidence.
- Implement immutable inputs/results and fail closed on non-finite values, missing sleeves, wrong timestamps, impossible beta/leverage, or negative equity.
- Run focused/full tests and commit `feat: add portfolio risk coordinator`.

## Task 2: Complete execution policy

- Create `execution.py` and `tests/test_execution_policy.py` while retaining the already-tested asset-level `costs.py` arithmetic.
- First write failing fixtures for equity/ETF, futures, and option commissions; conservative sell-only regulatory charges; base/double adverse slippage; whole-order minimums/caps; and no fee on canceled unfilled orders.
- Implement pure fee decisions plus adapter-facing policy markers. Do not depend on today's broker account or a live endpoint.
- Run focused/full tests and commit `feat: add integrated execution policy`.

## Task 3: Shared-account cloud sleeves

- Create `cloud_adapters/equity_sleeve.py`, `cloud_adapters/futures_sleeve.py`, `cloud_adapters/option_sleeve.py`, and adapter contract tests.
- Move only QuantConnect lifecycle adaptation out of the three proven smoke projects; continue importing the same pure universe, signal, allocation, roll, option-risk, and lifecycle modules.
- Each service exposes proposed gross, estimated beta, readiness/license status, counters, and order targets. It must consume the orchestrator's scale immediately before order creation.
- Equity orders only stock targets; its SPY hedge is returned to the orchestrator for aggregation with the core. Futures order only selected actual contracts. Options retain same-expiry atomic combo orders and cannot increase risk when the drawdown scale is zero.
- Use prefixes/tags to make every order and statistic attributable to one sleeve.
- Run focused/full tests and commit `refactor: add shared-account cloud sleeve adapters`.

## Task 4: Orchestrator, daily evidence, and gates

- Replace the foundation-only `main.py` with orchestration only; update `project-manifest.json` to `portfolio-integration-smoke` while keeping `formal_evaluation=false` and `live_trading=false`.
- Initialize one raw SPY minute subscription, one point-in-time equity universe, all 13 futures universes, and one SPY option universe. Combine security initialization so each asset gets the frozen fee/slippage policy.
- Refresh drawdown/risk scales from completed data, aggregate SPY core plus hedge, route lifecycle callbacks, and record daily strategy equity, SPY total-return benchmark, leverage, Alpha gross, beta, margin, drawdown, costs, and causal counters.
- Any margin call, forced liquidation, negative margin remaining, leverage/beta/risk breach, naked option state, future input, missing license, or inconsistent daily evidence sets an irreversible fail-closed gate.
- Add source/manifest tests and commit `feat: integrate alpha sleeves with SPY beta core`.

## Task 5: Non-formal integration cloud evidence

- Run all local tests, validators, secret scan, and `git diff --check`.
- Push the integrated smoke to QuantConnect Cloud. Inspect compile status, runtime status, orders, trades, custom statistics, and chart availability; a CLI exit code alone is insufficient.
- Archive exact commit/project/compile/backtest IDs, URL, dates, costs, module activity, risk maxima, margin state, license state, and every retained diagnostic in `docs/portfolio-integration.md`.
- Do not loosen economic parameters if the smoke fails. Fix only implementation defects with a regression test and retain failed backtest IDs.
- Reverify tests, GitHub `PRIVATE`, branch hash, merge to `main`, re-test, remove the clean worktree, verify privacy again, push `main`, and compare hashes.

## Completion gate

```text
All three previously verified sleeves run in one account and remain attributable.
SPY core and equity hedge are aggregated exactly once.
Risk contribution <= 40%, Alpha gross <= 1.00x, total gross <= 2.00x, and beta is 0.80-1.20.
The 15% and 25% drawdown rules are irreversible for the current risk refresh and cannot increase Alpha.
Base and double-slippage paths share signals and differ only in adverse execution.
Regulatory costs are explicit and conservative.
No naked option, continuous-future order, margin violation, future input, or live-trading path exists.
The completed cloud run is non-formal and archived before the frozen evaluation begins.
```
