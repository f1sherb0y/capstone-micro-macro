from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject


class GovernmentAgent(BaseEnterpriseAgent):
    def consider_review_assignment(self, project: ConstructionProject, *, required_resource: float):
        resource_fit = min(1.0, self.profile.available_resource() / max(required_resource, 1e-9))
        jurisdiction_fit = 1.0 if self.profile.region == project.region else 0.45 + 0.35 * self.profile.cross_region_experience
        utility = (
            0.34 * jurisdiction_fit
            + 0.24 * self.profile.policy_adaptability
            + 0.20 * self.profile.management_capability
            + 0.12 * self.profile.supervision_capability
            + 0.10 * resource_fit
        )
        accepted = resource_fit >= 1.0 and utility >= 0.40
        return self.make_decision(
            "accept_regulatory_review" if accepted else "defer_regulatory_review",
            utility=utility,
            accepted=accepted,
            reason=(
                "Regulator accepted the review within its jurisdiction and available service capacity."
                if accepted else
                "Regulator deferred the review because jurisdiction or service capacity was insufficient."
            ),
            factors={
                "decision_process": "GovernmentAgent.consider_review_assignment",
                "resource_fit": round(resource_fit, 3),
                "jurisdiction_fit": round(jurisdiction_fit, 3),
            },
        )

    def decide_approval(self, project: ConstructionProject, policy: PolicyRegime):
        base_probability = project.performance.inspection_pass_probability
        review_probability = self.clamp(
            0.72 * base_probability
            + 0.12 * self.profile.policy_adaptability
            + 0.08 * self.profile.management_capability
            + 0.08 * policy.information_transparency
            - 0.08 * policy.procedural_uncertainty
        )
        approved = review_probability >= 0.62 or self.rng.random() < review_probability
        return self.make_decision(
            "approve" if approved else "request_revision",
            utility=review_probability,
            probability=review_probability,
            accepted=approved,
            reason=(
                "Regulator approved the submission after reviewing design quality, information, and policy requirements."
                if approved else
                "Regulator requested revision because the submission did not meet its approval threshold."
            ),
            factors={
                "decision_process": "GovernmentAgent.decide_approval",
                "inspection_pass_probability": round(base_probability, 3),
                "design_quality": round(project.performance.design_quality, 3),
                "information_quality": round(project.performance.information_quality, 3),
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        operation = self.stable_pick(
            macro_environment.current_tick,
            [
                ("publish_guidelines", "Published guidance", f"Prepared policy and compliance guidance in {self.profile.region}."),
                ("monitor_compliance", "Monitored compliance signals", "Monitored approval, safety, and procurement compliance signals."),
                ("adjust_regulatory_focus", "Adjusted regulatory focus", "Adjusted inspection focus using market and project risk."),
                ("review_policy_feedback", "Reviewed policy feedback", "Reviewed enterprise feedback on transparency and compliance burden."),
            ],
        )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
