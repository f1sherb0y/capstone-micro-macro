"""Single-action Supplier host using existing durable action implementations."""
from copy import deepcopy
from dataclasses import dataclass, fields, replace
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import BeforeValidator, Field

from integration.action_model_host import ActionModelHost
from integration.commercial_worker import CommercialTaskWorker
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import (
    RoleContractExecution, RoleContractHost, RoleContractHostConfiguration, RoleContractInvocation,
    prepare_role_contract_options,
)
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


def _original_task_identity(value):
    """Restore JSON configuration without weakening the original identity checks."""
    return TaskIdentity(**value) if isinstance(value, dict) else value


ConfiguredTaskIdentity = Annotated[TaskIdentity, BeforeValidator(_original_task_identity)]


class SupplierRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class SupplierPlanningInputSelection(StrictRecord):
    planning_identity: ConfiguredTaskIdentity
    basis_ref: ref_type('SupplierPlanningHandoffBasis')


class SupplierOrderInputSelection(StrictRecord):
    order_identity: ConfiguredTaskIdentity
    basis_ref: ref_type('SupplierOrderHandoffBasis')


class SupplierOrderInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, SupplierOrderInputSelection]


class SupplierPlanningInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, SupplierPlanningInputSelection]


class SupplierExecutionInputSelection(StrictRecord):
    execution_identity: ConfiguredTaskIdentity
    basis_ref: ref_type('SupplierExecutionHandoffBasis')


class SupplierExecutionInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, SupplierExecutionInputSelection]


class SupplierQualityInputSelection(StrictRecord):
    quality_identity: ConfiguredTaskIdentity
    basis_ref: ref_type('SupplierQualityHandoffBasis')


class SupplierQualityInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, SupplierQualityInputSelection]


class SupplierLogisticsInputSelection(StrictRecord):
    logistics_identity: ConfiguredTaskIdentity
    basis_ref: ref_type('SupplierLogisticsHandoffBasis')


class SupplierLogisticsInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, SupplierLogisticsInputSelection]


class SupplierRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: SupplierRoleFeedbackSettings | None = None
    order_inputs: SupplierOrderInputSettings | None = None
    planning_inputs: SupplierPlanningInputSettings | None = None
    execution_inputs: SupplierExecutionInputSettings | None = None
    quality_inputs: SupplierQualityInputSettings | None = None
    logistics_inputs: SupplierLogisticsInputSettings | None = None


