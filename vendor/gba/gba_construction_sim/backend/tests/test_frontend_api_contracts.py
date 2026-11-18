from fastapi.testclient import TestClient

from gba_construction_sim.backend.main import app
from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service
from gba_construction_sim.backend.services.workflow_service import WorkflowService
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.repositories import simulation_repository


client = TestClient(app)


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] is not None
    return payload["data"]


def test_agent_cluster_policy_contracts():
    agents = assert_ok(client.get("/api/agents"))["items"]
    assert agents[0]["agent_id"]

    profile = assert_ok(client.get(f"/api/agents/{agents[0]['agent_id']}"))
    assert profile["capabilities"]

    cognitive = assert_ok(client.get(f"/api/agents/{agents[0]['agent_id']}/cognitive-state"))
    assert cognitive["strategy"]["primary_strategy"]
    assert cognitive["beliefs"]
    assert cognitive["memory"]
    assert cognitive["profile_summary"]["source_type"] in {"real_user", "real_public", "synthetic"}

    chat = assert_ok(
        client.post(
            f"/api/agents/{agents[0]['agent_id']}/chat",
            json={"message": "Which partners do you seek?", "context": {"policy_id": "POL001"}},
        )
    )
    assert chat["reply"]

    clusters = assert_ok(client.get("/api/clusters"))["items"]
    assert clusters[0]["cluster_id"] == "CL005"
    assert clusters[0]["agent_count"] == 1000
    cluster = assert_ok(client.get(f"/api/clusters/{clusters[0]['cluster_id']}"))
    assert cluster["map_preview"]["nodes"]
    assert cluster["cluster_size"] == 1000
    assert len(cluster["coverage"]) == 11
    assert cluster["default_output"]["source_mix"]["real_user"] == 149
    assert cluster["default_output"]["source_mix"]["real_public"] == 265
    assert cluster["default_output"]["source_mix"]["synthetic"] == 586
    assert cluster["default_output"]["source_mix"]["support_regulator"] == 11
    assert cluster["default_output"]["role_mix_by_city"]["Shenzhen"]["consultants"] > cluster["default_output"]["role_mix_by_city"]["Shenzhen"]["contractors"]
    assert cluster["default_output"]["role_mix_by_city"]["Macau"]["contractors"] > cluster["default_output"]["role_mix_by_city"]["Macau"]["consultants"]
    assert cluster["default_output"]["enterprise_agent_count"] == 1000
    assert cluster["default_output"]["total_agent_count"] == 1011
    cluster_run = assert_ok(client.post(f"/api/clusters/{clusters[0]['cluster_id']}/use-in-simulation"))
    assert cluster_run["agent_count"] == 1000
    assert cluster_run["enterprise_agent_count"] == 1000
    assert cluster_run["support_regulator_count"] == 11
    assert cluster_run["total_agent_count"] == 1011
    assert cluster_run["recommended_run"]["agent_count"] == 1000

    policies = assert_ok(client.get("/api/policies"))["items"]
    policy = assert_ok(client.get(f"/api/policies/{policies[0]['policy_id']}"))
    preview = assert_ok(client.get(f"/api/policies/{policy['policy_id']}/preview"))
    assert preview["expected_influence_path"]


def test_workflow_runtime_analytics_contracts():
    workflows = assert_ok(client.get("/api/workflows"))
    assert workflows[0]["workflow_id"]

    run = assert_ok(
        client.post(
            f"/api/workflows/{workflows[0]['workflow_id']}/run",
            json={
                "agent_source": "database",
                "agent_count": 1200,
                "ticks": 24,
                "enable_project_generation": True,
                "target_project_count": 8,
                "max_active_projects": 8,
                "max_tender_invites": 20,
            },
        )
    )
    simulation_id = run["simulation_id"]
    assert run["status"] == "created"
    assert run["current_tick"] == 0
    assert run["total_ticks"] == 24
    assert run["agent_count"] == 1200
    assert run["enterprise_agent_count"] == 1200
    assert run["support_regulator_count"] == 11
    assert run["total_agent_count"] == 1211
    assert run["live_mode"] is True

    first_tick = assert_ok(client.get(f"/api/simulations/{simulation_id}/runtime-state?tick=1"))
    assert first_tick["generated_until_tick"] == 1
    assert first_tick["map"]["projects"]

    runtime = assert_ok(client.get(f"/api/simulations/{simulation_id}/runtime-state?tick=24"))
    assert runtime["map"]["projects"]
    assert runtime["kpis"]["active_projects"] >= 1
    assert runtime["generated_until_tick"] >= 24
    assert runtime["total_ticks"] == 24
    assert runtime["camel_queue"]["completed"] >= 0
    assert runtime["camel_queue"]["running"] >= 0
    assert runtime["interaction_session_summary"]["total"] >= 0
    assert "by_type" in runtime["interaction_session_summary"]
    assert runtime["generation_state"]["camel_queue"]["current_operation"]
    performance = runtime["generation_state"]["performance"]
    assert performance["request_total_ms"] >= 0
    assert performance["generation_loop_ms"] >= 0
    assert performance["map_build_ms"] >= 0
    assert performance["kpi_build_ms"] >= 0
    assert performance["ticks_generated"] >= 0
    assert isinstance(performance["last_step_profile"], dict)
    assert runtime["kpis"]["total_projects"] >= 1
    assert len(runtime["map"]["enterprises"]) >= 500
    agent_id = runtime["map"]["enterprises"][0]["agent_id"]
    agent_history = assert_ok(client.get(f"/api/simulations/{simulation_id}/agents/{agent_id}/history?tick=5"))
    assert agent_history["current_tick"] == 5
    assert all(row["tick"] <= 5 for row in agent_history["activity_timeline"])
    assert all(event["tick"] <= 5 for event in agent_history["events"])
    participant_sets = [
        {participant["role"] for participant in project.get("participants", [])}
        for project in runtime["map"]["projects"]
        if project.get("participants")
    ]
    assert participant_sets
    assert any("Owner" in roles and {"Architect", "QS"}.issubset(roles) for roles in participant_sets)
    assert any(("Contractor" in roles or "Supplier" in roles) for roles in participant_sets)
    assert not all(roles <= {"Architect", "Engineer", "QS", "Consultant"} for roles in participant_sets)

    projects = assert_ok(client.get(f"/api/simulations/{simulation_id}/projects"))
    assert projects[0]["progress"] >= 0

    dashboard = assert_ok(client.get(f"/api/analytics/dashboard?simulation_id={simulation_id}"))
    assert dashboard["kpis"]["policy_impact_score"] > 0
    assert dashboard["workflow"]["execution_logic"]["total_ticks"] == 24
    assert dashboard["kpis"]["total_projects"] == runtime["kpis"]["total_projects"]
    assert dashboard["kpis"]["active_projects"] == runtime["kpis"]["active_projects"]
    assert dashboard["kpis"]["firms_engaged"] == runtime["kpis"]["firms_engaged"]
    assert dashboard["kpis"]["enterprise_pool"] == run["enterprise_agent_count"]
    assert dashboard["kpis"]["runtime_links"] == runtime["kpis"]["runtime_links"]
    assert dashboard["kpis"]["visible_enterprises"] >= 500
    assert len(dashboard["spatial_distribution"]["points"]) == len(runtime["map"]["projects"])
    assert dashboard["trend_analysis"]["series"][1]["data"]


