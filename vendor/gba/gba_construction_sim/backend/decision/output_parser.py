import json
import re
from typing import Any, Union

from pydantic import ValidationError

from gba_construction_sim.backend.models.action import AgentAction


class DecisionOutputParser:
    def parse(self, raw: Union[str, dict[str, Any], AgentAction]) -> AgentAction:
        if isinstance(raw, AgentAction):
            return raw
        payload = self._loads(raw) if isinstance(raw, str) else raw
        try:
            if hasattr(AgentAction, "model_validate"):
                return AgentAction.model_validate(payload)
            return AgentAction.parse_obj(payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid decision output: {exc}") from exc

    def _loads(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Decision output must be a JSON object")
        return payload
