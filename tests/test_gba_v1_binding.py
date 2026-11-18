"""Synthetic offline answers validate wiring, never model/business quality."""
import pytest

from integration.agent_client import GbaV1AgentClient, AgentClientError
from integration.bindings.gba_v1 import build_module_engine
from integration.observations import ObservationInbox
from gba_construction_sim.backend.agents.contracts import (
    AgentDecisionRequestV1, AgentDecisionResponseV1, AgentObservationV1,
    AgentProposalRequestV1, AgentProposalResponseV1, identity_from_profile,
)
from gba_construction_sim.backend.agents.operation_specs import get_operation_contract
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest


ROLES = ("Owner", "Bank", "Architect", "Engineer", "QS", "Government", "Contractor", "Supplier")
VERSIONS = {key: "offline-fixture-v1" for key in ("client", "skill", "prompt", "contract", "method", "model", "strategy")}


def inputs():
    agents = [EnterpriseAgentProfile(agent_id=role, name=f"Synthetic {role}", role=role,
                                    region="Hong Kong", enterprise_type="synthetic_fixture") for role in ROLES]
    project = ConstructionProject(project_id="fixture-project", name="Synthetic suspended project",
                                  project_type="building", region="Hong Kong", owner_id="Owner",
                                  initial_budget=1000, current_stage="suspended")
    return SimulationCreateRequest(agent_source="explicit", agents=agents, initial_projects=[project],
                                   use_prior_network_edges=False, enable_project_generation=False, ticks=1)


class Handlers:
    def __init__(self):
        self.proposals, self.decisions = [], []

    def propose(self, request):
        self.proposals.append(request)
        action = request.operation_contract.actions[0].action_type
        return AgentProposalResponseV1(request_id=request.request_id, action_type=action,
            accepted=True, utility=.5, probability=.5, reason="Synthetic wiring fixture",
            data={"label": "Fixture proposal", "description": "Synthetic monthly operation"})

    def decide(self, request):
        self.decisions.append(request)
        return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
            action_type="maintain_operations", decision=True, reason="Synthetic final choice differs from proposal")


def make_client(tmp_path, handlers=None, run_id="run-1", task_path=None):
    handlers = handlers or Handlers()
    return GbaV1AgentClient(run_id=run_id, organization_roles={role: role for role in ROLES},
        proposal_handlers={(role, "decide_monthly_operation"): handlers.propose for role in ROLES},
        decision_handler=handlers.decide, versions=VERSIONS, inbox_path=tmp_path / "observations.json",
        task_path=task_path)


def decision_request(request_id="same-id", tick=1):
    return AgentDecisionRequestV1(request_id=request_id, tick=tick, decision_type="monthly_enterprise_operation",
        priority="P3_BACKGROUND", agent=identity_from_profile(inputs().agents[0]),
        constraints={"allowed_actions": ["maintain_operations", "screen_investment_pipeline"]})


def observation(event_id="EVT1", agent_id="Owner", data=None):
    return AgentObservationV1(event_id=event_id, tick=1, event_type="agent_operation", agent_id=agent_id,
        description="Synthetic event", data=data or {"operation": "maintain_operations", "secret_bid": 100},
        project_snapshot={"competitor_private_finance": 500})


def test_engine_calls_both_external_paths_and_records_final_feedback_once(tmp_path):
    handlers = Handlers()
    client = make_client(tmp_path, handlers)
    assembly = build_module_engine(inputs(), client)
    assembly.engine.step(False)

    assert len(handlers.proposals) == len(ROLES)
    assert len(handlers.decisions) == len(ROLES)
    assert {request.agent.role for request in handlers.proposals} == set(ROLES)
    events = [event for event in assembly.engine.events.events if event.event_type == "agent_operation"]
    assert len(events) == len(ROLES)
    for event in events:
        assert event.data["operation"] == "maintain_operations"
        records = client.inbox.for_organization(run_id=client.run_id, organization_id=event.agent_id)
        assert len(records) == 1
        assert records[0]["event_id"] == event.event_id
        assert records[0]["payload"]["data"]["operation"] == event.data["operation"]
        assert records[0]["payload"]["agent_id"] == event.agent_id
    calls = assembly.evidence()["client"]["calls"]
    assert sum(row["purpose"] == "observe" and row["status"] == "recorded" for row in calls) == len(ROLES)
    assert sum(row["purpose"] == "observe" and row["status"] == "duplicate" for row in calls) == len(ROLES)
    assert all(not event.data.get("agent_observer_errors") for event in events)


