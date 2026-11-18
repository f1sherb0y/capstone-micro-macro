"""Explicit signed native facility received by Owner from original Bank confirmation."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.bank_arrangement_actions import BankArrangementActionAssembler
from integration.bank_arrangement_results import BankArrangementResultWorker
from integration.bank_offer_owner_fixture_sources import BankQuoteHistorySettings, _OfferReception
from integration.bank_role_contract_fixture_sources import build_sources as build_bank_sources
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_arrangement_objects import ArrangementOfferView
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.owner_financing_objects import FinancingAcceptanceView
from src.actions.contracts.owner_payment_objects import OwnerPaymentArrangementView, OwnerPaymentDrawConditionView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ArrangementConditionMapping(StrictRecord):
    native_condition_ref: ref_type('Requirement')
    native_projection: dict
    stage: Literal['arrangement_effective', 'per_draw']
    owner_condition: OwnerPaymentDrawConditionView | None


class DeclaredBankArrangementRegistration(StrictRecord):
    schema_version: Literal['bank-arrangement-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    offer: ArrangementOfferView
    arrangement: OwnerPaymentArrangementView
    borrower_acceptance: FinancingAcceptanceView
    lender_confirmation: FinancingAcceptanceView
    condition_mappings: list[ArrangementConditionMapping]
    native_facility: dict
    receipt_ref: ref_type('FinanceArrangementReceipt')
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    signed_at: TimePoint
    received_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow
    sharing_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    current_state: Literal['registered', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerBankArrangementFixtureSettings(OwnerFixtureSourceSettings):
    bank_history: BankQuoteHistorySettings
    registration: DeclaredBankArrangementRegistration


class _ArrangementReception(_OfferReception):
    VERSION = 'configured-owner-bank-arrangement-fixture-sources.v1'
    ACTION_ID = 'BANK-A05'
    ASSEMBLER = BankArrangementActionAssembler
    WORKER = BankArrangementResultWorker
    CHOICES = frozenset({'confirm'})

    def validate_reception(self, *, saved, receipt, arrangement, offer, borrower_acceptance, lender_confirmation, context):
        self._check(context)
        registration, history = self.settings.registration, self.settings.bank_history
        with self.owner.read_guard(context), self.bank.read_guard(history.request.context):
            original = self.read_bank_quote(context=context, source_task_sha256=history.identity.key)
            if (saved != original or registration.current_state != 'registered'
                    or arrangement != registration.arrangement or offer != registration.offer
                    or borrower_acceptance != registration.borrower_acceptance
                    or lender_confirmation != registration.lender_confirmation
                    or registration.run_id != context.run_id
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != receipt.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != arrangement.scope_ref or registration.scope != receipt.scope
                    or receipt.ref != registration.receipt_ref or receipt.native_evidence_ref != registration.native_evidence_ref
                    or receipt.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or receipt.signed_at != registration.signed_at or receipt.received_at != registration.received_at
                    or receipt.available_at != registration.available_at or receipt.effective_window != registration.effective_window
                    or not registration.effective_window.contains(context.business_time)):
                raise TaskConflict('Signed facility declaration changes original confirmation, parties or current Owner reception')
            conditions = [row.model_dump(mode='json') for row in saved.result.payload.conditions]
            originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
            owner_rows = {Reference.model_validate(row['ref']).key(): row['value']
                for row in self.settings.source_projection['objects']}
            mappings = registration.condition_mappings
            confirmed = {Reference.model_validate(row['requirement_ref']).key(): row for row in conditions}
            if (len({row.native_condition_ref.key() for row in mappings}) != len(mappings)
                    or {row.native_condition_ref.key() for row in mappings}
                        != set(confirmed)):
                raise TaskConflict('Native facility omits or repeats original confirmed formation/draw conditions')
            draw_refs = []
            for mapping in mappings:
                native = mapping.native_projection
                if (originals.get(mapping.native_condition_ref.key()) != native
                        or native.get('stage') != mapping.stage):
                    raise TaskConflict('Facility condition mapping substitutes original Bank condition stage or content')
                if mapping.stage == 'arrangement_effective':
                    if mapping.owner_condition is not None:
                        raise TaskConflict('Formation condition cannot silently become a per-draw requirement')
                else:
                    condition = mapping.owner_condition
                    if (condition is None or condition.arrangement_ref != arrangement.ref
                            or condition.borrower_id != arrangement.borrower_id
                            or condition.draw_authorization_ref not in arrangement.allowed_draw_authorization_refs
                            or owner_rows.get(condition.ref.key()) != condition.model_dump(mode='json')):
                        raise TaskConflict('Per-draw condition lacks its exact independently supplied Owner mapping')
                    outcome = confirmed[mapping.native_condition_ref.key()]['outcome']
                    if condition.satisfied.state == 'known':
                        expected_outcome = 'satisfied' if condition.satisfied.value else 'unsatisfied'
                        if outcome != expected_outcome:
                            raise TaskConflict('Owner draw condition changes original native verification outcome')
                    elif outcome in {'satisfied', 'unsatisfied'}:
                        raise TaskConflict('Owner condition discards the original known native verification')
                    verifier = native.get('verification')
                    if (verifier is None and condition.satisfied.state == 'known'
                            or verifier is not None and any(condition.model_dump(mode='json')[target] != verifier[source]
                                for source, target in [('organization_id', 'verifier_organization_id'),
                                    ('actor_id', 'verifier_actor_id'), ('function_ref', 'verifier_function_ref'),
                                    ('authority_ref', 'verifier_authority_ref'), ('action_id', 'verifier_action_id'),
                                    ('verified_at', 'verified_at')])
                            or condition.evidence_ref.model_dump(mode='json') not in native.get('evidence_refs', [])):
                        raise TaskConflict('Owner draw condition substitutes native verifier authority or evidence')
                    # Retain complete native verification separately. Owner
                    # current verification/evidence stays in its actual source.
                    draw_refs.append(condition.ref)
            if (len({ref.key() for ref in draw_refs}) != len(draw_refs)
                    or {ref.key() for ref in draw_refs} != {ref.key() for ref in arrangement.required_draw_condition_refs}
                    or arrangement.condition_refs != arrangement.required_draw_condition_refs):
                raise TaskConflict('Native facility drops or adds an Owner draw condition')
            expected = {'schema_version': 'bank-signed-facility.v1', 'run_id': context.run_id,
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'accepted_terms': offer.terms.model_dump(mode='json'), 'confirmed_conditions': conditions,
                'arrangement': arrangement.model_dump(mode='json'),
                'borrower_acceptance': borrower_acceptance.model_dump(mode='json'),
                'lender_confirmation': lender_confirmation.model_dump(mode='json'),
                'condition_mappings': [row.model_dump(mode='json') for row in mappings],
                'signed_at': registration.signed_at.model_dump(mode='json'), 'current_state': 'registered'}
            if registration.native_facility != expected:
                raise TaskConflict('Actual facility replaces native full terms, current undrawn amount, pending executions or draw permissions')
            for ref in [*arrangement.allowed_draw_authorization_refs, *arrangement.pending_execution_refs]:
                if ref.key() not in owner_rows:
                    raise TaskConflict('Native facility lacks an explicitly supplied actual draw permission or pending execution')
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.owner.evidence()), 'schema_version': self.VERSION,
            'bank_arrangement': {'source_task_sha256': self.settings.bank_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'bank_sources': deepcopy(self.bank.evidence()),
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'native_facility_sha256': task_digest(self.settings.registration.native_facility),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Explicit synthetic signed facility/current draw history; no cash, debt or draw execution.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerBankArrangementFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.bank_history, settings.registration
    bank_path, owner_path = Path(history.source_settings.journal_path).resolve(), Path(settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'OWN-A06' or settings.action_id != 'OWN-A06'
            or history.request.context.contract_ref.id != 'BANK-A05' or history.source_settings.action_id != 'BANK-A05'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.identity.role != 'Bank' or history.identity.action_id != 'BANK-A05'
            or history.identity.versions['client'] != history.client_version or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.run_id != request.context.run_id or registration.current_state != 'registered'
            or registration.sharing_authorized is not True or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.arrangement.lender_id != history.identity.organization_id
            or registration.recipient_organization_id != settings.source_projection['organization_id']
            or bank_path == owner_path or not bank_path.is_file()):
        raise ValueError('Facility reception requires existing separate Bank confirmation history and explicit current Owner sources')
    owner = bank = None
    try:
        owner = build_owner_sources(request=request, output_directory=output_directory, offline=offline,
            settings=OwnerFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'bank_history', 'registration'})))
        bank = build_bank_sources(request=history.request, output_directory=output_directory, offline=offline, settings=history.source_settings)
        binding = _ArrangementReception(request, settings, owner, bank)
        return replace(owner, version=binding.VERSION, read_bank_arrangement=binding.read_bank_quote,
            validate_payment_arrangement_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if bank is not None:
                bank.close()
        finally:
            if owner is not None:
                owner.close()
        raise
