"""Independent native draw approval for the original same-journal Bank execution host."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from pydantic import field_validator

from integration.bank_draw_handoff import BankDrawHandoffBasisView
from integration.bank_draw_results import BankDrawResultWorker
from integration.bank_role_contract_fixture_sources import BankFixtureSourceSettings, build_sources as build_bank_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.bank_draw_objects import BankDrawFeeRuleView
from src.actions.contracts.bank_execution_objects import (
    BankExecutionApprovalView, BankExecutionArrangementView, BankExecutionFeeRuleView,
)
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class BankDrawReceptionSettings(StrictRecord):
    identity: TaskIdentity
    basis: BankDrawHandoffBasisView
    approval: BankExecutionApprovalView
    arrangement: BankExecutionArrangementView
    native_payload: dict
    relation_payload: dict

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class BankDrawExecutionFixtureSettings(BankFixtureSourceSettings):
    draw_reception: BankDrawReceptionSettings


class _DrawApprovalReception:
    VERSION = 'configured-bank-draw-execution-fixture-sources.v1'

    def __init__(self, request, settings, sources):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.sources = sources
        self._configuration_sha256 = task_digest(self.settings.model_dump(mode='json'))
        identity = self.settings.draw_reception.identity
        self.worker = BankDrawResultWorker(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=identity.versions['client'], model_version=identity.versions['model'],
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)

    def _check(self):
        if task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('Bank native draw approval reception changed')
        self.sources.evidence()

    def validate_history(self, saved):
        with self.sources.read_guard(self.request.context):
            self._check()
            reception = self.settings.draw_reception
            basis = reception.basis
            if (saved.identity.as_dict() != reception.identity.as_dict()
                    or saved.current_context != self.request.context
                    or saved.record_sha256 != basis.draw_record_sha256
                    or saved.identity.input_sha256 != basis.draw_input_sha256
                    or saved.identity.context_sha256 != basis.draw_context_sha256
                    or saved.source_reading_sha256 != basis.draw_source_reading_sha256
                    or task_digest(saved.result.model_dump(mode='json')) != basis.draw_result_sha256
                    or task_digest(saved.audit) != basis.draw_audit_sha256
                    or saved.result.kind != 'completed' or saved.result.payload.choice != 'approve_draw'):
                raise TaskConflict('Execution replaces the selected original approved draw or its private journal lineage')
            return True

    def _validate_split(self, saved, terms, approval, reading):
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        currency = approval.amount.currency

        def number(value):
            result = Fraction(Decimal(value.value))
            evidence = reading.resolve(value.basis_ref)
            if (value.currency != currency or result < 0 or not isinstance(evidence, EvidenceRecord)
                    or evidence.source_kind != 'synthetic'
                    or value.basis_ref.key() in originals
                        and evidence.model_dump(mode='json') != originals[value.basis_ref.key()]
                    or evidence.effective_window is not None
                        and not evidence.effective_window.contains(self.request.context.business_time)):
                raise TaskConflict('Native approved split changes currency or lacks current explicit amount evidence')
            return result

        total = Fraction()
        for line in approval.lines:
            fees = {'withheld_fee': Fraction(), 'capitalized_fee': Fraction(), 'separate_fee_cash': Fraction()}
            for ref in line.transfer.fee_rule_refs:
                original = BankDrawFeeRuleView.model_validate(originals[ref.key()])
                current = reading.resolve(ref)
                if (original.arrangement_ref != approval.arrangement_ref
                        or original.destination_ref != line.transfer.destination_ref
                        or not isinstance(current, BankExecutionFeeRuleView)
                        or current.arrangement_ref != original.arrangement_ref or current.approval_ref != approval.ref
                        or current.destination_ref != original.destination_ref):
                    raise TaskConflict('Execution fee mapping changes its original approved facility or destination')
                expected = {'withheld_fee': Fraction(), 'capitalized_fee': Fraction(), 'separate_fee_cash': Fraction()}
                field = 'capitalized_fee' if original.basis == 'capitalized' else 'separate_fee_cash'
                expected[field] = number(original.fixed_amount)
                if any(number(getattr(current, key)) != value for key, value in expected.items()):
                    raise TaskConflict('Execution fee split substitutes original draw product fee basis or amount')
                for key in fees:
                    fees[key] += expected[key]
            cash = number(line.transfer.requested)
            figures = {key: number(getattr(line.amounts, key)) for key in
                ('beneficiary_cash', 'principal', 'withheld_fee', 'capitalized_fee', 'separate_fee_cash', 'bank_debit')}
            principal = cash + (fees['capitalized_fee'] if terms.principal_basis == 'transfers_plus_capitalized_fees' else 0)
            if (terms.principal_basis == 'net_transfers' and fees['capitalized_fee']
                    or figures != {'beneficiary_cash': cash, 'principal': principal, **fees,
                        'bank_debit': cash + fees['separate_fee_cash']}):
                raise TaskConflict('Native draw approval substitutes original beneficiary cash/principal/fee/bank debit amounts')
            total += principal
        if total != number(approval.amount):
            raise TaskConflict('Native approval total differs from original complete principal allocation')

    def validate_approval(self, *, saved, basis, request, original_arrangement, terms, approval,
            arrangement, context, reading):
        with self.sources.read_guard(context):
            self._check()
            self.validate_history(saved)
            reception = self.settings.draw_reception
            expected_native = {'schema_version': 'bank-draw-approval-registration.v1',
                'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                'native_approval_id': basis.native_approval_id, 'native_event_id': basis.native_event_id,
                'registered_at': basis.registered_at.model_dump(mode='json'),
                'draw_request': request.model_dump(mode='json'),
                'draw_arrangement': original_arrangement.model_dump(mode='json'),
                'draw_terms': terms.model_dump(mode='json'),
                'draw_conditions': [row.model_dump(mode='json') for row in saved.result.payload.conditions],
                'approval': approval.model_dump(mode='json'), 'arrangement': arrangement.model_dump(mode='json'),
                'current_state': 'registered'}
            expected_relation = {'schema_version': 'bank-draw-approval-relation.v1',
                'source_identity': saved.identity.as_dict(),
                'basis': basis.model_dump(mode='json', exclude={'evidence_refs', 'relation_evidence_refs'}),
                'current_state': 'active'}
            if (context != self.request.context or basis != reception.basis or approval != reception.approval
                    or arrangement != reception.arrangement or reception.native_payload != expected_native
                    or reception.relation_payload != expected_relation
                    or basis.native_source_sha256 != task_digest(reception.native_payload)):
                raise TaskConflict('Declared native approval, current execution history or independent source relation changed')
            for ref, digest in [(basis.native_evidence_ref, task_digest(reception.native_payload)),
                    *[(ref, task_digest(reception.relation_payload)) for ref in basis.relation_evidence_refs]]:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.basis_kind != 'observed'
                        or evidence.source_kind != 'synthetic' or evidence.content_hash != digest):
                    raise TaskConflict('Draw approval lacks separately observed native registration and relation evidence')
            self._validate_split(saved, terms, approval, reading)
            # Approval status/coverage/prior executions stay as independently
            # supplied; A07 owns reconciliation, path, cash and cancellation.
            reading.recheck()
            self._check()
            return True

    def evidence(self):
        self._check()
        reception = self.settings.draw_reception
        return {**deepcopy(self.sources.evidence()), 'schema_version': self.VERSION,
            'draw_reception': {'identity': reception.identity.as_dict(),
                'native_payload_sha256': task_digest(reception.native_payload),
                'relation_payload_sha256': task_digest(reception.relation_payload),
                'configuration_sha256': self._configuration_sha256,
                'limitations': ['Explicit synthetic approval registration and exact split; no A06 replay, native batch creation or transfer effect.']}}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = BankDrawExecutionFixtureSettings.model_validate(settings).model_copy(deep=True)
    identity, registration = settings.draw_reception.identity, settings.draw_reception
    operation = request.action_input.get('operation_context', {})
    if (offline is not True or settings.action_id != 'BANK-A07' or request.context.contract_ref.id != 'BANK-A07'
            or request.context.execution_mode != 'offline_fixture' or identity.action_id != 'BANK-A06'
            or identity.role != 'Bank' or identity.run_id != request.context.run_id
            or identity.organization_id != settings.source_projection['organization_id']
            or operation.get('kind') != 'initiate' or operation.get('draw_approval_ref') != registration.approval.ref.model_dump(mode='json')
            or request.action_input.get('arrangement_ref') != registration.arrangement.ref.model_dump(mode='json')
            or not Path(settings.journal_path).is_file()):
        raise ValueError('Execution approval fixture requires existing same-Bank A06 journal and explicit A07 initiation sources')
    sources = build_bank_sources(request=request, output_directory=output_directory, offline=offline,
        settings=BankFixtureSourceSettings.model_validate(settings.model_dump(mode='json', exclude={'draw_reception'})))
    try:
        reception = _DrawApprovalReception(request, settings, sources)
        return replace(sources, version=reception.VERSION, draw_worker=reception.worker,
            validate_draw_history=reception.validate_history, validate_draw_approval=reception.validate_approval,
            evidence=reception.evidence)
    except Exception:
        sources.close()
        raise
