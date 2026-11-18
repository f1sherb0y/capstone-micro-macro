"""Explicit single-action Government host using original assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.government_advice_actions import GovernmentAdviceActionAssembler
from integration.government_advice_results import GovernmentAdviceResultWorker
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import (
    RoleContractExecution, RoleContractHost, RoleContractHostConfiguration, RoleContractInvocation,
    prepare_role_contract_options,
)
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


class GovernmentRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class GovernmentArchitectMaterialSelection(StrictRecord):
    source_task_sha256: Digest
    publication_receipt_sha256: Digest
    receipt_ref: ref_type('ArchitectDeliverableReceipt')


class GovernmentArchitectMaterialSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, GovernmentArchitectMaterialSelection]


class GovernmentOwnerSupplementSelection(StrictRecord):
    source_task_sha256: Digest
    response_refs: Annotated[list[ref_type('Response')], Field(min_length=1)]
    native_evidence_ref: ref_type('Evidence')


class GovernmentOwnerSupplementSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, GovernmentOwnerSupplementSelection]


class GovernmentSupplementVerificationSelection(StrictRecord):
    source_task_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class GovernmentSupplementVerificationSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, GovernmentSupplementVerificationSelection]


class GovernmentDecisionPermitSelection(StrictRecord):
    source_task_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class GovernmentDecisionPermitSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, GovernmentDecisionPermitSelection]


class GovernmentRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: GovernmentRoleFeedbackSettings | None = None
    architect_material_inputs: GovernmentArchitectMaterialSettings | None = None
    owner_supplement_inputs: GovernmentOwnerSupplementSettings | None = None
    supplement_verification_inputs: GovernmentSupplementVerificationSettings | None = None
    registered_decision_inputs: GovernmentDecisionPermitSettings | None = None


@dataclass(frozen=True)
class GovernmentSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Government invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class GovernmentRoleContractSources:
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
    validators: GovernmentSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    read_architect_publication: Callable | None = None
    validate_architect_reception: Callable | None = None
    read_owner_supplement: Callable | None = None
    validate_owner_supplement_reception: Callable | None = None
    read_supplement_verification: Callable | None = None
    validate_supplement_application: Callable | None = None
    read_registered_decision: Callable | None = None
    validate_decision_permit_registration: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, GovernmentSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Government sources require original registries, persistent journal, reader and callbacks')
        if ((self.read_registered_decision is None) != (self.validate_decision_permit_registration is None)
                or self.read_registered_decision is not None and (
                    not callable(self.read_registered_decision) or not callable(self.validate_decision_permit_registration))):
            raise ValueError('Decision permits require paired original reader and independent native registration validator')
        if ((self.read_supplement_verification is None) != (self.validate_supplement_application is None)
                or self.read_supplement_verification is not None and (
                    not callable(self.read_supplement_verification) or not callable(self.validate_supplement_application))):
            raise ValueError('Supplement verification requires paired original reader and independent native application validator')
        if ((self.read_owner_supplement is None) != (self.validate_owner_supplement_reception is None)
                or self.read_owner_supplement is not None and (
                    not callable(self.read_owner_supplement) or not callable(self.validate_owner_supplement_reception))):
            raise ValueError('Owner supplements require paired original reader and independent reception validator')
        if ((self.read_architect_publication is None) != (self.validate_architect_reception is None)
                or self.read_architect_publication is not None and (
                    not callable(self.read_architect_publication) or not callable(self.validate_architect_reception))):
            raise ValueError('Architect material reception requires paired original reader and validator')
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.government_submission_feedback import GovernmentSubmissionFeedback
            if (not isinstance(self.feedback, GovernmentSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Government feedback requires original same-journal feedback and input validation')


# Closed routing: action input cannot select a processor, module or result table.
_ACTIONS = {
    'GOV-A01': ('advice', 'Advice'), 'GOV-A02': ('intake', 'Intake'),
    'GOV-A03': ('scheduling', 'Scheduling'), 'GOV-A04': ('review', 'Review'),
    'GOV-A05': ('consultation', 'Consultation'), 'GOV-A06': ('supplement', 'Supplement'),
    'GOV-A07': ('decision', 'Decision'), 'GOV-A08': ('permit', 'Permit'),
    'GOV-A09': ('transition', 'Transition'), 'GOV-A10': ('inspection', 'Inspection'),
    'GOV-A11': ('use', 'Use'), 'GOV-A12': ('feedback', 'Feedback'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Government source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Government source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Government source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    if sources.read_registered_decision is not None:
        from integration.government_decision_permit_handoff import read_registered_decision_permit
        from integration.government_submission_host import GovernmentSubmissionHost
        callbacks.update(read_registered_decision=sources.read_registered_decision,
            validate_decision_permit_registration=sources.validate_decision_permit_registration,
            registered_decision_handoff=read_registered_decision_permit,
            original_decision_permit_receipt_reader=GovernmentSubmissionHost.read_receipt)
    if sources.read_supplement_verification is not None:
        from integration.government_supplement_decision_handoff import read_applied_supplement_resolutions
        from integration.government_submission_host import GovernmentSubmissionHost
        callbacks.update(read_supplement_verification=sources.read_supplement_verification,
            validate_supplement_application=sources.validate_supplement_application,
            supplement_verification_handoff=read_applied_supplement_resolutions,
            original_supplement_verification_receipt_reader=GovernmentSubmissionHost.read_receipt)
    if sources.read_owner_supplement is not None:
        from integration.owner_government_supplement_handoff import read_received_owner_supplement
        from integration.owner_submission_host import OwnerSubmissionHost
        callbacks.update(read_owner_supplement=sources.read_owner_supplement,
            validate_owner_supplement_reception=sources.validate_owner_supplement_reception,
            owner_supplement_handoff=read_received_owner_supplement,
            original_owner_supplement_receipt_reader=OwnerSubmissionHost.read_receipt)
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.read_architect_publication is not None:
        from integration.architect_government_intake_handoff import read_received_architect_deliverable
        callbacks.update(read_architect_publication=sources.read_architect_publication,
            validate_architect_reception=sources.validate_architect_reception,
            architect_material_handoff=read_received_architect_deliverable)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Retain the complete original Government input for every supported action."""
    prepared = assembler.build(context, **values)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('Government assembly changes the original supplied input')
    return prepared


