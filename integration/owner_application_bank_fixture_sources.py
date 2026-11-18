"""Explicit offline Bank reception backed by the original authorized Owner journal."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.owner_financing_actions import OwnerFinancingActionAssembler
from integration.owner_financing_results import OwnerFinancingResultWorker
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerApplicationHistorySettings(StrictRecord):
    """Current independent Owner read context, original input and selected task."""
    request: RoleContractInvocation
    source_settings: OwnerFixtureSourceSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: Literal['offline-fixture-no-model.v1']

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredOwnerApplicationRegistration(StrictRecord):
    """Independent receiver declaration; no record is generated from a local result."""
    schema_version: Literal['owner-application-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    application: FinanceApplicationView
    receipt_ref: ref_type('OwnerFinanceApplicationReceipt')
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    sharing_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    current_state: Literal['submitted', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankOwnerApplicationFixtureSettings(BankFixtureSourceSettings):
    owner_history: OwnerApplicationHistorySettings
    registration: DeclaredOwnerApplicationRegistration


class _ApplicationReception:
    VERSION = 'configured-bank-owner-application-fixture-sources.v1'
    ACTION_ID = 'OWN-A05'
    ASSEMBLER = OwnerFinancingActionAssembler
    WORKER = OwnerFinancingResultWorker
    EXPECTED_CHOICE = 'apply'

    def __init__(self, request, settings, bank, owner):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.bank, self.owner = bank, owner
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.owner_history
        self._owner_input = owner.registry.get(self.ACTION_ID).contract.validate_input(history.request.action_input)
        self.worker = self.WORKER(store=owner.store,
            snapshots=InvocationSnapshotStore(owner.store), registry=owner.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=owner.validators.invocation, validate_wait=owner.validators.wait,
            validate_recovery=owner.validators.recovery)
        self.assembler = self.ASSEMBLER(registry=owner.registry,
            organizations=owner.organizations, provider=owner.provider,
            macro_version=history.macro_version, source_mode='fixture', methods=owner.methods,
            policy_version=history.policy_version, model_version=history.model_version)

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256):
            raise TaskConflict('Application reception changed its configured current recipient or declaration')
        # Check both current source/authority boundaries, without granting Bank
        # permission to invoke the Owner history worker under a Bank context.
        self.bank.evidence()
        self.owner.evidence()

    def _validate_history(self, saved, reading):
        history, registration = self.settings.owner_history, self.settings.registration
        shared = [ref.key() for ref in registration.shared_source_refs]
        if (saved.identity.as_dict() != history.identity.as_dict()
                or saved.current_context != history.request.context or saved.action_input != self._owner_input
                or saved.record_sha256 != registration.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != registration.source_result_sha256
                or saved.source_reading_sha256 != registration.source_reading_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != self.EXPECTED_CHOICE
                or registration.sharing_authorized is not True or len(set(shared)) != len(shared)
                or set(shared) != {Reference.model_validate(row['ref']).key() for row in saved.source_reading}):
            raise TaskConflict('Application sharing substitutes selected Owner history, native lineage or disclosed sources')
        for row in saved.source_reading:
            current = reading.resolve(Reference.model_validate(row['ref']))
            if current.model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original Owner history is no longer supplied by its current authorized source')
        reading.recheck()
        return True

    def read_owner_financing(self, *, context, source_task_sha256):
        self._check(context)
        history = self.settings.owner_history
        if source_task_sha256 != history.identity.key:
            raise TaskConflict('Bank application reader requires the explicitly selected Owner task')
        with self.bank.read_guard(context), self.owner.read_guard(history.request.context):
            prepared = self.assembler.build(history.request.context, **self._owner_input.model_dump(mode='json'))
            reading = prepared.reading
            try:
                versions = prepared_action_execution_versions(prepared,
                    client_version=history.client_version, model_version=history.model_version)
                return self.worker.read_completed(history.identity,
                    current_context=history.request.context, reading=reading,
                    execution_versions=versions,
                    validate_current=lambda saved: self._validate_history(saved, reading))
            finally:
                reading.recheck()
                self._check(context)

    def validate_reception(self, *, saved, receipt, application, context):
        self._check(context)
        registration = self.settings.registration
        history = self.settings.owner_history
        with self.bank.read_guard(context), self.owner.read_guard(history.request.context):
            # Re-read the original durable record under Owner authority. The
            # handoff separately checks actual Bank-visible application,
            # applicant grants, observed native evidence and chronology.
            original = self.read_owner_financing(context=context, source_task_sha256=history.identity.key)
            if (saved != original or registration.current_state != 'submitted'
                    or application.status != 'submitted' or application != registration.application
                    or registration.run_id != context.run_id
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != receipt.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != application.scope_ref or registration.scope != receipt.scope
                    or receipt.ref != registration.receipt_ref
                    or receipt.native_evidence_ref != registration.native_evidence_ref
                    or receipt.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or receipt.received_at != registration.received_at or receipt.available_at != registration.available_at
                    or receipt.effective_window != registration.effective_window
                    or not registration.effective_window.contains(context.business_time)):
                raise TaskConflict('Declared native registration changes current reception, full disclosures or sharing permission')
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.bank.evidence()), 'schema_version': self.VERSION,
            'owner_application': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'source_factory': 'integration.owner_role_contract_fixture_sources:build_sources',
                'owner_sources': deepcopy(self.owner.evidence()),
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Explicit synthetic registration and sharing declaration; no native effect or journal replay.']}}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.owner.close()
            finally:
                self.bank.close()


def build_sources(*, request, output_directory, offline, settings):
    """Bind original selected Owner history and independently declared Bank registration."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankOwnerApplicationFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.owner_history, settings.registration
    owner_path = Path(history.source_settings.journal_path).resolve()
    bank_path = Path(settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'BANK-A02' or settings.action_id != 'BANK-A02'
            or history.request.context.contract_ref.id != 'OWN-A05' or history.source_settings.action_id != 'OWN-A05'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A05'
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.run_id != request.context.run_id or registration.current_state != 'submitted'
            or registration.sharing_authorized is not True
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.application.borrower_id != history.identity.organization_id
            or registration.recipient_organization_id != settings.source_projection['organization_id']
            or owner_path == bank_path or not owner_path.is_file()):
        raise ValueError('Application fixture requires existing separate Owner history and explicit same-run Bank reception')
    bank = owner = None
    try:
        bank_settings = BankFixtureSourceSettings.model_validate(
            settings.model_dump(mode='json', exclude={'owner_history', 'registration'}))
        bank = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
            settings=bank_settings)
        owner = build_owner_sources(request=history.request, output_directory=output_directory, offline=offline,
            settings=history.source_settings)
        binding = _ApplicationReception(request, settings, bank, owner)
        return replace(bank, version=binding.VERSION, read_owner_financing=binding.read_owner_financing,
            validate_owner_application_reception=binding.validate_reception,
            evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if owner is not None:
                owner.close()
        finally:
            if bank is not None:
                bank.close()
        raise
