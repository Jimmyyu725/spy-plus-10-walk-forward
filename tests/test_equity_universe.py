import unittest
from datetime import date, timedelta

from tests.project_path import PROJECT_DIR  # noqa: F401
from universe import (
    DollarVolumePoint,
    FundamentalSnapshot,
    UniverseSelectionError,
    select_equity_candidates,
)


CUTOFF = date(2014, 12, 31)
SELECTION_TIME = date(2015, 1, 2)


def snapshot(symbol, *, price=10, roe=0.2, gross_profit=20, total_assets=100):
    return FundamentalSnapshot(
        symbol=symbol,
        as_of=CUTOFF,
        price=price,
        has_fundamental_data=True,
        roe=roe,
        gross_profit=gross_profit,
        total_assets=total_assets,
    )


def dollar_history(symbol, value=1_000_000, count=20):
    start = CUTOFF - timedelta(days=count - 1)
    return [
        DollarVolumePoint(symbol, start + timedelta(days=i), value + i)
        for i in range(count)
    ]


class EquityUniverseTests(unittest.TestCase):
    def test_filters_and_ranks_by_twenty_day_average(self):
        snapshots = [
            snapshot("HIGH"),
            snapshot("LOW"),
            snapshot("PENNY", price=4.99),
            snapshot("MISSING", roe=None),
            snapshot("BADASSET", total_assets=0),
        ]
        histories = {
            item.symbol: dollar_history(
                item.symbol,
                2_000_000 if item.symbol == "HIGH" else 1_000_000,
            )
            for item in snapshots
        }
        selected = select_equity_candidates(
            snapshots,
            histories,
            cutoff=CUTOFF,
            selection_time=SELECTION_TIME,
            top_n=500,
        )
        self.assertEqual([item.symbol for item in selected], ["HIGH", "LOW"])
        self.assertAlmostEqual(selected[0].gross_profit_to_assets, 0.2)

    def test_requires_full_completed_liquidity_window(self):
        selected = select_equity_candidates(
            [snapshot("SHORT")],
            {"SHORT": dollar_history("SHORT", count=19)},
            cutoff=CUTOFF,
            selection_time=SELECTION_TIME,
        )
        self.assertEqual(selected, ())

    def test_duplicate_dates_fail_closed(self):
        history = dollar_history("DUP")
        history[-1] = DollarVolumePoint("DUP", history[-2].as_of, 1_000_000)
        with self.assertRaisesRegex(UniverseSelectionError, "strictly increasing"):
            select_equity_candidates(
                [snapshot("DUP")],
                {"DUP": history},
                cutoff=CUTOFF,
                selection_time=SELECTION_TIME,
            )

    def test_selection_must_follow_cutoff(self):
        with self.assertRaisesRegex(UniverseSelectionError, "after cutoff"):
            select_equity_candidates(
                [snapshot("EARLY")],
                {"EARLY": dollar_history("EARLY")},
                cutoff=CUTOFF,
                selection_time=CUTOFF,
            )

    def test_top_n_and_symbol_tie_break_are_deterministic(self):
        snapshots = [snapshot(f"S{i:03d}") for i in range(503)]
        histories = {
            item.symbol: dollar_history(item.symbol, 1_000_000)
            for item in snapshots
        }
        selected = select_equity_candidates(
            snapshots,
            histories,
            cutoff=CUTOFF,
            selection_time=SELECTION_TIME,
            top_n=500,
        )
        self.assertEqual(len(selected), 500)
        self.assertEqual(selected[0].symbol, "S000")
        self.assertEqual(selected[-1].symbol, "S499")

    def test_future_append_cannot_change_past_selection(self):
        history = dollar_history("SAFE")
        before = select_equity_candidates(
            [snapshot("SAFE")],
            {"SAFE": history},
            cutoff=CUTOFF,
            selection_time=SELECTION_TIME,
        )
        history.append(DollarVolumePoint("SAFE", date(2030, 1, 1), 1))
        after = select_equity_candidates(
            [snapshot("SAFE")],
            {"SAFE": history},
            cutoff=CUTOFF,
            selection_time=SELECTION_TIME,
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