def test_native_async_decision_reenters_writer_guard_on_original_thread(tmp_path):
    import asyncio
    import threading
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider

    handlers, writer_guard = Handlers(), threading.RLock()
    original_thread = threading.get_ident()
    client = make_client(tmp_path, handlers)
    build_module_engine(inputs(), client)

    def guarded(request):
        # Check before acquiring the guard so a regression fails rather than
        # deadlocking the test in the original offloaded worker thread.
        assert threading.get_ident() == original_thread
        with writer_guard:
            return handlers.decide(request)

    client.decision_handler = guarded
    context = {'request_id': 'native-async-final', 'tick': 1,
        'decision_type': 'monthly_enterprise_operation', 'allowed_actions': ['maintain_operations']}
    try:
        with writer_guard:
            result = asyncio.run(ExternalAgentDecisionProvider(client).decide_async(inputs().agents[0], context))
        assert result.action_type == 'maintain_operations'
        # The original native request ID and journal/cache path are retained.
        assert len(handlers.decisions) == 1
        assert client.decide(handlers.decisions[0]).request_id == 'native-async-final'
        assert len(handlers.decisions) == 1
    finally:
        client.close()


def test_capabilities_only_advertise_explicit_operations_and_health_is_local(tmp_path):
    client = make_client(tmp_path)
    capabilities = client.capabilities()
    assert len(capabilities.operation_contracts) == 8
    assert capabilities.proposal_operations == ["decide_monthly_operation"]
    assert client.health().status == "unattached"
    request = AgentProposalRequestV1(request_id="unsupported", operation="evaluate_project_opportunity",
                                    agent=identity_from_profile(inputs().agents[0]))
    with pytest.raises(AgentClientError, match="Unsupported proposal"):
        client.propose(request)


def test_success_cache_preserves_request_id_and_rejects_input_or_version_reuse(tmp_path):
    handlers = Handlers()
    client = make_client(tmp_path, handlers)
    first = client.decide(decision_request())
    first.reason = "caller mutation"
    second = client.decide(decision_request())
    assert second.request_id == "same-id" and second.reason != first.reason
    assert len(handlers.decisions) == 1
    with pytest.raises(AgentClientError, match="different input"):
        client.decide(decision_request(tick=2))
    client.versions["skill"] = "changed"
    with pytest.raises(AgentClientError, match="versions"):
        client.decide(decision_request())


def test_independent_runs_never_share_cache_or_observation_store(tmp_path):
    handlers = Handlers()
    first = make_client(tmp_path / "first", handlers, "run-1")
    second = make_client(tmp_path / "second", handlers, "run-2")
    first.decide(decision_request())
    second.decide(decision_request())
    assert len(handlers.decisions) == 2
    first.observe(observation())
    with pytest.raises(ValueError, match="another run"):
        make_client(tmp_path / "first", run_id="run-2")


def test_technical_failure_can_retry_without_caching_failure(tmp_path):
    handlers = Handlers()
    client = make_client(tmp_path, handlers)
    def fail(request):
        raise RuntimeError("fixture transport failure")
    client.decision_handler = fail
    with pytest.raises(RuntimeError, match="transport"):
        client.decide(decision_request())
    client.decision_handler = handlers.decide
    assert client.decide(decision_request()).decision
    assert [row["status"] for row in client.evidence()["calls"]] == ["failed", "returned"]


