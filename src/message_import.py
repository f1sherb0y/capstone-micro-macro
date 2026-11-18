from __future__ import annotations

from src.models import DiscussionMessage, SimulationState


def import_discussion_messages(state: SimulationState, messages: list[DiscussionMessage], start_index: int) -> int:
    id_map: dict[str, str] = {}
    next_index = start_index
    for message in messages:
        next_index += 1
        old_id = message.message_id
        message.message_id = f"msg_{next_index:06d}"
        id_map[old_id] = message.message_id
        message.response_to = [id_map.get(item, item) for item in message.response_to]
        state.agent_discussion_history.append(message)
    return next_index
