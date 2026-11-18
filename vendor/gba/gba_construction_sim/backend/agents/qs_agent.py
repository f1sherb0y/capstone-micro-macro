from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject


class QSAgent(BaseEnterpriseAgent):
    def consider_appointment(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        *,
        required_resource: float,
        prior_fit: float,
    ):
        resource_fit = min(1.0, self.profile.available_resource() / max(required_resource, 1e-9))
        region_fit = 1.0 if self.profile.region == project.region else self.profile.cross_region_experience
        market_volatility = abs(macro_environment.material_price_index - 1.0) + abs(macro_environment.labor_price_index - 1.0)
        utility = (
            0.38 * self.profile.cost_estimation_capability
            + 0.18 * self.profile.management_capability
            + 0.14 * resource_fit
            + 0.12 * region_fit
            + 0.10 * prior_fit
            + 0.08 * self.profile.policy_adaptability
            - 0.05 * market_volatility
            - 0.04 * policy.procedural_uncertainty
        )
        accepted = resource_fit >= 1.0 and utility >= 0.43
        return self.make_decision(
            "accept_qs_appointment" if accepted else "decline_qs_appointment",
            utility=utility,
            accepted=accepted,
            reason=(
                "QS accepted after evaluating estimating fit, workload, market volatility, and regional experience."
                if accepted else
                "QS declined because workload or cost-management fit did not meet its acceptance threshold."
            ),
            factors={
                "decision_process": "QSAgent.consider_appointment",
                "resource_fit": round(resource_fit, 3),
                "region_fit": round(region_fit, 3),
                "market_volatility": round(market_volatility, 3),
                "prior_fit": round(prior_fit, 3),
            },
        )

    def evaluate_bid(
        self,
        bid: dict,
        contractor: EnterpriseAgentProfile,
        project: ConstructionProject,
        policy: PolicyRegime,
        prior_fit: float,
    ):
        price_score = max(0.0, 1.0 - (bid["bid_price"] / max(project.initial_budget, 1.0) - 0.9))
        region_penalty = 0.10 if contractor.region != project.region else 0.0
        delivery_risk_penalty = 0.10 * float(bid.get("risk_level", 0.5))
        score = (
            0.26 * price_score
            + 0.22 * contractor.construction_capability
            + 0.14 * contractor.quality_management_capability
            + 0.14 * contractor.safety_management_capability
            + 0.10 * contractor.financial_capacity
            + 0.07 * prior_fit
            + 0.07 * policy.cross_region_qualification_recognition
            - region_penalty
            - delivery_risk_penalty
        )
        return self.make_decision(
            "evaluate_bid",
            utility=score,
            probability=1.0,
            accepted=True,
            reason="QS independently normalized price, capability, safety, quality, finance, and delivery risk.",
            factors={
                "decision_process": "QSAgent.evaluate_bid",
                "price_score": round(price_score, 4),
                "prior_fit": round(prior_fit, 4),
                "region_penalty": round(region_penalty, 4),
                "delivery_risk_penalty": round(delivery_risk_penalty, 4),
            },
            data={"evaluation_score": score},
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        operation = self.stable_pick(
            macro_environment.current_tick,
            [
                ("update_cost_database", "Updated cost database", "Updated tender-price benchmarks and regional material indices."),
                ("seek_consulting_work", "Searched consulting work", "Screened consulting commissions and procurement opportunities."),
                ("review_cost_market", "Reviewed cost market", "Reviewed market rates, claims, and procurement risk signals."),
                ("improve_cost_estimation", "Improved cost estimation", "Refined estimating parameters using recent project evidence."),
            ],
        )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
