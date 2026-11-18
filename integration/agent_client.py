"""Explicit client boundary for the bundled GBA v1 external agent protocol."""
from __future__ import annotations

from copy import deepcopy
import threading

from integration.bootstrap import enable_gba_imports
from integration.observations import GbaV1OwnEventProjection, ObservationInbox, observation_digest
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore

enable_gba_imports()
from gba_construction_sim.backend.agents.contracts import (
    AGENT_MODULE_CONTRACT_VERSION, AgentDecisionRequestV1, AgentDecisionResponseV1,
    AgentModuleCapabilitiesV1, AgentModuleHealthV1, AgentObservationV1,
    AgentProposalRequestV1, AgentProposalResponseV1,
)
from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider, bounded_selection_validation_view
from gba_construction_sim.backend.agents.operation_specs import (
    get_operation_contract, validate_operation_inputs, validate_operation_response,
)
from gba_construction_sim.backend.models.action import find_forbidden_action_mutation_keys


class AgentClientError(ValueError):
    """An unsupported or inconsistent external invocation cannot be dispatched."""


# The bundled package's list predates resource ownership fields. Keep the
# integration boundary stricter without changing the protected package.
_EXTERNAL_OWNED_KEYS = frozenset({"occupied_resource"})


def _find_owned_mutations(value):
    found = set(find_forbidden_action_mutation_keys(value))
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _EXTERNAL_OWNED_KEYS:
                found.add(key)
            found.update(_find_owned_mutations(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_owned_mutations(child))
    return found


class GbaV1AgentClient:
    """Handlers use old operation contracts, with no implicit 106-action mapping.

    The host supplies implementations and their version identities. Absence of
    a handler is an explicit capability gap; there is no rule-provider fallback.
    Decision caches bind the entire request. An explicit task_path enables
    durable output recovery within the same run and macro simulation.
    """

    def __init__(self, *, run_id: str, organization_roles: dict[str, str],
                 proposal_handlers: dict[tuple[str, str], object], decision_handler,
                 versions: dict[str, str], inbox_path=None, task_path=None, continuation_dispatcher=None):
        required_versions = {"client", "skill", "prompt", "contract", "method", "model", "strategy"}
        if (set(versions) != required_versions or
                any(not isinstance(value, str) or not value.strip() for value in versions.values())):
            raise ValueError("Explicit client, Skill, prompt, contract, method, model and strategy versions are required")
        if not organization_roles:
            raise ValueError("Explicit organization roles are required")
        if not callable(decision_handler):
            raise ValueError("A final decision handler is required")
        for key, handler in proposal_handlers.items():
            if len(key) != 2 or not callable(handler):
                raise ValueError("Proposal handlers require (role, operation) keys and callables")
            get_operation_contract(key[1], key[0])
        self.run_id = run_id
        self.organization_roles = dict(organization_roles)
        self.proposal_handlers = dict(proposal_handlers)
        self.decision_handler = decision_handler
        self.versions = dict(versions)
        self.inbox = ObservationInbox(run_id, organization_roles, inbox_path)
        self.tasks = TaskStore(run_id=run_id, organization_ids=organization_roles, path=task_path)
        if continuation_dispatcher is not None and not callable(continuation_dispatcher):
            self.tasks.close()
            raise ValueError("Continuation dispatch must be an explicit trusted-host callback")
        self.continuation_dispatcher = continuation_dispatcher
        self._projection = GbaV1OwnEventProjection()
        self._cache = {}
        self._request_hashes = {}
        self._lock = threading.RLock()
        self._claimed = False
        self.simulation_id = None
        self._calls = []
        self._tender_feedback = None

    def claim(self, organization_roles: dict[str, str]) -> None:
        with self._lock:
            if self._claimed:
                raise AgentClientError("An external client cannot be shared between engines")
            if organization_roles != self.organization_roles:
                raise AgentClientError("Engine identities differ from the client recipient set")
            self._claimed = True

    def attach(self, simulation_id: str) -> None:
        with self._lock:
            if not self._claimed or self.simulation_id is not None:
                raise AgentClientError("Client must be claimed exactly once before attachment")
            try:
                self.tasks.attach_simulation(simulation_id)
            except TaskConflict as exc:
                raise AgentClientError(str(exc)) from exc
            self.simulation_id = simulation_id

    def _identity(self, request):
        self._assert_runtime_ready()
        if request.contract_version != AGENT_MODULE_CONTRACT_VERSION:
            raise AgentClientError("Unsupported macro contract version")
        if self.organization_roles.get(request.agent.agent_id) != request.agent.role:
            raise AgentClientError("Request organization or role is outside the engine input")
        if not request.request_id.strip():
            raise AgentClientError("Original request identity is required")
        declared_simulation = request.metadata.get("simulation_id")
        if declared_simulation is not None and declared_simulation != self.simulation_id:
            raise AgentClientError("Request belongs to another simulation")

    def _task_request_id(self, purpose, request):
        """Default transport identity; explicit native composition can scope repeated operations."""
        return request.request_id

    def _invocation_identity(self,purpose,request):
        self._identity(request)
        if purpose not in {'propose','decide'}:raise AgentClientError('Unknown external invocation purpose')
        content=request.model_dump(mode='json')
        input_hash=observation_digest({'run_id':self.run_id,'versions':self.versions,'request':content})
        task_request_id=self._task_request_id(purpose,request)
        if not isinstance(task_request_id,str) or not task_request_id.strip():
            raise AgentClientError('Internal task identity must be explicit and nonempty')
        key=(purpose,request.agent.agent_id,task_request_id)
        identity=TaskIdentity(run_id=self.run_id,organization_id=request.agent.agent_id,role=request.agent.role,
            action_id=request.operation if purpose=='propose' else request.decision_type,
            request_id=task_request_id,purpose=purpose,input_sha256=input_hash,
            context_sha256=observation_digest({'simulation_id':self.simulation_id,'request':content}),versions=self.versions)
        return input_hash,task_request_id,key,identity

    def _invoke(self, purpose, request, handler, validate):
        # Single-flight under this run-local lock also keeps audit order stable.
        with self._lock:
            input_hash,task_request_id,key,task_identity=self._invocation_identity(purpose,request)
            prior = self._request_hashes.get(key)
            if prior is not None and prior != input_hash:
                raise AgentClientError("An external request ID was reused with different input or versions")
            try:
                task = self.tasks.ensure(task_identity)
            except TaskConflict as exc:
                raise AgentClientError(str(exc)) from exc
            self._request_hashes[key] = input_hash
            record = {"purpose": purpose, "run_id": self.run_id, "request_id": request.request_id,
                      "task_request_id": task_request_id,
                      "agent_id": request.agent.agent_id, "role": request.agent.role,
                      "input_sha256": input_hash, "status": "started"}
            self._calls.append(record)
            if task["state"] == "output_formed":
                # Recheck transport and identity even for recovered outputs.
                try:
                    response = validate(deepcopy(task["output"]))
                except Exception as exc:
                    record.update(status="failed", error_type=type(exc).__name__)
                    raise
                record["status"] = "cache_hit"
                record["recovered"] = key not in self._cache
                return response
            try:
                task = self.tasks.start(task_identity, task["revision"])
            except TaskConflict as exc:
                record.update(status="failed", error_type=type(exc).__name__)
                raise AgentClientError(str(exc)) from exc
            try:
                response = validate(handler(request.model_copy(deep=True)))
            except Exception as exc:
                record.update(status="failed", error_type=type(exc).__name__)
                self.tasks.fail(task_identity, task["revision"], error_code=type(exc).__name__)
                raise
            try:
                self.tasks.finish(task_identity, task["revision"], output=response.model_dump(mode="json"))
            except Exception as exc:
                record.update(status="failed", error_type=type(exc).__name__)
                raise
            self._cache[key] = response.model_copy(deep=True)
            record.update(status="returned", response_sha256=observation_digest(response.model_dump(mode="json")),
                          action_type=response.action_type)
            return response

    @staticmethod
    def _input_snapshot(model, raw):
        """Capture caller data before validation, hashing, dispatch or filtering.

        Validating an existing Pydantic instance can return that same mutable
        instance. Python-mode data also preserves non-finite numbers that JSON
        model serialization could otherwise silently replace with null.
        """
        captured = deepcopy(raw)
        value = captured.model_dump(mode="python") if hasattr(captured, "model_dump") else captured
        if not isinstance(value, dict) or set(value) - set(model.model_fields):
            raise AgentClientError("External input has unknown fields or is not an object")
        observation_digest(value)
        snapshot = model.model_validate(value)
        # Validation can coerce a numeric string into an infinite float.
        observation_digest(snapshot.model_dump(mode="python"))
        return snapshot

    @staticmethod
    def _response(model, raw, request=None):
        value = raw.model_dump(mode="python") if hasattr(raw, "model_dump") else raw
        if not isinstance(value, dict) or set(value) - set(model.model_fields):
            raise AgentClientError("External response has unknown fields")
        # Pydantic JSON serialization can turn non-finite numbers into null.
        observation_digest(value)
        response = model.model_validate(value)
        if response.contract_version != AGENT_MODULE_CONTRACT_VERSION:
            raise AgentClientError("Unsupported response contract version")
        if _find_owned_mutations(bounded_selection_validation_view(request, response)):
            raise AgentClientError("External response attempted to mutate simulation-owned state")
        observation_digest(response.model_dump(mode="json"))
        return response

    def _assert_runtime_ready(self):
        if getattr(self, '_native_checkpoint_pending', None) is not None:
            raise AgentClientError('Original checkpoint applications must be reinstalled and verified before business requests')

    def binding_installation_blocked(self):
        """Retained tasks permit binding only during verified checkpoint reconstruction."""
        with self._lock:
            if self._calls or self._request_hashes or self._cache:
                return True
            if getattr(self, '_native_checkpoint_pending', None) is not None:
                from integration.native_checkpoint import checkpoint_binding_installation_allowed
                return not checkpoint_binding_installation_allowed(self)
            return any(self.tasks.for_organization(run_id=self.run_id, organization_id=org)
                       for org in self.organization_roles)

    def bind_proposal_handler(self, *, role, operation, handler, client_version):
        """Install a concrete handler before any request or recovered task exists.

        Hosts may assemble a simulation first to learn its identity, then bind
        a run-specific handler. Existing handlers and task versions are never
        silently replaced. This method does not invoke the handler.
        """
        if (role not in set(self.organization_roles.values()) or not callable(handler)
                or not isinstance(client_version, str) or not client_version.strip()):
            raise AgentClientError('Actual owned role, proposal handler and new client version required')
        get_operation_contract(operation, role)
        key = (role, operation)
        with self._lock:
            if self._tender_feedback is not None:
                raise AgentClientError('The persisted tender binding fixes the complete proposal route set')
            if key in self.proposal_handlers:
                raise AgentClientError('Proposal handler is already explicitly bound')
            if client_version == self.versions['client']:
                raise AgentClientError('A new proposal binding requires a new declared client version')
            if self.binding_installation_blocked():
                raise AgentClientError('Proposal bindings are immutable after any request, observation or saved task')
            self.proposal_handlers[key] = handler
            self.versions['client'] = client_version

    def bind_tender_decision(self, *, validate_current, client_version, host_configuration_sha256):
        """Add an explicit tender route before any request, without replacing other routes."""
        from integration.bindings.gba_v1_tender_decision import GbaTenderDecisionAdapter
        from integration.bindings.gba_v1_tender_feedback import GbaTenderFeedbackStore
        from integration.bindings.gba_v1_tender_binding import tender_binding_record, save_tender_binding

        if (not callable(validate_current) or not isinstance(client_version, str)
                or not client_version.strip() or ('Contractor', 'consider_tender') not in self.proposal_handlers):
            raise AgentClientError('Tender final route requires its explicit proposal binding and fresh validator')
        with self._lock:
            if isinstance(self.decision_handler, GbaTenderDecisionAdapter):
                raise AgentClientError('Tender decision route is already bound')
            if client_version == self.versions['client']:
                raise AgentClientError('Tender decision binding requires a new declared client version')
            if self.binding_installation_blocked():
                raise AgentClientError('Decision bindings are immutable after calls, observations or saved tasks')
            adapter = GbaTenderDecisionAdapter(client=self, validate_current=validate_current,
                other_handler=self.decision_handler)
            versions = {**self.versions, 'client':client_version}
            record = tender_binding_record(self, self.proposal_handlers[('Contractor', 'consider_tender')],
                adapter, versions=versions, host_configuration_sha256=host_configuration_sha256)
            feedback = GbaTenderFeedbackStore(self)
            save_tender_binding(self.tasks, record)
            self._tender_feedback = feedback
            self.decision_handler = adapter
            self.versions['client'] = client_version
            return adapter

    def restore_tender_bindings(self, *, registry, read_output, revalidate,
            validate_current, host_configuration_sha256):
        """Restore saved components/versions before any new process invocation.

        Persisted task outputs remain unchanged. Missing metadata or changed
        code/configuration is a concrete recovery gap, never silently migrated.
        Attachment must already refer to the restored original simulation.
        """
        from integration.bindings.gba_v1_tender_binding import saved_tender_binding, tender_binding_record
        from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter
        from integration.bindings.gba_v1_tender_decision import GbaTenderDecisionAdapter
        from integration.bindings.gba_v1_tender_feedback import GbaTenderFeedbackStore

        with self._lock:
            if (self.simulation_id is None or self._calls or self._request_hashes or self._cache
                    or self._tender_feedback is not None or isinstance(self.decision_handler, GbaTenderDecisionAdapter)
                    or ('Contractor', 'consider_tender') in self.proposal_handlers):
                raise AgentClientError('Restore requires an attached fresh client with no tender route or new calls')
            saved = saved_tender_binding(self.tasks)
            if saved is None:
                raise AgentClientError('Original tender binding metadata is missing; recover its actual source before restoration')
            proposal = GbaTenderProposalAdapter(run_id=self.run_id, simulation_id=self.simulation_id,
                registry=registry, read_output=read_output, revalidate=revalidate)
            decision = GbaTenderDecisionAdapter(client=self, validate_current=validate_current,
                other_handler=self.decision_handler)
            current = tender_binding_record(self, proposal, decision, versions=self.versions,
                host_configuration_sha256=host_configuration_sha256)
            if current != saved:
                raise AgentClientError('Tender restoration changes original code, components, versions, recipients or host configuration')
            for organization in self.organization_roles:
                for row in self.tasks.for_organization(run_id=self.run_id, organization_id=organization):
                    identity = row['identity']
                    if (identity['purpose'] in {'propose', 'decide'}
                            and identity['action_id'] in {'consider_tender', 'tender_decision'}
                            and identity['versions'] != self.versions):
                        raise AgentClientError('Saved tender invocation versions differ from the original restored binding')
            feedback = GbaTenderFeedbackStore(self)
            self.proposal_handlers[proposal.HANDLER_KEY] = proposal
            self.decision_handler, self._tender_feedback = decision, feedback
            return {'proposal':proposal, 'decision':decision}

    def _proposal_route(self,request):
        key=(request.agent.role,request.operation)
        handler=self.proposal_handlers.get(key)
        if handler is None:raise AgentClientError(f'Unsupported proposal operation: {key}')
        contract=get_operation_contract(request.operation,request.agent.role).model_copy(deep=True)
        if request.operation_contract!=contract:
            raise AgentClientError('Proposal request differs from the registered operation contract')
        validate_operation_inputs(contract,request.inputs)
        def validate(raw):
            response=self._response(AgentProposalResponseV1,raw,request)
            if response.request_id!=request.request_id:raise AgentClientError('Proposal response request ID mismatch')
            validate_operation_response(contract,response,request.inputs)
            return response
        return handler,validate

    @staticmethod
    def _proposal_recovery(handler):
        owner=getattr(handler,'__self__',handler)
        recovery=getattr(owner,'recover_saved_proposal',None)
        return recovery if callable(recovery) else None

    @staticmethod
    def _proposal_recovery_guard(handler):
        owner=getattr(handler,'__self__',handler)
        guard=getattr(owner,'recovery_guard',None)
        return guard if callable(guard) else None

    def propose(self, raw_request):
        request = self._input_snapshot(AgentProposalRequestV1, raw_request)
        with self._lock:
            handler,validate=self._proposal_route(request)
            return self._invoke("propose", request, handler, validate)

    def recover_proposal(self,raw_request):
        """Reconcile a known original response without running its handler again.

        This host-only operation neither delivers a response to the macro nor
        advances an engine. The installed owner must independently authenticate
        saved results and the still-current request. Missing/unknown work stays
        unresolved; no new native request or micro action is created here.
        """
        request=self._input_snapshot(AgentProposalRequestV1,raw_request)
        with self._lock:
            handler,validate=self._proposal_route(request)
            recover=self._proposal_recovery(handler)
            guard=self._proposal_recovery_guard(handler)
            if recover is None:raise AgentClientError('Installed proposal owner has no explicit saved-result recovery')
            if guard is None:raise AgentClientError('Saved proposal recovery requires its original host writer guard')
        # Preserve engine.run's guard -> client lock order. Waiting for the
        # engine while holding the client lock could deadlock its next callback.
        with guard():
            with self._lock:
                current_handler,validate=self._proposal_route(request)
                if (current_handler!=handler or self._proposal_recovery(current_handler)!=recover
                        or self._proposal_recovery_guard(current_handler)!=guard):
                    raise AgentClientError('Original proposal owner or recovery guard changed')
                return self._reconcile_proposal(request,recover,validate)

    def _reconcile_proposal(self,request,recover,validate):
        """Caller holds the actual host guard and this client's lock."""
        input_hash,task_request_id,key,identity=self._invocation_identity('propose',request)
        prior=self._request_hashes.get(key)
        if prior is not None and prior!=input_hash:
            raise AgentClientError('Recovery cannot replace an original request input or execution version')
        # get(), rather than ensure(), prohibits creating a recovery task
        # for a request that the original client never received.
        task=self.tasks.get(identity)
        if task['state'] not in {'processing','technical_failure','output_formed'}:
            raise AgentClientError('Original proposal state cannot be reconciled from a saved result')
        record={'purpose':'recover_propose','run_id':self.run_id,'request_id':request.request_id,
            'task_request_id':task_request_id,'agent_id':request.agent.agent_id,'role':request.agent.role,
            'input_sha256':input_hash,'status':'querying_original_result'}
        self._calls.append(record)
        try:
            response=validate(recover(request.model_copy(deep=True)))
            current=self.tasks.get(identity)
            formed=response.model_dump(mode='json')
            if current['state']=='output_formed':
                if current['output']!=formed or current['output_sha256']!=observation_digest(formed):
                    raise AgentClientError('Recovered proposal differs from its original formed response')
            else:
                if current!=task:raise AgentClientError('Original proposal changed while its saved result was queried')
                if current['state']=='technical_failure':current=self.tasks.start(identity,current['revision'])
                self.tasks.finish(identity,current['revision'],output=formed)
        except Exception as exc:
            record.update(status='unresolved',error_type=type(exc).__name__)
            raise
        self._request_hashes[key]=input_hash;self._cache[key]=response.model_copy(deep=True)
        record.update(status='reconciled_from_saved_result',response_sha256=observation_digest(formed),
            action_type=response.action_type,business_reexecuted=False,delivered_to_macro=False)
        return response

    def decide(self, raw_request):
        request = self._input_snapshot(AgentDecisionRequestV1, raw_request)
        with self._lock:

            def validate(raw):
                response = self._response(AgentDecisionResponseV1, raw, request)
                ExternalAgentDecisionProvider._validated_action(request, response)
                return response

            return self._invoke("decide", request, self.decision_handler, validate)

    async def decide_async(self, raw_request):
        """Keep local final validation on the native scheduler's calling thread.

        The bundled external provider otherwise offloads ``decide`` using
        asyncio.to_thread. That worker cannot reenter the application's writer
        guard held by engine.run. Handlers here are synchronous, serialized
        validation of saved decisions; preserve that same path and journal.
        """
        return self.decide(raw_request)

    def observe(self, raw_observation):
        self._assert_runtime_ready()
        observation = self._input_snapshot(AgentObservationV1, raw_observation)
        if observation.contract_version != AGENT_MODULE_CONTRACT_VERSION:
            raise AgentClientError("Unsupported observation contract version")
        if not observation.event_id.strip():
            raise AgentClientError("Stable event identity is required")
        with self._lock:
            projections = self._projection(observation, self.organization_roles)
            delivered = [organization_id for organization_id, payload in projections.items()
                         if self.inbox.deliver(run_id=self.run_id, event_id=observation.event_id,
                                               organization_id=organization_id, payload=payload)]
            if self._tender_feedback is not None:
                self._tender_feedback.record(observation)
            self._calls.append({"purpose": "observe", "run_id": self.run_id,
                                "event_id": observation.event_id, "event_type": observation.event_type,
                                "recipients": delivered,
                                "status": "recorded" if delivered else "duplicate" if projections else "filtered"})
        if self.continuation_dispatcher is not None:
            for organization_id in projections:
                self.continuation_dispatcher(run_id=self.run_id, organization_id=organization_id)

    def tender_feedback(self, *, organization_id):
        """Read own correlated core evidence for host projections; no domain write."""
        if self._tender_feedback is None:
            raise AgentClientError('Tender feedback is not explicitly bound')
        with self._lock:
            return self._tender_feedback.for_organization(organization_id=organization_id)

    def tender_feedback_context(self, request, *, project_only=True):
        """Supply actual prior own outcomes to a later micro decision producer."""
        if self._tender_feedback is None:
            raise AgentClientError('Tender feedback is not explicitly bound')
        with self._lock:
            return self._tender_feedback.context_for_request(request, project_only=project_only)

    def record_tender_feedback_consumption(self, *, request, identity, worker, source, read_guard=None):
        """Retain proof only after the actual later A01 has read own feedback."""
        if self._tender_feedback is None:
            raise AgentClientError('Tender feedback is not explicitly bound')
        with self._lock:
            return self._tender_feedback.record_screening_consumption(
                request=request, identity=identity, worker=worker, source=source, read_guard=read_guard)

    def capabilities(self):
        contracts = [get_operation_contract(operation, role)
                     for role, operation in sorted(self.proposal_handlers)]
        return AgentModuleCapabilitiesV1(
            module_name=type(self).__name__, module_version=self.versions["client"],
            roles=sorted({contract.role for contract in contracts}),
            proposal_operations=sorted({contract.operation for contract in contracts}),
            operation_contracts=deepcopy(contracts), supports_batch_decisions=False,
            supports_observations=True, supports_persistent_memory=self.inbox.path is not None,
        )

    def health(self):
        return AgentModuleHealthV1(status="ready" if self.simulation_id else "unattached",
                                  module_name=type(self).__name__,
                                  message="Local handler availability only; no remote health claim",
                                  details={"run_id": self.run_id, "simulation_id": self.simulation_id})

    def evidence(self):
        with self._lock:
            return {"schema_version": "gba-v1-client-evidence.v1", "run_id": self.run_id,
                    "simulation_id": self.simulation_id, "versions": dict(self.versions),
                    "capabilities": self.capabilities().model_dump(mode="json"),
                    "observation_event_types": sorted(self._projection.FIELDS),
                    "health": self.health().model_dump(mode="json"), "calls": deepcopy(self._calls),
                    "tasks": {organization: self.tasks.for_organization(run_id=self.run_id,
                                organization_id=organization) for organization in sorted(self.organization_roles)}}

    def close(self):
        """Release the task database after the host has stopped invoking this client."""
        try:
            self.tasks.close()
        finally:
            lease = getattr(self, '_native_engine_lease', None)
            if lease is not None:
                lease.close()
