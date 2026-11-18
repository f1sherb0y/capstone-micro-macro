from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from gba_construction_sim.backend.simulation.decision_request import InteractionMessage
from gba_construction_sim.backend.simulation.message_bus import BusEnvelope, SimulationMessageBus, simulation_message_bus


@dataclass
class InteractionSession:
    session_id: str
    project_id: str
    session_type: str
    participants: list[str]
    max_rounds: int = 3
    messages: list[InteractionMessage] = field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def append(self, message: InteractionMessage) -> None:
        self.messages.append(message)
        if len(self.messages) > self.max_rounds * max(1, len(self.participants)):
            self.messages = self.messages[-self.max_rounds * max(1, len(self.participants)) :]

    def recent_messages(self, limit: int = 4) -> list[InteractionMessage]:
        return self.messages[-max(0, limit) :]

    def compact_summary(self) -> str:
        if self.summary:
            return self.summary
        snippets = []
        for message in self.recent_messages(limit=3):
            recipients = ",".join(message.recipient_ids)
            snippets.append(f"{message.sender_id}->{recipients}: {message.content}")
        return " | ".join(snippets)

    def to_event_data(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "participants": self.participants,
            "max_rounds": self.max_rounds,
            "summary": self.compact_summary(),
            "recent_messages": [
                {
                    "message_id": message.message_id,
                    "sender_id": message.sender_id,
                    "recipient_ids": message.recipient_ids,
                    "topic": message.topic,
                    "content": message.content,
                    "metadata": message.metadata,
                }
                for message in self.recent_messages()
            ],
            "metadata": self.metadata,
        }


class InteractionSessionManager:
    """Bounded project interaction sessions backed by the central message bus."""

    def __init__(self, message_bus: SimulationMessageBus | None = None) -> None:
        self.message_bus = message_bus or simulation_message_bus
        self._lock = RLock()
        self._sessions: dict[str, InteractionSession] = {}

    def get_or_create(
        self,
        project_id: str,
        session_type: str,
        participants: list[str],
        *,
        max_rounds: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> InteractionSession:
        session_id = f"{project_id}:{session_type}"
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                for participant in participants:
                    if participant and participant not in session.participants:
                        session.participants.append(participant)
                if metadata:
                    session.metadata.update(metadata)
                return session
            session = InteractionSession(
                session_id=session_id,
                project_id=project_id,
                session_type=session_type,
                participants=[participant for participant in participants if participant],
                max_rounds=max_rounds,
                metadata=metadata or {},
            )
            self._sessions[session_id] = session
            return session

    def append_message(
        self,
        session: InteractionSession,
        *,
        tick: int,
        sender_id: str,
        recipient_ids: list[str],
        topic: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> InteractionMessage:
        with self._lock:
            message = InteractionMessage(
                message_id=f"{session.session_id}:M{len(session.messages) + 1:03d}",
                tick=tick,
                sender_id=sender_id,
                recipient_ids=[recipient_id for recipient_id in recipient_ids if recipient_id],
                session_id=session.session_id,
                topic=topic,
                content=content,
                metadata=metadata or {},
            )
            session.append(message)
            session.summary = self._summarize(session)
            self.message_bus.publish(
                BusEnvelope(
                    message_type="InteractionMessage",
                    topic=f"project:{session.project_id}",
                    payload=message,
                    tick=tick,
                    project_id=session.project_id,
                    session_id=session.session_id,
                    metadata={
                        "session_type": session.session_type,
                        "sender_id": sender_id,
                        "recipient_ids": message.recipient_ids,
                    },
                )
            )
            return message

    def by_project(self, project_id: str) -> list[InteractionSession]:
        with self._lock:
            return [session for session in self._sessions.values() if session.project_id == project_id]

    @staticmethod
    def _summarize(session: InteractionSession) -> str:
        messages = session.recent_messages(limit=4)
        if not messages:
            return ""
        parts = []
        for message in messages:
            recipients = ",".join(message.recipient_ids)
            parts.append(f"{message.sender_id} to {recipients}: {message.content}")
        return " / ".join(parts)
