"""Adapters for an independently implemented agent module or service."""

from __future__ import annotations

import asyncio
import math
from typing import Any, Iterable, Optional, Type, TypeVar

from pydantic import BaseModel

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.base_agent import AgentDecision
from gba_construction_sim.backend.agents.contracts import (
    AGENT_MODULE_CONTRACT_VERSION,
    AgentChoiceContractV1,
    AgentDecisionConstraintsV1,
    AgentDecisionRequestV1,
    AgentDecisionResponseV1,
    AgentModuleCapabilitiesV1,
    AgentModuleHealthV1,
    AgentObservationV1,
    AgentProposalRequestV1,
    AgentProposalResponseV1,
    ExternalAgentClientPort,
    identity_from_profile,
    to_jsonable,
)
from gba_construction_sim.backend.agents.operation_specs import (
    get_operation_contract,
    list_operation_contracts,
    validate_operation_inputs,
    validate_operation_response,
)
from gba_construction_sim.backend.decision.decision_provider import DecisionProvider
from gba_construction_sim.backend.models.action import AgentAction, find_forbidden_action_mutation_keys
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler


class AgentModuleIntegrationError(RuntimeError):
    """Raised when the external module violates the integration contract."""


def bounded_selection_validation_view(request: Any, response: Any) -> dict[str, Any]:
    """Validate an Owner's bounded bid choice without granting state-write access.

    Only the top-level candidate ID is omitted from the mutation scan copy.
    The original payload, including its choice, still goes to native commitment.
    """
    data = dict(response.data)
    if "selected_contractor_id" not in data:
        return data
    proposal = isinstance(request, AgentProposalRequestV1)
    final = isinstance(request, AgentDecisionRequestV1)
    valid_proposal = (proposal and request.agent.role == "Owner"
        and request.operation == "select_preferred_bid"
        and response.action_type == "select_preferred_bidder" and response.accepted is True)
    valid_final = (final and request.agent.role == "Owner"
        and request.decision_type == "owner_preferred_bidder_selection"
        and response.action_type == "select_preferred_bidder" and response.decision is True
        and response.action_type in request.constraints.allowed_actions
        and request.choice_contract.output_field == "selected_contractor_id"
        and not request.choice_contract.multiple)
    if not (valid_proposal or valid_final):
        return data  # All other contexts retain the original recursive rejection.
    candidates = request.inputs.get("evaluated_bids", []) if proposal else request.candidate_options
    key = "contractor_id" if proposal else "id"
    ids = [row.get(key) for row in candidates if isinstance(row, dict)]
    selected = data["selected_contractor_id"]
    if (len(ids) != len(candidates) or not ids
            or any(not isinstance(value, str) or not value.strip() for value in ids)
            or len(set(ids)) != len(ids) or not isinstance(selected, str) or selected not in ids):
        raise AgentModuleIntegrationError("Owner selection requires unique current candidates and a valid candidate ID.")
    if proposal:
        contract = get_operation_contract("select_preferred_bid", "Owner")
        if request.operation_contract != contract:
            raise AgentModuleIntegrationError("Owner selection contract differs from the registered contract.")
        validate_operation_inputs(contract, request.inputs)
        validate_operation_response(contract, response, request.inputs)
        ranked = data.get("ranked_bids")
        if (not isinstance(ranked, list) or len(ranked) != len(ids)
                or any(not isinstance(row, dict) for row in ranked)):
            raise AgentModuleIntegrationError("Owner ranking must preserve the complete current bid set.")
        ranked_ids = [row.get("contractor_id") for row in ranked]
        if any(not isinstance(value, str) for value in ranked_ids) or set(ranked_ids) != set(ids) or len(set(ranked_ids)) != len(ids):
            raise AgentModuleIntegrationError("Owner ranking cannot add, omit or repeat a current bid.")
        original = {row["contractor_id"]: row for row in candidates}
        for row in ranked:
            source = original[row["contractor_id"]]
            score = row.get("owner_selection_score")
            if (isinstance(score, bool) or not isinstance(score, (float, int))
                    or not math.isfinite(score) or not 0 <= score <= 1
                    or set(row) != set(source) | {"owner_selection_score"}
                    or any(row.get(k) != v for k, v in source.items())):
                raise AgentModuleIntegrationError("Owner ranking may only add a finite bounded selection score to unchanged bids.")
    elif any(k in data for k in ("ranked_bids", "bid_price", "evaluation_score", "owner_selection_score")):
        raise AgentModuleIntegrationError("Final Owner choice cannot overwrite formal bid evidence.")
    data.pop("selected_contractor_id")
    return data


