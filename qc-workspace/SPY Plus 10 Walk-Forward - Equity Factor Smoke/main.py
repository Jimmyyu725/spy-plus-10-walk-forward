from AlgorithmImports import *
from collections import deque
from math import isfinite

from equity_allocation import AllocationError, allocate_equity_factors
from signals.equity_factor import (
    EquityPrice,
    FactorSignalError,
    compute_raw_equity_factor,
    rank_equity_factors,
)
from universe import (
    DollarVolumePoint,
    FundamentalSnapshot,
    UniverseSelectionError,
    select_equity_candidates,
)


class EquityCommissionModel(FeeModel):
    def get_order_fee(self, parameters):
        commission = max(abs(parameters.order.quantity) * 0.005, 1.0)
        return OrderFee(CashAmount(commission, "USD"))


class EquityAdverseSlippageModel:
    def get_slippage_approximation(self, asset, order):
        half_spread = 0.0
        if asset.bid_price > 0 and asset.ask_price >= asset.bid_price:
            half_spread = float(asset.ask_price - asset.bid_price) / 2
        return max(float(asset.price) * 0.0005, half_spread)


class SPYPlus10WalkForwardEquityFactorSmoke(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2012, 1, 1)
        self.set_end_date(2015, 3, 31)
        self.set_cash(1_000_000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.set_security_initializer(self._initialize_security)

        self._spy = self.add_equity(
            "SPY",
            Resolution.MINUTE,
            data_normalization_mode=DataNormalizationMode.ADJUSTED,
        ).symbol
        self.set_benchmark(self._spy)
        self.universe_settings.resolution = Resolution.MINUTE
        self.universe_settings.data_normalization_mode = DataNormalizationMode.ADJUSTED
        self._universe = self.add_universe(self._select_fundamentals)
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_open(self._spy, 30),
            self._execute_pending,
        )

        self._snapshots = {}
        self._dollar_volume = {}
        self._qc_symbols = {}
        self._last_month = None
        self._last_cutoff = None
        self._pending = None
        self._universe_observations = 0
        self._month_end_signals = 0
        self._selected_count = 0
        self._order_count = 0
        self._future_input_count = 0
        self._missing_fundamental_count = 0
        self._beta_after = 0.0
        self._gross_exposure = 0.0
        self._license_status = "UNVERIFIED"

    def _initialize_security(self, security):
        if security.type == SecurityType.EQUITY:
            security.set_fee_model(EquityCommissionModel())
            security.set_slippage_model(EquityAdverseSlippageModel())

    def _select_fundamentals(self, fundamentals):
        current_month = (self.time.year, self.time.month)
        selected_symbols = None
        if self._last_month is not None and current_month != self._last_month:
            selected_symbols = self._prepare_monthly_signal(self.time.date())
        self._capture_fundamentals(fundamentals, self.time.date())
        self._last_month = current_month
        self._universe_observations += 1
        if selected_symbols is None:
            return Universe.UNCHANGED
        return selected_symbols

    def _capture_fundamentals(self, fundamentals, as_of):
        snapshots = {}
        complete_quality = 0
        for item in fundamentals:
            symbol_key = str(item.symbol)
            self._qc_symbols[symbol_key] = item.symbol
            history = self._dollar_volume.setdefault(symbol_key, deque(maxlen=20))
            dollar_volume = float(item.dollar_volume)
            if isfinite(dollar_volume) and dollar_volume > 0:
                history.append(DollarVolumePoint(symbol_key, as_of, dollar_volume))
            try:
                roe = float(item.operation_ratios.roe.value)
                gross_profit = float(
                    item.financial_statements.income_statement.gross_profit.twelve_months
                )
                total_assets = float(
                    item.financial_statements.balance_sheet.total_assets.twelve_months
                )
            except (AttributeError, TypeError, ValueError):
                roe = gross_profit = total_assets = None
            if all(
                value is not None and isfinite(value)
                for value in (roe, gross_profit, total_assets)
            ):
                complete_quality += 1
            else:
                self._missing_fundamental_count += 1
            snapshots[symbol_key] = FundamentalSnapshot(
                symbol_key,
                as_of,
                float(item.price),
                bool(item.has_fundamental_data),
                roe,
                gross_profit,
                total_assets,
            )
        self._snapshots = snapshots
        self._last_cutoff = as_of
        if complete_quality:
            self._license_status = "AVAILABLE"

    def _prepare_monthly_signal(self, decision_day):
        if self._last_cutoff is None or not self._snapshots:
            return None
        histories = {
            symbol: list(points) for symbol, points in self._dollar_volume.items()
        }
        try:
            candidates = select_equity_candidates(
                list(self._snapshots.values()),
                histories,
                cutoff=self._last_cutoff,
                selection_time=decision_day,
            )
        except UniverseSelectionError as error:
            self.error(f"equity universe failed closed: {error}")
            return None
        if not candidates:
            return None
        qc_symbols = [self._qc_symbols[item.symbol] for item in candidates]
        requested = qc_symbols + [self._spy]
        prices = {symbol: [] for symbol in requested}
        for bars in self.history[TradeBar](requested, 253, Resolution.DAILY):
            for symbol, bar in bars.items():
                bar_day = bar.end_time.date()
                if bar_day > self._last_cutoff:
                    self._future_input_count += 1
                    continue
                prices[symbol].append(
                    EquityPrice(
                        "SPY" if symbol == self._spy else str(symbol),
                        bar_day,
                        float(bar.close),
                    )
                )
        raw = []
        for candidate in candidates:
            symbol = self._qc_symbols[candidate.symbol]
            try:
                raw.append(
                    compute_raw_equity_factor(
                        candidate,
                        prices[symbol],
                        prices[self._spy],
                        cutoff=self._last_cutoff,
                    )
                )
            except FactorSignalError:
                continue
        if not raw:
            return None
        try:
            ranked = rank_equity_factors(raw)
            allocation = allocate_equity_factors(list(ranked))
        except (FactorSignalError, AllocationError) as error:
            self.error(f"equity signal failed closed: {error}")
            return None
        self._pending = allocation
        self._month_end_signals += 1
        self._selected_count = len(allocation.stock_weights)
        self._beta_after = allocation.beta_after_hedge
        self._gross_exposure = allocation.gross_exposure
        return qc_symbols

    def _execute_pending(self):
        if self._pending is None:
            return
        targets = [
            PortfolioTarget(self._qc_symbols[symbol], weight)
            for symbol, weight in self._pending.stock_weights.items()
        ]
        targets.append(PortfolioTarget(self._spy, self._pending.spy_weight))
        before = len(self.transactions.get_orders())
        self.set_holdings(targets, True)
        self._order_count += len(self.transactions.get_orders()) - before
        self._pending = None

    def on_end_of_algorithm(self):
        statistics = {
            "EQUITY_UNIVERSE_OBSERVATIONS": self._universe_observations,
            "EQUITY_MONTH_END_SIGNALS": self._month_end_signals,
            "EQUITY_SELECTED_COUNT": self._selected_count,
            "EQUITY_ORDER_COUNT": self._order_count,
            "EQUITY_FUTURE_INPUT_COUNT": self._future_input_count,
            "EQUITY_MISSING_FUNDAMENTAL_COUNT": self._missing_fundamental_count,
            "EQUITY_BETA_AFTER": f"{self._beta_after:.12f}",
            "EQUITY_GROSS_EXPOSURE": f"{self._gross_exposure:.12f}",
            "EQUITY_LICENSE_STATUS": self._license_status,
            "EQUITY_REGULATORY_FEE_MODEL": "DEFERRED_TO_FORMAL_INTEGRATION",
        }
        for key, value in statistics.items():
            self.set_summary_statistic(key, str(value))
