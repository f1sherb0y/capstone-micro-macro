from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject


class ArchitectAgent(BaseEnterpriseAgent):
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
        complexity_fit = self.clamp(1.15 - abs(project.technical_complexity - self.profile.technical_capability))
        utility = (
            0.32 * self.profile.design_capability
            + 0.19 * self.profile.technical_capability
            + 0.14 * self.profile.management_capability
            + 0.12 * resource_fit
            + 0.10 * region_fit
            + 0.08 * prior_fit
            + 0.05 * complexity_fit
            - 0.06 * policy.procedural_uncertainty
        )
        accepted = resource_fit >= 1.0 and utility >= 0.45
        return self.make_decision(
            "accept_design_appointment" if accepted else "decline_design_appointment",
            utility=utility,
            accepted=accepted,
            reason=(
                "Architect accepted after evaluating design fit, workload, region, and prior collaboration."
                if accepted else
                "Architect declined because capability, regional fit, or available design capacity was insufficient."
            ),
            factors={
                "decision_process": "ArchitectAgent.consider_appointment",
                "resource_fit": round(resource_fit, 3),
                "region_fit": round(region_fit, 3),
                "complexity_fit": round(complexity_fit, 3),
                "prior_fit": round(prior_fit, 3),
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        operation = self.stable_pick(
            macro_environment.current_tick,
            [
                ("seek_design_commission", "Searched design commissions", "Reviewed design commissions against current capacity and technical fit."),
                ("build_cross_region_reputation", "Built cross-region reputation", "Updated portfolio and cross-region collaboration evidence."),
                ("improve_design_capability", "Improved design capability", "Used free capacity to improve design and approval methods."),
                ("maintain_client_relationship", "Maintained client relationships", "Maintained owner and consultant relationships for future work."),
            ],
        )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
