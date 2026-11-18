from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.project import ConstructionProject


class SupplierAgent(BaseEnterpriseAgent):
    def consider_supply_order(
        self,
        project: ConstructionProject,
        *,
        contractor_id: str,
        required_resource: float,
        prior_fit: float,
    ):
        resource_fit = min(1.0, self.profile.available_resource() / max(required_resource, 1e-9))
        local_fit = 1.0 if self.profile.region == project.region else self.profile.cross_region_experience
        utility = (
            0.34 * self.profile.supply_reliability
            + 0.26 * self.profile.material_quality
            + 0.16 * self.profile.management_capability
            + 0.12 * prior_fit
            + 0.08 * resource_fit
            + 0.04 * local_fit
        )
        accepted = resource_fit >= 1.0 and utility >= 0.42
        return self.make_decision(
            "accept_supply_order" if accepted else "decline_supply_order",
            utility=utility,
            accepted=accepted,
            reason=(
                "Supplier accepted after checking capacity, reliability, quality, logistics, and contractor history."
                if accepted else
                "Supplier declined because capacity or delivery fit was below its commitment threshold."
            ),
            factors={
                "decision_process": "SupplierAgent.consider_supply_order",
                "contractor_id": contractor_id,
                "resource_fit": round(resource_fit, 3),
                "local_fit": round(local_fit, 3),
                "prior_fit": round(prior_fit, 3),
            },
            data={"offer_score": utility},
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        if macro_environment.material_price_index > 1.05:
            operation = (
                "adjust_inventory", "Adjusted inventory",
                "Adjusted stock and quotations against material-price movement and construction demand.",
            )
        else:
            operation = self.stable_pick(
                macro_environment.current_tick,
                [
                    ("seek_supply_contract", "Searched supply contracts", "Looked for supply packages and checked delivery capacity."),
                    ("monitor_material_prices", "Monitored material prices", "Updated quotations from material-price movements."),
                    ("improve_supply_reliability", "Improved supply reliability", "Reviewed logistics, backup sourcing, and delivery contingencies."),
                ],
            )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
