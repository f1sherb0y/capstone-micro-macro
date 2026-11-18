from collections import Counter
import csv
import time

import pytest

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.decision.camel_provider import CamelDecisionError
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.services.simulation_service import ROLE_MAP, simulation_runtime_service
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.repositories import simulation_repository
from gba_construction_sim.backend.storage.agent_database import DEFAULT_AGENT_CSV
from gba_construction_sim.backend.network.collaboration_prior import DEFAULT_NETWORK_EDGE_CSV


def _has_full_source_mix() -> bool:
    """Return whether the optional private Batch001 source mix is available."""

    if not DEFAULT_AGENT_CSV.exists():
        return False
    with DEFAULT_AGENT_CSV.open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle), {})
    return first.get("data_source_type") != "generated_public_demo"


def test_seeded_simulation_is_reproducible_for_core_trajectory():
    request = SimulationCreateRequest(ticks=35, random_seed=123)
    first = SimulationEngine.from_request(request)
    second = SimulationEngine.from_request(request)

    first.run()
    second.run()

    first_project = first.projects["P001"]
    second_project = second.projects["P001"]
    assert first_project.current_stage == second_project.current_stage
    assert first_project.selected_contractor_id == second_project.selected_contractor_id
    assert first.result_store.get_project_performance("P001") == second.result_store.get_project_performance("P001")


def test_metrics_and_network_are_available():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=20, random_seed=42))
    engine.run()

    assert "project_completion_rate" in engine.metrics.project_metrics
    assert "network_density" in engine.metrics.network_metrics
    assert engine.network.to_dict()["nodes"]


def test_step_profile_records_runtime_sections():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=6, random_seed=42))

    summary = engine.step(return_snapshot=False)
    profile = engine.last_step_profile

    assert summary["step_profile"]["tick"] == 1
    assert profile["tick"] == 1
    assert profile["return_snapshot_requested"] is False
    assert profile["total_step_ms"] >= 0
    assert profile["macro_environment_ms"] >= 0
    assert profile["owner_initiation_ms"] >= 0
    assert profile["project_lifecycle_ms"] >= 0
    assert profile["project_state_update_ms"] >= 0
    assert profile["network_metrics_ms"] >= 0
    assert profile["snapshot_save_ms"] >= 0
    assert len(engine.step_profile_history) == 1


def test_failed_step_does_not_mark_tick_as_generated():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=6,
            random_seed=11,
            enable_project_generation=False,
        )
    )

    def fail_lifecycle(*_args, **_kwargs):
        raise RuntimeError("CAMEL decision timed out")

    engine.lifecycle_engine.step = fail_lifecycle

    with pytest.raises(RuntimeError, match="CAMEL decision timed out"):
        engine.step()

    assert engine.current_tick == 0
    assert engine.status == "running"
    assert engine.current_operation == "failed_processing_project_lifecycle"
    assert engine.result_store.tick_snapshots == []


def test_runtime_state_reports_visible_camel_failure_without_http_failure():
    class FailingTenderDecisionProvider:
        def decide(self, agent, context):
            raise CamelDecisionError("CAMEL decision timed out during tender decision")

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=30, random_seed=42))
    engine.lifecycle_engine.decision_provider = FailingTenderDecisionProvider()
    simulation_repository.add(engine)

    state = simulation_runtime_service.runtime_state(engine.simulation_id, tick=25)

    assert state["status"] in {"running", "completed"}
    assert state["generation_state"]["status"] in {"running", "completed"}
    assert state["requested_tick"] == 25
    assert state["generated_until_tick"] >= 25
    assert state["camel_queue"]["failed"] >= 1
    assert "CAMEL decision timed out" in state["camel_queue"]["last_error"]
    assert state["generation_state"]["camel_queue"]["failed"] >= 1


def test_agent_operations_are_structured_enterprise_decisions():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=5, random_seed=77))
    engine.run()

    operations = [event for event in engine.events.events if event.event_type == "agent_operation"]

    assert operations
    assert all(event.data.get("label") for event in operations)
    assert all(event.data.get("description") for event in operations)
    assert all("available_resource" in event.data for event in operations)
    assert all("decision_factors" in event.data for event in operations)
    assert {event.data.get("operation") for event in operations} - {"maintain_operations"}


