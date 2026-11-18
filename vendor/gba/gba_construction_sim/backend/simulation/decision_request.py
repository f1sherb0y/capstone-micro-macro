from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import time
from typing import Any, Optional

from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile


class DecisionPriority(IntEnum):
    P0_STAGE_CRITICAL = 0
    P1_RESOURCE_CASHFLOW = 1
    P2_INTERACTION = 2
    P3_BACKGROUND = 3


@dataclass
class DecisionRequest:
    request_id: str
    tick: int
    decision_type: str
    agent: EnterpriseAgentProfile
    context: dict[str, Any]
    priority: DecisionPriority = DecisionPriority.P1_RESOURCE_CASHFLOW
    project_id: Optional[str] = None
    allowed_actions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.perf_counter)

    @property
    def agent_id(self) -> str:
        return self.agent.agent_id


@dataclass
class DecisionResult:
    request: DecisionRequest
    action: Optional[AgentAction] = None
    status: str = "completed"
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    queue_ms: int = 0
    model_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.action is not None and not self.error


@dataclass
class InteractionMessage:
    message_id: str
    tick: int
    sender_id: str
    recipient_ids: list[str]
    session_id: Optional[str]
    topic: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateAction:
    action_id: str
    tick: int
    action: AgentAction
    project_id: Optional[str]
    priority: DecisionPriority
    source_request_id: Optional[str] = None