ModelT = TypeVar("ModelT", bound=BaseModel)


def _parse_model(model_type: Type[ModelT], value: Any) -> ModelT:
    if isinstance(value, model_type):
        return value
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(value)
    return model_type.parse_obj(value)


def _require_contract_version(version: str) -> None:
    if version != AGENT_MODULE_CONTRACT_VERSION:
        raise AgentModuleIntegrationError(
            f"Unsupported agent contract version {version!r}; expected {AGENT_MODULE_CONTRACT_VERSION!r}."
        )


def _decision_task(context: dict[str, Any]) -> dict[str, Any]:
    task = context.get("decision_task") or {}
    if isinstance(task, str):
        return {"objective": task}
    return to_jsonable(task)


def build_decision_request_v1(
    agent: EnterpriseAgentProfile,
    context: dict[str, Any],
) -> AgentDecisionRequestV1:
    task = _decision_task(context)
    allowed_actions = list(context.get("allowed_actions") or [])
    project_snapshot = context.get("project_snapshot") or to_jsonable(context.get("project")) or {}
    project_id = project_snapshot.get("project_id") if isinstance(project_snapshot, dict) else None
    request_id = str(
        context.get("request_id")
        or f"tick{int(context.get('tick', context.get('current_tick', 0)) or 0)}-"
        f"{project_id or 'none'}-{agent.agent_id}-{context.get('decision_type', 'agent_decision')}"
    )
    return AgentDecisionRequestV1(
        request_id=request_id,
        tick=int(context.get("tick", context.get("current_tick", 0)) or 0),
        decision_type=str(context.get("decision_type") or "agent_decision"),
        priority=str(context.get("decision_priority") or "P1_RESOURCE_CASHFLOW"),
        project_id=project_id,
        agent=identity_from_profile(agent),
        memory={
            "persistent": to_jsonable(context.get("agent_memory") or []),
            "recent_episodes": to_jsonable(
                context.get("agent_recent_episodes") or agent.episodic_memory[-8:]
            ),
        },
        beliefs=to_jsonable(context.get("agent_belief") or []),
        strategy=to_jsonable(context.get("agent_strategy") or {}),
        current_state={
            "available_resource": agent.available_resource(),
            "occupied_resource": agent.occupied_resource,
            "total_resource_capacity": agent.total_resource_capacity,
            "risk_inputs": to_jsonable(context.get("risk_inputs") or {}),
        },
        project=to_jsonable(project_snapshot),
        environment=to_jsonable(
            context.get("macro_environment") or context.get("environment") or {}
        ),
        policy=to_jsonable(context.get("policy") or {}),
        engagement=to_jsonable(context.get("engagement") or {}),
        stage_rule=to_jsonable(
            context.get("stage_rule_snapshot") or context.get("stage_rule") or {}
        ),
        recent_messages=to_jsonable(context.get("recent_messages") or []),
        decision_task=task,
        decision_support=to_jsonable(
            context.get("decision_support") or task.get("decision_support_only") or {}
        ),
        candidate_options=to_jsonable(
            task.get("candidate_options") or context.get("candidate_options") or []
        ),
        choice_contract=AgentChoiceContractV1(
            output_field=task.get("choice_output_field"),
            multiple=bool(task.get("choice_multiple", False)),
            limit=task.get("choice_limit"),
        ),
        constraints=AgentDecisionConstraintsV1(allowed_actions=allowed_actions),
        metadata={
            "simulation_id": context.get("simulation_id"),
            "correlation_id": context.get("correlation_id"),
            "context_schema": "agent_decision_context_v1",
        },
    )


