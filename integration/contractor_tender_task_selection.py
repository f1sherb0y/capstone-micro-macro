"""Persist exact native-request to completed A02 task selections without replay."""
from copy import deepcopy
import json

from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalMappingView
from integration.contractor_bid_results import ContractorTenderReadSelection
from integration.contractor_tender_host import GbaContractorTenderHost
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest


class ContractorTenderTaskSelector:
    """Application explicitly registers a completed original task for one request.

    attach_host and select_current can be used as the corresponding application
    callbacks. A selection is immutable and read-only: it never finds a latest
    task, creates a task, runs a strategy or manufactures a proposal. The original
    proposal adapter still validates professional indicators and exposure gates.
    The actual shared engine writer guard must be supplied by the application.
    """
    VERSION = 'contractor-tender-task-selector.v1'

    def __init__(self, *, store, registry, selector_id, version, read_guard):
        if (not isinstance(store, TaskStore) or store.path is None or not isinstance(registry, ActionRegistry)
                or not all(isinstance(value, str) and value.strip() for value in (selector_id, version))
                or not callable(read_guard)):
            raise ValueError('Tender selector requires original persistent journal, registry, version and writer guard')
        self.store, self.registry, self.read_guard = store, registry, read_guard
        self.selector_id, self.version = selector_id, version
        self.host = None
        self._components = (store, registry, read_guard)
        self._declared = self._configuration()
        self._key = 'contractor_tender_task_selector:' + selector_id
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original tender selector configuration changed')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'selector_id': self.selector_id, 'version': self.version,
            'code': module_factory_descriptor(type(self).select_current, self.VERSION),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard')}

    def _check(self, *, bound=True):
        if (any(value is not original for value, original in zip(
                (self.store, self.registry, self.read_guard), self._components))
                or self._configuration() != self._declared):
            raise TaskConflict('Tender selector changed its original components or configuration')
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Tender selector lacks original configuration evidence')
        if bound:
            if self.host is None or self.host is not self._host:
                raise TaskConflict('Tender selector requires its original attached host')
            self.host._check(bound=True)
            if (self.host.pipeline.worker.store is not self.store
                    or self.host.pipeline.worker.registry is not self.registry
                    or self.host.pipeline.read_guard is not self.read_guard
                    or self.host.callbacks.select_current != self.select_current
                    or self.host.configuration_sha256 != self._host_sha256):
                raise TaskConflict('Tender selector changed its original installed host or callback')
            with self.store._lock:
                saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key + ':host',)).fetchone()
                expected = {'configuration_sha256': self._host_sha256,
                    'simulation_id': self.host.pipeline.assembly.client.simulation_id}
                if saved is None or json.loads(saved[0]) != expected:
                    raise TaskConflict('Tender selector changed its original host binding evidence')

    def attach_host(self, host):
        self._check(bound=False)
        if not isinstance(host, GbaContractorTenderHost):
            raise ValueError('Tender selector requires the original installed tender host')
        host._check(bound=True)
        if (host.pipeline.worker.store is not self.store or host.pipeline.worker.registry is not self.registry
                or host.pipeline.read_guard is not self.read_guard
                or host.callbacks.select_current != self.select_current
                or self.host is not None and self.host is not host):
            raise TaskConflict('Tender selector cannot attach a different journal, guard, registry or host')
        binding = {'configuration_sha256': host.configuration_sha256,
            'simulation_id': host.pipeline.assembly.client.simulation_id}
        with self.store._transaction():
            key = self._key + ':host'
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is None:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(binding)))
            elif json.loads(prior[0]) != binding:
                raise TaskConflict('Tender selector cannot replace its original installed binding')
        self.host = self._host = host
        self._host_sha256 = host.configuration_sha256

    def _request(self, request):
        from gba_construction_sim.backend.agents.contracts import AGENT_MODULE_CONTRACT_VERSION, AgentProposalRequestV1
        from gba_construction_sim.backend.agents.operation_specs import get_operation_contract, validate_operation_inputs

        self._check()
        request = AgentProposalRequestV1.model_validate(request).model_copy(deep=True)
        client = self.host.pipeline.assembly.client
        if (request.contract_version != AGENT_MODULE_CONTRACT_VERSION
                or request.agent.role != 'Contractor' or request.operation != 'consider_tender'
                or client.organization_roles.get(request.agent.agent_id) != 'Contractor'
                or request.metadata.get('simulation_id') not in {None, client.simulation_id}):
            raise TaskConflict('Tender selection changes the original native contract, operation or recipient')
        contract = get_operation_contract(request.operation, 'Contractor')
        if request.operation_contract != contract:
            raise TaskConflict('Tender selection requires the original native operation contract')
        validate_operation_inputs(contract, request.inputs)
        return request

    def _record_key(self, request):
        return self._key + ':request:' + task_digest([
            self.host.pipeline.assembly.client.simulation_id, request.agent.agent_id, request.request_id])

    def _validate_selection(self, request, selection):
        if not isinstance(selection, ContractorTenderReadSelection):
            raise ValueError('Tender selection requires an explicit typed original-task selection')
        identity = TaskIdentity(**selection.identity.as_dict())
        current = ActionContext.model_validate(selection.current_context).model_copy(deep=True)
        mapping_ref = Reference.model_validate(selection.mapping_ref).model_copy(deep=True)
        if (identity.run_id != self.store.run_id or identity.organization_id != request.agent.agent_id
                or identity.role != 'Contractor' or identity.action_id != 'CONTRACTOR-A02' or identity.purpose != 'action'
                or current.run_id != identity.run_id or current.contract_ref.kind != 'ActionContract'
                or current.contract_ref.id != 'CONTRACTOR-A02' or current.execution_mode == 'offline_fixture'):
            raise TaskConflict('Tender selection changes the original A02 task or formal read identity')
        pipeline = self.host.pipeline
        reading = pipeline.assembler.build_result_reading(current)
        saved = pipeline.worker.read_completed(identity, current_context=current, reading=reading, mapping_ref=mapping_ref)
        original = saved.context
        if (identity.versions['client'] != pipeline.worker.client_version
                or identity.versions['model'] != pipeline.worker.model_version):
            raise TaskConflict('Tender selection changes original client/model execution versions')
        pipeline.assembler.check_execution_versions(identity, context=original)
        if (any(getattr(current, field) != getattr(original, field)
                for field in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope'))
                or original.execution_mode == 'offline_fixture'
                or current.business_time.clock_ref != original.business_time.clock_ref
                or current.business_time.offset < original.business_time.offset):
            raise TaskConflict('Tender selection substitutes the original actor, scope, clock or source mode')
        mapping = reading.resolve(mapping_ref)
        client = pipeline.assembly.client
        if (not isinstance(mapping, GbaTenderProposalMappingView) or mapping.ref != mapping_ref
                or mapping.run_id != identity.run_id or mapping.simulation_id != client.simulation_id
                or mapping.organization_id != identity.organization_id
                or mapping.project_id != request.inputs['project'].get('project_id')
                or mapping.scope != original.scope or mapping.package_ref != saved.action_input.package_ref
                or mapping.request_sha256 != task_digest(request.model_dump(mode='json'))
                or mapping.context_sha256 != identity.context_sha256 or mapping.input_sha256 != identity.input_sha256
                or mapping.result_sha256 != task_digest(saved.result.model_dump(mode='json'))):
            raise TaskConflict('Tender selection mapping changes the original request, package or saved result')
        reading.recheck()
        record = pipeline.worker.get_record(identity)
        return {'identity': identity.as_dict(), 'current_context': current.model_dump(mode='json'),
            'mapping_ref': mapping_ref.model_dump(mode='json'), 'result_record_sha256': record['record_sha256']}

    def register(self, request, selection):
        """Persist one explicit relation; repeating it is idempotent, replacement is rejected."""
        with self.read_guard():
            request = self._request(request)
            body = {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
                'host_sha256': self._host_sha256, 'request_sha256': task_digest(request.model_dump(mode='json')),
                **self._validate_selection(request, selection)}
            body['record_sha256'] = task_digest(body)
            self._check()
            with self.store._transaction():
                key = self._record_key(request)
                prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                if prior is None:
                    self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
                elif json.loads(prior[0]) != body:
                    raise TaskConflict('Original tender request cannot select a replacement task or read point')
            return deepcopy(body)

    def select_current(self, request):
        """Read the registered original relation under current authority; never execute a task."""
        # GbaContractorTenderHost holds this same guard while invoking the callback.
        request = self._request(request)
        with self.store._lock:
            row = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._record_key(request),)).fetchone()
        if row is None:
            raise TaskConflict('No explicit completed A02 task is registered for this native request')
        record = json.loads(row[0])
        if (record.get('record_sha256') != task_digest({key: value for key, value in record.items() if key != 'record_sha256'})
                or record.get('schema_version') != self.VERSION
                or record.get('configuration_sha256') != task_digest(self._declared)
                or record.get('host_sha256') != self._host_sha256
                or record.get('request_sha256') != task_digest(request.model_dump(mode='json'))):
            raise TaskConflict('Tender selection record changed its original native request or binding')
        selected = ContractorTenderReadSelection(identity=TaskIdentity(**record['identity']),
            current_context=ActionContext.model_validate(record['current_context']),
            mapping_ref=Reference.model_validate(record['mapping_ref']))
        if self._validate_selection(request, selected) != {name: record[name] for name in
                ('identity', 'current_context', 'mapping_ref', 'result_record_sha256')}:
            raise TaskConflict('Tender selection changed its original saved task or current authorized sources')
        self._check()
        return selected
