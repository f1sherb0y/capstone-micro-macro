from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject


class ContractorAgent(BaseEnterpriseAgent):
    def consider_tender(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        attractiveness: float,
    ):
        regional_friction = macro_environment.regional_friction_matrix.get(self.profile.region, {}).get(
            project.region,
            macro_environment.regional_friction_matrix.get(project.region, {}).get(self.profile.region, 0.0),
        )
        local_experience = 1.0 if self.profile.region == project.region else self.profile.cross_region_experience
        qualification_fit = min(
            1.0,
            self.profile.qualification_level
            + (policy.cross_region_qualification_recognition * 0.25 if self.profile.region != project.region else 0.20),
        )
        resource_fit = min(1.0, self.profile.available_resource() / 0.35)
        delivery_strength = (
            0.32 * self.profile.construction_capability
            + 0.22 * self.profile.management_capability
            + 0.18 * self.profile.financial_capacity
            + 0.14 * self.profile.quality_management_capability
            + 0.14 * self.profile.safety_management_capability
        )
        risk_level = self.clamp(
            0.18 * project.technical_complexity
            + 0.18 * project.performance.project_failure_risk
            + 0.16 * policy.procedural_uncertainty
            + 0.14 * policy.compliance_cost
            + 0.14 * regional_friction
            + 0.10 * max(0.0, 1.0 - resource_fit)
            + 0.10 * max(0.0, 1.0 - local_experience)
        )
        bid_probability = self.clamp(
            0.23 * attractiveness
            + 0.18 * self.profile.risk_preference
            + 0.17 * resource_fit
            + 0.16 * delivery_strength
            + 0.11 * qualification_fit
            + 0.08 * local_experience
            + 0.07 * policy.cross_region_qualification_recognition
            - 0.18 * risk_level
            - 0.08 * regional_friction,
            0.03,
            0.96,
        )
        market_cost = project.initial_budget * (
            0.80
            + 0.08 * project.technical_complexity
            + 0.05 * max(0.0, macro_environment.material_price_index - 1.0)
            + 0.04 * max(0.0, macro_environment.labor_price_index - 1.0)
            + 0.03 * policy.compliance_cost
            + 0.03 * regional_friction
        )
        target_margin = self.clamp(
            0.055
            + 0.055 * self.profile.risk_preference
            + 0.035 * risk_level
            - 0.025 * attractiveness
            + self.rng.uniform(-0.012, 0.012),
            0.025,
            0.20,
        )
        bid_price = market_cost * (1.0 + target_margin)
        expected_profit = self.clamp((bid_price - market_cost) / max(bid_price, 1.0), 0.0, 0.28)
        accepted = self.rng.random() < bid_probability
        decline_reason = self._decline_reason(
            resource_fit, qualification_fit, expected_profit, risk_level, regional_friction
        )
        factors = {
            "decision_process": "ContractorAgent.consider_tender",
            "tender_attractiveness": round(attractiveness, 3),
            "resource_fit": round(resource_fit, 3),
            "delivery_strength": round(delivery_strength, 3),
            "qualification_fit": round(qualification_fit, 3),
            "local_experience": round(local_experience, 3),
            "regional_friction": round(regional_friction, 3),
            "policy_compliance_cost": round(policy.compliance_cost, 3),
            "market_material_index": round(macro_environment.material_price_index, 3),
            "market_labor_index": round(macro_environment.labor_price_index, 3),
        }
        return self.make_decision(
            "submit_bid" if accepted else "decline_bid",
            utility=bid_probability,
            probability=bid_probability,
            accepted=accepted,
            reason=(
                "Contractor chose to bid after evaluating margin, delivery capacity, qualification, and risk."
                if accepted else decline_reason
            ),
            factors=factors,
            data={
                "bid_probability": bid_probability,
                "bid_price": bid_price,
                "expected_profit": expected_profit,
                "risk_level": risk_level,
                "decline_reason": decline_reason,
            },
        )

    def select_supplier(self, offers: list[tuple[EnterpriseAgentProfile, object]]):
        accepted = [(supplier, decision) for supplier, decision in offers if getattr(decision, "accepted", False)]
        if not accepted:
            return self.make_decision(
                "select_supplier", utility=0.0, probability=0.0, accepted=False,
                reason="No supplier independently accepted the order under the required delivery conditions.",
            )
        selected, supplier_decision = max(
            accepted,
            key=lambda item: (getattr(item[1], "utility", 0.0), item[0].supply_reliability, item[0].agent_id),
        )
        return self.make_decision(
            "select_supplier",
            utility=getattr(supplier_decision, "utility", 0.5),
            probability=1.0,
            accepted=True,
            reason=f"Contractor selected {selected.name} from suppliers that accepted the delivery order.",
            factors={
                "decision_process": "ContractorAgent.select_supplier",
                "candidate_count": len(offers),
                "accepted_candidate_count": len(accepted),
            },
            data={
                "selected_supplier_id": selected.agent_id,
                "accepted_supplier_ids": [supplier.agent_id for supplier, _decision in accepted],
            },
        )

    def decide_contract_terms(self, project: ConstructionProject, preferred_bid: dict):
        expected_profit = float(preferred_bid.get("expected_profit", 0.0) or 0.0)
        risk_level = float(preferred_bid.get("risk_level", 0.5) or 0.5)
        cashflow_fit = 0.55 * self.profile.financial_capacity + 0.45 * self.profile.available_resource()
        utility = 0.45 * expected_profit / 0.20 + 0.35 * cashflow_fit + 0.20 * (1.0 - risk_level)
        accepted = utility >= 0.42
        return self.make_decision(
            "accept_terms" if accepted else "request_revision",
            utility=utility,
            accepted=accepted,
            reason=(
                "Contractor accepted the proposed contract terms after reviewing margin, risk, and cashflow capacity."
                if accepted else
                "Contractor requested revised terms because margin, risk allocation, or cashflow capacity was inadequate."
            ),
            factors={
                "decision_process": "ContractorAgent.decide_contract_terms",
                "expected_profit": round(expected_profit, 4),
                "risk_level": round(risk_level, 4),
                "cashflow_fit": round(cashflow_fit, 4),
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        free_resource = self.profile.available_resource() / max(self.profile.total_resource_capacity, 1e-9)
        if free_resource > 0.5 and self.profile.risk_preference >= 0.35:
            operation = (
                "scan_tender_opportunities", "Scanned tender opportunities",
                "Ranked tenders by expected margin, qualification fit, workload, and regional risk.",
            )
        elif macro_environment.material_price_index > 1.05:
            operation = (
                "adjust_bid_strategy", "Adjusted bid strategy",
                "Updated bid allowances for material inflation, supply risk, and recent outcomes.",
            )
        else:
            operation = self.stable_pick(
                macro_environment.current_tick,
                [
                    ("evaluate_region_entry", "Evaluated regional entry", "Checked qualification and local partner availability in nearby markets."),
                    ("seek_joint_venture_partner", "Searched JV partners", "Reviewed local partners for cross-region delivery risk sharing."),
                    ("maintain_supplier_relationship", "Maintained supplier network", "Checked material availability and supplier reliability for future bids."),
                ],
            )
        return self.make_decision(
            operation[0], utility=free_resource, accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )

    def _decline_reason(
        self,
        resource_fit: float,
        qualification_fit: float,
        expected_profit: float,
        risk_level: float,
        regional_friction: float,
    ) -> str:
        reasons = [
            (resource_fit, "insufficient available delivery capacity"),
            (qualification_fit, "qualification fit below the contractor's entry threshold"),
            (expected_profit / 0.08, "expected margin below the contractor's target"),
            (1.0 - risk_level, "delivery risk above the contractor's tolerance"),
            (1.0 - regional_friction, "regional friction too high for the current strategy"),
        ]
        return min(reasons, key=lambda item: item[0])[1]