@pytest.mark.skipif(
    not _has_full_source_mix(),
    reason="The public package omits private Batch001 source-mix and collaboration-prior data",
)
def test_database_agent_source_loads_agents_and_limits_tender_pool():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=12,
            random_seed=42,
            agent_source="database",
            agent_count=6000,
            max_tender_invites=40,
        )
    )

    assert len(engine.agents) >= 6000
    assert engine.projects["P001"].owner_id in engine.agents
    assert any(agent.semantic_memory.get("agent_type") == "synthetic" for agent in engine.agents.values())

    engine.run()
    project = engine.projects["P001"]
    contractor_engagements = [engagement for engagement in project.engagements if engagement.role == "Contractor"]

    assert len(contractor_engagements) <= 40
    assert any(event.event_type == "agent_operations_aggregated" for event in engine.events.events)
    assert engine.network.metrics()["prior_edge_count"] == 52000


@pytest.mark.skipif(not DEFAULT_AGENT_CSV.exists(), reason="Batch001 agent CSV is not available")
def test_runtime_visible_enterprises_keep_city_role_mix():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=12,
            random_seed=42,
            agent_source="database",
            agent_count=6000,
            max_tender_invites=40,
        )
    )

    visible_agents = simulation_runtime_service._visible_enterprise_agents(engine)
    role_classes_by_region = {}
    count_by_region = {}
    for agent in visible_agents:
        count_by_region[agent.region] = count_by_region.get(agent.region, 0) + 1
        role_classes_by_region.setdefault(agent.region, set()).add(ROLE_MAP.get(agent.role, "consultant"))

    mixed_regions = [
        region
        for region, count in count_by_region.items()
        if count >= 8
    ]

    assert len(visible_agents) >= 500
    assert len(mixed_regions) >= 8
    assert all(len(role_classes_by_region[region]) >= 3 for region in mixed_regions)


@pytest.mark.skipif(not DEFAULT_AGENT_CSV.exists(), reason="Batch001 agent CSV is not available")
def test_database_default_project_target_scales_for_large_workflows():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=60,
            random_seed=42,
            agent_source="database",
            agent_count=6000,
            enable_project_generation=True,
        )
    )

    assert engine.target_project_count >= 50
    assert engine.max_active_projects >= 30


@pytest.mark.skipif(
    not _has_full_source_mix(),
    reason="The public package omits private Batch001 source-mix data",
)
def test_database_1000_cluster_selection_is_balanced_and_real_first():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=12,
            random_seed=42,
            agent_source="database",
            agent_count=1000,
            max_tender_invites=30,
            enable_project_generation=True,
        )
    )

    assert len(engine.agents) == 1011

    enterprise_agents = [agent for agent in engine.agents.values() if agent.role != "Government"]
    government_agents = [agent for agent in engine.agents.values() if agent.role == "Government"]
    source_counts = Counter(agent.semantic_memory.get("agent_type") for agent in enterprise_agents)
    city_counts = Counter(agent.region for agent in enterprise_agents)
    role_class_counts = Counter(ROLE_MAP.get(agent.role, "consultant") for agent in enterprise_agents)
    role_classes_by_region_count = {}
    role_classes_by_city = {}
    for agent in enterprise_agents:
        role_classes_by_city.setdefault(agent.region, set()).add(ROLE_MAP.get(agent.role, "consultant"))
        role_classes_by_region_count.setdefault(agent.region, Counter())[ROLE_MAP.get(agent.role, "consultant")] += 1

    assert len(enterprise_agents) == 1000
    assert len(government_agents) == 11
    assert {agent.region for agent in government_agents} == set(city_counts)
    assert source_counts["real_user"] == 149
    assert source_counts["real_public"] >= 230
    assert source_counts["synthetic"] <= 620
    assert len(city_counts) == 11
    assert city_counts["Shenzhen"] == 205
    assert city_counts["Guangzhou"] == 177
    assert city_counts["Hong Kong"] == 167
    assert min(city_counts.values()) >= 39
    assert max(city_counts.values()) <= 205
    assert 360 <= role_class_counts["contractor"] <= 410
    assert 315 <= role_class_counts["consultant"] <= 355
    assert 170 <= role_class_counts["developer"] <= 200
    assert 85 <= role_class_counts["supplier"] <= 115
    assert role_classes_by_region_count["Shenzhen"]["consultant"] > role_classes_by_region_count["Shenzhen"]["contractor"]
    assert role_classes_by_region_count["Macau"]["contractor"] > role_classes_by_region_count["Macau"]["consultant"]
    assert all(len(role_classes) >= 4 for role_classes in role_classes_by_city.values())


