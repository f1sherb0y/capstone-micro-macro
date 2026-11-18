from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.agent_database import agent_database


def test_mvp_project_reaches_closed_without_stage_jump():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    assert project.current_stage == ProjectStage.CLOSED

    transitions = [
        event["data"]
        for event in project.event_log
        if event["event_type"] == "stage_transition"
    ]
    assert {"from_stage": "design", "to_stage": "construction"} not in transitions
    assert transitions[0] == {"from_stage": "initiation", "to_stage": "design"}
    assert transitions[-1] == {"from_stage": "final_account", "to_stage": "closed"}

    approval_event = next(event for event in project.event_log if event["event_type"] == "approval_approved")
    assert "design_quality" in approval_event["data"]
    assert "information_quality" in approval_event["data"]
    assert "procedural_uncertainty" in approval_event["data"]


def test_architect_standby_and_final_release_are_recorded():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=7))
    engine.run()
    project = engine.projects["P001"]

    architect_engagement = next(
        engagement for engagement in project.engagements if engagement.agent_id == project.selected_architect_id
    )
    assert architect_engagement.status == EngagementStatus.RELEASED
    assert any(event["event_type"] == "agent_standby" for event in project.event_log)
    assert any(event["event_type"] == "agent_released" for event in project.event_log)


def test_project_state_history_contains_quality_and_detected_defects():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=30, random_seed=42))
    engine.run()

    history = engine.result_store.get_project_performance("P001")
    assert history
    assert any(row["stage"] == "construction" for row in history)
    construction_rows = [row for row in history if row["stage"] == "construction"]
    assert all(row["detected_defect_rate"] <= row["defect_rate"] for row in construction_rows)
    assert any(event.event_type == "project_state_updated" for event in engine.events.events)


def test_representative_validation_does_not_call_primary_decision_provider():
    class ExplodingDecisionProvider:
        def decide(self, agent, context):
            raise AssertionError("guardrail validation should not call the primary decision provider")

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=5, random_seed=42))
    engine.lifecycle_engine.decision_provider = ExplodingDecisionProvider()
    project = engine.projects["P001"]

    # Run the guardrail-only validation directly. A full lifecycle now invokes
    # the provider for each subject's real appointment and stage decisions.
    engine.lifecycle_engine._validate_representative_actions(
        project,
        engine.agents,
        engine.policy,
        engine.macro_environment,
        tick=1,
    )

    assert not any(
        event["event_type"] == "stage_transition"
        and event["data"] == {"from_stage": "design", "to_stage": "construction"}
        for event in project.event_log
    )


def test_decision_context_includes_market_friction_and_collaboration_inputs():
    contexts = []

    class CaptureDecisionProvider:
        def decide(self, agent, context):
            contexts.append(context)
            return AgentAction(
                action_type=context["allowed_actions"][0],
                project_id=getattr(context.get("project"), "project_id", None),
                agent_id=agent.agent_id,
                decision=True,
                reason="captured context",
            )

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=25, random_seed=42))
    engine.lifecycle_engine.decision_provider = CaptureDecisionProvider()
    while engine.current_tick < engine.ticks and not any(
        context.get("decision_type") == "tender_decision" for context in contexts
    ):
        engine.step()

    tender_contexts = [context for context in contexts if context.get("decision_type") == "tender_decision"]
    assert tender_contexts
    assert all("macro_environment" in context for context in tender_contexts)
    assert all("regional_friction" in context for context in tender_contexts)
    assert all("previous_collaboration" in context for context in tender_contexts)
    assert all(context["stage_rule"].stage == ProjectStage.TENDERING for context in tender_contexts)


