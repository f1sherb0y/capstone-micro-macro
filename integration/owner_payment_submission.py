"""Submit original Owner pay/repay instructions and observe actual commands."""
from copy import deepcopy
from fractions import Fraction
from typing import Annotated, Callable, Literal

from pydantic import Field, TypeAdapter

from integration.module_host import module_factory_descriptor
from integration.owner_payment_results import OwnerPaymentResultWorker
from integration.owner_submission import OwnerResultSubmission, OwnerSubmissionCallbacks
from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, StrictRecord
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentAccountView, OwnerPaymentAuthorizationView, OwnerPaymentComponentAmount,
    OwnerPaymentExecutionView, OwnerPaymentReceiptView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import exact_decimal
from src.organization.registry import scope_covers


class OwnerPaymentIssuedLine(StrictRecord):
    line_index: Annotated[int, Field(ge=0)]
    execution: OwnerPaymentExecutionView
    receipt: OwnerPaymentReceiptView | None
    component_amounts: Annotated[list[OwnerPaymentComponentAmount], Field(min_length=1)]


class OwnerPaymentExecutionObservation(StrictRecord):
    schema_version: Literal['owner-payment-execution-observation.v1']
    lines: Annotated[list[OwnerPaymentIssuedLine], Field(min_length=1)]
    coverage: Literal['complete']
    native_payload: dict
    native_evidence: EvidenceRecord