@pytest.mark.skipif(
    not DEFAULT_AGENT_CSV.exists() or not DEFAULT_NETWORK_EDGE_CSV.exists(),
    reason="Batch001 agent or network CSV is not available",
)
def test_database_simulation_completes_reproducibly_with_release_and_performance_budget():
    request = SimulationCreateRequest(
        ticks=80,
        random_seed=20260520,
        agent_source="database",
        agent_count=6000,
        max_tender_invites=40,
        enable_project_generation=True,
        target_project_count=12,
        max_active_projects=10,
    )
    start = time.perf_counter()
    first = SimulationEngine.from_request(request)
    assert first.projects == {}
    first.run()
    elapsed = time.perf_counter() - start

    second = SimulationEngine.from_request(request)
    second.run()

    first_project = next(iter(first.projects.values()))
    second_project = second.projects[first_project.project_id]
    first_project_trajectory = sorted(
        (project.project_id, project.region, project.project_type, project.current_stage.value)
        for project in first.projects.values()
    )
    second_project_trajectory = sorted(
        (project.project_id, project.region, project.project_type, project.current_stage.value)
        for project in second.projects.values()
    )
    role_counts = {
        role: sum(1 for agent in first.agents.values() if agent.role == role)
        for role in ["Owner", "Architect", "QS", "Contractor", "Supplier", "Government"]
    }
    closed_projects = [project for project in first.projects.values() if project.current_stage == ProjectStage.CLOSED]
    closed_project = closed_projects[0]

    assert len(first.agents) >= 6000
    assert len(first.projects) == 12
    assert len({project.region for project in first.projects.values()}) >= 4
    assert len({project.owner_id for project in first.projects.values()}) >= 4
    assert len({project.selected_contractor_id for project in first.projects.values() if project.selected_contractor_id}) >= 4
    assert all(project.flags.get("owner_decision") for project in first.projects.values())
    assert all(project.flags.get("opportunity") for project in first.projects.values())
    assert all(count > 0 for count in role_counts.values())
    assert first.collaboration_prior.edge_count == 52000
    assert closed_projects
    assert first_project.current_stage == second_project.current_stage
    assert first_project_trajectory == second_project_trajectory
    assert first_project.selected_architect_id == second_project.selected_architect_id
    assert first_project.selected_qs_id == second_project.selected_qs_id
    assert first_project.selected_contractor_id == second_project.selected_contractor_id
    assert first_project.selected_supplier_ids == second_project.selected_supplier_ids
    assert first.result_store.get_project_performance("P001") == second.result_store.get_project_performance("P001")
    assert first.metrics.agent_metrics["detail_truncated"] is True
    assert first.metrics.agent_metrics["summary"]["total_agents"] == len(first.agents)
    assert first.metrics.agent_metrics["summary"]["joined_agents"] > 0
    assert all(
        engagement.status in {EngagementStatus.RELEASED, EngagementStatus.TERMINATED}
        for engagement in closed_project.engagements
    )
    assert elapsed < 25.0


