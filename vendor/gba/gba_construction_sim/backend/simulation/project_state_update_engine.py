import itertools
import random
from typing import Dict, Iterable, Optional

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.core.random_utils import clamp
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_prior import CollaborationPrior
from gba_construction_sim.backend.simulation.event_system import EventSystem


class ProjectStateUpdateEngine:
    def __init__(
        self,
        events: EventSystem,
        rng: Optional[random.Random] = None,
        collaboration_prior: Optional[CollaborationPrior] = None,
    ) -> None:
        self.events = events
        self.rng = rng or random.Random()
        self.collaboration_prior = collaboration_prior or CollaborationPrior()

    def update(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if project.current_stage in {ProjectStage.DESIGN, ProjectStage.CONCEPT_DESIGN, ProjectStage.DETAILED_DESIGN}:
            self.update_design_state(project, agents)
        elif project.current_stage in {ProjectStage.APPROVAL, ProjectStage.STATUTORY_APPROVAL}:
            self.update_approval_state(project, policy, macro_environment)
        elif project.current_stage == ProjectStage.TENDERING:
            self.update_tender_state(project, policy, macro_environment)
        elif project.current_stage == ProjectStage.CONSTRUCTION:
            if project.stage_tick <= 0:
                project.flags["mobilization_ready"] = True
            else:
                self.update_construction_state(project, agents, policy, macro_environment, tick)
        elif project.current_stage == ProjectStage.COMPLETION:
            self.update_completion_state(project, policy)

        project.performance.project_failure_risk = self.calculate_project_failure_risk(project)
        self.events.record(
            tick,
            "project_state_updated",
            f"Project state updated at {project.current_stage.value}",
            project=project,
            data=project.performance.dict(),
        )

    def update_design_state(self, project: ConstructionProject, agents: Dict[str, EnterpriseAgentProfile]) -> None:
        architect = agents.get(project.selected_architect_id or "")
        qs = agents.get(project.selected_qs_id or "")

        architect_quality = architect.design_capability if architect else 0.5
        technical_support = architect.technical_capability if architect else 0.5
        qs_accuracy = qs.cost_estimation_capability if qs else 0.5
        coordination = self.calculate_coordination_efficiency(project, agents)

        design_increment = (
            0.45 * architect_quality
            + 0.25 * technical_support
            + 0.15 * qs_accuracy
            + 0.15 * coordination
        ) * 0.22

        project.performance.design_quality = clamp(project.performance.design_quality + design_increment)
        project.performance.coordination_efficiency = coordination
        project.performance.information_quality = clamp(0.6 * project.performance.design_quality + 0.4 * coordination)
        project.performance.variation_risk = clamp(1.0 - project.performance.design_quality)
        project.estimated_cost = project.initial_budget * (0.90 + 0.20 * (1.0 - qs_accuracy))
        project.performance.planned_cost = project.estimated_cost
        if project.performance.planned_duration <= 0:
            project.performance.planned_duration = max(8, int(18 * project.technical_complexity))

    def update_approval_state(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> None:
        approval_prob = self.calculate_approval_probability(project, policy, macro_environment)
        project.performance.inspection_pass_probability = approval_prob
        project.performance.compliance_risk = clamp(
            1.0 - approval_prob + 0.2 * policy.procedural_uncertainty
        )
        if approval_prob < 0.55:
            project.performance.delay_days += 15
            project.performance.actual_cost += 0.005 * project.initial_budget

    def calculate_approval_probability(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> float:
        regional_friction = self.get_project_regional_friction(project, macro_environment)
        approval_prob = (
            0.35 * policy.approval_success_prob
            + 0.30 * project.performance.design_quality
            + 0.20 * project.performance.information_quality
            + 0.15 * policy.information_transparency
        )
        approval_prob -= 0.20 * policy.procedural_uncertainty
        approval_prob -= 0.20 * regional_friction
        return clamp(approval_prob)

    def update_tender_state(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> None:
        attractiveness = self.calculate_tender_attractiveness(project, policy, macro_environment)
        project.flags["tender_attractive"] = attractiveness >= 0.35
        project.performance.claim_risk = clamp(project.performance.claim_risk + 0.05 * (1.0 - attractiveness))

    def calculate_tender_attractiveness(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> float:
        regional_friction = self.get_project_regional_friction(project, macro_environment)
        budget_reasonableness = project.initial_budget / max(project.performance.planned_cost or project.initial_budget, 1.0)
        attractiveness = (
            0.35 * min(1.0, budget_reasonableness)
            + 0.25 * project.performance.information_quality
            + 0.20 * (1.0 - project.performance.project_failure_risk)
            + 0.20 * policy.information_transparency
        )
        attractiveness -= 0.20 * policy.compliance_cost
        attractiveness -= 0.20 * regional_friction
        return clamp(attractiveness)

    def update_construction_state(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        contractor = agents.get(project.selected_contractor_id or "")
        suppliers = [agents[sid] for sid in project.selected_supplier_ids if sid in agents]
        owner = agents.get(project.owner_id)
        if not contractor or not owner:
            project.performance.delay_days += 30
            project.performance.project_failure_risk = clamp(project.performance.project_failure_risk + 0.2)
            return

        previous_progress = project.performance.actual_progress
        previous_cost = project.performance.actual_cost
        previous_delay_days = project.performance.delay_days
        previous_material_availability = project.performance.material_availability

        self.update_planned_progress(project)
        supply_result = self.update_supply_state(project, suppliers)
        self.update_construction_progress(project, contractor, policy)
        self.update_delay(project)
        self.update_construction_quality(project, contractor, suppliers, policy)
        self.update_detected_defects(project, policy)
        self.update_cost(project, policy, macro_environment)
        self.update_safety_risk(project, contractor, policy)
        self.update_compliance_risk(project, contractor, policy, macro_environment)
        self.update_claim_and_variation_risk(project, owner)
        self.record_construction_process_events(
            project,
            agents,
            owner,
            contractor,
            suppliers,
            policy,
            macro_environment,
            tick,
            previous_progress,
            previous_cost,
            previous_delay_days,
            previous_material_availability,
            supply_result,
        )

    def update_planned_progress(self, project: ConstructionProject) -> None:
        project.performance.elapsed_time += 1
        project.performance.planned_progress = clamp(
            project.performance.elapsed_time / max(project.performance.planned_duration, 1)
        )

    def update_supply_state(self, project: ConstructionProject, suppliers: Iterable[EnterpriseAgentProfile]) -> dict:
        supplier_list = list(suppliers)
        reliability = self.average([supplier.supply_reliability for supplier in supplier_list], default=0.5)
        quality = self.average([supplier.material_quality for supplier in supplier_list], default=0.5)
        supply_delay_risk = clamp(1.0 - reliability)
        delayed = False
        if self.rng.random() < supply_delay_risk * 0.08:
            project.performance.material_availability = clamp(project.performance.material_availability - 0.15)
            project.performance.delay_days += 10
            delayed = True
        else:
            project.performance.material_availability = clamp(project.performance.material_availability + 0.05)
        project.performance.supply_delay_risk = supply_delay_risk
        project.performance.material_quality = quality
        return {
            "delayed": delayed,
            "supplier_count": len(supplier_list),
            "average_reliability": reliability,
            "average_material_quality": quality,
            "supply_delay_risk": supply_delay_risk,
        }

    def update_construction_progress(
        self,
        project: ConstructionProject,
        contractor: EnterpriseAgentProfile,
        policy: PolicyRegime,
    ) -> None:
        base_rate = 1.0 / max(project.performance.planned_duration, 1)
        contractor_factor = (
            0.40 * contractor.construction_capability
            + 0.30 * contractor.management_capability
            + 0.30 * contractor.financial_capacity
        )
        resource_allocation = self.get_resource_allocation(project, contractor.agent_id)
        resource_factor = 0.75 + 0.35 * max(0.0, min(1.0, resource_allocation))
        capability_factor = 0.65 + 0.70 * max(0.0, min(1.0, contractor_factor))
        material_factor = 0.75 + 0.25 * project.performance.material_availability
        coordination_factor = 0.85 + 0.25 * project.performance.coordination_efficiency
        regulatory_drag = 1.0 - 0.12 * policy.regulatory_intensity
        safety_drag = 1.0 - 0.14 * project.performance.safety_risk
        progress_increment = (
            base_rate
            * resource_factor
            * capability_factor
            * material_factor
            * coordination_factor
            * regulatory_drag
            * safety_drag
        )
        project.performance.actual_progress = clamp(project.performance.actual_progress + progress_increment)

    def update_delay(self, project: ConstructionProject) -> None:
        actual = project.performance.actual_progress
        planned = project.performance.planned_progress
        project.performance.progress_deviation = actual - planned
        if actual < planned:
            projected_delay_days = int((planned - actual) * max(project.performance.planned_duration, 1) * 30)
            project.performance.delay_days = max(project.performance.delay_days, projected_delay_days)

    def update_construction_quality(
        self,
        project: ConstructionProject,
        contractor: EnterpriseAgentProfile,
        suppliers: Iterable[EnterpriseAgentProfile],
        policy: PolicyRegime,
    ) -> None:
        contractor_quality = (
            0.40 * contractor.construction_capability
            + 0.30 * contractor.quality_management_capability
            + 0.20 * contractor.management_capability
            + 0.10 * contractor.policy_adaptability
        )
        supplier_quality = self.average([supplier.material_quality for supplier in suppliers], default=0.5)
        regulatory_quality_effect = 0.15 * policy.regulatory_intensity
        construction_quality = (
            0.25 * project.performance.design_quality
            + 0.30 * contractor_quality
            + 0.20 * supplier_quality
            + 0.15 * 0.6
            + 0.10 * regulatory_quality_effect
        )
        project.performance.construction_quality = clamp(construction_quality)
        project.performance.overall_quality = clamp(
            0.40 * project.performance.design_quality + 0.60 * project.performance.construction_quality
        )
        project.performance.defect_rate = clamp(1.0 - project.performance.overall_quality)

    def update_detected_defects(self, project: ConstructionProject, policy: PolicyRegime) -> None:
        project.performance.detected_defect_rate = (
            project.performance.defect_rate * clamp(policy.regulatory_intensity)
        )

    def update_cost(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> None:
        if not project.contract_sum:
            return
        previous_costed_progress = float(project.flags.get("last_costed_progress", 0.0))
        progress_delta = max(0.0, project.performance.actual_progress - previous_costed_progress)
        project.flags["last_costed_progress"] = project.performance.actual_progress
        earned_work_cost = project.contract_sum * progress_delta
        monthly_reference_cost = project.contract_sum / max(project.performance.planned_duration, 1)
        progress_pressure = max(0.0, -project.performance.progress_deviation)
        rework_cost = project.performance.detected_defect_rate * 0.05 * monthly_reference_cost
        compliance_cost = policy.compliance_cost * 0.03 * monthly_reference_cost
        delay_cost = progress_pressure * 0.05 * monthly_reference_cost
        overhead_cost = 0.003 * project.contract_sum
        market_price_factor = clamp(
            1.0
            + 0.55 * (macro_environment.material_price_index - 1.0)
            + 0.35 * (macro_environment.labor_price_index - 1.0),
            0.8,
            1.35,
        )
        monthly_cost = (
            earned_work_cost * market_price_factor
            + rework_cost
            + compliance_cost
            + delay_cost
            + overhead_cost
        )
        project.performance.actual_cost += monthly_cost
        project.performance.cost_overrun_ratio = (
            project.performance.actual_cost - project.contract_sum
        ) / max(project.contract_sum, 1.0)

    def update_safety_risk(
        self,
        project: ConstructionProject,
        contractor: EnterpriseAgentProfile,
        policy: PolicyRegime,
    ) -> None:
        management_gap = 1.0 - contractor.safety_management_capability
        schedule_pressure = max(0.0, -project.performance.progress_deviation)
        safety_risk = (
            0.2
            + 0.30 * management_gap
            + 0.25 * schedule_pressure
            + 0.25 * project.technical_complexity
            - 0.20 * policy.regulatory_intensity
        )
        project.performance.safety_risk = clamp(safety_risk)

    def update_compliance_risk(
        self,
        project: ConstructionProject,
        contractor: EnterpriseAgentProfile,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> None:
        regional_friction = self.get_project_regional_friction(project, macro_environment)
        compliance_risk = (
            0.30 * (1.0 - contractor.policy_adaptability)
            + 0.25 * policy.procedural_uncertainty
            + 0.25 * regional_friction
            + 0.20 * (1.0 - project.performance.information_quality)
        )
        project.performance.compliance_risk = clamp(compliance_risk)

    def update_claim_and_variation_risk(
        self,
        project: ConstructionProject,
        owner: EnterpriseAgentProfile,
    ) -> None:
        schedule_pressure = max(0.0, -project.performance.progress_deviation)
        project.performance.variation_risk = clamp(
            0.40 * (1.0 - project.performance.design_quality)
            + 0.25 * (1.0 - owner.decision_speed)
            + 0.20 * schedule_pressure
            + 0.15 * project.performance.detected_defect_rate
        )
        project.performance.claim_risk = clamp(
            0.30 * min(1.0, project.performance.delay_days / 180)
            + 0.25 * max(0.0, project.performance.cost_overrun_ratio)
            + 0.25 * (1.0 - owner.payment_reliability)
            + 0.20 * project.performance.variation_risk
        )
        project.performance.dispute_risk = clamp(
            0.50 * project.performance.claim_risk
            + 0.30 * (1.0 - project.performance.coordination_efficiency)
            + 0.20 * project.performance.compliance_risk
        )

    def record_construction_process_events(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        owner: EnterpriseAgentProfile,
        contractor: EnterpriseAgentProfile,
        suppliers: Iterable[EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
        previous_progress: float,
        previous_cost: float,
        previous_delay_days: int,
        previous_material_availability: float,
        supply_result: dict,
    ) -> None:
        suppliers = list(suppliers)
        progress_delta = max(0.0, project.performance.actual_progress - previous_progress)
        cost_delta = max(0.0, project.performance.actual_cost - previous_cost)
        delay_delta = max(0, project.performance.delay_days - previous_delay_days)
        self.events.record(
            tick,
            "construction_progress_updated",
            "Contractor executed work and reported monthly construction progress",
            project=project,
            agent_id=contractor.agent_id,
            data={
                "contractor_id": contractor.agent_id,
                "contractor_name": contractor.name,
                "actual_progress": round(project.performance.actual_progress, 4),
                "planned_progress": round(project.performance.planned_progress, 4),
                "progress_delta": round(progress_delta, 4),
                "progress_deviation": round(project.performance.progress_deviation, 4),
                "delay_days": project.performance.delay_days,
                "delay_delta_days": delay_delta,
                "monthly_cost": round(cost_delta, 2),
                "actual_cost": round(project.performance.actual_cost, 2),
            },
        )

        if supply_result.get("delayed"):
            self.events.record(
                tick,
                "supply_delay",
                "Material delivery delay reduced site material availability",
                project=project,
                agent_id=suppliers[0].agent_id if suppliers else None,
                data={
                    "supplier_ids": [supplier.agent_id for supplier in suppliers],
                    "supplier_names": [supplier.name for supplier in suppliers],
                    "previous_material_availability": round(previous_material_availability, 3),
                    "material_availability": round(project.performance.material_availability, 3),
                    "supply_delay_risk": round(supply_result["supply_delay_risk"], 3),
                    "average_reliability": round(supply_result["average_reliability"], 3),
                },
            )

        self._record_payment_event(project, owner, contractor, macro_environment, tick)
        self._record_inspection_event(project, agents, policy, tick)
        self._record_safety_event(project, contractor, policy, tick)

    def _record_payment_event(
        self,
        project: ConstructionProject,
        owner: EnterpriseAgentProfile,
        contractor: EnterpriseAgentProfile,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if not project.contract_sum:
            return
        next_payment_progress = float(project.flags.get("next_payment_progress", 0.20))
        if project.performance.actual_progress + 1e-9 < next_payment_progress:
            return

        previous_payment_progress = float(project.flags.get("last_payment_progress", 0.0))
        certified_progress = max(0.0, next_payment_progress - previous_payment_progress)
        payment_amount = project.contract_sum * certified_progress
        delay_probability = clamp(
            0.04
            + 0.30 * (1.0 - owner.payment_reliability)
            + 0.16 * max(0.0, 1.0 - macro_environment.financing_condition_index)
            + 0.12 * project.performance.claim_risk
        )
        delayed = self.rng.random() < delay_probability
        project.flags["last_payment_progress"] = next_payment_progress
        project.flags["next_payment_progress"] = min(1.0, next_payment_progress + 0.20)

        self.events.record(
            tick,
            "payment_requested",
            "Contractor requested interim payment for certified construction progress",
            project=project,
            agent_id=contractor.agent_id,
            data={
                "contractor_id": contractor.agent_id,
                "contractor_name": contractor.name,
                "owner_id": owner.agent_id,
                "owner_name": owner.name,
                "qs_id": project.selected_qs_id,
                "certified_progress": round(next_payment_progress, 3),
                "payment_amount": round(payment_amount, 2),
                "payment_status": "delayed" if delayed else "approved",
                "payment_delay_probability": round(delay_probability, 3),
            },
        )

        if delayed:
            project.performance.claim_risk = clamp(project.performance.claim_risk + 0.04)
            project.performance.dispute_risk = clamp(project.performance.dispute_risk + 0.03)
            self.events.record(
                tick,
                "payment_delayed",
                "Owner payment was delayed, increasing claim and dispute risk",
                project=project,
                agent_id=owner.agent_id,
                data={
                    "owner_id": owner.agent_id,
                    "owner_name": owner.name,
                    "contractor_id": contractor.agent_id,
                    "contractor_name": contractor.name,
                    "payment_amount": round(payment_amount, 2),
                    "owner_payment_reliability": round(owner.payment_reliability, 3),
                    "financing_condition_index": round(macro_environment.financing_condition_index, 3),
                    "claim_risk": round(project.performance.claim_risk, 3),
                    "dispute_risk": round(project.performance.dispute_risk, 3),
                },
            )

    def _record_inspection_event(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        tick: int,
    ) -> None:
        inspection_due = (
            project.performance.elapsed_time == 1
            or project.performance.elapsed_time % 3 == 0
            or project.performance.detected_defect_rate > 0.22
            or project.performance.compliance_risk > 0.55
        )
        if not inspection_due:
            return
        last_inspection_elapsed = int(project.flags.get("last_inspection_elapsed", -1))
        if last_inspection_elapsed == project.performance.elapsed_time:
            return
        project.flags["last_inspection_elapsed"] = project.performance.elapsed_time

        pass_probability = clamp(
            0.92
            - 0.55 * project.performance.detected_defect_rate
            - 0.28 * project.performance.compliance_risk
            - 0.25 * project.performance.safety_risk
            + 0.10 * policy.regulatory_intensity
        )
        passed = self.rng.random() < pass_probability
        event_type = "inspection_passed" if passed else "inspection_failed"
        description = (
            "Regulatory and quality inspection passed"
            if passed
            else "Inspection found issues and required rectification"
        )
        if not passed:
            project.performance.delay_days += 7
            project.performance.actual_cost += 0.004 * (project.contract_sum or project.initial_budget)
            project.performance.claim_risk = clamp(project.performance.claim_risk + 0.03)
        inspector = self._inspection_authority(project, agents)
        self.events.record(
            tick,
            event_type,
            description,
            project=project,
            agent_id=inspector.agent_id if inspector else None,
            data={
                "inspector_id": inspector.agent_id if inspector else None,
                "inspector_name": inspector.name if inspector else "Regional construction regulator",
                "inspector_region": inspector.region if inspector else project.region,
                "inspection_type": "scheduled quality and safety inspection",
                "inspection_month": project.performance.elapsed_time,
                "result": "passed" if passed else "rectification_required",
                "pass_probability": round(pass_probability, 3),
                "regulatory_intensity": round(policy.regulatory_intensity, 3),
                "detected_defect_rate": round(project.performance.detected_defect_rate, 3),
                "safety_risk": round(project.performance.safety_risk, 3),
                "compliance_risk": round(project.performance.compliance_risk, 3),
                "corrective_actions": [] if passed else [
                    "submit rectification plan",
                    "correct detected defects",
                    "follow-up inspection before next payment gate",
                ],
            },
        )

    def _inspection_authority(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
    ) -> Optional[EnterpriseAgentProfile]:
        for engagement in project.engagements:
            if engagement.role != "Government":
                continue
            if engagement.status not in {EngagementStatus.ACTIVE, EngagementStatus.STANDBY}:
                continue
            agent = agents.get(engagement.agent_id)
            if agent:
                return agent
        governments = [agent for agent in agents.values() if agent.role == "Government"]
        if not governments:
            return None
        return max(
            governments,
            key=lambda agent: (
                0.35 if agent.region == project.region else 0.0
            )
            + 0.40 * agent.policy_adaptability
            + 0.15 * agent.management_capability
            + 0.10 * agent.cross_region_experience,
        )

    def _record_safety_event(
        self,
        project: ConstructionProject,
        contractor: EnterpriseAgentProfile,
        policy: PolicyRegime,
        tick: int,
    ) -> None:
        if project.performance.safety_risk <= 0.62:
            return
        last_safety_issue_elapsed = int(project.flags.get("last_safety_issue_elapsed", -1))
        if project.performance.elapsed_time - last_safety_issue_elapsed < 3:
            return
        issue_probability = clamp(
            0.10
            + 0.35 * (project.performance.safety_risk - 0.62)
            - 0.08 * policy.regulatory_intensity
        )
        if self.rng.random() >= issue_probability:
            return
        project.flags["last_safety_issue_elapsed"] = project.performance.elapsed_time
        project.performance.delay_days += 5
        project.performance.claim_risk = clamp(project.performance.claim_risk + 0.02)
        self.events.record(
            tick,
            "safety_issue",
            "Site safety issue required management response",
            project=project,
            agent_id=contractor.agent_id,
            data={
                "contractor_id": contractor.agent_id,
                "contractor_name": contractor.name,
                "safety_risk": round(project.performance.safety_risk, 3),
                "contractor_safety_capability": round(contractor.safety_management_capability, 3),
                "regulatory_intensity": round(policy.regulatory_intensity, 3),
                "delay_days_added": 5,
            },
        )

    def update_completion_state(self, project: ConstructionProject, policy: PolicyRegime) -> None:
        self.update_detected_defects(project, policy)
        if project.performance.detected_defect_rate > 0.25:
            project.performance.delay_days += 15
            project.performance.actual_cost += 0.01 * (project.contract_sum or project.initial_budget)

    def calculate_project_failure_risk(self, project: ConstructionProject) -> float:
        risk = (
            0.25 * min(1.0, project.performance.delay_days / 365)
            + 0.20 * min(1.0, max(0.0, project.performance.cost_overrun_ratio))
            + 0.20 * project.performance.safety_risk
            + 0.15 * project.performance.compliance_risk
            + 0.10 * project.performance.dispute_risk
            + 0.10 * project.performance.defect_rate
        )
        return clamp(risk)

    def calculate_coordination_efficiency(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
    ) -> float:
        participants = [
            agents[engagement.agent_id]
            for engagement in project.engagements
            if engagement.status == EngagementStatus.ACTIVE and engagement.agent_id in agents
        ]
        if len(participants) <= 1:
            return 1.0
        fits = []
        for agent_a, agent_b in itertools.combinations(participants, 2):
            regional_friction = 0.0 if agent_a.region == agent_b.region else 0.25
            previous = self.collaboration_prior.score(agent_a.agent_id, agent_b.agent_id, 0.5)
            capability_match = 1.0 - abs(agent_a.management_capability - agent_b.management_capability)
            fit = (
                0.40 * capability_match
                + 0.30 * previous
                + 0.20 * min(agent_a.cross_region_experience, agent_b.cross_region_experience)
                + 0.10 * min(agent_a.collaboration_preference, agent_b.collaboration_preference)
                - 0.30 * regional_friction
            )
            fits.append(clamp(fit))
        return self.average(fits, default=1.0)

    def get_resource_allocation(self, project: ConstructionProject, agent_id: str) -> float:
        allocations = [
            engagement.resource_allocation
            for engagement in project.engagements
            if engagement.agent_id == agent_id and engagement.status == EngagementStatus.ACTIVE
        ]
        return self.average(allocations, default=0.0)

    def get_project_regional_friction(
        self,
        project: ConstructionProject,
        macro_environment: MacroEnvironment,
    ) -> float:
        row = macro_environment.regional_friction_matrix.get(project.region, {})
        values = [value for region, value in row.items() if region != project.region]
        return self.average(values, default=0.0)

    @staticmethod
    def average(values: Iterable[float], default: float) -> float:
        values = list(values)
        if not values:
            return default
        return sum(values) / len(values)
