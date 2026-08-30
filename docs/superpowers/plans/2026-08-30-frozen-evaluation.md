# Frozen Evaluation Implementation Plan

> Execute this plan without changing economic rules after the first formal backtest result is created. Preserve and report every formal result, including failures.

**Goal:** Freeze the approved strategy, run one base-cost and one double-slippage QuantConnect Cloud evaluation from the same immutable commit, independently recompute the evidence, and archive an honest `PASS`, `FAIL`, or `UNVERIFIED` conclusion.

**Architecture:** QuantConnect Cloud remains the only historical-data and execution environment. The algorithm writes exact end-of-day evidence and signal chronology to a uniquely named compressed Object Store artifact. Atlas downloads Cloud API metadata, orders, trades, and that artifact, then a separate local verifier recomputes annual gates and drawdown without changing the strategy.

**Technology:** Python, QuantConnect LEAN/Algorithm Framework APIs, QuantConnect Cloud REST API, LEAN CLI, gzip/JSON, `unittest`, Git.

## Frozen decisions

- Evaluation warm-up starts `2012-01-01`; scoring begins on `2015-01-02`; the fixed final complete trading date is `2026-08-28`.
- The immutable formal parameters are `evaluation_mode=frozen-evaluation`, `slippage_multiplier=1|2`, and matching `evaluation_run_label=base|double`.
- The base run determines whether the return objective passes. The double-slippage run is a mandatory sensitivity test and must pass data and safety gates, but its annual return rows do not change the base objective verdict.
- Both runs must use the same Git commit and cloud project code. There is no retry, tuning, year deletion, benchmark change, or economic edit after the first formal result.
- A missing artifact, incomplete run, missing license, failed chronology audit, or irreconcilable recomputation is `UNVERIFIED`. A verified annual miss or safety/risk violation is `FAIL`.
- Formal execution is cloud backtest only. Live mode, broker connections, and real orders remain prohibited.

## Task 1: Freeze formal contracts and entry parameters

**Files:**
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/baseline-contract.json`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/portfolio-integration-contract.json`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/project-manifest.json`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/baseline.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/risk.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/main.py`
- Modify: `spy_plus_10/foundation.py`
- Test: `tests/test_foundation.py`
- Test: `tests/test_baseline_contract.py`
- Test: `tests/test_portfolio_integration_cloud.py`

1. Add failing tests for exact formal mode, fixed dates, live-mode rejection, slippage/run-label pairing, and frozen contract hashes.
2. Run the focused tests and confirm the new tests fail for the expected missing formal behavior.
3. Update the JSON contracts, embedded contract copies, manifest, validator, and entry-point guards.
4. Run the focused tests and the existing contract verifiers until they pass.

## Task 2: Enforce next-event futures execution and option chronology evidence

**Files:**
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/main.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/option_lifecycle.py`
- Test: `tests/test_futures_trend.py`
- Test: `tests/test_option_lifecycle.py`
- Test: `tests/test_portfolio_integration_cloud.py`

1. Add source and fixture tests proving a weekly futures signal is not executed in the same data slice.
2. Add fixture tests for option audit samples with strict `data_cutoff < signal < order < fill` chronology and rejection of non-strict samples.
3. Defer weekly futures execution to the next tradable slice without changing its signal formula or sizing.
4. Capture eligible option fill chronology, expose immutable audit samples, and rerun focused tests.

## Task 3: Write exact cloud evidence once at backtest end

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/formal_evidence.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward/main.py`
- Test: `tests/test_formal_evidence.py`
- Test: `tests/test_portfolio_integration_cloud.py`

1. Add failing pure tests for evidence schema, unique Object Store key construction, gzip/JSON round-trip, exact daily ordering, and formal status precedence.
2. Implement daily records containing strategy/benchmark equity, cumulative fees, margin, gross exposure, drawdown, beta/risk contribution, and non-zero positions.
3. Track fill-event fees and option chronology samples; save one compressed artifact under a run- and algorithm-specific key in `on_end_of_algorithm`.
4. Emit structured statistics for artifact key/save status/counts, data audit, safety gate, annual gate, and overall `PASS|FAIL|UNVERIFIED`.
5. Rerun focused tests.

