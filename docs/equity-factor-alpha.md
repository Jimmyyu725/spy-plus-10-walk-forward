# Equity Factor Alpha Cloud Evidence

- Purpose: independent point-in-time data, scoring, allocation, and execution smoke test
- Formal evaluation: false
- Live trading: disabled
- Initial cash: 1,000,000 USD
- Backtest range: 2012-01-01 through 2015-03-31
- LEAN CLI version: lean 1.0.229
- LEAN engine version: 2.5.0.0.18041
- Git commit executed: 3940eede403830f129f973852774c7efa39e8858
- QuantConnect project ID: 35861090
- QuantConnect compile ID: 12f6e0205547d3c51b7a645c1e5e3885-8c43f6f1fd9f35c48174279a3ab772c6
- QuantConnect backtest ID: ab974ff307f53f3b54db0aa53de5c24a
- Result URL: https://www.quantconnect.com/project/35861090/ab974ff307f53f3b54db0aa53de5c24a
- Cloud status: completed without runtime error

## Frozen implementation

- Historical QuantConnect US fundamental universe; no present-day constituent list
- Minimum price 5 USD; top 500 by prior 20 completed days' average dollar volume
- 12-1 momentum from 253 completed adjusted closes
- Quality: 50% ROE plus 50% gross-profit-to-assets using the point-in-time Morningstar objects delivered to the universe callback
- Low residual volatility: negative annualized residual standard deviation from 126 aligned stock/SPY returns
- Cross-sectional 1%/99% winsorization and population z-scores; final weights 50% momentum, 25% quality, 25% low residual volatility
- Top 30, inverse-volatility long allocation, SPY beta hedge, 5% module volatility target, 50% gross cap
- Monthly decision uses the prior completed month-end snapshot; execution is scheduled 30 minutes after the next regular-session open

## Custom statistics

| Statistic | Value |
|---|---:|
| EQUITY_UNIVERSE_OBSERVATIONS | 815 |
| EQUITY_MONTH_END_SIGNALS | 18 |
| EQUITY_SELECTED_COUNT | 30 |
| EQUITY_ORDER_COUNT | 753 |
| EQUITY_FUTURE_INPUT_COUNT | 0 |
| EQUITY_REJECTED_POST_CUTOFF_COUNT | 8,496 |
| EQUITY_MISSING_FUNDAMENTAL_COUNT | 3,472,915 |
| EQUITY_BETA_AFTER | -0.000000000000 |
| EQUITY_GROSS_EXPOSURE | 0.500000000000 |
| EQUITY_LICENSE_STATUS | AVAILABLE |

`EQUITY_MISSING_FUNDAMENTAL_COUNT` is the cumulative count across the full daily cross-section; incomplete records are excluded rather than imputed. `EQUITY_REJECTED_POST_CUTOFF_COUNT` records bars returned by batch history whose timestamps exceeded the frozen signal cutoff. They were discarded before factor calculation, while `EQUITY_FUTURE_INPUT_COUNT=0` confirms none were used.

The cloud engine reported 757 total orders versus 753 strategy-counted submissions. The event ledger remains available in the cloud result; this evidence does not infer the source of the four additional engine-reported orders.

## Costs and limitations

The smoke adapter applies 0.005 USD per share with a 1 USD order minimum and adverse slippage equal to the greater of half-spread or 5 bps. Regulatory fees are explicitly marked `DEFERRED_TO_FORMAL_INTEGRATION`; therefore this component smoke is not a complete formal cost result. Tax is excluded under the approved specification.

The retained diagnostic predecessor is backtest `66f881b28cff29e412106f2c50ad110c`. It produced identical economic results but counted rejected post-cutoff rows under the wrong audit label. The verified run above changes only that accounting label, not the strategy inputs or parameters.

## Result boundary

This run proves the licensed point-in-time fundamental fields are accessible, completed-data filters work, the frozen factor produces orders, and the ex-ante beta/gross constraints are enforced. It is an early-period, non-formal component smoke test. Its 4.274% total return is not evidence that the combined strategy passes the annual `SPY total return + 10 percentage points` objective.
