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


class EquityFactorSleeve:
    """Point-in-time equity sleeve service for a shared QCAlgorithm account."""

    def __init__(self, algorithm, spy):
        self._algorithm = algorithm
        self._spy = spy
        algorithm.universe_settings.resolution = Resolution.MINUTE
        algorithm.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self._universe = algorithm.add_universe(self._select_fundamentals)

        self._snapshots = {}
        self._dollar_volume = {}
        self._qc_symbols = {}
        self._last_month = None
        self._last_cutoff = None
        self._pending = None
        self._current_allocation = None
        self._owned_symbols = set()
        self._last_scale = 0.0
        self._universe_observations = 0
        self._month_end_signals = 0
        self._selected_count = 0
        self._order_count = 0
        self._future_input_count = 0
        self._rejected_post_cutoff_count = 0
        self._missing_fundamental_count = 0
        self._beta_after = 0.0
        self._gross_exposure = 0.0
        self._license_status = "UNVERIFIED"

    def __getattr__(self, name):
        return getattr(self._algorithm, name)

    @property
    def data_cutoff(self):
        return self._last_cutoff

    @property
    def license_status(self):
        return self._license_status

    def proposed_gross(self):
        allocation = self._pending or self._current_allocation
        return allocation.gross_exposure if allocation is not None else 0.50

    def estimated_beta(self):
        allocation = self._pending or self._current_allocation
        return allocation.beta_after_hedge if allocation is not None else 0.0

    def applied_scale(self):
        return self._last_scale

    def spy_hedge_weight(self):
        if self._current_allocation is None:
            return 0.0
        return self._current_allocation.spy_weight * self._last_scale

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
        for bars in self.history[TradeBar](
            requested,
            253,
            Resolution.DAILY,
            data_normalization_mode=DataNormalizationMode.SCALED_RAW,
        ):
            for symbol, bar in bars.items():
                bar_day = bar.end_time.date()
                if bar_day > self._last_cutoff:
                    self._rejected_post_cutoff_count += 1
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

    def execute_pending(self, scale):
        if not 0 <= scale <= 1:
            raise ValueError("equity scale must be between zero and one")
        allocation = self._pending or self._current_allocation
        if allocation is None or not self._algorithm.can_trade_now():
            return
        # Between monthly signals, immediately reduce risk but never add churn by
        # chasing a higher daily allowance.  A new monthly signal resets the scale.
        if self._pending is None and scale >= self._last_scale - 1e-12:
            return
        desired = {
            self._qc_symbols[symbol]: weight * scale
            for symbol, weight in allocation.stock_weights.items()
        }
        before = len(self.transactions.get_orders())
        for symbol in sorted(self._owned_symbols - set(desired), key=str):
            if self.portfolio[symbol].invested:
                self.liquidate(symbol, tag="equity-factor:remove")
        for symbol, weight in desired.items():
            self.set_holdings(symbol, weight, tag="equity-factor:target")
        self._order_count += len(self.transactions.get_orders()) - before
        self._owned_symbols = set(desired)
        self._current_allocation = allocation
        self._pending = None
        self._last_scale = scale

    def statistics(self):
        return {
            "EQUITY_UNIVERSE_OBSERVATIONS": self._universe_observations,
            "EQUITY_MONTH_END_SIGNALS": self._month_end_signals,
            "EQUITY_SELECTED_COUNT": self._selected_count,
            "EQUITY_ORDER_COUNT": self._order_count,
            "EQUITY_FUTURE_INPUT_COUNT": self._future_input_count,
            "EQUITY_REJECTED_POST_CUTOFF_COUNT": self._rejected_post_cutoff_count,
            "EQUITY_MISSING_FUNDAMENTAL_COUNT": self._missing_fundamental_count,
            "EQUITY_BETA_AFTER": f"{self._beta_after:.12f}",
            "EQUITY_GROSS_EXPOSURE": f"{self._gross_exposure:.12f}",
            "EQUITY_LICENSE_STATUS": self._license_status,
            "EQUITY_HISTORY_NORMALIZATION": "SCALED_RAW_POINT_IN_TIME",
        }
