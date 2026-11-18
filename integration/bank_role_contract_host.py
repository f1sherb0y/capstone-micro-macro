"""Explicit single-action bank host using existing assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields, replace
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field, field_validator

from integration.action_model_host import ActionModelHost
from integration.bank_intake_actions import BankIntakeActionAssembler
from integration.bank_intake_results import BankIntakeResultWorker
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


class BankRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class BankOwnerApplicationSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('OwnerFinanceApplicationReceipt')
    receipt_sha256: Digest | None = None


class BankOwnerApplicationSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankOwnerApplicationSelection]


class BankOwnerAcceptanceSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('FinancingAcceptanceReceipt')
    receipt_sha256: Digest | None = None


class BankOwnerAcceptanceSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankOwnerAcceptanceSelection]


class BankOwnerDrawRequestSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('OwnerDrawRequestReceipt')
    receipt_sha256: Digest | None = None


class BankOwnerDrawRequestSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankOwnerDrawRequestSelection]


class BankDrawApprovalSelection(StrictRecord):
    draw_identity: TaskIdentity
    basis_ref: ref_type('BankDrawHandoffBasis')

    @field_validator('draw_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankDrawApprovalSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankDrawApprovalSelection]


class BankExecutionReceiptSelection(StrictRecord):
    source_task_sha256: Digest


class BankExecutionReceiptSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankExecutionReceiptSelection]


class BankIntakeSelection(StrictRecord):
    intake_identity: TaskIdentity
    basis_ref: ref_type('BankIntakeHandoffBasis')

    @field_validator('intake_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankIntakeSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankIntakeSelection]


class BankCreditSelection(StrictRecord):
    credit_identity: TaskIdentity
    basis_ref: ref_type('BankCreditHandoffBasis')

    @field_validator('credit_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankCreditSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, BankCreditSelection]


class BankRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: BankRoleFeedbackSettings | None = None
    owner_acceptance_inputs: BankOwnerAcceptanceSettings | None = None
    owner_draw_request_inputs: BankOwnerDrawRequestSettings | None = None
    draw_approval_inputs: BankDrawApprovalSettings | None = None
    execution_receipt_inputs: BankExecutionReceiptSettings | None = None
    owner_application_inputs: BankOwnerApplicationSettings | None = None
    intake_inputs: BankIntakeSettings | None = None
    credit_inputs: BankCreditSettings | None = None


@dataclass(frozen=True)
class BankSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Bank invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class BankRoleContractSources:
    """Application owns actual sources and a persistent run journal, including cleanup.

    read_guard(context) holds the application's current source/authorization
    boundary. The source factory owns partial resources until returning this
    object. No factory here invents a native record or creates a model client.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    store: TaskStore
    provider: object
    read_guard: Callable
    validators: BankSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    read_owner_financing: Callable | None = None
    validate_owner_acceptance_reception: Callable | None = None
    read_owner_payment: Callable | None = None
    validate_owner_draw_request_reception: Callable | None = None
    draw_worker: object = None
    validate_draw_history: Callable | None = None
    validate_draw_approval: Callable | None = None
    prepare_execution_reception: Callable | None = None
    validate_owner_application_reception: Callable | None = None
    intake_worker: object = None
    validate_intake_history: Callable | None = None
    validate_intake_handoff: Callable | None = None
    credit_worker: object = None
    validate_credit_history: Callable | None = None
    validate_credit_handoff: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, BankSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Bank sources require original registries, persistent journal, reader and callbacks')
        owner_validators = (self.validate_owner_acceptance_reception, self.validate_owner_application_reception)
        if ((self.read_owner_financing is None) != all(callback is None for callback in owner_validators)
                or self.read_owner_financing is not None and not callable(self.read_owner_financing)
                or any(callback is not None and not callable(callback) for callback in owner_validators)):
            raise ValueError('Bank Owner sources require original financing reader and explicit reception validators')
        if ((self.read_owner_payment is None) != (self.validate_owner_draw_request_reception is None)
                or self.read_owner_payment is not None and (
                    not callable(self.read_owner_payment) or not callable(self.validate_owner_draw_request_reception))):
            raise ValueError('Bank draw sources require paired original Owner payment reader and receiver validator')
        if any(value is not None for value in (self.draw_worker, self.validate_draw_history, self.validate_draw_approval)):
            _check_draw_approval_sources(self)
        if self.prepare_execution_reception is not None and not callable(self.prepare_execution_reception):
            raise ValueError('Bank execution receipt sources require an explicit reception callback')
        if any(value is not None for value in (self.intake_worker, self.validate_intake_history, self.validate_intake_handoff)):
            _check_intake_sources(self)
        if any(value is not None for value in (self.credit_worker, self.validate_credit_history, self.validate_credit_handoff)):
            _check_credit_sources(self)
        if self.feedback is not None or self.validate_feedback_input is not None:
            # Local import keeps the closed bank action routing available to
            # feedback/submission modules without an import cycle.
            from integration.bank_submission_feedback import BankSubmissionFeedback
            if (not isinstance(self.feedback, BankSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Bank feedback sources require original same-journal feedback and an input validator')


# Closed action routing; never load a processor or table named by input data.
_ACTIONS = {
    'BANK-A01': ('strategy', 'Strategy'), 'BANK-A02': ('intake', 'Intake'),
    'BANK-A03': ('credit', 'Credit'), 'BANK-A04': ('quote', 'Quote'),
    'BANK-A05': ('arrangement', 'Arrangement'), 'BANK-A06': ('draw', 'Draw'),
    'BANK-A07': ('execution', 'Execution'), 'BANK-A08': ('monitoring', 'Monitoring'),
    'BANK-A09': ('debt', 'Debt'), 'BANK-A10': ('resolution', 'Resolution'),
    'BANK-A11': ('closeout', 'Closeout'), 'BANK-A12': ('learning', 'Learning'),
    'BANK-A13': ('advice', 'Advice'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Bank source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Bank source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Bank source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.read_owner_financing is not None:
        from integration.owner_financing_bank_acceptance_handoff import read_received_owner_financing_acceptance
        from integration.owner_financing_bank_intake_handoff import read_received_owner_application
        callbacks['read_owner_financing'] = sources.read_owner_financing
        if sources.validate_owner_acceptance_reception is not None:
            callbacks.update(validate_owner_acceptance_reception=sources.validate_owner_acceptance_reception,
                owner_acceptance_handoff=read_received_owner_financing_acceptance)
        if sources.validate_owner_application_reception is not None:
            callbacks.update(validate_owner_application_reception=sources.validate_owner_application_reception,
                owner_application_handoff=read_received_owner_application)
    if sources.read_owner_payment is not None:
        from integration.owner_payment_bank_draw_handoff import read_received_owner_draw_request
        callbacks.update(read_owner_payment=sources.read_owner_payment,
            validate_owner_draw_request_reception=sources.validate_owner_draw_request_reception,
            owner_draw_request_handoff=read_received_owner_draw_request)
    if sources.draw_worker is not None:
        from integration.bank_draw_handoff import prepare_bank_draw_handoff
        callbacks.update(draw_history_reader=sources.draw_worker.read_completed,
            draw_approval_handoff=prepare_bank_draw_handoff,
            validate_draw_history=sources.validate_draw_history, validate_draw_approval=sources.validate_draw_approval)
    if sources.prepare_execution_reception is not None:
        callbacks['prepare_execution_reception'] = sources.prepare_execution_reception
    if sources.intake_worker is not None:
        from integration.bank_intake_handoff import prepare_bank_intake_handoff
        callbacks.update(intake_history_reader=sources.intake_worker.read_completed,
            intake_handoff=prepare_bank_intake_handoff, validate_intake_history=sources.validate_intake_history,
            validate_intake_handoff=sources.validate_intake_handoff)
    if sources.credit_worker is not None:
        from integration.bank_credit_handoff import prepare_bank_credit_handoff
        callbacks.update(credit_history_reader=sources.credit_worker.read_completed,
            credit_handoff=prepare_bank_credit_handoff, validate_credit_history=sources.validate_credit_history,
            validate_credit_handoff=sources.validate_credit_handoff)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def _check_draw_approval_sources(sources):
    from integration.bank_draw_results import BankDrawResultWorker

    if (not isinstance(sources.draw_worker, BankDrawResultWorker)
            or sources.draw_worker.ACTION_ID != 'BANK-A06'
            or sources.draw_worker.store is not sources.store or sources.draw_worker.registry is not sources.registry
            or sources.draw_worker.snapshots.store is not sources.store
            or not callable(sources.validate_draw_history) or not callable(sources.validate_draw_approval)):
        raise ValueError('Bank execution approval requires original same-journal A06 worker and explicit validators')


def _check_intake_sources(sources):
    if (not isinstance(sources.intake_worker, BankIntakeResultWorker)
            or sources.intake_worker.ACTION_ID != 'BANK-A02'
            or sources.intake_worker.store is not sources.store or sources.intake_worker.registry is not sources.registry
            or sources.intake_worker.snapshots.store is not sources.store
            or not callable(sources.validate_intake_history) or not callable(sources.validate_intake_handoff)):
        raise ValueError('Bank credit intake requires original same-journal A02 worker and explicit validators')


def _intake_handoff(sources, prepared, selection):
    """Read selected accepted intake and bind its independent native review task."""
    from integration.bank_intake_handoff import prepare_bank_intake_handoff

    _check_intake_sources(sources)
    if prepared.context.contract_ref.id != 'BANK-A03':
        raise TaskConflict('Intake lineage requires the original Bank credit action')
    identity = TaskIdentity(**selection.intake_identity.as_dict())
    try:
        saved = sources.intake_worker.read_completed(identity, current_context=prepared.context.model_copy(deep=True),
            reading=prepared.reading, execution_versions=identity.versions,
            validate_current=sources.validate_intake_history)
        handoff = prepare_bank_intake_handoff(saved, context=prepared.context.model_copy(deep=True),
            reading=prepared.reading, basis_ref=selection.basis_ref.model_copy(deep=True),
            application_ref=prepared.action_input.application_ref.model_copy(deep=True),
            product_ref=prepared.action_input.product_ref.model_copy(deep=True),
            validate_current=sources.validate_intake_handoff)
        if handoff.get('kind') != 'prepared':
            raise TaskConflict('Original intake did not establish acceptance for the actual review task')
        return {**deepcopy(handoff), 'intake_identity': identity.as_dict()}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Intake lineage changed original Bank credit context or input')


def _check_credit_sources(sources):
    from integration.bank_credit_results import BankCreditResultWorker

    if (not isinstance(sources.credit_worker, BankCreditResultWorker)
            or sources.credit_worker.ACTION_ID != 'BANK-A03'
            or sources.credit_worker.store is not sources.store or sources.credit_worker.registry is not sources.registry
            or sources.credit_worker.snapshots.store is not sources.store
            or not callable(sources.validate_credit_history) or not callable(sources.validate_credit_handoff)):
        raise ValueError('Bank quote review requires original same-journal A03 worker and explicit validators')


def _credit_handoff(sources, prepared, selection):
    """Bind the selected original review to its independently recorded assessment."""
    from integration.bank_credit_handoff import prepare_bank_credit_handoff

    _check_credit_sources(sources)
    if prepared.context.contract_ref.id != 'BANK-A04':
        raise TaskConflict('Credit lineage requires the original Bank quotation action')
    identity = TaskIdentity(**selection.credit_identity.as_dict())
    try:
        saved = sources.credit_worker.read_completed(identity, current_context=prepared.context.model_copy(deep=True),
            reading=prepared.reading, execution_versions=identity.versions,
            validate_current=sources.validate_credit_history)
        handoff = prepare_bank_credit_handoff(saved, context=prepared.context.model_copy(deep=True),
            reading=prepared.reading, basis_ref=selection.basis_ref.model_copy(deep=True),
            assessment_ref=prepared.action_input.assessment_ref.model_copy(deep=True),
            validate_current=sources.validate_credit_handoff)
        if handoff.get('kind') != 'prepared':
            raise TaskConflict('Original credit review did not establish the selected actual recorded assessment')
        return {**deepcopy(handoff), 'credit_identity': identity.as_dict()}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Credit lineage changed original Bank quotation context or input')


def _draw_approval_handoff(sources, prepared, selection):
    """Reuse the original approval relation without replaying approval or execution."""
    from integration.bank_draw_handoff import prepare_bank_draw_handoff

    _check_draw_approval_sources(sources)
    operation = prepared.action_input.operation_context
    if (prepared.context.contract_ref.id != 'BANK-A07' or operation.kind != 'initiate'
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Approval handoff requires the original explicit Bank execution initiation')
    identity = TaskIdentity(**selection.draw_identity.as_dict())
    try:
        saved = sources.draw_worker.read_completed(identity,
            current_context=prepared.context.model_copy(deep=True), reading=prepared.reading,
            execution_versions=identity.versions, validate_current=sources.validate_draw_history)
        handoff = prepare_bank_draw_handoff(saved, context=prepared.context.model_copy(deep=True),
            reading=prepared.reading, basis_ref=selection.basis_ref.model_copy(deep=True),
            approval_ref=operation.draw_approval_ref.model_copy(deep=True),
            arrangement_ref=prepared.action_input.arrangement_ref.model_copy(deep=True),
            validate_current=sources.validate_draw_approval)
        if handoff.get('kind') != 'prepared':
            raise TaskConflict('Selected original Bank decision cannot establish the actual execution approval')
        return {**deepcopy(handoff), 'draw_identity': identity.as_dict(),
            'approval_ref': operation.draw_approval_ref.model_dump(mode='json')}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Draw approval relation changed original Bank execution context or input')


def build_role_host(*, request, output_directory, offline, configuration):
    """Assemble one authorized invocation; execution stays in the original worker."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = BankRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Bank host requires an explicit matching bank action and model mode')
    feedback_settings = settings.feedback_inputs
    acceptance_settings = settings.owner_acceptance_inputs
    draw_request_settings = settings.owner_draw_request_inputs
    approval_settings = settings.draw_approval_inputs
    execution_receipt_settings = settings.execution_receipt_inputs
    application_settings = settings.owner_application_inputs
    intake_settings = settings.intake_inputs
    credit_settings = settings.credit_inputs
    if execution_receipt_settings is not None and (settings.action_id != 'BANK-A07'
            or request.action_input.get('operation_context', {}).get('kind') != 'existing'
            or approval_settings is not None
            or request.context.operation_id not in execution_receipt_settings.selections):
        raise ValueError('Execution receipts require explicit BANK-A07 existing-context selections')
    if credit_settings is not None and (settings.action_id != 'BANK-A04'
            or request.context.operation_id not in credit_settings.selections):
        raise ValueError('Credit inputs require explicit BANK-A04 selections for this operation')
    if intake_settings is not None and (settings.action_id != 'BANK-A03'
            or request.context.operation_id not in intake_settings.selections):
        raise ValueError('Intake inputs require explicit BANK-A03 selections for this operation')
    if application_settings is not None and (settings.action_id != 'BANK-A02'
            or request.context.operation_id not in application_settings.selections):
        raise ValueError('Owner application inputs require explicit BANK-A02 selections for this operation')
    if approval_settings is not None and (settings.action_id != 'BANK-A07'
            or request.context.operation_id not in approval_settings.selections):
        raise ValueError('Draw approval inputs require explicit BANK-A07 selections for this operation')
    if draw_request_settings is not None and (settings.action_id != 'BANK-A06'
            or request.context.operation_id not in draw_request_settings.selections):
        raise ValueError('Owner draw inputs require explicit BANK-A06 selections for this operation')
    if acceptance_settings is not None and (settings.action_id != 'BANK-A05'
            or request.context.operation_id not in acceptance_settings.selections):
        raise ValueError('Owner acceptance inputs require explicit BANK-A05 selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Bank feedback host requires formal mode and an explicit unique selection for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, BankRoleContractSources):
        raise ValueError('Bank source factory must return BankRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Bank sources change their declared version, run or source factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Bank feedback source binding must match its explicit host configuration')
        if acceptance_settings is not None and (sources.read_owner_financing is None
                or sources.validate_owner_acceptance_reception is None):
            raise ValueError('Configured acceptance requires original Owner journal and actual reception callbacks')
        if application_settings is not None and (sources.read_owner_financing is None
                or sources.validate_owner_application_reception is None):
            raise ValueError('Configured application requires original Owner journal and actual reception callbacks')
        if draw_request_settings is not None and sources.read_owner_payment is None:
            raise ValueError('Configured draw requires original Owner payment journal and actual reception callbacks')
        if approval_settings is not None:
            _check_draw_approval_sources(sources)
        if (execution_receipt_settings is None) != (sources.prepare_execution_reception is None):
            raise ValueError('Execution receipt reception must match its explicit host configuration')
        if intake_settings is not None:
            _check_intake_sources(sources)
        if credit_settings is not None:
            _check_credit_sources(sources)
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise ValueError('Bank host requires its original implemented processor and Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Bank worker execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline bank host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM bank host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.bank_' + module + '_actions'),
            'Bank' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.bank_' + module + '_results'),
            'Bank' + name + 'ResultWorker')
        if not issubclass(assembler_type, BankIntakeActionAssembler) or not issubclass(worker_type, BankIntakeResultWorker):
            raise ValueError('Bank routing must retain the original assembler and result worker')
        assembler = assembler_type(registry=sources.registry, organizations=sources.organizations,
            provider=sources.provider, macro_version=settings.macro_version,
            source_mode='fixture' if offline else 'formal', methods=sources.methods,
            policy_version=settings.policy_version, model_version=settings.model_version, model_host=model_host)
        worker = worker_type(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=settings.client_version, model_version=settings.model_version,
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        feedback_assembler = feedback_input = None
        if feedback_settings is not None:
            from integration.bank_feedback_inputs import BankFeedbackInputAssembler
            feedback_assembler = BankFeedbackInputAssembler(assembler=assembler, worker=worker,
                feedback=sources.feedback, version=feedback_settings.version, read_guard=sources.read_guard,
                validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        declared = {'schema_version': 'bank-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': assembler.source_mode,
            'assembler': module_factory_descriptor(assembler.build, settings.action_id),
            'worker': module_factory_descriptor(worker_type.execute, settings.action_id),
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        # One host identity may handle multiple requests; request identity lives
        # in the original invocation/task, not in this configuration record.
        key = 'bank_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Bank host configuration or code changed; explicit review required')
        approval_provenance = None
        execution_receipt_provenance = None
        execution_receipt_selection = (execution_receipt_settings.selections[request.context.operation_id].model_dump(mode='json')
            if execution_receipt_settings is not None else None)
        approval_selection = (approval_settings.selections[request.context.operation_id]
            if approval_settings is not None else None)
        application_provenance = None
        intake_provenance = None
        credit_provenance = None
        credit_selection = (credit_settings.selections[request.context.operation_id]
            if credit_settings is not None else None)
        intake_selection = (intake_settings.selections[request.context.operation_id]
            if intake_settings is not None else None)
        application_selection = (application_settings.selections[request.context.operation_id].model_dump(mode='json')
            if application_settings is not None else None)

        def prepare_handoff_sources(invocation):
            nonlocal approval_provenance, application_provenance, intake_provenance, credit_provenance
            nonlocal execution_receipt_provenance
            if execution_receipt_settings is not None:
                execution_receipt_provenance = sources.prepare_execution_reception(invocation, **execution_receipt_selection)
                if not isinstance(execution_receipt_provenance, dict):
                    raise ValueError('Bank execution reception must return explicit source provenance')
            if credit_settings is not None:
                credit_provenance = _credit_handoff(sources, invocation, credit_selection)
            if intake_settings is not None:
                intake_provenance = _intake_handoff(sources, invocation, intake_selection)
            if approval_settings is not None:
                approval_provenance = _draw_approval_handoff(sources, invocation, approval_selection)
            if application_settings is not None:
                from integration.owner_financing_bank_intake_handoff import read_received_owner_application
                application_provenance = read_received_owner_application(invocation, **application_selection,
                    read_owner_financing=sources.read_owner_financing,
                    validate_reception=sources.validate_owner_application_reception)
            return True

        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id],
                prepare_additional_sources=prepare_handoff_sources
                    if any(value is not None for value in (approval_settings, execution_receipt_settings, application_settings, intake_settings, credit_settings)) else None)
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                values = supplied.model_dump(mode='json')
                # A02 derives all application fields from the actual selected source.
                arguments = {'application_ref': values['application_ref']} if settings.action_id == 'BANK-A02' else values
                prepared = assembler.build(request.context, **arguments)
                if prepared.action_input.model_dump(mode='json') != values:
                    raise TaskConflict('Bank assembly changes the original supplied input')
                if any(value is not None for value in (approval_settings, execution_receipt_settings, application_settings, intake_settings, credit_settings)):
                    prepare_handoff_sources(prepared)
                    prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
        draw_request_provenance = None
        if draw_request_settings is not None:
            from integration.owner_payment_bank_draw_handoff import read_received_owner_draw_request
            draw_request_selection = draw_request_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                draw_request_provenance = read_received_owner_draw_request(prepared, **draw_request_selection,
                    read_owner_payment=sources.read_owner_payment,
                    validate_reception=sources.validate_owner_draw_request_reception)
        acceptance_provenance = None
        if acceptance_settings is not None:
            from integration.owner_financing_bank_acceptance_handoff import read_received_owner_financing_acceptance
            acceptance_selection = acceptance_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                acceptance_provenance = read_received_owner_financing_acceptance(prepared, **acceptance_selection,
                    read_owner_financing=sources.read_owner_financing,
                    validate_reception=sources.validate_owner_acceptance_reception)
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Bank source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Bank executor requires its original invocation once, without replay')
            executed = True
            if (_descriptors(sources) != callbacks
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or sources.registry is not worker.registry or prepared.runner.registry is not worker.registry
                    or prepared.runner.organizations is not sources.organizations
                    or assembler.provider is not sources.provider or worker.store is not sources.store
                    or assembler.methods is not sources.methods or sources.model_host is not model_host):
                raise TaskConflict('Bank original source components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if execution_receipt_settings is not None:
                    current_execution_receipts = sources.prepare_execution_reception(prepared, **execution_receipt_selection)
                    if (current_execution_receipts != execution_receipt_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original execution or actual native command/receipt reception changed before reconciliation')
                if intake_settings is not None:
                    current_intake = _intake_handoff(sources, prepared, intake_selection)
                    if (current_intake != intake_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original Bank intake or actual review task changed before credit execution')
                if credit_settings is not None:
                    current_credit = _credit_handoff(sources, prepared, credit_selection)
                    if (current_credit != credit_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original Bank review or actual recorded assessment changed before quotation')
                if application_settings is not None:
                    from integration.owner_financing_bank_intake_handoff import read_received_owner_application
                    current_application = read_received_owner_application(prepared, **application_selection,
                        read_owner_financing=sources.read_owner_financing,
                        validate_reception=sources.validate_owner_application_reception)
                    if (current_application != application_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original Owner draft or actual Bank registration changed before intake')
                if approval_settings is not None:
                    current_approval = _draw_approval_handoff(sources, prepared, approval_selection)
                    if (current_approval != approval_provenance
                            or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
                        raise TaskConflict('Original Bank approval or execution sources changed before execution')
                if draw_request_settings is not None:
                    current_draw_request = read_received_owner_draw_request(prepared, **draw_request_selection,
                        read_owner_payment=sources.read_owner_payment,
                        validate_reception=sources.validate_owner_draw_request_reception)
                    if current_draw_request != draw_request_provenance:
                        raise TaskConflict('Original Owner draw or actual received Bank request changed before execution')
                if acceptance_settings is not None:
                    current_acceptance = read_received_owner_financing_acceptance(prepared, **acceptance_selection,
                        read_owner_financing=sources.read_owner_financing,
                        validate_reception=sources.validate_owner_acceptance_reception)
                    if current_acceptance != acceptance_provenance:
                        raise TaskConflict('Original Owner choice or actual independent acceptance changed before execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is None:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                else:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Bank feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Bank execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Bank source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record['source_reading_sha256'], 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'owner_acceptance_input': deepcopy(acceptance_provenance),
                    'owner_draw_request_input': deepcopy(draw_request_provenance),
                    'draw_approval_input': deepcopy(approval_provenance),
                    'execution_receipt_input': deepcopy(execution_receipt_provenance),
                    'owner_application_input': deepcopy(application_provenance),
                    'intake_input': deepcopy(intake_provenance),
                    'credit_input': deepcopy(credit_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='bank-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'owner_acceptance_input': deepcopy(acceptance_provenance),
                'owner_draw_request_input': deepcopy(draw_request_provenance),
                'draw_approval_input': deepcopy(approval_provenance),
                'execution_receipt_input': deepcopy(execution_receipt_provenance),
                'owner_application_input': deepcopy(application_provenance),
                'intake_input': deepcopy(intake_provenance), 'credit_input': deepcopy(credit_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
