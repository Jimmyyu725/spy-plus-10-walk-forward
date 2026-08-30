import unittest
from datetime import date

from tests.project_path import PROJECT_DIR  # noqa: F401
from futures_roll import ContractSnapshot, RollSelectionError, select_volume_contract


class FuturesRollTests(unittest.TestCase):
    def test_highest_volume_valid_contract_wins(self):
        contracts = [
            ContractSnapshot("ESH15", date(2015, 3, 20), 100, 200, 2000),
            ContractSnapshot("ESM15", date(2015, 6, 19), 101, 500, 1000),
        ]
        self.assertEqual(
            select_volume_contract(contracts, date(2015, 1, 5)).symbol,
            "ESM15",
        )

    def test_expiry_buffer_excludes_near_contract(self):
        contracts = [
            ContractSnapshot("ESH15", date(2015, 1, 10), 100, 1000, 2000),
            ContractSnapshot("ESM15", date(2015, 3, 20), 101, 100, 1000),
        ]
        self.assertEqual(
            select_volume_contract(contracts, date(2015, 1, 5)).symbol,
            "ESM15",
        )

    def test_ties_use_open_interest_then_expiry(self):
        contracts = [
            ContractSnapshot("ESM15", date(2015, 6, 19), 101, 500, 1000),
            ContractSnapshot("ESH15", date(2015, 3, 20), 100, 500, 2000),
        ]
        self.assertEqual(
            select_volume_contract(contracts, date(2015, 1, 5)).symbol,
            "ESH15",
        )

    def test_missing_valid_contract_fails_closed(self):
        with self.assertRaisesRegex(RollSelectionError, "no valid"):
            select_volume_contract([], date(2015, 1, 5))


if __name__ == "__main__":
    unittest.main()
