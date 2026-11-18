from typing import Optional

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.models.action import AgentAction, find_forbidden_action_mutation_keys
from gba_construction_sim.backend.models.engagement import ProjectEngagement
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.stage_rule import StageRule
from gba_construction_sim.backend.simulation.event_system import EventSystem


class ActionValidator:
    def __init__(self, events: EventSystem) -> None:
        self.events = events

    def validate(
        self,
        action: AgentAction,
        project: ConstructionProject,
        engagement: Optional[ProjectEngagement],
        stage_rule: StageRule,
        policy: Optional[PolicyRegime] = None,
        tick: int = 0,
    ) -> bool:
        if action.project_id != project.project_id:
            return self._invalid(action, project, tick, "action project does not match current project")

        forbidden_keys = find_forbidden_action_mutation_keys(action.data)
        if forbidden_keys:
            return self._invalid(
                action,
                project,
                tick,
                f"action data attempts to mutate simulation state: {sorted(forbidden_keys)}",
            )

        if not engagement:
            return self._invalid(action, project, tick, "agent has no project engagement")

        allowed = stage_rule.allowed_actions.get(engagement.role, [])
        if action.action_type not in allowed:
            return self._invalid(action, project, tick, "action is not allowed in current stage for role")

        allowed_statuses = {EngagementStatus.ACTIVE}
        if engagement.role == "Contractor" and action.action_type in {"evaluate_tender", "decide_bid", "submit_bid", "decline_bid"}:
            allowed_statuses = {EngagementStatus.INVITED, EngagementStatus.BIDDING, EngagementStatus.ACTIVE}

        if engagement.status not in allowed_statuses:
            return self._invalid(action, project, tick, "engagement status cannot execute action")

        if engagement.resource_allocation <= 0.0 and engagement.status in allowed_statuses:
            return self._invalid(action, project, tick, "engagement has no allocated resource for action")

        if engagement.role == "Contractor" and not self._validate_contractor_procurement(action, project, tick):
            return False

        if engagement.role == "Supplier" and project.current_stage == ProjectStage.CONSTRUCTION:
            if action.agent_id not in set(project.selected_supplier_ids):
                return self._invalid(action, project, tick, "supplier was not selected for this project")

        if policy and policy.scope_breadth <= 0:
            return self._invalid(action, project, tick, "policy scope does not allow action")

        return True

    def _validate_contractor_procurement(
        self,
        action: AgentAction,
        project: ConstructionProject,
        tick: int,
    ) -> bool:
        if project.current_stage == ProjectStage.TENDERING:
            invited_ids = set(project.flags.get("invited_contractor_ids") or [])
            if invited_ids and action.agent_id not in invited_ids:
                return self._invalid(action, project, tick, "contractor was not invited to this tender")

        if project.current_stage == ProjectStage.BID_EVALUATION:
            bidder_ids = {bid.get("contractor_id") for bid in project.bids}
            if action.agent_id not in bidder_ids:
                return self._invalid(action, project, tick, "contractor did not submit a valid bid")

        if project.current_stage in {ProjectStage.CONTRACT_AWARD, ProjectStage.CONSTRUCTION}:
            if action.agent_id != project.selected_contractor_id:
                return self._invalid(action, project, tick, "contractor is not the selected contractor")
            if not project.contract_sum:
                return self._invalid(action, project, tick, "construction contract has not been priced")

        return True

    def _invalid(self, action: AgentAction, project: ConstructionProject, tick: int, reason: str) -> bool:
        self.events.record(
            tick,
            "invalid_action",
            reason,
            project=project,
            agent_id=action.agent_id,
            data={"action": action.dict(), "reason": reason},
        )
        return False