def test_every_invited_contractor_receives_an_individual_model_decision():
    contexts = []

    class CaptureDecisionProvider:
        def decide(self, agent, context):
            contexts.append(context)
            allowed_actions = context["allowed_actions"]
            return AgentAction(
                action_type="submit_bid" if "submit_bid" in allowed_actions else allowed_actions[0],
                project_id=getattr(context.get("project"), "project_id", None),
                agent_id=agent.agent_id,
                decision=True,
                data={"bid_probability": 0.9},
                reason="captured capped tender advisor",
            )

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=25, random_seed=42))
    engine.lifecycle_engine.decision_provider = CaptureDecisionProvider()
    engine.run()
    project = engine.projects["P001"]
    bid_events = [
        event
        for event in project.event_log
        if event["event_type"] in {"bid_submitted", "bid_declined"}
    ]

    tender_contexts = [
        context for context in contexts if context.get("decision_type") == "tender_decision"
    ]
    invited_ids = set(project.flags.get("invited_contractor_ids", []))
    decided_ids = {context["agent_profile"]["agent_id"] for context in tender_contexts}

    assert invited_ids
    assert decided_ids == invited_ids
    assert len(bid_events) == len(invited_ids)
    assert all(event["data"]["decision_advisor"].get("available") for event in bid_events)


def test_zhipu_default_tender_advisor_limit_is_conservative(monkeypatch):
    monkeypatch.delenv("CAMEL_TENDER_ADVISOR_LIMIT", raising=False)
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "ZHIPU")
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=5, random_seed=42))

    assert engine.lifecycle_engine.max_tender_camel_advisors == 1


def test_explicit_tender_advisor_limit_overrides_provider_default(monkeypatch):
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "ZHIPU")
    monkeypatch.setenv("CAMEL_TENDER_ADVISOR_LIMIT", "4")
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=5, random_seed=42))

    assert engine.lifecycle_engine.max_tender_camel_advisors == 4


def test_procurement_and_delivery_milestones_keep_real_project_order():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    first_tick_by_type = {}
    for event in project.event_log:
        first_tick_by_type.setdefault(event["event_type"], event["tick"])

    assert first_tick_by_type["tender_opened"] < first_tick_by_type["bid_submitted"]
    assert first_tick_by_type["bid_submitted"] < first_tick_by_type["bid_evaluation_completed"]
    assert first_tick_by_type["bid_evaluation_completed"] < first_tick_by_type["contract_negotiation_started"]
    assert first_tick_by_type["contract_negotiation_started"] < first_tick_by_type["contract_negotiation_recommendation"]
    assert first_tick_by_type["contract_negotiation_recommendation"] < first_tick_by_type["contract_awarded"]
    assert first_tick_by_type["contract_negotiation_started"] < first_tick_by_type["contract_awarded"]
    assert first_tick_by_type["contract_awarded"] <= first_tick_by_type["supplier_selected"]
    assert first_tick_by_type["supplier_selected"] < first_tick_by_type["construction_progress_updated"]
    assert first_tick_by_type["construction_progress_updated"] < first_tick_by_type["final_account_settled"]

    for engagement in project.engagements:
        if engagement.role == "Supplier":
            assert engagement.start_stage == ProjectStage.CONTRACT_AWARD
            assert engagement.joined_at_tick >= first_tick_by_type["contract_awarded"]

    final_account_event = next(event for event in project.event_log if event["event_type"] == "final_account_settled")
    assert final_account_event["data"]["final_account_amount"] >= final_account_event["data"]["contract_sum"]
    assert "claim_risk" in final_account_event["data"]
    assert "dispute_risk" in final_account_event["data"]

    tasks = agent_database.list_simulation_tasks(project_id=project.project_id, limit=50)
    task_types = {task["task_type"] for task in tasks}
    assert "design_coordination_task" in task_types
    assert "contractor_bid_decision_task" in task_types
    assert "construction_delivery_task" in task_types