@pytest.mark.parametrize("kind", ["action", "agent", "request", "version", "mutation", "extra",
                                  "nan", "infinity", "nested_infinity", "model_nan"])
def test_invalid_decisions_never_enter_cache(tmp_path, kind):
    client = make_client(tmp_path)
    response = Handlers().decide(decision_request()).model_dump(mode="json")
    changes = {
        "action": {"action_type": "unbounded_action"}, "agent": {"agent_id": "Bank"},
        "request": {"request_id": "changed"}, "version": {"contract_version": "unknown"},
        "mutation": {"data": {"current_stage": "closed"}}, "extra": {"unexpected": True},
        "nan": {"data": {"value": float("nan")}},
        "infinity": {"data": {"value": float("inf")}},
        "nested_infinity": {"data": {"values": [{"value": float("-inf")}] }},
        "model_nan": {"data": {"value": float("nan")}},
    }
    response.update(changes[kind])
    if kind == "model_nan":
        response = AgentDecisionResponseV1.model_validate(response)
    client.decision_handler = lambda request: response
    with pytest.raises((ValueError, RuntimeError)):
        client.decide(decision_request())
    assert not client._cache


def test_requests_reject_wrong_role_version_and_simulation(tmp_path):
    client = make_client(tmp_path)
    request = decision_request()
    request.agent.role = "Bank"
    with pytest.raises(AgentClientError, match="role"):
        client.decide(request)
    request = decision_request()
    request.contract_version = "unknown"
    with pytest.raises(AgentClientError, match="version"):
        client.decide(request)
    request = decision_request()
    request.metadata["simulation_id"] = "another-simulation"
    with pytest.raises(AgentClientError, match="another simulation"):
        client.decide(request)


def test_observations_trim_private_data_and_deduplicate_across_restart(tmp_path):
    client = make_client(tmp_path)
    client.observe(observation())
    client.observe(observation())
    records = client.inbox.for_organization(run_id="run-1", organization_id="Owner")
    assert len(records) == 1
    assert "secret_bid" not in records[0]["payload"]["data"]
    assert "project_snapshot" not in records[0]["payload"]
    assert not client.inbox.for_organization(run_id="run-1", organization_id="Bank")
    restored = make_client(tmp_path)
    restored.observe(observation())
    assert len(restored.inbox.for_organization(run_id="run-1", organization_id="Owner")) == 1
    assert restored.evidence()["calls"][0]["status"] == "duplicate"
    with pytest.raises(ValueError, match="Immutable"):
        restored.observe(observation(data={"operation": "changed"}))


def test_observations_require_known_committed_event_and_stable_identity(tmp_path):
    client = make_client(tmp_path)
    for updates in ({"event_type": "unknown"}, {"committed": False}, {"agent_id": "competitor"}):
        client.observe(observation().model_copy(update=updates))
    assert not client.inbox.for_organization(run_id="run-1", organization_id="Owner")
    with pytest.raises(AgentClientError, match="Stable event"):
        client.observe(observation(event_id=""))


def test_inbox_recipient_specific_dedup_and_run_isolation(tmp_path):
    inbox = ObservationInbox("run-1", ["Owner", "Bank"], tmp_path / "inbox.json")
    for organization in ("Owner", "Bank"):
        assert inbox.deliver(run_id="run-1", event_id="same", organization_id=organization, payload={})
    with pytest.raises(ValueError, match="run or recipient"):
        inbox.deliver(run_id="run-2", event_id="new", organization_id="Owner", payload={})
    with pytest.raises(ValueError, match="run or recipient"):
        inbox.for_organization(run_id="run-1", organization_id="competitor")


