from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any, Dict

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment


@dataclass(frozen=True)
class AgentDecision:
    """Read-only result returned by one enterprise agent's own decision process."""

    action_type: str
    accepted: bool
    utility: float
    probability: float
    reason: str
    factors: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_event_data(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "accepted": self.accepted,
            "utility": round(self.utility, 4),
            "probability": round(self.probability, 4),
            "reason": self.reason,
            "decision_factors": self.factors,
            **self.data,
        }


class BaseEnterpriseAgent:
    def __init__(self, profile: EnterpriseAgentProfile, rng: random.Random | None = None) -> None:
        self.profile = profile
        self.rng = rng or random.Random()

    @property
    def agent_id(self) -> str:
        return self.profile.agent_id

    @property
    def role(self) -> str:
        return self.profile.role

    @staticmethod
    def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, value))

    def make_decision(
        self,
        action_type: str,
        *,
        utility: float,
        probability: float | None = None,
        accepted: bool | None = None,
        reason: str,
        factors: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
    ) -> AgentDecision:
        utility = self.clamp(utility)
        probability = self.clamp(probability if probability is not None else 0.10 + 0.80 * utility)
        if accepted is None:
            accepted = self.rng.random() <= probability
        return AgentDecision(
            action_type=action_type,
            accepted=bool(accepted),
            utility=utility,
            probability=probability,
            reason=reason,
            factors=factors or {},
            data=data or {},
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment) -> AgentDecision:
        return self.make_decision(
            "maintain_operations",
            utility=0.5,
            accepted=True,
            reason="Maintained normal enterprise operations while monitoring project opportunities.",
            data={
                "label": "Maintained operations",
                "description": "Maintained enterprise operations and watched for suitable GBA collaboration opportunities.",
            },
        )

    def stable_pick(self, tick: int, catalog: list[tuple[str, str, str]]) -> tuple[str, str, str]:
        seed = sum(ord(char) for char in self.agent_id) + tick * 19
        return catalog[seed % max(len(catalog), 1)]