def test_contract_supply_mobilization_and_closeout_are_not_collapsed():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    first_tick_by_type = {}
    for event in project.event_log:
        first_tick_by_type.setdefault(event["event_type"], event["tick"])

    assert first_tick_by_type["contract_negotiation_started"] < first_tick_by_type["contract_awarded"]
    assert first_tick_by_type["contract_awarded"] < first_tick_by_type["supplier_selected"]
    assert first_tick_by_type["supplier_selected"] < first_tick_by_type["mobilization_completed"]
    assert first_tick_by_type["mobilization_completed"] < first_tick_by_type["construction_progress_updated"]
    assert first_tick_by_type["completion_inspection_started"] < first_tick_by_type["project_completed"]
    assert first_tick_by_type["final_account_review_started"] < first_tick_by_type["final_account_settled"]


def test_project_interaction_sessions_are_created_for_key_negotiation_points():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    session_events = {
        event["event_type"]: event
        for event in project.event_log
        if event["event_type"].endswith("_session_started")
    }

    assert "tender_clarification_session_started" in session_events
    assert "contract_negotiation_session_started" in session_events
    assert "final_account_dispute_session_started" in session_events
    for event in session_events.values():
        assert event["data"]["session_id"].startswith(f"{project.project_id}:")
        assert len(event["data"]["session_participants"]) >= 2
        assert event["data"]["recent_messages"]
        assert event["data"]["summary"]


def test_contract_negotiation_records_bounded_recommendation_before_award():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    recommendation = next(
        event for event in project.event_log if event["event_type"] == "contract_negotiation_recommendation"
    )
    award = next(event for event in project.event_log if event["event_type"] == "contract_awarded")

    assert recommendation["tick"] < award["tick"]
    assert recommendation["data"]["selected_action"] in {
        "accept_terms",
        "request_revision",
        "escalate_dispute",
    }
    assert recommendation["data"]["stage_state_mutated"] is False
    assert recommendation["data"]["session_id"].endswith(":contract_negotiation")

    traces = agent_database.get_agent_decision_trace(project.selected_contractor_id, limit=50000)
    assert any(
        (trace.get("retry_info") or {}).get("decision_type") == "contract_negotiation"
        and trace.get("tick") == recommendation["tick"]
        and trace.get("selected_action") == recommendation["data"]["selected_action"]
        for trace in traces
    )


def test_project_event_log_obeys_lifecycle_invariants():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    stage_order = {
        "initiation": 0,
        "design": 1,
        "approval": 2,
        "statutory_approval": 2,
        "tender_preparation": 3,
        "tendering": 4,
        "bid_evaluation": 5,
        "contract_award": 6,
        "construction": 7,
        "completion": 8,
        "final_account": 9,
        "closed": 10,
    }
    transition_targets = [
        event["data"]["to_stage"]
        for event in project.event_log
        if event["event_type"] == "stage_transition"
        and event["data"].get("to_stage") not in {"failed", "suspended"}
    ]
    transition_values = [stage_order[stage] for stage in transition_targets if stage in stage_order]
    assert transition_values == sorted(transition_values)

    first_tick_by_type = {}
    for event in project.event_log:
        first_tick_by_type.setdefault(event["event_type"], event["tick"])

    required_order_pairs = [
        ("tender_opened", "bid_submitted"),
        ("bid_submitted", "bid_evaluation_completed"),
        ("bid_evaluation_completed", "contract_negotiation_session_started"),
        ("contract_negotiation_session_started", "contract_awarded"),
        ("contract_awarded", "supplier_selected"),
        ("supplier_selected", "mobilization_completed"),
        ("mobilization_completed", "construction_progress_updated"),
        ("construction_progress_updated", "completion_inspection_started"),
        ("completion_inspection_started", "project_completed"),
        ("project_completed", "final_account_review_started"),
        ("final_account_review_started", "final_account_settled"),
    ]
    for earlier, later in required_order_pairs:
        assert first_tick_by_type[earlier] < first_tick_by_type[later]

    expected_event_stage = {
        "tender_clarification_session_started": "tendering",
        "bid_evaluation_completed": "bid_evaluation",
        "contract_negotiation_session_started": "contract_award",
        "contract_awarded": "contract_award",
        "supplier_selected": "contract_award",
        "mobilization_completed": "contract_award",
        "construction_progress_updated": "construction",
        "completion_inspection_started": "completion",
        "final_account_dispute_session_started": "final_account",
        "final_account_settled": "final_account",
    }
    for event in project.event_log:
        expected_stage = expected_event_stage.get(event["event_type"])
        if expected_stage:
            assert event["stage"] == expected_stage


