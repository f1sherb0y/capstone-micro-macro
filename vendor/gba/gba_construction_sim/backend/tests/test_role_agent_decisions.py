from __future__ import annotations

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.architect_agent import ArchitectAgent
from gba_construction_sim.backend.agents.base_agent import AgentDecision
from gba_construction_sim.backend.agents.owner_agent import OwnerAgent
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine


class _CapturingDecisionProvider:
    def __init__(self, decisions: dict[str, bool] | None = None, selected_choice: str | None = None):
        self.decisions = decisions or {}
        self.selected_choice = selected_choice
        self.calls = []

    def decide(self, agent, context):
        self.calls.append((agent, context))
        data = {"confidence": 0.83}
        choice_field = (context.get("decision_task") or {}).get("choice_output_field")
        if choice_field and self.selected_choice is not None:
            data[choice_field] = self.selected_choice
        return AgentAction(
            action_type=context["allowed_actions"][0],
            project_id=getattr(context.get("project"), "project_id", None),
            agent_id=agent.agent_id,
            decision=self.decisions.get(agent.agent_id, True),
            data=data,
            reason=f"{agent.name} made a bounded model decision from its own context.",
        )


def test_registry_keeps_one_persistent_decision_process_per_subject():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=2, random_seed=41))
    owner = next(agent for agent in engine.agents.values() if agent.role == "Owner")
    architect = next(agent for agent in engine.agents.values() if agent.role == "Architect")

    owner_behavior = engine.agent_registry.for_profile(owner)
    architect_behavior = engine.agent_registry.for_profile(architect)

    assert owner_behavior is engine.agent_registry.for_profile(owner)
    assert architect_behavior is engine.agent_registry.for_profile(architect)
    assert owner_behavior is not architect_behavior
    assert isinstance(owner_behavior, OwnerAgent)
    assert isinstance(architect_behavior, ArchitectAgent)
    assert owner_behavior.profile is owner
    assert architect_behavior.profile is architect
    assert owner_behavior.rng is not architect_behavior.rng


def test_lifecycle_records_each_subjects_independent_decision_before_selection():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=80, random_seed=42))
    engine.run()

    events_by_type = {}
    for event in engine.events.events:
        events_by_type.setdefault(event.event_type, []).append(event)

    for event_type in (
        "appointment_decision",
        "regulatory_review_decision",
        "contractor_tender_decision",
        "supplier_order_decision",
    ):
        assert events_by_type.get(event_type), f"missing auditable {event_type} events"

    independent_events = [
        *events_by_type["appointment_decision"],
        *events_by_type["regulatory_review_decision"],
        *events_by_type["contractor_tender_decision"],
        *events_by_type["supplier_order_decision"],
    ]
    assert all("accepted" in event.data for event in independent_events)
    assert all("utility" in event.data for event in independent_events)
    assert all("probability" in event.data for event in independent_events)
    assert all(event.data.get("decision_factors", {}).get("decision_process") for event in independent_events)

    project = engine.projects["P001"]
    consultant_event = next(
        event for event in project.event_log if event["event_type"] == "consultant_team_appointed"
    )
    selections = consultant_event["data"]["owner_selections"]
    assert selections["architect"]["selected_agent_id"] in selections["architect"]["accepted_agent_ids"]
    assert selections["qs"]["selected_agent_id"] in selections["qs"]["accepted_agent_ids"]

    supplier_event = next(event for event in project.event_log if event["event_type"] == "supplier_selected")
    contractor_decision = supplier_event["data"]["contractor_decision"]
    assert contractor_decision["selected_supplier_id"] in contractor_decision["accepted_supplier_ids"]


def test_monthly_operations_are_delegated_to_role_specific_agents():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=4, random_seed=19))
    engine.run()

    decisions = [
        event.data
        for event in engine.events.events
        if event.event_type == "agent_operation" and event.data.get("operation") != "fully_allocated"
    ]

    assert decisions
    assert all(data.get("decision_process", "").endswith(".decide_monthly_operation") for data in decisions)
    assert any(data["decision_process"].startswith("OwnerAgent.") for data in decisions)
    assert any(data["decision_process"].startswith("ContractorAgent.") for data in decisions)


def test_generated_project_financing_uses_independent_bank_offers_and_owner_choice():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=1,
            random_seed=42,
            enable_project_generation=True,
            target_project_count=1,
            max_active_projects=1,
        )
    )
    owner = next(agent for agent in engine.agents.values() if agent.role == "Owner")

    engine._rank_owner_project_decisions = lambda _opportunity, _target: [
        (owner, 0.95, 1.0, {"individual_accepted": True})
    ]
    engine._owner_initiation_advisor = lambda owner_agent, project_id, *_args, **_kwargs: AgentAction(
        action_type="initiate_project",
        project_id=project_id,
        agent_id=owner_agent.agent_id,
        decision=True,
        reason="Owner confirmed the independently selected opportunity.",
    )

    engine.step(return_snapshot=False)

    project = engine.projects["PGEN0001"]
    bank_events = [event for event in engine.events.events if event.event_type == "bank_financing_decision"]
    owner_event = next(event for event in engine.events.events if event.event_type == "project_financing_selected")

    assert bank_events
    assert all(event.data["decision_factors"]["decision_process"] == "BankAgent.consider_financing" for event in bank_events)
    assert project.selected_bank_id == owner_event.data["selected_bank_id"]
    assert project.selected_bank_id in owner_event.data["accepted_bank_ids"]
    assert owner_event.data["decision_factors"]["decision_process"] == "OwnerAgent.select_financing_offer"