@dataclass(frozen=True)
class SupplierSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Supplier invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class SupplierRoleContractSources:
    """Source factory owns original sources, current read guard and cleanup.

    A12 receives its existing commercial worker and journal from the application.
    This host creates no source facts, model client, submission or receipt.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    store: TaskStore
    provider: object
    read_guard: Callable
    validators: SupplierSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    commercial_worker: CommercialTaskWorker | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    order_worker: object = None
    validate_order_history: Callable | None = None
    validate_order_planning: Callable | None = None
    planning_worker: object = None
    validate_planning_history: Callable | None = None
    validate_planning_execution: Callable | None = None
    execution_worker: object = None
    validate_execution_history: Callable | None = None
    validate_execution_quality: Callable | None = None
    quality_worker: object = None
    validate_quality_history: Callable | None = None
    validate_quality_dispatch: Callable | None = None
    logistics_worker: object = None
    validate_logistics_history: Callable | None = None
    validate_logistics_receiving: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, SupplierSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)
                or self.commercial_worker is not None and not isinstance(self.commercial_worker, CommercialTaskWorker)):
            raise ValueError('Supplier sources require original registries, journal, reader and callbacks')
        if any(value is not None for value in (self.order_worker,
                self.validate_order_history, self.validate_order_planning)):
            _check_order_sources(self)
        if any(value is not None for value in (self.planning_worker,
                self.validate_planning_history, self.validate_planning_execution)):
            _check_planning_sources(self)
        if any(value is not None for value in (self.execution_worker,
                self.validate_execution_history, self.validate_execution_quality)):
            _check_execution_sources(self)
        if any(value is not None for value in (self.quality_worker,
                self.validate_quality_history, self.validate_quality_dispatch)):
            _check_quality_sources(self)
        if any(value is not None for value in (self.logistics_worker,
                self.validate_logistics_history, self.validate_logistics_receiving)):
            _check_logistics_sources(self)
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.supplier_submission_feedback import SupplierSubmissionFeedback
            if (not isinstance(self.feedback, SupplierSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Supplier feedback requires original same-journal feedback and input validation')


# A12 uses its existing commercial worker rather than a duplicate result table.
_ACTIONS = {
    'SUPPLIER-A01': ('screening', 'Screening'), 'SUPPLIER-A02': ('product', 'Product'),
    'SUPPLIER-A03': ('quote', 'Quote'), 'SUPPLIER-A04': ('order', 'Order'),
    'SUPPLIER-A05': ('planning', 'Planning'), 'SUPPLIER-A06': ('execution', 'Execution'),
    'SUPPLIER-A07': ('quality', 'Quality'), 'SUPPLIER-A08': ('logistics', 'Logistics'),
    'SUPPLIER-A09': ('receiving', 'Receiving'), 'SUPPLIER-A10': ('payment', 'Payment'),
    'SUPPLIER-A11': ('remedy', 'Remedy'), 'SUPPLIER-A12': ('commercial', 'Commercial'),
    'SUPPLIER-A13': ('advice', 'Advice'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Supplier source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Supplier source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Supplier source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.order_worker is not None:
        callbacks.update(order_handoff=sources.order_worker.prepare_planning_handoff,
            order_history_reader=sources.order_worker.read_completed,
            validate_order_history=sources.validate_order_history,
            validate_order_planning=sources.validate_order_planning)
    if sources.planning_worker is not None:
        callbacks.update(planning_handoff=sources.planning_worker.prepare_execution_handoff,
            planning_history_reader=sources.planning_worker.read_completed,
            validate_planning_history=sources.validate_planning_history,
            validate_planning_execution=sources.validate_planning_execution)
    if sources.execution_worker is not None:
        callbacks.update(execution_handoff=sources.execution_worker.prepare_quality_handoff,
            execution_history_reader=sources.execution_worker.read_completed,
            validate_execution_history=sources.validate_execution_history,
            validate_execution_quality=sources.validate_execution_quality)
    if sources.quality_worker is not None:
        callbacks.update(quality_handoff=sources.quality_worker.prepare_logistics_handoff,
            quality_history_reader=sources.quality_worker.read_completed,
            validate_quality_history=sources.validate_quality_history,
            validate_quality_dispatch=sources.validate_quality_dispatch)
    if sources.logistics_worker is not None:
        callbacks.update(logistics_handoff=sources.logistics_worker.prepare_receiving_handoff,
            logistics_history_reader=sources.logistics_worker.read_completed,
            validate_logistics_history=sources.validate_logistics_history,
            validate_logistics_receiving=sources.validate_logistics_receiving)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Retain original complete Supplier inputs, including profile-derived A12."""
    action_id = context.contract_ref.id
    if action_id == 'SUPPLIER-A12':
        arguments = {'profile_ref': values['continuation_profile_ref']}
    elif action_id in {'SUPPLIER-A05', 'SUPPLIER-A07'}:
        # These assemblers derive scope_ref from the original context rather
        # than accepting it as a source-selection argument.
        if values['scope_ref'] != context.scope.model_dump(mode='json'):
            raise TaskConflict('Supplier input scope differs from its original invocation')
        arguments = {name: value for name, value in values.items() if name != 'scope_ref'}
    else:
        arguments = values
    prepared = assembler.build(context, **arguments)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('Supplier assembly changes the original supplied input')
    return prepared


def _check_order_sources(sources):
    from integration.supplier_order_results import SupplierOrderResultWorker

    if (not isinstance(sources.order_worker, SupplierOrderResultWorker)
            or sources.order_worker.store.run_id != sources.store.run_id
            or sources.order_worker.registry is not sources.registry
            or not callable(sources.validate_order_history)
            or not callable(sources.validate_order_planning)):
        raise ValueError('Order inputs require original same-run A04 worker, shared registry and explicit validators')


