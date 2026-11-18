from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager
from gba_construction_sim.backend.simulation.event_system import EventSystem


def test_engagement_release_and_recall_resource_accounting():
    events = EventSystem()
    manager = EngagementManager(events)
    agent = EnterpriseAgentProfile(agent_id="A1", name="Architect", role="Architect", region="Shenzhen", enterprise_type="consultant")
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)

    engagement = manager.create_engagement(project, agent, "Architect", EngagementStatus.ACTIVE, 1, 0.5)
    assert agent.occupied_resource == 0.5

    manager.set_standby(engagement, agent, project, 2)
    assert engagement.status == EngagementStatus.STANDBY
    assert agent.occupied_resource == 0.0

    recalled = manager.recall_standby_agent(project, agent, "Architect", 3, 0.2, "variation")
    assert recalled is engagement
    assert engagement.status == EngagementStatus.ACTIVE
    assert agent.occupied_resource == 0.2

    project.current_stage = ProjectStage.FINAL_ACCOUNT
    manager.release_engagement(engagement, agent, project, 4)
    assert engagement.status == EngagementStatus.RELEASED
    assert agent.occupied_resource == 0.0
