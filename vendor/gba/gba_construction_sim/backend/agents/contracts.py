"""Stable contracts between the simulation core and an agent implementation.

The simulation is intentionally allowed to know *what* decision is required,
but not how an agent framework stores memory, builds prompts, or calls a model.
These versioned DTOs are safe to send to an in-process adapter or an external
agent service.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from gba_construction_sim.backend.agents.base_agent import AgentDecision, BaseEnterpriseAgent
from gba_construction_sim.backend.models.action import FORBIDDEN_ACTION_MUTATION_KEYS
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile


AGENT_MODULE_CONTRACT_VERSION = "1.0"


def to_jsonable(value: Any) -> Any:
    """Convert simulation objects into a transport-safe snapshot."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return to_jsonable(value.dict())
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return str(value)


class AgentIdentityV1(BaseModel):
    agent_id: str
    name: str
    role: str
    region: str
    enterprise_type: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    background: Dict[str, Any] = Field(default_factory=dict)


class AgentChoiceContractV1(BaseModel):
    output_field: Optional[str] = None
    multiple: bool = False
    limit: Optional[int] = None


class AgentDecisionConstraintsV1(BaseModel):
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_state_keys: list[str] = Field(
        default_factory=lambda: sorted(FORBIDDEN_ACTION_MUTATION_KEYS)
    )
    state_mutation_owner: str = "simulation_core"
    formal_calculation_owner: str = "simulation_core"


class AgentOperationFieldV1(BaseModel):
    """One named field in a role-operation contract."""

    name: str
    value_type: str
    required: bool = True
    description: str
    example: Any = None
    enum: list[Any] = Field(default_factory=list)
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class AgentOperationActionV1(BaseModel):
    """One valid proposal outcome for a role operation."""

    action_type: str
    accepted: Optional[bool] = None
    description: str
    data_fields: list[AgentOperationFieldV1] = Field(default_factory=list)


