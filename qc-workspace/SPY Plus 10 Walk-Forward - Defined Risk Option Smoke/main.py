from AlgorithmImports import *
from datetime import timedelta
from math import ceil, floor, isfinite

from option_chain import (
    OptionChainError,
    OptionContractSnapshot,
    select_bull_put_spread,
)
from option_lifecycle import (
    ExitQuote,
    OptionLifecycleError,
    SpreadPosition,
    can_open_new_spread,
    decide_exit,
    validate_decision_timeline,
)
from option_risk import (
    OptionRiskError,
    RealizedOptionLoss,
    size_defined_risk_spread,
)
from signals.option_signal import (
    AtmIvObservation,
    DailyClose,
    OptionSignalError,
    compute_option_regime,
)


class PerLegOptionFeeModel(FeeModel):
    def get_order_fee(self, parameters):
        fee = max(abs(parameters.order.quantity) * 0.65, 1.0)
        return OrderFee(CashAmount(fee, "USD"))


class SPYPlus10WalkForwardDefinedRiskOptionSmoke(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2012, 1, 1)
        self.set_end_date(2015, 3, 31)
        self.set_cash(1_000_000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_brokerage_model(BrokerageName.QUANTCONNECT_BROKERAGE)
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.set_security_initializer(self._initialize_security)

        self._spy = self.add_equity(
            "SPY",
            Resolution.MINUTE,
            data_normalization_mode=DataNormalizationMode.RAW,
        ).symbol
        option = self.add_option("SPY", Resolution.MINUTE)
        option.price_model = OptionPriceModels.binomial_cox_ross_rubinstein()
        option.set_filter(
            lambda universe: universe.include_weeklys()
            .puts_only()
            .strikes(-30, 0)
            .expiration(30, 60)
        )
        self._option = option.symbol

        self.schedule.on(
            self.date_rules.week_start(self._spy),
            self.time_rules.after_market_close(self._spy, 1),
            self._evaluate_weekly_signal,
        )
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.after_market_open(self._spy, 30),
            self._try_entry,
        )
        self.schedule.on(
            self.date_rules.every_day(self._spy),
            self.time_rules.before_market_close(self._spy, 5),
            self._cancel_stale_combo,
        )

        self._latest_chain = None
        self._latest_chain_time = None
        self._latest_underlying_price = 0.0
        self._contract_symbols = {}
        self._pending_signal = None
        self._pending_combo = None
        self._position = None
        self._realized_losses = []
        self._statistics = {
            "OPTION_CHAIN_OBSERVATIONS": 0,
            "OPTION_ELIGIBLE_SIGNALS": 0,
            "OPTION_SPREADS_OPENED": 0,
            "OPTION_SPREADS_CLOSED": 0,
            "OPTION_NAKED_LEG_COUNT": 0,
            "OPTION_MAX_LOSS_BREACH_COUNT": 0,
            "OPTION_FUTURE_INPUT_COUNT": 0,
            "OPTION_REJECT_NO_CHAIN": 0,
            "OPTION_REJECT_REGIME": 0,
            "OPTION_REJECT_LIQUIDITY": 0,
            "OPTION_REJECT_RISK": 0,
            "OPTION_COMBO_REJECTED": 0,
            "OPTION_ASSIGNMENT_EVENTS": 0,
        }
        self._license_status = "UNVERIFIED"

    def _initialize_security(self, security):
        if security.type == SecurityType.OPTION:
            security.set_fee_model(PerLegOptionFeeModel())

    def on_data(self, data: Slice):
        chain = data.option_chains.get(self._option)
        if chain:
            self._latest_chain = chain
            self._latest_chain_time = self.time
            self._latest_underlying_price = float(chain.underlying.price)
        if self._position is not None and self._pending_combo is None:
            self._evaluate_exit()

    @staticmethod
    def _is_put(contract):
        return str(contract.right).upper().endswith("PUT")

    def _iv_observations(self, cutoff):
        if self._latest_chain is None:
            return []
        observations = []
        for contract in self._latest_chain.contracts.values():
            if not self._is_put(contract):
                continue
            implied_volatility = float(contract.implied_volatility)
            if not isfinite(implied_volatility) or implied_volatility <= 0:
                continue
            observations.append(
                AtmIvObservation(
                    cutoff,
                    contract.expiry.date(),
                    float(contract.strike),
                    self._latest_underlying_price,
                    implied_volatility,
                    int(contract.open_interest),
                )
            )
        return observations

    def _evaluate_weekly_signal(self):
        if not can_open_new_spread(self._position) or self._pending_combo is not None:
            return
        if self._latest_chain is None:
            self._statistics["OPTION_REJECT_NO_CHAIN"] += 1
            return
        bars = list(self.history[TradeBar](self._spy, 200, Resolution.DAILY))
        if len(bars) < 200:
            self._statistics["OPTION_REJECT_REGIME"] += 1
            return
        prices = [DailyClose(bar.end_time.date(), float(bar.close)) for bar in bars]
        cutoff = prices[-1].as_of
        data_cutoff_time = bars[-1].end_time
        observations = self._iv_observations(cutoff)
        self._statistics["OPTION_CHAIN_OBSERVATIONS"] += 1
        if observations:
            self._license_status = "AVAILABLE"
        try:
            signal = compute_option_regime(
                prices,
                observations,
                cutoff=cutoff,
                data_cutoff_time=data_cutoff_time,
                signal_time=self.time,
            )
        except OptionSignalError as error:
            self.debug(f"option regime rejected: {error}")
            self._statistics["OPTION_REJECT_REGIME"] += 1
            return
        if not signal.eligible:
            self._statistics["OPTION_REJECT_REGIME"] += 1
            return
        self._pending_signal = (signal, data_cutoff_time)
        self._statistics["OPTION_ELIGIBLE_SIGNALS"] += 1

    def _snapshot_chain(self, entry_time):
        if self._latest_chain is None or self._latest_chain_time is None:
            return []
        snapshots = []
        for contract in self._latest_chain.contracts.values():
            if not self._is_put(contract):
                continue
            if self._latest_chain_time > entry_time:
                self._statistics["OPTION_FUTURE_INPUT_COUNT"] += 1
                continue
            symbol_key = str(contract.symbol)
            self._contract_symbols[symbol_key] = contract.symbol
            properties = self.securities[contract.symbol].symbol_properties
            snapshots.append(
                OptionContractSnapshot(
                    symbol_key,
                    self._latest_chain_time,
                    contract.expiry.date(),
                    float(contract.strike),
                    "PUT",
                    float(contract.bid_price),
                    float(contract.ask_price),
                    int(contract.volume),
                    int(contract.open_interest),
                    float(contract.greeks.delta),
                    float(contract.implied_volatility),
                    int(float(properties.contract_multiplier)),
                    float(properties.minimum_price_variation),
                )
            )
        return snapshots

    def _try_entry(self):
        if (
            self._pending_signal is None
            or self._pending_combo is not None
            or not can_open_new_spread(self._position)
        ):
            return
        signal, data_cutoff_time = self._pending_signal
        if self.time.date() <= signal.signal_time.date():
            return
        try:
            validate_decision_timeline(data_cutoff_time, signal.signal_time, self.time)
        except OptionLifecycleError:
            self._statistics["OPTION_FUTURE_INPUT_COUNT"] += 1
            self._pending_signal = None
            return
        snapshots = self._snapshot_chain(self.time)
        self._statistics["OPTION_CHAIN_OBSERVATIONS"] += 1
        try:
            selection = select_bull_put_spread(
                snapshots,
                entry_time=self.time,
                underlying_price=self._latest_underlying_price,
            )
        except OptionChainError as error:
            self.debug(f"option chain rejected: {error}")
            self._statistics["OPTION_REJECT_LIQUIDITY"] += 1
            self._pending_signal = None
            return
        try:
            sizing = size_defined_risk_spread(
                selection,
                equity=float(self.portfolio.total_portfolio_value),
                as_of=self.time,
                realized_losses=self._realized_losses,
                per_contract_annual_pnl_volatility=selection.width * 100,
            )
        except OptionRiskError as error:
            self.debug(f"option risk rejected: {error}")
            self._statistics["OPTION_REJECT_RISK"] += 1
            self._pending_signal = None
            return
        if sizing.total_max_loss > sizing.available_risk_budget + 1e-9:
            self._statistics["OPTION_MAX_LOSS_BREACH_COUNT"] += 1
            self._pending_signal = None
            return
        short_symbol = self._contract_symbols[selection.short_put.symbol]
        long_symbol = self._contract_symbols[selection.long_put.symbol]
        legs = [
            Leg.create(short_symbol, -1, sizing.short_fill),
            Leg.create(long_symbol, 1, sizing.long_fill),
        ]
        tickets = self.combo_leg_limit_order(
            legs,
            sizing.contracts,
            tag="defined-risk-entry",
        )
        self._pending_combo = {
            "kind": "ENTRY",
            "tickets": tickets,
            "selection": selection,
            "sizing": sizing,
            "submitted": self.time,
        }
        self._pending_signal = None
        self._reconcile_combo()

    @staticmethod
    def _leg_fee(contracts):
        return max(abs(contracts) * 0.65, 1.0)

    def _reconcile_combo(self):
        if self._pending_combo is None:
            return
        tickets = self._pending_combo["tickets"]
        statuses = [ticket.status for ticket in tickets]
        failed = {
            OrderStatus.CANCELED,
            OrderStatus.INVALID,
        }
        if any(status in failed for status in statuses):
            filled = [ticket for ticket in tickets if ticket.quantity_filled != 0]
            if filled and len(filled) != len(tickets):
                self._statistics["OPTION_NAKED_LEG_COUNT"] += 1
            self._statistics["OPTION_COMBO_REJECTED"] += 1
            self._pending_combo = None
            return
        if not all(status == OrderStatus.FILLED for status in statuses):
            return
        pending = self._pending_combo
        if pending["kind"] == "ENTRY":
            selection = pending["selection"]
            sizing = pending["sizing"]
            by_symbol = {str(ticket.symbol): ticket for ticket in tickets}
            short_fill = abs(
                float(by_symbol[selection.short_put.symbol].average_fill_price)
            )
            long_fill = abs(
                float(by_symbol[selection.long_put.symbol].average_fill_price)
            )
            actual_credit = short_fill - long_fill
            if actual_credit <= 0:
                actual_credit = sizing.credit_per_share
            self._position = SpreadPosition(
                selection.short_put.symbol,
                selection.long_put.symbol,
                pending["submitted"],
                selection.short_put.expiry,
                selection.short_put.strike,
                selection.long_put.strike,
                actual_credit,
                sizing.contracts,
                selection.short_put.multiplier,
                sizing.entry_fees,
                "OPEN",
            )
            self._statistics["OPTION_SPREADS_OPENED"] += 1
        else:
            position = self._position
            decision = pending["decision"]
            exit_fees = 2 * self._leg_fee(position.contracts)
            pnl = (
                (position.entry_credit - decision.exit_debit)
                * position.multiplier
                * position.contracts
                - position.entry_fees
                - exit_fees
            )
            if pnl < 0:
                self._realized_losses.append(
                    RealizedOptionLoss(self.time.date(), -pnl)
                )
            self._position = None
            self._statistics["OPTION_SPREADS_CLOSED"] += 1
        self._pending_combo = None

    def on_order_event(self, order_event):
        self._reconcile_combo()

    def on_assignment_order_event(self, assignment_event):
        self._statistics["OPTION_ASSIGNMENT_EVENTS"] += 1

    @staticmethod
    def _round_up(value, tick):
        return ceil((value - 1e-12) / tick) * tick

    @staticmethod
    def _round_down(value, tick):
        return floor((value + 1e-12) / tick) * tick

    def _evaluate_exit(self):
        if self._latest_chain is None or self._position is None:
            return
        short_symbol = self._contract_symbols.get(self._position.short_symbol)
        long_symbol = self._contract_symbols.get(self._position.long_symbol)
        if short_symbol is None or long_symbol is None:
            return
        short_contract = self._latest_chain.contracts.get(short_symbol)
        long_contract = self._latest_chain.contracts.get(long_symbol)
        if short_contract is None or long_contract is None:
            return
        properties = self.securities[short_symbol].symbol_properties
        tick = float(properties.minimum_price_variation)
        quote = ExitQuote(
            self.time,
            float(short_contract.bid_price),
            float(short_contract.ask_price),
            float(long_contract.bid_price),
            float(long_contract.ask_price),
            tick,
        )
        try:
            decision = decide_exit(self._position, quote)
        except OptionLifecycleError:
            return
        if decision.action == "HOLD":
            return
        short_mid = (quote.short_bid + quote.short_ask) / 2
        long_mid = (quote.long_bid + quote.long_ask) / 2
        short_limit = self._round_up(
            short_mid + (quote.short_ask - quote.short_bid) * 0.25,
            tick,
        )
        long_limit = self._round_down(
            long_mid - (quote.long_ask - quote.long_bid) * 0.25,
            tick,
        )
        tickets = self.combo_leg_limit_order(
            [
                Leg.create(short_symbol, 1, short_limit),
                Leg.create(long_symbol, -1, long_limit),
            ],
            self._position.contracts,
            tag=f"defined-risk-exit:{decision.action}",
        )
        self._pending_combo = {
            "kind": "EXIT",
            "tickets": tickets,
            "decision": decision,
            "submitted": self.time,
        }
        self._reconcile_combo()

    def _cancel_stale_combo(self):
        if self._pending_combo is None:
            return
        for ticket in self._pending_combo["tickets"]:
            if ticket.status not in {OrderStatus.FILLED, OrderStatus.CANCELED}:
                ticket.cancel("stale defined-risk combo")
        self._reconcile_combo()

    def on_end_of_algorithm(self):
        self._reconcile_combo()
        option_holdings = [
            holding
            for holding in self.portfolio.values()
            if holding.type == SecurityType.OPTION and holding.quantity != 0
        ]
        if len(option_holdings) not in {0, 2}:
            self._statistics["OPTION_NAKED_LEG_COUNT"] += 1
        trailing_loss = sum(
            item.loss
            for item in self._realized_losses
            if self.time.date() - timedelta(days=365) <= item.realized_at <= self.time.date()
        )
        statistics = dict(self._statistics)
        statistics.update(
            {
                "OPTION_LICENSE_STATUS": self._license_status,
                "OPTION_COST_MODEL_STATUS": "PER_LEG_ADVERSE_LIMITS_AND_FEES",
                "OPTION_TRAILING_REALIZED_LOSS": f"{trailing_loss:.2f}",
                "OPTION_OPEN_POSITION_AT_END": str(self._position is not None).lower(),
            }
        )
        for key, value in statistics.items():
            self.set_summary_statistic(key, str(value))
