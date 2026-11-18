"""Authenticate original remedy/refund waits while retaining installed use and actual transaction history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, ref_type
from src.actions.contracts.supplier_remedy_objects import (
    SupplierRemedyOrderView, SupplierRemedyProfileView, SupplierRemedyRequestView,
    SupplierOriginalTransactionView, SupplierRefundExecutionView, SupplierInstalledUseView, SupplierRemovalRecordView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


REQUEST_CODE = 'continue_original_supply_remedy_request'
REFUND_CODE = 'query_original_refund_before_new_proposal'
_REQUEST_TERMINAL = {'accepted', 'rejected', 'withdrawn'}
_REFUND_TERMINAL = {'succeeded', 'failed', 'rejected'}
_METADATA = {'ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}


@dataclass(frozen=True)
class SupplierRemedyConditionReading(ContractorCloseoutConditionReading):
    """Original immutable remedy input and actual explicitly selected query version."""


def check_supplier_remedy_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    kind = 'SupplyRemedyRequest' if code == REQUEST_CODE else 'RefundExecution'
    if (code not in {REQUEST_CODE, REFUND_CODE} or source['action_id'] != 'SUPPLIER-A11' or source['role'] != 'Supplier'
            or source['purpose'] != 'action' or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (kind,)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, SupplierRemedyConditionReading) or not isinstance(selected.context, ActionContext)
            or not isinstance(selected.original_context, ActionContext) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.history_ref, Reference) or not callable(validate_relation)):
        raise TaskConflict('Remedy recovery requires original typed request/refund wait and private Supplier')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original_context.contract_ref or context.contract_ref.id != 'SUPPLIER-A11'
            or context.scope != original_context.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original_context.actor_id
                or context.function_ref != original_context.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Remedy recovery replaces original input/scope or current read authorization')
    reading.check_method_context(context, 'SUPPLIER-A11')

    def clock(point):
        if point.clock_ref != context.business_time.clock_ref or point.offset > context.business_time.offset:
            raise TaskConflict('Remedy recovery requires the actual same-clock nonfuture source point')

    def evidence_refs(refs, *, at=None, historic=False):
        point = context.business_time if at is None else at
        clock(point)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Remedy recovery lacks exact typed original/current evidence')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    raise TaskConflict('Remedy recovery evidence was not valid at its actual use point')

    def read(ref, schema, *, at=None, historic=False):
        point = context.business_time if at is None else at
        clock(point)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Remedy recovery lacks exact typed original/current sources')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > point.offset:
                raise TaskConflict('Remedy recovery injects an unavailable original/query source')
        evidence_refs(getattr(row, 'evidence_refs', []), at=None if historic else point, historic=historic)
        return row

    def authorize(ref, actor, function_ref, organization, action, at, target):
        clock(at)
        grant, function = read(ref, Authorization), read(function_ref, RoleAssignment)
        roles = {'SUPPLIER': 'Supplier', 'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'QS': 'QS',
            'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.organization_id != organization or grant.actor_id != actor or grant.function_ref != function_ref
                or function.function_ref != function_ref or function.role != roles.get(action.split('-')[0])
                or action not in grant.action_ids or not grant.validity.contains(at)
                or not any(scope_covers(item, target) for item in grant.scopes)):
            raise TaskConflict('Remedy recovery lacks original independent actor/function/scope authority')
        clock(grant.validity.start)
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence_refs([basis_ref], at=at)
            else:
                reading.resolve(basis_ref)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise TaskConflict('Remedy recovery source precedes its original actual author execution')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Remedy recovery repeats source versions')
        return result

    def cash(amount, currency):
        value = decimal_fraction(amount.value)
        if amount.currency != currency or value < 0:
            raise TaskConflict('Refund history substitutes original currency or actual nonnegative cash')
        # Original receipts/refunds have no actual occurrence field. Expiry
        # cannot erase recorded cash or be replaced by a guessed as_of time.
        evidence_refs([amount.basis_ref], historic=True)
        return value

    versions = []
    for values, invocation in ((raw, original_context), (current_raw, context)):
        at = original_context.business_time if terminal else invocation.business_time
        order = read(ref_type('Order').model_validate(values['order_ref']), SupplierRemedyOrderView, at=at)
        profile = read(ref_type('SupplyRemedyProfile').model_validate(values['remedy_profile_ref']), SupplierRemedyProfileView, at=at)
        if (order.supplier_id != source['organization_id'] or order.coverage != 'complete' or order.as_of != at
                or not scope_covers(order.scope, invocation.scope) or profile.order_ref != order.ref
                or profile.organization_id != source['organization_id'] or profile.scope != invocation.scope
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or any(row.effective_window.start.clock_ref != at.clock_ref or row.effective_window.end.clock_ref != at.clock_ref
                    or not row.effective_window.contains(at) for row in (order, profile))):
            raise TaskConflict('Remedy recovery changes original complete order, private profile or working scope')
        if not terminal or values is raw:
            if (profile.authority_ref not in invocation.authorization_refs
                    or keys([Reference.model_validate(ref) for ref in values['authority_refs']]) != keys(invocation.authorization_refs)):
                raise TaskConflict('Remedy recovery replaces original explicit action authorizations')
        authorize(profile.authority_ref, invocation.actor_id, invocation.function_ref,
            source['organization_id'], 'SUPPLIER-A11', at, invocation.scope)
        evidence_refs(profile.basis_refs, at=at)
        for field, order_field in (('batch_refs', 'batch_refs'), ('installed_use_refs', 'material_use_refs'),
                ('change_refs', 'change_refs'), ('defect_refs', 'defect_refs')):
            if keys([Reference.model_validate(ref) for ref in values[field]]) != keys(getattr(order, order_field)):
                raise TaskConflict('Remedy recovery drops original batches, installed uses, changes or defects')
        if (keys(profile.affected_line_refs) & keys(profile.unaffected_line_refs)
                or keys(profile.affected_line_refs) | keys(profile.unaffected_line_refs) != keys(order.line_refs)):
            raise TaskConflict('Remedy recovery drops original unaffected order duties')
        uses, events = {}, set()
        for ref in order.material_use_refs:
            use = read(ref, SupplierInstalledUseView, at=at, historic=True)
            if (use.order_ref != order.ref or use.physical_use_key in uses or use.core_event_id in events
                    or decimal_fraction(use.quantity.value) < 0):
                raise TaskConflict('Remedy recovery duplicates or substitutes installed physical consumption')
            events.add(use.core_event_id)
            evidence_refs([use.quantity.basis_ref], historic=True)
            removed = 0
            keys(use.removal_record_refs)
            for removal_ref in use.removal_record_refs:
                removal = read(removal_ref, SupplierRemovalRecordView, at=at, historic=True)
                quantity = decimal_fraction(removal.quantity.value)
                if (removal.material_use_ref != use.ref or removal.physical_use_key != use.physical_use_key
                        or removal.core_event_id in events or removal.quantity.unit != use.quantity.unit or quantity <= 0):
                    raise TaskConflict('Remedy recovery invents or repeats actual core material removal')
                events.add(removal.core_event_id)
                evidence_refs([removal.quantity.basis_ref], historic=True)
                removed += quantity
            if removed > decimal_fraction(use.quantity.value):
                raise TaskConflict('Remedy recovery erases more than original installed material')
            uses[use.physical_use_key] = use
        versions.append(dict(order=order, profile=profile, uses=uses))
    old, current = versions
    if (old['order'].ref.key()[:2] != current['order'].ref.key()[:2]
            or any(getattr(old['order'], field) != getattr(current['order'], field) for field in ('supplier_id', 'buyer_id', 'currency', 'scope'))):
        raise TaskConflict('Remedy recovery changes original order parties, currency or scope')
    for field in ('line_refs', 'batch_refs', 'material_use_refs', 'change_refs', 'defect_refs', 'transaction_refs', 'request_history_refs'):
        before, after = getattr(old['order'], field), getattr(current['order'], field)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Remedy recovery drops original affected/unaffected physical or payment history')
        for ref in (*before, *after):
            reading.resolve(ref)
    for physical_key, use in old['uses'].items():
        after = current['uses'].get(physical_key)
        if (after is None or any(getattr(use, field) != getattr(after, field) for field in
                ('physical_batch_key', 'owner_id', 'site_operator_id', 'quantity', 'location_ref', 'core_event_id'))
                or not {ref.key()[:2] for ref in use.removal_record_refs} <= {ref.key()[:2] for ref in after.removal_record_refs}):
            raise TaskConflict('Remedy recovery rewrites original installed quantity, ownership or removal history')
    requests, first_request = set(), None
    keys(old['order'].request_history_refs)
    for ref in old['order'].request_history_refs:
        row = read(ref, SupplierRemedyRequestView, at=original_context.business_time, historic=True)
        author(row)
        if row.order_ref != old['order'].ref or row.author_organization_id != source['organization_id'] or row.business_key in requests:
            raise TaskConflict('Remedy recovery duplicates or borrows original request business history')
        requests.add(row.business_key)
        if row.business_key == old['profile'].business_key:
            first_request = row
            break
    transaction_before = transaction_after = None
    if code == REQUEST_CODE:
        first = first_request
        if (first is None or tuple(check.condition.object_refs) != (first.ref,) or first.choice != old['profile'].choice
                or read(first.profile_ref, SupplierRemedyProfileView, at=original_context.business_time) != old['profile']):
            raise TaskConflict('Remedy request wait differs from original first same-business profile gate')
        schema, terminal_statuses = SupplierRemedyRequestView, _REQUEST_TERMINAL
    else:
        if first_request is not None or old['profile'].choice != 'propose_refund':
            raise TaskConflict('Refund query wait bypasses original remedy-request or refund-proposal gate')
        first, transaction_events, refund_events = None, set(), set()
        if not keys(old['profile'].transaction_refs) or not keys(old['profile'].transaction_refs) <= keys(old['order'].transaction_refs):
            raise TaskConflict('Refund query lacks original selected received transaction history')
        for ref in old['profile'].transaction_refs:
            txn = read(ref, SupplierOriginalTransactionView, at=original_context.business_time)
            if (txn.order_ref != old['order'].ref or txn.payer_id != old['order'].buyer_id or txn.payee_id != source['organization_id']
                    or not isinstance(txn.actual_received, Known) or txn.actual_received.value is not True
                    or txn.core_event_id in transaction_events or not txn.refund_history_complete or txn.as_of != original_context.business_time):
                raise TaskConflict('Refund query lacks actual original receipt and complete refund history')
            transaction_events.add(txn.core_event_id)
            businesses, remaining = set(), cash(txn.amount, old['order'].currency)
            keys(txn.refund_execution_refs)
            for refund_ref in txn.refund_execution_refs:
                refund = read(refund_ref, SupplierRefundExecutionView, at=original_context.business_time, historic=True)
                if refund.transaction_ref != txn.ref or refund.business_key in businesses:
                    raise TaskConflict('Refund query duplicates or substitutes original transaction business')
                businesses.add(refund.business_key)
                if refund.status in {'unknown', 'pending'}:
                    first, transaction_before = refund, txn
                    break
                if refund.status == 'succeeded':
                    if refund.core_event_id is None or refund.core_event_id in refund_events:
                        raise TaskConflict('Refund query repeats or invents original actual cash event')
                    refund_events.add(refund.core_event_id)
                    remaining -= cash(refund.amount, old['order'].currency)
                elif refund.core_event_id is not None:
                    raise TaskConflict('Failed/refused original refund invents actual cash')
            if first is not None:
                break
            if remaining < 0:
                raise TaskConflict('Original refunds exceed actual received transaction')
        if first is None or tuple(check.condition.object_refs) != (first.ref,):
            raise TaskConflict('Refund query differs from original first unknown/pending transaction gate')
        schema, terminal_statuses = SupplierRefundExecutionView, _REFUND_TERMINAL
    ref = selected.history_ref
    if ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Remedy query replaces original physical request/refund identity')
    history = read(ref, schema, at=context.business_time, historic=True)
    parent_field = 'transaction_ref' if code == REFUND_CODE else 'order_ref'
    excluded = _METADATA | {parent_field} | ({'core_event_id'} if code == REFUND_CODE else set())
    if (first.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
            or getattr(first, parent_field).key()[:2] != getattr(history, parent_field).key()[:2]
            or first.status in terminal_statuses and first.status != history.status
            or code == REFUND_CODE and first.core_event_id is not None and first.core_event_id != history.core_event_id):
        raise TaskConflict('Remedy query rewrites original request/refund content or known disposition')
    now = context.business_time
    if not history.effective_window.contains(now):
        return 'unavailable', None
    if history.status not in terminal_statuses or not history.evidence_refs:
        return 'waiting', None
    if code == REFUND_CODE:
        if history.status == 'succeeded' and history.core_event_id is None or history.status != 'succeeded' and history.core_event_id is not None:
            raise TaskConflict('Refund query invents successful cash or assigns cash to failure/rejection')
        if terminal and first.business_key != old['profile'].business_key:
            raise TaskConflict('Unrelated refund history must resume the original new-proposal wait instead of archiving it')
        transaction_after = read(history.transaction_ref, SupplierOriginalTransactionView, at=now)
        if (transaction_after.ref.key()[:2] != transaction_before.ref.key()[:2]
                or transaction_after.order_ref.key()[:2] != old['order'].ref.key()[:2]
                or transaction_after.as_of.clock_ref != now.clock_ref
                or not original_context.business_time.offset <= transaction_after.as_of.offset <= now.offset
                or any(getattr(transaction_after, field) != getattr(transaction_before, field) for field in
                    ('payer_id', 'payee_id', 'amount', 'actual_received', 'core_event_id'))
                or not transaction_after.refund_history_complete
                or ref.key() not in keys(transaction_after.refund_execution_refs)
                or not {value.key()[:2] for value in transaction_before.refund_execution_refs}
                    <= {value.key()[:2] for value in transaction_after.refund_execution_refs}):
            raise TaskConflict('Refund query replaces original receipt or erases actual refund ledger history')
        if not terminal:
            transaction_ref = next((ref for ref in current['order'].transaction_refs if ref.key()[:2] == transaction_before.ref.key()[:2]), None)
            if transaction_ref != transaction_after.ref:
                raise TaskConflict('Refund recovery loses original received transaction')
            if transaction_after.order_ref != current['order'].ref or transaction_after.as_of != now:
                raise TaskConflict('Refund recovery requires actual current order and transaction version')
        remaining, events, businesses, refunds, pending = cash(transaction_after.amount, old['order'].currency), set(), set(), {}, False
        for refund_ref in transaction_after.refund_execution_refs:
            refund = read(refund_ref, SupplierRefundExecutionView, at=now, historic=True)
            physical = refund.ref.key()[:2]
            if (refund.transaction_ref != transaction_after.ref or refund.business_key in businesses or physical in refunds):
                raise TaskConflict('Refund recovery borrows or duplicates original transaction history')
            businesses.add(refund.business_key)
            refunds[physical] = refund
            if refund.status not in _REFUND_TERMINAL:
                pending = True
            if refund.status == 'succeeded':
                if refund.core_event_id is None or refund.core_event_id in events:
                    raise TaskConflict('Refund recovery invents or repeats actual returned cash')
                events.add(refund.core_event_id)
                remaining -= cash(refund.amount, old['order'].currency)
            elif refund.core_event_id is not None:
                raise TaskConflict('Unsuccessful refund recovery invents actual returned cash')
        for original_ref in transaction_before.refund_execution_refs:
            original = read(original_ref, SupplierRefundExecutionView, at=original_context.business_time, historic=True)
            after = refunds[original_ref.key()[:2]]
            if (original.model_dump(exclude=excluded) != after.model_dump(exclude=excluded)
                    or original.status in _REFUND_TERMINAL and after.status != original.status
                    or original.core_event_id is not None and original.core_event_id != after.core_event_id):
                raise TaskConflict('Refund recovery rewrites immutable prior cash or refund business history')
        if remaining < 0:
            raise TaskConflict('Refund recovery exceeds original actual received cash')
        if pending and not terminal:
            return 'waiting', None
    elif not terminal and (history.order_ref != current['order'].ref
            or ref.key() not in keys(current['order'].request_history_refs)):
        raise TaskConflict('Remedy query is absent from the actual current request history')
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Remedy query requires independently observed actual native history evidence')
        if row.effective_window is not None and not row.effective_window.contains(now):
            return 'unavailable', None
        if row.effective_window is not None:
            clock(row.effective_window.start)
        evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version='supplier-remedy-history-resolution.v1', condition_code=code,
        disposition=history.status, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_order=old['order'].model_dump(mode='json'), current_order=current['order'].model_dump(mode='json'),
        original_transaction=None if transaction_before is None else transaction_before.model_dump(mode='json'),
        current_transaction=None if transaction_after is None else transaction_after.model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_remedy_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Remedy recovery lacks native original branch/installed-use/receipt/refund/current authority authentication')
    if not terminal and current['profile'].business_key == first.business_key:
        return 'waiting', None
    return 'ready', resolution


def supplier_original_remedy_profile(read_current, validate_relation, condition_code):
    if condition_code not in {REQUEST_CODE, REFUND_CODE} or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Remedy recovery requires original guarded request/refund route and actual native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_supplier_remedy_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('SUPPLIER-A11', condition_code, '2', frozenset({'dependency_change'}), evaluate)