def test_generated_projects_are_owner_decision_driven():
    request = SimulationCreateRequest(
        ticks=50,
        random_seed=20260527,
        enable_project_generation=True,
        target_project_count=6,
        max_active_projects=4,
    )
    engine = SimulationEngine.from_request(request)

    assert engine.projects == {}
    engine.run()

    initiated = [event for event in engine.events.events if event.event_type == "project_opportunity_initiated"]
    assert len(engine.projects) >= 2
    assert len(initiated) == len(engine.projects)
    assert all(event.agent_id == engine.projects[event.project_id].owner_id for event in initiated)
    assert all("decision_score" in event.data for event in initiated)
    initiated_by_project = {event.project_id: event.tick for event in initiated}
    for event in initiated:
        factors = event.data["decision_factors"]
        assert factors["active_owner_projects"] >= 0
        assert 0.0 <= factors["budget_capacity"] <= 1.0
        assert "macro_support" in factors
        assert "risk_drag" in factors
        assert "financial_capacity" in factors
        assert "payment_reliability" in factors
        assert event.data["decision_advisor"]["available"] is True
        assert event.data["decision_advisor"]["action_type"] == "initiate_project"
        assert event.data["decision_advisor"]["decision"] is True
    runtime_nodes = [
        simulation_runtime_service._project_node(project, engine.agents)
        for project in engine.projects.values()
    ]
    assert all(node["created_tick"] == initiated_by_project[node["project_id"]] for node in runtime_nodes)
    assert max(node["created_tick"] for node in runtime_nodes) > 1
    assert all(project.current_stage != ProjectStage.INITIATION for project in engine.projects.values())


def test_generated_project_stays_in_initiation_on_creation_tick():
    request = SimulationCreateRequest(
        ticks=10,
        random_seed=20260527,
        enable_project_generation=True,
        target_project_count=2,
        max_active_projects=2,
    )
    engine = SimulationEngine.from_request(request)

    created_project = None
    for _ in range(request.ticks):
        engine.step(return_snapshot=False)
        created_project = next(
            (
                project
                for project in engine.projects.values()
                if project.flags.get("created_tick") == engine.current_tick
            ),
            None,
        )
        if created_project:
            break

    assert created_project is not None
    assert created_project.current_stage == ProjectStage.INITIATION
    assert created_project.stage_tick == 1


def test_owner_decision_rejection_prevents_generated_project_creation():
    class RejectingOwnerDecisionProvider:
        def decide(self, agent, context):
            project = context["project"]
            return AgentAction(
                action_type="initiate_project",
                project_id=project.project_id,
                agent_id=agent.agent_id,
                decision=False,
                data={"decision_score": context.get("owner_decision_score")},
                reason="Owner deferred investment because the opportunity does not fit current resource strategy.",
            )

    request = SimulationCreateRequest(
        ticks=35,
        random_seed=20260528,
        enable_project_generation=True,
        target_project_count=4,
        max_active_projects=3,
    )
    engine = SimulationEngine.from_request(request)
    engine.lifecycle_engine.decision_provider = RejectingOwnerDecisionProvider()
    engine.run()

    declined_by_owner = [
        event
        for event in engine.events.events
        if event.event_type == "project_opportunity_declined"
        and event.data.get("decision_advisor", {}).get("decision") is False
    ]

    assert engine.projects == {}
    assert declined_by_owner
    assert all(event.project_id is None for event in declined_by_owner)


def test_invalid_owner_initiation_advisor_cannot_create_project():
    class InvalidOwnerDecisionProvider:
        def decide(self, agent, context):
            project = context["project"]
            return AgentAction(
                action_type="evaluate_market_opportunity",
                project_id=project.project_id,
                agent_id=agent.agent_id,
                decision=True,
                reason="Owner only evaluated the opportunity and did not initiate it.",
            )

    request = SimulationCreateRequest(
        ticks=30,
        random_seed=20260529,
        enable_project_generation=True,
        target_project_count=4,
        max_active_projects=3,
    )
    engine = SimulationEngine.from_request(request)
    engine.lifecycle_engine.decision_provider = InvalidOwnerDecisionProvider()
    engine.run()

    declined_by_owner = [
        event
        for event in engine.events.events
        if event.event_type == "project_opportunity_declined"
        and event.data.get("decision_advisor", {}).get("action_type") == "evaluate_market_opportunity"
    ]

    assert engine.projects == {}
    assert declined_by_owner
    assert all(event.project_id is None for event in declined_by_owner)


