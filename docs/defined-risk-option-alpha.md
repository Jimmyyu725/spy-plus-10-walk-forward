# Defined-Risk Option Alpha Cloud Evidence

- Purpose: independent point-in-time signal, option-chain, bounded-risk sizing, lifecycle, and atomic-order smoke test
- Formal evaluation: false
- Live trading: disabled
- Initial cash: 1,000,000 USD
- Backtest range: 2012-01-01 through 2015-03-31
- LEAN CLI version: lean 1.0.229
- LEAN engine version: 2.5.0.0.18041
- Git commit executed: 1db79d3a51551d021f34866a1028a5af74e918ce
- QuantConnect project ID: 35862360
- QuantConnect compile ID: 8d3d4d5c9e79915638e76408e866062f-6a581ffa4f949c031653a28997c3df3b
- QuantConnect backtest ID: 860f5821a9f7f000616af32ad7d5a2b5
- Result URL: https://www.quantconnect.com/project/35862360/860f5821a9f7f000616af32ad7d5a2b5
- Cloud status: completed without initialization or runtime error

## Frozen implementation

- Underlying: raw SPY minute data; option universe includes weekly puts with 30-60 DTE
- Weekly regime decision: first completed trading-day close, SPY above its completed 200-day SMA, and closest-to-45-DTE ATM put IV at least 0.05 above 20-day realized volatility
- Earliest entry: next trading day at 10:00 ET
- Spread: same-expiry bull put spread; short delta nearest -0.20 and long delta nearest -0.10, with the long strike strictly below the short strike
- Liquidity: bid greater than zero, non-crossed quote, spread/mid at most 20%, volume at least 1, and open interest at least 100 on both legs
- Risk: finite maximum loss, at most 0.50% of equity per spread, 3% rolling 12-month realized-loss budget, 3% option-sleeve volatility target, and no overlapping spread
- Exit: buy back at no more than 50% of entry credit or at the first tradable point with at most 21 DTE
- Execution: atomic combo-leg limit orders; adverse fill limits at mid plus/minus 25% of each leg's spread, rounded against the strategy
- Fees: 0.65 USD per contract per leg with a 1 USD per-order minimum

## Cloud result

| Statistic | Value |
|---|---:|
| Start equity | 1,000,000.00 USD |
| End equity | 1,002,679.40 USD |
| Net profit | 0.268% |
| Drawdown | 0.300% |
| Total fees | 1,003.60 USD |
| Total leg orders | 106 |
| OPTION_CHAIN_OBSERVATIONS | 155 |
| OPTION_ELIGIBLE_SIGNALS | 22 |
| OPTION_SPREADS_OPENED | 15 |
| OPTION_SPREADS_CLOSED | 15 |
| OPTION_REJECT_NO_CHAIN | 0 |
| OPTION_REJECT_REGIME | 112 |
| OPTION_REJECT_LIQUIDITY | 3 |
| OPTION_REJECT_RISK | 0 |
| OPTION_COMBO_STALE_CANCELED | 23 |
| OPTION_COMBO_INVALID | 0 |
| OPTION_NAKED_LEG_COUNT | 0 |
| OPTION_MAX_LOSS_BREACH_COUNT | 0 |
| OPTION_FUTURE_INPUT_COUNT | 0 |
| OPTION_ASSIGNMENT_EVENTS | 0 |
| OPTION_TRAILING_REALIZED_LOSS | 46.80 USD |
| OPTION_OPEN_POSITION_AT_END | false |
| OPTION_LICENSE_STATUS | AVAILABLE |
| OPTION_COST_MODEL_STATUS | PER_LEG_ADVERSE_LIMITS_AND_FEES |

The cloud order API returned 60 filled and 46 canceled leg orders. The 46 canceled legs belong to 23 two-leg groups, have no fill timestamp, and were canceled together by the explicit end-of-day stale-order rule. No group was invalid and no partially filled or naked state was recorded. `OPTION_COMBO_REJECTED=23` is retained as the aggregate compatibility counter; its entire value is explained by `OPTION_COMBO_STALE_CANCELED=23` and `OPTION_COMBO_INVALID=0`.

## Retained diagnostics

Backtest `1ea9e1fa72ee29caed519da5023d7931` failed during initialization because the adapter used a misspelled brokerage enum. The failure was converted into a source-level regression test before correction. Backtest `274c86f418395285a9e8eaee17146856` then completed with the same economics and risk gates as the verified run, but reported all 23 stale unfilled groups only under the aggregate combo-rejected label. The final run separates stale cancellations from invalid groups without changing signal, sizing, fill, or exit rules.

The one remaining cloud compile warning flags an intentional fail-closed exception boundary around pure signal validation. It does not suppress a runtime fault: rejected inputs increment an explicit counter and produce no order.

## Result boundary

This run verifies that licensed historical SPY option chains, quotes, Greeks, volume, and open interest are available; the frozen signal creates bounded-loss positions; atomic orders can fill and exit; and the causal, cost, loss-budget, maximum-loss, and naked-position gates remain intact. It is an early-period, non-formal component smoke test. Its 0.268% total return is not evidence that the combined strategy passes the annual `SPY total return + 10 percentage points` objective.