## Task 4: Build independent artifact downloader and verifier

**Files:**
- Create: `spy_plus_10/frozen_evaluation.py`
- Create: `scripts/fetch_quantconnect_evidence.py`
- Create: `scripts/verify_frozen_evaluation.py`
- Test: `tests/test_frozen_evaluation.py`
- Test: `tests/test_fetch_quantconnect_evidence.py`

1. Add artificial fixtures that include passing, annual-failure, missing-evidence, chronology-failure, and 0.01-percentage-point reconciliation-boundary cases.
2. Implement a separate Decimal-based annual return, SPY+10 threshold, maximum drawdown, completeness, and chronology verifier.
3. Implement authenticated Cloud reads for backtest metadata, all paginated orders/trades, and the exact Object Store key without printing credentials.
4. Compare independent annual rows and drawdown with Cloud statistics at a tolerance of at most `0.0001` return units; derive the final status mechanically.
5. Run focused tests.

## Task 5: Freeze and verify the immutable formal commit

**Files:**
- Modify: `README.md`
- Create: `docs/frozen-evaluation-protocol.md`

1. Document the fixed dates, parameters, one-run rule, evidence schema, base/stress interpretation, and non-live boundary.
2. Run the complete artificial-fixture suite, foundation/audit verifiers, syntax compilation, contract consistency checks, and a secret scan.
3. Commit all implementation changes as the immutable formal version.
4. Verify the GitHub destination is `PRIVATE`, push the feature branch, and verify the remote commit equals the local commit.
5. Record the exact commit before launching any formal backtest.

## Task 6: Run the two formal cloud evaluations exactly once

**Files:**
- Create after runs: `docs/evidence/frozen-evaluation-v1/run-manifest.json`

1. Launch the base run with the immutable commit and exactly `evaluation_mode=frozen-evaluation`, `slippage_multiplier=1`, `evaluation_run_label=base`.
2. Preserve its project, compile, and backtest identifiers even if it fails.
3. Without changing code or inspecting/tuning annual results, launch the double-slippage run with only `slippage_multiplier=2`, `evaluation_run_label=double` changed.
4. Wait for both terminal states; never launch a replacement run under v1.
5. Record organization, project, commit, engine, datasets/licenses, dates, parameters, timestamps, backtest IDs, and Object Store keys.

## Task 7: Download, independently verify, and archive the verdict

**Files:**
- Create: `docs/evidence/frozen-evaluation-v1/base/*`
- Create: `docs/evidence/frozen-evaluation-v1/double/*`
- Create: `docs/frozen-evaluation.md`

1. Download both backtest payloads, every orders/trades page, and exact compressed daily evidence artifacts.
2. Run the independent verifier for each run and retain machine-readable output.
3. Inspect at least ten chronology samples and reconcile annual rows and maximum drawdown within `0.01` percentage point.
4. Produce a Chinese report with every year, strategy return, SPY total return, threshold, excess, and status; distinguish the mandatory double-slippage sensitivity result.
5. If any evidence cannot be verified, publish `UNVERIFIED`; if any base annual gate or safety gate fails, publish `FAIL`; publish `PASS` only if all required gates pass.
6. Commit the report and all allowable evidence, verify repository privacy, push, and verify the remote commit.

## Task 8: Integrate the completed milestone

1. Re-run the complete local verification suite against the archived evidence.
2. Review the branch diff for accidental credentials, live-trading configuration, economic changes after the frozen commit, and missing failed results.
3. Merge the completed feature branch to `main` only after verification; do not rewrite or squash away the immutable formal commit.
4. Verify the exact GitHub repository is private before pushing `main`, then confirm the remote main hash.
5. Remove the worktree only after the branch and evidence are safely pushed.