def test_project_parties_follow_procurement_sequence():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    bid_events = [
        event
        for event in project.event_log
        if event["event_type"] == "bid_submitted"
    ]
    bid_submitters = {
        event["data"]["contractor_id"]
        for event in bid_events
    }
    selected_bidder_events = [
        event
        for event in project.event_log
        if event["event_type"] == "bid_evaluation_completed"
    ]
    contract_events = [
        event
        for event in project.event_log
        if event["event_type"] == "contract_awarded"
    ]
    supplier_events = [
        event
        for event in project.event_log
        if event["event_type"] == "supplier_selected"
    ]
    mobilization_events = [
        event
        for event in project.event_log
        if event["event_type"] == "mobilization_completed"
    ]
    tender_opened_events = [
        event
        for event in project.event_log
        if event["event_type"] == "tender_opened"
    ]
    contractor_engagements = [engagement for engagement in project.engagements if engagement.role == "Contractor"]

    assert project.selected_contractor_id in bid_submitters
    assert tender_opened_events[0]["data"]["invited_count"] == len(contractor_engagements)
    assert all("decision_factors" in event["data"] for event in bid_events)
    assert all("expected_profit" in event["data"] for event in bid_events)
    assert all("risk_level" in event["data"] for event in bid_events)
    assert all("bid_probability" in event["data"] for event in bid_events)
    assert all(
        event["data"]["decision_advisor"]["available"]
        or event["data"]["decision_advisor"].get("skipped_reason") == "camel_tender_advisor_limit"
        for event in bid_events
    )
    assert all(
        "action_type" in event["data"]["decision_advisor"]
        for event in bid_events
        if event["data"]["decision_advisor"]["available"]
    )
    assert selected_bidder_events
    assert contract_events
    assert supplier_events
    assert mobilization_events
    assert selected_bidder_events[0]["tick"] <= contract_events[0]["tick"]
    assert all(engagement.start_stage == ProjectStage.TENDERING for engagement in contractor_engagements)
    assert supplier_events[0]["tick"] >= contract_events[0]["tick"]
    assert mobilization_events[0]["tick"] >= supplier_events[0]["tick"]
    assert mobilization_events[0]["data"]["construction_plan"]["method_statement_ready"] is True
    assert mobilization_events[0]["data"]["contractor_resource_allocation"] == 0.8
    assert mobilization_events[0]["data"]["supplier_resource_allocation"] == 0.35
    assert supplier_events[0]["data"]["candidate_count"] >= 1
    assert supplier_events[0]["data"]["shortlisted_suppliers"]
    assert supplier_events[0]["data"]["selection_basis"] == [
        "supply reliability",
        "material quality",
        "contractor collaboration prior",
        "local delivery fit",
        "available resource",
    ]
    if any(event["event_type"] == "construction_progress_updated" for event in project.event_log):
        first_progress_tick = next(
            event["tick"]
            for event in project.event_log
            if event["event_type"] == "construction_progress_updated"
        )
        assert mobilization_events[0]["tick"] < first_progress_tick

    first_tick_by_type = {
        event["event_type"]: event["tick"]
        for event in project.event_log
        if event["event_type"]
        in {
            "tender_opened",
            "bid_evaluation_completed",
            "contract_awarded",
            "supplier_selected",
            "mobilization_completed",
            "construction_progress_updated",
        }
    }
    for snapshot in engine.result_store.tick_snapshots:
        tick = snapshot["tick"]
        snap_project = snapshot["projects"][project.project_id]
        if tick < first_tick_by_type["bid_evaluation_completed"]:
            assert snap_project["selected_contractor_id"] is None
            assert snap_project["contract_sum"] is None
        if tick < first_tick_by_type["supplier_selected"]:
            assert snap_project["selected_supplier_ids"] == []
        if "construction_progress_updated" in first_tick_by_type and tick < first_tick_by_type["supplier_selected"]:
            assert snap_project["performance"]["actual_progress"] == 0.0


def test_network_contractors_only_appear_after_procurement_award():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=35, random_seed=42))
    engine.run()
    pre_award_stages = {
        ProjectStage.INITIATION.value,
        ProjectStage.DESIGN.value,
        ProjectStage.APPROVAL.value,
        ProjectStage.TENDER_PREPARATION.value,
        ProjectStage.TENDERING.value,
        ProjectStage.BID_EVALUATION.value,
    }

    for snapshot in engine.result_store.tick_snapshots:
        projects = snapshot.get("projects", {})
        for edge in snapshot.get("network", {}).get("edges", []):
            if edge.get("relation_type") != "owner_contractor":
                continue
            project = projects[edge["project_id"]]
            assert project["current_stage"] not in pre_award_stages


