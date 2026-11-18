"""Single-action Contractor host using existing durable action implementations."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

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
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


class ContractorRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class ContractorReceivedMaterialSelection(StrictRecord):
    source_task_sha256: Digest
    material_basis_refs: Annotated[list[ref_type('ReceivedMaterialBasis')], Field(min_length=1)]


class ContractorReceivedMaterialSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ContractorReceivedMaterialSelection]


class ContractorReceivedPaymentSelection(StrictRecord):
    source_task_sha256: Digest
    execution_refs: Annotated[list[ref_type('PaymentExecution')], Field(min_length=1)]


class ContractorReceivedPaymentSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ContractorReceivedPaymentSelection]


class ContractorReceivedAwardSelection(StrictRecord):
    source_task_sha256: Digest
    acceptance_ref: ref_type('PartyAcceptance')
    native_evidence_ref: ref_type('Evidence')


class ContractorReceivedAwardSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ContractorReceivedAwardSelection]


class ContractorReceivedTenderSelection(StrictRecord):
    source_task_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class ContractorReceivedTenderSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ContractorReceivedTenderSelection]


class ContractorReceivedPermitSelection(StrictRecord):
    source_task_sha256: Digest
    requirement_ref: ref_type('Requirement')
    verification_ref: ref_type('ReadinessVerification')
    native_evidence_ref: ref_type('Evidence')


class ContractorReceivedPermitSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, ContractorReceivedPermitSelection]


class ContractorRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: ContractorRoleFeedbackSettings | None = None
    received_material_inputs: ContractorReceivedMaterialSettings | None = None
    received_payment_inputs: ContractorReceivedPaymentSettings | None = None
    received_award_inputs: ContractorReceivedAwardSettings | None = None
    received_tender_inputs: ContractorReceivedTenderSettings | None = None
    received_permit_inputs: ContractorReceivedPermitSettings | None = None


@dataclass(frozen=True)
class ContractorSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Contractor invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class ContractorRoleContractSources:
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
    validators: ContractorSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    commercial_worker: CommercialTaskWorker | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    read_supplier_receiving: Callable | None = None
    validate_received_materials: Callable | None = None
    read_owner_payment: Callable | None = None
    validate_received_payments: Callable | None = None
    read_owner_award: Callable | None = None
    validate_received_award: Callable | None = None
    read_owner_tender: Callable | None = None
    validate_received_tender: Callable | None = None
    read_government_permit: Callable | None = None
    validate_received_permit: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, ContractorSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)
                or self.commercial_worker is not None and not isinstance(self.commercial_worker, CommercialTaskWorker)):
            raise ValueError('Contractor sources require original registries, journal, reader and callbacks')
        if ((self.read_government_permit is None) != (self.validate_received_permit is None)
                or self.read_government_permit is not None and (
                    not callable(self.read_government_permit) or not callable(self.validate_received_permit))):
            raise ValueError('Permit readiness requires paired original Government reader and independent reception validator')
        if ((self.read_owner_tender is None) != (self.validate_received_tender is None)
                or self.read_owner_tender is not None and (
                    not callable(self.read_owner_tender) or not callable(self.validate_received_tender))):
            raise ValueError('Received tender requires paired original Owner reader and independent intake validator')
        if ((self.read_owner_award is None) != (self.validate_received_award is None)
                or self.read_owner_award is not None and (
                    not callable(self.read_owner_award) or not callable(self.validate_received_award))):
            raise ValueError('Received award requires paired original Owner reader and independent reception validator')
        if ((self.read_supplier_receiving is None) != (self.validate_received_materials is None)
                or self.read_supplier_receiving is not None and (
                    not callable(self.read_supplier_receiving) or not callable(self.validate_received_materials))):
            raise ValueError('Received materials require paired original Supplier reader and reception validator')
        if ((self.read_owner_payment is None) != (self.validate_received_payments is None)
                or self.read_owner_payment is not None and (
                    not callable(self.read_owner_payment) or not callable(self.validate_received_payments))):
            raise ValueError('Received payments require paired authorized Owner reader and Contractor reception validator')
        if self.feedback is not None or self.validate_feedback_input is not None:
            from integration.contractor_submission_feedback import ContractorSubmissionFeedback
            if (not isinstance(self.feedback, ContractorSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Contractor feedback requires original same-journal feedback and input validation')


# A12 uses its existing commercial worker rather than a duplicate result table.
_ACTIONS = {
    'CONTRACTOR-A01': ('screening', 'Screening'), 'CONTRACTOR-A02': ('bid', 'Bid'),
    'CONTRACTOR-A03': ('amendment', 'Amendment'), 'CONTRACTOR-A04': ('formation', 'Formation'),
    'CONTRACTOR-A05': ('planning', 'Planning'), 'CONTRACTOR-A06': ('readiness', 'Readiness'),
    'CONTRACTOR-A07': ('execution', 'Execution'), 'CONTRACTOR-A08': ('quality', 'Quality'),
    'CONTRACTOR-A09': ('claim', 'Claim'), 'CONTRACTOR-A10': ('payment', 'Payment'),
    'CONTRACTOR-A11': ('closeout', 'Closeout'), 'CONTRACTOR-A12': ('commercial', 'Commercial'),
    'CONTRACTOR-A13': ('advice', 'Advice'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Contractor source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Contractor source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Contractor source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.read_supplier_receiving is not None:
        from integration.supplier_contractor_material_handoff import read_received_contractor_materials
        callbacks.update(read_supplier_receiving=sources.read_supplier_receiving,
            validate_received_materials=sources.validate_received_materials,
            received_material_handoff=read_received_contractor_materials)
    if sources.read_owner_payment is not None:
        from integration.owner_contractor_payment_handoff import read_received_contractor_payments
        callbacks.update(read_owner_payment=sources.read_owner_payment,
            validate_received_payments=sources.validate_received_payments,
            received_payment_handoff=read_received_contractor_payments)
    if sources.read_owner_award is not None:
        from integration.owner_contractor_award_handoff import read_received_owner_award
        from integration.owner_submission_host import OwnerSubmissionHost
        callbacks.update(read_owner_award=sources.read_owner_award,
            validate_received_award=sources.validate_received_award,
            received_award_handoff=read_received_owner_award,
            original_owner_award_receipt_reader=OwnerSubmissionHost.read_receipt)
    if sources.read_owner_tender is not None:
        from integration.owner_contractor_tender_handoff import read_received_owner_tender
        from integration.owner_submission_host import OwnerSubmissionHost
        callbacks.update(read_owner_tender=sources.read_owner_tender,
            validate_received_tender=sources.validate_received_tender,
            received_tender_handoff=read_received_owner_tender,
            original_owner_tender_receipt_reader=OwnerSubmissionHost.read_receipt)
    if sources.read_government_permit is not None:
        from integration.government_contractor_permit_handoff import read_received_permit_verification
        from integration.government_submission_host import GovernmentSubmissionHost
        callbacks.update(read_government_permit=sources.read_government_permit,
            validate_received_permit=sources.validate_received_permit,
            received_permit_handoff=read_received_permit_verification,
            original_government_permit_receipt_reader=GovernmentSubmissionHost.read_receipt)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _build_input(assembler, context, values):
    """Use each original assembler's explicit selection and compare the full input."""
    action_id = context.contract_ref.id
    if action_id == 'CONTRACTOR-A12':
        arguments = {'profile_ref': values['continuation_profile_ref']}
    elif action_id == 'CONTRACTOR-A02':
        arguments = {key: values[key] for key in ('pricing_profile_ref', 'capacity_ref', 'cost_refs')}
        if 'allowed_method_refs' in values:
            arguments['allowed_method_refs'] = values['allowed_method_refs']
    else:
        arguments = values
    prepared = assembler.build(context, **arguments)
    if prepared.action_input.model_dump(mode='json') != values:
        raise TaskConflict('Contractor assembly changes the original supplied input')
    return prepared


