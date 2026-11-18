"""Independently observed Owner settlement reception of original Bank reconciliation."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.bank_execution_actions import BankExecutionActionAssembler
from integration.bank_execution_results import BankExecutionResultWorker
from integration.bank_offer_owner_fixture_sources import BankQuoteHistorySettings, _OfferReception
from integration.bank_role_contract_fixture_sources import build_sources as build_bank_sources
from integration.owner_payment_results import OwnerPaymentResultWorker
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_execution_objects import BankExecutionReceiptView, BankExecutionSavedView
from src.actions.contracts.common import Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.owner_payment_objects import OwnerPaymentDrawView, OwnerPaymentExecutionView, OwnerPaymentReceiptView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerSettlementSource(StrictRecord):
    ref: Reference
    value: dict


class ObservedOwnerSettlementEffect(StrictRecord):
    effect_id: TextId
    local_key: TextId
    component: Literal['beneficiary_cash', 'principal', 'withheld_fee', 'capitalized_fee', 'separate_fee_cash', 'bank_debit']
    subject_id: TextId
    amount: Money
    owner_source_refs: list[Reference]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class DeclaredBankExecutionRegistration(StrictRecord):
    schema_version: Literal['bank-execution-owner-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    owner_draw_identity: TaskIdentity
    owner_draw_record_sha256: Digest
    owner_draw_result_sha256: Digest
    owner_draw_reading_sha256: Digest
    owner_authorization: OwnerPaymentDrawView
    bank_execution: BankExecutionSavedView
    bank_receipts: list[BankExecutionReceiptView]
    owner_execution: OwnerPaymentExecutionView
    owner_receipt: OwnerPaymentReceiptView | None
    owner_sources: list[OwnerSettlementSource]
    effects: list[ObservedOwnerSettlementEffect]
    native_settlement: dict
    receipt_ref: ref_type('BankExecutionReception')
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
    current_state: Literal['observed', 'superseded']

    @field_validator('source_identity', 'owner_draw_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerBankExecutionFixtureSettings(OwnerFixtureSourceSettings):
    owner_policy_version: TextId
    bank_history: BankQuoteHistorySettings
    registration: DeclaredBankExecutionRegistration


class _ExecutionReception(_OfferReception):
    VERSION = 'configured-owner-bank-execution-fixture-sources.v1'
    ACTION_ID = 'BANK-A07'
    ASSEMBLER = BankExecutionActionAssembler
    WORKER = BankExecutionResultWorker
    CHOICES = frozenset({'reconcile'})

    def __init__(self, request, settings, owner, bank):
        super().__init__(request, settings, owner, bank)
        identity = self.settings.registration.owner_draw_identity
        self.owner_worker = OwnerPaymentResultWorker(store=owner.store, snapshots=InvocationSnapshotStore(owner.store),
            registry=owner.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=owner.validators.invocation, validate_wait=owner.validators.wait,
            validate_recovery=owner.validators.recovery)

    def _validate_owner_draw(self, saved):
        registration = self.settings.registration
        if (saved.identity.as_dict() != registration.owner_draw_identity.as_dict()
                or saved.record_sha256 != registration.owner_draw_record_sha256
                or saved.source_reading_sha256 != registration.owner_draw_reading_sha256
                or task_digest(saved.result.model_dump(mode='json')) != registration.owner_draw_result_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'draw_request'):
            raise TaskConflict('Settlement reception substitutes original independently authorized Owner draw history')
        return True

    def validate_reception(self, *, saved, reception, bank_execution, bank_receipts, owner_execution, actual_amounts, context):
        self._check(context)
        registration, history = self.settings.registration, self.settings.bank_history
        with self.owner.read_guard(context), self.bank.read_guard(history.request.context):
            original = self.read_bank_quote(context=context, source_task_sha256=history.identity.key)
            if (saved != original or registration.current_state != 'observed'
                    or bank_execution != registration.bank_execution or bank_receipts != registration.bank_receipts
                    or owner_execution != registration.owner_execution
                    or registration.source_identity.as_dict() != saved.identity.as_dict()
                    or registration.recipient_organization_id != reception.recipient_organization_id
                    or registration.recipient_actor_id != context.actor_id
                    or registration.recipient_function_ref != context.function_ref
                    or registration.recipient_authorization_refs != context.authorization_refs
                    or registration.scope != reception.scope or reception.ref != registration.receipt_ref
                    or reception.native_evidence_ref != registration.native_evidence_ref
                    or reception.native_record_sha256 != task_digest(registration.model_dump(mode='json'))
                    or reception.received_at != registration.received_at or reception.available_at != registration.available_at
                    or reception.effective_window != registration.effective_window):
                raise TaskConflict('Owner registration changes original Bank history or actual current received execution')
            rows = {Reference.model_validate(row['ref']).key(): row['value'] for row in self.settings.source_projection['objects']}
            # Build an Owner reading under Owner authority, then read its own
            # original draw from the same persistent journal; never run it.
            from integration.owner_payment_actions import OwnerPaymentActionAssembler
            assembler = OwnerPaymentActionAssembler(registry=self.owner.registry, organizations=self.owner.organizations,
                provider=self.owner.provider, macro_version=self.settings.source_projection['macro_version'], source_mode='fixture',
                methods=self.owner.methods, policy_version=self.settings.owner_policy_version,
                model_version=registration.owner_draw_identity.versions['model'])
            current = assembler.build(context, **self.request.action_input)
            try:
                identity = registration.owner_draw_identity
                owner_saved = self.owner_worker.read_completed(identity, current_context=context, reading=current.reading,
                    execution_versions=identity.versions, validate_current=self._validate_owner_draw)
                originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in owner_saved.source_reading}
                draw = registration.owner_authorization
                if (originals.get(draw.ref.key()) != draw.model_dump(mode='json')
                        or rows.get(draw.ref.key()) != draw.model_dump(mode='json') or owner_execution.authorization_ref != draw.ref
                        or draw.arrangement_ref != owner_saved.result.payload.arrangement_ref
                        or draw.amount != owner_saved.result.payload.amount or draw.beneficiary_id != owner_saved.result.payload.beneficiary_id):
                    raise TaskConflict('Owner settlement replaces original actual draw authorization, amount or beneficiary')
            finally:
                current.reading.recheck()
            terminal = registration.owner_receipt
            if ((owner_execution.receipt_ref is None) != (terminal is None)
                    or terminal is not None and (owner_execution.receipt_ref != terminal.ref
                        or rows.get(terminal.ref.key()) != terminal.model_dump(mode='json'))):
                raise TaskConflict('Settlement reception replaces independent terminal Owner receipt')
            financial = {row.ref.key(): row.model_dump(mode='json') for row in registration.owner_sources}
            owner_fields = {'Account': 'organization_id', 'FundingSource': 'organization_id', 'Debt': 'borrower_id',
                'FinanceArrangement': 'borrower_id', 'Obligation': 'debtor_id', 'SettlementComponent': 'debtor_id'}
            if (len(financial) != len(registration.owner_sources)
                    or any(row.ref.kind not in owner_fields or rows.get(row.ref.key()) != row.value
                        or row.value.get(owner_fields[row.ref.kind]) != bank_execution.borrower_id
                        or 'as_of' in row.value and row.value['as_of'] != context.business_time
                        for row in registration.owner_sources)):
                raise TaskConflict('Owner actual financial snapshot is repeated, unavailable or changes native source content')
            effects = {(row.local_key, row.component): row for row in registration.effects}
            expected_effects = {(key, name): Fraction(value) for key, values in actual_amounts.items()
                for name, value in values.items() if Fraction(value) > 0}
            if (len(effects) != len(registration.effects) or len({row.effect_id for row in effects.values()}) != len(effects)
                    or set(effects) != set(expected_effects)):
                raise TaskConflict('Native settlement effects omit or repeat actually observed cash/principal/fee components')
            lines = {line.local_key: line for line in bank_execution.lines}
            for key, effect in effects.items():
                expected_subject = (lines[effect.local_key].transfer.beneficiary_id if effect.component == 'beneficiary_cash'
                    else bank_execution.lender_id if effect.component == 'bank_debit' else bank_execution.borrower_id)
                if (effect.amount.currency != owner_execution.amount.currency or Fraction(effect.amount.value) != expected_effects[key]
                        or effect.subject_id != expected_subject
                        or len(set(effect.owner_source_refs)) != len(effect.owner_source_refs)
                        or any(ref.key() not in financial for ref in effect.owner_source_refs)
                        or effect.component != 'bank_debit' and not effect.owner_source_refs):
                    raise TaskConflict('Owner native effect changes actual recipient/component amount or lacks explicit settlement sources')
                allowed = {'beneficiary_cash': {'Account', 'FundingSource'} if effect.subject_id == bank_execution.borrower_id
                        else {'Obligation', 'SettlementComponent'},
                    'principal': {'Debt'}, 'withheld_fee': {'Debt', 'Obligation', 'SettlementComponent'},
                    'capitalized_fee': {'Debt', 'Obligation', 'SettlementComponent'},
                    'separate_fee_cash': {'Account', 'FundingSource', 'Obligation', 'SettlementComponent'}, 'bank_debit': set()}
                if any(ref.kind not in allowed[effect.component] for ref in effect.owner_source_refs):
                    raise TaskConflict('Native cash/principal/fee component maps to another financial source kind')
                payload = {'schema_version': 'bank-execution-owner-effect.v1', 'source_identity': saved.identity.as_dict(),
                    'source_record_sha256': saved.record_sha256, 'command_id': bank_execution.command_id,
                    'business_key': bank_execution.business_key,
                    'receipt_events': [{'ref': row.ref.model_dump(mode='json'), 'event_id': row.event_id,
                        'sequence': row.sequence, 'semantics': row.semantics} for row in bank_receipts],
                    'effect': effect.model_dump(mode='json', exclude={'basis_refs'}),
                    'owner_sources': [financial[ref.key()] for ref in effect.owner_source_refs]}
                for ref in effect.basis_refs:
                    evidence = rows.get(ref.key())
                    if (not isinstance(evidence, dict) or evidence.get('source_kind') != 'synthetic'
                            or evidence.get('basis_kind') != 'observed' or evidence.get('content_hash') != task_digest(payload)):
                        raise TaskConflict('Settlement component lacks its independently observed native effect and source mapping')
            expected_native = {'schema_version': 'bank-execution-owner-settlement.v1',
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'owner_draw_identity': registration.owner_draw_identity.as_dict(),
                'owner_draw_record_sha256': registration.owner_draw_record_sha256,
                'owner_authorization': registration.owner_authorization.model_dump(mode='json'),
                'bank_execution': bank_execution.model_dump(mode='json'),
                'bank_receipts': [row.model_dump(mode='json') for row in bank_receipts],
                'actual_amounts': actual_amounts, 'owner_execution': owner_execution.model_dump(mode='json'),
                'owner_receipt': terminal.model_dump(mode='json') if terminal is not None else None,
                'owner_sources': [row.model_dump(mode='json') for row in registration.owner_sources],
                'effects': [row.model_dump(mode='json') for row in registration.effects], 'current_state': 'observed'}
            if registration.native_settlement != expected_native:
                raise TaskConflict('Independent Owner settlement substitutes complete native command/receipt/effect history')
            self._check(context)
            return True

    def evidence(self):
        self._check(self.request.context)
        registration = self.settings.registration
        return {**deepcopy(self.owner.evidence()), 'schema_version': self.VERSION,
            'bank_execution': {'source_task_sha256': self.settings.bank_history.identity.key,
                'source_record_sha256': registration.source_record_sha256,
                'owner_draw_identity': registration.owner_draw_identity.as_dict(),
                'bank_sources': deepcopy(self.bank.evidence()),
                'registration_sha256': task_digest(registration.model_dump(mode='json')),
                'native_settlement_sha256': task_digest(registration.native_settlement),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Independent synthetic execution/receipt and native Owner effects; no generated cash, principal, fee or offset.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerBankExecutionFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, registration = settings.bank_history, settings.registration
    bank_path, owner_path = Path(history.source_settings.journal_path).resolve(), Path(settings.journal_path).resolve()
    draw_identity = registration.owner_draw_identity
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.context.contract_ref.id != 'OWN-A06' or settings.action_id != 'OWN-A06'
            or history.request.context.contract_ref.id != 'BANK-A07' or history.source_settings.action_id != 'BANK-A07'
            or history.request.context.execution_mode != 'offline_fixture' or history.identity.role != 'Bank'
            or history.identity.action_id != 'BANK-A07' or history.identity.run_id != request.context.run_id
            or history.request.context.run_id != request.context.run_id or history.request.context.business_time != request.context.business_time
            or history.identity.versions['client'] != history.client_version or history.identity.versions['model'] != history.model_version
            or registration.run_id != request.context.run_id or registration.current_state != 'observed'
            or registration.sharing_authorized is not True or registration.source_identity.as_dict() != history.identity.as_dict()
            or draw_identity.action_id != 'OWN-A06' or draw_identity.role != 'Owner' or draw_identity.run_id != request.context.run_id
            or draw_identity.organization_id != settings.source_projection['organization_id']
            or draw_identity.versions['model'] != 'offline-fixture-no-model.v1'
            or draw_identity.request_id == request.context.operation_id
            or bank_path == owner_path or not bank_path.is_file() or not owner_path.is_file()):
        raise ValueError('Owner execution reception requires original separate Bank and Owner draw journals with explicit current sources')
    owner = bank = None
    try:
        owner = build_owner_sources(request=request, output_directory=output_directory, offline=offline,
            settings=OwnerFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'owner_policy_version', 'bank_history', 'registration'})))
        bank = build_bank_sources(request=history.request, output_directory=output_directory, offline=offline, settings=history.source_settings)
        binding = _ExecutionReception(request, settings, owner, bank)
        return replace(owner, version=binding.VERSION, read_bank_execution=binding.read_bank_quote,
            validate_bank_execution_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if bank is not None:
                bank.close()
        finally:
            if owner is not None:
                owner.close()
        raise
