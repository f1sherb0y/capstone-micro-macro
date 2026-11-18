"""Explicit single-action Engineer host using original assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker
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


class EngineerRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class EngineerRegisteredDesignSelection(StrictRecord):
    source_task_sha256: Digest
    registration_ref: ref_type('EngineerDesignRegistration')
    native_evidence_ref: ref_type('Evidence')
    native_source_sha256: Digest
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class EngineerRegisteredDesignSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, EngineerRegisteredDesignSelection]


class EngineerRegisteredRevisionSelection(EngineerRegisteredDesignSelection):
    registration_ref: ref_type('EngineerRevisionRegistration')


class EngineerRegisteredRevisionSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, EngineerRegisteredRevisionSelection]


class EngineerRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: EngineerRoleFeedbackSettings | None = None
    registered_design_inputs: EngineerRegisteredDesignSettings | None = None
    registered_revision_inputs: EngineerRegisteredRevisionSettings | None = None


@dataclass(frozen=True)
class EngineerSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Engineer invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class EngineerRoleContractSources:
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
    validators: EngineerSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    save_learning_assessment: Callable | None = None
    publish_saved_learning_assessment: Callable | None = None
    save_training_estimate: Callable | None = None
    publish_saved_training_estimate: Callable | None = None
    save_parameter_calculation: Callable | None = None
    publish_saved_parameter_calculations: Callable | None = None
    save_interface_check_calculation: Callable | None = None
    publish_saved_interface_check_calculations: Callable | None = None
    publish_saved_design_calculations: Callable | None = None
    publish_saved_change_revision_calculations: Callable | None = None
    save_review_check_calculation: Callable | None = None
    publish_saved_review_check_calculations: Callable | None = None
    save_research_check_calculation: Callable | None = None
    publish_saved_research_check_calculations: Callable | None = None
    save_inspection_check_calculation: Callable | None = None
    publish_saved_inspection_check_calculations: Callable | None = None
    save_change_check_calculation: Callable | None = None
    publish_saved_change_check_calculations: Callable | None = None
    save_change_parameter_calculation: Callable | None = None
    publish_saved_change_parameter_calculations: Callable | None = None
    save_change_revision_check_calculation: Callable | None = None
    publish_saved_change_revision_check_calculations: Callable | None = None
    save_research_estimate_calculation: Callable | None = None
    publish_saved_research_estimate_calculations: Callable | None = None
    read_registered_design: Callable | None = None
    validate_registered_design_mapping: Callable | None = None
    read_registered_revision: Callable | None = None
    validate_registered_revision_mapping: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, EngineerSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Engineer sources require original registries, persistent journal, reader and callbacks')
        if ((self.read_registered_design is None) != (self.validate_registered_design_mapping is None)
                or self.read_registered_design is not None and (
                    not callable(self.read_registered_design) or not callable(self.validate_registered_design_mapping))):
            raise ValueError('Engineer design registration requires paired original A05 reader and mapping validator')
        if ((self.read_registered_revision is None) != (self.validate_registered_revision_mapping is None)
                or self.read_registered_revision is not None and (
                    not callable(self.read_registered_revision) or not callable(self.validate_registered_revision_mapping))):
            raise ValueError('Engineer revision registration requires paired original A09 reader and mapping validator')
        if ((self.save_learning_assessment is None) != (self.publish_saved_learning_assessment is None)
                or self.save_learning_assessment is not None and (
                    not callable(self.save_learning_assessment) or not callable(self.publish_saved_learning_assessment))):
            raise ValueError('Engineer assessment persistence requires paired explicit save/publish callbacks')
        if ((self.save_training_estimate is None) != (self.publish_saved_training_estimate is None)
                or self.save_training_estimate is not None and (
                    not callable(self.save_training_estimate) or not callable(self.publish_saved_training_estimate))):
            raise ValueError('Engineer training persistence requires paired explicit save/publish callbacks')
        if ((self.save_parameter_calculation is None) != (self.publish_saved_parameter_calculations is None)
                or self.save_parameter_calculation is not None and (
                    not callable(self.save_parameter_calculation) or not callable(self.publish_saved_parameter_calculations))):
            raise ValueError('Engineer parameter persistence requires paired explicit save/publish callbacks')
        if ((self.save_interface_check_calculation is None) != (self.publish_saved_interface_check_calculations is None)
                or self.save_interface_check_calculation is not None and (
                    not callable(self.save_interface_check_calculation) or not callable(self.publish_saved_interface_check_calculations))):
            raise ValueError('Engineer interface-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_review_check_calculation is None) != (self.publish_saved_review_check_calculations is None)
                or self.save_review_check_calculation is not None and (
                    not callable(self.save_review_check_calculation) or not callable(self.publish_saved_review_check_calculations))):
            raise ValueError('Engineer review-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_research_check_calculation is None) != (self.publish_saved_research_check_calculations is None)
                or self.save_research_check_calculation is not None and (
                    not callable(self.save_research_check_calculation) or not callable(self.publish_saved_research_check_calculations))):
            raise ValueError('Engineer research-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_inspection_check_calculation is None) != (self.publish_saved_inspection_check_calculations is None)
                or self.save_inspection_check_calculation is not None and (
                    not callable(self.save_inspection_check_calculation) or not callable(self.publish_saved_inspection_check_calculations))):
            raise ValueError('Engineer inspection-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_change_check_calculation is None) != (self.publish_saved_change_check_calculations is None)
                or self.save_change_check_calculation is not None and (
                    not callable(self.save_change_check_calculation) or not callable(self.publish_saved_change_check_calculations))):
            raise ValueError('Engineer change-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_change_parameter_calculation is None) != (self.publish_saved_change_parameter_calculations is None)
                or self.save_change_parameter_calculation is not None and (
                    not callable(self.save_change_parameter_calculation) or not callable(self.publish_saved_change_parameter_calculations))):
            raise ValueError('Engineer revision-parameter persistence requires paired explicit save/publish callbacks')
        if ((self.save_change_revision_check_calculation is None) != (self.publish_saved_change_revision_check_calculations is None)
                or self.save_change_revision_check_calculation is not None and (
                    not callable(self.save_change_revision_check_calculation) or not callable(self.publish_saved_change_revision_check_calculations))):
            raise ValueError('Engineer revision-check persistence requires paired explicit save/publish callbacks')
        if ((self.save_research_estimate_calculation is None) != (self.publish_saved_research_estimate_calculations is None)
                or self.save_research_estimate_calculation is not None and (
                    not callable(self.save_research_estimate_calculation) or not callable(self.publish_saved_research_estimate_calculations))):
            raise ValueError('Engineer research-estimate persistence requires paired explicit save/publish callbacks')
        if self.publish_saved_design_calculations is not None and (
                not callable(self.publish_saved_design_calculations) or self.save_parameter_calculation is None
                or self.save_interface_check_calculation is None):
            raise ValueError('Joint design publication requires both explicit parameter and check chains')
        if self.publish_saved_change_revision_calculations is not None and (
                not callable(self.publish_saved_change_revision_calculations)
                or self.save_change_parameter_calculation is None
                or self.save_change_revision_check_calculation is None):
            raise ValueError('Joint revision publication requires both explicit A09 parameter and check chains')
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.engineer_submission_feedback import EngineerSubmissionFeedback
            if (not isinstance(self.feedback, EngineerSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Engineer feedback requires original same-journal feedback and input validation')


# Closed routing: action input cannot select a processor, module or result table.
_ACTIONS = {
    'ENGINEER-A01': ('opportunity', 'Opportunity'), 'ENGINEER-A02': ('intake', 'Intake'),
    'ENGINEER-A03': ('appointment', 'Appointment'), 'ENGINEER-A04': ('planning', 'Planning'),
    'ENGINEER-A05': ('design', 'Design'), 'ENGINEER-A06': ('review', 'Review'),
    'ENGINEER-A07': ('deliverable', 'Deliverable'), 'ENGINEER-A08': ('inspection', 'Inspection'),
    'ENGINEER-A09': ('change', 'Change'), 'ENGINEER-A10': ('billing', 'Billing'),
    'ENGINEER-A11': ('transition', 'Transition'), 'ENGINEER-A12': ('learning', 'Learning'),
    'ENGINEER-A13': ('research', 'Research'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Engineer source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Engineer source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Engineer source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.read_registered_design is not None:
        from integration.engineer_registered_design_inputs import prepare_engineer_registered_design
        from integration.engineer_deliverable_actions import EngineerDeliverableActionAssembler
        from integration.engineer_design_registration_handoff import prepare_engineer_design_registration_handoff
        callbacks.update(read_registered_design=sources.read_registered_design,
            validate_registered_design_mapping=sources.validate_registered_design_mapping,
            registered_design_inputs=prepare_engineer_registered_design,
            registered_design_assembly=EngineerDeliverableActionAssembler.build_from_registered_design,
            registered_professional_work=EngineerDeliverableActionAssembler._build_from_registered_professional_work,
            registered_design_handoff=prepare_engineer_design_registration_handoff)
    if sources.read_registered_revision is not None:
        from integration.engineer_registered_revision_inputs import prepare_engineer_registered_revision
        from integration.engineer_deliverable_actions import EngineerDeliverableActionAssembler
        from integration.engineer_change_revision_registration_handoff import prepare_engineer_change_revision_registration_handoff
        callbacks.update(read_registered_revision=sources.read_registered_revision,
            validate_registered_revision_mapping=sources.validate_registered_revision_mapping,
            registered_revision_inputs=prepare_engineer_registered_revision,
            registered_revision_assembly=EngineerDeliverableActionAssembler.build_from_registered_revision,
            registered_revision_work=EngineerDeliverableActionAssembler._build_from_registered_professional_work,
            registered_revision_handoff=prepare_engineer_change_revision_registration_handoff)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.save_learning_assessment is not None:
        callbacks.update(save_learning_assessment=sources.save_learning_assessment,
            publish_saved_learning_assessment=sources.publish_saved_learning_assessment)
    if sources.save_training_estimate is not None:
        callbacks.update(save_training_estimate=sources.save_training_estimate,
            publish_saved_training_estimate=sources.publish_saved_training_estimate)
    if sources.save_parameter_calculation is not None:
        callbacks.update(save_parameter_calculation=sources.save_parameter_calculation,
            publish_saved_parameter_calculations=sources.publish_saved_parameter_calculations)
    if sources.save_interface_check_calculation is not None:
        callbacks.update(save_interface_check_calculation=sources.save_interface_check_calculation,
            publish_saved_interface_check_calculations=sources.publish_saved_interface_check_calculations)
    if sources.publish_saved_design_calculations is not None:
        callbacks['publish_saved_design_calculations'] = sources.publish_saved_design_calculations
    if sources.publish_saved_change_revision_calculations is not None:
        callbacks['publish_saved_change_revision_calculations'] = sources.publish_saved_change_revision_calculations
    if sources.save_review_check_calculation is not None:
        callbacks.update(save_review_check_calculation=sources.save_review_check_calculation,
            publish_saved_review_check_calculations=sources.publish_saved_review_check_calculations)
    if sources.save_research_check_calculation is not None:
        callbacks.update(save_research_check_calculation=sources.save_research_check_calculation,
            publish_saved_research_check_calculations=sources.publish_saved_research_check_calculations)
    if sources.save_inspection_check_calculation is not None:
        callbacks.update(save_inspection_check_calculation=sources.save_inspection_check_calculation,
            publish_saved_inspection_check_calculations=sources.publish_saved_inspection_check_calculations)
    if sources.save_change_check_calculation is not None:
        callbacks.update(save_change_check_calculation=sources.save_change_check_calculation,
            publish_saved_change_check_calculations=sources.publish_saved_change_check_calculations)
    if sources.save_change_parameter_calculation is not None:
        callbacks.update(save_change_parameter_calculation=sources.save_change_parameter_calculation,
            publish_saved_change_parameter_calculations=sources.publish_saved_change_parameter_calculations)
    if sources.save_change_revision_check_calculation is not None:
        callbacks.update(save_change_revision_check_calculation=sources.save_change_revision_check_calculation,
            publish_saved_change_revision_check_calculations=sources.publish_saved_change_revision_check_calculations)
    if sources.save_research_estimate_calculation is not None:
        callbacks.update(save_research_estimate_calculation=sources.save_research_estimate_calculation,
            publish_saved_research_estimate_calculations=sources.publish_saved_research_estimate_calculations)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Retain the complete original Engineer input for every supported action."""
    prepared = assembler.build(context, **values)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('Engineer assembly changes the original supplied input')
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
            or worker.RESULT_TABLE != 'engineer_' + _ACTIONS[settings.action_id][0] + '_results'
            or worker.ROLE != 'Engineer' or assembler.registry is not sources.registry
            or assembler.organizations is not sources.organizations or assembler.methods is not sources.methods
            or assembler.source_mode != source_mode or assembler.policy_version != settings.policy_version
            or assembler.model_version != settings.model_version or assembler._views.provider is not sources.provider
            or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != source_mode
            or worker.registry is not sources.registry or worker.store is not sources.store
            or worker.snapshots.store is not sources.store or worker.client_version != settings.client_version
            or worker.model_version != settings.model_version or sources.model_host is not model_host
            or any(getattr(worker, 'validate_' + name) is not getattr(sources.validators, name)
                for name in ('invocation', 'wait', 'recovery'))):
        raise TaskConflict('Engineer original components, versions or source callbacks changed')
    expected = () if model_host is None else tuple(model_host.bindings)
    if assembler.decision_strategies != expected:
        raise TaskConflict('Engineer assembler changed its explicitly bound model strategies')
    if model_host is not None and (model_host.store is not sources.store or model_host.registry is not sources.registry
            or model_host.model_version != settings.model_version):
        raise TaskConflict('Engineer model host changed its original journal, registry or version')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = EngineerRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Engineer host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    design_settings = settings.registered_design_inputs
    revision_settings = settings.registered_revision_inputs
    if revision_settings is not None and (offline or settings.action_id != 'ENGINEER-A07'
            or request.context.operation_id not in revision_settings.selections
            or feedback_settings is not None or design_settings is not None):
        raise ValueError('Registered revisions require explicit formal Engineer A07 selection without competing assembly')
    if design_settings is not None and (offline or settings.action_id != 'ENGINEER-A07'
            or request.context.operation_id not in design_settings.selections or feedback_settings is not None):
        raise ValueError('Registered designs require explicit formal Engineer A07 selection without competing feedback assembly')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Engineer feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, EngineerRoleContractSources):
        raise ValueError('Engineer source factory must return EngineerRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Engineer sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Engineer feedback source binding must match its explicit input configuration')
        if design_settings is not None and sources.read_registered_design is None:
            raise ValueError('Configured Engineer designs require actual A05 journal and native registration callbacks')
        if revision_settings is not None and sources.read_registered_revision is None:
            raise ValueError('Configured Engineer revisions require actual A09 journal and native registration callbacks')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Engineer' or not registration.implemented or registration.skill is None:
            raise ValueError('Engineer host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Engineer execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Engineer host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Engineer host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.engineer_' + module + '_actions'),
            'Engineer' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.engineer_' + module + '_results'),
            'Engineer' + name + 'ResultWorker')
        if (not issubclass(assembler_type, EngineerOpportunityActionAssembler)
                or not issubclass(worker_type, EngineerOpportunityResultWorker)):
            raise ValueError('Engineer routing requires its original input assembler and result worker')
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
            from integration.engineer_feedback_inputs import EngineerFeedbackInputAssembler
            feedback_assembler = EngineerFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        components = _component_descriptors(assembler, worker, settings.action_id)
        declared = {'schema_version': 'engineer-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'host_factory': module_factory_descriptor(build_role_host, 'integration.engineer_role_contract_host:build_role_host'),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode, **components,
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'engineer_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Engineer host configuration or code changed; explicit review required')
        design_provenance = None
        design_selection = None
        revision_provenance = None
        revision_selection = None
        if revision_settings is not None:
            from integration.engineer_registered_revision_inputs import prepare_engineer_registered_revision
            revision_selection = revision_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, revision_provenance = prepare_engineer_registered_revision(assembler,
                    context=request.context, action_input=supplied, selection=revision_selection,
                    read_revision=sources.read_registered_revision,
                    validate_mapping=sources.validate_registered_revision_mapping, read_guard=sources.read_guard)
        elif design_settings is not None:
            from integration.engineer_registered_design_inputs import prepare_engineer_registered_design
            design_selection = design_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, design_provenance = prepare_engineer_registered_design(assembler,
                    context=request.context, action_input=supplied, selection=design_selection,
                    read_design=sources.read_registered_design, validate_mapping=sources.validate_registered_design_mapping,
                    read_guard=sources.read_guard)
        elif feedback_assembler is not None:
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
            raise ValueError('Engineer source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Engineer executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or _component_descriptors(assembler, worker, settings.action_id) != components
                    or module_factory_descriptor(build_role_host, 'integration.engineer_role_contract_host:build_role_host')
                        != declared['host_factory']
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.context.run_id != sources.store.run_id
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations
                    or (model_host.configuration_sha256 if model_host is not None else None)
                        != declared['model_configuration_sha256']):
                raise TaskConflict('Engineer original sources, components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if revision_settings is not None:
                    current_revision, current_provenance = prepare_engineer_registered_revision(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=revision_selection, read_revision=sources.read_registered_revision,
                        validate_mapping=sources.validate_registered_revision_mapping, read_guard=sources.read_guard)
                    if (current_provenance != revision_provenance
                            or current_revision.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original Engineer revision registration or frozen A07 sources changed before execution')
                if design_settings is not None:
                    current_design, current_provenance = prepare_engineer_registered_design(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=design_selection, read_design=sources.read_registered_design,
                        validate_mapping=sources.validate_registered_design_mapping, read_guard=sources.read_guard)
                    if (current_provenance != design_provenance
                            or current_design.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original Engineer design registration or frozen A07 sources changed before execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Engineer feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Engineer execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Engineer source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'), 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'registered_design_input': deepcopy(design_provenance),
                    'registered_revision_input': deepcopy(revision_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='engineer-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'registered_design_input': deepcopy(design_provenance),
                'registered_revision_input': deepcopy(revision_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
