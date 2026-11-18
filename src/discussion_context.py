from __future__ import annotations

from src.models import DiscussionMessage


def public_discussion_line(message: DiscussionMessage) -> str:
    return (
        f"{message.agent_name} ({message.position}, {message.company_id}, {message.round_type}) "
        f"said: {message.content} Recommendation: {message.recommendation}. "
        f"Decision impact: {message.decision_impact}."
    )


def recent_discussion_context(messages: list[DiscussionMessage], limit: int = 6) -> str:
    if not messages:
        return "No earlier messages in this discussion."
    lines = []
    for message in messages[-limit:]:
        lines.append(f"- {message.message_id} | {public_discussion_line(message)}")
    return "\n".join(lines)
