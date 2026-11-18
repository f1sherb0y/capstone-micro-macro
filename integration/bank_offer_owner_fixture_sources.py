"""Explicit offline Owner reception of a quotation from the original Bank journal."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.bank_quote_actions import BankQuoteActionAssembler
from integration.bank_quote_results import BankQuoteResultWorker
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.bank_quote_objects import QuoteReservationView
from src.actions.contracts.common import Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.owner_financing_objects import FinancingOfferView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class BankQuoteHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: BankFixtureSourceSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: Literal['offline-fixture-no-model.v1']

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredOfferReservation(StrictRecord):
    reservation_id: TextId
    offer_ref: ref_type('FinanceOffer')
    policy_ref: ref_type('ReservationPolicy')
    principal: Money
    expiry_ref: ref_type('TimeWindow')
    registered_at: TimePoint
    as_of: TimePoint
    state: Literal['reserved', 'converted', 'released', 'expired']


class DeclaredBankOfferRegistration(StrictRecord):
    """Independent offer, reservation and sharing declaration, supplied by receiver."""
    schema_version: Literal['bank-offer-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    application: FinanceApplicationView
    offer: FinancingOfferView
    reservation_policy: QuoteReservationView
    reservation: DeclaredOfferReservation | None
    receipt_ref: ref_type('FinanceOfferReceipt')
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
    current_state: Literal['offered', 'withdrawn', 'expired', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerBankOfferFixtureSettings(OwnerFixtureSourceSettings):
    bank_history: BankQuoteHistorySettings
    registration: DeclaredBankOfferRegistration


class _OfferReception:
    VERSION = 'configured-owner-bank-offer-fixture-sources.v1'
    ACTION_ID = 'BANK-A04'
    ASSEMBLER = BankQuoteActionAssembler
    WORKER = BankQuoteResultWorker
    CHOICES = frozenset({'offer', 'conditional_offer'})

    def __init__(self, request, settings, owner, bank):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.owner, self.bank = owner, bank
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.bank_history
        self._bank_input = bank.registry.get(self.ACTION_ID).contract.validate_input(history.request.action_input)
        self.worker = self.WORKER(store=bank.store, snapshots=InvocationSnapshotStore(bank.store),
            registry=bank.registry, client_version=history.client_version, model_version=history.model_version,
            validate_invocation=bank.validators.invocation, validate_wait=bank.validators.wait,
            validate_recovery=bank.validators.recovery)
        self.assembler = self.ASSEMBLER(registry=bank.registry, organizations=bank.organizations,
            provider=bank.provider, macro_version=history.macro_version, source_mode='fixture', methods=bank.methods,
            policy_version=history.policy_version, model_version=history.model_version)

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256):
            raise TaskConflict('Offer reception changed its configured current Owner or registration declaration')
        self.owner.evidence()
        self.bank.evidence()

    def _validate_history(self, saved, reading):
        history, registration = self.settings.bank_history, self.settings.registration
        shared = [ref.key() for ref in registration.shared_source_refs]
        if (saved.identity.as_dict() != history.identity.as_dict()
                or saved.current_context != history.request.context or saved.action_input != self._bank_input
                or saved.record_sha256 != registration.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != registration.source_result_sha256
                or saved.source_reading_sha256 != registration.source_reading_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice not in self.CHOICES
                or registration.sharing_authorized is not True or len(set(shared)) != len(shared)
                or set(shared) != {Reference.model_validate(row['ref']).key() for row in saved.source_reading}):
            raise TaskConflict('Offer sharing substitutes selected Bank history, native lineage or disclosed sources')
        for row in saved.source_reading:
            current = reading.resolve(Reference.model_validate(row['ref']))
            if current.model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original quotation is no longer supplied by current authorized Bank sources')
        reading.recheck()
        return True

    def read_bank_quote(self, *, context, source_task_sha256):
        self._check(context)
        history = self.settings.bank_history
        if source_task_sha256 != history.identity.key:
            raise TaskConflict('Owner offer reader requires the explicitly selected original Bank task')
        # The Bank worker retains its own current Bank authorization boundary.
        with self.owner.read_guard(context), self.bank.read_guard(history.request.context):
            prepared = self.assembler.build(history.request.context, **self._bank_input.model_dump(mode='json'))
            reading = prepared.reading
            try:
                versions = prepared_action_execution_versions(prepared,
                    client_version=history.client_version, model_version=history.model_version)
                return self.worker.read_completed(history.identity, current_context=history.request.context,
                    reading=reading, execution_versions=versions,
                    validate_current=lambda saved: self._validate_history(saved, reading))
            finally:
                reading.recheck()
                self._check(context)

    def validate_reception(self, *, saved, receipt, offer, application, context):
        self._check(context)
        registration, history = self.settings.registration, self.settings.bank_history
        with self.owner.read_guard(context), self.bank.read_guard(history.request.context):
            original = self.read_bank_quote(context=context, source_task_sha256=history.identity.key)
            policy = registration.reservation_policy
            originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in original.source_reading}
            if (saved != original or registration.current_state != 'offered' or offer.status != 'offered'
                    or offer != registration.offer or application != registration.application
                    or registration.run_id != context.run_id
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != receipt.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != offer.scope_ref or registration.scope != receipt.scope
                    or receipt.ref != registration.receipt_ref or receipt.native_evidence_ref != registration.native_evidence_ref
                    or receipt.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or receipt.received_at != registration.received_at or receipt.available_at != registration.available_at
                    or receipt.effective_window != registration.effective_window
                    or not registration.effective_window.contains(context.business_time)
                    or policy.ref != receipt.reservation_policy_ref
                    or policy.model_dump(mode='json') != originals.get(policy.ref.key())
                    or policy.application_ref != application.ref or policy.product_ref != offer.terms.product_ref
                    or policy.borrower_id != application.borrower_id or policy.lender_id != offer.lender_id
                    or not policy.effective_window.contains(context.business_time)):
                raise TaskConflict('Declared offer registration changes current terms, reservation policy or sharing permission')
            reservation = registration.reservation
            if policy.reserves_capacity:
                if (reservation is None or reservation.state != 'reserved' or reservation.offer_ref != offer.ref
                        or reservation.policy_ref != policy.ref or reservation.principal != offer.terms.principal_limit
                        or reservation.expiry_ref != policy.expiry_ref or reservation.as_of != context.business_time
                        or reservation.registered_at.clock_ref != context.business_time.clock_ref
                        or not offer.issued_at.offset <= reservation.registered_at.offset <= context.business_time.offset):
                    raise TaskConflict('Reserved offer requires its explicit current independent native reservation')
            elif reservation is not None:
                raise TaskConflict('Nonreserving offer cannot assert a native capacity reservation')
            expiry_projection = history.source_settings.source_projection['objects']
            windows = [row['value'] for row in expiry_projection
                if Reference.model_validate(row['ref']).key() == policy.expiry_ref.key()]
            if len(windows) != 1 or not TimeWindow.model_validate(windows[0]).contains(context.business_time):
                raise TaskConflict('Received quote reservation policy has expired at the current Owner read point')
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.owner.evidence()), 'schema_version': self.VERSION,
            'bank_offer': {'source_task_sha256': self.settings.bank_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'source_factory': 'integration.bank_role_contract_fixture_sources:build_sources',
                'bank_sources': deepcopy(self.bank.evidence()),
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Explicit synthetic offer/reservation/sharing declarations; no acceptance or core effect.']}}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.bank.close()
            finally:
                self.owner.close()


def build_sources(*, request, output_directory, offline, settings):
    """Bind only supplied native offer and original Bank history; never execute quotation."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerBankOfferFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.bank_history, settings.registration
    bank_path, owner_path = Path(history.source_settings.journal_path).resolve(), Path(settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'OWN-A05' or settings.action_id != 'OWN-A05'
            or history.request.context.contract_ref.id != 'BANK-A04' or history.source_settings.action_id != 'BANK-A04'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.identity.role != 'Bank' or history.identity.action_id != 'BANK-A04'
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.run_id != request.context.run_id or registration.current_state != 'offered'
            or registration.sharing_authorized is not True
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.offer.lender_id != history.identity.organization_id
            or registration.recipient_organization_id != settings.source_projection['organization_id']
            or bank_path == owner_path or not bank_path.is_file()):
        raise ValueError('Offer fixture requires existing separate Bank history and explicit same-run current Owner reception')
    owner = bank = None
    try:
        owner_settings = OwnerFixtureSourceSettings.model_validate(
            settings.model_dump(mode='json', exclude={'bank_history', 'registration'}))
        owner = build_owner_sources(request=request, output_directory=output_directory, offline=offline, settings=owner_settings)
        bank = build_bank_sources(request=history.request, output_directory=output_directory, offline=offline,
            settings=history.source_settings)
        binding = _OfferReception(request, settings, owner, bank)
        return replace(owner, version=binding.VERSION, read_bank_quote=binding.read_bank_quote,
            validate_financing_offer_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if bank is not None:
                bank.close()
        finally:
            if owner is not None:
                owner.close()
        raise