def _check_components(sources, assembler, worker, settings, source_mode, model_host):
    commercial = settings.action_id == 'CONTRACTOR-A12'
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
        raise TaskConflict('Contractor original components, versions or source callbacks changed')
    if commercial:
        if sources.commercial_worker is not worker or worker.assembler is not assembler:
            raise TaskConflict('Contractor A12 requires its original commercial worker and assembler')
        expected = () if model_host is None else tuple(model_host.bindings)
        if assembler.decision_strategies != expected:
            raise TaskConflict('Contractor A12 requires its original explicitly bound model strategies')
    elif worker.registry is not sources.registry:
        raise TaskConflict('Contractor result worker requires its original registry')


def build_role_host(*, request, output_directory, offline, configuration):
    """Build one authorized decision; native submission and feedback are separate."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Contractor host requires a matching explicit action and execution mode')
    feedback_settings = settings.feedback_inputs
    material_settings = settings.received_material_inputs
    payment_settings = settings.received_payment_inputs
    award_settings = settings.received_award_inputs
    tender_settings = settings.received_tender_inputs
    permit_settings = settings.received_permit_inputs
    if permit_settings is not None and (settings.action_id != 'CONTRACTOR-A06'
            or request.context.operation_id not in permit_settings.selections):
        raise ValueError('Permit readiness inputs require explicit CONTRACTOR-A06 selections for this operation')
    if tender_settings is not None and (settings.action_id != 'CONTRACTOR-A02'
            or request.context.operation_id not in tender_settings.selections):
        raise ValueError('Received tender requires explicit CONTRACTOR-A02 selections for this operation')
    if award_settings is not None and (settings.action_id != 'CONTRACTOR-A04'
            or request.context.operation_id not in award_settings.selections):
        raise ValueError('Received award requires explicit CONTRACTOR-A04 selections for this operation')
    if payment_settings is not None and (offline or settings.action_id != 'CONTRACTOR-A10'
            or request.context.operation_id not in payment_settings.selections):
        raise ValueError('Received payments require explicit formal CONTRACTOR-A10 selections for this operation')
    if material_settings is not None and (settings.action_id != 'CONTRACTOR-A07'
            or request.context.operation_id not in material_settings.selections):
        raise ValueError('Received materials require explicit CONTRACTOR-A07 selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Contractor feedback requires formal mode and unique saved selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, ContractorRoleContractSources):
        raise ValueError('Contractor source factory must return ContractorRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Contractor sources change their declared version, run or factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Contractor feedback source binding must match its explicit input configuration')
        if material_settings is not None and sources.read_supplier_receiving is None:
            raise ValueError('Configured materials require original Supplier journal and actual receiver callbacks')
        if payment_settings is not None and sources.read_owner_payment is None:
            raise ValueError('Configured payments require lawfully shared original Owner history and actual receiver callbacks')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Contractor' or not registration.implemented or registration.skill is None:
            raise ValueError('Contractor host requires its implemented processor and original Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Contractor execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Contractor host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Contractor host requires its existing same-journal model host and budget')
        source_mode = 'fixture' if offline else 'formal'
        commercial = settings.action_id == 'CONTRACTOR-A12'
        if commercial:
            worker = sources.commercial_worker
            if worker is None:
                raise ValueError('Contractor A12 requires the existing commercial worker and wait journal')
            assembler = worker.assembler
        else:
            module, name = _ACTIONS[settings.action_id]
            assembler_type = getattr(importlib.import_module('integration.contractor_' + module + '_actions'),
                'Contractor' + name + 'ActionAssembler')
            worker_type = getattr(importlib.import_module('integration.contractor_' + module + '_results'),
                'Contractor' + name + 'ResultWorker')
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
            from integration.contractor_feedback_inputs import ContractorFeedbackInputAssembler
            feedback_assembler = ContractorFeedbackInputAssembler(assembler=assembler, worker=worker,
                action_id=settings.action_id, feedback=sources.feedback, version=feedback_settings.version,
                read_guard=sources.read_guard, validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        declared = {'schema_version': 'contractor-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': source_mode,
            'assembler': module_factory_descriptor(assembler.build, settings.action_id),
            'worker': module_factory_descriptor(worker.run if commercial else worker.execute, settings.action_id),
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        key = 'contractor_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Contractor host configuration or code changed; explicit review required')
        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id])
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                prepared = _build_input(assembler, request.context, supplied.model_dump(mode='json'))
        permit_provenance = None
        if permit_settings is not None:
            from integration.government_contractor_permit_handoff import read_received_permit_verification
            if sources.read_government_permit is None:
                raise ValueError('Permit readiness requires original Government reader and independent reception validator')
            permit_selection = permit_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                permit_provenance = read_received_permit_verification(prepared, **permit_selection,
                    read_permit=sources.read_government_permit, validate_reception=sources.validate_received_permit)
        tender_provenance = None
        if tender_settings is not None:
            from integration.owner_contractor_tender_handoff import read_received_owner_tender
            if sources.read_owner_tender is None:
                raise ValueError('Received tender requires original Owner source reader and independent intake validator')
            tender_selection = tender_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                tender_provenance = read_received_owner_tender(prepared, **tender_selection,
                    read_owner_tender=sources.read_owner_tender, validate_reception=sources.validate_received_tender)
        award_provenance = None
        if award_settings is not None:
            from integration.owner_contractor_award_handoff import read_received_owner_award
            if sources.read_owner_award is None:
                raise ValueError('Received award requires original Owner source reader and independent reception validator')
            award_selection = award_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                award_provenance = read_received_owner_award(prepared, **award_selection,
                    read_owner_award=sources.read_owner_award, validate_reception=sources.validate_received_award)
        payment_provenance = None
        if payment_settings is not None:
            from integration.owner_contractor_payment_handoff import read_received_contractor_payments
            payment_selection = payment_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                payment_provenance = read_received_contractor_payments(prepared, **payment_selection,
                    read_owner_payment=sources.read_owner_payment, validate_reception=sources.validate_received_payments)
        material_provenance = None
        if material_settings is not None:
            from integration.supplier_contractor_material_handoff import read_received_contractor_materials
            material_selection = material_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                material_provenance = read_received_contractor_materials(prepared, **material_selection,
                    read_receiving=sources.read_supplier_receiving, validate_reception=sources.validate_received_materials)
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Contractor source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Contractor executor requires its original invocation once, without replay')
            executed = True
            _check_components(sources, assembler, worker, settings, source_mode, model_host)
            if (_descriptors(sources) != callbacks
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or prepared.runner.registry is not sources.registry
                    or prepared.runner.organizations is not sources.organizations):
                raise TaskConflict('Contractor original sources or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if permit_settings is not None:
                    current_permit = read_received_permit_verification(prepared, **permit_selection,
                        read_permit=sources.read_government_permit, validate_reception=sources.validate_received_permit)
                    if current_permit != permit_provenance:
                        raise TaskConflict('Original agency permit findings or current Contractor readiness mapping changed before execution')
                if tender_settings is not None:
                    current_tender = read_received_owner_tender(prepared, **tender_selection,
                        read_owner_tender=sources.read_owner_tender, validate_reception=sources.validate_received_tender)
                    if current_tender != tender_provenance:
                        raise TaskConflict('Original Owner tender intake or authorized native package changed before Contractor execution')
                if award_settings is not None:
                    current_award = read_received_owner_award(prepared, **award_selection,
                        read_owner_award=sources.read_owner_award, validate_reception=sources.validate_received_award)
                    if current_award != award_provenance:
                        raise TaskConflict('Original Owner award reception or final agreement mapping changed before Contractor execution')
                if payment_settings is not None:
                    current_payment = read_received_contractor_payments(prepared, **payment_selection,
                        read_owner_payment=sources.read_owner_payment, validate_reception=sources.validate_received_payments)
                    if current_payment != payment_provenance:
                        raise TaskConflict('Original Owner payment or actual Contractor cash/receivable mapping changed before execution')
                if material_settings is not None:
                    current_material = read_received_contractor_materials(prepared, **material_selection,
                        read_receiving=sources.read_supplier_receiving,
                        validate_reception=sources.validate_received_materials)
                    if current_material != material_provenance:
                        raise TaskConflict('Original Supplier receipt or current material mapping changed before execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is not None:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Contractor feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                elif commercial:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id, purpose='action')
                else:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                bid_source_witness = None
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
                    capture_bid = identity.action_id == 'CONTRACTOR-A02'
                    audit_count = len(prepared.runner.audit_records)
                    original_retention = prepared.runner.retain_reading_evidence
                    if capture_bid:
                        prepared.runner.retain_reading_evidence = True
                    try:
                        outcome = worker.execute(identity, prepared)
                    finally:
                        prepared.runner.retain_reading_evidence = original_retention
                    record = worker.get_record(identity)
                    table = worker.RESULT_TABLE
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Contractor execution lacks its original durable result')
                if not commercial and capture_bid:
                    snapshot = worker.snapshots.get(identity)
                    witness = None
                    if len(prepared.runner.audit_records) > audit_count:
                        audit = prepared.runner.audit_records[-1]
                        witness = deepcopy(audit.source_reading_evidence)
                        if (audit.as_dict() != record['audit'] or not witness
                                or task_digest(witness) != record['audit']['reading'].get('sha256')):
                            raise TaskConflict('Bid source witness differs from its original execution audit')
                    # Recovery exposes saved originals, never a reconstructed reading.
                    bid_source_witness = {
                        'schema_version': 'contractor-bid-source-witness.v1',
                        'status': 'captured' if witness is not None else 'unavailable_saved_attempt',
                        'original_source_reading': witness,
                        'source_reading_sha256': record['audit']['reading'].get('sha256'),
                        'source_snapshot': snapshot, 'source_snapshot_sha256': task_digest(snapshot),
                        'source_record_sha256': record['record_sha256'],
                        'source_audit_reading_sha256': task_digest(record['audit']['reading']),
                    }
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Contractor source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': table,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record.get('source_reading_sha256'),
                    'bid_source_witness': bid_source_witness,
                    'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'received_material_input': deepcopy(material_provenance),
                    'received_payment_input': deepcopy(payment_provenance),
                    'received_award_input': deepcopy(award_provenance),
                    'received_tender_input': deepcopy(tender_provenance),
                    'received_permit_input': deepcopy(permit_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='contractor-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'received_material_input': deepcopy(material_provenance),
                'received_payment_input': deepcopy(payment_provenance),
                'received_award_input': deepcopy(award_provenance),
                'received_tender_input': deepcopy(tender_provenance),
                'received_permit_input': deepcopy(permit_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
