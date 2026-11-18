"""Offline contract tests: selection must never silently run the wrong executor."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gba_construction_sim.backend.main import app
from gba_construction_sim.backend.models.procurement import ProcurementExecution, ProcurementUnavailableError
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.services.workflow_service import WorkflowService
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.repositories import simulation_repository
from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider

client = TestClient(app)
NATIVE = ProcurementExecution().dict()
MICRO = {**NATIVE, "mode": "codedemo_micro", "adapter_profile_id": "codedemo-local"}
RUN = {"agent_source": "default", "ticks": 2, "enable_project_generation": False, "use_prior_network_edges": False}


@pytest.fixture(autouse=True)
def isolate_repository():
    previous = dict(simulation_repository._items)
    yield
    simulation_repository._items.clear()
    simulation_repository._items.update(previous)


@pytest.mark.parametrize("url", ["/simulation/create", "/api/workflows/WF001/run"])
def test_legacy_creation_defaults_to_native_and_locks_at_tick_zero(url):
    response = client.post(url, json=RUN)
    assert response.status_code == 200, response.text
    data = response.json()
    data = data.get("data", data)
    state = data["procurement"]
    assert data["current_tick"] == 0
    assert state["effective_configuration"] == NATIVE
    assert state["locked"] is True
    assert len(state["configuration_hash"]) == 64
    assert client.get(f"/api/simulations/{data['simulation_id']}/procurement").json()["data"] == state


@pytest.mark.parametrize("url", ["/simulation/create", "/api/workflows/WF001/run"])
@pytest.mark.parametrize("configuration", [
    {"mode": "typo"},
    {**NATIVE, "scope": "participation_only"},
    {**NATIVE, "failure_policy": "fallback_native"},
    {**NATIVE, "adapter_profile_id": "codedemo-local"},
    {"mode": "codedemo_micro"},
    {**MICRO, "adapter_profile_id": "https://arbitrary.example"},
    {**NATIVE, "unknown_option": True},
    None,
])
def test_invalid_selection_is_422_without_creating_a_run(url, configuration):
    before = len(simulation_repository.all())
    response = client.post(url, json={**RUN, "procurement_execution": configuration})
    assert response.status_code == 422, response.text
    assert len(simulation_repository.all()) == before


@pytest.mark.parametrize("url", ["/simulation/create", "/api/workflows/WF001/run"])
@pytest.mark.parametrize("location", ["explicit", "saved"])
def test_micro_is_rejected_before_native_inputs_or_provider_are_loaded(url, location, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unavailable micro request reached native initialization")

    monkeypatch.setattr("gba_construction_sim.backend.simulation.simulation_engine.agents_from_request", unexpected)
    monkeypatch.setattr(WorkflowService, "_configure_runtime_decision_provider", unexpected)
    payload = {**RUN}
    if location == "explicit":
        payload["procurement_execution"] = MICRO
    else:
        payload["workflow_configuration"] = {"configuration": {"procurement_execution": MICRO}}
    before = len(simulation_repository.all())
    response = client.post(url, json=payload)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["error_code"] == "PROCUREMENT_ENGINE_UNAVAILABLE"
    assert len(simulation_repository.all()) == before


def test_creation_priority_replaces_whole_object_and_saved_draft_does_not_change_run():
    service = WorkflowService()
    service.update_workflow("WF001", {"configuration": {"procurement_execution": MICRO}})
    with pytest.raises(ProcurementUnavailableError):
        service.run_workflow("WF001", RUN)
    # A partial explicit object receives model defaults, not the saved micro profile.
    result = service.run_workflow("WF001", {**RUN, "procurement_execution": {"mode": "gba_native"}})
    engine = simulation_repository.get(result["simulation_id"])
    original = engine.procurement_state()
    assert original["effective_configuration"] == NATIVE
    service.update_workflow("WF001", {"configuration": {"procurement_execution": MICRO}})
    assert engine.procurement_state() == original
    assert engine.workflow_config["configuration"]["procurement_execution"] == NATIVE


def test_template_is_a_snapshot_and_round_trips_procurement():
    service = WorkflowService()
    service.update_workflow("WF001", {"configuration": {"procurement_execution": MICRO}})
    service.save_template("WF001")
    service.update_workflow("WF001", {"configuration": {"procurement_execution": NATIVE}})
    template = service.load_template()
    assert template["configuration"]["procurement_execution"] == MICRO
    template["configuration"]["procurement_execution"]["mode"] = "changed"
    assert service.load_template()["configuration"]["procurement_execution"] == MICRO


def test_workflow_passes_explicit_enterprises_and_projects():
    payload = {
        **RUN,
        "agent_source": "explicit",
        "agents": [{"agent_id": "shared-owner", "name": "Scenario owner", "role": "Owner",
                    "region": "Hong Kong", "enterprise_type": "private"}],
        "initial_projects": [{"project_id": "shared-project", "name": "Scenario project",
                              "region": "Hong Kong", "owner_id": "shared-owner", "initial_budget": 1000}],
    }
    result = WorkflowService().run_workflow("WF001", payload)
    engine = simulation_repository.get(result["simulation_id"])
    assert set(engine.projects) == {"shared-project"}
    assert "shared-owner" in engine.agents
    assert set(engine.agents) == {"shared-owner"}
    assert engine.projects["shared-project"].initial_budget == 1000


@pytest.mark.parametrize("url", ["/simulation/create", "/api/workflows/WF001/run"])
def test_unimplemented_dataset_reference_is_not_silently_ignored(url):
    response = client.post(url, json={**RUN, "shared_input": {"dataset_id": "missing"}})
    assert response.status_code == 422


def test_receipt_query_is_read_only_and_cannot_unlock_paused_or_running_engine():
    engine = SimulationEngine.from_request(SimulationCreateRequest(**RUN), decision_provider=RuleBasedDecisionProvider())
    simulation_repository.add(engine)
    url = f"/api/simulations/{engine.simulation_id}/procurement"
    original = engine.procurement_state()
    for status in ["created", "paused", "running", "completed"]:
        engine.status = status
        tick = engine.current_tick
        for _ in range(2):
            assert client.get(url + "?tick=999").json()["data"] == original
        assert engine.current_tick == tick
        for method in [client.patch, client.put]:
            response = method(url, json={"procurement_execution": MICRO})
            assert response.status_code == 409
        assert engine.procurement_state() == original
    engine.status = "created"
    engine.step(return_snapshot=False)
    assert engine.current_tick == 1
    assert engine.procurement_state() == original


def test_configuration_is_detached_and_frozen():
    request = SimulationCreateRequest(**RUN)
    engine = SimulationEngine.from_request(request, decision_provider=RuleBasedDecisionProvider())
    receipt = engine.procurement_state()
    original = deepcopy(receipt)
    receipt["effective_configuration"]["mode"] = "codedemo_micro"
    request.procurement_execution = ProcurementExecution(**MICRO)
    assert engine.procurement_state() == original
    with pytest.raises((TypeError, ValidationError)):
        engine.procurement_execution.mode = "codedemo_micro"
    with pytest.raises(AttributeError):
        engine.procurement_execution = ProcurementExecution(**MICRO)


def test_capabilities_and_missing_simulation():
    engines = client.get("/api/procurement-engines").json()["data"]
    assert {row["mode"]: row["available"] for row in engines} == {"gba_native": True, "codedemo_micro": False}
    assert client.get("/api/simulations/no-such-run/procurement").status_code == 404


@pytest.mark.parametrize("url", ["/simulation/create", "/api/workflows/WF001/run"])
@pytest.mark.parametrize("invalid_case", ["empty", "duplicate_agent", "duplicate_project", "unknown_owner", "generation", "prior"])
def test_explicit_pool_does_not_fall_back_or_drop_duplicate_entities(url, invalid_case):
    owner = {"agent_id": "owner", "name": "Owner", "role": "Owner",
             "region": "Hong Kong", "enterprise_type": "private"}
    project = {"project_id": "project", "name": "Project", "region": "Hong Kong",
               "owner_id": "owner", "initial_budget": 1000}
    payload = {**RUN, "agent_source": "explicit", "agents": [owner], "initial_projects": [project]}
    if invalid_case == "empty":
        payload["agents"] = []
    elif invalid_case == "duplicate_agent":
        payload["agents"] = [owner, owner]
    elif invalid_case == "duplicate_project":
        payload["initial_projects"] = [project, project]
    elif invalid_case == "unknown_owner":
        payload["initial_projects"] = [{**project, "owner_id": "missing"}]
    elif invalid_case == "generation":
        payload["enable_project_generation"] = True
    else:
        payload["use_prior_network_edges"] = True
    before = len(simulation_repository.all())
    response = client.post(url, json=payload)
    assert response.status_code == 422, response.text
    assert len(simulation_repository.all()) == before