def test_workflow_run_defaults_to_local_decision_fallback(monkeypatch):
    monkeypatch.delenv("CAMEL_DECISION_STRICT", raising=False)
    service = WorkflowService()

    run = service.run_workflow(
        "WF001",
        {
            "ticks": 1,
            "agent_source": "default",
            "enable_project_generation": False,
        },
    )
    engine = simulation_repository.get(run["simulation_id"])
    provider = engine.lifecycle_engine.decision_provider

    assert provider.strict is False
    assert isinstance(provider.fallback, RuleBasedDecisionProvider)


def test_runtime_state_can_advance_playback_after_early_lifecycle_completion():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            name="frontend playback continuation",
            ticks=6,
            random_seed=99,
            enable_project_generation=False,
        )
    )
    simulation_repository.add(engine)

    first_tick = simulation_runtime_service.runtime_state(engine.simulation_id, 1)
    assert first_tick["current_tick"] == 1
    engine.result_store.save_tick_result(engine.current_tick, engine.projects, engine.agents, engine.network, engine.metrics)
    timeline = simulation_runtime_service.timeline(engine.simulation_id)
    assert [row["tick"] for row in timeline["ticks"]].count(1) == 1

    engine.status = "completed"
    later_tick = simulation_runtime_service.runtime_state(engine.simulation_id, 4)

    assert later_tick["current_tick"] == 4
    assert later_tick["generated_until_tick"] == 4
    assert later_tick["status"] == "running"
    assert later_tick["generation_state"]["requested_tick"] == 4
    assert later_tick["generation_state"]["generated_until_tick"] == 4
    assert later_tick["generation_state"]["current_operation"]
    assert later_tick["generation_state"]["performance"]["ticks_generated"] == 3
    assert later_tick["generation_state"]["performance"]["last_step_profile"]["return_snapshot_requested"] is False
    assert later_tick["generation_state"]["performance"]["map_build_ms"] >= 0
    assert later_tick["progress_percent"] >= 0


def test_runtime_participants_do_not_show_bidders_before_signed_contract():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            name="participant contract timing",
            ticks=40,
            random_seed=42,
            enable_project_generation=False,
        )
    )
    simulation_repository.add(engine)

    bid_evaluation_tick = None
    contract_signed_tick = None
    while engine.current_tick < engine.ticks and (bid_evaluation_tick is None or contract_signed_tick is None):
        engine.step()
        project = engine.projects.get("P001")
        if not project:
            continue
        for event in project.event_log:
            if event["event_type"] == "bid_evaluation_completed":
                bid_evaluation_tick = bid_evaluation_tick or event["tick"]
            if event["event_type"] == "contract_awarded":
                contract_signed_tick = contract_signed_tick or event["tick"]

    assert bid_evaluation_tick is not None
    assert contract_signed_tick is not None
    assert bid_evaluation_tick < contract_signed_tick

    before_contract = simulation_runtime_service.runtime_state(engine.simulation_id, bid_evaluation_tick)
    before_project = next(project for project in before_contract["map"]["projects"] if project["project_id"] == "P001")
    before_roles = {participant["role"] for participant in before_project["participants"]}
    assert "Contractor" not in before_roles
    assert before_project["selected_contractor_id"]
    assert before_project["contracts"] == []

    after_contract = simulation_runtime_service.runtime_state(engine.simulation_id, contract_signed_tick)
    after_project = next(project for project in after_contract["map"]["projects"] if project["project_id"] == "P001")
    after_roles = {participant["role"] for participant in after_project["participants"]}
    assert "Contractor" in after_roles
    assert after_project["contracts"]
