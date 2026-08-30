from AlgorithmImports import *


class SpyPlusTenWalkForward(QCAlgorithm):
    """Cloud-only connectivity smoke test; not a formal strategy evaluation."""

    def initialize(self):
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 9)
        self.set_cash(1_000_000)
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

    def on_data(self, data: Slice):
        if not self.portfolio.invested and data.bars.contains_key(self.spy):
            self.set_holdings(self.spy, 1.0)
