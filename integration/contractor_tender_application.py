"""Concrete configured Contractor tender application and original task validators."""
from copy import deepcopy
import json
from pathlib import Path
from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.bindings.gba_v1_tender_clarification import publish_clarification_request, query_clarification_request
from integration.contractor_tender_clarification_response import (
    respond_to_clarification, query_clarification_response, query_clarification_review,
)
from integration.contractor_tender_clarification_continuation import publish_response_consumption, response_consumption, effective_screening
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings, build_authority_runtime
from integration.contractor_tender_host import ContractorTenderHostCallbacks, GbaContractorTenderHost
from integration.contractor_tender_module_host import ContractorTenderSourceValidators, _load_source_factory
from integration.contractor_tender_source_factory import ContractorTenderApplicationBindings
from integration.contractor_tender_task_selection import ContractorTenderTaskSelector
from integration.contractor_tender_request_trigger import ContractorTenderRequestTrigger
from integration.module_host import module_factory_descriptor
from integration.unstarted_action_continuation import execute_original_stage
from integration.bindings.gba_v1_bid_evaluation import with_own_evaluation_history
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


class TenderProfessionalCallback(StrictRecord):
    symbol: TextId
    version: TextId
    settings: dict


class TenderProfessionalCallbacks(StrictRecord):
    publication: TenderProfessionalCallback
    quantity: TenderProfessionalCallback
    cost: TenderProfessionalCallback
    handoff: TenderProfessionalCallback
    exposure: TenderProfessionalCallback
    final: TenderProfessionalCallback
    programme: TenderProfessionalCallback | None = None
    mapping: TenderProfessionalCallback | None = None


class ContractorTenderApplicationSettings(StrictRecord):
    version: TextId
    authority: TenderAuthorityRuntimeSettings
    professional: TenderProfessionalCallbacks
    model_host_factory: TextId | None = None
    model_host_settings: dict
    allow_saved_recovery: bool = False
    continue_unstarted_actions_on_error: bool = False
    publish_native_clarification_requests: bool = False
    request_work_factory: TextId | None = None
    request_recovery_factory: TextId | None = None
    request_work_settings: dict = Field(default_factory=dict)