class AgentOperationContractV1(BaseModel):
    """Machine-readable input/output contract for one role operation."""

    contract_id: str
    operation: str
    role: str
    purpose: str
    inputs: list[AgentOperationFieldV1] = Field(default_factory=list)
    actions: list[AgentOperationActionV1] = Field(default_factory=list)
    factor_fields: list[AgentOperationFieldV1] = Field(default_factory=list)
    final_decision_types: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AgentProposalRequestV1(BaseModel):
    """Input for role-specific professional reasoning before the final choice."""

    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    request_id: str
    operation: str
    agent: AgentIdentityV1
    inputs: Dict[str, Any] = Field(default_factory=dict)
    operation_contract: Optional[AgentOperationContractV1] = None
    recent_episodes: list[Dict[str, Any]] = Field(default_factory=list)
    constraints: AgentDecisionConstraintsV1 = Field(default_factory=AgentDecisionConstraintsV1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentProposalResponseV1(BaseModel):
    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    request_id: str
    action_type: str
    accepted: bool
    utility: float = Field(ge=0.0, le=1.0)
    probability: float = Field(ge=0.0, le=1.0)
    reason: str
    factors: Dict[str, Any] = Field(default_factory=dict)
    data: Dict[str, Any] = Field(default_factory=dict)

    def to_agent_decision(self) -> AgentDecision:
        return AgentDecision(
            action_type=self.action_type,
            accepted=self.accepted,
            utility=self.utility,
            probability=self.probability,
            reason=self.reason,
            factors=dict(self.factors),
            data=dict(self.data),
        )


class AgentDecisionRequestV1(BaseModel):
    """Complete, read-only information package for one bounded agent choice."""

    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    request_id: str
    tick: int
    decision_type: str
    priority: str
    project_id: Optional[str] = None
    agent: AgentIdentityV1
    memory: Dict[str, Any] = Field(default_factory=dict)
    beliefs: Any = Field(default_factory=list)
    strategy: Dict[str, Any] = Field(default_factory=dict)
    current_state: Dict[str, Any] = Field(default_factory=dict)
    project: Dict[str, Any] = Field(default_factory=dict)
    environment: Dict[str, Any] = Field(default_factory=dict)
    policy: Dict[str, Any] = Field(default_factory=dict)
    engagement: Dict[str, Any] = Field(default_factory=dict)
    stage_rule: Dict[str, Any] = Field(default_factory=dict)
    recent_messages: list[Dict[str, Any]] = Field(default_factory=list)
    decision_task: Dict[str, Any] = Field(default_factory=dict)
    decision_support: Dict[str, Any] = Field(default_factory=dict)
    candidate_options: list[Dict[str, Any]] = Field(default_factory=list)
    choice_contract: AgentChoiceContractV1 = Field(default_factory=AgentChoiceContractV1)
    constraints: AgentDecisionConstraintsV1 = Field(default_factory=AgentDecisionConstraintsV1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentDecisionResponseV1(BaseModel):
    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    request_id: str
    agent_id: str
    action_type: str
    decision: bool
    reason: str
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    data: Dict[str, Any] = Field(default_factory=dict)


class AgentObservationV1(BaseModel):
    """Committed simulation fact returned to the agent module after validation."""

    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    event_id: str
    tick: int
    event_type: str
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    stage: Optional[str] = None
    description: str
    data: Dict[str, Any] = Field(default_factory=dict)
    project_snapshot: Dict[str, Any] = Field(default_factory=dict)
    committed: bool = True


class AgentModuleCapabilitiesV1(BaseModel):
    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    module_name: str
    module_version: str
    roles: list[str] = Field(default_factory=list)
    proposal_operations: list[str] = Field(default_factory=list)
    operation_contracts: list[AgentOperationContractV1] = Field(default_factory=list)
    supports_batch_decisions: bool = False
    supports_observations: bool = True
    supports_persistent_memory: bool = True


class AgentModuleHealthV1(BaseModel):
    contract_version: str = AGENT_MODULE_CONTRACT_VERSION
    status: str
    module_name: str
    message: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)


def identity_from_profile(profile: EnterpriseAgentProfile) -> AgentIdentityV1:
    return AgentIdentityV1(
        agent_id=profile.agent_id,
        name=profile.name,
        role=profile.role,
        region=profile.region,
        enterprise_type=profile.enterprise_type,
        capabilities={
            "qualification_level": profile.qualification_level,
            "financial_capacity": profile.financial_capacity,
            "technical_capability": profile.technical_capability,
            "management_capability": profile.management_capability,
            "design_capability": profile.design_capability,
            "cost_estimation_capability": profile.cost_estimation_capability,
            "construction_capability": profile.construction_capability,
            "safety_management_capability": profile.safety_management_capability,
            "quality_management_capability": profile.quality_management_capability,
            "supervision_capability": profile.supervision_capability,
            "supply_reliability": profile.supply_reliability,
            "material_quality": profile.material_quality,
            "payment_reliability": profile.payment_reliability,
            "decision_speed": profile.decision_speed,
        },
        preferences={
            "risk_preference": profile.risk_preference,
            "collaboration_preference": profile.collaboration_preference,
            "cross_region_experience": profile.cross_region_experience,
            "policy_adaptability": profile.policy_adaptability,
            "active_regions": list(profile.active_regions),
            "preferred_partners": list(profile.preferred_partners),
        },
        resources={
            "total_resource_capacity": profile.total_resource_capacity,
            "occupied_resource": profile.occupied_resource,
            "available_resource": profile.available_resource(),
        },
        background=to_jsonable(profile.semantic_memory),
    )


@runtime_checkable
class AgentContextPort(Protocol):
    def standard_context(
        self,
        agent: EnterpriseAgentProfile,
        context: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...


@runtime_checkable
class ExternalAgentClientPort(Protocol):
    """Transport-neutral contract implemented by an external agent module."""

    def propose(self, request: AgentProposalRequestV1) -> AgentProposalResponseV1: ...

    def decide(self, request: AgentDecisionRequestV1) -> AgentDecisionResponseV1: ...

    def observe(self, observation: AgentObservationV1) -> None: ...


@runtime_checkable
class AgentModulePort(Protocol):
    """Only interface the simulation core requires from the agent module."""

    def register_profiles(self, profiles: Iterable[EnterpriseAgentProfile]) -> None: ...

    def for_profile(self, profile: EnterpriseAgentProfile) -> BaseEnterpriseAgent: ...

    def propose(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
        **inputs: Any,
    ) -> AgentDecision: ...

    def proposal_process_name(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
    ) -> str: ...

    def get_operation_contract(
        self,
        operation: str,
        role: str,
    ) -> AgentOperationContractV1: ...

    def resolve_decision(
        self,
        profile: EnterpriseAgentProfile,
        proposal: AgentDecision,
        **kwargs: Any,
    ) -> AgentDecision: ...

    def attach_decision_scheduler(self, decision_scheduler: Any) -> None: ...

    def observe_event(self, event: Any, project: Any | None = None) -> None: ...

    def capabilities(self) -> AgentModuleCapabilitiesV1: ...

    def health(self) -> AgentModuleHealthV1: ...
