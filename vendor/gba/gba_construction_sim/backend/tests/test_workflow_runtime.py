import pytest

from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.services.workflow_service import WorkflowService
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.simulation.workflow_runtime import WorkflowRuntimeController
from gba_construction_sim.backend.storage.repositories import simulation_repository


def test_workflow_runtime_applies_period_policy_and_explicit_environment_event():
    policy = PolicyRegime()
    environment = MacroEnvironment()
    events = EventSystem()
    controller = WorkflowRuntimeController(
        {
            "configuration": {
                "periods": [
                    {"id": "p1", "title": "Baseline", "startTick": 0, "endTick": 2},
                    {"id": "p2", "title": "Policy period", "startTick": 2, "endTick": 5},
                ],
                "policies": [
                    {
                        "id": "i1",
                        "title": "Approval pilot",
                        "startTick": 2,
                        "endTick": 4,
                        "parameters": {
                            "approval_success_prob": 0.91,
                            "entry_waiting_time": 12,
                        },
                    }
                ],
                "events": [
                    {
                        "id": "e1",
                        "title": "Demand shock",
                        "startTick": 3,
                        "environment_changes": {
                            "market_demand_index": 1.25,
                            "regulatory_pressure_index": {"operation": "add", "value": 0.1},
                        },
                    }
                ],
            }
        },
        policy,
        environment,
        events,
    )

    before = controller.apply_tick(1)
    assert before["current_period"]["phase_id"] == "p1"
    assert before["active_interventions"] == []
    assert policy.approval_success_prob == pytest.approx(0.7)

    active = controller.apply_tick(2)
    assert active["current_period"]["phase_id"] == "p2"
    assert active["active_interventions"][0]["intervention_id"] == "i1"
    assert policy.approval_success_prob == pytest.approx(0.91)
    assert policy.entry_waiting_time == pytest.approx(12)

    event_tick = controller.apply_tick(3)
    assert event_tick["events_applied_this_tick"][0]["event_id"] == "e1"
    assert event_tick["events_applied_this_tick"][0]["quantitative_effect_applied"] is True
    assert environment.market_demand_index == pytest.approx(1.25)
    assert environment.regulatory_pressure_index == pytest.approx(0.6)
    assert len([event for event in events.events if event.event_type == "workflow_external_event"]) == 1

    after = controller.apply_tick(4)
    assert after["active_interventions"] == []
    assert after["events_applied_this_tick"] == []
    assert policy.approval_success_prob == pytest.approx(0.7)
    assert len([event for event in events.events if event.event_type == "workflow_external_event"]) == 1


def test_workflow_service_preserves_frontend_configuration_and_exposes_run_receipt():
    service = WorkflowService()
    workflow_id = "WF001"
    updated = service.update_workflow(
        workflow_id,
        {
            "selected_cluster_id": "CL005",
            "horizon_years": 1,
            "configuration": {
                "periods": [
                    {"id": "baseline", "title": "Baseline", "startTick": 0, "endTick": 2},
                    {"id": "continue", "title": "Continue", "startTick": 2, "endTick": 6},
                ],
                "policies": [
                    {
                        "id": "pilot",
                        "policy_id": "POL001",
                        "title": "Cross-region policy",
                        "startTick": 2,
                        "endTick": 6,
                    }
                ],
                "events": [
                    {"id": "event-1", "title": "Review event", "startTick": 3}
                ],
                "agent_source": "default",
                "agent_count": 8,
                "agent_regions": ["Hong Kong", "Shenzhen"],
                "max_tender_invites": 17,
                "use_prior_network_edges": False,
            },
        },
    )

    assert len(updated["phases"]) == 2
    assert updated["interventions"][0]["policy_id"] == "POL001"
    assert updated["events"][0]["tick"] == 3

    created = service.run_workflow(workflow_id, {"ticks": 6, "random_seed": 9})
    receipt = created["configuration_summary"]
    assert receipt["selected_cluster_id"] == "CL005"
    assert receipt["agent_regions"] == ["Hong Kong", "Shenzhen"]
    assert receipt["requested_agent_count"] == 8
    assert receipt["max_tender_invites"] == 17
    assert receipt["period_count"] == 2
    assert receipt["policy_count"] == 1
    assert receipt["event_count"] == 1

    engine = simulation_repository.get(created["simulation_id"])
    engine.step(return_snapshot=False)
    assert engine.workflow_runtime.state()["current_period"]["phase_id"] == "baseline"
    engine.step(return_snapshot=False)
    runtime = engine.workflow_runtime.state()
    assert runtime["current_period"]["phase_id"] == "continue"
    assert runtime["active_interventions"][0]["policy_id"] == "POL001"
    assert engine.policy.approval_success_prob == pytest.approx(0.82)


def test_run_payload_schedule_overrides_older_saved_nested_configuration():
    service = WorkflowService()
    workflow_id = "WF001"
    service.update_workflow(
        workflow_id,
        {
            "configuration": {
                "periods": [
                    {"id": "old-period", "title": "Old period", "startTick": 0, "endTick": 6}
                ],
                "policies": [],
                "events": [],
                "agent_source": "default",
                "agent_count": 8,
            }
        },
    )

    created = service.run_workflow(
        workflow_id,
        {
            "ticks": 4,
            "phases": [
                {"phase_id": "p1", "name": "Baseline", "start_tick": 0, "end_tick": 1},
                {"phase_id": "p2", "name": "Selected period", "start_tick": 1, "end_tick": 4},
            ],
            "interventions": [
                {
                    "intervention_id": "policy-now",
                    "name": "Selected policy",
                    "apply_tick": 1,
                    "end_tick": 4,
                    "parameters": {"approval_success_prob": 0.9},
                }
            ],
            "events": [
                {"event_id": "event-now", "name": "Selected event", "tick": 1}
            ],
        },
    )

    assert created["configuration_summary"]["period_count"] == 2
    assert created["configuration_summary"]["policy_count"] == 1
    assert created["configuration_summary"]["event_count"] == 1

    engine = simulation_repository.get(created["simulation_id"])
    engine.step(return_snapshot=False)
    runtime = engine.workflow_runtime.state()
    assert runtime["current_period"]["phase_id"] == "p2"
    assert runtime["active_interventions"][0]["intervention_id"] == "policy-now"
    assert runtime["events_applied_this_tick"][0]["event_id"] == "event-now"
    assert engine.policy.approval_success_prob == pytest.approx(0.9)
