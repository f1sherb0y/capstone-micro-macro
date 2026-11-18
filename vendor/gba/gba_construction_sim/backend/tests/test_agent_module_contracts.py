import pytest

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.contracts import (
    AGENT_MODULE_CONTRACT_VERSION,
    AgentDecisionRequestV1,
    AgentDecisionResponseV1,
    AgentModulePort,
    AgentProposalResponseV1,
)
from gba_construction_sim.backend.agents.external_adapter import (
    AgentModuleIntegrationError,
    ExternalAgentDecisionProvider,
    ExternalAgentModuleAdapter,
)
from gba_construction_sim.backend.agents.operation_specs import (
    get_operation_contract,
    list_operation_contracts,
)
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.simulation.stage_rule_registry import StageRuleRegistry


def _agent(agent_id: str = "OWNER-EXT") -> EnterpriseAgentProfile:
    return EnterpriseAgentProfile(
        agent_id=agent_id,
        name="External Owner",
        role="Owner",
        region="Hong Kong",
        enterprise_type="developer",
        financial_capacity=0.78,
        risk_preference=0.42,
        semantic_memory={
            "identity_background": {"mandate": "Build a resilient cross-border project portfolio."}
        },
        episodic_memory=[{"tick": 2, "event_type": "project_screened", "result": "deferred"}],
    )


def _project() -> ConstructionProject:
    return ConstructionProject(
        project_id="P-EXT",
        name="External Integration Project",
        project_type="building",
        region="Shenzhen",
        owner_id="OWNER-EXT",
        initial_budget=120_000_000,
    )


class _CapturingClient:
    def __init__(self) -> None:
        self.decision_requests: list[AgentDecisionRequestV1] = []
        self.proposal_requests = []
        self.observations = []

    def decide(self, request):
        self.decision_requests.append(request)
        return AgentDecisionResponseV1(
            request_id=request.request_id,
            agent_id=request.agent.agent_id,
            action_type=request.constraints.allowed_actions[0],
            decision=True,
            reason="The agent accepted the bounded option after reviewing its own state.",
            confidence=0.81,
            data={"selected_agent_id": "ARCH-1"},
        )

    def propose(self, request):
        self.proposal_requests.append(request)
        return AgentProposalResponseV1(
            request_id=request.request_id,
            action_type="initiate_project",
            accepted=True,
            utility=0.73,
            probability=0.68,
            reason="Professional evidence supports project initiation.",
            factors={"formal_evidence_owner": "simulation_core"},
            data={"selected_concept": request.inputs["opportunity"]},
        )

    def observe(self, observation):
        self.observations.append(observation)


def test_external_provider_receives_complete_versioned_decision_package():
    agent = _agent()
    project = _project()
    policy = PolicyRegime()
    environment = MacroEnvironment(current_tick=4)
    stage_rule = StageRuleRegistry().get(project.current_stage)
    context = DecisionRequestCollector().standard_context(
        agent,
        {
            "request_id": "REQ-EXT-1",
            "tick": 4,
            "project": project,
            "policy": policy,
            "macro_environment": environment,
            "stage_rule": stage_rule,
            "allowed_actions": ["select_architect", "defer_appointment"],
            "decision_task": {
                "objective": "Choose one architect from the bounded shortlist.",
                "candidate_options": [{"id": "ARCH-1", "name": "Architect One"}],
                "choice_output_field": "selected_agent_id",
            },
            "decision_support": {"ranked_candidate_ids": ["ARCH-1"]},
        },
        decision_type="owner_select_architect",
        project=project,
        stage_rule=stage_rule,
        allowed_actions=["select_architect", "defer_appointment"],
    )
    client = _CapturingClient()

    action = ExternalAgentDecisionProvider(client).decide(agent, context)

    request = client.decision_requests[0]
    assert request.contract_version == AGENT_MODULE_CONTRACT_VERSION
    assert request.agent.agent_id == agent.agent_id
    assert request.agent.background["identity_background"]["mandate"]
    assert request.memory["recent_episodes"][0]["result"] == "deferred"
    assert request.project["project_id"] == project.project_id
    assert request.environment["current_tick"] == 4
    assert request.policy
    assert request.stage_rule["stage"] == project.current_stage.value
    assert request.decision_task["objective"].startswith("Choose one architect")
    assert request.candidate_options[0]["id"] == "ARCH-1"
    assert request.choice_contract.output_field == "selected_agent_id"
    assert request.constraints.state_mutation_owner == "simulation_core"
    assert action.agent_id == agent.agent_id
    assert action.data["confidence"] == 0.81


def test_external_provider_rejects_simulation_state_mutation():
    class MutatingClient(_CapturingClient):
        def decide(self, request):
            return {
                "contract_version": AGENT_MODULE_CONTRACT_VERSION,
                "request_id": request.request_id,
                "agent_id": request.agent.agent_id,
                "action_type": request.constraints.allowed_actions[0],
                "decision": True,
                "reason": "Attempted invalid mutation.",
                "data": {"current_stage": "Closed"},
            }

    agent = _agent()
    context = {
        "request_id": "REQ-MUTATION",
        "tick": 1,
        "decision_type": "test_decision",
        "allowed_actions": ["maintain_operations"],
    }

    with pytest.raises(AgentModuleIntegrationError, match="simulation-owned state"):
        ExternalAgentDecisionProvider(MutatingClient()).decide(agent, context)


