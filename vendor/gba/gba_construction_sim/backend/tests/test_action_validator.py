from gba_construction_sim.backend.core.enums import EngagementStatus
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.simulation.action_validator import ActionValidator
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.simulation.stage_rule_registry import StageRuleRegistry


def test_invalid_action_is_logged():
    events = EventSystem()
    manager = EngagementManager(events)
    validator = ActionValidator(events)
    rules = StageRuleRegistry()
    agent = EnterpriseAgentProfile(agent_id="A1", name="Architect", role="Architect", region="Shenzhen", enterprise_type="consultant")
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)
    project.current_stage = rules.get(project.current_stage).next_stage
    engagement = manager.create_engagement(project, agent, "Architect", EngagementStatus.ACTIVE, 1, 0.5)

    action = AgentAction(action_type="execute_work", project_id=project.project_id, agent_id=agent.agent_id)
    ok = validator.validate(action, project, engagement, rules.get(project.current_stage), tick=1)

    assert not ok
    assert events.events[-1].event_type == "invalid_action"


def test_action_data_cannot_mutate_project_or_engagement_state():
    events = EventSystem()
    manager = EngagementManager(events)
    validator = ActionValidator(events)
    rules = StageRuleRegistry()
    agent = EnterpriseAgentProfile(
        agent_id="A1",
        name="Architect",
        role="Architect",
        region="Shenzhen",
        enterprise_type="consultant",
    )
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)
    project.current_stage = rules.get(project.current_stage).next_stage
    engagement = manager.create_engagement(project, agent, "Architect", EngagementStatus.ACTIVE, 1, 0.5)

    ok_action = AgentAction(
        action_type="prepare_concept_design",
        project_id=project.project_id,
        agent_id=agent.agent_id,
        data={"design_option": "compact podium", "coordination_notes": ["QS cost check needed"]},
    )
    assert validator.validate(ok_action, project, engagement, rules.get(project.current_stage), tick=1)

    bad_action = AgentAction(
        action_type="prepare_concept_design",
        project_id=project.project_id,
        agent_id=agent.agent_id,
        data={"recommendation": {"current_stage": "construction"}, "performance": {"actual_progress": 1.0}},
    )
    assert not validator.validate(bad_action, project, engagement, rules.get(project.current_stage), tick=2)
    assert events.events[-1].event_type == "invalid_action"
    assert "mutate simulation state" in events.events[-1].data["reason"]
    assert "current_stage" in events.events[-1].data["reason"]
    assert "performance" in events.events[-1].data["reason"]


def test_bid_evaluation_rejects_contractor_without_submitted_bid():
    events = EventSystem()
    manager = EngagementManager(events)
    validator = ActionValidator(events)
    rules = StageRuleRegistry()
    contractor = EnterpriseAgentProfile(
        agent_id="C1",
        name="Contractor",
        role="Contractor",
        region="Shenzhen",
        enterprise_type="contractor",
    )
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    engagement = manager.create_engagement(project, contractor, "Contractor", EngagementStatus.ACTIVE, 1, 0.2)

    action = AgentAction(action_type="provide_clarification", project_id=project.project_id, agent_id=contractor.agent_id)
    ok = validator.validate(action, project, engagement, rules.get(project.current_stage), tick=1)

    assert not ok
    assert events.events[-1].event_type == "invalid_action"
    assert events.events[-1].data["reason"] == "contractor did not submit a valid bid"

    project.bids.append({"contractor_id": contractor.agent_id, "bid_price": 950_000})
    ok = validator.validate(action, project, engagement, rules.get(project.current_stage), tick=2)

    assert ok


def test_contract_award_rejects_non_selected_contractor():
    events = EventSystem()
    manager = EngagementManager(events)
    validator = ActionValidator(events)
    rules = StageRuleRegistry()
    selected = EnterpriseAgentProfile(
        agent_id="C1",
        name="Selected Contractor",
        role="Contractor",
        region="Shenzhen",
        enterprise_type="contractor",
    )
    other = EnterpriseAgentProfile(
        agent_id="C2",
        name="Other Contractor",
        role="Contractor",
        region="Guangzhou",
        enterprise_type="contractor",
    )
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.selected_contractor_id = selected.agent_id
    project.contract_sum = 980_000
    selected_engagement = manager.create_engagement(project, selected, "Contractor", EngagementStatus.ACTIVE, 1, 0.8)
    other_engagement = manager.create_engagement(project, other, "Contractor", EngagementStatus.ACTIVE, 1, 0.8)

    selected_action = AgentAction(action_type="accept_contract", project_id=project.project_id, agent_id=selected.agent_id)
    other_action = AgentAction(action_type="accept_contract", project_id=project.project_id, agent_id=other.agent_id)

    assert validator.validate(selected_action, project, selected_engagement, rules.get(project.current_stage), tick=1)
    assert not validator.validate(other_action, project, other_engagement, rules.get(project.current_stage), tick=1)
    assert events.events[-1].data["reason"] == "contractor is not the selected contractor"


def test_construction_rejects_unselected_supplier():
    events = EventSystem()
    manager = EngagementManager(events)
    validator = ActionValidator(events)
    rules = StageRuleRegistry()
    supplier = EnterpriseAgentProfile(
        agent_id="S1",
        name="Supplier",
        role="Supplier",
        region="Shenzhen",
        enterprise_type="supplier",
    )
    project = ConstructionProject(project_id="P1", name="Project", region="Shenzhen", owner_id="O1", initial_budget=1_000_000)
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    project.current_stage = rules.get(project.current_stage).next_stage
    engagement = manager.create_engagement(project, supplier, "Supplier", EngagementStatus.ACTIVE, 1, 0.35)

    action = AgentAction(action_type="deliver_materials", project_id=project.project_id, agent_id=supplier.agent_id)
    ok = validator.validate(action, project, engagement, rules.get(project.current_stage), tick=1)

    assert not ok
    assert events.events[-1].data["reason"] == "supplier was not selected for this project"

    project.selected_supplier_ids = [supplier.agent_id]
    ok = validator.validate(action, project, engagement, rules.get(project.current_stage), tick=2)

    assert ok
