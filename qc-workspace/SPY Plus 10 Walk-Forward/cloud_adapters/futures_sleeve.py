from AlgorithmImports import *
from collections import deque

from futures_allocation import AllocationError, allocate_trend
from futures_roll import ContractSnapshot, RollSelectionError, select_volume_contract
from signals.futures_trend import DailyPrice, TrendSignalError, compute_trend_signal


ROOT_CONSTANTS = {
    "ES": Futures.Indices.SP_500_E_MINI,
    "NQ": Futures.Indices.NASDAQ_100_E_MINI,
    "ZN": Futures.Financials.Y_10_TREASURY_NOTE,
    "ZB": Futures.Financials.Y_30_TREASURY_BOND,
    "GC": Futures.Metals.GOLD,
    "SI": Futures.Metals.SILVER,
    "CL": Futures.Energy.CRUDE_OIL_WTI,
    "NG": Futures.Energy.NATURAL_GAS,
    "ZC": Futures.Grains.CORN,
    "ZS": Futures.Grains.SOYBEANS,
    "6E": Futures.Currencies.EUR,
    "6J": Futures.Currencies.JPY,
    "6B": Futures.Currencies.GBP,
}

ROOT_BETA_ASSUMPTIONS = {
    "ES": 1.0,
    "NQ": 1.2,
    "ZN": 0.0,
    "ZB": 0.0,
    "GC": 0.0,
    "SI": 0.0,
    "CL": 0.0,
    "NG": 0.0,
    "ZC": 0.0,
    "ZS": 0.0,
    "6E": 0.0,
    "6J": 0.0,
    "6B": 0.0,
}


