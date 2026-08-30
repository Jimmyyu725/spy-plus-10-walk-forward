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


class PerContractFeeModel(FeeModel):
    def get_order_fee(self, parameters):
        fee = abs(parameters.order.quantity) * 2.50
        return OrderFee(CashAmount(fee, "USD"))


class OneTickSlippageModel(SlippageModel):
    def get_slippage_approximation(self, asset, order):
        return asset.symbol_properties.minimum_price_variation


class FuturesTrendSmokeAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2012, 1, 1)
        self.set_end_date(2015, 3, 31)
        self.set_cash(1_000_000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_security_initializer(self._initialize_security)

        self._futures = {}
        self._prices = {root: deque(maxlen=253) for root in ROOT_CONSTANTS}
        self._returns = {root: deque(maxlen=252) for root in ROOT_CONSTANTS}
        self._chains = {}
        self._pending = None
        self._current_contract = {}
        self._last_observed_week = None
        self._signal_count = 0
        self._order_count = 0
        self._continuous_order_count = 0
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
            future = self.add_future(
                constant,
                Resolution.DAILY,
                extended_market_hours=True,
                data_mapping_mode=DataMappingMode.OPEN_INTEREST,
                data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO,
                contract_depth_offset=0,
            )
            future.set_filter(0, 180)
            self._futures[root] = future

    def _initialize_security(self, security):
        if security.type == SecurityType.FUTURE:
            security.set_fee_model(PerContractFeeModel())
            security.set_slippage_model(OneTickSlippageModel())

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
            if chain:
                self._chains[root] = chain

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
        self._signal_count += 1

    def _execute_pending_if_due(self):
        if self._pending is None or self.time.date() <= self._pending[0]:
            return
        if not all(root in self._chains for root in ROOT_CONSTANTS):
            return
        _, weights = self._pending
        selected = {}
        for root, chain in self._chains.items():
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
            try:
                choice = select_volume_contract(snapshots, self.time.date())
            except RollSelectionError:
                return
            selected[root] = (symbols[choice.symbol], choice)
            self._coverage[root]["contract"] = True
        for root, (symbol, snapshot) in selected.items():
            old = self._current_contract.get(root)
            if old is not None and old != symbol and self.portfolio[old].invested:
                self.liquidate(old, tag=f"roll-out:{root}")
                self._order_count += 1
            multiplier = float(
                self.securities[symbol].symbol_properties.contract_multiplier
            )
            target_notional = weights[root] * float(
                self.portfolio.total_portfolio_value
            )
            target_quantity = int(target_notional / (snapshot.price * multiplier))
            current_quantity = int(self.portfolio[symbol].quantity)
            delta = target_quantity - current_quantity
            if delta:
                self.market_order(symbol, delta, tag=f"trend:{root}")
                self._order_count += 1
                self._coverage[root]["order"] = True
            self._current_contract[root] = symbol
        self._pending = None

    def on_end_of_algorithm(self):
        self.set_summary_statistic("TREND_SIGNAL_COUNT", str(self._signal_count))
        self.set_summary_statistic("TREND_ORDER_COUNT", str(self._order_count))
        self.set_summary_statistic(
            "CONTINUOUS_ORDER_COUNT",
            str(self._continuous_order_count),
        )
        for root, status in self._coverage.items():
            encoded = ",".join(
                f"{key}={str(value).lower()}" for key, value in status.items()
            )
            self.set_summary_statistic(f"ROOT_{root}", encoded)