class OwnerPaymentSubmission(OwnerResultSubmission):
    """Preserve the original uncertain-submit boundary; query actual execution.

    Supplied submit/query callbacks own the actual native transport and current
    source guard. read_native_execution independently observes all commands for
    the original accepted request. A registration receipt proves no settlement.
    This adapter creates no execution, receipt, account or debt projection.
    """
    VERSION = 'owner-payment-submission.v2'

    def __init__(self, *, worker, binding_id, binding_version, macro_version,
            callbacks: OwnerSubmissionCallbacks, read_native_execution: Callable,
            supported_choices=None):
        choices = ['pay', 'repay'] if supported_choices is None else list(supported_choices)
        if (not isinstance(worker, OwnerPaymentResultWorker) or not isinstance(callbacks, OwnerSubmissionCallbacks)
                or callbacks.query is None or not callable(read_native_execution)
                or not choices or len(set(choices)) != len(choices) or not set(choices) <= {'pay', 'repay'}):
            raise ValueError('Payment submission requires original payment worker, actual query and independent native observer')
        self.read_native_execution = read_native_execution
        self._original_components = (worker, worker.store, worker.snapshots, worker.registry, callbacks, read_native_execution)
        super().__init__(worker=worker, binding_id=binding_id, binding_version=binding_version,
            macro_version=macro_version, supported_choices=choices, callbacks=callbacks)

    def _configuration(self):
        return {**super()._configuration(), 'native_execution_reader': module_factory_descriptor(
            self.read_native_execution, 'read_native_execution')}

    def _check_binding(self):
        current = (self.worker, self.worker.store, self.worker.snapshots, self.worker.registry,
            self.callbacks, self.read_native_execution)
        if any(actual is not original for actual, original in zip(current, self._original_components)):
            raise TaskConflict('Payment submission substituted original journal, worker or native callbacks')
        super()._check_binding()

    @staticmethod
    def _payment_plan(record, snapshot):
        """Recover exact partial allocations from retained authorized ordering."""
        payload, context = record['result']['payload'], snapshot['context']
        originals = {task_digest(row['ref']): row['projection'] for row in record['source_reading']}
        subject = originals[task_digest(snapshot['action_input']['scope_ref']['ref'])]
        decision = OwnerPaymentAuthorizationView.model_validate(originals[task_digest(subject['payment_authorization_ref'])])
        account = OwnerPaymentAccountView.model_validate(originals[task_digest(payload['account_ref'])])
        if (decision.choice != payload['choice'] or decision.account_ref != account.ref
                or account.organization_id != decision.organization_id
                or decision.actor_id != context['actor_id']
                or decision.function_ref.model_dump(mode='json') != context['function_ref']
                or decision.scope.model_dump(mode='json') != context['scope']
                or account.as_of.model_dump(mode='json') != context['business_time']
                or account.coverage != 'complete' or account.execution_coverage != 'complete'
                or not decision.lines or len({line.priority for line in decision.lines}) != len(decision.lines)):
            raise TaskConflict('Payment changes original authorized account, choice, actor, priority or current cash source')
        states = (account.actual_cash, account.restricted_cash, account.reserved_cash)
        if any(state.state != 'known' or state.value.currency != account.currency
                or Fraction(state.value.value) < 0 for state in states):
            raise TaskConflict('Payment requires original known nonnegative cash, restrictions and reservations')
        free = Fraction(states[0].value.value) - Fraction(states[1].value.value) - Fraction(states[2].value.value)
        if free < 0 or (not decision.allow_partial
                and sum((Fraction(line.amount.value) for line in decision.lines), Fraction()) > free):
            raise TaskConflict('Payment exceeds original actual free cash or partial-payment authority')
        expected, allocations, relations, seen = [], [], [], set()
        for line in sorted(decision.lines, key=lambda value: value.priority):
            if (line.amount.currency != account.currency or Fraction(line.amount.value) <= 0
                    or sum((Fraction(part.amount.value) for part in line.component_amounts), Fraction()) != Fraction(line.amount.value)
                    or any(part.amount.currency != account.currency or Fraction(part.amount.value) <= 0
                        for part in line.component_amounts)):
                raise TaskConflict('Original payment line differs from its positive exact component allocation')
            for part in line.component_amounts:
                if part.component_ref.key() in seen:
                    raise TaskConflict('Original payment authorization repeats a settlement component')
                seen.add(part.component_ref.key())
            available = min(Fraction(line.amount.value), free)
            if available <= 0:
                continue
            rest, parts = available, []
            for part in line.component_amounts:
                if rest <= 0:
                    break
                value = min(rest, Fraction(part.amount.value))
                parts.append({'component_ref': part.component_ref.model_dump(mode='json'),
                    'amount': {**part.amount.model_dump(mode='json'), 'value': exact_decimal(value)}})
                rest -= value
            expected.append({'obligation_ref': line.obligation_ref.model_dump(mode='json'), 'payee_id': line.payee_id,
                'amount': {**line.amount.model_dump(mode='json'), 'value': exact_decimal(available)},
                'component_refs': [part['component_ref'] for part in parts]})
            allocations.append(parts)
            obligation = originals[task_digest(line.obligation_ref.model_dump(mode='json'))]
            debt_ref = obligation['debt_ref']
            arrangement_ref = originals[task_digest(debt_ref)]['arrangement_ref'] if debt_ref is not None else None
            relations.append({'origin_scope': deepcopy(obligation['origin_scope']),
                'debt_ref': deepcopy(debt_ref), 'arrangement_ref': deepcopy(arrangement_ref)})
            free -= available
        if not expected or expected != payload['lines']:
            raise TaskConflict('Saved payment changes original priority, partial amount or component identities')
        return {'schema_version': 'owner-payment-original-plan.v1', 'choice': payload['choice'],
            'authorization_ref': decision.ref.model_dump(mode='json'), 'account_ref': payload['account_ref'],
            'lines': [{**line, 'component_amounts': parts, **relation}
                for line, parts, relation in zip(expected, allocations, relations)]}

    def _original(self, identity):
        request, record, snapshot, row = super()._original(identity)
        self._payment_plan(record, snapshot)
        return request, record, snapshot, row

    def query_execution(self, identity):
        """Read every issued command of the same request, without resubmitting.

        Caller holds the application's current source/authorization guard.
        None preserves unknown issuance; pending/unknown command states are
        returned explicitly. Complete coverage means all original planned lines,
        never complete cash/debt effects. Core reconciliation is a separate step.
        """
        request, record, snapshot, row = self._original(identity)
        if row['submission'] is None:
            raise TaskConflict('Payment execution query requires the original submitted request')
        raw = self._query(request)
        if raw is None:
            return None
        submission_receipt = self._submission._receipt(request, deepcopy(raw))
        self._submission._check_receipt_observation(request, submission_receipt)
        if submission_receipt['disposition'] != 'accepted':
            return None
        plan = self._payment_plan(record, snapshot)
        observed = self.read_native_execution(request=deepcopy(request), record=deepcopy(record),
            snapshot=deepcopy(snapshot), receipt=deepcopy(submission_receipt), payment_plan=deepcopy(plan))
        if observed is None:
            return None
        observation = OwnerPaymentExecutionObservation.model_validate(observed).model_copy(deep=True)
        rows = sorted(observation.lines, key=lambda value: value.line_index)
        if ([value.line_index for value in rows] != list(range(len(plan['lines'])))
                or len({value.execution.ref.key() for value in rows}) != len(rows)
                or len({value.execution.command_id for value in rows}) != len(rows)
                or len({value.execution.business_key for value in rows}) != len(rows)):
            raise TaskConflict('Payment observation duplicates or omits original planned commands')
        original_context = ActionContext.model_validate(snapshot['context'])
        original_time = original_context.business_time
        receipt_refs = set()
        for issued, planned in zip(rows, plan['lines']):
            execution, receipt = issued.execution, issued.receipt
            if (execution.organization_id != request.identity.organization_id
                    or execution.authorization_ref.model_dump(mode='json') != plan['authorization_ref']
                    or execution.operation != plan['choice']
                    or execution.account_ref is None or execution.account_ref.model_dump(mode='json') != plan['account_ref']
                    or execution.arrangement_ref is not None
                        and execution.arrangement_ref.model_dump(mode='json') != planned['arrangement_ref']
                    or [value.model_dump(mode='json') for value in execution.obligation_refs] != [planned['obligation_ref']]
                    or [value.model_dump(mode='json') for value in execution.component_refs] != planned['component_refs']
                    or execution.beneficiary_id != planned['payee_id']
                    or execution.amount.model_dump(mode='json') != planned['amount']
                    or [value.model_dump(mode='json') for value in issued.component_amounts] != planned['component_amounts']
                    or not (scope_covers(original_context.scope, execution.scope)
                        or scope_covers(TypeAdapter(ScopeRef).validate_python(planned['origin_scope']), execution.scope))):
                raise TaskConflict('Actual command changes original account, authorized partial amount or cash component allocation')
            if (execution.available_at.clock_ref != original_time.clock_ref
                    or execution.available_at.offset < original_time.offset
                    or not execution.effective_window.contains(execution.available_at)
                    or observation.native_evidence.ref not in execution.evidence_refs):
                raise TaskConflict('Actual command lacks original chronology or independent native evidence')
            if execution.status in {'unknown', 'pending'}:
                if receipt is not None or execution.receipt_ref is not None:
                    raise TaskConflict('Uncertain command cannot carry a final cash receipt')
                continue
            if (receipt is None or receipt.ref in receipt_refs or execution.receipt_ref != receipt.ref
                    or receipt.execution_ref != execution.ref or receipt.command_id != execution.command_id
                    or receipt.business_key != execution.business_key or receipt.amount != execution.amount
                    or receipt.beneficiary_id != execution.beneficiary_id or receipt.status != execution.status
                    or receipt.scope != execution.scope or receipt.available_at.clock_ref != original_time.clock_ref
                    or receipt.available_at.offset < execution.available_at.offset
                    or not receipt.effective_window.contains(receipt.available_at)
                    or observation.native_evidence.ref not in receipt.evidence_refs):
                raise TaskConflict('Actual final receipt substitutes original command identity, amount or execution outcome')
            receipt_refs.add(receipt.ref)
        native = {'schema_version': 'owner-payment-native-execution.v1',
            'receipt_identity': request.receipt_identity(), 'original_receipt': deepcopy(submission_receipt['original_receipt']),
            'source_identity': request.identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_reading_sha256': record['source_reading_sha256'], 'payment_plan': deepcopy(plan),
            'lines': [value.model_dump(mode='json') for value in observation.lines], 'coverage': 'complete'}
        evidence = observation.native_evidence
        if (task_digest(observation.native_payload) != task_digest(native) or evidence.source_kind == 'synthetic'
                or evidence.basis_kind != 'observed' or evidence.content_hash != task_digest(native)
                or evidence.effective_window is not None and any(not evidence.effective_window.contains(point)
                    for point in [*(value.execution.available_at for value in rows),
                        *(value.receipt.available_at for value in rows if value.receipt is not None)])):
            raise TaskConflict('Payment observation lacks authentic complete native evidence correlated with the original submission')
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Payment receipt-read authority changed during actual execution observation')
        self._submission._check_receipt_observation(request, submission_receipt)
        return {'schema_version': 'owner-payment-issued-reception.v1',
            'source_identity': request.identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_result_sha256': request.output_sha256, 'source_reading_sha256': record['source_reading_sha256'],
            'submission_receipt': deepcopy(submission_receipt), 'payment_plan': deepcopy(plan),
            'observation': observation.model_dump(mode='json')}
