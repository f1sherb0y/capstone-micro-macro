import json
from typing import Any, Dict, Optional

from pydantic import BaseModel

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.action import AgentAction, FORBIDDEN_ACTION_MUTATION_KEYS
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.stage_rule import StageRule


FORBIDDEN_ACTION_DATA_KEYS = sorted(FORBIDDEN_ACTION_MUTATION_KEYS)


def build_decision_prompt(
    agent: EnterpriseAgentProfile,
    project: Optional[ConstructionProject],
    stage_rule: StageRule,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    context = context or {}
    allowed_actions = list(context.get("allowed_actions") or stage_rule.allowed_actions.get(agent.role, []))
    engagement = context.get("engagement")
    policy = context.get("policy")
    macro_environment = context.get("macro_environment")
    regional_friction = context.get("regional_friction", context.get("friction"))
    previous_collaboration = context.get("previous_collaboration")
    tick = context.get("tick", context.get("current_tick"))
    cognitive_context = context.get("cognitive_context") or {}
    rag_context = context.get("rag_context") or []

    decision_context = {
        "tick": tick,
        "agent": _compact_agent(agent),
        "agent_background": {
            "semantic_memory": _jsonable(agent.semantic_memory),
            "recent_profile_episodes": _jsonable(agent.episodic_memory[-8:]),
        },
        "enterprise_cognitive_state": {
            "profile_summary": _jsonable(cognitive_context.get("profile_summary")),
            "memory_summary": _jsonable(cognitive_context.get("memory_summary")),
            "belief_summary": _jsonable(cognitive_context.get("belief_summary")),
            "strategy_summary": _jsonable(cognitive_context.get("strategy_summary")),
        },
        "resource_state": {
            "total_resource_capacity": agent.total_resource_capacity,
            "occupied_resource": agent.occupied_resource,
            "available_resource": agent.available_resource(),
        },
        "engagement": _jsonable(engagement),
        "project": _compact_project(project),
        "stage_rule": {
            "required_roles": stage_rule.required_roles,
            "allowed_actions_for_role": allowed_actions,
            "entry_conditions": stage_rule.entry_conditions,
            "exit_conditions": stage_rule.exit_conditions,
            "failure_conditions": stage_rule.failure_conditions,
            "next_stage": stage_rule.next_stage.value if stage_rule.next_stage else None,
        },
        "policy": _jsonable(policy),
        "macro_environment": _jsonable(macro_environment),
        "regional_friction": regional_friction,
        "previous_collaboration": previous_collaboration,
        "retrieved_local_context": _jsonable(rag_context),
        "forbidden_action_data_keys": FORBIDDEN_ACTION_DATA_KEYS,
        "decision_task": _jsonable(context.get("decision_task")),
        "formal_decision_support": _jsonable(context.get("decision_support")),
        "decision_inputs": _jsonable(
            {
                key: context.get(key)
                for key in [
                    "owner_decision_score",
                    "initiation_probability",
                    "decision_factors",
                    "generation_pressure",
                    "opportunity",
                ]
                if key in context
            }
        ),
    }
    role_guidance = _role_guidance(agent.role)

    return (
        "You are the decision-making intelligence of one specific enterprise agent in a Greater Bay Area construction simulation.\n"
        "Your job is to make exactly one bounded enterprise choice for this agent, using only this agent's identity, "
        "background, memory, beliefs, strategy, resources, messages, and current situation. You do not control lifecycle transitions, "
        "project state, engagement status, or validation. The simulation rule engine will validate your output.\n\n"
        "Hard constraints:\n"
        "1. Choose action_type only from allowed_actions_for_role.\n"
        "2. If the agent lacks resources, qualification, or risk appetite, set decision=false and explain why.\n"
        "3. Reflect the agent's real enterprise logic: finance, occupied resources, region experience, policy fit, "
        "collaboration history, memory, belief, strategy, project complexity, expected profit, and delivery risk.\n"
        "4. Do not invent lifecycle jumps, partners, contract awards, or construction progress.\n"
        "5. Do not place lifecycle, performance, contract, resource, or engagement mutation keys inside data. "
        "Forbidden keys are illegal even as analysis labels; for resource reasoning use keys like "
        "resource_fit_score, capacity_comment, or resource_utilization_estimate instead of resource_allocation.\n"
        "6. Return only data matching the AgentAction schema.\n\n"
        "7. Treat formal_decision_support as evidence, not as a prior decision. You choose independently whether "
        "to act. Do not overwrite computed engineering, cost, capacity, or risk values.\n"
        "8. If decision_task contains candidate_options and choice_output_field, place the selected valid option id "
        "in data under that exact field.\n\n"
        f"Role-specific decision logic for {agent.role}:\n{role_guidance}\n\n"
        f"AgentAction JSON schema:\n{json.dumps(_compact_action_schema(), ensure_ascii=False)}\n\n"
        f"Decision context:\n{json.dumps(decision_context, ensure_ascii=False, default=str)}"
    )


def build_system_message() -> str:
    return (
        "You are a CAMEL ChatAgent acting as one identified subject's decision and explanation layer in a construction "
        "multi-agent simulation. You must produce that subject's structured bounded choice and never directly "
        "modify project lifecycle, project performance, or engagement state."
    )


def _role_guidance(role: str) -> str:
    guidance = {
        "Owner": (
            "Evaluate market demand, financing capacity, active project load, payment reliability, "
            "policy uncertainty, and regional fit. Initiate only when the opportunity is financially "
            "and operationally credible; otherwise evaluate or defer."
        ),
        "Architect": (
            "Focus on design quality, approval readiness, information coordination, technical complexity, "
            "recall obligations, and whether design changes reduce future variation and approval risk."
        ),
        "Engineer": (
            "Focus on technical feasibility, constructability, safety, coordination interfaces, design assumptions, "
            "inspection evidence, and whether available engineering capacity is adequate for the assignment."
        ),
        "QS": (
            "Focus on cost certainty, tender documentation quality, bill-of-quantities readiness, "
            "bid-comparison integrity, variation valuation, claim exposure, and final account settlement."
        ),
        "Contractor": (
            "For tendering, decide bid or decline using expected margin, construction capacity, spare resource, "
            "cashflow pressure, safety/quality capability, qualification recognition, regional friction, "
            "collaboration trust, and competing workload. Never assume award before evaluation."
        ),
        "Supplier": (
            "Focus on material availability, supply reliability, price volatility, delivery region, "
            "contractor trust, inventory constraints, and whether accepting supply work creates delay risk."
        ),
        "Government": (
            "Focus on statutory compliance, information completeness, procedural uncertainty, safety and "
            "quality inspection intensity, transparency, and whether review should approve, reject, or request revision."
        ),
        "Bank": (
            "Focus on borrower strength, requested exposure, cashflow resilience, project and regional risk, security, "
            "portfolio concentration, financing conditions, and whether credit terms fit the bank's own strategy."
        ),
    }
    return guidance.get(role, "Use the enterprise profile, memory, belief, strategy, resource state, and current stage.")


def _action_schema() -> dict[str, Any]:
    if hasattr(AgentAction, "model_json_schema"):
        return AgentAction.model_json_schema()
    return AgentAction.schema()


def _compact_action_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action_type", "project_id", "agent_id", "decision", "data", "reason"],
        "properties": {
            "action_type": "must be one value from allowed_actions_for_role",
            "project_id": "current project_id",
            "agent_id": "requesting agent_id",
            "decision": "boolean",
            "data": (
                "object with decision details only; no forbidden mutation keys. "
                "Use resource_fit_score/resource_utilization_estimate, never resource_allocation."
            ),
            "reason": "one concise sentence",
        },
        "forbidden_data_keys": FORBIDDEN_ACTION_DATA_KEYS,
    }


