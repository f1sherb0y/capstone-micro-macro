"""Shared original Bank command/receipt lineage checks; no dispatch or cash effects."""
from copy import deepcopy
from typing import Annotated

from pydantic import Field, field_validator

from integration.bank_execution_owner_payment_handoff import _receipt_history, _values
from integration.bank_execution_actions import PreparedBankExecution
from src.actions.contracts.bank_execution_objects import (
    BankExecutionApprovalView, BankExecutionReceiptView, BankExecutionSavedView,
)
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class BankExecutionReceptionSettings(StrictRecord):
    identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    executions: Annotated[list[BankExecutionSavedView], Field(min_length=1)]
    receipts: list[BankExecutionReceiptView]
    native_payload: dict
    native_evidence_ref: ref_type('Evidence')
    relation_payload: dict
    relation_evidence_ref: ref_type('Evidence')

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class _ExecutionReception:
    VERSION = 'configured-bank-execution-receipt-fixture-sources.v1'

    def __init__(self, request, settings, sources, worker):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.sources = sources
        self._configuration_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self.worker = worker

    @property
    def reception(self):
        return self.settings.execution_reception

    def _guard(self, context):
        return self.sources.read_guard(context)

    def _validate_evidence(self, observed, payload, prepared):
        return (isinstance(observed, EvidenceRecord) and observed.source_kind == 'synthetic'
            and observed.basis_kind == 'observed' and observed.content_hash == task_digest(payload)
            and (observed.effective_window is None
                or observed.effective_window.contains(prepared.context.business_time)))

    def _validate_observation(self, saved, original_approval, prepared):
        pass

    def _check(self, prepared):
        if (not isinstance(prepared, PreparedBankExecution) or prepared.context.contract_ref.id != 'BANK-A07'
                or prepared.context != self.request.context
                or task_digest(prepared.action_input.model_dump(mode='json')) != task_digest(self.request.action_input)
                or task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256
                or prepared.action_input.operation_context.kind != 'existing'):
            raise TaskConflict('Execution receipt reception changes original existing input, current reader or declaration')
        self.sources.evidence()
        prepared.reading.recheck()

    def _validate_history(self, saved):
        reception = self.reception
        if (saved.identity.as_dict() != reception.identity.as_dict() or saved.current_context != self.request.context
                or saved.record_sha256 != reception.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != reception.source_result_sha256
                or saved.source_reading_sha256 != reception.source_reading_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'execute'
                or saved.action_input.operation_context.kind != 'initiate'):
            raise TaskConflict('Command reception substitutes original Bank execution proposal or its durable lineage')
        return True

    def prepare(self, prepared, *, source_task_sha256):
        self._check(prepared)
        reception = self.reception
        if source_task_sha256 != reception.identity.key:
            raise TaskConflict('Execution receipt reception requires the explicitly selected original Bank task')
        with self._guard(prepared.context):
            reading = prepared.reading
            try:
                saved = self.worker.read_completed(reception.identity, current_context=prepared.context,
                    reading=reading, execution_versions=reception.identity.versions, validate_current=self._validate_history)
                operation = prepared.action_input.operation_context
                originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
                original_approval = BankExecutionApprovalView.model_validate(originals[saved.result.payload.approval_ref.key()])
                executions = {row.ref.key(): row for row in reception.executions}
                receipts = {row.ref.key(): row for row in reception.receipts}
                if (len(executions) != len(reception.executions) or len(receipts) != len(reception.receipts)
                        or len({(row.ref.kind, row.ref.id) for row in reception.executions}) != len(reception.executions)
                        or len({(row.ref.kind, row.ref.id) for row in reception.receipts}) != len(reception.receipts)
                        or len({row.command_id for row in executions.values()}) != len(executions)
                        or len({row.business_key for row in executions.values()}) != len(executions)
                        or set(executions) != {ref.key() for ref in operation.execution_refs}
                        or set(receipts) != {ref.key() for ref in prepared.action_input.receipt_refs}):
                    raise TaskConflict('Execution reception copies or omits explicitly selected original commands or receipts')
                aggregate = {line.local_key: dict.fromkeys(_values(line.amounts, original_approval.amount.currency), 0)
                    for line in original_approval.lines}
                used_receipts = set()
                for execution in reception.executions:
                    current = reading.resolve(execution.ref)
                    approval = reading.resolve(execution.approval_ref)
                    if (current != execution or execution.approval_ref != original_approval.ref
                            or execution.arrangement_ref != saved.action_input.arrangement_ref
                            or execution.path_ref != saved.result.payload.path_ref
                            or execution.lender_id != saved.identity.organization_id
                            or execution.borrower_id != original_approval.borrower_id
                            or execution.lines != original_approval.lines or not isinstance(approval, BankExecutionApprovalView)
                            or execution.ref not in approval.execution_refs
                            or any(getattr(approval, name) != getattr(original_approval, name) for name in
                                ('lender_id', 'borrower_id', 'arrangement_ref', 'terms_ref', 'batch_key', 'amount', 'lines',
                                 'approved_at', 'approver_actor_id', 'approver_function_ref', 'approver_authority_ref', 'scope'))):
                        raise TaskConflict('Native command changes original approval, path, author, parties or complete line allocation')
                    if set(ref.key() for ref in approval.execution_refs) != set(executions):
                        raise TaskConflict('Current approval omits another original command from existing processing')
                    if len({(ref.kind, ref.id) for ref in execution.receipt_refs}) != len(execution.receipt_refs):
                        raise TaskConflict('Native execution repeats a receipt identity')
                    known = [receipts[ref.key()] for ref in execution.receipt_refs if ref.key() in receipts]
                    if execution.receipt_coverage == 'complete' and len(known) != len(execution.receipt_refs):
                        raise TaskConflict('Complete native command history omits an actual receipt source')
                    for receipt in known:
                        if receipt.ref.key() in used_receipts or reading.resolve(receipt.ref) != receipt:
                            raise TaskConflict('Actual receipt is reused by another command or changes current source')
                        used_receipts.add(receipt.ref.key())
                    totals, _ = _receipt_history(execution, known, original_approval.amount.currency,
                        observed_by=prepared.context.business_time)
                    for key, amounts in totals.items():
                        for name, value in amounts.items():
                            aggregate[key][name] += value
                if used_receipts != set(receipts):
                    raise TaskConflict('Reception includes unrelated receipts outside original selected commands')
                for line in original_approval.lines:
                    cap = _values(line.amounts, original_approval.amount.currency)
                    if any(aggregate[line.local_key][name] > value for name, value in cap.items()):
                        raise TaskConflict('Observed commands together exceed the original approved line cash/principal/fee allocation')
                expected_native = {'schema_version': 'bank-execution-observation.v1',
                    'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                    'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
                    'source_reading_sha256': saved.source_reading_sha256,
                    'original_approval': original_approval.model_dump(mode='json'),
                    'executions': [row.model_dump(mode='json') for row in reception.executions],
                    'receipts': [row.model_dump(mode='json') for row in reception.receipts], 'current_state': 'observed'}
                expected_relation = {'schema_version': 'bank-execution-observation-relation.v1',
                    'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
                    'current_context_sha256': task_digest(prepared.context.model_dump(mode='json')),
                    'current_input_sha256': task_digest(prepared.action_input.model_dump(mode='json')),
                    'native_payload_sha256': task_digest(expected_native), 'current_state': 'active'}
                if (reception.native_payload != expected_native or reception.relation_payload != expected_relation
                        or reception.native_evidence_ref == reception.relation_evidence_ref):
                    raise TaskConflict('Independent native command history or current authorized relation differs from original execution')
                for ref, payload in [(reception.native_evidence_ref, expected_native),
                        (reception.relation_evidence_ref, expected_relation)]:
                    observed = reading.resolve(ref)
                    if not self._validate_evidence(observed, payload, prepared):
                        raise TaskConflict('Execution reception lacks separately observed actual command and relation evidence')
                self._validate_observation(saved, original_approval, prepared)
                self._check(prepared)
                return {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
                    'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
                    'source_reading_sha256': saved.source_reading_sha256,
                    'native_payload_sha256': task_digest(expected_native), 'relation_payload_sha256': task_digest(expected_relation),
                    'execution_refs': [row.ref.model_dump(mode='json') for row in reception.executions],
                    'receipt_refs': [row.ref.model_dump(mode='json') for row in reception.receipts]}
            finally:
                reading.recheck()
                self._check(prepared)

    def evidence(self):
        if task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256:
            raise TaskConflict('Execution receipt configuration changed')
        reception = self.reception
        return {**deepcopy(self.sources.evidence()), 'schema_version': self.VERSION,
            'execution_reception': {'identity': reception.identity.as_dict(),
                'native_payload_sha256': task_digest(reception.native_payload),
                'relation_payload_sha256': task_digest(reception.relation_payload),
                'configuration_sha256': self._configuration_sha256,
                'limitations': ['Independent synthetic native command/receipt history; no dispatch, replay or inferred cash/debt.']}}
