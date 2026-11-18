from __future__ import annotations

from typing import Any
from src.verification import require_verification_requests


AGENT_MESSAGE_FIELDS = ["thoughts", "content", "recommendation", "decision_impact"]


def require_agent_message(data: dict[str, Any]) -> None:
    for field in AGENT_MESSAGE_FIELDS:
        if field not in data:
            raise KeyError(f"AGENT_MESSAGE missing field: {field}")
    require_verification_requests(data)