def _compact_agent(agent: EnterpriseAgentProfile) -> dict[str, Any]:
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
        "cross_region_experience": agent.cross_region_experience,
        "policy_adaptability": agent.policy_adaptability,
        "construction_capability": agent.construction_capability,
        "quality_management_capability": agent.quality_management_capability,
        "safety_management_capability": agent.safety_management_capability,
        "supply_reliability": agent.supply_reliability,
        "material_quality": agent.material_quality,
        "payment_reliability": agent.payment_reliability,
        "decision_speed": agent.decision_speed,
        "total_resource_capacity": agent.total_resource_capacity,
        "occupied_resource": agent.occupied_resource,
        "active_regions": agent.active_regions[:5],
    }


def _compact_performance(performance: Any) -> dict[str, Any]:
    if performance is None:
        return {}
    return {
        "planned_progress": getattr(performance, "planned_progress", None),
        "actual_progress": getattr(performance, "actual_progress", None),
        "overall_quality": getattr(performance, "overall_quality", None),
        "actual_cost": getattr(performance, "actual_cost", None),
        "cost_overrun_ratio": getattr(performance, "cost_overrun_ratio", None),
        "delay_days": getattr(performance, "delay_days", None),
        "safety_risk": getattr(performance, "safety_risk", None),
        "compliance_risk": getattr(performance, "compliance_risk", None),
        "claim_risk": getattr(performance, "claim_risk", None),
        "project_failure_risk": getattr(performance, "project_failure_risk", None),
        "information_quality": getattr(performance, "information_quality", None),
    }


def _compact_project(project: Optional[ConstructionProject]) -> dict[str, Any]:
    if project is None:
        return {}
    return {
        "project_id": project.project_id,
        "name": project.name,
        "stage": project.current_stage.value,
        "project_type": project.project_type,
        "region": project.region,
        "technical_complexity": project.technical_complexity,
        "initial_budget": project.initial_budget,
        "estimated_cost": project.estimated_cost,
        "contract_sum": project.contract_sum,
        "performance": _compact_performance(project.performance),
    }


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
