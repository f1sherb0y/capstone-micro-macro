from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.project_performance import ProjectPerformanceState
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.storage.agent_database import agent_database


def _project(owner_id: str = "OTEST_COG_EVENT"):
    return ConstructionProject(
        project_id="PTEST_COG_EVENT",
        name="Cognitive Event Project",
        project_type="public_housing",
        region="Shenzhen",
        owner_id=owner_id,
        initial_budget=100_000_000,
        current_stage=ProjectStage.TENDERING,
        performance=ProjectPerformanceState(planned_duration=24),
    )


def test_event_system_writes_tender_event_to_agent_memory_and_belief():
    contractor_id = "CTEST_COG_EVENT_BID"
    project = _project()
    event_system = EventSystem()

    event = event_system.record(
        tick=12,
        event_type="bid_submitted",
        description="Contractor submitted a tender bid",
        project=project,
        agent_id=contractor_id,
        data={
            "contractor_id": contractor_id,
            "bid_price": 98_500_000,
            "expected_profit": 0.12,
            "risk_level": 0.31,
        },
    )

    assert "cognition_error" not in event.data
    memory = agent_database.get_agent_memory(contractor_id, limit=5, memory_type="tender_memory")
    assert any(item["event_type"] == "bid_submitted" and "bid_price=98500000" in item["content"] for item in memory)
    beliefs = agent_database.get_agent_beliefs(contractor_id)
    assert any(item["belief_type"] == "competition_belief" for item in beliefs)


def test_event_system_writes_owner_project_opportunity_memory():
    owner_id = "OTEST_COG_EVENT_OWNER"
    project = _project(owner_id)
    project.current_stage = ProjectStage.INITIATION
    event_system = EventSystem()

    event = event_system.record(
        tick=4,
        event_type="project_opportunity_initiated",
        description="Owner evaluated market demand and initiated a new project",
        project=project,
        agent_id=owner_id,
        data={
            "owner_id": owner_id,
            "region": "Shenzhen",
            "budget": 100_000_000,
            "initiation_probability": 0.74,
        },
    )

    assert "cognition_error" not in event.data
    memory = agent_database.get_agent_memory(owner_id, limit=5, memory_type="market_memory")
    assert any(item["event_type"] == "project_opportunity_initiated" for item in memory)
    beliefs = agent_database.get_agent_beliefs(owner_id)
    assert any(
        item["belief_type"] == "market_opportunity_belief" and item["target_id"] == project.project_id
        for item in beliefs
    )


def test_interaction_session_event_writes_memory_for_all_participants():
    owner_id = "OTEST_COG_SESSION_OWNER"
    contractor_id = "CTEST_COG_SESSION_CONTRACTOR"
    qs_id = "QTEST_COG_SESSION_QS"
    project = _project(owner_id)
    project.current_stage = ProjectStage.CONTRACT_AWARD
    event_system = EventSystem()

    event = event_system.record(
        tick=15,
        event_type="contract_negotiation_session_started",
        description="Controlled contract negotiation session opened before contract signing",
        project=project,
        agent_id=owner_id,
        data={
            "session_id": "PTEST_COG_EVENT:contract_negotiation",
            "session_type": "contract_negotiation",
            "session_participants": [owner_id, contractor_id, qs_id],
            "owner_id": owner_id,
            "contractor_id": contractor_id,
            "qs_id": qs_id,
            "summary": "Owner and contractor discussed contract sum, payment, programme, and risk allocation.",
        },
    )

    assert "cognition_error" not in event.data
    for agent_id in [owner_id, contractor_id, qs_id]:
        memory = agent_database.get_agent_memory(agent_id, limit=5)
        assert any(item["event_type"] == "contract_negotiation_session_started" for item in memory)


def test_contract_negotiation_recommendation_writes_memory_and_belief_for_participants():
    owner_id = "OTEST_COG_RECO_OWNER"
    contractor_id = "CTEST_COG_RECO_CONTRACTOR"
    qs_id = "QTEST_COG_RECO_QS"
    project = _project(owner_id)
    project.current_stage = ProjectStage.CONTRACT_AWARD
    event_system = EventSystem()

    event = event_system.record(
        tick=16,
        event_type="contract_negotiation_recommendation",
        description="CAMEL produced a bounded contract negotiation recommendation",
        project=project,
        agent_id=contractor_id,
        data={
            "session_id": "PTEST_COG_EVENT:contract_negotiation",
            "session_type": "contract_negotiation",
            "session_participants": [owner_id, contractor_id, qs_id],
            "owner_id": owner_id,
            "contractor_id": contractor_id,
            "qs_id": qs_id,
            "selected_action": "request_revision",
            "decision_reason": "Payment milestone should be clarified before signing.",
            "stage_state_mutated": False,
        },
    )

    assert "cognition_error" not in event.data
    for agent_id in [owner_id, contractor_id, qs_id]:
        memory = agent_database.get_agent_memory(agent_id, limit=5, memory_type="relationship_memory")
        assert any(
            item["event_type"] == "contract_negotiation_recommendation"
            and "selected_action=request_revision" in item["content"]
            for item in memory
        )
        beliefs = agent_database.get_agent_beliefs(agent_id)
        assert any(item["belief_type"] == "partner_trust_belief" for item in beliefs)
