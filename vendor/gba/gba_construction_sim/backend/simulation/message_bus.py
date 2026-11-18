from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Deque, Optional


@dataclass
class BusEnvelope:
    message_type: str
    topic: str
    payload: Any
    tick: int
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SimulationMessageBus:
    def __init__(self) -> None:
        self._lock = RLock()
        self._queues: dict[str, Deque[BusEnvelope]] = defaultdict(deque)
        self._log: list[BusEnvelope] = []

    def publish(self, envelope: BusEnvelope) -> None:
        with self._lock:
            self._queues[envelope.topic].append(envelope)
            self._log.append(envelope)

    def drain(
        self,
        topic: str,
        *,
        message_type: Optional[str] = None,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[BusEnvelope]:
        with self._lock:
            retained: Deque[BusEnvelope] = deque()
            drained: list[BusEnvelope] = []
            while self._queues[topic]:
                envelope = self._queues[topic].popleft()
                if self._matches(envelope, message_type, project_id, session_id) and (
                    limit is None or len(drained) < limit
                ):
                    drained.append(envelope)
                else:
                    retained.append(envelope)
            self._queues[topic] = retained
            return drained

    def peek(self, topic: Optional[str] = None) -> list[BusEnvelope]:
        with self._lock:
            if topic is None:
                return list(self._log)
            return list(self._queues[topic])

    @staticmethod
    def _matches(
        envelope: BusEnvelope,
        message_type: Optional[str],
        project_id: Optional[str],
        session_id: Optional[str],
    ) -> bool:
        if message_type and envelope.message_type != message_type:
            return False
        if project_id and envelope.project_id != project_id:
            return False
        if session_id and envelope.session_id != session_id:
            return False
        return True


simulation_message_bus = SimulationMessageBus()
