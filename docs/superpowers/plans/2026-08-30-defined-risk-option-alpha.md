# Defined-Risk Option Alpha Implementation Plan

> Scope: implement and independently cloud-verify the approved SPY bull-put-spread sleeve. This is not the frozen 2015-current evaluation.

**Goal:** Use only historical SPY option chains to form bounded-loss 30-60 DTE credit spreads after a completed-data weekly signal, with deterministic contract choice, realistic multi-leg costs, explicit lifecycle rules, and no naked exposure.

**Architecture:** Pure modules own signal eligibility, chain validation/selection, payoff/risk sizing, and lifecycle state. A separate QuantConnect project adapts real historical chains and minute quotes, submits combo orders, and records audit statistics. Missing chains, quotes, Greeks, margin, or licensing fail closed.

Official references:

- <https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/equity-options/greeks-and-implied-volatility/key-concepts>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/universes/equity-options>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/asset-classes/equity-options>
- <https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/option-strategies/bull-put-spread>

## Frozen contract

Create `option-alpha-contract.json` before any cloud result:

- underlying SPY only; weeklys included;
- evaluate after the first complete trading-day close each week; earliest order next trading day 10:00 ET;
- entry regime: completed SPY close above completed 200-day SMA and closest-to-45-DTE ATM put IV at least 0.05 above 20-day annualized realized volatility;
- entry chain 30-60 DTE; expiry closest to 45 DTE, then earlier expiry;
- short put closest to delta -0.20 and long put closest to delta -0.10, same expiry, long strike strictly below short strike;
- ties: nearer expiry, higher open interest, then lower strike;
- each leg requires bid > 0, ask >= bid, spread/mid <= 20%, volume >= 1, and open interest >= 100;
- profit exit when spread debit is at most 50% of entry credit; time exit at the first tradable point with DTE <= 21;
- per-trade maximum loss including entry costs <= 0.50% of current equity; rolling 12-month realized option loss <= 3%; target sleeve volatility 3%; no overlapping spread unless the prior spread is fully closed;
- fee 0.65 USD/contract/leg with 1 USD/order minimum; adverse fill is mid plus/minus 25% spread rounded against the strategy to the minimum tick; double-slippage control retained;
- no naked legs, live trading, or formal evaluation.

## Task 1: Signal and chain selection

- Create `signals/option_signal.py`, `option_chain.py`, contract JSON, and focused tests.
- First write failing fixtures for 200-SMA/IV-premium eligibility, 20-day realized volatility, 30-60 DTE, exact delta targets, common expiry, quote/liquidity filters, tie-breaks, missing chain, and future-append invariance.
- Implement immutable dated inputs and fail-closed pure functions; run focused/full suites; commit `feat: add point-in-time option signal and chain selection`.

## Task 2: Defined loss, sizing, and lifecycle

- Create `option_risk.py`, `option_lifecycle.py`, and focused tests.
- First write failing tests for net credit, width, maximum loss, per-leg fees/slippage, 0.50% sizing, 3% rolling loss budget, 50% profit exit, 21-DTE exit, no overlap, and impossibility of naked or reversed-strike structures.
- Implement pure records/state transitions. Every state transition requires `data_cutoff < signal_time < order_time`; future fixtures cannot change a past action. Run all tests; commit `feat: add defined-risk option sizing and lifecycle`.

## Task 3: Independent cloud adapter

- Create `SPY Plus 10 Walk-Forward - Defined Risk Option Smoke`, deterministic sync script, manifest, and sync tests.
- Fixed smoke range: 2012-01-01 through 2015-03-31, cash 1,000,000 USD, non-live/non-formal.
- Subscribe to raw SPY minute data and an SPY option universe including weeklys with 0-70 DTE and sufficient strikes. Use the prior-close precomputed universe Greeks only for the weekly regime audit; at 10:00 use the real current chain, bid/ask, volume, open interest, expiry, strike, IV, and delta.
- Submit both legs as one combo order; reject partial/naked state, and explicitly record order/fill/assignment/expiry events.
- Custom statistics must include chain observations, eligible signals, spreads opened/closed, rejected reasons, naked-leg count, max-loss breach count, future-input count, realized loss budget, license status, and cost-model status.
- Run tests and commit `feat: add independent defined-risk option smoke project`.

## Task 4: Cloud evidence and integration

- Run full local verification, then cloud compile/backtest. Inspect runtime status and custom gates, not only CLI exit code.
- If option data/Greeks/quotes are unavailable, archive `UNVERIFIED`; do not purchase data or loosen rules.
- Create `docs/defined-risk-option-alpha.md` with exact commit/project/compile/backtest IDs, URL, period, license, signals, orders, rejected reasons, risk/cost statistics, and explicit non-formal boundary.
- Re-test, scan for secrets, commit, verify GitHub `PRIVATE`, push/compare feature hash, merge to `main`, re-test, remove clean worktree, verify privacy, push/compare main hash.

## Completion gate

```text
Only historical SPY option chains and completed underlying data are used.
All economic parameters are frozen before cloud results.
Every spread has same-expiry long protection and a computable finite maximum loss.
No naked order or position is possible.
The 0.50% per-trade and 3% rolling-loss budgets are enforced.
Profit/time exits and all per-leg costs are deterministic and tested.
The cloud smoke is licensed, non-live, non-formal, and archived.
The final commit is synchronized to a freshly verified private repository.
```
