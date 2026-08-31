from AlgorithmImports import *


class SpyPlusTenV2EvidenceCapability(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 5)
        self.set_cash(1_000_000)
        self._git_commit = self.get_parameter("v2_git_commit")
        self._run_label = self.get_parameter("evidence_run_label")