class ContractorTenderApplication:
    """Own micro authority/guard and explicit task/source relations, never core facts.

    Professional callbacks receive their original arguments plus application and
    settings. They must inspect actual independent sources, not return a fixed
    answer. The source factory installs the persistent task selector separately.
    Construction executes no action and makes no proposal or native submission.
    """
    VERSION = 'configured-contractor-tender-application.v8'

    def __init__(self, *, assembly, request, output_directory, offline, settings, authority=None):
        if type(offline) is not bool:
            raise ValueError('Tender application requires explicit model mode')
        self.settings = ContractorTenderApplicationSettings.model_validate(settings).model_copy(deep=True)
        if (offline and (self.settings.model_host_factory is not None or self.settings.model_host_settings)
                or not offline and self.settings.model_host_factory is None):
            raise ValueError('Offline tender application forbids model configuration; LLM requires an explicit existing-host factory')
        self.assembly = assembly
        self._owns_authority = authority is None
        self.authority = authority if authority is not None else build_authority_runtime(assembly=assembly, settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings != self.settings.authority:
            raise TaskConflict('Tender shared authority must retain its exact original assembly and declared snapshot')
        self.registry, self.organizations = self.authority.registry, self.authority.organizations
        # Retain one bound callable identity for every constructed component.
        self.read_guard = self.authority.read_guard
        self.store = assembly.client.tasks
        self.host = self.selector = self.model_host = None
        self.screening_assembler = self.screening_worker = None
        self._screening_components = None
        self.request_trigger = None
        self._attached_host = self._attached_selector = None
        self._closed = False
        self._callbacks, descriptors = {}, {}
        try:
            for name in TenderProfessionalCallbacks.model_fields:
                spec = getattr(self.settings.professional, name)
                if spec is not None:
                    callback = _load_source_factory(spec.symbol)
                    self._callbacks[name] = callback
                    descriptors[name] = module_factory_descriptor(callback, spec.symbol)
            model_descriptor = None
            if not offline:
                factory = _load_source_factory(self.settings.model_host_factory)
                model_descriptor = module_factory_descriptor(factory, self.settings.model_host_factory)
                self.model_host = factory(assembly=assembly, registry=self.registry, organizations=self.organizations,
                    store=self.store, read_guard=self.read_guard, request=request.model_copy(deep=True),
                    output_directory=Path(output_directory), settings=deepcopy(self.settings.model_host_settings))
                if (not isinstance(self.model_host, ActionModelHost) or self.model_host.store is not self.store
                        or self.model_host.registry is not self.registry
                        or self.model_host.model_version != assembly.client.versions['model']
                        or module_factory_descriptor(factory, self.settings.model_host_factory) != model_descriptor):
                    raise ValueError('Tender application requires an existing same-journal/registry/version budget model host')
            self._declared = {'schema_version': self.VERSION, 'run_id': self.store.run_id,
                'simulation_id': assembly.client.simulation_id, 'configuration_sha256': task_digest(self.settings.model_dump(mode='json')),
                'code': module_factory_descriptor(type(self).validate_invocation, self.VERSION),
                'clarification_bridge': self._clarification_descriptors(),
                'professional_callbacks': descriptors, 'model_factory': model_descriptor,
                'model_configuration_sha256': self.model_host.configuration_sha256 if self.model_host is not None else None}
            if self.settings.request_work_factory is not None:
                if self.settings.professional.mapping is None:
                    raise ValueError('Request-driven tender work requires a pre-selection mapping validator')
                self._declared['request_work_factory'] = module_factory_descriptor(
                    _load_source_factory(self.settings.request_work_factory), self.settings.request_work_factory)
                self._declared['request_trigger'] = module_factory_descriptor(
                    ContractorTenderRequestTrigger.__call__, ContractorTenderRequestTrigger.VERSION)
                self._declared['unstarted_executor'] = module_factory_descriptor(
                    execute_original_stage,'unstarted-action-continuation.v1')
                self._declared['evaluation_history_reader']=module_factory_descriptor(
                    with_own_evaluation_history,'own-evaluated-bids.v1')
            elif self.settings.request_work_settings:
                raise ValueError('Request work settings require an explicit source producer factory')
            if self.settings.continue_unstarted_actions_on_error and self.settings.request_work_factory is None:
                raise ValueError('Unstarted continuation requires the original request-driven work producer')
            if self.settings.publish_native_clarification_requests and self.settings.request_work_factory is None:
                raise ValueError('Clarification questions require the original request-driven work producer')
            if self.settings.request_recovery_factory is not None:
                if not self.settings.allow_saved_recovery or self.settings.request_work_factory is None:
                    raise ValueError('Tender request recovery requires original work sources and explicit saved-result authorization')
                self._declared['request_recovery_factory'] = module_factory_descriptor(
                    _load_source_factory(self.settings.request_recovery_factory), self.settings.request_recovery_factory)
            if (getattr(assembly.client, 'native_routes', None) is not None
                    and assembly.client.native_routes.settings.query_saved_tender_on_error
                    and self.settings.request_recovery_factory is None):
                raise ValueError('Tender query on error requires its explicit original saved-result recovery factory')
            self._components = (assembly, assembly.engine, assembly.client, self.store, self.authority,
                self.registry, self.organizations, self.read_guard, self.model_host)
            self._key = 'contractor_tender_application:' + self.settings.authority.runtime_id
            with self.store._transaction():
                prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
                if prior is None:
                    self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
                elif json.loads(prior[0]) != self._declared:
                    raise TaskConflict('Original tender application configuration changed')
        except Exception:
            self.close()
            raise

    @staticmethod
    def _clarification_descriptors():
        return {name: module_factory_descriptor(callback, name) for name, callback in
            [('publish', publish_clarification_request), ('query', query_clarification_request),
             ('respond', respond_to_clarification), ('query_response', query_clarification_response),
             ('query_review', query_clarification_review),
             ('consume_response',publish_response_consumption),('read_consumption',response_consumption),
             ('effective_screening',effective_screening)]}

    def _check(self):
        self.authority._check()
        actual = (self.assembly, self.assembly.engine, self.assembly.client, self.store, self.authority,
            self.registry, self.organizations, self.read_guard, self.model_host)
        if (self._closed or self.host is not self._attached_host or self.selector is not self._attached_selector
                or any(value is not original for value, original in zip(actual, self._components))
                or self.authority.registry is not self.registry or self.authority.organizations is not self.organizations
                or task_digest(self.settings.model_dump(mode='json')) != self._declared['configuration_sha256']
                or self._clarification_descriptors() != self._declared['clarification_bridge']
                or module_factory_descriptor(type(self).validate_invocation, self.VERSION) != self._declared['code']):
            raise TaskConflict('Tender application changed its original components or configuration, or is closed')
        for name, callback in self._callbacks.items():
            spec = getattr(self.settings.professional, name)
            if (module_factory_descriptor(callback, spec.symbol) != self._declared['professional_callbacks'][name]
                    or _load_source_factory(spec.symbol) is not callback):
                raise TaskConflict('Tender professional callback changed its original source or binding')
        if self.settings.request_work_factory is not None and module_factory_descriptor(
                _load_source_factory(self.settings.request_work_factory), self.settings.request_work_factory
                ) != self._declared['request_work_factory']:
            raise TaskConflict('Tender request work producer changed its declared implementation')
        if self.request_trigger is not None and (
                self.request_trigger.selector is not self.selector
                or self.request_trigger.prepare_work != self._prepare_request_work
                or self.request_trigger.continue_unstarted_actions_on_error
                    is not self.settings.continue_unstarted_actions_on_error
                or self.request_trigger.publish_clarification != (self.publish_clarification_request
                    if self.settings.publish_native_clarification_requests else None)
                or module_factory_descriptor(self.request_trigger.__call__, self.request_trigger.VERSION)
                    != self._declared.get('request_trigger')
                or module_factory_descriptor(execute_original_stage,'unstarted-action-continuation.v1')
                    != self._declared.get('unstarted_executor')
                or module_factory_descriptor(with_own_evaluation_history,'own-evaluated-bids.v1')
                    != self._declared.get('evaluation_history_reader')):
            raise TaskConflict('Tender request trigger changed its original continuation authorization or code')
        if self.settings.request_recovery_factory is not None and module_factory_descriptor(
                _load_source_factory(self.settings.request_recovery_factory), self.settings.request_recovery_factory
                ) != self._declared['request_recovery_factory']:
            raise TaskConflict('Tender saved-result query changed its original implementation')
        if self.model_host is not None:
            if (self.model_host.store is not self.store or self.model_host.registry is not self.registry
                    or self.model_host.model_version != self.assembly.client.versions['model']
                    or self.model_host.configuration_sha256 != self._declared['model_configuration_sha256']
                    or module_factory_descriptor(_load_source_factory(self.settings.model_host_factory),
                        self.settings.model_host_factory) != self._declared['model_factory']):
                raise TaskConflict('Tender application changed its original model host')
        with self.store._lock:
            row = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if row is None or json.loads(row[0]) != self._declared:
                raise TaskConflict('Tender application configuration evidence changed')

    def _professional(self, name, *args, **kwargs):
        with self.read_guard():
            self._check()
            callback = self._callbacks.get(name)
            if callback is None:
                raise TaskConflict('No independent professional callback is configured for ' + name)
            returned = callback(*args, application=self,
                settings=deepcopy(getattr(self.settings.professional, name).settings), **kwargs)
            if returned is not None:
                raise TaskConflict('Independent professional callback must explicitly succeed: ' + name)
            self._check()

    def publication(self, prepared, context):
        self._professional('publication', prepared, context)

    def quantity(self, **kwargs):
        self._professional('quantity', **kwargs)

    def cost(self, **kwargs):
        self._professional('cost', **kwargs)

    def handoff(self, **kwargs):
        self._professional('handoff', **kwargs)

    def programme(self, **kwargs):
        self._professional('programme', **kwargs)

    def exposure(self, **kwargs):
        self._professional('exposure', **kwargs)

    def mapping(self, **kwargs):
        self._professional('mapping', **kwargs)

    def final(self, **kwargs):
        self._professional('final', **kwargs)

    def attach_host(self, host):
        self._check()
        if (not isinstance(host, GbaContractorTenderHost) or host.pipeline.assembly is not self.assembly
                or host.pipeline.worker.store is not self.store or host.pipeline.worker.registry is not self.registry
                or host.pipeline.assembler.organizations is not self.organizations
                or host.pipeline.read_guard is not self.read_guard or self.host is not None and self.host is not host):
            raise TaskConflict('Tender application cannot attach a different original host')
        host._check(bound=True)
        self.host = self._attached_host = host
        if self.screening_worker is None:
            from integration.contractor_screening_actions import ContractorScreeningActionAssembler
            from integration.contractor_screening_results import ContractorScreeningResultWorker

            bid = host.pipeline.assembler
            self.screening_assembler = ContractorScreeningActionAssembler(registry=self.registry,
                organizations=self.organizations, provider=bid.provider, macro_version=bid.macro_version,
                source_mode=bid.source_mode, methods=bid.methods, audit_sink=bid.audit_sink,
                policy_version=bid.policy_version, model_version=bid.model_version, model_host=self.model_host)
            self.screening_worker = ContractorScreeningResultWorker(store=self.store,
                snapshots=host.pipeline.worker.snapshots, registry=self.registry,
                client_version=host.pipeline.worker.client_version, model_version=host.pipeline.worker.model_version,
                validate_invocation=self.validate_invocation, validate_wait=self.validate_wait,
                validate_recovery=self.validate_recovery)
            self._screening_components = (self.screening_worker, self.screening_assembler)

    def attach_task_selector(self, selector):
        self._check()
        if (not isinstance(selector, ContractorTenderTaskSelector) or self.host is None
                or selector.host is not self.host or selector.store is not self.store
                or selector.registry is not self.registry or selector.read_guard is not self.read_guard
                or self.selector is not None and self.selector is not selector):
            raise TaskConflict('Tender application cannot attach a substitute task selector')
        selector._check()
        self.selector = self._attached_selector = selector
        if self.settings.request_work_factory is not None and self.request_trigger is None:
            from integration.contractor_tender_request_trigger import ContractorTenderRequestTrigger

            self.request_trigger = ContractorTenderRequestTrigger(selector=selector, prepare_work=self._prepare_request_work,
                continue_unstarted_actions_on_error=self.settings.continue_unstarted_actions_on_error,
                publish_clarification=self.publish_clarification_request
                    if self.settings.publish_native_clarification_requests else None)

    def publish_clarification_request(self, *, request, identity, prepared):
        return publish_clarification_request(self, request, identity, prepared)

    def query_clarification_request(self, request):
        return query_clarification_request(self, request)

    def query_clarification_response(self, request):
        return query_clarification_response(self, request)

    def query_clarification_review(self, request):
        return query_clarification_review(self, request)

    def _prepare_request_work(self, request):
        self._check()
        factory = _load_source_factory(self.settings.request_work_factory)
        return factory(application=self, request=request.model_copy(deep=True),
                       settings=deepcopy(self.settings.request_work_settings))

    def prepare_request(self, request):
        """Prepare only on an actual native request, after original route installation."""
        self._check()
        if self.request_trigger is None or self.request_trigger.selector is not self.selector:
            raise TaskConflict('Request-driven tender work requires the original attached selector and source producer')
        self.request_trigger(request)

    def select_current(self, request):
        if self.selector is None:
            raise TaskConflict('Tender application requires the configured persistent task selector')
        return self.selector.select_current(request)

    def recover_request(self, request):
        """Explicit current-request query; the factory cannot run missing work."""
        from integration.contractor_tender_request_trigger import read_request_record
        from integration.contractor_bid_results import ContractorTenderReadSelection
        with self.read_guard():
            self._check()
            if (not self.settings.allow_saved_recovery or self.settings.request_recovery_factory is None
                    or self.request_trigger is None or self.selector is None):
                raise TaskConflict('Original tender request recovery must be explicitly configured')
            request = self.selector._request(request)
            record = read_request_record(application=self, organization_id=request.agent.agent_id, request_id=request.request_id)
            if (record['native_request'] != request.model_dump(mode='json')
                    or request.metadata.get('tick') != self.assembly.engine.current_tick):
                raise TaskConflict('Tender recovery changes its original current native request')
            selected = _load_source_factory(self.settings.request_recovery_factory)(application=self,
                request=request.model_copy(deep=True), settings=deepcopy(self.settings.request_work_settings), record=deepcopy(record))
            if not isinstance(selected, ContractorTenderReadSelection) or selected.identity.as_dict() != record.get('bid_identity'):
                raise TaskConflict('Tender recovery must select the exact existing original bid')
            self.selector.register(request, selected)
            stages=[('screening',self.screening_worker),('bid',self.host.pipeline.worker)]
            if 'screening_successor_identity' in record:
                stages.append(('screening_successor',self.screening_worker))
            for stage, worker in stages:
                saved = worker.get_record(TaskIdentity(**record[stage + '_identity']))
                if record.get(stage + '_result_sha256') not in {None, saved['result_sha256']}:
                    raise TaskConflict('Tender recovery changes its original stage result')
                record[stage + '_result_sha256'] = saved['result_sha256']
            record['state'] = 'selected'
            key = 'tender_request_trigger:' + task_digest([self.assembly.client.simulation_id,
                request.agent.agent_id, request.request_id])
            self.request_trigger._save(self.store, key, record)

    def _task(self, row):
        self._check()
        if self.host is None:
            raise TaskConflict('Tender task validation requires its installed original host')
        self.host._check(bound=True)
        identity = TaskIdentity(**row['identity'])
        if (identity.run_id != self.store.run_id or identity.action_id not in {'CONTRACTOR-A01', 'CONTRACTOR-A02'}
                or identity.role != 'Contractor' or identity.purpose != 'action' or self.store.get(identity) != row):
            raise TaskConflict('Tender application task changes its original screening/bid identity')
        worker, assembler = self._execution_components(identity.action_id)
        snapshot = worker.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != identity.action_id:
            raise TaskConflict('Tender task contract differs from its original action identity')
        grants = self.organizations.grants(context, identity.action_id, 'Contractor')
        if grants[0].organization_id != identity.organization_id:
            raise TaskConflict('Tender task changes its original currently authorized organization')
        return identity, snapshot, context

    def _execution_components(self, action_id):
        if action_id == 'CONTRACTOR-A02':
            return self.host.pipeline.worker, self.host.pipeline.assembler
        worker, assembler = self.screening_worker, self.screening_assembler
        bid = self.host.pipeline
        if (action_id != 'CONTRACTOR-A01' or worker is None or assembler is None
                or self._screening_components is None
                or any(value is not original for value, original in zip((worker, assembler), self._screening_components))
                or worker.store is not self.store or worker.snapshots is not bid.worker.snapshots
                or worker.registry is not self.registry or worker.client_version != bid.worker.client_version
                or worker.model_version != bid.worker.model_version or assembler.registry is not self.registry
                or assembler.organizations is not self.organizations or assembler._views.provider is not bid.assembler.provider
                or assembler.source_mode != bid.assembler.source_mode
                or assembler.model_version != bid.assembler.model_version
                or assembler.policy_version != bid.assembler.policy_version
                or assembler.decision_strategies != bid.assembler.decision_strategies
                or assembler.methods is not bid.assembler.methods
                or worker.validate_invocation != self.validate_invocation
                or worker.validate_wait != self.validate_wait or worker.validate_recovery != self.validate_recovery):
            raise TaskConflict('Screening must retain original shared tender sources, authority, journal and versions')
        return worker, assembler

    def _source_digest(self, context):
        _, assembler = self._execution_components(context.contract_ref.id)
        return assembler._views.assemble(context, context.contract_ref.id, 'Contractor').digest

    def validate_invocation(self, row, prepared):
        with self.read_guard():
            identity, snapshot, context = self._task(row)
            worker, assembler = self._execution_components(identity.action_id)
            if (worker._prepared_identity(prepared, request_id=identity.request_id, purpose=identity.purpose) != identity
                    or prepared.context != context or prepared.action_input.model_dump(mode='json') != snapshot['action_input']
                    or prepared.runner.organizations is not self.organizations
                    or prepared.reading._organizations is not self.organizations
                    or prepared.runner.references is not prepared.reading._resolver):
                raise TaskConflict('Tender invocation substitutes its original prepared input or authority')
            prepared.reading.recheck()
            projection = assembler._views.assemble(context, identity.action_id, 'Contractor')
            current_sources = {item.ref.key(): item.value.model_dump(mode='json') for item in projection.objects}
            for source in prepared.reading.evidence():
                if current_sources.get(Reference.model_validate(source['ref']).key()) != source['projection']:
                    raise TaskConflict('Tender prepared source cache differs from its actual current original projections')
            body = {'identity': identity.as_dict(), 'source_projection_sha256': projection.digest}
            with self.store._transaction():
                key = self._key + ':execution_source:' + identity.key
                prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                if prior is None:
                    self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
                elif json.loads(prior[0]) != body:
                    raise TaskConflict('Tender task cannot replace its original source snapshot')
            return True

    def validate_wait(self, row, result, conditions):
        with self.read_guard():
            identity, _, _ = self._task(row)
            worker, _ = self._execution_components(identity.action_id)
            result = self.registry.get(identity.action_id).contract.result_adapter.validate_python(result).model_dump(mode='json')
            expected = {'kind': worker.WAIT_KIND, 'result_kind': result['kind'], 'result_sha256': task_digest(result)}
            if result['kind'] == 'needs_information':
                expected.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
            elif result['kind'] == 'unsupported':
                expected['capability_ref'] = result['capability_ref']
            elif result['kind'] == 'deferred':
                expected['resume_condition'] = result['resume_condition']
            else:
                raise TaskConflict('Tender wait requires an original pending result')
            if conditions != [expected]:
                raise TaskConflict('Tender wait changes the original result or resume condition')
            return True

    def validate_recovery(self, row, record, snapshot):
        with self.read_guard():
            identity, original, context = self._task(row)
            worker, _ = self._execution_components(identity.action_id)
            if (not self.settings.allow_saved_recovery or snapshot != original
                    or record['identity'] != identity.as_dict() or worker.get_record(identity) != record):
                raise TaskConflict('Tender saved-result recovery requires explicit unchanged original evidence')
            with self.store._lock:
                saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                    (self._key + ':execution_source:' + identity.key,)).fetchone()
            expected = {'identity': identity.as_dict(), 'source_projection_sha256': self._source_digest(context)}
            if saved is None or json.loads(saved[0]) != expected:
                raise TaskConflict('Tender recovery lacks the original currently authorized source projection')
            return True

    def evidence(self):
        with self.read_guard():
            self._check()
            return {'schema_version': self.VERSION, 'status': 'configured_unverified',
                'configuration_sha256': task_digest(self._declared), 'authority': self.authority.evidence(),
                'host_attached': self.host is not None, 'task_selector_attached': self.selector is not None,
                'request_trigger_configured': self.request_trigger is not None,
                'request_saved_recovery_configured': self.settings.request_recovery_factory is not None,
                'professional_callbacks': deepcopy(self._declared['professional_callbacks']),
                'limitations': ['Professional callbacks and independently supplied source files require functional verification.',
                    'Configuration and micro task results do not establish native business effects.']}

    def close(self):
        if not self._closed:
            self._closed = True
            if self._owns_authority:self.authority.close()


