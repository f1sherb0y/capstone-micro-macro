"""Reconcile existing original draw batches without approving their principal again."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_draw_objects import (
    BankDrawRequestView, BankDrawArrangementView, BankDrawCapacityView, BankDrawBatchView,
    BankDrawExecutionView, BankDrawReceiptView, BankDrawDecisionView, BankDrawTermsView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.roles.bank_draw_accounting import read_draw_usage
from src.actions.roles.owner import ObservationGap
from src.coordination.bank_debt_conditions import BankDebtConditionReading
from src.coordination.continuations import ConditionProfile, ConditionRegistry
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


DRAW_PREFIX = 'query_original_draw_batch:'


class BankDrawBatchRegistry(ConditionRegistry):
    """Only the declared BANK-A06 batch-key family can retain an original wait."""
    def get(self, action_id, condition):
        code = condition.condition_code
        if action_id != 'BANK-A06' or not code.startswith(DRAW_PREFIX) or not code[len(DRAW_PREFIX):]:
            return super().get(action_id, condition)
        if condition.trigger != 'event':
            raise TaskConflict('Original draw batch query requires its declared event trigger')

        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or source['role'] != 'Bank' or source['purpose'] != 'action'
                    or check.condition.condition_code != code or check.condition.trigger != 'event'
                    or not check.condition.object_refs or any(ref.kind != 'DrawBatch' for ref in check.condition.object_refs)
                    or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Original draw batch query changes its task, batch or recipient')
            # Existing approval is never a reason to create another approval.
            return 'waiting'

        return ConditionProfile(action_id, code, '1', frozenset({'event'}), evaluate)


@dataclass(frozen=True)
class BankDrawBatchReading(BankDebtConditionReading):
    queried_capacity_refs: tuple[Reference, ...] = ()


def check_original_draw_batch(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'BANK-A06' or source['role'] != 'Bank'
            or source['purpose'] != 'action' or not check.condition.condition_code.startswith(DRAW_PREFIX)
            or check.condition.trigger != 'event' or check.signal.run_id != source['run_id']
            or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, BankDrawBatchReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not callable(validate_relation)):
        raise TaskConflict('Original draw batch archive requires an explicit authenticated terminal query')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    original_input = selected.original_action_input
    raw = original_input.model_dump(mode='json')
    if (task_digest(raw) != source['input_sha256'] or raw != selected.action_input.model_dump(mode='json')
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A06'
            or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
            or context.scope != original_context.scope or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset or context.execution_mode != 'llm'
            or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']):
        raise TaskConflict('Original draw query replaces the persisted invocation, authority, input or read point')
    reading.check_method_context(context, 'BANK-A06')
    rows = {}

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Draw query lacks exact typed original/current history')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != context.business_time.clock_ref
                or row.available_at.offset > context.business_time.offset):
            raise TaskConflict('Draw query introduces a source unavailable at the observation time')
        rows[ref.key()] = row
        return row

    request = read(original_input.draw_request_ref, BankDrawRequestView)
    arrangement = read(original_input.arrangement_ref, BankDrawArrangementView)
    old_capacity = read(original_input.capacity_snapshot_ref, BankDrawCapacityView)
    profile = read(request.decision_profile_ref, BankDrawDecisionView)
    if (request.lender_id != source['organization_id'] or arrangement.lender_id != request.lender_id
            or request.borrower_id != arrangement.borrower_id or request.arrangement_ref != arrangement.ref
            or profile.organization_id != arrangement.lender_id or profile.draw_request_ref != request.ref
            or old_capacity.lender_id != arrangement.lender_id or old_capacity.arrangement_ref != arrangement.ref
            or old_capacity.coverage != 'complete' or old_capacity.as_of != original_context.business_time
            or check.condition.condition_code != DRAW_PREFIX + request.batch_key
            or {ref.key() for ref in original_input.pending_execution_refs} != {ref.key() for ref in old_capacity.execution_refs}):
        raise TaskConflict('Draw query changes the original batch key, complete usage, request or facility')
    grant = read(profile.authority_ref, Authorization)
    function = read(original_context.function_ref, RoleAssignment)
    if (grant.organization_id != arrangement.lender_id or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or 'BANK-A06' not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time) or function.role != 'Bank'
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes)):
        raise TaskConflict('Draw query lacks the original independent Bank approval authority')
    old_batches = [read(ref, BankDrawBatchView) for ref in old_capacity.approved_batch_refs]
    original_matches = [batch for batch in old_batches
        if batch.batch_key == request.batch_key or batch.draw_request_ref == request.ref]
    if not original_matches or tuple(check.condition.object_refs) != tuple(batch.ref for batch in original_matches):
        raise TaskConflict('Draw query differs from the original first existing-batch gate')
    if len(selected.queried_capacity_refs) != 1:
        raise TaskConflict('Draw query requires one explicitly selected actual current usage snapshot')
    capacity_ref = selected.queried_capacity_refs[0]
    if capacity_ref.key()[:2] != old_capacity.ref.key()[:2]:
        raise TaskConflict('Draw query replaces original physical facility capacity')
    capacity = read(capacity_ref, BankDrawCapacityView)
    current_arrangement = read(capacity.arrangement_ref, BankDrawArrangementView)
    if (current_arrangement.ref.key()[:2] != arrangement.ref.key()[:2]
            or current_arrangement.lender_id != arrangement.lender_id
            or current_arrangement.borrower_id != arrangement.borrower_id
            or current_arrangement.scope != arrangement.scope or capacity.lender_id != arrangement.lender_id
            or capacity.coverage != 'complete' or capacity.as_of != context.business_time):
        raise TaskConflict('Draw query replaces original facility, parties or complete current occupancy')
    for field in ('approved_batch_refs', 'execution_refs', 'reinstatement_refs'):
        before, after = getattr(old_capacity, field), getattr(capacity, field)
        if (len({ref.key()[:2] for ref in after}) != len(after)
                or not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}):
            raise TaskConflict('Draw query drops or duplicates original approved/unknown usage or reinstatement history')
    terms = read(arrangement.terms_ref, BankDrawTermsView)
    currency = terms.facility_limit.currency

    def evidence(refs):
        for ref in refs:
            read(ref, EvidenceRecord)

    def amount(value, expected_currency, positive=False):
        evidence([value.basis_ref])
        number = decimal_fraction(value.value)
        if value.currency != expected_currency or number < 0 or positive and number == 0:
            raise TaskConflict('Draw query changes original currency or actual nonnegative approval/receipt amount')
        return number

    def receipt(ref, expected_currency):
        row = read(ref, BankDrawReceiptView)
        if row.lender_id != arrangement.lender_id or row.arrangement_ref != current_arrangement.ref:
            raise TaskConflict('Draw query receipt substitutes original lender/facility')
        return row, amount(row.amount, expected_currency, True)

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Draw query repeats a current batch/execution/receipt reference')
        return result

    try:
        usage, executed, batches, executions, receipt_ids = read_draw_usage(capacity=capacity,
            arrangement=current_arrangement, lender=arrangement.lender_id, currency=currency,
            read=read, amount=amount, receipt=receipt, evidence=evidence, keys=keys)
    except ObservationGap:
        return 'waiting', None
    by_id = {batch.ref.key()[:2]: batch for batch in batches.values()}
    current_matches = [by_id[batch.ref.key()[:2]] for batch in original_matches]
    for before in old_batches:
        after = by_id[before.ref.key()[:2]]
        if (before.batch_key != after.batch_key or before.draw_request_ref.key()[:2] != after.draw_request_ref.key()[:2]
                or before.lender_id != after.lender_id or before.scope != after.scope
                or amount(before.approved_amount, currency, True) != amount(after.approved_amount, currency, True)
                or not {ref.key()[:2] for ref in before.execution_refs} <= {ref.key()[:2] for ref in after.execution_refs}
                or not {ref.key()[:2] for ref in before.release_receipt_refs} <= {ref.key()[:2] for ref in after.release_receipt_refs}):
            raise TaskConflict('Draw query changes original approval/content or drops prior batch execution/release history')
    current_executions = {row.ref.key()[:2]: row for row in executions.values()}
    for ref in old_capacity.execution_refs:
        before = read(ref, BankDrawExecutionView)
        after = current_executions[ref.key()[:2]]
        if (before.command_id != after.command_id or before.lender_id != after.lender_id or before.scope != after.scope
                or any(getattr(before, field).key()[:2] != getattr(after, field).key()[:2]
                    for field in ('arrangement_ref', 'batch_ref', 'draw_request_ref'))
                or amount(before.amount, currency, True) != amount(after.amount, currency, True)
                or before.status in {'succeeded', 'failed', 'rejected'} and before.status != after.status
                or before.receipt_ref is not None and (after.receipt_ref is None
                    or before.receipt_ref.key()[:2] != after.receipt_ref.key()[:2])):
            raise TaskConflict('Draw query rewrites original payment command, amount or terminal outcome')
    matched_executions = [executions[ref.key()] for batch in current_matches for ref in batch.execution_refs]
    if any(row.status in {'unknown', 'pending'} for row in matched_executions):
        return 'waiting', None
    observed = {}
    for row in (*current_matches, *matched_executions,
            *(read(row.receipt_ref, BankDrawReceiptView) for row in matched_executions)):
        if not row.evidence_refs:
            return 'waiting', None
        for ref in row.evidence_refs:
            item = read(ref, EvidenceRecord)
            if item.source_kind == 'synthetic' or item.basis_kind != 'observed':
                raise TaskConflict('Draw query requires actual observed approval/execution/receipt evidence')
            observed[ref.key()] = item.model_dump(mode='json')
    resolution = dict(schema_version='bank-original-draw-batch-resolution.v1',
        disposition='reconciled_existing_batch' if matched_executions else 'observed_existing_approval',
        original_action_input=raw, action_input=raw, original_context=original_context.model_dump(mode='json'),
        context=context.model_dump(mode='json'), capacity=capacity.model_dump(mode='json'),
        batches=[batch.model_dump(mode='json') for batch in current_matches],
        executions=[row.model_dump(mode='json') for row in matched_executions],
        sources=[row.model_dump(mode='json') for row in rows.values()], observed_evidence=list(observed.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=check.condition.condition_code,
            terminal_draw_batch=True, original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Draw query lacks native original batch/payment/usage/receipt history authentication')
    return 'ready', resolution