def test_engine_rejects_client_reuse_mixed_procurement_and_provider_drift(tmp_path):
    client = make_client(tmp_path)
    assembly = build_module_engine(inputs(), client)
    with pytest.raises(AgentClientError, match="shared"):
        build_module_engine(inputs(), client)
    assembly.engine.lifecycle_engine.decision_provider = object()
    with pytest.raises(AgentClientError, match="no longer share"):
        assembly.evidence()
    request = inputs()
    request.procurement_execution = request.procurement_execution.model_copy(update={"mode": "codedemo_micro"})
    with pytest.raises(AgentClientError, match="also own"):
        build_module_engine(request, make_client(tmp_path / "other"))


def test_proposal_contract_and_mutations_are_checked_before_caching(tmp_path):
    client = make_client(tmp_path)
    contract = get_operation_contract("decide_monthly_operation", "Owner")
    request = AgentProposalRequestV1(request_id="proposal-1", operation=contract.operation,
        agent=identity_from_profile(inputs().agents[0]), operation_contract=contract,
        inputs={"macro_environment": {"current_tick": 1}})
    result = client.propose(request)
    assert result.request_id == request.request_id
    assert client.propose(request) == result
    altered = request.model_copy(deep=True)
    altered.operation_contract.actions = []
    with pytest.raises(AgentClientError, match="registered operation"):
        client.propose(altered)
    bad_response = result.model_dump(mode="json")
    bad_response["data"]["occupied_resource"] = 1
    client.proposal_handlers[("Owner", contract.operation)] = lambda request: bad_response
    request.request_id = "new-proposal"
    bad_response["request_id"] = request.request_id
    with pytest.raises(AgentClientError, match="simulation-owned"):
        client.propose(request)


def test_durable_decision_recovery_revalidates_without_calling_handler(tmp_path):
    path, handlers = tmp_path / "tasks.sqlite", Handlers()
    client = make_client(tmp_path, handlers, task_path=path)
    first = client.decide(decision_request())
    client.close()
    restored = make_client(tmp_path, handlers, task_path=path)
    assert restored.decide(decision_request()) == first
    assert len(handlers.decisions) == 1
    assert restored.evidence()["calls"][0]["recovered"]
    rows = restored.tasks.for_organization(run_id="run-1", organization_id="Owner")
    assert len(rows) == 1 and rows[0]["state"] == "output_formed"
    assert rows[0]["receipt"] is None and rows[0]["submission"] is None
    with pytest.raises(AgentClientError, match="different input"):
        restored.decide(decision_request(tick=2))
    restored.close()


def test_durable_proposal_and_final_decision_remain_independent(tmp_path):
    path, handlers = tmp_path / "tasks.sqlite", Handlers()
    contract = get_operation_contract("decide_monthly_operation", "Owner")
    proposal = AgentProposalRequestV1(request_id="same-id", operation=contract.operation,
        agent=identity_from_profile(inputs().agents[0]), operation_contract=contract,
        inputs={"macro_environment": {"current_tick": 1}})
    client = make_client(tmp_path, handlers, task_path=path)
    first_proposal, first_decision = client.propose(proposal), client.decide(decision_request())
    client.close()
    restored = make_client(tmp_path, handlers, task_path=path)
    assert restored.propose(proposal) == first_proposal
    assert restored.decide(decision_request()) == first_decision
    assert len(handlers.proposals) == len(handlers.decisions) == 1
    assert len(restored.evidence()["tasks"]["Owner"]) == 2
    restored.close()


def test_durable_failed_processing_can_retry_same_input(tmp_path):
    path, handlers = tmp_path / "tasks.sqlite", Handlers()
    client = make_client(tmp_path, handlers, task_path=path)
    def fail(request):
        raise RuntimeError("fixture handler failure")
    client.decision_handler = fail
    with pytest.raises(RuntimeError):
        client.decide(decision_request())
    client.close()
    restored = make_client(tmp_path, handlers, task_path=path)
    restored.decide(decision_request())
    assert len(handlers.decisions) == 1
    assert restored.evidence()["tasks"]["Owner"][0]["state"] == "output_formed"
    restored.close()