def test_external_module_supports_proposals_and_committed_event_observations():
    client = _CapturingClient()
    agent = _agent()
    project = _project()
    module = ExternalAgentModuleAdapter(client, [agent], random_seed=3)

    proposal = module.propose(
        agent,
        "evaluate_project_opportunity",
        opportunity={
            "name": "External Integration Project",
            "project_type": "building",
            "region": "Shenzhen",
            "scale": "medium",
            "budget": 120_000_000,
            "technical_complexity": 0.5,
            "planned_duration": 24,
        },
        macro_environment=MacroEnvironment(current_tick=5),
        policy=PolicyRegime(),
        active_project_count=1,
        target_pressure=0.3,
    )
    events = EventSystem(observers=[module.observe_event])
    events.record(
        5,
        "project_initiated",
        "Owner initiated the project after validation.",
        project=project,
        agent_id=agent.agent_id,
        data={"decision_committed": True},
    )

    assert proposal.accepted is True
    assert client.proposal_requests[0].operation == "evaluate_project_opportunity"
    assert client.proposal_requests[0].operation_contract.contract_id == "Owner.evaluate_project_opportunity.v1"
    assert client.proposal_requests[0].inputs["opportunity"]["budget"] == 120_000_000
    assert client.observations[0].event_type == "project_initiated"
    assert client.observations[0].committed is True
    assert client.observations[0].project_snapshot["project_id"] == project.project_id


def test_every_runtime_operation_has_a_role_specific_contract():
    expected = {
        ("evaluate_project_opportunity", "Owner"),
        ("consider_financing", "Bank"),
        ("select_financing_offer", "Owner"),
        ("consider_appointment", "Architect"),
        ("consider_appointment", "Engineer"),
        ("consider_appointment", "QS"),
        ("select_appointment", "Owner"),
        ("consider_review_assignment", "Government"),
        ("decide_approval", "Government"),
        ("select_tender_invitees", "Owner"),
        ("consider_tender", "Contractor"),
        ("evaluate_bid", "QS"),
        ("select_preferred_bid", "Owner"),
        ("decide_contract_award", "Owner"),
        ("decide_contract_terms", "Contractor"),
        ("consider_supply_order", "Supplier"),
        ("select_supplier", "Contractor"),
    }
    contracts = list_operation_contracts()
    available = {(contract.operation, contract.role) for contract in contracts}

    assert expected <= available
    assert all(contract.inputs for contract in contracts)
    assert all(contract.actions for contract in contracts)
    assert get_operation_contract("consider_appointment", "Architect").contract_id.endswith(".v1")


def test_external_module_rejects_an_invalid_operation_response_shape():
    class InvalidProposalClient(_CapturingClient):
        def propose(self, request):
            return AgentProposalResponseV1(
                request_id=request.request_id,
                action_type="unknown_action",
                accepted=True,
                utility=0.7,
                probability=0.7,
                reason="Invalid operation response.",
                data={},
            )

    module = ExternalAgentModuleAdapter(InvalidProposalClient(), [_agent()])

    with pytest.raises(AgentModuleIntegrationError, match="invalid action/accepted pair"):
        module.propose(
            _agent(),
            "evaluate_project_opportunity",
            opportunity={
                "name": "Test",
                "project_type": "building",
                "region": "Shenzhen",
                "scale": "small",
                "budget": 60_000_000,
                "technical_complexity": 0.4,
                "planned_duration": 18,
            },
            macro_environment=MacroEnvironment(current_tick=1),
            policy=PolicyRegime(),
            active_project_count=0,
            target_pressure=0.2,
        )


def test_external_module_rejects_missing_action_payload_fields():
    class MissingDataClient(_CapturingClient):
        def propose(self, request):
            return AgentProposalResponseV1(
                request_id=request.request_id,
                action_type="initiate_project",
                accepted=True,
                utility=0.7,
                probability=0.7,
                reason="Missing the required selected concept payload.",
                data={},
            )

    module = ExternalAgentModuleAdapter(MissingDataClient(), [_agent()])

    with pytest.raises(AgentModuleIntegrationError, match="missing required field 'selected_concept'"):
        module.propose(
            _agent(),
            "evaluate_project_opportunity",
            opportunity={
                "name": "Test",
                "project_type": "building",
                "region": "Shenzhen",
                "scale": "small",
                "budget": 60_000_000,
                "technical_complexity": 0.4,
                "planned_duration": 18,
            },
            macro_environment=MacroEnvironment(current_tick=1),
            policy=PolicyRegime(),
            active_project_count=0,
            target_pressure=0.2,
        )


def test_simulation_engine_accepts_an_injected_agent_module():
    class RecordingModule(AgentBehaviorRegistry):
        def __init__(self):
            super().__init__()
            self.observed = []

        def observe_event(self, event, project=None):
            self.observed.append((event.event_type, getattr(project, "project_id", None)))

    module = RecordingModule()
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(ticks=1, random_seed=8),
        agent_module=module,
    )

    assert isinstance(module, AgentModulePort)
    assert engine.agent_module is module
    assert engine.agent_registry is module
    assert module.health().details["registered_agents"] == len(engine.agents)
    capabilities = module.capabilities()
    assert len(capabilities.operation_contracts) == 25
    assert "evaluate_project_opportunity" in capabilities.proposal_operations

    project = next(iter(engine.projects.values()))
    engine.events.record(0, "integration_probe", "Integration probe", project=project)
    assert module.observed[-1] == ("integration_probe", project.project_id)
