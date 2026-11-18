"""Explicit single-action QS host using original assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.qs_market_actions import QSMarketActionAssembler
from integration.qs_market_results import QSMarketResultWorker
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import (
    RoleContractExecution, RoleContractHost, RoleContractHostConfiguration, RoleContractInvocation,
    prepare_role_contract_options,
)
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


class QSRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class QSRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: QSRoleFeedbackSettings | None = None


@dataclass(frozen=True)
class QSSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('QS invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class QSRoleContractSources:
    """Application owns actual sources, current read guard and persistent journal.

    The source factory owns partial resources until returning this object.
    This host creates no source facts, model client, native submission or receipt.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    store: TaskStore
    provider: object
    read_guard: Callable
    validators: QSSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    publish_cost_calculation: Callable | None = None
    publish_saved_cost_calculation: Callable | None = None
    publish_change_calculation: Callable | None = None
    publish_saved_change_calculation: Callable | None = None
    publish_payment_calculations: Callable | None = None
    publish_saved_payment_calculations: Callable | None = None
    publish_final_account_reconciliation: Callable | None = None
    publish_saved_final_account_reconciliation: Callable | None = None
    save_procurement_document: Callable | None = None
    publish_saved_procurement_document: Callable | None = None
    save_bid_normalization: Callable | None = None
    publish_saved_bid_normalization: Callable | None = None
    save_bid_ranking: Callable | None = None
    publish_saved_bid_ranking: Callable | None = None
    save_billing_calculation: Callable | None = None
    publish_saved_billing_calculation: Callable | None = None
    save_learning_comparability: Callable | None = None
    publish_saved_learning_comparability: Callable | None = None
    save_learning_error: Callable | None = None
    publish_saved_learning_error: Callable | None = None
    save_learning_assessment: Callable | None = None
    publish_saved_learning_assessment: Callable | None = None
    save_training_estimate: Callable | None = None
    publish_saved_training_estimate: Callable | None = None
    save_research_normalization_calculation: Callable | None = None
    publish_saved_research_normalization_calculation: Callable | None = None
    save_research_ranking_calculation: Callable | None = None
    publish_saved_research_ranking_calculation: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, QSSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('QS sources require original registries, persistent journal, reader and callbacks')
        if ((self.publish_cost_calculation is None) != (self.publish_saved_cost_calculation is None)
                or self.publish_cost_calculation is not None and (not callable(self.publish_cost_calculation)
                    or not callable(self.publish_saved_cost_calculation))):
            raise ValueError('QS cost production and saved-publication callbacks must be configured together')
        if ((self.publish_change_calculation is None) != (self.publish_saved_change_calculation is None)
                or self.publish_change_calculation is not None and (not callable(self.publish_change_calculation)
                    or not callable(self.publish_saved_change_calculation))):
            raise ValueError('QS change production and saved-publication callbacks must be configured together')
        if ((self.publish_payment_calculations is None) != (self.publish_saved_payment_calculations is None)
                or self.publish_payment_calculations is not None and (not callable(self.publish_payment_calculations)
                    or not callable(self.publish_saved_payment_calculations))):
            raise ValueError('QS payment production and saved-publication callbacks must be configured together')
        if ((self.publish_final_account_reconciliation is None) != (self.publish_saved_final_account_reconciliation is None)
                or self.publish_final_account_reconciliation is not None and (
                    not callable(self.publish_final_account_reconciliation)
                    or not callable(self.publish_saved_final_account_reconciliation))):
            raise ValueError('QS final-account production and saved-publication callbacks must be configured together')
        if ((self.save_procurement_document is None) != (self.publish_saved_procurement_document is None)
                or self.save_procurement_document is not None and (
                    not callable(self.save_procurement_document) or not callable(self.publish_saved_procurement_document))):
            raise ValueError('QS procurement document save and saved-publication callbacks must be configured together')
        if ((self.save_bid_normalization is None) != (self.publish_saved_bid_normalization is None)
                or self.save_bid_normalization is not None and (
                    not callable(self.save_bid_normalization) or not callable(self.publish_saved_bid_normalization))):
            raise ValueError('QS bid normalization save and saved-publication callbacks must be configured together')
        if ((self.save_bid_ranking is None) != (self.publish_saved_bid_ranking is None)
                or self.save_bid_ranking is not None and (
                    not callable(self.save_bid_ranking) or not callable(self.publish_saved_bid_ranking))):
            raise ValueError('QS bid ranking save and saved-publication callbacks must be configured together')
        if ((self.save_billing_calculation is None) != (self.publish_saved_billing_calculation is None)
                or self.save_billing_calculation is not None and (
                    not callable(self.save_billing_calculation) or not callable(self.publish_saved_billing_calculation))):
            raise ValueError('QS fee calculation save and saved-publication callbacks must be configured together')
        if ((self.save_learning_comparability is None) != (self.publish_saved_learning_comparability is None)
                or self.save_learning_comparability is not None and (
                    not callable(self.save_learning_comparability) or not callable(self.publish_saved_learning_comparability))):
            raise ValueError('QS forecast comparison save and saved-publication callbacks must be configured together')
        if ((self.save_learning_error is None) != (self.publish_saved_learning_error is None)
                or self.save_learning_error is not None and (
                    not callable(self.save_learning_error) or not callable(self.publish_saved_learning_error))):
            raise ValueError('QS forecast error save and saved-publication callbacks must be configured together')
        if ((self.save_learning_assessment is None) != (self.publish_saved_learning_assessment is None)
                or self.save_learning_assessment is not None and (
                    not callable(self.save_learning_assessment) or not callable(self.publish_saved_learning_assessment))):
            raise ValueError('QS learning assessment save and saved-publication callbacks must be configured together')
        if ((self.save_training_estimate is None) != (self.publish_saved_training_estimate is None)
                or self.save_training_estimate is not None and (
                    not callable(self.save_training_estimate) or not callable(self.publish_saved_training_estimate))):
            raise ValueError('QS training estimate save and saved-publication callbacks must be configured together')
        if ((self.save_research_normalization_calculation is None) != (self.publish_saved_research_normalization_calculation is None)
                or self.save_research_normalization_calculation is not None and (
                    not callable(self.save_research_normalization_calculation)
                    or not callable(self.publish_saved_research_normalization_calculation))):
            raise ValueError('QS research normalization save and publication callbacks must be configured together')
        if ((self.save_research_ranking_calculation is None) != (self.publish_saved_research_ranking_calculation is None)
                or self.save_research_ranking_calculation is not None and (
                    not callable(self.save_research_ranking_calculation)
                    or not callable(self.publish_saved_research_ranking_calculation))):
            raise ValueError('QS research ranking save and publication callbacks must be configured together')
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.qs_submission_feedback import QSSubmissionFeedback
            if (not isinstance(self.feedback, QSSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('QS feedback requires original same-journal feedback and input validation')


# Closed routing: action input cannot select a processor, module or result table.
_ACTIONS = {
    'QS-A01': ('market', 'Market'), 'QS-A02': ('intake', 'Intake'),
    'QS-A03': ('appointment', 'Appointment'), 'QS-A04': ('cost', 'Cost'),
    'QS-A05': ('procurement', 'Procurement'), 'QS-A06': ('bid', 'Bid'),
    'QS-A07': ('change', 'Change'), 'QS-A08': ('payment', 'Payment'),
    'QS-A09': ('final_account', 'FinalAccount'), 'QS-A10': ('billing', 'Billing'),
    'QS-A11': ('transition', 'Transition'), 'QS-A12': ('learning', 'Learning'),
    'QS-A13': ('research', 'Research'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('QS source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('QS source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('QS source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.publish_cost_calculation is not None:
        callbacks.update(publish_cost_calculation=sources.publish_cost_calculation,
            publish_saved_cost_calculation=sources.publish_saved_cost_calculation)
    if sources.publish_change_calculation is not None:
        callbacks.update(publish_change_calculation=sources.publish_change_calculation,
            publish_saved_change_calculation=sources.publish_saved_change_calculation)
    if sources.publish_payment_calculations is not None:
        callbacks.update(publish_payment_calculations=sources.publish_payment_calculations,
            publish_saved_payment_calculations=sources.publish_saved_payment_calculations)
    if sources.publish_final_account_reconciliation is not None:
        callbacks.update(publish_final_account_reconciliation=sources.publish_final_account_reconciliation,
            publish_saved_final_account_reconciliation=sources.publish_saved_final_account_reconciliation)
    if sources.save_procurement_document is not None:
        callbacks.update(save_procurement_document=sources.save_procurement_document,
            publish_saved_procurement_document=sources.publish_saved_procurement_document)
    if sources.save_bid_normalization is not None:
        callbacks.update(save_bid_normalization=sources.save_bid_normalization,
            publish_saved_bid_normalization=sources.publish_saved_bid_normalization)
    if sources.save_bid_ranking is not None:
        callbacks.update(save_bid_ranking=sources.save_bid_ranking,
            publish_saved_bid_ranking=sources.publish_saved_bid_ranking)
    if sources.save_billing_calculation is not None:
        callbacks.update(save_billing_calculation=sources.save_billing_calculation,
            publish_saved_billing_calculation=sources.publish_saved_billing_calculation)
    if sources.save_learning_comparability is not None:
        callbacks.update(save_learning_comparability=sources.save_learning_comparability,
            publish_saved_learning_comparability=sources.publish_saved_learning_comparability)
    if sources.save_learning_error is not None:
        callbacks.update(save_learning_error=sources.save_learning_error,
            publish_saved_learning_error=sources.publish_saved_learning_error)
    if sources.save_learning_assessment is not None:
        callbacks.update(save_learning_assessment=sources.save_learning_assessment,
            publish_saved_learning_assessment=sources.publish_saved_learning_assessment)
    if sources.save_training_estimate is not None:
        callbacks.update(save_training_estimate=sources.save_training_estimate,
            publish_saved_training_estimate=sources.publish_saved_training_estimate)
    if sources.save_research_normalization_calculation is not None:
        callbacks.update(save_research_normalization_calculation=sources.save_research_normalization_calculation,
            publish_saved_research_normalization_calculation=sources.publish_saved_research_normalization_calculation)
    if sources.save_research_ranking_calculation is not None:
        callbacks.update(save_research_ranking_calculation=sources.save_research_ranking_calculation,
            publish_saved_research_ranking_calculation=sources.publish_saved_research_ranking_calculation)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Retain the complete original QS input for every supported action."""
    prepared = assembler.build(context, **values)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('QS assembly changes the original supplied input')
    return prepared


def _component_descriptors(assembler, worker, action_id):
    descriptors = {name: module_factory_descriptor(callback, action_id) for name, callback in {
        'assembler_init': type(assembler).__init__, 'assembler': assembler.build,
        'worker_init': type(worker).__init__, 'worker': worker.execute,
        'source_validation': worker._validate_primary_sources,
        'assembler_source_schemas': assembler.SOURCE_SCHEMAS,
        'worker_source_schemas': worker.SOURCE_SCHEMAS,
    }.items()}
    schemas = assembler._views.schemas
    descriptors['source_projection_schemas'] = {
        kind: {'component': schema.__module__ + '.' + schema.__qualname__,
            'version_type': version_type.__name__, 'identity_field': schemas._identity_fields[kind],
            'schema_sha256': task_digest(schema.model_json_schema())}
        for kind, (schema, version_type) in sorted(schemas._schemas.items())}
    return descriptors


def _check_components(sources, assembler, worker, settings, source_mode, model_host):
    if (sources.version != settings.source_version or sources.store.run_id != sources.organizations.run_id
            or assembler.ACTION_ID != settings.action_id or worker.ACTION_ID != settings.action_id
            or worker.RESULT_TABLE != 'qs_' + _ACTIONS[settings.action_id][0] + '_results'
            or worker.ROLE != 'QS' or assembler.registry is not sources.registry
            or assembler.organizations is not sources.organizations or assembler.methods is not sources.methods
            or assembler.source_mode != source_mode or assembler.policy_version != settings.policy_version
            or assembler.model_version != settings.model_version or assembler._views.provider is not sources.provider
            or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != source_mode
            or worker.registry is not sources.registry or worker.store is not sources.store
            or worker.snapshots.store is not sources.store or worker.client_version != settings.client_version
            or worker.model_version != settings.model_version or sources.model_host is not model_host
            or any(getattr(worker, 'validate_' + name) is not getattr(sources.validators, name)
                for name in ('invocation', 'wait', 'recovery'))):
        raise TaskConflict('QS original components, versions or source callbacks changed')
    expected = () if model_host is None else tuple(model_host.bindings)
    if assembler.decision_strategies != expected:
        raise TaskConflict('QS assembler changed its explicitly bound model strategies')
    if model_host is not None and (model_host.store is not sources.store or model_host.registry is not sources.registry
            or model_host.model_version != settings.model_version):
        raise TaskConflict('QS model host changed its original journal, registry or version')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = QSRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('QS host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('QS feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, QSRoleContractSources):
        raise ValueError('QS source factory must return QSRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('QS sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('QS feedback source binding must match its explicit input configuration')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'QS' or not registration.implemented or registration.skill is None:
            raise ValueError('QS host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('QS execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline QS host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM QS host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.qs_' + module + '_actions'),
            'QS' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.qs_' + module + '_results'),
            'QS' + name + 'ResultWorker')
        if (not issubclass(assembler_type, QSMarketActionAssembler)
                or not issubclass(worker_type, QSMarketResultWorker)):
            raise ValueError('QS routing requires its original input assembler and result worker')
        source_mode = 'fixture' if offline else 'formal'
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
            from integration.qs_feedback_inputs import QSFeedbackInputAssembler
            feedback_assembler = QSFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        components = _component_descriptors(assembler, worker, settings.action_id)
        declared = {'schema_version': 'qs-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'host_factory': module_factory_descriptor(build_role_host, 'integration.qs_role_contract_host:build_role_host'),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode, **components,
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'qs_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('QS host configuration or code changed; explicit review required')
        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id])
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                prepared = _build_input(assembler, request.context, supplied.model_dump(mode='json'))
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('QS source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('QS executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or _component_descriptors(assembler, worker, settings.action_id) != components
                    or module_factory_descriptor(build_role_host, 'integration.qs_role_contract_host:build_role_host')
                        != declared['host_factory']
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.context.run_id != sources.store.run_id
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations
                    or (model_host.configuration_sha256 if model_host is not None else None)
                        != declared['model_configuration_sha256']):
                raise TaskConflict('QS original sources, components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('QS feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('QS execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('QS source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'), 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='qs-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence)},
            execute=execute)
    except Exception:
        sources.close()
        raise