def test_interrupted_client_processing_requires_host_diagnosis(tmp_path):
    path = tmp_path / "tasks.sqlite"
    client = make_client(tmp_path, task_path=path)
    def interrupted(request):
        raise SystemExit("fixture worker interruption")
    client.decision_handler = interrupted
    with pytest.raises(SystemExit):
        client.decide(decision_request())
    client.close()
    handlers = Handlers()
    restored = make_client(tmp_path, handlers, task_path=path)
    with pytest.raises(AgentClientError, match="processing does not permit"):
        restored.decide(decision_request())
    assert not handlers.decisions
    restored.close()


def test_durable_client_cannot_claim_a_fresh_engine_is_a_macro_resume(tmp_path):
    path = tmp_path / "tasks.sqlite"
    client = make_client(tmp_path, task_path=path)
    client.claim(client.organization_roles)
    client.attach("original-simulation")
    client.decide(decision_request())
    client.close()
    restored = make_client(tmp_path, task_path=path)
    restored.claim(restored.organization_roles)
    with pytest.raises(AgentClientError, match="another simulation"):
        restored.attach("new-simulation")
    assert restored.simulation_id is None
    restored.attach("original-simulation")
    restored.decide(decision_request())
    assert restored.evidence()["calls"][0]["status"] == "cache_hit"
    restored.close()


def test_durable_client_rejects_changed_versions_across_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    client = make_client(tmp_path, task_path=path)
    client.decide(decision_request())
    client.close()
    restored = make_client(tmp_path, task_path=path)
    restored.versions["model"] = "new-model-version"
    with pytest.raises(AgentClientError, match="versions"):
        restored.decide(decision_request())
    restored.close()


def test_restored_client_never_reuses_invalid_output(tmp_path):
    import json
    from src.coordination.tasks import task_digest
    path = tmp_path / "tasks.sqlite"
    client = make_client(tmp_path, task_path=path)
    client.decide(decision_request())
    row = client.evidence()["tasks"]["Owner"][0]
    row["output"]["data"] = {"current_stage": "closed"}
    row["output_sha256"] = task_digest(row["output"])
    client.tasks._db.execute("UPDATE tasks SET record=?", (json.dumps(row),))
    client.close()
    restored = make_client(tmp_path, task_path=path)
    with pytest.raises(AgentClientError, match="simulation-owned"):
        restored.decide(decision_request())
    restored.close()


class _SavedProposalOwner(Handlers):
    """Synthetic host-owned durable answer; no native business is executed."""
    def __init__(self,path,interruption):
        from contextlib import nullcontext
        super().__init__()
        self.path,self.interruption=path,interruption
        self.queries=0
        self.recovery_guard=nullcontext

    def propose(self,request):
        import json
        response=super().propose(request)
        self.path.write_text(json.dumps({'request':request.model_dump(mode='json'),
            'response':response.model_dump(mode='json')}),encoding='utf-8')
        raise self.interruption('Synthetic interruption after durable owner result')

    def recover_saved_proposal(self,request):
        import json
        from src.coordination.tasks import TaskConflict
        self.queries+=1
        if not self.path.exists():raise TaskConflict('Original owner result is still unknown')
        saved=json.loads(self.path.read_text(encoding='utf-8'))
        if saved['request']!=request.model_dump(mode='json'):raise TaskConflict('Original request changed')
        return saved['response']


def _saved_recovery_request():
    contract=get_operation_contract('decide_monthly_operation','Owner')
    return AgentProposalRequestV1(request_id='saved-owner-proposal',operation=contract.operation,
        agent=identity_from_profile(inputs().agents[0]),operation_contract=contract,
        inputs={'macro_environment':{'current_tick':1}})