def build_observation_v1(event: Any, project: Any | None = None) -> AgentObservationV1:
    stage = getattr(event, "stage", None)
    return AgentObservationV1(
        event_id=str(getattr(event, "event_id", "")),
        tick=int(getattr(event, "tick", 0) or 0),
        event_type=str(getattr(event, "event_type", "simulation_event")),
        project_id=getattr(event, "project_id", None),
        agent_id=getattr(event, "agent_id", None),
        stage=getattr(stage, "value", stage),
        description=str(getattr(event, "description", "")),
        data=to_jsonable(getattr(event, "data", {}) or {}),
        project_snapshot=to_jsonable(project) if project is not None else {},
    )


class ExternalAgentDecisionProvider(DecisionProvider):
    """Expose a versioned external client through the existing scheduler."""

    def __init__(self, client: ExternalAgentClientPort) -> None:
        self.client = client

    def decide(self, agent: EnterpriseAgentProfile, context: dict) -> AgentAction:
        request = build_decision_request_v1(agent, context)
        response = self.client.decide(request)
        return self._validated_action(request, response)

    async def decide_async(self, agent: EnterpriseAgentProfile, context: dict) -> AgentAction:
        request = build_decision_request_v1(agent, context)
        decide_async = getattr(self.client, "decide_async", None)
        if callable(decide_async):
            response = await decide_async(request)
        else:
            response = await asyncio.to_thread(self.client.decide, request)
        return self._validated_action(request, response)

    def decide_batch(
        self,
        requests: Iterable[AgentDecisionRequestV1],
    ) -> list[AgentAction]:
        request_list = list(requests)
        decide_batch = getattr(self.client, "decide_batch", None)
        if callable(decide_batch):
            responses = list(decide_batch(request_list))
        else:
            responses = [self.client.decide(request) for request in request_list]
        if len(responses) != len(request_list):
            raise AgentModuleIntegrationError("External batch response count does not match request count.")
        return [
            self._validated_action(request, response)
            for request, response in zip(request_list, responses)
        ]

    def observe_event(self, event: Any, project: Any | None = None) -> None:
        observe = getattr(self.client, "observe", None)
        if callable(observe):
            observe(build_observation_v1(event, project))

    @staticmethod
    def _validated_action(
        request: AgentDecisionRequestV1,
        raw_response: Any,
    ) -> AgentAction:
        response = _parse_model(AgentDecisionResponseV1, raw_response)
        _require_contract_version(response.contract_version)
        if response.request_id != request.request_id:
            raise AgentModuleIntegrationError("External decision response request_id does not match the request.")
        if response.agent_id != request.agent.agent_id:
            raise AgentModuleIntegrationError("External decision response belongs to a different agent.")
        if response.action_type not in request.constraints.allowed_actions:
            raise AgentModuleIntegrationError(
                f"External action {response.action_type!r} is outside the bounded action set."
            )
        forbidden = find_forbidden_action_mutation_keys(bounded_selection_validation_view(request, response))
        if forbidden:
            raise AgentModuleIntegrationError(
                f"External decision attempted to mutate simulation-owned state: {sorted(forbidden)}"
            )
        data = dict(response.data)
        if response.confidence is not None:
            data.setdefault("confidence", response.confidence)
        return AgentAction(
            action_type=response.action_type,
            project_id=request.project_id,
            agent_id=response.agent_id,
            decision=response.decision,
            reason=response.reason,
            data=data,
        )


