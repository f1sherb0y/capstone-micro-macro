"""Explicit single-action Architect host using original assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker
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


class ArchitectRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class ArchitectCommissionSelection(StrictRecord):
    owner_task_sha256: Digest
    provider_task_sha256: Digest


class ArchitectCommissionInputSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ArchitectCommissionSelection]


class ArchitectReceivedOpinionSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('ArchitectReviewOpinionReceipt')
    native_evidence_ref: ref_type('Evidence')
    native_source_sha256: Digest
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class ArchitectReceivedOpinionSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ArchitectReceivedOpinionSelection]


class ArchitectReceivedReviewTaskSelection(StrictRecord):
    source_task_sha256: Digest
    registration_ref: ref_type('ArchitectReviewTaskRegistration')
    native_evidence_ref: ref_type('Evidence')
    native_source_sha256: Digest
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class ArchitectReceivedReviewTaskSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ArchitectReceivedReviewTaskSelection]


class ArchitectRegisteredDesignSelection(ArchitectReceivedReviewTaskSelection):
    registration_ref: ref_type('DesignRegistration')


class ArchitectRegisteredDesignSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ArchitectRegisteredDesignSelection]


class ArchitectRegisteredIntegrationSelection(ArchitectReceivedReviewTaskSelection):
    registration_ref: ref_type('IntegrationRegistration')


class ArchitectRegisteredIntegrationSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ArchitectRegisteredIntegrationSelection]


class ArchitectRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: ArchitectRoleFeedbackSettings | None = None
    commission_inputs: ArchitectCommissionInputSettings | None = None
    received_opinion_inputs: ArchitectReceivedOpinionSettings | None = None
    received_review_task_inputs: ArchitectReceivedReviewTaskSettings | None = None
    registered_design_inputs: ArchitectRegisteredDesignSettings | None = None
    registered_integration_inputs: ArchitectRegisteredIntegrationSettings | None = None


@dataclass(frozen=True)
class ArchitectSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Architect invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class ArchitectRoleContractSources:
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
    validators: ArchitectSourceValidators
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
    save_area_calculation: Callable | None = None
    publish_saved_area_calculations: Callable | None = None
    save_consistency_calculation: Callable | None = None
    publish_saved_consistency_calculations: Callable | None = None
    save_change_impact_calculation: Callable | None = None
    publish_saved_change_impact_calculations: Callable | None = None
    save_research_estimate_calculation: Callable | None = None
    publish_saved_research_estimate_calculations: Callable | None = None
    read_commission_decisions: Callable | None = None
    validate_commission_mapping: Callable | None = None
    read_review_opinion: Callable | None = None
    validate_review_opinion_mapping: Callable | None = None
    read_review_task: Callable | None = None
    validate_review_task_mapping: Callable | None = None
    read_registered_design: Callable | None = None
    validate_registered_design_mapping: Callable | None = None
    read_registered_integration: Callable | None = None
    validate_registered_integration_mapping: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, ArchitectSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Architect sources require original registries, persistent journal, reader and callbacks')
        if ((self.read_commission_decisions is None) != (self.validate_commission_mapping is None)
                or self.read_commission_decisions is not None and (
                    not callable(self.read_commission_decisions) or not callable(self.validate_commission_mapping))):
            raise ValueError('Commission reception requires paired original journal reader and mapping validator')
        if ((self.read_review_opinion is None) != (self.validate_review_opinion_mapping is None)
                or self.read_review_opinion is not None and (
                    not callable(self.read_review_opinion) or not callable(self.validate_review_opinion_mapping))):
            raise ValueError('Opinion reception requires paired original reviewer reader and independent mapping validator')
        if ((self.read_review_task is None) != (self.validate_review_task_mapping is None)
                or self.read_review_task is not None and (
                    not callable(self.read_review_task) or not callable(self.validate_review_task_mapping))):
            raise ValueError('Review task reception requires paired original A07 reader and independent mapping validator')
        if ((self.read_registered_design is None) != (self.validate_registered_design_mapping is None)
                or self.read_registered_design is not None and (
                    not callable(self.read_registered_design) or not callable(self.validate_registered_design_mapping))):
            raise ValueError('Design registration requires paired original A05 reader and independent mapping validator')
        if ((self.read_registered_integration is None) != (self.validate_registered_integration_mapping is None)
                or self.read_registered_integration is not None and (
                    not callable(self.read_registered_integration) or not callable(self.validate_registered_integration_mapping))):
            raise ValueError('Integration registration requires paired original A06 reader and mapping validator')
        if ((self.save_learning_assessment is None) != (self.publish_saved_learning_assessment is None)
                or self.save_learning_assessment is not None and (
                    not callable(self.save_learning_assessment) or not callable(self.publish_saved_learning_assessment))):
            raise ValueError('Architect assessment persistence requires paired explicit save/publish callbacks')
        if ((self.save_training_estimate is None) != (self.publish_saved_training_estimate is None)
                or self.save_training_estimate is not None and (
                    not callable(self.save_training_estimate) or not callable(self.publish_saved_training_estimate))):
            raise ValueError('Architect training persistence requires paired explicit save/publish callbacks')
        if ((self.save_area_calculation is None) != (self.publish_saved_area_calculations is None)
                or self.save_area_calculation is not None and (
                    not callable(self.save_area_calculation) or not callable(self.publish_saved_area_calculations))):
            raise ValueError('Architect area persistence requires paired explicit save/publish callbacks')
        if ((self.save_consistency_calculation is None) != (self.publish_saved_consistency_calculations is None)
                or self.save_consistency_calculation is not None and (
                    not callable(self.save_consistency_calculation) or not callable(self.publish_saved_consistency_calculations))):
            raise ValueError('Architect consistency persistence requires paired explicit save/publish callbacks')
        if ((self.save_change_impact_calculation is None) != (self.publish_saved_change_impact_calculations is None)
                or self.save_change_impact_calculation is not None and (
                    not callable(self.save_change_impact_calculation) or not callable(self.publish_saved_change_impact_calculations))):
            raise ValueError('Architect impact persistence requires paired explicit save/publish callbacks')
        if ((self.save_research_estimate_calculation is None) != (self.publish_saved_research_estimate_calculations is None)
                or self.save_research_estimate_calculation is not None and (
                    not callable(self.save_research_estimate_calculation) or not callable(self.publish_saved_research_estimate_calculations))):
            raise ValueError('Architect research estimate persistence requires paired explicit save/publish callbacks')
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.architect_submission_feedback import ArchitectSubmissionFeedback
            if (not isinstance(self.feedback, ArchitectSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Architect feedback requires original same-journal feedback and input validation')


# Closed routing: action input cannot select a processor, module or result table.
_ACTIONS = {
    'ARCHITECT-A01': ('opportunity', 'Opportunity'), 'ARCHITECT-A02': ('intake', 'Intake'),
    'ARCHITECT-A03': ('appointment', 'Appointment'), 'ARCHITECT-A04': ('planning', 'Planning'),
    'ARCHITECT-A05': ('design', 'Design'), 'ARCHITECT-A06': ('integration', 'Integration'),
    'ARCHITECT-A07': ('deliverable', 'Deliverable'), 'ARCHITECT-A08': ('review', 'Review'),
    'ARCHITECT-A09': ('change', 'Change'), 'ARCHITECT-A10': ('billing', 'Billing'),
    'ARCHITECT-A11': ('transition', 'Transition'), 'ARCHITECT-A12': ('learning', 'Learning'),
    'ARCHITECT-A13': ('research', 'Research'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Architect source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Architect source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Architect source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.read_commission_decisions is not None:
        from integration.owner_architect_commission_handoff import read_owner_architect_commission
        callbacks.update(read_commission_decisions=sources.read_commission_decisions,
            validate_commission_mapping=sources.validate_commission_mapping,
            commission_handoff=read_owner_architect_commission)
    if sources.read_review_opinion is not None:
        from integration.architect_review_opinion_inputs import prepare_architect_received_opinion
        from integration.architect_review_actions import ArchitectReviewActionAssembler
        from integration.architect_review_opinion_handoff import prepare_received_architect_review_opinion
        callbacks.update(read_review_opinion=sources.read_review_opinion,
            validate_review_opinion_mapping=sources.validate_review_opinion_mapping,
            received_opinion_inputs=prepare_architect_received_opinion,
            received_opinion_assembly=ArchitectReviewActionAssembler.build_from_received_opinion,
            received_opinion_source_gate=ArchitectReviewActionAssembler._prepare_received_opinion,
            received_opinion_handoff=prepare_received_architect_review_opinion)
    if sources.read_review_task is not None:
        from integration.architect_review_task_inputs import prepare_architect_received_review_task
        from integration.architect_review_actions import ArchitectReviewActionAssembler
        from integration.architect_review_task_handoff import prepare_architect_review_task_handoff
        callbacks.update(read_review_task=sources.read_review_task,
            validate_review_task_mapping=sources.validate_review_task_mapping,
            received_review_task_inputs=prepare_architect_received_review_task,
            received_review_task_assembly=ArchitectReviewActionAssembler.build_from_review_task,
            received_review_task_handoff=prepare_architect_review_task_handoff)
    if sources.read_registered_design is not None:
        from integration.architect_registered_design_inputs import prepare_architect_registered_design
        from integration.architect_integration_actions import ArchitectIntegrationActionAssembler
        from integration.architect_design_registration_handoff import prepare_architect_design_registration_handoff
        callbacks.update(read_registered_design=sources.read_registered_design,
            validate_registered_design_mapping=sources.validate_registered_design_mapping,
            registered_design_inputs=prepare_architect_registered_design,
            registered_design_assembly=ArchitectIntegrationActionAssembler.build_from_registered_design,
            registered_design_handoff=prepare_architect_design_registration_handoff)
    if sources.read_registered_integration is not None:
        from integration.architect_registered_integration_inputs import prepare_architect_registered_integration
        from integration.architect_deliverable_actions import ArchitectDeliverableActionAssembler
        from integration.architect_integration_registration_handoff import prepare_architect_integration_registration_handoff
        callbacks.update(read_registered_integration=sources.read_registered_integration,
            validate_registered_integration_mapping=sources.validate_registered_integration_mapping,
            registered_integration_inputs=prepare_architect_registered_integration,
            registered_integration_assembly=ArchitectDeliverableActionAssembler.build_from_registered_integration,
            registered_integration_handoff=prepare_architect_integration_registration_handoff)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.save_learning_assessment is not None:
        callbacks.update(save_learning_assessment=sources.save_learning_assessment,
            publish_saved_learning_assessment=sources.publish_saved_learning_assessment)
    if sources.save_training_estimate is not None:
        callbacks.update(save_training_estimate=sources.save_training_estimate,
            publish_saved_training_estimate=sources.publish_saved_training_estimate)
    if sources.save_area_calculation is not None:
        callbacks.update(save_area_calculation=sources.save_area_calculation,
            publish_saved_area_calculations=sources.publish_saved_area_calculations)
    if sources.save_consistency_calculation is not None:
        callbacks.update(save_consistency_calculation=sources.save_consistency_calculation,
            publish_saved_consistency_calculations=sources.publish_saved_consistency_calculations)
    if sources.save_change_impact_calculation is not None:
        callbacks.update(save_change_impact_calculation=sources.save_change_impact_calculation,
            publish_saved_change_impact_calculations=sources.publish_saved_change_impact_calculations)
    if sources.save_research_estimate_calculation is not None:
        callbacks.update(save_research_estimate_calculation=sources.save_research_estimate_calculation,
            publish_saved_research_estimate_calculations=sources.publish_saved_research_estimate_calculations)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Retain the complete original Architect input for every supported action."""
    prepared = assembler.build(context, **values)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('Architect assembly changes the original supplied input')
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
            or worker.RESULT_TABLE != 'architect_' + _ACTIONS[settings.action_id][0] + '_results'
            or worker.ROLE != 'Architect' or assembler.registry is not sources.registry
            or assembler.organizations is not sources.organizations or assembler.methods is not sources.methods
            or assembler.source_mode != source_mode or assembler.policy_version != settings.policy_version
            or assembler.model_version != settings.model_version or assembler._views.provider is not sources.provider
            or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != source_mode
            or worker.registry is not sources.registry or worker.store is not sources.store
            or worker.snapshots.store is not sources.store or worker.client_version != settings.client_version
            or worker.model_version != settings.model_version or sources.model_host is not model_host
            or any(getattr(worker, 'validate_' + name) is not getattr(sources.validators, name)
                for name in ('invocation', 'wait', 'recovery'))):
        raise TaskConflict('Architect original components, versions or source callbacks changed')
    expected = () if model_host is None else tuple(model_host.bindings)
    if assembler.decision_strategies != expected:
        raise TaskConflict('Architect assembler changed its explicitly bound model strategies')
    if model_host is not None and (model_host.store is not sources.store or model_host.registry is not sources.registry
            or model_host.model_version != settings.model_version):
        raise TaskConflict('Architect model host changed its original journal, registry or version')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = ArchitectRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Architect host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    commission_settings = settings.commission_inputs
    opinion_settings = settings.received_opinion_inputs
    review_task_settings = settings.received_review_task_inputs
    design_settings = settings.registered_design_inputs
    integration_settings = settings.registered_integration_inputs
    if integration_settings is not None and (offline or settings.action_id != 'ARCHITECT-A07'
            or request.context.operation_id not in integration_settings.selections
            or any(v is not None for v in (feedback_settings, opinion_settings, review_task_settings, design_settings))):
        raise ValueError('Registered integration requires explicit formal A07 selection without competing input assembly')
    if design_settings is not None and (offline or settings.action_id != 'ARCHITECT-A06'
            or request.context.operation_id not in design_settings.selections
            or any(v is not None for v in (feedback_settings, opinion_settings, review_task_settings))):
        raise ValueError('Registered designs require explicit formal A06 selection without competing input assembly')
    if review_task_settings is not None and (offline or settings.action_id != 'ARCHITECT-A08'
            or request.context.operation_id not in review_task_settings.selections
            or feedback_settings is not None or opinion_settings is not None):
        raise ValueError('Received review tasks require explicit formal A08 selection without competing input assembly')
    if opinion_settings is not None and (offline or settings.action_id != 'ARCHITECT-A08'
            or request.context.operation_id not in opinion_settings.selections or feedback_settings is not None):
        raise ValueError('Received opinion inputs require explicit formal A08 selection without competing feedback assembly')
    if commission_settings is not None and (settings.action_id != 'ARCHITECT-A03'
            or request.context.operation_id not in commission_settings.selections):
        raise ValueError('Commission inputs require explicit A03 original task selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Architect feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, ArchitectRoleContractSources):
        raise ValueError('Architect source factory must return ArchitectRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Architect sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Architect feedback source binding must match its explicit input configuration')
        if commission_settings is not None and sources.read_commission_decisions is None:
            raise ValueError('Configured commission inputs require actual application journal and reception callbacks')
        if opinion_settings is not None and sources.read_review_opinion is None:
            raise ValueError('Configured received opinions require actual reviewer journal and reception callbacks')
        if review_task_settings is not None and sources.read_review_task is None:
            raise ValueError('Configured review tasks require actual A07 journal and intake mapping callbacks')
        if design_settings is not None and sources.read_registered_design is None:
            raise ValueError('Configured designs require actual A05 journal and native registration callbacks')
        if integration_settings is not None and sources.read_registered_integration is None:
            raise ValueError('Configured integration requires actual A06 journal and native registration callbacks')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise ValueError('Architect host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Architect execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Architect host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Architect host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.architect_' + module + '_actions'),
            'Architect' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.architect_' + module + '_results'),
            'Architect' + name + 'ResultWorker')
        if (not issubclass(assembler_type, ArchitectOpportunityActionAssembler)
                or not issubclass(worker_type, ArchitectOpportunityResultWorker)):
            raise ValueError('Architect routing requires its original input assembler and result worker')
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
            from integration.architect_feedback_inputs import ArchitectFeedbackInputAssembler
            feedback_assembler = ArchitectFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        components = _component_descriptors(assembler, worker, settings.action_id)
        declared = {'schema_version': 'architect-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'host_factory': module_factory_descriptor(build_role_host, 'integration.architect_role_contract_host:build_role_host'),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode, **components,
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'architect_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Architect host configuration or code changed; explicit review required')
        opinion_provenance = None
        opinion_selection = None
        review_task_provenance = None
        review_task_selection = None
        design_provenance = None
        design_selection = None
        integration_provenance = None
        integration_selection = None
        if integration_settings is not None:
            from integration.architect_registered_integration_inputs import prepare_architect_registered_integration
            integration_selection = integration_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, integration_provenance = prepare_architect_registered_integration(assembler,
                    context=request.context, action_input=supplied, selection=integration_selection,
                    read_integration=sources.read_registered_integration,
                    validate_mapping=sources.validate_registered_integration_mapping, read_guard=sources.read_guard)
        elif design_settings is not None:
            from integration.architect_registered_design_inputs import prepare_architect_registered_design
            design_selection = design_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, design_provenance = prepare_architect_registered_design(assembler,
                    context=request.context, action_input=supplied, selection=design_selection,
                    read_design=sources.read_registered_design, validate_mapping=sources.validate_registered_design_mapping,
                    read_guard=sources.read_guard)
        elif review_task_settings is not None:
            from integration.architect_review_task_inputs import prepare_architect_received_review_task
            review_task_selection = review_task_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, review_task_provenance = prepare_architect_received_review_task(assembler,
                    context=request.context, action_input=supplied, selection=review_task_selection,
                    read_task=sources.read_review_task, validate_mapping=sources.validate_review_task_mapping,
                    read_guard=sources.read_guard)
        elif opinion_settings is not None:
            from integration.architect_review_opinion_inputs import prepare_architect_received_opinion
            opinion_selection = opinion_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input).model_dump(mode='json')
                prepared, opinion_provenance = prepare_architect_received_opinion(assembler,
                    context=request.context, action_input=supplied, selection=opinion_selection,
                    read_opinion=sources.read_review_opinion, validate_mapping=sources.validate_review_opinion_mapping,
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
        commission_provenance = None
        if commission_settings is not None:
            from integration.owner_architect_commission_handoff import read_owner_architect_commission
            selection = commission_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                commission_provenance = read_owner_architect_commission(prepared, **selection,
                    read_decisions=sources.read_commission_decisions, validate_mapping=sources.validate_commission_mapping)
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Architect source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Architect executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or _component_descriptors(assembler, worker, settings.action_id) != components
                    or module_factory_descriptor(build_role_host, 'integration.architect_role_contract_host:build_role_host')
                        != declared['host_factory']
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.context.run_id != sources.store.run_id
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations
                    or (model_host.configuration_sha256 if model_host is not None else None)
                        != declared['model_configuration_sha256']):
                raise TaskConflict('Architect original sources, components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if integration_settings is not None:
                    current_integration, current_provenance = prepare_architect_registered_integration(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=integration_selection, read_integration=sources.read_registered_integration,
                        validate_mapping=sources.validate_registered_integration_mapping, read_guard=sources.read_guard)
                    if (current_provenance != integration_provenance
                            or current_integration.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original integration registration or frozen A07 sources changed before execution')
                if design_settings is not None:
                    current_design, current_provenance = prepare_architect_registered_design(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=design_selection, read_design=sources.read_registered_design,
                        validate_mapping=sources.validate_registered_design_mapping, read_guard=sources.read_guard)
                    if (current_provenance != design_provenance
                            or current_design.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original registered design or frozen A06 sources changed before execution')
                if review_task_settings is not None:
                    current_review, current_provenance = prepare_architect_received_review_task(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=review_task_selection, read_task=sources.read_review_task,
                        validate_mapping=sources.validate_review_task_mapping, read_guard=sources.read_guard)
                    if (current_provenance != review_task_provenance
                            or current_review.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original review task intake or frozen reviewer sources changed before A08 execution')
                if opinion_settings is not None:
                    current_opinion, current_provenance = prepare_architect_received_opinion(assembler,
                        context=prepared.context, action_input=prepared.action_input.model_dump(mode='json'),
                        selection=opinion_selection, read_opinion=sources.read_review_opinion,
                        validate_mapping=sources.validate_review_opinion_mapping, read_guard=sources.read_guard)
                    if (current_provenance != opinion_provenance
                            or current_opinion.reading_sha256 != prepared.reading_sha256):
                        raise TaskConflict('Original received opinion or frozen author sources changed before A08 execution')
                if commission_settings is not None:
                    current_commission = read_owner_architect_commission(prepared, **selection,
                        read_decisions=sources.read_commission_decisions,
                        validate_mapping=sources.validate_commission_mapping)
                    if current_commission != commission_provenance:
                        raise TaskConflict('Commission original decisions or reception changed before A03 execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Architect feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Architect execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Architect source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'), 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'commission_input': deepcopy(commission_provenance),
                    'received_opinion_input': deepcopy(opinion_provenance),
                    'received_review_task_input': deepcopy(review_task_provenance),
                    'registered_design_input': deepcopy(design_provenance),
                    'registered_integration_input': deepcopy(integration_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='architect-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'commission_input': deepcopy(commission_provenance),
                'received_opinion_input': deepcopy(opinion_provenance),
                'received_review_task_input': deepcopy(review_task_provenance),
                'registered_design_input': deepcopy(design_provenance),
                'registered_integration_input': deepcopy(integration_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
