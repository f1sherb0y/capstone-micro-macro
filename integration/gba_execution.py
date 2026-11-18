"""Read-only contract views feeding the existing GBA state equations."""
from __future__ import annotations

from copy import deepcopy

from gba_construction_sim.backend.core.enums import EngagementStatus
from gba_construction_sim.backend.models.project_performance import ProjectPerformanceState
from gba_construction_sim.backend.simulation.project_state_update_engine import ProjectStateUpdateEngine


CAPABILITIES = ("technical_capability", "management_capability", "design_capability", "cost_estimation_capability",
                "construction_capability", "safety_management_capability", "quality_management_capability",
                "policy_adaptability", "supervision_capability", "supply_reliability", "material_quality")


def execution_profile(contract, agents):
    # This profile is local to a calculation. It is never registered as a new
    # enterprise, counted in metrics or given its own resources.
    profile = agents[contract["lead_id"]].model_copy(deep=True)
    for field in CAPABILITIES:
        setattr(profile, field, sum(getattr(agents[key], field) * share for key, share in contract["work_shares"].items()))
    profile.financial_capacity = min(agents[key].financial_capacity for key in contract["members"])
    profile.qualification_level = min(agents[key].qualification_level for key in contract["members"])
    return profile


class ContractStateUpdater(ProjectStateUpdateEngine):
    def __init__(self, native, dataset):
        super().__init__(native.events, native.rng, native.collaboration_prior)
        self.dataset = dataset

    def update_design_state(self, project, agents):
        view = dict(agents)
        for contract in project.flags.get("package_contracts", {}).values():
            if contract["kind"] in {"design", "cost_consulting"}:
                view[contract["lead_id"]] = execution_profile(contract, agents)
        super().update_design_state(project, view)

    def update_construction_state(self, project, agents, policy, macro_environment, tick):
        contracts = [c for c in project.flags.get("package_contracts", {}).values() if c["kind"] == "construction"]
        if not contracts:
            raise ValueError("Construction requires committed package contracts")
        records = project.flags.setdefault("package_execution", {})
        external_delay = max(0, project.performance.delay_days - project.flags.get("package_delay_posted", project.performance.delay_days))
        by_id = {p.package_id: p for p in self.dataset.packages}
        observations = []
        for contract in contracts:
            key = contract["package_id"]
            part = project.model_copy(deep=True)
            part.selected_contractor_id, part.contract_sum = contract["lead_id"], contract["price"]
            supply = [c for c in project.flags["package_contracts"].values()
                      if c["kind"] == "supply" and c["parent_package_id"] == key]
            part.selected_supplier_ids = sorted({m for c in supply for m in c["members"]})
            previous = records.get(key)
            if previous:
                part.performance = ProjectPerformanceState(**previous["performance"])
                part.performance.delay_days += external_delay
                part.flags.update(previous["process_flags"])
            else:
                part.performance.actual_cost = 0
                part.performance.elapsed_time = 0
                part.performance.actual_progress = 0
                part.flags["last_costed_progress"] = 0
            allocations = contract["resource_commitments"]
            active = {e.agent_id: e for e in project.engagements if e.role == "Contractor" and e.status == EngagementStatus.ACTIVE}
            if not set(allocations).issubset(active):
                raise ValueError("A contracted member is no longer actively engaged")
            # The ledger owns real member allocations. The legacy progress
            # equation consumes their combined allocation for this package.
            part.engagements = [e for e in part.engagements if e.role != "Contractor"]
            representative = active[contract["lead_id"]].model_copy(deep=True)
            representative.resource_allocation = sum(allocations.values())
            part.engagements.append(representative)
            view = dict(agents)
            view[contract["lead_id"]] = execution_profile(contract, agents)
            start_events = len(self.events.events)
            if part.performance.actual_progress < 1:
                super().update_construction_state(part, view, policy, macro_environment, tick)
            for event in self.events.events[start_events:]:
                event.data["package_id"] = key
                event.data["execution_members"] = contract["members"]
                project.event_log.append(event.dict())
            process_flags = {k: v for k, v in part.flags.items() if k.startswith("last_")}
            records[key] = {"performance": part.performance.dict(), "process_flags": process_flags,
                            "member_resources": allocations, "work_shares": contract["work_shares"]}
            observations.append((by_id[key].budget, part.performance))
        total_weight = sum(weight for weight, _ in observations)
        for field in ("actual_progress", "planned_progress", "construction_quality", "overall_quality", "defect_rate",
                      "detected_defect_rate", "material_availability", "material_quality", "supply_delay_risk", "coordination_efficiency",
                      "inspection_pass_probability"):
            setattr(project.performance, field, sum(weight * getattr(performance, field) for weight, performance in observations) / total_weight)
        for field in ("safety_risk", "compliance_risk", "claim_risk", "variation_risk", "dispute_risk", "delay_days", "elapsed_time"):
            setattr(project.performance, field, max(getattr(performance, field) for _, performance in observations))
        service_cost = sum(c["price"] for c in project.flags["package_contracts"].values()
                           if c["kind"] in {"design", "cost_consulting"} and c["cost_inclusion"] == "owner_additional")
        prior_construction_cost = project.flags.get("construction_cost_posted", 0.0)
        construction_cost = sum(performance.actual_cost for _, performance in observations)
        # Preserve approvals/other costs already posted by GBA; add only this
        # tick's construction delta. Included supply is not posted a second time.
        project.performance.actual_cost += construction_cost - prior_construction_cost
        project.flags["construction_cost_posted"] = construction_cost
        project.flags["package_delay_posted"] = project.performance.delay_days
        project.performance.progress_deviation = project.performance.actual_progress - project.performance.planned_progress
        reference = project.contract_sum + service_cost
        project.performance.cost_overrun_ratio = (project.performance.actual_cost - reference) / max(reference, 1)
