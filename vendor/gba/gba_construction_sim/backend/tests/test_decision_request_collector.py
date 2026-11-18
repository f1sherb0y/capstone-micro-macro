from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority
from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler
from gba_construction_sim.backend.simulation.stage_rule_registry import StageRuleRegistry


class NoopDecisionProvider:
    def decide(self, agent, context):
        raise AssertionError("collector test should not call provider")


def test_collector_builds_standard_context_package():
    agent = EnterpriseAgentProfile(
        agent_id="A-COLLECTOR",
        name="Collector Test Contractor",
        role="Contractor",
        region="Shenzhen",
        enterprise_type="contractor",
    )
    project = ConstructionProject(
        project_id="P-COLLECTOR",
        name="Collector Test Project",
        project_type="building",
        region="Shenzhen",
        owner_id="O001",
        initial_budget=100000000,
    )
    stage_rule = StageRuleRegistry().get(project.current_stage)
    collector = DecisionRequestCollector()
    scheduler = EnterpriseDecisionScheduler(NoopDecisionProvider())

    request = collector.build_request(
        scheduler,
        agent,
        {
            "tick": 3,
            "project": project,
            "stage_rule": stage_rule,
            "allowed_actions": ["evaluate_tender"],
            "regional_friction": 0.2,
        },
        decision_type="tender_decision",
        priority=DecisionPriority.P0_STAGE_CRITICAL,
        project_id=project.project_id,
        risk_inputs={"risk_level": 0.4},
    )

    assert request.request_id == "tick3-P-COLLECTOR-A-COLLECTOR-tender_decision"
    assert request.context["agent_profile"]["agent_id"] == agent.agent_id
    assert "agent_memory" in request.context
    assert "agent_belief" in request.context
    assert "agent_strategy" in request.context
    assert request.context["project_snapshot"]["project_id"] == project.project_id
    assert request.context["stage_rule_snapshot"]["stage"] == project.current_stage.value
    assert request.context["allowed_actions"] == ["evaluate_tender"]
    assert request.context["risk_inputs"]["risk_level"] == 0.4
