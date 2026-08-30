import json
import unittest
from datetime import datetime, timezone

from tests.project_path import PROJECT_DIR  # noqa: F401
from audit import AuditError, AuditEvent, AuditTrail


def moment(hour):
    return datetime(2015, 1, 5, hour, tzinfo=timezone.utc)


class AuditTrailTests(unittest.TestCase):
    def test_valid_event_serializes_deterministically(self):
        event = AuditEvent(
            sequence=1,
            module="benchmark",
            data_cutoff=moment(16),
            signal_time=moment(17),
            order_time=moment(18),
            fill_time=moment(19),
            inputs={"symbol": "SPY"},
            target={"weight": "1.0"},
            order={"quantity": "10"},
            risk={"live_trading": False},
        )
        trail = AuditTrail()
        trail.append(event)
        payload = json.loads(trail.to_jsonl())
        self.assertEqual(payload["sequence"], 1)
        self.assertEqual(payload["module"], "benchmark")

    def test_future_data_or_same_time_order_fails(self):
        event = AuditEvent(
            1,
            "benchmark",
            moment(17),
            moment(16),
            moment(16),
            moment(19),
            {},
            {},
            {},
            {},
        )
        with self.assertRaisesRegex(AuditError, "causal order"):
            AuditTrail().append(event)

    def test_sequence_and_time_cannot_move_backwards(self):
        first = AuditEvent(
            1,
            "benchmark",
            moment(15),
            moment(16),
            moment(17),
            moment(18),
            {},
            {},
            {},
            {},
        )
        second = AuditEvent(
            1,
            "benchmark",
            moment(16),
            moment(17),
            moment(18),
            moment(19),
            {},
            {},
            {},
            {},
        )
        trail = AuditTrail()
        trail.append(first)
        with self.assertRaisesRegex(AuditError, "sequence"):
            trail.append(second)

    def test_returned_events_cannot_mutate_serialized_history(self):
        trail = AuditTrail()
        event = AuditEvent(
            1,
            "benchmark",
            moment(15),
            moment(16),
            moment(17),
            moment(18),
            {"x": 1},
            {},
            {},
            {},
        )
        trail.append(event)
        self.assertIsInstance(trail.events, tuple)
        trail.events[0]["inputs"]["x"] = 99
        self.assertEqual(json.loads(trail.to_jsonl())["inputs"]["x"], 1)


if __name__ == "__main__":
    unittest.main()
