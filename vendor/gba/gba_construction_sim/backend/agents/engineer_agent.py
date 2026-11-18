from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.project import ConstructionProject


class EngineerAgent(BaseEnterpriseAgent):
    def consider_appointment(self, project: ConstructionProject, *, required_resource: float, prior_fit: float):
        resource_fit = min(1.0, self.profile.available_resource() / max(required_resource, 1e-9))
        technical_fit = 0.55 * self.profile.technical_capability + 0.25 * self.profile.supervision_capability
        region_fit = 1.0 if self.profile.region == project.region else self.profile.cross_region_experience
        utility = technical_fit + 0.10 * region_fit + 0.10 * prior_fit - 0.10 * project.technical_complexity
        accepted = resource_fit >= 1.0 and utility >= 0.42
        return self.make_decision(
            "accept_engineering_appointment" if accepted else "decline_engineering_appointment",
            utility=utility,
            accepted=accepted,
            reason="Engineer independently evaluated technical scope, capacity, regional fit, and delivery risk.",
            factors={
                "decision_process": "EngineerAgent.consider_appointment",
                "resource_fit": round(resource_fit, 3),
                "technical_fit": round(technical_fit, 3),
                "region_fit": round(region_fit, 3),
                "prior_fit": round(prior_fit, 3),
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        operation = self.stable_pick(
            macro_environment.current_tick,
            [
                ("review_technical_market", "Reviewed technical market", "Reviewed technical demand and specialist project opportunities."),
                ("improve_engineering_capability", "Improved engineering capability", "Updated design-review and constructability methods."),
                ("maintain_professional_qualifications", "Maintained qualifications", "Maintained professional qualifications and regional compliance knowledge."),
            ],
        )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