def test_generated_project_invariants_hold_across_lifecycle():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=70,
            random_seed=20260527,
            enable_project_generation=True,
            target_project_count=5,
            max_active_projects=3,
        )
    )
    engine.run()

    initiated_project_ids = {
        event.project_id
        for event in engine.events.events
        if event.event_type == "project_opportunity_initiated"
    }
    assert initiated_project_ids == set(engine.projects)

    for project in engine.projects.values():
        assert project.flags.get("owner_decision")
        assert project.owner_id in engine.agents
        first_tick_by_type = {}
        for event in project.event_log:
            first_tick_by_type.setdefault(event["event_type"], event["tick"])
        if not project.selected_contractor_id:
            continue
        submitted_bidder_ids = {
            event["data"]["contractor_id"]
            for event in project.event_log
            if event["event_type"] == "bid_submitted"
        }
        assert project.selected_contractor_id in submitted_bidder_ids
        assert any(event["event_type"] == "bid_evaluation_completed" for event in project.event_log)
        assert any(event["event_type"] == "contract_awarded" for event in project.event_log)
        assert first_tick_by_type["tender_opened"] < first_tick_by_type["bid_submitted"]
        assert first_tick_by_type["bid_submitted"] < first_tick_by_type["bid_evaluation_completed"]
        assert first_tick_by_type["bid_evaluation_completed"] < first_tick_by_type["contract_awarded"]
        assert all(
            engagement.start_stage == ProjectStage.TENDERING
            for engagement in project.engagements
            if engagement.role == "Contractor"
        )
        for engagement in project.engagements:
            if engagement.role == "Supplier":
                assert engagement.start_stage == ProjectStage.CONTRACT_AWARD
                assert engagement.joined_at_tick >= first_tick_by_type["contract_awarded"]
        if "construction_progress_updated" in first_tick_by_type:
            assert "supplier_selected" in first_tick_by_type
            assert first_tick_by_type["supplier_selected"] < first_tick_by_type["construction_progress_updated"]


def test_contractor_bid_events_include_business_assessment():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=30, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    bid_events = [
        event
        for event in project.event_log
        if event["event_type"] in {"bid_submitted", "bid_declined"}
    ]

    assert bid_events
    assert all("bid_probability" in event["data"] for event in bid_events)
    assert all("risk_level" in event["data"] for event in bid_events)
    assert all("expected_profit" in event["data"] for event in bid_events)
    assert all("decision_factors" in event["data"] for event in bid_events)
    assert all("decision_advisor" in event["data"] for event in bid_events)
    assert any(event["data"]["decision_advisor"]["available"] for event in bid_events)
    assert all(
        event["data"]["decision_advisor"]["available"]
        or event["data"]["decision_advisor"].get("skipped_reason") == "camel_tender_advisor_limit"
        for event in bid_events
    )
    assert any("tender_attractiveness" in event["data"]["decision_factors"] for event in bid_events)


def test_construction_events_capture_payment_and_inspection_details():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=35, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    progress_events = [
        event
        for event in project.event_log
        if event["event_type"] == "construction_progress_updated"
    ]
    payment_events = [
        event
        for event in project.event_log
        if event["event_type"] == "payment_requested"
    ]
    inspection_events = [
        event
        for event in project.event_log
        if event["event_type"] in {"inspection_passed", "inspection_failed"}
    ]

    assert progress_events
    assert payment_events
    assert inspection_events
    assert all("actual_progress" in event["data"] for event in progress_events)
    assert all("monthly_cost" in event["data"] for event in progress_events)
    assert all("payment_amount" in event["data"] for event in payment_events)
    assert all(event["data"]["payment_status"] in {"approved", "delayed"} for event in payment_events)
    assert all("pass_probability" in event["data"] for event in inspection_events)
    assert all("detected_defect_rate" in event["data"] for event in inspection_events)
    assert all("inspector_name" in event["data"] for event in inspection_events)
    assert all("inspection_type" in event["data"] for event in inspection_events)
    assert all("corrective_actions" in event["data"] for event in inspection_events)