def _component_descriptors(assembler, worker, action_id):
    return {name: module_factory_descriptor(callback, action_id) for name, callback in {
        'assembler_init': type(assembler).__init__, 'assembler': assembler.build,
        'worker_init': type(worker).__init__, 'worker': worker.execute,
        'source_validation': worker._validate_primary_sources,
    }.items()}


def _check_components(sources, assembler, worker, settings, source_mode, model_host):
    if (sources.version != settings.source_version or sources.store.run_id != sources.organizations.run_id
            or assembler.ACTION_ID != settings.action_id or worker.ACTION_ID != settings.action_id
            or worker.RESULT_TABLE != 'government_' + _ACTIONS[settings.action_id][0] + '_results'
            or worker.ROLE != 'Government' or assembler.registry is not sources.registry
            or assembler.organizations is not sources.organizations or assembler.methods is not sources.methods
            or assembler.source_mode != source_mode or assembler.policy_version != settings.policy_version
            or assembler.model_version != settings.model_version or assembler._views.provider is not sources.provider
            or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != source_mode
            or worker.registry is not sources.registry or worker.store is not sources.store
            or worker.snapshots.store is not sources.store or worker.client_version != settings.client_version
            or worker.model_version != settings.model_version or sources.model_host is not model_host
            or any(getattr(worker, 'validate_' + name) is not getattr(sources.validators, name)
                for name in ('invocation', 'wait', 'recovery'))):
        raise TaskConflict('Government original components, versions or source callbacks changed')
    expected = () if model_host is None else tuple(model_host.bindings)
    if assembler.decision_strategies != expected:
        raise TaskConflict('Government assembler changed its explicitly bound model strategies')
    if model_host is not None and (model_host.store is not sources.store or model_host.registry is not sources.registry
            or model_host.model_version != settings.model_version):
        raise TaskConflict('Government model host changed its original journal, registry or version')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = GovernmentRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Government host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    material_settings = settings.architect_material_inputs
    supplement_settings = settings.owner_supplement_inputs
    verification_settings = settings.supplement_verification_inputs
    decision_settings = settings.registered_decision_inputs
    if decision_settings is not None and (settings.action_id != 'GOV-A08'
            or request.context.operation_id not in decision_settings.selections):
        raise ValueError('Registered decision inputs require explicit GOV-A08 selections for this operation')
    if verification_settings is not None and (settings.action_id != 'GOV-A07'
            or request.context.operation_id not in verification_settings.selections):
        raise ValueError('Supplement verification inputs require explicit GOV-A07 selections for this operation')
    if supplement_settings is not None and (settings.action_id != 'GOV-A06'
            or request.context.operation_id not in supplement_settings.selections):
        raise ValueError('Owner supplement inputs require explicit GOV-A06 selections for this operation')
    if material_settings is not None and (settings.action_id != 'GOV-A02'
            or request.context.operation_id not in material_settings.selections):
        raise ValueError('Architect material inputs require explicit GOV-A02 selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Government feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, GovernmentRoleContractSources):
        raise ValueError('Government source factory must return GovernmentRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Government sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Government feedback source binding must match its explicit input configuration')
        if material_settings is not None and sources.read_architect_publication is None:
            raise ValueError('Configured architect materials require actual original publication and reception callbacks')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Government' or not registration.implemented or registration.skill is None:
            raise ValueError('Government host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Government execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Government host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Government host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.government_' + module + '_actions'),
            'Government' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.government_' + module + '_results'),
            'Government' + name + 'ResultWorker')
        if (not issubclass(assembler_type, GovernmentAdviceActionAssembler)
                or not issubclass(worker_type, GovernmentAdviceResultWorker)):
            raise ValueError('Government routing requires its original input assembler and result worker')
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
            from integration.government_feedback_inputs import GovernmentFeedbackInputAssembler
            feedback_assembler = GovernmentFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        components = _component_descriptors(assembler, worker, settings.action_id)
        declared = {'schema_version': 'government-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'host_factory': module_factory_descriptor(build_role_host, 'integration.government_role_contract_host:build_role_host'),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode, **components,
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'government_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Government host configuration or code changed; explicit review required')
        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id])
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                prepared = _build_input(assembler, request.context, supplied.model_dump(mode='json'))
        decision_provenance = None
        if decision_settings is not None:
            from integration.government_decision_permit_handoff import read_registered_decision_permit
            if sources.read_registered_decision is None:
                raise ValueError('Registered decision inputs require original reader and independent native registration validator')
            decision_selection = decision_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                decision_provenance = read_registered_decision_permit(prepared, **decision_selection,
                    read_decision=sources.read_registered_decision, validate_registration=sources.validate_decision_permit_registration)
        verification_provenance = None
        if verification_settings is not None:
            from integration.government_supplement_decision_handoff import read_applied_supplement_resolutions
            if sources.read_supplement_verification is None:
                raise ValueError('Supplement verification requires original reader and independent native application validator')
            verification_selection = verification_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                verification_provenance = read_applied_supplement_resolutions(prepared, **verification_selection,
                    read_verification=sources.read_supplement_verification, validate_application=sources.validate_supplement_application)
        supplement_provenance = None
        if supplement_settings is not None:
            from integration.owner_government_supplement_handoff import read_received_owner_supplement
            if sources.read_owner_supplement is None:
                raise ValueError('Owner supplements require original reader and independent reception validator')
            supplement_selection = supplement_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                supplement_provenance = read_received_owner_supplement(prepared, **supplement_selection,
                    read_supplement=sources.read_owner_supplement, validate_reception=sources.validate_owner_supplement_reception)
        material_provenance = None
        if material_settings is not None:
            from integration.architect_government_intake_handoff import read_received_architect_deliverable
            selection = material_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                material_provenance = read_received_architect_deliverable(prepared, **selection,
                    read_publication=sources.read_architect_publication,
                    validate_reception=sources.validate_architect_reception)
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Government source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Government executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or _component_descriptors(assembler, worker, settings.action_id) != components
                    or module_factory_descriptor(build_role_host, 'integration.government_role_contract_host:build_role_host')
                        != declared['host_factory']
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.context.run_id != sources.store.run_id
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations
                    or (model_host.configuration_sha256 if model_host is not None else None)
                        != declared['model_configuration_sha256']):
                raise TaskConflict('Government original sources, components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if decision_settings is not None:
                    current_decision = read_registered_decision_permit(prepared, **decision_selection,
                        read_decision=sources.read_registered_decision, validate_registration=sources.validate_decision_permit_registration)
                    if current_decision != decision_provenance:
                        raise TaskConflict('Original decision draft or actual signed permit registration changed before verification')
                if verification_settings is not None:
                    current_verification = read_applied_supplement_resolutions(prepared, **verification_selection,
                        read_verification=sources.read_supplement_verification, validate_application=sources.validate_supplement_application)
                    if current_verification != verification_provenance:
                        raise TaskConflict('Original supplement verification or actual issue/current-material application changed before decision')
                if supplement_settings is not None:
                    current_supplement = read_received_owner_supplement(prepared, **supplement_selection,
                        read_supplement=sources.read_owner_supplement, validate_reception=sources.validate_owner_supplement_reception)
                    if current_supplement != supplement_provenance:
                        raise TaskConflict('Original Owner supplement or actual agency response/current-material intake changed before execution')
                if material_settings is not None:
                    current_material = read_received_architect_deliverable(prepared, **selection,
                        read_publication=sources.read_architect_publication,
                        validate_reception=sources.validate_architect_reception)
                    if current_material != material_provenance:
                        raise TaskConflict('Original architect publication or reception changed before intake execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Government feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Government execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Government source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'), 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'architect_material_input': deepcopy(material_provenance),
                    'owner_supplement_input': deepcopy(supplement_provenance),
                    'supplement_verification_input': deepcopy(verification_provenance),
                    'registered_decision_input': deepcopy(decision_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='government-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'architect_material_input': deepcopy(material_provenance),
                'owner_supplement_input': deepcopy(supplement_provenance),
                'supplement_verification_input': deepcopy(verification_provenance),
                'registered_decision_input': deepcopy(decision_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