def _order_handoff(sources, prepared, selection):
    """Attach original accepted A04 evidence to independently existing A05 work."""
    _check_order_sources(sources)
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Order handoff changes original A05 context or input')
    identity = TaskIdentity(**selection.order_identity.as_dict())
    handoff = sources.order_worker.prepare_planning_handoff(identity,
        current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
        execution_versions=identity.versions, basis_ref=selection.basis_ref.model_copy(deep=True),
        work_authority_ref=prepared.action_input.work_authority_ref,
        validate_history=sources.validate_order_history, validate_current=sources.validate_order_planning)
    prepared.reading.recheck()
    if (handoff.get('kind') != 'prepared'
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Selected A04 acceptance cannot establish the actual A05 order/work source')
    provenance = deepcopy(handoff)
    provenance['order_ref'] = handoff['order_ref'].model_dump(mode='json')
    provenance['work_authority_ref'] = prepared.action_input.work_authority_ref.model_dump(mode='json')
    provenance['order_identity'] = identity.as_dict()
    return provenance


def _check_planning_sources(sources):
    from integration.supplier_planning_results import SupplierPlanningResultWorker

    if (not isinstance(sources.planning_worker, SupplierPlanningResultWorker)
            or sources.planning_worker.store.run_id != sources.store.run_id
            or sources.planning_worker.registry is not sources.registry
            or not callable(sources.validate_planning_history)
            or not callable(sources.validate_planning_execution)):
        raise ValueError('Planning inputs require the original same-run A05 worker, shared registry and explicit validators')


def _planning_handoff(sources, prepared, selection):
    """Reuse original A05 history and actual task formation under the source guard."""
    _check_planning_sources(sources)
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Planning handoff changed original A06 context or input')
    identity = TaskIdentity(**selection.planning_identity.as_dict())
    setup = prepared.action_input.execution_setup
    handoff = sources.planning_worker.prepare_execution_handoff(identity,
        current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
        execution_versions=identity.versions, basis_ref=selection.basis_ref.model_copy(deep=True),
        task_ref=prepared.action_input.task_ref,
        release_ref=setup.release_ref if setup.kind == 'production' else None,
        validate_history=sources.validate_planning_history, validate_current=sources.validate_planning_execution)
    prepared.reading.recheck()
    if (handoff.get('kind') != 'prepared' or handoff.get('task_ref') != prepared.action_input.task_ref
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Selected original planning cannot establish the actual A06 execution task')
    provenance = deepcopy(handoff)
    provenance['task_ref'] = prepared.action_input.task_ref.model_dump(mode='json')
    provenance['planning_identity'] = identity.as_dict()
    return provenance


def _check_execution_sources(sources):
    from integration.supplier_execution_results import SupplierExecutionResultWorker

    if (not isinstance(sources.execution_worker, SupplierExecutionResultWorker)
            or sources.execution_worker.store.run_id != sources.store.run_id
            or sources.execution_worker.registry is not sources.registry
            or not callable(sources.validate_execution_history)
            or not callable(sources.validate_execution_quality)):
        raise ValueError('Quality inputs require the original same-run A06 worker, shared registry and explicit validators')


def _execution_handoff(sources, prepared, selection):
    """Reuse actual production receipt and output-batch lineage without approval."""
    _check_execution_sources(sources)
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Execution handoff changed original A07 context or input')
    identity = TaskIdentity(**selection.execution_identity.as_dict())
    handoff = sources.execution_worker.prepare_quality_handoff(identity,
        current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
        execution_versions=identity.versions, basis_ref=selection.basis_ref.model_copy(deep=True),
        batch_ref=prepared.action_input.batch_ref,
        validate_history=sources.validate_execution_history, validate_current=sources.validate_execution_quality)
    prepared.reading.recheck()
    if (handoff.get('kind') != 'prepared' or handoff.get('batch_ref') != prepared.action_input.batch_ref
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Selected original execution cannot establish the actual A07 batch')
    provenance = deepcopy(handoff)
    provenance['batch_ref'] = prepared.action_input.batch_ref.model_dump(mode='json')
    provenance['execution_identity'] = identity.as_dict()
    return provenance


def _check_quality_sources(sources):
    from integration.supplier_quality_results import SupplierQualityResultWorker

    if (not isinstance(sources.quality_worker, SupplierQualityResultWorker)
            or sources.quality_worker.store.run_id != sources.store.run_id
            or sources.quality_worker.registry is not sources.registry
            or not callable(sources.validate_quality_history)
            or not callable(sources.validate_quality_dispatch)):
        raise ValueError('Dispatch inputs require the original same-run A07 worker, shared registry and explicit validators')


def _quality_handoff(sources, prepared, selection):
    """Reuse independent actual dispatch release; a quality proposal is insufficient."""
    _check_quality_sources(sources)
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Quality handoff changed original A08 context or input')
    identity = TaskIdentity(**selection.quality_identity.as_dict())
    handoff = sources.quality_worker.prepare_logistics_handoff(identity,
        current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
        execution_versions=identity.versions, basis_ref=selection.basis_ref.model_copy(deep=True),
        dispatchable_refs=prepared.action_input.dispatchable_refs,
        validate_history=sources.validate_quality_history, validate_current=sources.validate_quality_dispatch)
    prepared.reading.recheck()
    if (handoff.get('kind') != 'prepared'
            or handoff.get('dispatchable_refs') != prepared.action_input.dispatchable_refs
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Selected quality decision cannot establish actual dispatch release and inventory')
    provenance = deepcopy(handoff)
    provenance['dispatchable_refs'] = [ref.model_dump(mode='json') for ref in prepared.action_input.dispatchable_refs]
    provenance['quality_identity'] = identity.as_dict()
    return provenance


def _check_logistics_sources(sources):
    from integration.supplier_logistics_results import SupplierLogisticsResultWorker

    if (not isinstance(sources.logistics_worker, SupplierLogisticsResultWorker)
            or sources.logistics_worker.store.run_id != sources.store.run_id
            or sources.logistics_worker.registry is not sources.registry
            or not callable(sources.validate_logistics_history)
            or not callable(sources.validate_logistics_receiving)):
        raise ValueError('Receiving inputs require the original same-run A08 worker, shared registry and explicit validators')


def _logistics_handoff(sources, prepared, selection):
    """Link the actual shipment without inventing arrival or receiving effects."""
    _check_logistics_sources(sources)
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Logistics handoff changed original A09 context or input')
    identity = TaskIdentity(**selection.logistics_identity.as_dict())
    handoff = sources.logistics_worker.prepare_receiving_handoff(identity,
        current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
        execution_versions=identity.versions, basis_ref=selection.basis_ref.model_copy(deep=True),
        shipment_ref=prepared.action_input.shipment_ref,
        validate_history=sources.validate_logistics_history, validate_current=sources.validate_logistics_receiving)
    prepared.reading.recheck()
    if (handoff.get('kind') != 'prepared' or handoff.get('shipment_ref') != prepared.action_input.shipment_ref
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Selected logistics decision cannot establish the actual receiving shipment')
    provenance = deepcopy(handoff)
    provenance['shipment_ref'] = prepared.action_input.shipment_ref.model_dump(mode='json')
    provenance['logistics_identity'] = identity.as_dict()
    return provenance


def _check_components(sources, assembler, worker, settings, source_mode, model_host):
    commercial = settings.action_id == 'SUPPLIER-A12'
    views = assembler._views.values() if commercial else (assembler._views,)
    if (assembler.registry is not sources.registry or assembler.organizations is not sources.organizations
            or assembler.methods is not sources.methods or assembler.source_mode != source_mode
            or assembler.policy_version != settings.policy_version or assembler.model_version != settings.model_version
            or any(view.provider is not sources.provider or view.macro_version != settings.macro_version
                or view.source_mode != source_mode for view in views)
            or worker.store is not sources.store or worker.snapshots.store is not sources.store
            or worker.client_version != settings.client_version or worker.model_version != settings.model_version
            or any(getattr(worker, 'validate_' + name) is not getattr(sources.validators, name)
                for name in ('invocation', 'wait', 'recovery'))
            or sources.model_host is not model_host):
        raise TaskConflict('Supplier original components, versions or source callbacks changed')
    if commercial:
        if sources.commercial_worker is not worker or worker.assembler is not assembler:
            raise TaskConflict('Supplier A12 requires its original commercial worker and assembler')
        expected = () if model_host is None else tuple(model_host.bindings)
        if assembler.decision_strategies != expected:
            raise TaskConflict('Supplier A12 requires its original explicitly bound model strategies')
    elif worker.registry is not sources.registry:
        raise TaskConflict('Supplier result worker requires its original registry')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = SupplierRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Supplier host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    order_settings = settings.order_inputs
    planning_settings = settings.planning_inputs
    execution_settings = settings.execution_inputs
    quality_settings = settings.quality_inputs
    logistics_settings = settings.logistics_inputs
    if order_settings is not None and (settings.action_id != 'SUPPLIER-A05'
            or request.context.operation_id not in order_settings.selections):
        raise ValueError('Order inputs require explicit SUPPLIER-A05 selections for this operation')
    if planning_settings is not None and (settings.action_id != 'SUPPLIER-A06'
            or request.context.operation_id not in planning_settings.selections):
        raise ValueError('Planning inputs require explicit SUPPLIER-A06 selections for this operation')
    if execution_settings is not None and (settings.action_id != 'SUPPLIER-A07'
            or request.context.operation_id not in execution_settings.selections):
        raise ValueError('Execution inputs require explicit SUPPLIER-A07 selections for this operation')
    if quality_settings is not None and (settings.action_id != 'SUPPLIER-A08'
            or request.context.operation_id not in quality_settings.selections):
        raise ValueError('Quality inputs require explicit SUPPLIER-A08 selections for this operation')
    if logistics_settings is not None and (settings.action_id != 'SUPPLIER-A09'
            or request.context.operation_id not in logistics_settings.selections):
        raise ValueError('Logistics inputs require explicit SUPPLIER-A09 selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Supplier feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, SupplierRoleContractSources):
        raise ValueError('Supplier source factory must return SupplierRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Supplier sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Supplier feedback source binding must match its explicit input configuration')
        if order_settings is not None:
            _check_order_sources(sources)
        if planning_settings is not None:
            _check_planning_sources(sources)
        if execution_settings is not None:
            _check_execution_sources(sources)
        if quality_settings is not None:
            _check_quality_sources(sources)
        if logistics_settings is not None:
            _check_logistics_sources(sources)
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Supplier' or not registration.implemented or registration.skill is None:
            raise ValueError('Supplier host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Supplier execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Supplier host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Supplier host requires its existing same-journal model host and budget')
        source_mode = 'fixture' if offline else 'formal'
        commercial = settings.action_id == 'SUPPLIER-A12'
        if commercial:
            worker = sources.commercial_worker
            if worker is None:
                raise ValueError('Supplier A12 requires the existing commercial worker and wait journal')
            assembler = worker.assembler
        else:
            module, name = _ACTIONS[settings.action_id]
            assembler_type = getattr(importlib.import_module('integration.supplier_' + module + '_actions'),
                'Supplier' + name + 'ActionAssembler')
            worker_type = getattr(importlib.import_module('integration.supplier_' + module + '_results'),
                'Supplier' + name + 'ResultWorker')
            assembler = assembler_type(registry=sources.registry, organizations=sources.organizations,
                provider=sources.provider, macro_version=settings.macro_version, source_mode=source_mode,
                methods=sources.methods, policy_version=settings.policy_version,
                model_version=settings.model_version, model_host=model_host)
            worker = worker_type(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
                registry=sources.registry, client_version=settings.client_version, model_version=settings.model_version,
                validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
                validate_recovery=sources.validators.recovery)
        _check_components(sources, assembler, worker, settings, source_mode, model_host)
        feedback_assembler = feedback_input = None
        if feedback_settings is not None:
            from integration.supplier_feedback_inputs import SupplierFeedbackInputAssembler
            feedback_assembler = SupplierFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        declared = {'schema_version': 'supplier-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode,
            'assembler': module_factory_descriptor(assembler.build, settings.action_id),
            'worker': module_factory_descriptor(worker.run if commercial else worker.execute, settings.action_id),
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'supplier_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Supplier host configuration or code changed; explicit review required')
        order_provenance = None
        order_selection = (order_settings.selections[request.context.operation_id]
            if order_settings is not None else None)
        planning_provenance = None
        planning_selection = (planning_settings.selections[request.context.operation_id]
            if planning_settings is not None else None)
        execution_provenance = None
        execution_selection = (execution_settings.selections[request.context.operation_id]
            if execution_settings is not None else None)
        quality_provenance = None
        quality_selection = (quality_settings.selections[request.context.operation_id]
            if quality_settings is not None else None)
        logistics_provenance = None
        logistics_selection = (logistics_settings.selections[request.context.operation_id]
            if logistics_settings is not None else None)
        handoff_settings = (order_settings, planning_settings, execution_settings, quality_settings, logistics_settings)

        def prepare_handoff_sources(invocation):
            nonlocal order_provenance, planning_provenance, execution_provenance, quality_provenance, logistics_provenance
            if order_settings is not None:
                order_provenance = _order_handoff(sources, invocation, order_selection)
            if planning_settings is not None:
                planning_provenance = _planning_handoff(sources, invocation, planning_selection)
            if execution_settings is not None:
                execution_provenance = _execution_handoff(sources, invocation, execution_selection)
            if quality_settings is not None:
                quality_provenance = _quality_handoff(sources, invocation, quality_selection)
            if logistics_settings is not None:
                logistics_provenance = _logistics_handoff(sources, invocation, logistics_selection)
            return True

        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id],
                prepare_additional_sources=prepare_handoff_sources
                    if any(s is not None for s in handoff_settings) else None)
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                prepared = _build_input(assembler, request.context, supplied.model_dump(mode='json'))
        if any(s is not None for s in handoff_settings) and feedback_input is None:
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                prepare_handoff_sources(prepared)
                prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Supplier source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Supplier executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations):
                raise TaskConflict('Supplier original sources or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if order_settings is not None:
                    if (_order_handoff(sources, prepared, order_selection) != order_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original order acceptance or independent work source changed before planning')
                if planning_settings is not None:
                    if (_planning_handoff(sources, prepared, planning_selection) != planning_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original planning or actual task formation changed before execution')
                if execution_settings is not None:
                    if (_execution_handoff(sources, prepared, execution_selection) != execution_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original production receipt or batch lineage changed before quality execution')
                if quality_settings is not None:
                    if (_quality_handoff(sources, prepared, quality_selection) != quality_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original quality release or dispatchable stock changed before logistics execution')
                if logistics_settings is not None:
                    if (_logistics_handoff(sources, prepared, logistics_selection) != logistics_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original logistics decision or shipment changed before receiving execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Supplier feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                elif commercial:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id, purpose='action')
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                if commercial:
                    # The existing A12 worker builds a fresh authorized runner;
                    # forward the entry point's audit sink without changing it permanently.
                    original_sink = assembler.audit_sink
                    assembler.audit_sink = prepared.runner.audit_sink
                    try:
                        outcome = worker.run(identity)
                    finally:
                        assembler.audit_sink = original_sink
                    record = worker._saved(identity)
                    table = 'commercial_action_results'
                else:
                    outcome = worker.execute(identity, prepared)
                    record = worker.get_record(identity)
                    table = worker.RESULT_TABLE
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Supplier execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Supplier source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': table,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'),
                    'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'order_input': deepcopy(order_provenance),
                    'planning_input': deepcopy(planning_provenance),
                    'execution_input': deepcopy(execution_provenance),
                    'quality_input': deepcopy(quality_provenance),
                    'logistics_input': deepcopy(logistics_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='supplier-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'order_input': deepcopy(order_provenance),
                'planning_input': deepcopy(planning_provenance), 'execution_input': deepcopy(execution_provenance),
                'quality_input': deepcopy(quality_provenance), 'logistics_input': deepcopy(logistics_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