class ExternalAgentModuleAdapter(AgentBehaviorRegistry):
    """Full replacement adapter for an externally managed agent framework.

    The external client supplies professional proposals, final LLM decisions,
    memory handling, and observation ingestion. The inherited registry retains
    the simulation-side bounds and validation semantics.
    """

    def __init__(
        self,
        client: ExternalAgentClientPort,
        profiles: Iterable[EnterpriseAgentProfile] = (),
        *,
        random_seed: Optional[int] = None,
        scheduler_options: Optional[dict[str, Any]] = None,
    ) -> None:
        self.client = client
        self.decision_provider = ExternalAgentDecisionProvider(client)
        scheduler = EnterpriseDecisionScheduler(
            self.decision_provider,
            **(scheduler_options or {}),
        )
        super().__init__(profiles, random_seed, scheduler)

    def propose(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
        **inputs: Any,
    ) -> AgentDecision:
        self.for_profile(profile)
        tick = int(
            inputs.get("tick")
            or getattr(inputs.get("macro_environment"), "current_tick", 0)
            or 0
        )
        project = inputs.get("project")
        project_id = getattr(project, "project_id", None)
        try:
            contract = self.get_operation_contract(operation, profile.role)
            transport_inputs = to_jsonable(inputs)
            validate_operation_inputs(contract, transport_inputs)
        except ValueError as exc:
            raise AgentModuleIntegrationError(str(exc)) from exc
        request = AgentProposalRequestV1(
            request_id=f"proposal-tick{tick}-{project_id or 'none'}-{profile.agent_id}-{operation}",
            operation=operation,
            agent=identity_from_profile(profile),
            inputs=transport_inputs,
            operation_contract=contract,
            recent_episodes=to_jsonable(profile.episodic_memory[-8:]),
            metadata={"project_id": project_id, "tick": tick},
        )
        propose = getattr(self.client, "propose", None)
        if not callable(propose):
            raise AgentModuleIntegrationError(
                "The external agent client must implement propose(request)."
            )
        response = _parse_model(AgentProposalResponseV1, propose(request))
        _require_contract_version(response.contract_version)
        if response.request_id != request.request_id:
            raise AgentModuleIntegrationError("External proposal response request_id does not match the request.")
        try:
            validate_operation_response(contract, response, transport_inputs)
        except ValueError as exc:
            raise AgentModuleIntegrationError(str(exc)) from exc
        forbidden = find_forbidden_action_mutation_keys(bounded_selection_validation_view(request, response))
        if forbidden:
            raise AgentModuleIntegrationError(
                f"External proposal attempted to mutate simulation-owned state: {sorted(forbidden)}"
            )
        return response.to_agent_decision()

    def proposal_process_name(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
    ) -> str:
        return f"{self.client.__class__.__name__}.{operation}"

    def observe_event(self, event: Any, project: Any | None = None) -> None:
        observe = getattr(self.client, "observe", None)
        if callable(observe):
            observe(build_observation_v1(event, project))

    def capabilities(self) -> AgentModuleCapabilitiesV1:
        capability_method = getattr(self.client, "capabilities", None)
        if callable(capability_method):
            capabilities = _parse_model(AgentModuleCapabilitiesV1, capability_method())
            _require_contract_version(capabilities.contract_version)
            return capabilities
        contracts = list_operation_contracts()
        return AgentModuleCapabilitiesV1(
            module_name=self.client.__class__.__name__,
            module_version="external",
            roles=sorted({contract.role for contract in contracts}),
            proposal_operations=sorted({contract.operation for contract in contracts}),
            operation_contracts=contracts,
            supports_batch_decisions=callable(getattr(self.client, "decide_batch", None)),
        )

    def health(self) -> AgentModuleHealthV1:
        health_method = getattr(self.client, "health", None)
        if callable(health_method):
            health = _parse_model(AgentModuleHealthV1, health_method())
            _require_contract_version(health.contract_version)
            return health
        return AgentModuleHealthV1(
            status="unknown",
            module_name=self.client.__class__.__name__,
            message="External client does not expose a health endpoint.",
        )
