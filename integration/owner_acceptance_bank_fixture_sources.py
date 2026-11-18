"""Explicit Owner acceptance registration received by the original Bank arrangement host."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.bank_offer_owner_fixture_sources import DeclaredOfferReservation
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.owner_application_bank_fixture_sources import OwnerApplicationHistorySettings, _ApplicationReception
from integration.owner_role_contract_fixture_sources import build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_arrangement_objects import (
    ArrangementAcceptanceView, ArrangementBorrowerDecisionView, ArrangementOfferView,
)
from src.actions.contracts.bank_quote_objects import QuoteReservationView
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredOwnerAcceptanceRegistration(StrictRecord):
    schema_version: Literal['owner-acceptance-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    offer: ArrangementOfferView
    acceptance: ArrangementAcceptanceView
    recorded_decision: ArrangementBorrowerDecisionView
    reservation_policy: QuoteReservationView
    reservation: DeclaredOfferReservation | None
    receipt_ref: ref_type('FinancingAcceptanceReceipt')
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
    current_state: Literal['accepted', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankOwnerAcceptanceFixtureSettings(BankFixtureSourceSettings):
    owner_history: OwnerApplicationHistorySettings
    registration: DeclaredOwnerAcceptanceRegistration


class _AcceptanceReception(_ApplicationReception):
    """Reuse original current Owner history authorization, exact versions and close."""
    VERSION = 'configured-bank-owner-acceptance-fixture-sources.v1'
    EXPECTED_CHOICE = 'accept_offer'

    def validate_reception(self, *, saved, receipt, offer, acceptance, recorded_decision, context):
        self._check(context)
        registration, history = self.settings.registration, self.settings.owner_history
        with self.bank.read_guard(context), self.owner.read_guard(history.request.context):
            original = self.read_owner_financing(context=context, source_task_sha256=history.identity.key)
            if (saved != original or registration.current_state != 'accepted'
                    or offer != registration.offer or acceptance != registration.acceptance
                    or recorded_decision != registration.recorded_decision
                    or acceptance.decision != 'accept' or recorded_decision.decision != 'accept'
                    or registration.run_id != context.run_id
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != receipt.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != offer.scope_ref or registration.scope != receipt.scope
                    or receipt.ref != registration.receipt_ref
                    or receipt.native_evidence_ref != registration.native_evidence_ref
                    or receipt.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or receipt.received_at != registration.received_at or receipt.available_at != registration.available_at
                    or receipt.effective_window != registration.effective_window
                    or not registration.effective_window.contains(context.business_time)):
                raise TaskConflict('Declared acceptance changes original independent Owner decision or current Bank reception')
            policy = registration.reservation_policy
            rows = {Reference.model_validate(row['ref']).key(): row['value']
                for row in self.settings.source_projection['objects']}
            if (rows.get(policy.ref.key()) != policy.model_dump(mode='json')
                    or policy.ref != offer.reservation_policy_ref or policy.application_ref != offer.application_ref
                    or policy.product_ref != offer.terms.product_ref or policy.borrower_id != offer.terms.borrower_id
                    or policy.lender_id != offer.lender_id):
                raise TaskConflict('Actual Owner acceptance lacks the exact current Bank reservation policy')
            reservation = registration.reservation
            if policy.reserves_capacity:
                if (reservation is None or reservation.offer_ref != offer.ref
                        or reservation.policy_ref != policy.ref or reservation.principal != offer.terms.principal_limit
                        or reservation.expiry_ref != policy.expiry_ref or reservation.as_of != context.business_time
                        or reservation.registered_at.clock_ref != context.business_time.clock_ref
                        or not offer.issued_at.offset <= reservation.registered_at.offset <= acceptance.accepted_at.offset):
                    raise TaskConflict('Accepted reserved offer requires its independent current native reservation')
            elif reservation is not None:
                raise TaskConflict('Nonreserving accepted offer cannot assert a native capacity reservation')
            expiry = rows.get(policy.expiry_ref.key())
            if expiry is None or TimeWindow.model_validate(expiry).start.clock_ref != context.business_time.clock_ref:
                raise TaskConflict('Original accepted offer lacks its exact reservation expiry window')
            # Original A05 owns expiry precedence, requote/decline and existing
            # commitment evaluation. Preserve actual reservation terminal states.
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.bank.evidence()), 'schema_version': self.VERSION,
            'owner_acceptance': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'owner_sources': deepcopy(self.owner.evidence()),
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Explicit synthetic independent Owner acceptance; no Bank confirmation or financing effect.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankOwnerAcceptanceFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.owner_history, settings.registration
    owner_path, bank_path = Path(history.source_settings.journal_path).resolve(), Path(settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'BANK-A05' or settings.action_id != 'BANK-A05'
            or history.request.context.contract_ref.id != 'OWN-A05' or history.source_settings.action_id != 'OWN-A05'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A05'
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.run_id != request.context.run_id or registration.current_state != 'accepted'
            or registration.sharing_authorized is not True
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.offer.terms.borrower_id != history.identity.organization_id
            or registration.recipient_organization_id != settings.source_projection['organization_id']
            or owner_path == bank_path or not owner_path.is_file()):
        raise ValueError('Acceptance fixture requires existing separate Owner history and explicit same-run Bank reception')
    bank = owner = None
    try:
        bank_settings = BankFixtureSourceSettings.model_validate(
            settings.model_dump(mode='json', exclude={'owner_history', 'registration'}))
        bank = build_bank_sources(request=request, output_directory=output_directory, offline=offline, settings=bank_settings)
        owner = build_owner_sources(request=history.request, output_directory=output_directory, offline=offline,
            settings=history.source_settings)
        binding = _AcceptanceReception(request, settings, bank, owner)
        return replace(bank, version=binding.VERSION, read_owner_financing=binding.read_owner_financing,
            validate_owner_acceptance_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if owner is not None:
                owner.close()
        finally:
            if bank is not None:
                bank.close()
        raise