def test_construction_progress_tracks_planned_duration_without_artificial_stall():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()
    project = engine.projects["P001"]

    progress_events = [
        event
        for event in project.event_log
        if event["event_type"] == "construction_progress_updated"
    ]
    assert progress_events
    assert progress_events[-1]["data"]["actual_progress"] >= 1.0
    assert len(progress_events) <= project.performance.planned_duration + 4
    assert progress_events[-1]["data"]["delay_days"] <= 60


def test_explicit_tender_advisor_decision_controls_bid_outcome():
    class AlternatingTenderDecisionProvider:
        def __init__(self):
            self.tender_calls = 0

        def decide(self, agent, context):
            project_id = getattr(context.get("project"), "project_id", None)
            if context.get("decision_type") != "tender_decision":
                return AgentAction(
                    action_type=context["allowed_actions"][0],
                    project_id=project_id,
                    agent_id=agent.agent_id,
                    decision=True,
                    reason="Non-tender subject decision accepted for lifecycle setup.",
                )
            self.tender_calls += 1
            if self.tender_calls == 1:
                return AgentAction(
                    action_type="decline_bid",
                    project_id=project_id,
                    agent_id=agent.agent_id,
                    decision=False,
                    reason="Capacity is reserved for higher margin work.",
                )
            return AgentAction(
                action_type="decide_bid",
                project_id=project_id,
                agent_id=agent.agent_id,
                decision=True,
                data={"bid_probability": 0.01},
                reason="Project fits current tender strategy.",
            )

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=30, random_seed=42))
    engine.lifecycle_engine.decision_provider = AlternatingTenderDecisionProvider()
    engine.run()
    project = engine.projects["P001"]

    advised_bid_events = [
        event
        for event in project.event_log
        if event["event_type"] in {"bid_submitted", "bid_declined"}
        and event["data"]["decision_advisor"]["available"]
    ]

    assert advised_bid_events
    for event in advised_bid_events:
        action_type = event["data"]["decision_advisor"]["action_type"]
        if action_type == "decline_bid":
            assert event["event_type"] == "bid_declined"
        if action_type in {"submit_bid", "decide_bid"}:
            assert event["event_type"] == "bid_submitted"


def test_construction_variation_records_parties_and_resolution_details():
    class AlwaysTriggerVariation:
        def random(self):
            return 0.0

    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    project = engine.projects["P001"]
    while project.current_stage != ProjectStage.CONSTRUCTION:
        engine.step()

    engine.lifecycle_engine.rng = AlwaysTriggerVariation()
    project.performance.variation_risk = 0.85
    project.performance.design_quality = 0.62
    project.performance.actual_progress = 0.30
    project.performance.progress_deviation = -0.08
    project.performance.detected_defect_rate = 0.09
    project.performance.claim_risk = 0.24

    engine.step()
    requested = next(event for event in project.event_log if event["event_type"] == "variation_requested")

    assert requested["data"]["owner_id"] == project.owner_id
    assert requested["data"]["contractor_id"] == project.selected_contractor_id
    assert requested["data"]["architect_id"] == project.selected_architect_id
    assert requested["data"]["potential_impacts"] == ["programme delay", "variation cost", "claim risk"]

    engine.step()
    resolved = next(event for event in project.event_log if event["event_type"] == "variation_resolved")

    assert resolved["data"]["architect_id"] == project.selected_architect_id
    assert resolved["data"]["contractor_id"] == project.selected_contractor_id
    assert "resolved_progress" in resolved["data"]
