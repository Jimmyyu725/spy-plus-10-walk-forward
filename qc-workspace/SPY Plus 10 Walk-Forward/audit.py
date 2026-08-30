from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime


class AuditError(RuntimeError):
    """Raised when an audit event violates ordering or immutability rules."""


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    module: str
    data_cutoff: datetime
    signal_time: datetime
    order_time: datetime
    fill_time: datetime
    inputs: dict
    target: dict
    order: dict
    risk: dict


class AuditTrail:
    def __init__(self):
        self._lines: list[str] = []
        self._last_sequence = 0
        self._last_fill_time: datetime | None = None

    @property
    def events(self) -> tuple[dict, ...]:
        return tuple(json.loads(line) for line in self._lines)

    def append(self, event: AuditEvent) -> None:
        if event.sequence <= 0 or not event.module:
            raise AuditError("invalid event identity")
        if not (
            event.data_cutoff
            < event.signal_time
            < event.order_time
            < event.fill_time
        ):
            raise AuditError("event violates causal order")
        if any(
            value.tzinfo is None
            for value in (
                event.data_cutoff,
                event.signal_time,
                event.order_time,
                event.fill_time,
            )
        ):
            raise AuditError("timestamps must be timezone-aware")
        if event.sequence != self._last_sequence + 1:
            raise AuditError("event sequence must increase by one")
        if self._last_fill_time is not None and event.fill_time < self._last_fill_time:
            raise AuditError("event time moved backwards")
        payload = asdict(event)
        for field in ("data_cutoff", "signal_time", "order_time", "fill_time"):
            payload[field] = payload[field].isoformat()
        try:
            line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise AuditError("event payload is not JSON serializable") from exc
        self._lines.append(line)
        self._last_sequence = event.sequence
        self._last_fill_time = event.fill_time

    def to_jsonl(self) -> str:
        return "\n".join(self._lines) + ("\n" if self._lines else "")
