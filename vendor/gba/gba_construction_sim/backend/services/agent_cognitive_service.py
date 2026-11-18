"""Enterprise-agent cognitive state service.

This service keeps CAMEL-facing agent state separate from the hard simulation
engines. It can read and summarize profile, memory, belief, strategy, and
decision-trace data, but it does not mutate project lifecycle, performance,
engagement, contract, or resource state.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel

from gba_construction_sim.backend.models.action import AgentAction, find_forbidden_action_mutation_keys
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.storage.agent_database import agent_database, summarize_agent


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


def _compact_memory(memory: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "memory_type": item.get("memory_type"),
            "event_type": item.get("event_type"),
            "content": item.get("content"),
            "importance_score": item.get("importance_score"),
            "created_tick": item.get("created_tick"),
        }
        for item in memory[:limit]
    ]


def _compact_beliefs(beliefs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        item.get("belief_type"): {
            "value": item.get("belief_value"),
            "confidence": item.get("confidence"),
            "target": item.get("target_id"),
            "explanation": item.get("explanation"),
        }
        for item in beliefs
    }


class AgentCognitiveService:
    def get_agent_memory(
        self,
        agent_id: str,
        limit: int = 20,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return agent_database.get_agent_memory(agent_id, limit=limit, memory_type=memory_type)

    def get_agent_beliefs(self, agent_id: str) -> list[dict[str, Any]]:
        return agent_database.get_agent_beliefs(agent_id)

    def get_agent_strategy(self, agent_id: str) -> dict[str, Any] | None:
        return agent_database.get_agent_strategy(agent_id)

    def get_agent_decision_trace(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return agent_database.get_agent_decision_trace(agent_id, limit=limit)

    def get_agent_cognitive_state(self, agent_id: str) -> dict[str, Any]:
        record = agent_database.get_agent(agent_id)
        if not record:
            raise KeyError(f"Agent not found: {agent_id}")
        summary = summarize_agent(record)
        strategy = self.get_agent_strategy(agent_id) or {}
        return {
            "agent_id": agent_id,
            "profile_summary": {
                "name": summary["name"],
                "role": summary["role"],
                "region": summary["region"],
                "source_type": summary.get("source_type") or summary.get("agent_type"),
                "agent_type": summary.get("agent_type"),
                "enterprise_scale": summary.get("enterprise_scale"),
                "rating": summary.get("rating"),
                "capabilities": {
                    "financial_capacity": summary.get("financial_capacity"),
                    "technical_capability": summary.get("technical_capability"),
                    "management_capability": summary.get("management_capability"),
                    "cross_region_experience": summary.get("cross_region_experience"),
                    "policy_adaptability": summary.get("policy_adaptability"),
                },
            },
            "profile_7s": strategy.get("profile_7s") or {},
            "schein_culture": strategy.get("schein_culture") or {},
            "memory": self.get_agent_memory(agent_id),
            "beliefs": self.get_agent_beliefs(agent_id),
            "strategy": strategy,
            "decision_trace": self.get_agent_decision_trace(agent_id),
        }

    def build_agent_decision_context(
        self,
        agent: EnterpriseAgentProfile,
        project: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        memory = self.get_agent_memory(agent.agent_id, limit=8)
        beliefs = self.get_agent_beliefs(agent.agent_id)
        strategy = self.get_agent_strategy(agent.agent_id) or {}
        profile_episodes = list(agent.episodic_memory[-8:])
        return {
            "profile_summary": {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role,
                "region": agent.region,
                "financial_capacity": agent.financial_capacity,
                "technical_capability": agent.technical_capability,
                "management_capability": agent.management_capability,
                "risk_preference": agent.risk_preference,
                "collaboration_preference": agent.collaboration_preference,
                "cross_region_experience": agent.cross_region_experience,
                "policy_adaptability": agent.policy_adaptability,
                "available_resource": agent.available_resource(),
                "enterprise_type": agent.enterprise_type,
                "active_regions": list(agent.active_regions),
                "preferred_partners": list(agent.preferred_partners),
            },
            "background_summary": _jsonable(agent.semantic_memory),
            "memory_summary": {
                "persisted_cognitive_memory": _compact_memory(memory),
                "recent_simulation_episodes": _jsonable(profile_episodes),
            },
            "belief_summary": _compact_beliefs(beliefs),
            "strategy_summary": {
                "primary_strategy": strategy.get("primary_strategy"),
                "bidding_aggressiveness": strategy.get("bidding_aggressiveness"),
                "margin_protection_level": strategy.get("margin_protection_level"),
                "cooperation_preference": strategy.get("cooperation_preference"),
                "risk_tolerance": strategy.get("risk_tolerance"),
                "regional_expansion_preference": strategy.get("regional_expansion_preference"),
                "cash_preservation_level": strategy.get("cash_preservation_level"),
                "profile_7s": strategy.get("profile_7s"),
                "schein_culture": strategy.get("schein_culture"),
            },
            "project_snapshot": _jsonable(project),
            "decision_inputs": _jsonable(context),
        }

    def record_decision_trace(
        self,
        agent: EnterpriseAgentProfile,
        context: dict[str, Any],
        action: AgentAction | None,
        *,
        camel_used: bool,
        fallback_used: bool,
        validation_result: dict[str, Any] | None = None,
        explanation: str | None = None,
        candidate_actions: list[str] | None = None,
        utility_score: float | None = None,
        memory_used: list[dict[str, Any]] | None = None,
        retry_info: dict[str, Any] | None = None,
        model_info: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = context.get("project")
        stage_rule = context.get("stage_rule")
        stage = getattr(getattr(project, "current_stage", None), "value", None)
        if not candidate_actions and stage_rule:
            candidate_actions = stage_rule.allowed_actions.get(agent.role, [])
        strategy = self.get_agent_strategy(agent.agent_id) or {}
        beliefs = self.get_agent_beliefs(agent.agent_id)
        memory_snapshot = memory_used if memory_used is not None else _compact_memory(self.get_agent_memory(agent.agent_id, 5))
        model_info = model_info or {}
        selected_action = action.action_type if action else None
        forbidden_keys = find_forbidden_action_mutation_keys(action.data) if action else set()
        scheduler_info = context.get("scheduler") or {}
        validation_payload = validation_result or {
            "valid": not forbidden_keys,
            "forbidden_mutation_keys": sorted(forbidden_keys),
        }
        trace = {
            "agent_id": agent.agent_id,
            "project_id": getattr(project, "project_id", None),
            "tick": context.get("tick", context.get("current_tick")),
            "stage": stage,
            "role": agent.role,
            "decision_type": selected_action or "agent_decision",
            "selected_action": selected_action,
            "candidate_actions": candidate_actions or [],
            "available_actions": candidate_actions or [],
            "utility_score": utility_score,
            "input_context": self._compact_trace_context(context, agent),
            "belief_snapshot": _compact_beliefs(beliefs),
            "memory_used": memory_snapshot,
            "memory_belief_used": {
                "memory_count": len(memory_snapshot),
                "belief_count": len(beliefs),
                "used_memory": bool(memory_snapshot),
                "used_belief": bool(beliefs),
            },
            "strategy_used": {
                key: strategy.get(key)
                for key in [
                    "primary_strategy",
                    "bidding_aggressiveness",
                    "margin_protection_level",
                    "cooperation_preference",
                    "risk_tolerance",
                    "cash_preservation_level",
                ]
            },
            "camel_used": camel_used,
            "fallback_used": fallback_used,
            "validation_result": validation_payload,
            "decision_reason": explanation or (action.reason if action else ""),
            "explanation": explanation or (action.reason if action else ""),
            "model_provider": model_info.get("provider"),
            "model_name": model_info.get("model"),
            "retry_info": retry_info or {
                "attempts": 1,
                "errors": [],
                "queue_ms": scheduler_info.get("queue_ms"),
                "model_ms": scheduler_info.get("model_ms"),
                "skipped_reason": scheduler_info.get("skipped_reason"),
            },
            "error": error_info or {},
            "created_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        }
        return agent_database.record_decision_trace(trace)

    def record_agent_decision_memory(
        self,
        agent: EnterpriseAgentProfile,
        context: dict[str, Any],
        action: AgentAction,
        *,
        source_type: str = "llm_agent_decision",
    ) -> dict[str, Any]:
        """Persist one validated decision as this subject's own episodic memory."""

        project = context.get("project")
        tick = int(context.get("tick", context.get("current_tick", 0)) or 0)
        stage = getattr(getattr(project, "current_stage", None), "value", None)
        content = {
            "decision_type": context.get("decision_type"),
            "action_type": action.action_type,
            "decision": action.decision,
            "reason": action.reason,
            "project_id": getattr(project, "project_id", None),
            "stage": stage,
            "data": action.data,
        }
        return agent_database.record_agent_memory(
            {
                "agent_id": agent.agent_id,
                "memory_type": "decision_episode",
                "related_project_id": getattr(project, "project_id", None),
                "city": getattr(project, "region", agent.region),
                "event_type": "llm_agent_decision",
                "content": json.dumps(content, ensure_ascii=False, default=str),
                "sentiment": "positive" if action.decision else "cautious",
                "importance_score": 0.80 if context.get("decision_priority") == "P0_STAGE_CRITICAL" else 0.65,
                "decay_rate": 0.02,
                "created_tick": tick,
                "last_access_tick": tick,
                "source_type": source_type,
            }
        )

    def record_scheduler_decision_trace(self, result: Any) -> dict[str, Any] | None:
        request = getattr(result, "request", None)
        if not request:
            return None
        scheduler_info = {
            "request_id": request.request_id,
            "status": result.status,
            "queue_ms": result.queue_ms,
            "model_ms": result.model_ms,
            "skipped_reason": result.skipped_reason,
            "error": result.error,
            "decision_type": request.decision_type,
            "priority": getattr(request.priority, "name", str(request.priority)),
        }
        context = {
            **request.context,
            "scheduler": scheduler_info,
        }
        return self.record_decision_trace(
            request.agent,
            context,
            result.action,
            camel_used=result.status in {"completed", "failed"},
            fallback_used=False,
            validation_result={
                "valid": result.ok,
                "scheduler_status": result.status,
                "skipped_reason": result.skipped_reason,
            },
            explanation=result.error
            or result.skipped_reason
            or (result.action.reason if result.action else "Scheduler processed decision request"),
            candidate_actions=request.allowed_actions,
            retry_info={
                "attempts": 1 if result.status != "skipped" else 0,
                "errors": [result.error] if result.error else [],
                "queue_ms": result.queue_ms,
                "model_ms": result.model_ms,
                "skipped_reason": result.skipped_reason,
                "scheduler_status": result.status,
            },
            model_info=context.get("model_info") or {},
            error_info={"message": result.error} if result.error else {},
        )

    def _compact_trace_context(self, context: dict[str, Any], agent: EnterpriseAgentProfile) -> dict[str, Any]:
        project = context.get("project")
        stage_rule = context.get("stage_rule")
        engagement = context.get("engagement")
        policy = context.get("policy")
        macro_environment = context.get("macro_environment")
        cognitive_context = context.get("cognitive_context") or {}
        return {
            "tick": context.get("tick", context.get("current_tick")),
            "project": {
                "project_id": getattr(project, "project_id", None),
                "stage": getattr(getattr(project, "current_stage", None), "value", None),
                "region": getattr(project, "region", None),
                "project_type": getattr(project, "project_type", None),
                "initial_budget": getattr(project, "initial_budget", None),
                "technical_complexity": getattr(project, "technical_complexity", None),
            },
            "engagement": {
                "status": getattr(getattr(engagement, "status", None), "value", None),
                "role": getattr(engagement, "role", None),
                "resource_allocation": getattr(engagement, "resource_allocation", None),
            },
            "stage_rule": {
                "stage": getattr(getattr(stage_rule, "stage", None), "value", None),
                "required_roles": getattr(stage_rule, "required_roles", []),
            },
            "available_actions": context.get("allowed_actions")
            or (stage_rule.allowed_actions.get(agent.role, []) if stage_rule else []),
            "scheduler": _jsonable(context.get("scheduler")),
            "regional_friction": context.get("regional_friction"),
            "previous_collaboration": context.get("previous_collaboration"),
            "policy": {
                "approval_success_prob": getattr(policy, "approval_success_prob", None),
                "procedural_uncertainty": getattr(policy, "procedural_uncertainty", None),
                "compliance_cost": getattr(policy, "compliance_cost", None),
                "cross_region_qualification_recognition": getattr(policy, "cross_region_qualification_recognition", None),
            },
            "macro_environment": {
                "market_demand_index": getattr(macro_environment, "market_demand_index", None),
                "financing_condition_index": getattr(macro_environment, "financing_condition_index", None),
                "material_price_index": getattr(macro_environment, "material_price_index", None),
                "labor_price_index": getattr(macro_environment, "labor_price_index", None),
            },
            "cognitive_context": {
                "memory_summary": cognitive_context.get("memory_summary"),
                "belief_summary": cognitive_context.get("belief_summary"),
                "strategy_summary": cognitive_context.get("strategy_summary"),
            },
            "bid_assessment": _jsonable(context.get("bid_assessment")),
            "owner_decision_score": context.get("owner_decision_score"),
            "initiation_probability": context.get("initiation_probability"),
        }

    def record_simulation_event(self, event: Any, project: Any | None = None) -> None:
        event_type = getattr(event, "event_type", "") or ""
        tick = int(getattr(event, "tick", 0) or 0)
        data = getattr(event, "data", {}) or {}
        target_agent_ids = self._event_target_agent_ids(event, project)
        if not target_agent_ids:
            return
        memory_type = self._memory_type_for_event(event_type)
        importance = self._importance_for_event(event_type)
        content = self._event_memory_content(event, project)
        city = data.get("region") or data.get("city") or getattr(project, "region", "")
        related_project_id = getattr(event, "project_id", None)

        memories: list[dict[str, Any]] = []
        beliefs: list[dict[str, Any]] = []
        for agent_id in sorted(target_agent_ids):
            if not agent_id:
                continue
            memories.append(
                {
                    "agent_id": agent_id,
                    "memory_type": memory_type,
                    "related_agent_id": self._related_agent_id(agent_id, data),
                    "related_project_id": related_project_id,
                    "city": city,
                    "event_type": event_type,
                    "content": content,
                    "sentiment": self._sentiment_for_event(event_type),
                    "importance_score": importance,
                    "decay_rate": 0.02 if importance >= 0.75 else 0.05,
                    "created_tick": tick,
                    "last_access_tick": tick,
                    "source_type": "simulation_event",
                }
            )
            for spec in self._belief_specs_for_event(event_type, data, project):
                beliefs.append(
                    {
                        "agent_id": agent_id,
                        "belief_type": spec["belief_type"],
                        "target_type": spec["target_type"],
                        "target_id": spec["target_id"],
                        "belief_value": spec["belief_value"],
                        "confidence": spec["confidence"],
                        "evidence_count": 1,
                        "updated_tick": tick,
                        "explanation": spec["explanation"],
                    }
                )
        agent_database.record_cognitive_event(memories, beliefs)

    def record_simulation_task(
        self,
        *,
        project_id: str | None,
        agent_id: str | None,
        stage: str | None,
        task_type: str,
        content: str,
        state: str,
        created_tick: int,
        completed_tick: int | None = None,
        result: dict[str, Any] | None = None,
        source: str = "lifecycle_engine",
        parent_task_id: str | None = None,
    ) -> dict[str, Any]:
        return agent_database.record_simulation_task(
            {
                "parent_task_id": parent_task_id,
                "project_id": project_id,
                "agent_id": agent_id,
                "stage": stage,
                "task_type": task_type,
                "content": content,
                "state": state,
                "result": result or {},
                "created_tick": created_tick,
                "completed_tick": completed_tick,
                "source": source,
            }
        )

    def _event_target_agent_ids(self, event: Any, project: Any | None) -> set[str]:
        data = getattr(event, "data", {}) or {}
        target_ids: set[str] = set()
        event_agent_id = getattr(event, "agent_id", None)
        if event_agent_id:
            target_ids.add(event_agent_id)
        for key in [
            "owner_id",
            "architect_id",
            "engineer_id",
            "qs_id",
            "contractor_id",
            "supplier_id",
            "reviewer_id",
            "selected_contractor_id",
            "selected_bank_id",
        ]:
            value = data.get(key)
            if value:
                target_ids.add(str(value))
        for list_key, id_key in [
            ("invited_contractors", "contractor_id"),
            ("ranked_bids", "contractor_id"),
            ("shortlisted_suppliers", "supplier_id"),
        ]:
            for item in data.get(list_key, []) or []:
                value = item.get(id_key) if isinstance(item, dict) else None
                if value:
                    target_ids.add(str(value))
        for list_key in ["invited_contractor_ids", "supplier_ids", "selected_supplier_ids"]:
            for value in data.get(list_key, []) or []:
                if value:
                    target_ids.add(str(value))
        for list_key in ["session_participants", "participants"]:
            for value in data.get(list_key, []) or []:
                if isinstance(value, str) and value:
                    target_ids.add(value)
        if project is not None:
            for value in [
                getattr(project, "owner_id", None),
                getattr(project, "selected_architect_id", None),
                getattr(project, "selected_qs_id", None),
                getattr(project, "selected_contractor_id", None),
                getattr(project, "selected_bank_id", None),
            ]:
                if value and getattr(event, "event_type", "") in {
                    "stage_transition",
                    "project_completed",
                    "project_suspended",
                    "project_failed",
                    "final_account_settled",
                }:
                    target_ids.add(str(value))
        return target_ids

    def _update_beliefs_from_event(
        self,
        agent_id: str,
        event_type: str,
        tick: int,
        data: dict[str, Any],
        project: Any | None,
    ) -> None:
        belief_specs = self._belief_specs_for_event(event_type, data, project)
        for spec in belief_specs:
            agent_database.upsert_agent_belief(
                {
                    "agent_id": agent_id,
                    "belief_type": spec["belief_type"],
                    "target_type": spec["target_type"],
                    "target_id": spec["target_id"],
                    "belief_value": spec["belief_value"],
                    "confidence": spec["confidence"],
                    "evidence_count": 1,
                    "updated_tick": tick,
                    "explanation": spec["explanation"],
                }
            )

    def _belief_specs_for_event(
        self,
        event_type: str,
        data: dict[str, Any],
        project: Any | None,
    ) -> list[dict[str, Any]]:
        project_id = getattr(project, "project_id", data.get("project_id", ""))
        project_target = str(project_id or "")
        if event_type == "project_opportunity_initiated":
            return [
                {
                    "belief_type": "market_opportunity_belief",
                    "target_type": "project",
                    "target_id": project_target,
                    "belief_value": float(data.get("initiation_probability", 0.7)),
                    "confidence": 0.78,
                    "explanation": "A market opportunity was credible enough for the owner to initiate a project.",
                }
            ]
        if event_type == "project_opportunity_declined":
            return [
                {
                    "belief_type": "market_opportunity_belief",
                    "target_type": "region",
                    "target_id": str(data.get("region", "")),
                    "belief_value": float(data.get("initiation_probability", 0.25)),
                    "confidence": 0.65,
                    "explanation": "A project opportunity was evaluated but not initiated under current resource and risk conditions.",
                }
            ]
        if event_type in {"approval_rejected", "approval_approved"}:
            approved = event_type == "approval_approved"
            return [
                {
                    "belief_type": "policy_risk_belief",
                    "target_type": "project",
                    "target_id": project_target,
                    "belief_value": 0.25 if approved else 0.72,
                    "confidence": 0.76,
                    "explanation": "Approval outcome updated perceived statutory and procedural risk.",
                }
            ]
        if event_type in {"bid_submitted", "bid_declined", "bid_failed", "bid_evaluation_completed"}:
            value = {
                "bid_submitted": 0.62,
                "bid_declined": 0.35,
                "bid_failed": 0.25,
                "bid_evaluation_completed": 0.72,
            }[event_type]
            return [
                {
                    "belief_type": "competition_belief",
                    "target_type": "project",
                    "target_id": project_target,
                    "belief_value": value,
                    "confidence": 0.70,
                    "explanation": "Tender participation and evaluation outcome updated competitive positioning.",
                }
            ]
        if event_type in {"contract_awarded", "supplier_selected", "contract_negotiation_recommendation"}:
            partner_id = str(data.get("contractor_id") or data.get("supplier_id") or "")
            return [
                {
                    "belief_type": "partner_trust_belief",
                    "target_type": "agent",
                    "target_id": partner_id,
                    "belief_value": 0.70,
                    "confidence": 0.72,
                    "explanation": "Contract or supply appointment created stronger project-based collaboration evidence.",
                }
            ]
        if event_type in {"supply_delay", "quality_issue", "safety_issue", "project_suspended"}:
            return [
                {
                    "belief_type": "cashflow_risk_belief",
                    "target_type": "project",
                    "target_id": project_target,
                    "belief_value": 0.68,
                    "confidence": 0.72,
                    "explanation": "Delivery disruption increased perceived cashflow or operational risk.",
                }
            ]
        if event_type in {"agent_released", "final_account_settled", "project_completed"}:
            return [
                {
                    "belief_type": "self_capacity_belief",
                    "target_type": "agent",
                    "target_id": "",
                    "belief_value": 0.74,
                    "confidence": 0.69,
                    "explanation": "Resource release or project completion improved perceived available capacity.",
                }
            ]
        return []

    @staticmethod
    def _memory_type_for_event(event_type: str) -> str:
        if event_type.startswith("project_opportunity"):
            return "market_memory"
        if event_type.startswith("bid") or "tender" in event_type:
            return "tender_memory"
        if event_type.startswith("contract") or event_type.endswith("_session_started"):
            return "relationship_memory"
        if event_type.startswith("approval") or event_type in {"inspection_passed", "inspection_failed"}:
            return "policy_memory"
        if event_type in {"agent_engaged", "agent_released", "agent_standby", "agent_recalled", "supplier_selected"}:
            return "relationship_memory"
        if event_type in {"safety_issue", "quality_issue", "supply_delay", "project_suspended", "project_failed"}:
            return "risk_memory"
        if event_type == "agent_operation":
            return "operation_memory"
        return "project_memory"

    @staticmethod
    def _importance_for_event(event_type: str) -> float:
        if event_type in {
            "project_opportunity_initiated",
            "bid_submitted",
            "bid_declined",
            "tender_invitation_received",
            "bid_evaluation_completed",
            "contract_awarded",
            "contract_negotiation_recommendation",
            "supplier_selected",
            "approval_rejected",
            "approval_approved",
            "variation_requested",
            "final_account_settled",
            "project_completed",
            "project_suspended",
            "project_failed",
        }:
            return 0.86
        if event_type.endswith("_session_started"):
            return 0.78
        if event_type.startswith("agent_") or event_type.startswith("stage_"):
            return 0.68
        return 0.55

    @staticmethod
    def _sentiment_for_event(event_type: str) -> str:
        if event_type in {"bid_declined", "bid_failed", "approval_rejected", "quality_issue", "safety_issue", "project_suspended", "project_failed", "supply_delay"}:
            return "negative"
        if event_type in {"project_opportunity_initiated", "approval_approved", "bid_submitted", "contract_awarded", "supplier_selected", "project_completed", "final_account_settled"}:
            return "positive"
        return "neutral"

    @staticmethod
    def _related_agent_id(agent_id: str, data: dict[str, Any]) -> str | None:
        for key in ["contractor_id", "supplier_id", "owner_id", "architect_id", "qs_id", "reviewer_id"]:
            value = data.get(key)
            if value and value != agent_id:
                return str(value)
        return None

    @staticmethod
    def _event_memory_content(event: Any, project: Any | None) -> str:
        data = getattr(event, "data", {}) or {}
        project_name = getattr(project, "name", None)
        stage = getattr(getattr(event, "stage", None), "value", getattr(event, "stage", None))
        details: list[str] = []
        for key in [
            "project_type",
            "region",
            "budget",
            "bid_price",
            "expected_profit",
            "risk_level",
            "contract_sum",
            "final_account_amount",
            "decline_reason",
            "result",
            "failure_reason",
            "resource_allocation",
            "delay_days",
            "delay_days_added",
            "payment_amount",
            "payment_status",
            "selected_action",
            "decision_reason",
            "skipped_reason",
            "error",
        ]:
            if key in data and data[key] is not None:
                details.append(f"{key}={data[key]}")
        suffix = f" Details: {', '.join(details)}." if details else ""
        project_part = f" on {project_name}" if project_name else ""
        stage_part = f" during {stage}" if stage else ""
        return f"{getattr(event, 'description', '')}{project_part}{stage_part}.{suffix}".strip()


agent_cognitive_service = AgentCognitiveService()