def build_application(*, assembly, request, output_directory, offline, settings, authority=None):
    """Source settings application_factory entry returning the original typed bundle."""
    application = ContractorTenderApplication(assembly=assembly, request=request, output_directory=output_directory,
        offline=offline, settings=settings, authority=authority)
    try:
        return ContractorTenderApplicationBindings(version=application.settings.version,
            registry=application.registry, organizations=application.organizations, read_guard=application.read_guard,
            validators=ContractorTenderSourceValidators(publication=application.publication,
                invocation=application.validate_invocation, wait=application.validate_wait, recovery=application.validate_recovery,
                quantity=application.quantity, cost=application.cost, handoff=application.handoff,
                programme=application.programme if application.settings.professional.programme is not None else None),
            tender_callbacks=ContractorTenderHostCallbacks(select_current=application.select_current,
                revalidate=application.exposure, validate_current=application.final,
                prepare_request=application.prepare_request if application.settings.request_work_factory is not None else None,
                recover_request=application.recover_request if application.settings.request_recovery_factory is not None else None,
                validate_mapping=application.mapping if application.settings.professional.mapping is not None else None),
            attach_host=application.attach_host, evidence=application.evidence, close=application.close,
            model_host=application.model_host, attach_task_selector=application.attach_task_selector)
    except Exception:
        application.close()
        raise
