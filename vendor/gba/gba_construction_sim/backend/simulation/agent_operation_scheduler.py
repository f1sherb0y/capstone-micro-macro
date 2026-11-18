from __future__ import annotations

import random
from typing import Dict

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.contracts import AgentModulePort
from gba_construction_sim.backend.core.random_utils import clamp
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority


class AgentOperationScheduler:
    def __init__(self, rng: random.Random, agent_registry: AgentModulePort | None = None) -> None:
        self.rng = rng
        self.agent_registry = agent_registry or AgentBehaviorRegistry()

    def preview_operation(
        self,
        agent: EnterpriseAgentProfile,
        macro_environment: MacroEnvironment,
        *,
        use_llm: bool = True,
    ) -> Dict:
        if agent.available_resource() <= 0.05:
            return {
                "operation": "fully_allocated",
                "label": "Fully allocated",
                "description": "All usable resources are committed to active project work.",
                "available_resource": round(agent.available_resource(), 4),
            }

        decision = self.agent_registry.propose(
            agent,
            "decide_monthly_operation",
            macro_environment=macro_environment,
        )
        if use_llm:
            decision = self.agent_registry.resolve_decision(
                agent,
                decision,
                decision_type="monthly_enterprise_operation",
                tick=macro_environment.current_tick,
                macro_environment=macro_environment,
                priority=DecisionPriority.P3_BACKGROUND,
                decision_task=(
                    "Choose the enterprise's most appropriate background operation this month using its identity, "
                    "strategy, recent memory, workload, free resources, risk preference, and current market conditions."
                ),
                allowed_actions=[decision.action_type, "maintain_operations"],
            )
        operation = decision.action_type if decision.accepted else "maintain_operations"
        if operation == "maintain_operations":
            label = "Maintained current operations"
            description = decision.reason or "The enterprise chose not to start a new background initiative this month."
        else:
            label = decision.data.get("label", operation.replace("_", " ").title())
            description = decision.data.get("description", decision.reason)
        return {
            "operation": operation,
            "label": label,
            "description": description,
            "decision_process": self.agent_registry.proposal_process_name(
                agent,
                "decide_monthly_operation",
            ),
            "decision_utility": round(decision.utility, 4),
            "decision_probability": round(decision.probability, 4),
            "decision_accepted": decision.accepted,
            "decision_source": decision.factors.get("decision_source", "local_evidence"),
            "available_resource": round(agent.available_resource(), 4),
            "decision_factors": {
                "market_demand_index": round(macro_environment.market_demand_index, 4),
                "material_price_index": round(macro_environment.material_price_index, 4),
                "financing_condition_index": round(macro_environment.financing_condition_index, 4),
                "resource_free_ratio": round(agent.available_resource() / max(agent.total_resource_capacity, 1e-9), 4),
                "risk_preference": round(agent.risk_preference, 4),
                "cross_region_experience": round(agent.cross_region_experience, 4),
                "policy_adaptability": round(agent.policy_adaptability, 4),
            },
        }

    def step(self, agent: EnterpriseAgentProfile, macro_environment: MacroEnvironment) -> Dict:
        operation = self.preview_operation(agent, macro_environment)
        if operation.get("operation") == "fully_allocated":
            return operation

        if self.rng.random() < 0.15 * agent.available_resource():
            capability_update = None
            if agent.role == "Architect":
                agent.design_capability = clamp(agent.design_capability + 0.01)
                capability_update = "design_capability"
            elif agent.role == "QS":
                agent.cost_estimation_capability = clamp(agent.cost_estimation_capability + 0.01)
                capability_update = "cost_estimation_capability"
            elif agent.role == "Contractor":
                agent.construction_capability = clamp(agent.construction_capability + 0.01)
                capability_update = "construction_capability"
            elif agent.role == "Supplier":
                agent.supply_reliability = clamp(agent.supply_reliability + 0.01)
                capability_update = "supply_reliability"
            elif agent.role == "Government":
                agent.policy_adaptability = clamp(agent.policy_adaptability + 0.005)
                capability_update = "policy_adaptability"
            elif agent.role == "Engineer":
                agent.technical_capability = clamp(agent.technical_capability + 0.01)
                capability_update = "technical_capability"
            elif agent.role == "Bank":
                agent.financial_capacity = clamp(agent.financial_capacity + 0.005)
                capability_update = "financial_capacity"
            if capability_update:
                operation["capability_update"] = capability_update

        agent.episodic_memory.append(
            {
                "tick": macro_environment.current_tick,
                "operation": operation.get("operation"),
                "label": operation.get("label"),
                "available_resource": agent.available_resource(),
                "decision_factors": operation.get("decision_factors", {}),
                "capability_update": operation.get("capability_update"),
            }
        )
        return operation