class FuturesTrendSleeve:
    """Actual-contract multi-asset trend service for a shared account."""

    def __init__(self, algorithm):
        self._algorithm = algorithm
        self._futures = {}
        self._prices = {root: deque(maxlen=253) for root in ROOT_CONSTANTS}
        self._returns = {root: deque(maxlen=252) for root in ROOT_CONSTANTS}
        self._contract_snapshots = {}
        self._contract_symbols = {}
        self._contract_snapshot_dates = {}
        self._pending = None
        self._last_weights = None
        self._last_signal_date = None
        self._current_contract = {}
        self._last_observed_week = None
        self._allowed_scale = 0.0
        self._applied_scale = 0.0
        self._proposed_gross = 0.70
        self._estimated_beta = 0.0
        self._signal_count = 0
        self._order_count = 0
        self._continuous_order_count = 0
        self._scale_violation_count = 0
        self._coverage = {
            root: {
                "history": False,
                "contract": False,
                "signal": False,
                "order": False,
            }
            for root in ROOT_CONSTANTS
        }
        for root, constant in ROOT_CONSTANTS.items():
            future = algorithm.add_future(
                constant,
                Resolution.DAILY,
                extended_market_hours=True,
                data_mapping_mode=DataMappingMode.OPEN_INTEREST,
                data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO,
                contract_depth_offset=0,
            )
            future.set_filter(0, 180)
            self._futures[root] = future

    def __getattr__(self, name):
        return getattr(self._algorithm, name)

    @property
    def data_cutoff(self):
        return self._last_signal_date

    def proposed_gross(self):
        return self._proposed_gross

    def estimated_beta(self):
        return self._estimated_beta

    def applied_scale(self):
        return self._applied_scale

    def set_scale(self, scale):
        if not 0 <= scale <= 1:
            raise ValueError("futures scale must be between zero and one")
        self._allowed_scale = scale
        if (
            scale < self._applied_scale - 1e-12
            and self._last_weights is not None
            and self._algorithm.can_trade_now()
        ):
            if not self._reduce_current_contracts(self._last_weights):
                self._scale_violation_count += 1

    def on_data(self, data: Slice):
        self._capture_chains(data)
        current_week = self.time.date().isocalendar()[:2]
        if (
            self._last_observed_week is not None
            and current_week != self._last_observed_week
        ):
            self._compute_weekly_targets()
            self._execute_pending_if_due()
        self._capture_completed_prices(data)
        self._last_observed_week = current_week

    def _capture_chains(self, data):
        for root, future in self._futures.items():
            chain = data.future_chains.get(future.symbol)
            if not chain:
                continue
            snapshots = []
            symbols = {}
            for contract in chain.contracts.values():
                snapshot = ContractSnapshot(
                    str(contract.symbol),
                    contract.expiry.date(),
                    float(contract.last_price),
                    int(contract.volume),
                    int(contract.open_interest),
                )
                snapshots.append(snapshot)
                symbols[snapshot.symbol] = contract.symbol
            if snapshots:
                try:
                    select_volume_contract(snapshots, self.time.date())
                except RollSelectionError:
                    # Minute slices can contain chain refreshes with zero volume.
                    # Preserve the last independently valid completed snapshot.
                    continue
                self._contract_snapshots[root] = snapshots
                self._contract_symbols[root] = symbols
                self._contract_snapshot_dates[root] = self.time.date()

    def _capture_completed_prices(self, data):
        for root, future in self._futures.items():
            bar = data.bars.get(future.symbol)
            if bar is None or bar.close <= 0:
                continue
            history = self._prices[root]
            if history and history[-1].as_of >= self.time.date():
                continue
            if history:
                self._returns[root].append(float(bar.close / history[-1].close - 1))
            history.append(DailyPrice(self.time.date(), float(bar.close)))
            self._coverage[root]["history"] = len(history) == 253

    def _compute_weekly_targets(self):
        if any(not self._prices[root] for root in ROOT_CONSTANTS):
            return
        signal_date = min(self._prices[root][-1].as_of for root in ROOT_CONSTANTS)
        scores = {}
        histories = {}
        for root in ROOT_CONSTANTS:
            try:
                signal = compute_trend_signal(
                    root,
                    list(self._prices[root]),
                    signal_date,
                )
            except TrendSignalError:
                return
            scores[root] = signal.score
            histories[root] = list(self._returns[root])
            self._coverage[root]["signal"] = True
        try:
            allocation = allocate_trend(scores, histories)
        except AllocationError:
            return
        self._pending = (signal_date, allocation.weights)
        self._last_signal_date = signal_date
        self._proposed_gross = allocation.gross_notional
        self._estimated_beta = sum(
            allocation.weights[root] * ROOT_BETA_ASSUMPTIONS[root]
            for root in ROOT_CONSTANTS
        )
        self._signal_count += 1

    def _execute_pending_if_due(self):
        if (
            self._pending is None
            or self.time.date() <= self._pending[0]
            or not self._algorithm.can_trade_now()
        ):
            return
        _, weights = self._pending
        if self._execute_weights(weights):
            self._last_weights = dict(weights)
            self._pending = None

    def _select_contracts(self):
        if not all(root in self._contract_snapshots for root in ROOT_CONSTANTS):
            return None
        selected = {}
        for root in ROOT_CONSTANTS:
            age = (self.time.date() - self._contract_snapshot_dates[root]).days
            if age > 7:
                return None
            snapshots = self._contract_snapshots[root]
            symbols = self._contract_symbols[root]
            try:
                choice = select_volume_contract(snapshots, self.time.date())
            except RollSelectionError:
                return None
            selected[root] = (symbols[choice.symbol], choice)
            self._coverage[root]["contract"] = True
        return selected

    def _reduce_current_contracts(self, weights):
        """Apply a risk cut to held actual contracts without opening or rolling."""
        equity = float(self.portfolio.total_portfolio_value)
        if equity <= 0:
            return False
        reductions = []
        for root, symbol in self._current_contract.items():
            current_quantity = int(self.portfolio[symbol].quantity)
            if current_quantity == 0:
                continue
            security = self.securities[symbol]
            price = float(security.price)
            multiplier = float(security.symbol_properties.contract_multiplier)
            if price <= 0 or multiplier <= 0:
                return False
            target_notional = weights[root] * self._allowed_scale * equity
            target_quantity = int(target_notional / (price * multiplier))
            if target_quantity * current_quantity <= 0:
                target_quantity = 0
            elif abs(target_quantity) > abs(current_quantity):
                target_quantity = current_quantity
            delta = target_quantity - current_quantity
            if delta:
                reductions.append((root, symbol, delta))
        for root, symbol, delta in reductions:
            self.market_order(symbol, delta, tag=f"trend:risk-reduction:{root}")
            self._order_count += 1
            self._coverage[root]["order"] = True
        self._applied_scale = self._allowed_scale
        return True

    def _execute_weights(self, weights):
        selected = self._select_contracts()
        if selected is None:
            return False
        for root, (symbol, snapshot) in selected.items():
            old = self._current_contract.get(root)
            if old is not None and old != symbol and self.portfolio[old].invested:
                self.liquidate(old, tag=f"trend:roll-out:{root}")
                self._order_count += 1
            multiplier = float(
                self.securities[symbol].symbol_properties.contract_multiplier
            )
            target_notional = weights[root] * self._allowed_scale * float(
                self.portfolio.total_portfolio_value
            )
            target_quantity = int(target_notional / (snapshot.price * multiplier))
            current_quantity = int(self.portfolio[symbol].quantity)
            delta = target_quantity - current_quantity
            if delta:
                self.market_order(symbol, delta, tag=f"trend:target:{root}")
                self._order_count += 1
                self._coverage[root]["order"] = True
            self._current_contract[root] = symbol
        self._applied_scale = self._allowed_scale
        return True

    def statistics(self):
        result = {
            "TREND_SIGNAL_COUNT": self._signal_count,
            "TREND_ORDER_COUNT": self._order_count,
            "CONTINUOUS_ORDER_COUNT": self._continuous_order_count,
            "TREND_SCALE_VIOLATION_COUNT": self._scale_violation_count,
            "TREND_VALID_SNAPSHOT_ROOTS": len(self._contract_snapshots),
            "TREND_PROPOSED_GROSS": f"{self._proposed_gross:.12f}",
            "TREND_ESTIMATED_BETA": f"{self._estimated_beta:.12f}",
        }
        for root, status in self._coverage.items():
            result[f"ROOT_{root}"] = ",".join(
                f"{key}={str(value).lower()}" for key, value in status.items()
            )
        return result