def test_llm_agent_uses_own_identity_background_memory_and_can_reject_local_proposal():
    owner = EnterpriseAgentProfile(
        agent_id="O_LLM_001",
        name="Cautious Owner",
        role="Owner",
        region="Hong Kong",
        enterprise_type="developer",
        semantic_memory={"investment_mandate": "Protect liquidity and prefer phased delivery."},
        episodic_memory=[{"tick": 1, "event": "prior_delay", "impact": "high"}],
    )
    provider = _CapturingDecisionProvider({owner.agent_id: False})
    scheduler = EnterpriseDecisionScheduler(
        provider,
        tick_max_decisions=50,
        project_max_decisions=50,
        agent_max_decisions=50,
    )
    registry = AgentBehaviorRegistry([owner], random_seed=7, decision_scheduler=scheduler)
    local_evidence = AgentDecision(
        action_type="initiate_project",
        accepted=True,
        utility=0.92,
        probability=0.90,
        reason="Formal evidence suggests the opportunity is financially attractive.",
        factors={"net_present_value_fit": 0.92},
    )

    resolved = registry.resolve_decision(
        owner,
        local_evidence,
        decision_type="owner_investment_decision",
        tick=2,
        priority=DecisionPriority.P0_STAGE_CRITICAL,
    )

    assert resolved.accepted is False
    assert resolved.factors["decision_source"] == "llm_agent"
    assert resolved.utility == local_evidence.utility
    assert owner.episodic_memory[-1]["decision_type"] == "owner_investment_decision"
    assert owner.episodic_memory[-1]["accepted"] is False
    called_agent, context = provider.calls[0]
    assert called_agent is owner
    assert context["agent_profile"]["agent_id"] == owner.agent_id
    assert context["agent_background"]["investment_mandate"].startswith("Protect liquidity")
    assert context["agent_recent_episodes"][0]["event"] == "prior_delay"
    assert context["cognitive_context"]["background_summary"]["investment_mandate"].startswith("Protect liquidity")


def test_each_llm_subject_keeps_an_isolated_context_and_episode_stream():
    first = EnterpriseAgentProfile(
        agent_id="C_LLM_A",
        name="Contractor A",
        role="Contractor",
        region="Shenzhen",
        enterprise_type="contractor",
        semantic_memory={"specialism": "high-rise"},
    )
    second = EnterpriseAgentProfile(
        agent_id="C_LLM_B",
        name="Contractor B",
        role="Contractor",
        region="Macau",
        enterprise_type="contractor",
        semantic_memory={"specialism": "hospitality"},
    )
    provider = _CapturingDecisionProvider({first.agent_id: True, second.agent_id: False})
    registry = AgentBehaviorRegistry(
        [first, second],
        decision_scheduler=EnterpriseDecisionScheduler(
            provider,
            tick_max_decisions=50,
            project_max_decisions=50,
            agent_max_decisions=50,
        ),
    )
    evidence = AgentDecision(
        action_type="submit_bid",
        accepted=True,
        utility=0.7,
        probability=0.7,
        reason="Formal tender evidence is available.",
    )

    first_result = registry.resolve_decision(first, evidence, decision_type="bid", tick=3)
    second_result = registry.resolve_decision(second, evidence, decision_type="bid", tick=3)

    assert first_result.accepted is True
    assert second_result.accepted is False
    assert first.episodic_memory[-1]["decision_type"] == "bid"
    assert second.episodic_memory[-1]["decision_type"] == "bid"
    assert len(first.episodic_memory) == 1
    assert len(second.episodic_memory) == 1
    first_context = provider.calls[0][1]
    second_context = provider.calls[1][1]
    assert first_context["agent_profile"]["semantic_memory"]["specialism"] == "high-rise"
    assert second_context["agent_profile"]["semantic_memory"]["specialism"] == "hospitality"
    assert first_context["agent_profile"]["agent_id"] != second_context["agent_profile"]["agent_id"]


def test_environment_rejects_llm_choice_outside_the_bounded_candidate_set():
    owner = EnterpriseAgentProfile(
        agent_id="O_LLM_CHOICE",
        name="Selecting Owner",
        role="Owner",
        region="Shenzhen",
        enterprise_type="developer",
    )
    provider = _CapturingDecisionProvider(selected_choice="NOT_A_CANDIDATE")
    registry = AgentBehaviorRegistry(
        [owner],
        decision_scheduler=EnterpriseDecisionScheduler(
            provider,
            tick_max_decisions=20,
            project_max_decisions=20,
            agent_max_decisions=20,
        ),
    )
    proposal = AgentDecision(
        action_type="select_architect",
        accepted=True,
        utility=0.8,
        probability=1.0,
        reason="One bounded architect candidate is available.",
        data={"selected_agent_id": "A_VALID"},
    )

    resolved = registry.resolve_decision(
        owner,
        proposal,
        decision_type="owner_select_architect",
        tick=4,
        choice_options=[{"id": "A_VALID", "name": "Valid Architect"}],
        choice_field="selected_agent_id",
    )

    assert resolved.accepted is False
    assert resolved.data.get("selected_agent_id") is None
    assert resolved.data["choice_source"] == "invalid_llm_choice_rejected"
