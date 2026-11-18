"""Offline tender intake from an existing Owner journal and independent registration."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_bid_fixture_sources import (
    ContractorBidFixtureSettings, build_sources as build_contractor_sources,
)
from integration.owner_role_contract_fixture_sources import (
    OwnerFixtureSourceSettings, build_sources as build_owner_sources,
)
from integration.owner_tender_actions import OwnerTenderActionAssembler
from integration.owner_tender_results import OwnerTenderResultWorker
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import (
    Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type,
)
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerTenderHistorySettings(StrictRecord):
    """Current Owner authority and the explicitly selected original publication."""
    request: RoleContractInvocation
    source_settings: OwnerFixtureSourceSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredTenderDeliverableMapping(StrictRecord):
    submission_ref: ref_type('DeliverableSubmission')
    deliverable_ref: ref_type('ReleasedDeliverable')


class DeclaredOwnerTenderRegistration(StrictRecord):
    """Supplied synthetic native mapping; never inferred from a publication draft."""
    schema_version: Literal['owner-tender-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    package: ContractorBidPackageView
    procedure_ref: ref_type('ProcurementProcedure')
    evaluation_profile_ref: ref_type('TenderEvaluationProfile')
    requirement_refs: list[ref_type('Requirement')]
    deliverable_mappings: list[DeclaredTenderDeliverableMapping]
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    received_at: TimePoint
    effective_window: TimeWindow
    sharing_authorized: bool
    shared_source_refs: list[Reference]
    current_state: Literal['received', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ContractorOwnerTenderFixtureSettings(ContractorBidFixtureSettings):
    owner_history: OwnerTenderHistorySettings
    registration: DeclaredOwnerTenderRegistration


class _OwnerTenderHistoryBinding:
    ACTION_ID = 'OWN-A09'
    ASSEMBLER = OwnerTenderActionAssembler
    WORKER = OwnerTenderResultWorker
    EXPECTED_CHOICE = 'publish_package'
    AUTHORIZATION_FLAG = 'sharing_authorized'

    def __init__(self, request, settings, recipient, owner):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.recipient, self.owner = recipient, owner
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
            raise TaskConflict('Tender reception changed its recipient or independent declaration')
        self.recipient.evidence()
        self.owner.evidence()

    def _validate_history(self, saved, reading):
        history, registration = self.settings.owner_history, self.settings.registration
        if (saved.identity.as_dict() != history.identity.as_dict()
                or saved.current_context != history.request.context or saved.action_input != self._owner_input
                or saved.record_sha256 != registration.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != registration.source_result_sha256
                or saved.source_reading_sha256 != registration.source_reading_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != self.EXPECTED_CHOICE):
            raise TaskConflict('Tender reader substitutes the selected original completed Owner decision')
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        shared = [ref.key() for ref in registration.shared_source_refs]
        if (getattr(registration, self.AUTHORIZATION_FLAG) is not True or len(set(shared)) != len(shared)
                or not set(shared) <= originals):
            raise TaskConflict('Tender registration lacks an explicit authorized subset of original sources')
        # Full original source checks occur only inside Owner authority. A
        # Contractor declaration never grants access to Owner budget sources.
        for row in saved.source_reading:
            current = reading.resolve(Reference.model_validate(row['ref']))
            if current.model_dump(mode='json') != row['projection']:
                raise TaskConflict('Owner tender history differs from current authorized original sources')
        reading.recheck()
        return True

    def read_owner_tender(self, *, context, source_task_sha256):
        self._check(context)
        history = self.settings.owner_history
        if source_task_sha256 != history.identity.key:
            raise TaskConflict('Tender reader requires its explicitly selected Owner decision task')
        with self.recipient.read_guard(context), self.owner.read_guard(history.request.context):
            prepared = self.assembler.build(history.request.context, **self._owner_input.model_dump(mode='json'))
            try:
                versions = prepared_action_execution_versions(prepared,
                    client_version=history.client_version, model_version=history.model_version)
                return self.worker.read_completed(history.identity,
                    current_context=history.request.context, reading=prepared.reading,
                    execution_versions=versions,
                    validate_current=lambda saved: self._validate_history(saved, prepared.reading))
            finally:
                prepared.reading.recheck()
                self._check(context)

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.owner.close()
            finally:
                self.recipient.close()


class _TenderReception(_OwnerTenderHistoryBinding):
    VERSION = 'configured-contractor-owner-tender-fixture-sources.v1'

    def validate_reception(self, saved, package, evidence, context):
        self._check(context)
        registration = self.settings.registration
        original = self.read_owner_tender(context=context,
            source_task_sha256=self.settings.owner_history.identity.key)
        draft = original.result.payload.package
        mappings = registration.deliverable_mappings
        submissions = [row.submission_ref for row in mappings]
        deliverables = [row.deliverable_ref for row in mappings]
        public_refs = ([draft.procedure_ref, draft.evaluation_profile_ref, draft.submission_window_ref]
            + draft.technical_submission_refs + draft.requirement_refs
            + ([draft.quantity_basis_ref] if draft.quantity_basis_ref is not None else [])) if draft is not None else []
        if (saved != original or draft is None or registration.current_state != 'received'
                or package != registration.package or package.status != 'open'
                or registration.source_identity.as_dict() != saved.identity.as_dict()
                or registration.run_id != context.run_id or registration.scope != context.scope
                or registration.scope != package.scope or package.scope != draft.scope_ref
                or registration.recipient_organization_id != self.settings.source_projection['organization_id']
                or registration.recipient_actor_id != context.actor_id
                or registration.recipient_function_ref != context.function_ref
                or registration.recipient_authorization_refs != context.authorization_refs
                or registration.native_evidence_ref != evidence.ref
                or evidence.ref not in package.evidence_refs or evidence.basis_kind != 'observed'
                or evidence.source_kind != 'synthetic'
                or registration.procedure_ref != draft.procedure_ref
                or registration.evaluation_profile_ref != draft.evaluation_profile_ref
                or registration.requirement_refs != draft.requirement_refs
                or package.submission_window_ref != draft.submission_window_ref
                or package.quantity_refs != ([draft.quantity_basis_ref] if draft.quantity_basis_ref is not None else [])
                or submissions != draft.technical_submission_refs or deliverables != package.deliverable_refs
                or len({ref.key() for ref in submissions}) != len(submissions)
                or len({ref.key() for ref in deliverables}) != len(deliverables)
                or {ref.key() for ref in public_refs} != {ref.key() for ref in registration.shared_source_refs}
                or registration.recipient_organization_id not in package.recipient_organization_ids
                or saved.result.payload.bidder_ids and set(package.recipient_organization_ids) != set(saved.result.payload.bidder_ids)
                or registration.received_at.clock_ref != context.business_time.clock_ref
                or not saved.context.business_time.offset <= registration.received_at.offset <= package.available_at.offset
                or package.available_at.offset > context.business_time.offset
                or not registration.effective_window.contains(context.business_time)):
            raise TaskConflict('Independent tender registration changes publication mapping, recipient, sharing or chronology')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.recipient.evidence()), 'schema_version': self.VERSION,
            'owner_tender': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Independent synthetic registration; no native publication, delivery or formal receipt.']}}


def build_sources(*, request, output_directory, offline, settings):
    """Read an existing selected publication; create no result, package or receipt."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = ContractorOwnerTenderFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.owner_history, settings.registration
    owner_path = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or request.context.contract_ref.id != 'CONTRACTOR-A02' or settings.action_id != 'CONTRACTOR-A02'
            or history.request.context.contract_ref.id != 'OWN-A09' or history.source_settings.action_id != 'OWN-A09'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A09'
            or history.identity.purpose != 'action'
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.run_id != request.context.run_id or registration.current_state != 'received'
            or registration.sharing_authorized is not True
            or registration.package.ref.model_dump(mode='json') not in
                [row.get('ref') for row in settings.source_projection.get('objects', [])]
            or owner_path == Path(settings.journal_path).resolve() or not owner_path.is_file()):
        raise ValueError('Tender fixture requires existing separate Owner publication and same-run declared reception')
    contractor = owner = None
    try:
        contractor_settings = ContractorBidFixtureSettings.model_validate(
            settings.model_dump(mode='json', exclude={'owner_history', 'registration'}))
        contractor = build_contractor_sources(request=request, output_directory=output_directory,
            offline=offline, settings=contractor_settings)
        owner = build_owner_sources(request=history.request, output_directory=output_directory,
            offline=offline, settings=history.source_settings)
        binding = _TenderReception(request, settings, contractor, owner)
        return replace(contractor, version=binding.VERSION, read_owner_tender=binding.read_owner_tender,
            validate_received_tender=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if owner is not None:
                owner.close()
        finally:
            if contractor is not None:
                contractor.close()
        raise
