from typing import Iterable, Optional

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.engagement import ProjectEngagement
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.simulation.event_system import EventSystem


RESOURCE_HOLDING_STATUSES = {
    EngagementStatus.INVITED,
    EngagementStatus.BIDDING,
    EngagementStatus.ACTIVE,
}


class EngagementManager:
    def __init__(self, events: EventSystem) -> None:
        self.events = events
        self._counter = 0

    def find(
        self,
        project: ConstructionProject,
        agent_id: Optional[str] = None,
        role: Optional[str] = None,
        statuses: Optional[Iterable[EngagementStatus]] = None,
    ) -> Optional[ProjectEngagement]:
        status_set = set(statuses) if statuses else None
        for engagement in project.engagements:
            if agent_id and engagement.agent_id != agent_id:
                continue
            if role and engagement.role != role:
                continue
            if status_set and engagement.status not in status_set:
                continue
            return engagement
        return None

    def by_role(
        self,
        project: ConstructionProject,
        role: str,
        statuses: Optional[Iterable[EngagementStatus]] = None,
    ) -> list[ProjectEngagement]:
        status_set = set(statuses) if statuses else None
        return [
            engagement
            for engagement in project.engagements
            if engagement.role == role and (not status_set or engagement.status in status_set)
        ]

    def create_engagement(
        self,
        project: ConstructionProject,
        agent: EnterpriseAgentProfile,
        role: str,
        status: EngagementStatus,
        tick: int,
        resource_allocation: float,
        start_stage: Optional[ProjectStage] = None,
        contractual_obligation: bool = True,
        can_be_recalled: bool = False,
    ) -> ProjectEngagement:
        existing = self.find(project, agent_id=agent.agent_id, role=role)
        if existing and existing.status not in {EngagementStatus.RELEASED, EngagementStatus.TERMINATED}:
            return existing

        self._counter += 1
        engagement = ProjectEngagement(
            engagement_id=f"ENG{self._counter:06d}",
            project_id=project.project_id,
            agent_id=agent.agent_id,
            role=role,
            status=status,
            start_stage=start_stage or project.current_stage,
            joined_at_tick=tick,
            resource_allocation=resource_allocation,
            contractual_obligation=contractual_obligation,
            can_be_recalled=can_be_recalled,
        )
        project.engagements.append(engagement)
        if status in RESOURCE_HOLDING_STATUSES:
            agent.occupied_resource += resource_allocation
        self.events.record(
            tick,
            "agent_engaged",
            f"{role} {agent.agent_id} engaged as {status.value}",
            project=project,
            agent_id=agent.agent_id,
            data={"role": role, "status": status.value, "resource_allocation": resource_allocation},
        )
        return engagement

    def activate_engagement(
        self,
        engagement: ProjectEngagement,
        agent: EnterpriseAgentProfile,
        project: ConstructionProject,
        tick: int,
        resource_allocation: Optional[float] = None,
        reason: str = "",
    ) -> None:
        new_allocation = resource_allocation if resource_allocation is not None else engagement.resource_allocation
        if engagement.status not in RESOURCE_HOLDING_STATUSES:
            agent.occupied_resource += new_allocation
        elif new_allocation != engagement.resource_allocation:
            agent.occupied_resource += new_allocation - engagement.resource_allocation
        engagement.status = EngagementStatus.ACTIVE
        engagement.resource_allocation = new_allocation
        engagement.released_at_tick = None
        self.events.record(
            tick,
            "agent_recalled" if reason else "agent_engaged",
            reason or f"{engagement.role} {agent.agent_id} activated",
            project=project,
            agent_id=agent.agent_id,
            data={"role": engagement.role, "resource_allocation": new_allocation},
        )

    def set_standby(
        self,
        engagement: ProjectEngagement,
        agent: EnterpriseAgentProfile,
        project: ConstructionProject,
        tick: int,
        reason: str = "",
    ) -> None:
        if engagement.status in RESOURCE_HOLDING_STATUSES:
            agent.occupied_resource -= engagement.resource_allocation
        engagement.status = EngagementStatus.STANDBY
        engagement.resource_allocation = 0.0
        engagement.released_at_tick = tick
        engagement.can_be_recalled = True
        self.events.record(
            tick,
            "agent_standby",
            reason or f"{engagement.role} {agent.agent_id} moved to standby",
            project=project,
            agent_id=agent.agent_id,
            data={"role": engagement.role},
        )

    def release_engagement(
        self,
        engagement: ProjectEngagement,
        agent: EnterpriseAgentProfile,
        project: ConstructionProject,
        tick: int,
        reason: str = "",
    ) -> None:
        if engagement.status in RESOURCE_HOLDING_STATUSES:
            agent.occupied_resource -= engagement.resource_allocation
        engagement.status = EngagementStatus.RELEASED
        engagement.resource_allocation = 0.0
        engagement.actual_end_stage = project.current_stage
        engagement.released_at_tick = tick
        engagement.can_be_recalled = False
        self.events.record(
            tick,
            "agent_released",
            reason or f"{engagement.role} {agent.agent_id} released",
            project=project,
            agent_id=agent.agent_id,
            data={"role": engagement.role},
        )

    def terminate_engagement(
        self,
        engagement: ProjectEngagement,
        agent: EnterpriseAgentProfile,
        project: ConstructionProject,
        tick: int,
        reason: str = "",
    ) -> None:
        if engagement.status in RESOURCE_HOLDING_STATUSES:
            agent.occupied_resource -= engagement.resource_allocation
        engagement.status = EngagementStatus.TERMINATED
        engagement.resource_allocation = 0.0
        engagement.actual_end_stage = project.current_stage
        engagement.released_at_tick = tick
        self.events.record(
            tick,
            "agent_terminated",
            reason or f"{engagement.role} {agent.agent_id} terminated",
            project=project,
            agent_id=agent.agent_id,
            data={"role": engagement.role},
        )

    def recall_standby_agent(
        self,
        project: ConstructionProject,
        agent: EnterpriseAgentProfile,
        role: str,
        tick: int,
        resource_allocation: float,
        reason: str,
    ) -> Optional[ProjectEngagement]:
        engagement = self.find(
            project,
            agent_id=agent.agent_id,
            role=role,
            statuses=[EngagementStatus.STANDBY],
        )
        if not engagement or not engagement.can_be_recalled or not self.check_agent_availability(agent, resource_allocation):
            return None
        engagement.recall_reason = reason
        self.activate_engagement(engagement, agent, project, tick, resource_allocation, reason)
        return engagement

    def check_agent_availability(self, agent: EnterpriseAgentProfile, required_resource: float) -> bool:
        return agent.available_resource() + 1e-9 >= required_resource

    def normalize_agent_resources(self, agents: dict[str, EnterpriseAgentProfile]) -> None:
        for agent in agents.values():
            agent.occupied_resource = max(0.0, min(agent.total_resource_capacity, agent.occupied_resource))
