# Futures Trend Alpha Cloud Evidence

- Purpose: independent implementation, data-coverage, and order-routing smoke test
- Formal evaluation: false
- Live trading: disabled
- Initial cash: 1,000,000 USD
- Backtest range: 2012-01-01 through 2015-03-31
- LEAN CLI version: lean 1.0.229
- LEAN engine version: 2.5.0.0.18041
- Git commit executed: 43aef6fb988dce0337752105cca2b970d568857b
- QuantConnect project ID: 35860486
- QuantConnect compile ID: 70bfd73981e04007c919fa536651afe8-923584bb2b2a6afa45e434b6d4721df9
- QuantConnect backtest ID: 6cf80fdfc04f7988a907ee7ec0ee1764
- Result URL: https://www.quantconnect.com/project/35860486/6cf80fdfc04f7988a907ee7ec0ee1764
- Cloud status: completed without runtime error

## Frozen universe and rules

- Roots: ES, NQ, ZN, ZB, GC, SI, CL, NG, ZC, ZS, 6E, 6J, 6B
- Trend signal: equal-weighted signs of 63-, 126-, and 252-completed-bar returns
- Risk allocation: 60-day inverse volatility, 252-day covariance, 7% annualized target, 70% gross cap
- Roll rule: exclude contracts inside a 7-day expiry buffer, then rank by current volume, open interest, and expiry
- Execution: signals are formed from completed data and submitted on a later bar; only actual contracts are eligible for orders
- Costs: 2.50 USD per contract per side and one minimum price variation of slippage

## Custom statistics

| Statistic | Value |
|---|---:|
| TREND_SIGNAL_COUNT | 62 |
| TREND_ORDER_COUNT | 26 |
| CONTINUOUS_ORDER_COUNT | 0 |

QuantConnect reported 28 total orders while the strategy's own counter recorded 26 submissions. This smoke record does not infer the source of the two additional engine-reported orders; the cloud result retains the event-level order history for inspection.

## Per-root coverage

| Root | 253 bars | Valid actual contract | Signal | Strategy order |
|---|---:|---:|---:|---:|
| ES | yes | yes | yes | no |
| NQ | yes | yes | yes | yes |
| ZN | yes | yes | yes | yes |
| ZB | yes | yes | yes | no |
| GC | yes | yes | yes | no |
| SI | yes | yes | yes | no |
| CL | yes | yes | yes | no |
| NG | yes | yes | yes | no |
| ZC | yes | yes | yes | yes |
| ZS | yes | yes | yes | no |
| 6E | yes | yes | yes | no |
| 6J | yes | yes | yes | yes |
| 6B | yes | yes | yes | yes |

An order value of `no` means the frozen allocation and whole-contract sizing produced no non-zero order for that root during this bounded smoke period. It is not treated as a missing-data failure.

## Result boundary

This run verifies that the frozen futures trend component compiles, receives sufficient point-in-time data for all 13 roots, selects tradable contracts, produces signals, places actual-contract orders, and never submits an order for a continuous symbol. It is deliberately an early-period, non-formal smoke test and is not evidence that the combined strategy passes the annual `SPY total return + 10 percentage points` objective.
