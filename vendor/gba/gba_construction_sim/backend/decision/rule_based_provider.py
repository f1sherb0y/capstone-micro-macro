from typing import Dict, List, Optional

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.decision.decision_provider import DecisionProvider


class RuleBasedDecisionProvider(DecisionProvider):
    def decide(self, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        project = context.get("project")
        stage = project.current_stage if project else context.get("stage")
        stage_rule = context.get("stage_rule")
        allowed_actions = context.get("allowed_actions") or (
            stage_rule.allowed_actions.get(agent.role, []) if stage_rule else []
        )
        if agent.role == "Owner" and stage == ProjectStage.INITIATION:
            return self._owner_initiation_decision(agent, context, allowed_actions)
        if agent.role == "Contractor" and stage == ProjectStage.TENDERING:
            return self._contractor_tender_decision(agent, context, allowed_actions)
        action_type = self._action_for(agent.role, stage, allowed_actions)
        return AgentAction(
            action_type=action_type,
            project_id=project.project_id if project else None,
            agent_id=agent.agent_id,
            decision=True,
            data=self._decision_data(agent, context),
            reason=f"Rule-based {agent.role} action for {stage.value if isinstance(stage, ProjectStage) else stage}",
        )

    def _owner_initiation_decision(
        self,
        agent: EnterpriseAgentProfile,
        context: Dict,
        allowed_actions: List[str],
    ) -> AgentAction:
        project = context.get("project")
        decision_score = float(context.get("owner_decision_score") or 0.5)
        initiation_probability = float(context.get("initiation_probability") or 0.5)
        decision_factors = context.get("decision_factors") or {}
        budget_capacity = float(decision_factors.get("budget_capacity", 0.5))
        active_projects = int(decision_factors.get("active_owner_projects", 0))
        risk_drag = float(decision_factors.get("risk_drag", 0.3))
        available_resource = agent.available_resource()
        should_initiate = (
            decision_score >= 0.30
            and initiation_probability >= 0.25
            and budget_capacity >= 0.18
            and available_resource >= 0.25
            and active_projects <= 3
            and risk_drag <= 0.75
        )
        action_type = "initiate_project" if should_initiate else "evaluate_market_opportunity"
        if action_type not in allowed_actions:
            action_type = self._action_for(agent.role, ProjectStage.INITIATION, allowed_actions)
        return AgentAction(
            action_type=action_type,
            project_id=project.project_id if project else None,
            agent_id=agent.agent_id,
            decision=should_initiate,
            data={
                "owner_decision_score": round(decision_score, 4),
                "initiation_probability": round(initiation_probability, 4),
                "available_resource": round(available_resource, 4),
                "decision_factors": decision_factors,
            },
            reason=(
                "Owner has sufficient capital, resource capacity, and market support to initiate the project"
                if should_initiate
                else "Owner keeps the opportunity under review because capacity, finance, or risk conditions are weak"
            ),
        )

    def _contractor_tender_decision(
        self,
        agent: EnterpriseAgentProfile,
        context: Dict,
        allowed_actions: List[str],
    ) -> AgentAction:
        project = context.get("project")
        policy = context.get("policy")
        macro_environment = context.get("macro_environment")
        regional_friction = float(context.get("regional_friction") or 0.0)
        previous_collaboration = float(context.get("previous_collaboration") or 0.5)
        resource_fit = self._clamp(agent.available_resource() / 0.15)
        tender_attractiveness = float(
            context.get("tender_attractiveness")
            or getattr(project, "flags", {}).get("tender_attractiveness", 0.55)
            if project
            else 0.55
        )
        policy_cost = float(getattr(policy, "compliance_cost", 0.2))
        qualification_recognition = float(getattr(policy, "cross_region_qualification_recognition", 0.5))
        material_index = float(getattr(macro_environment, "material_price_index", 1.0))
        labor_index = float(getattr(macro_environment, "labor_price_index", 1.0))
        project_failure_risk = float(getattr(getattr(project, "performance", None), "project_failure_risk", 0.0))
        complexity = float(getattr(project, "technical_complexity", 0.5))
        delivery_strength = (
            0.30 * agent.construction_capability
            + 0.20 * agent.management_capability
            + 0.18 * agent.financial_capacity
            + 0.16 * agent.quality_management_capability
            + 0.16 * agent.safety_management_capability
        )
        market_pressure = self._clamp(0.45 * max(0.0, material_index - 1.0) + 0.35 * max(0.0, labor_index - 1.0))
        risk_level = self._clamp(
            0.22 * complexity
            + 0.18 * project_failure_risk
            + 0.16 * policy_cost
            + 0.15 * regional_friction
            + 0.14 * market_pressure
            + 0.15 * max(0.0, 1.0 - resource_fit)
        )
        bid_score = self._clamp(
            0.22 * tender_attractiveness
            + 0.18 * agent.risk_preference
            + 0.17 * resource_fit
            + 0.16 * delivery_strength
            + 0.11 * qualification_recognition
            + 0.08 * previous_collaboration
            + 0.08 * agent.cross_region_experience
            - 0.20 * risk_level
            - 0.08 * regional_friction
        )
        expected_profit = self._clamp(0.035 + 0.10 * agent.risk_preference + 0.04 * risk_level - 0.05 * policy_cost)
        should_bid = bid_score >= 0.42 and expected_profit >= 0.045 and resource_fit >= 0.35
        action_type = "submit_bid" if should_bid else "decline_bid"
        if action_type not in allowed_actions:
            action_type = self._action_for(agent.role, ProjectStage.TENDERING, allowed_actions)
        return AgentAction(
            action_type=action_type,
            project_id=project.project_id if project else None,
            agent_id=agent.agent_id,
            decision=should_bid,
            data={
                "bid_probability": round(bid_score, 4),
                "expected_profit": round(expected_profit, 4),
                "risk_level": round(risk_level, 4),
                "decision_factors": {
                    "tender_attractiveness": round(tender_attractiveness, 4),
                    "resource_fit": round(resource_fit, 4),
                    "delivery_strength": round(delivery_strength, 4),
                    "qualification_recognition": round(qualification_recognition, 4),
                    "regional_friction": round(regional_friction, 4),
                    "previous_collaboration": round(previous_collaboration, 4),
                    "policy_compliance_cost": round(policy_cost, 4),
                    "material_price_index": round(material_index, 4),
                    "labor_price_index": round(labor_index, 4),
                },
            },
            reason=(
                "Contractor has enough resource, margin, and delivery fit for the tender"
                if should_bid
                else "Contractor declines because resource, expected margin, or delivery risk is not acceptable"
            ),
        )

    def _decision_data(self, agent: EnterpriseAgentProfile, context: Dict) -> Dict:
        return {
            "available_resource": round(agent.available_resource(), 4),
            "regional_friction": round(float(context.get("regional_friction") or 0.0), 4),
            "previous_collaboration": round(float(context.get("previous_collaboration") or 0.5), 4),
        }

    def _action_for(self, role: str, stage: ProjectStage, allowed_actions: Optional[List[str]] = None) -> str:
        defaults = {
            ("Owner", ProjectStage.INITIATION): "initiate_project",
            ("Architect", ProjectStage.DESIGN): "prepare_detailed_design",
            ("QS", ProjectStage.DESIGN): "update_cost_estimate",
            ("Government", ProjectStage.APPROVAL): "review_submission",
            ("QS", ProjectStage.TENDER_PREPARATION): "prepare_tender_documents",
            ("Contractor", ProjectStage.TENDERING): "submit_bid",
            ("QS", ProjectStage.BID_EVALUATION): "rank_bids",
            ("Owner", ProjectStage.CONTRACT_AWARD): "award_contract",
            ("Contractor", ProjectStage.CONSTRUCTION): "execute_work",
            ("Supplier", ProjectStage.CONSTRUCTION): "deliver_materials",
            ("Government", ProjectStage.COMPLETION): "conduct_final_inspection",
            ("QS", ProjectStage.FINAL_ACCOUNT): "prepare_final_account",
        }
        preferred = defaults.get((role, stage))
        if allowed_actions:
            if preferred in allowed_actions:
                return preferred
            return allowed_actions[0]
        return preferred or "monitor_progress"

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))