@pytest.mark.parametrize('interruption,state',[(SystemExit,'processing'),(RuntimeError,'technical_failure')])
def test_explicit_proposal_recovery_uses_durable_owner_result_without_reexecuting(tmp_path,interruption,state):
    path=tmp_path/'tasks.sqlite';answer=tmp_path/'owner-result.json';request=_saved_recovery_request()
    original=_SavedProposalOwner(answer,interruption)
    client=make_client(tmp_path,original,task_path=path)
    with pytest.raises(interruption):client.propose(request)
    assert client.evidence()['tasks']['Owner'][0]['state']==state
    client.close()
    owner=_SavedProposalOwner(answer,AssertionError)
    restored=make_client(tmp_path,owner,task_path=path)
    try:
        result=restored.recover_proposal(request)
        assert result.request_id==request.request_id
        assert len(original.proposals)==1 and not owner.proposals and owner.queries==1
        rows=restored.evidence()['tasks']['Owner']
        assert len(rows)==1 and rows[0]['state']=='output_formed'
        assert rows[0]['submission'] is None and rows[0]['receipt'] is None
        assert restored.propose(request)==result and not owner.proposals
        assert restored.evidence()['calls'][0]['delivered_to_macro'] is False
    finally:restored.close()


def test_explicit_proposal_recovery_preserves_unknown_work_and_never_creates_requests(tmp_path):
    from src.coordination.tasks import TaskConflict
    answer=tmp_path/'owner-result.json';owner=_SavedProposalOwner(answer,SystemExit)
    client=make_client(tmp_path,owner,task_path=tmp_path/'tasks.sqlite');request=_saved_recovery_request()
    try:
        with pytest.raises(SystemExit):client.propose(request)
        answer.unlink()
        before=client.evidence()['tasks']['Owner']
        with pytest.raises(TaskConflict,match='still unknown'):client.recover_proposal(request)
        assert client.evidence()['tasks']['Owner']==before
        other=request.model_copy(deep=True);other.request_id='a-new-request'
        with pytest.raises(TaskConflict):client.recover_proposal(other)
        assert client.evidence()['tasks']['Owner']==before and len(owner.proposals)==1
    finally:client.close()


def test_explicit_proposal_recovery_rejects_owned_state_mutations_without_resolving_task(tmp_path):
    import json
    answer=tmp_path/'owner-result.json';owner=_SavedProposalOwner(answer,SystemExit)
    client=make_client(tmp_path,owner,task_path=tmp_path/'tasks.sqlite');request=_saved_recovery_request()
    try:
        with pytest.raises(SystemExit):client.propose(request)
        before=client.evidence()['tasks']['Owner']
        saved=json.loads(answer.read_text(encoding='utf-8'))
        saved['response']['data']['current_stage']='closed'
        answer.write_text(json.dumps(saved),encoding='utf-8')
        with pytest.raises(AgentClientError,match='simulation-owned'):client.recover_proposal(request)
        assert client.evidence()['tasks']['Owner']==before and len(owner.proposals)==1
    finally:client.close()


def test_explicit_proposal_recovery_waits_for_host_without_holding_client_lock(tmp_path):
    from contextlib import contextmanager
    import threading
    owner=_SavedProposalOwner(tmp_path/'owner-result.json',SystemExit)
    client=make_client(tmp_path,owner,task_path=tmp_path/'tasks.sqlite');request=_saved_recovery_request()
    writer=threading.RLock();held=threading.Event();requested=threading.Event();errors=[]
    @contextmanager
    def guarded():
        requested.set()
        with writer:yield
    owner.recovery_guard=guarded
    def engine_callback():
        with writer:
            held.set()
            if not requested.wait(3):errors.append('Recovery never requested original host guard');return
            if not client._lock.acquire(timeout=3):errors.append('Recovery held client lock while waiting for engine');return
            client._lock.release()
    thread=threading.Thread(target=engine_callback)
    try:
        with pytest.raises(SystemExit):client.propose(request)
        thread.start();assert held.wait(3)
        result=client.recover_proposal(request)
        thread.join(timeout=3)
        assert not thread.is_alive() and not errors
        assert result.request_id==request.request_id and len(owner.proposals)==1
    finally:
        requested.set()
        if thread.ident is not None:thread.join(timeout=3)
        client.close()
