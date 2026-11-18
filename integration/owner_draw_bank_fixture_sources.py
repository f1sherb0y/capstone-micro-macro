"""Independent Bank draw reception backed by the original authorized Owner journal."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.owner_application_bank_fixture_sources import OwnerApplicationHistorySettings, _ApplicationReception
from integration.owner_payment_actions import OwnerPaymentActionAssembler
from integration.owner_payment_results import OwnerPaymentResultWorker
from integration.owner_role_contract_fixture_sources import build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_draw_objects import BankDrawRequestView, OwnerDrawConditionRelation
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentArrangementReceiptView, OwnerPaymentArrangementView, OwnerPaymentDrawView,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest

# Preserve all explicitly supplied native draw sources, including historical
# usage and receipts. The private lender decision is evaluated by Bank A06.
_BANK_NATIVE_KINDS = frozenset({'DrawRequest', 'FinanceArrangement', 'FinanceTerms', 'DrawCapacity',
    'FundingPurpose', 'Account', 'FeeRule', 'Requirement', 'DrawBatch', 'CreditReinstatement',
    'PaymentExecution', 'PaymentReceipt', 'Obligation', 'TimeWindow'})


class DeclaredDrawBankSource(StrictRecord):
    ref: Reference
    value: dict


class DeclaredOwnerDrawRegistration(StrictRecord):
    schema_version: Literal['owner-draw-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    owner_authorization: OwnerPaymentDrawView
    owner_arrangement: OwnerPaymentArrangementView
    owner_arrangement_receipt: OwnerPaymentArrangementReceiptView
    draw_request: BankDrawRequestView
    condition_relations: list[OwnerDrawConditionRelation]
    bank_sources: Annotated[list[DeclaredDrawBankSource], Field(min_length=1)]
    native_request: dict
    receipt_ref: ref_type('OwnerDrawRequestReceipt')
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


class BankOwnerDrawFixtureSettings(BankFixtureSourceSettings):
    owner_history: OwnerApplicationHistorySettings
    registration: DeclaredOwnerDrawRegistration


class _DrawReception(_ApplicationReception):
    VERSION = 'configured-bank-owner-draw-fixture-sources.v1'
    ACTION_ID = 'OWN-A06'
    ASSEMBLER = OwnerPaymentActionAssembler
    WORKER = OwnerPaymentResultWorker
    EXPECTED_CHOICE = 'draw_request'

    def read_owner_payment(self, *, context, source_task_sha256):
        return self.read_owner_financing(context=context, source_task_sha256=source_task_sha256)

    def validate_reception(self, *, saved, receipt, owner_authorization, owner_arrangement, request, context):
        self._check(context)
        registration, history = self.settings.registration, self.settings.owner_history
        with self.bank.read_guard(context), self.owner.read_guard(history.request.context):
            original = self.read_owner_payment(context=context, source_task_sha256=history.identity.key)
            if (saved != original or registration.current_state != 'submitted' or request.status != 'submitted'
                    or owner_authorization != registration.owner_authorization
                    or owner_arrangement != registration.owner_arrangement or request != registration.draw_request
                    or registration.run_id != context.run_id
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != receipt.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != request.scope or registration.scope != receipt.scope
                    or receipt.ref != registration.receipt_ref or receipt.native_evidence_ref != registration.native_evidence_ref
                    or receipt.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or receipt.condition_relations != registration.condition_relations
                    or receipt.transfer_lines != request.transfer_lines
                    or receipt.received_at != registration.received_at or receipt.available_at != registration.available_at
                    or receipt.effective_window != registration.effective_window
                    or not registration.effective_window.contains(context.business_time)):
                raise TaskConflict('Draw registration changes original Owner instruction or actual current Bank reception')
            originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
            signed = registration.owner_arrangement_receipt
            if (originals.get(owner_authorization.ref.key()) != owner_authorization.model_dump(mode='json')
                    or originals.get(owner_arrangement.ref.key()) != owner_arrangement.model_dump(mode='json')
                    or originals.get(signed.ref.key()) != signed.model_dump(mode='json')
                    or signed.arrangement_ref != owner_arrangement.ref
                    or signed.arrangement_sha256 != task_digest(owner_arrangement.model_dump(mode='json'))):
                raise TaskConflict('Native draw registration substitutes original Owner authority or signed facility/history')
            rows = {Reference.model_validate(row['ref']).key(): row for row in self.settings.source_projection['objects']}
            declared = {row.ref.key(): row.model_dump(mode='json') for row in registration.bank_sources}
            current = {key: row for key, row in rows.items() if row['ref']['kind'] in _BANK_NATIVE_KINDS}
            if (len(declared) != len(registration.bank_sources) or declared != current
                    or rows.get(request.ref.key(), {}).get('value') != request.model_dump(mode='json')):
                raise TaskConflict('Native draw mapping omits or changes current facility/terms/usage/destination/fee/purpose sources')
            required = [request.arrangement_ref, request.terms_ref, request.purpose_ref,
                *request.condition_refs,
                *(line.destination_ref for line in request.transfer_lines),
                *(ref for line in request.transfer_lines for ref in [*line.obligation_refs, *line.fee_rule_refs])]
            if any(ref.key() not in declared for ref in required):
                raise TaskConflict('Native request lacks explicitly declared complete transfer or facility dependencies')
            terms = declared[request.terms_ref.key()]['value']
            tenor = rows.get(signed.accepted_terms.tenor_ref.key(), {}).get('value')
            if (terms['facility_limit'] != signed.accepted_terms.principal_limit.model_dump(mode='json')
                    or terms['draw_window'] != tenor
                    or terms['allowed_fee_rule_refs'] != [ref.model_dump(mode='json') for ref in signed.accepted_terms.fee_rule_refs]
                    or request.purpose_ref != signed.accepted_terms.purpose_ref):
                raise TaskConflict('Bank facility mapping changes originally signed principal, draw window, fees or purpose')
            expected = {'schema_version': 'bank-owner-draw-registration.v1', 'run_id': context.run_id,
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'owner_authorization': owner_authorization.model_dump(mode='json'),
                'owner_arrangement': owner_arrangement.model_dump(mode='json'),
                'owner_arrangement_receipt': signed.model_dump(mode='json'),
                'owner_source_reading': deepcopy(list(saved.source_reading)),
                'draw_request': request.model_dump(mode='json'),
                'condition_relations': [row.model_dump(mode='json') for row in registration.condition_relations],
                'bank_sources': [row.model_dump(mode='json') for row in registration.bank_sources],
                'received_at': registration.received_at.model_dump(mode='json'), 'current_state': 'submitted'}
            if registration.native_request != expected:
                raise TaskConflict('Independent native request replaces original full instruction/history or current Bank source mapping')
            # The original handoff verifies borrower grants, observed receipt,
            # exact amounts/beneficiaries, condition/verifier relations and time.
            # A06 evaluates current capacity, unknown executions and all stages.
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.bank.evidence()), 'schema_version': self.VERSION,
            'owner_draw_request': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'owner_sources': deepcopy(self.owner.evidence()),
                'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Explicit synthetic independent received request; no Bank approval, transfer or cash/debt effect.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankOwnerDrawFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.owner_history, settings.registration
    owner_path, bank_path = Path(history.source_settings.journal_path).resolve(), Path(settings.journal_path).resolve()
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'BANK-A06' or settings.action_id != 'BANK-A06'
            or history.request.context.contract_ref.id != 'OWN-A06' or history.source_settings.action_id != 'OWN-A06'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A06'
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or registration.run_id != request.context.run_id or registration.current_state != 'submitted'
            or registration.sharing_authorized is not True
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.owner_authorization.organization_id != history.identity.organization_id
            or registration.draw_request.borrower_id != history.identity.organization_id
            or registration.draw_request.lender_id != settings.source_projection['organization_id']
            or registration.recipient_organization_id != settings.source_projection['organization_id']
            or owner_path == bank_path or not owner_path.is_file()):
        raise ValueError('Draw reception requires existing separate Owner history and explicit current same-run Bank sources')
    bank = owner = None
    try:
        bank = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
            settings=BankFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'owner_history', 'registration'})))
        owner = build_owner_sources(request=history.request, output_directory=output_directory, offline=offline,
            settings=history.source_settings)
        binding = _DrawReception(request, settings, bank, owner)
        return replace(bank, version=binding.VERSION, read_owner_payment=binding.read_owner_payment,
            validate_owner_draw_request_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if owner is not None:
                owner.close()
        finally:
            if bank is not None:
                bank.close()
        raise
