from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority, DecisionRequest
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.dict()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


class DecisionRequestCollector:
    """Builds standardized model decision contexts without mutating state."""

    def standard_context(
        self,
        agent: EnterpriseAgentProfile,
        context: dict[str, Any],
        *,
        decision_type: str,
        project: Any | None = None,
        stage_rule: Any | None = None,
        allowed_actions: Optional[list[str]] = None,
        recent_messages: Optional[list[dict[str, Any]]] = None,
        risk_inputs: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        project = project if project is not None else context.get("project")
        stage_rule = stage_rule if stage_rule is not None else context.get("stage_rule")
        allowed_actions = list(allowed_actions or context.get("allowed_actions") or [])
        if not allowed_actions and stage_rule:
            allowed_actions = list(stage_rule.allowed_actions.get(agent.role, []))
        memory = agent_cognitive_service.get_agent_memory(agent.agent_id, limit=8)
        beliefs = agent_cognitive_service.get_agent_beliefs(agent.agent_id)
        strategy = agent_cognitive_service.get_agent_strategy(agent.agent_id) or {}
        cognitive_context = agent_cognitive_service.build_agent_decision_context(agent, project, context)
        standard = {
            **context,
            "decision_type": decision_type,
            "agent_profile": self._agent_profile(agent),
            "agent_background": _jsonable(agent.semantic_memory),
            "agent_memory": memory,
            "agent_recent_episodes": _jsonable(agent.episodic_memory[-8:]),
            "agent_belief": beliefs,
            "agent_strategy": strategy,
            "project_snapshot": self._project_snapshot(project),
            "stage_rule_snapshot": self._stage_rule_snapshot(stage_rule, agent.role),
            "stage_rule": stage_rule,
            "project": project,
            "allowed_actions": allowed_actions,
            "recent_messages": recent_messages if recent_messages is not None else context.get("recent_messages", []),
            "risk_inputs": risk_inputs if risk_inputs is not None else self._risk_inputs(context),
            "cognitive_context": cognitive_context,
        }
        return standard

    def build_request(
        self,
        scheduler: EnterpriseDecisionScheduler,
        agent: EnterpriseAgentProfile,
        context: dict[str, Any],
        *,
        decision_type: str,
        priority: DecisionPriority,
        project_id: Optional[str] = None,
        project: Any | None = None,
        stage_rule: Any | None = None,
        allowed_actions: Optional[list[str]] = None,
        recent_messages: Optional[list[dict[str, Any]]] = None,
        risk_inputs: Optional[dict[str, Any]] = None,
    ) -> DecisionRequest:
        return scheduler.build_request(
            agent,
            self.standard_context(
                agent,
                context,
                decision_type=decision_type,
                project=project,
                stage_rule=stage_rule,
                allowed_actions=allowed_actions,
                recent_messages=recent_messages,
                risk_inputs=risk_inputs,
            ),
            decision_type=decision_type,
            priority=priority,
            project_id=project_id,
        )

    @staticmethod
    def _agent_profile(agent: EnterpriseAgentProfile) -> dict[str, Any]:
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "role": agent.role,
            "region": agent.region,
            "enterprise_type": agent.enterprise_type,
            "qualification_level": agent.qualification_level,
            "financial_capacity": agent.financial_capacity,
            "technical_capability": agent.technical_capability,
            "management_capability": agent.management_capability,
            "risk_preference": agent.risk_preference,
            "collaboration_preference": agent.collaboration_preference,
            "available_resource": agent.available_resource(),
            "active_regions": list(agent.active_regions),
            "preferred_partners": list(agent.preferred_partners),
            "semantic_memory": _jsonable(agent.semantic_memory),
        }

    @staticmethod
    def _project_snapshot(project: Any | None) -> dict[str, Any]:
        if not project:
            return {}
        return {
            "project_id": getattr(project, "project_id", None),
            "name": getattr(project, "name", None),
            "project_type": getattr(project, "project_type", None),
            "region": getattr(project, "region", None),
            "stage": getattr(getattr(project, "current_stage", None), "value", None),
            "owner_id": getattr(project, "owner_id", None),
            "initial_budget": getattr(project, "initial_budget", None),
            "technical_complexity": getattr(project, "technical_complexity", None),
            "selected_architect_id": getattr(project, "selected_architect_id", None),
            "selected_qs_id": getattr(project, "selected_qs_id", None),
            "selected_contractor_id": getattr(project, "selected_contractor_id", None),
            "selected_bank_id": getattr(project, "selected_bank_id", None),
            "bid_count": len(getattr(project, "bids", []) or []),
            "contract_count": len(getattr(project, "contracts", []) or []),
            "flags": _jsonable(getattr(project, "flags", {}) or {}),
        }

    @staticmethod
    def _stage_rule_snapshot(stage_rule: Any | None, role: str) -> dict[str, Any]:
        if not stage_rule:
            return {}
        return {
            "stage": getattr(getattr(stage_rule, "stage", None), "value", None),
            "required_roles": list(getattr(stage_rule, "required_roles", []) or []),
            "allowed_actions": list(getattr(stage_rule, "allowed_actions", {}).get(role, []) or []),
            "exit_conditions": list(getattr(stage_rule, "exit_conditions", []) or []),
        }

    @staticmethod
    def _risk_inputs(context: dict[str, Any]) -> dict[str, Any]:
        return {
            "regional_friction": context.get("regional_friction"),
            "previous_collaboration": context.get("previous_collaboration"),
            "bid_assessment": _jsonable(context.get("bid_assessment")),
            "owner_decision_score": context.get("owner_decision_score"),
            "initiation_probability": context.get("initiation_probability"),
            "decision_factors": _jsonable(context.get("decision_factors")),
        }
