import unittest
from datetime import datetime, timedelta, timezone

from tests.project_path import PROJECT_DIR  # noqa: F401
from option_lifecycle import (
    ExitQuote,
    OptionLifecycleError,
    SpreadPosition,
    can_open_new_spread,
    decide_exit,
    validate_decision_timeline,
)


ENTRY = datetime(2015, 1, 6, 10, 0)


def position(expiry_days=45, status="OPEN"):
    return SpreadPosition(
        "SHORT", "LONG", ENTRY, ENTRY.date() + timedelta(days=expiry_days),
        100, 95, 1.10, 1, 100, 2.0, status,
    )


class OptionLifecycleTests(unittest.TestCase):
    def test_profit_take_at_half_entry_credit(self):
        quote = ExitQuote(
            ENTRY + timedelta(days=5), 0.70, 0.80, 0.30, 0.40, 0.01
        )
        decision = decide_exit(position(), quote)
        self.assertEqual(decision.action, "TAKE_PROFIT")
        self.assertLessEqual(decision.exit_debit, 0.55)

    def test_time_exit_at_twenty_one_dte(self):
        current = ENTRY + timedelta(days=24)
        quote = ExitQuote(current, 1.3, 1.4, 0.4, 0.5, 0.01)
        self.assertEqual(decide_exit(position(), quote).action, "TIME_EXIT")

    def test_hold_before_exit_conditions(self):
        quote = ExitQuote(
            ENTRY + timedelta(days=5), 1.3, 1.4, 0.4, 0.5, 0.01
        )
        self.assertEqual(decide_exit(position(), quote).action, "HOLD")

    def test_open_position_blocks_overlap(self):
        self.assertFalse(can_open_new_spread(position()))
        self.assertTrue(can_open_new_spread(position(status="CLOSED")))
        self.assertTrue(can_open_new_spread(None))

    def test_timeline_is_strictly_ordered(self):
        cutoff = ENTRY - timedelta(days=1)
        signal = ENTRY - timedelta(hours=12)
        validate_decision_timeline(cutoff, signal, ENTRY)
        with self.assertRaisesRegex(OptionLifecycleError, "strictly"):
            validate_decision_timeline(cutoff, ENTRY, ENTRY)

    def test_naked_or_reversed_position_is_rejected(self):
        with self.assertRaisesRegex(OptionLifecycleError, "protection"):
            SpreadPosition(
                "SHORT", "LONG", ENTRY, ENTRY.date() + timedelta(days=45),
                95, 100, 1.0, 1, 100, 2.0, "OPEN",
            )

    def test_strict_aware_timeline_is_accepted_for_formal_audit(self):
        cutoff = datetime(2015, 1, 5, 21, tzinfo=timezone.utc)
        signal = cutoff + timedelta(minutes=1)
        order = signal + timedelta(hours=17)
        validate_decision_timeline(cutoff, signal, order)


if __name__ == "__main__":
    unittest.main()
