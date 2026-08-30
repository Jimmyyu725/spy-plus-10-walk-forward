from AlgorithmImports import *
from datetime import date, datetime, timezone
from decimal import Decimal as PythonDecimal
from pathlib import Path
from zoneinfo import ZoneInfo

from audit import AuditTrail
from baseline import load_baseline_contract
from benchmark import PricePoint, build_spy_buy_hold
from cloud_adapters.equity_sleeve import EquityFactorSleeve
from cloud_adapters.futures_sleeve import FuturesTrendSleeve
from cloud_adapters.option_sleeve import DefinedRiskOptionSleeve
from cloud_adapters.reality_models import (
    EquityAdverseSlippageModel,
    FutureOneTickSlippageModel,
    IntegratedFeeModel,
    OptionAdverseSlippageModel,
)
from costs import equity_execution
from execution import REGULATORY_POLICY_STATUS
from ledger import CashLedger
from metrics import EquityPoint, evaluate_annual_gates
from risk import (
    DatedReturn,
    PortfolioRiskError,
    SleeveForecast,
    annualized_volatility,
    coordinate_portfolio_risk,
    load_portfolio_integration_contract,
)


class SpyPlusTenWalkForward(QCAlgorithm):
    """Non-formal shared-account integration smoke; no live trading path."""

    def initialize(self):
        project = Path(__file__).resolve().parent
        baseline = load_baseline_contract(
            project / "baseline-contract.json",
            allow_embedded=True,
        )
        integration = load_portfolio_integration_contract(
            project / "portfolio-integration-contract.json",
            allow_embedded=True,
        )
        if baseline.formal_evaluation or baseline.live_trading:
            raise RuntimeError("baseline must remain non-formal and non-live")
        if integration["formal_evaluation"] or integration["live_trading"]:
            raise RuntimeError("integration smoke must remain non-formal and non-live")
        mode = self.get_parameter("evaluation_mode") or "integration-smoke"
        if mode != "integration-smoke":
            raise RuntimeError("only the non-formal integration smoke is enabled")
        raw_slippage = self.get_parameter("slippage_multiplier")
        self._slippage_multiplier = float(raw_slippage) if raw_slippage else 1.0
        if self._slippage_multiplier not in {1.0, 2.0}:
            raise RuntimeError("slippage multiplier must be frozen to 1 or 2")

        self.set_start_date(2012, 1, 1)
        self.set_end_date(2015, 3, 31)
        self.set_cash(1_000_000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_brokerage_model(BrokerageName.QUANT_CONNECT_BROKERAGE)
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.set_security_initializer(self._initialize_security)
        self._spy = self.add_equity(
            "SPY",
            Resolution.MINUTE,
            data_normalization_mode=DataNormalizationMode.RAW,
        ).symbol
        self.set_benchmark(self._spy)

        self._trading_start = date(2013, 1, 2)
        self._initial_cash = PythonDecimal("1000000")
        self._equity = EquityFactorSleeve(self, self._spy)
        self._futures = FuturesTrendSleeve(self)
        self._option = DefinedRiskOptionSleeve(
            self,
            self._spy,
            self._slippage_multiplier,
        )

        self._risk_allocation = None
        self._risk_refresh_count = 0
        self._peak_equity = 1_000_000.0
        self._gate_failures = set()
        self._core_order_count = 0
        self._margin_call_count = 0
        self._margin_warning_count = 0
        self._strategy_points = []
        self._benchmark_prices = []
        self._benchmark_points = []
        self._max_alpha_gross = 0.0
        self._max_total_gross = 0.0
        self._max_risk_contribution = 0.0
        self._min_beta = float("inf")
        self._max_beta = float("-inf")
        self._max_drawdown = 0.0
        self._max_margin_used_fraction = 0.0

        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_open(self._spy, 29),
            self._refresh_portfolio_risk,
        )
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_open(self._spy, 31),
            self._execute_equity_targets,
        )
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_open(self._spy, 32),
            self._rebalance_spy_core,
        )
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_close(self._spy, 2),
            self._record_daily_evidence,
        )

    def _initialize_security(self, security):
        if security.type in {
            SecurityType.EQUITY,
            SecurityType.FUTURE,
            SecurityType.OPTION,
        }:
            security.set_fee_model(IntegratedFeeModel())
        if security.type == SecurityType.EQUITY:
            security.set_slippage_model(
                EquityAdverseSlippageModel(self._slippage_multiplier)
            )
        elif security.type == SecurityType.FUTURE:
            security.set_slippage_model(
                FutureOneTickSlippageModel(self._slippage_multiplier)
            )
        elif security.type == SecurityType.OPTION:
            security.set_slippage_model(
                OptionAdverseSlippageModel(self._slippage_multiplier)
            )

    def can_trade_now(self):
        return self.time.date() >= self._trading_start

    @staticmethod
    def _utc_aware(value):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _bar_end_utc(value):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(
            timezone.utc
        )

    def _completed_spy_risk_evidence(self):
        bars = list(
            self.history[TradeBar](
                self._spy,
                61,
                Resolution.DAILY,
                data_normalization_mode=DataNormalizationMode.SCALED_RAW,
            )
        )
        if len(bars) < 61:
            raise PortfolioRiskError("61 completed SPY bars are required")
        points = []
        for previous, current in zip(bars, bars[1:]):
            if previous.close <= 0 or current.close <= 0:
                raise PortfolioRiskError("SPY risk prices must be positive")
            points.append(
                DatedReturn(
                    current.end_time.date(),
                    float(current.close / previous.close - 1),
                )
            )
        cutoff = points[-1].as_of
        volatility = annualized_volatility(points, cutoff=cutoff, lookback=60)
        return volatility, self._bar_end_utc(bars[-1].end_time)

    def _refresh_portfolio_risk(self):
        current_equity = float(self.portfolio.total_portfolio_value)
        if current_equity <= 0:
            self._gate_failures.add("NON_POSITIVE_EQUITY")
            return
        if self.can_trade_now():
            self._peak_equity = max(self._peak_equity, current_equity)
        try:
            spy_volatility, data_cutoff = self._completed_spy_risk_evidence()
            decision_time = self._utc_aware(self.utc_time)
            forecasts = [
                SleeveForecast(
                    "EQUITY",
                    data_cutoff,
                    0.05,
                    self._equity.proposed_gross(),
                    self._equity.estimated_beta(),
                ),
                SleeveForecast(
                    "FUTURES",
                    data_cutoff,
                    0.07,
                    self._futures.proposed_gross(),
                    self._futures.estimated_beta(),
                ),
                SleeveForecast(
                    "OPTION",
                    data_cutoff,
                    0.03,
                    self._option.proposed_gross(),
                    self._option.estimated_beta(),
                ),
            ]
            allocation = coordinate_portfolio_risk(
                forecasts,
                decision_time=decision_time,
                spy_annual_volatility=spy_volatility,
                peak_equity=self._peak_equity,
                current_equity=min(current_equity, self._peak_equity),
            )
        except PortfolioRiskError as error:
            if self.can_trade_now():
                self._gate_failures.add("PORTFOLIO_RISK_EVIDENCE")
                self.error(f"portfolio risk failed closed: {error}")
            self._futures.set_scale(0.0)
            self._option.set_scale(0.0)
            return
        self._risk_allocation = allocation
        self._risk_refresh_count += 1
        self._futures.set_scale(allocation.scales["FUTURES"])
        self._option.set_scale(allocation.scales["OPTION"])
        self._max_alpha_gross = max(self._max_alpha_gross, allocation.alpha_gross)
        self._max_total_gross = max(self._max_total_gross, allocation.total_gross)
        self._max_risk_contribution = max(
            self._max_risk_contribution,
            allocation.maximum_risk_contribution,
        )
        self._min_beta = min(self._min_beta, allocation.predicted_beta)
        self._max_beta = max(self._max_beta, allocation.predicted_beta)
        self._max_drawdown = max(self._max_drawdown, allocation.drawdown)

    def _execute_equity_targets(self):
        if self._risk_allocation is None:
            return
        self._equity.execute_pending(self._risk_allocation.scales["EQUITY"])

    def _rebalance_spy_core(self):
        if self._risk_allocation is None or not self.can_trade_now():
            return
        equity_scale = self._equity.applied_scale()
        futures_scale = self._futures.applied_scale()
        option_scale = self._option.applied_scale()
        core = 1.0 - (
            self._equity.estimated_beta() * equity_scale
            + self._futures.estimated_beta() * futures_scale
            + self._option.estimated_beta() * option_scale
        )
        target = core + self._equity.spy_hedge_weight()
        before = len(self.transactions.get_orders())
        self.set_holdings(self._spy, target, tag="portfolio:spy-core-plus-equity-hedge")
        self._core_order_count += len(self.transactions.get_orders()) - before

    def on_data(self, data: Slice):
        self._futures.on_data(data)
        self._option.on_data(data)

    def _actual_total_gross(self, equity):
        gross = 0.0
        for security in self.securities.values():
            holding = self.portfolio[security.symbol]
            if holding.quantity == 0:
                continue
            if security.type == SecurityType.FUTURE:
                multiplier = float(security.symbol_properties.contract_multiplier)
                gross += abs(float(holding.quantity) * float(security.price) * multiplier)
            elif security.type == SecurityType.EQUITY:
                gross += abs(float(holding.holdings_value))
        gross += self._option.actual_gross() * equity
        return gross / equity if equity > 0 else float("inf")

    def _record_daily_evidence(self):
        if not self.can_trade_now():
            return
        equity = float(self.portfolio.total_portfolio_value)
        if equity <= 0:
            self._gate_failures.add("NON_POSITIVE_EQUITY")
            return
        day = self.time.date()
        if self._strategy_points and self._strategy_points[-1].as_of >= day:
            return
        history = list(
            self.history[TradeBar](
                self._spy,
                1,
                Resolution.DAILY,
                data_normalization_mode=DataNormalizationMode.TOTAL_RETURN,
            )
        )
        if not history or history[-1].close <= 0:
            self._gate_failures.add("BENCHMARK_TOTAL_RETURN_MISSING")
            return
        benchmark_day = history[-1].end_time.date()
        if benchmark_day != day:
            self._gate_failures.add("BENCHMARK_DATE_MISMATCH")
            return
        self._benchmark_prices.append(PricePoint(day, history[-1].close))
        benchmark = build_spy_buy_hold(
            self._benchmark_prices,
            initial_cash=self._initial_cash,
        )
        benchmark_value = benchmark.equity[-1].value
        self._strategy_points.append(EquityPoint(day, equity))
        self._benchmark_points.append(EquityPoint(day, benchmark_value))
        self.plot("Daily Evidence", "Strategy Equity", equity)
        self.plot("Daily Evidence", "SPY Total Return", float(benchmark_value))

        margin_used = float(self.portfolio.total_margin_used)
        margin_fraction = margin_used / equity
        self._max_margin_used_fraction = max(
            self._max_margin_used_fraction,
            margin_fraction,
        )
        if float(self.portfolio.margin_remaining) < -1e-8:
            self._gate_failures.add("NEGATIVE_MARGIN_REMAINING")
        actual_gross = self._actual_total_gross(equity)
        self._max_total_gross = max(self._max_total_gross, actual_gross)
        if actual_gross > 2.0 + 1e-6:
            self._gate_failures.add("ACTUAL_TOTAL_GROSS_BREACH")

    def on_order_event(self, order_event):
        self._option.on_order_event(order_event)
        if order_event.status == OrderStatus.INVALID:
            self._gate_failures.add("ORDER_INVALID")
        if (
            order_event.status == OrderStatus.PARTIALLY_FILLED
            and order_event.symbol.security_type == SecurityType.OPTION
        ):
            self._gate_failures.add("OPTION_PARTIAL_FILL")

    def on_assignment_order_event(self, assignment_event):
        self._option.on_assignment_order_event(assignment_event)
        self._gate_failures.add("OPTION_ASSIGNMENT")

    def on_margin_call(self, requests):
        self._margin_call_count += 1
        self._gate_failures.add("MARGIN_CALL")

    def on_margin_call_warning(self):
        self._margin_warning_count += 1
        self._gate_failures.add("MARGIN_CALL_WARNING")

    def _validate_sleeve_statistics(self, statistics):
        zero_required = (
            "CONTINUOUS_ORDER_COUNT",
            "EQUITY_FUTURE_INPUT_COUNT",
            "OPTION_FUTURE_INPUT_COUNT",
            "OPTION_NAKED_LEG_COUNT",
            "OPTION_MAX_LOSS_BREACH_COUNT",
            "OPTION_COMBO_INVALID",
            "TREND_SCALE_VIOLATION_COUNT",
        )
        for key in zero_required:
            if int(statistics.get(key, 0)) != 0:
                self._gate_failures.add(key)
        if statistics.get("EQUITY_LICENSE_STATUS") != "AVAILABLE":
            self._gate_failures.add("EQUITY_LICENSE_UNAVAILABLE")
        if statistics.get("OPTION_LICENSE_STATUS") != "AVAILABLE":
            self._gate_failures.add("OPTION_LICENSE_UNAVAILABLE")
        if int(statistics.get("TREND_ORDER_COUNT", 0)) <= 0:
            self._gate_failures.add("TREND_ORDER_COUNT")
        for key, value in statistics.items():
            if not key.startswith("ROOT_"):
                continue
            encoded = str(value)
            for required in ("history=true", "contract=true", "signal=true"):
                if required not in encoded:
                    self._gate_failures.add(f"{key}_{required.split('=')[0].upper()}")

    def on_end_of_algorithm(self):
        statistics = {}
        for sleeve in (self._equity, self._futures, self._option):
            statistics.update(sleeve.statistics())
        self._validate_sleeve_statistics(statistics)
        if not self._strategy_points or not self._benchmark_points:
            self._gate_failures.add("DAILY_EVIDENCE_MISSING")
        else:
            annual = evaluate_annual_gates(
                self._strategy_points,
                self._benchmark_points,
                initial_value=self._initial_cash,
                as_of=self._strategy_points[-1].as_of,
            )
            for row in annual.rows:
                statistics[f"INTEGRATION_YEAR_{row.year}"] = (
                    f"{row.period},strategy={row.strategy_return},"
                    f"spy={row.spy_return},excess={row.excess_return},"
                    f"status={row.status}"
                )
        statistics.update(
            {
                "PORTFOLIO_FORMAL_EVALUATION": "false",
                "PORTFOLIO_GATE_STATUS": (
                    "PASS" if not self._gate_failures else "FAIL"
                ),
                "PORTFOLIO_GATE_FAILURES": (
                    ",".join(sorted(self._gate_failures)) or "NONE"
                ),
                "PORTFOLIO_RISK_REFRESH_COUNT": self._risk_refresh_count,
                "PORTFOLIO_CORE_ORDER_COUNT": self._core_order_count,
                "PORTFOLIO_MAX_ALPHA_GROSS": f"{self._max_alpha_gross:.12f}",
                "PORTFOLIO_MAX_TOTAL_GROSS": f"{self._max_total_gross:.12f}",
                "PORTFOLIO_MAX_RISK_CONTRIBUTION": (
                    f"{self._max_risk_contribution:.12f}"
                ),
                "PORTFOLIO_MIN_BETA": (
                    f"{self._min_beta:.12f}"
                    if self._min_beta != float("inf")
                    else "UNAVAILABLE"
                ),
                "PORTFOLIO_MAX_BETA": (
                    f"{self._max_beta:.12f}"
                    if self._max_beta != float("-inf")
                    else "UNAVAILABLE"
                ),
                "PORTFOLIO_MAX_DRAWDOWN": f"{self._max_drawdown:.12f}",
                "PORTFOLIO_MAX_MARGIN_USED_FRACTION": (
                    f"{self._max_margin_used_fraction:.12f}"
                ),
                "PORTFOLIO_MARGIN_CALL_COUNT": self._margin_call_count,
                "PORTFOLIO_MARGIN_WARNING_COUNT": self._margin_warning_count,
                "PORTFOLIO_DAILY_EVIDENCE_COUNT": len(self._strategy_points),
                "PORTFOLIO_REGULATORY_FEE_STATUS": REGULATORY_POLICY_STATUS,
                "PORTFOLIO_SLIPPAGE_MULTIPLIER": self._slippage_multiplier,
            }
        )
        for key, value in statistics.items():
            self.set_summary_statistic(key, str(value))