def test_agent_history_includes_monthly_enterprise_operations():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=60,
            random_seed=9,
            enable_project_generation=True,
            target_project_count=5,
            max_active_projects=3,
        )
    )
    simulation_repository.add(engine)
    engine.run()

    released_agent_ids = [
        engagement.agent_id
        for project in engine.projects.values()
        for engagement in project.engagements
        if engagement.role in {"Contractor", "Supplier", "Architect", "QS"}
        and engagement.status == EngagementStatus.RELEASED
    ]
    assert released_agent_ids

    history = None
    for agent_id in released_agent_ids:
        candidate = simulation_runtime_service.agent_history(engine.simulation_id, agent_id)
        operation_labels = {
            row.get("data", {}).get("operation_label")
            for row in candidate["activity_timeline"]
            if row.get("event_type") in {"enterprise_operation", "out_of_project_operation"}
        }
        if len(operation_labels) >= 2:
            history = candidate
            break

    assert history is not None
    event_types = {row["event_type"] for row in history["activity_timeline"]}
    operation_labels = {
        row.get("data", {}).get("operation_label")
        for row in history["activity_timeline"]
        if row.get("event_type") in {"enterprise_operation", "out_of_project_operation"}
    }

    assert "agent_operation" not in event_types
    assert event_types & {"enterprise_operation", "out_of_project_operation"}
    assert len(operation_labels) >= 2


def test_agent_history_respects_playback_tick():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=60,
            random_seed=11,
            enable_project_generation=True,
            target_project_count=5,
            max_active_projects=3,
        )
    )
    simulation_repository.add(engine)
    engine.run()

    agent_id = next(iter(engine.agents))
    full_history = simulation_runtime_service.agent_history(engine.simulation_id, agent_id)
    tick_history = simulation_runtime_service.agent_history(engine.simulation_id, agent_id, tick=12)

    assert full_history["current_tick"] == engine.current_tick
    assert tick_history["current_tick"] == 12
    assert full_history["status_timeline"]
    assert tick_history["status_timeline"]
    assert max(row["tick"] for row in tick_history["status_timeline"]) <= 12
    assert max(row["tick"] for row in tick_history["activity_timeline"]) <= 12
    assert all(event["tick"] <= 12 for event in tick_history["events"])


def test_agent_history_returns_to_free_after_release_month():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=60,
            random_seed=17,
            enable_project_generation=True,
            target_project_count=6,
            max_active_projects=4,
        )
    )
    simulation_repository.add(engine)
    engine.run()

    released_agent_ids = [
        engagement.agent_id
        for project in engine.projects.values()
        for engagement in project.engagements
        if engagement.released_at_tick and engagement.released_at_tick < engine.current_tick
    ]
    assert released_agent_ids

    history = None
    release_tick = None
    for agent_id in released_agent_ids:
        candidate = simulation_runtime_service.agent_history(engine.simulation_id, agent_id)
        release_ticks = [
            int(event["tick"])
            for event in candidate["events"]
            if event.get("event_type") == "agent_released"
        ]
        if not release_ticks:
            continue
        candidate_release_tick = min(release_ticks)
        later_generated_rows = [
            row
            for row in candidate["activity_timeline"]
            if int(row.get("tick") or 0) > candidate_release_tick
            and row.get("data", {}).get("activity_source") == "generated_monthly_operation"
        ]
        if later_generated_rows:
            history = candidate
            release_tick = candidate_release_tick
            break

    assert history is not None
    assert release_tick is not None

    later_statuses = [
        row["status"]
        for row in history["status_timeline"]
        if int(row["tick"]) > release_tick
    ]
    assert later_statuses
    assert "released" not in later_statuses

    later_generated_rows = [
        row
        for row in history["activity_timeline"]
        if int(row.get("tick") or 0) > release_tick
        and row.get("data", {}).get("activity_source") == "generated_monthly_operation"
    ]
    assert later_generated_rows
    assert all(row["data"].get("status") != "released" for row in later_generated_rows)
