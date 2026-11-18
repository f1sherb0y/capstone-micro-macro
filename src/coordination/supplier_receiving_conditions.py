"""Authenticate original A09 waits using original read-only receiving checks."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_receiving_objects import (
    SupplierReceivingShipmentView, SupplierDeliveryResponseProfileView, SupplierLogisticsOrderView,
    SupplierDeliveryDiscrepancyView, SupplierDeliveryReplacementView,
)
from src.actions.roles.qs_change import content_digest
from src.actions.roles.supplier_receiving import respond_to_receiving
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


SHIPMENT_CODE = 'query_original_shipment_before_receiving_response'
REPLACEMENT_CODE = 'continue_original_delivery_replacement_proposal'
_FIELDS = ('arrival_refs', 'receipt_refs', 'inspection_refs', 'discrepancy_refs', 'receiving_party_refs')
_REPLACEMENT_TERMINAL = {'accepted', 'withdrawn', 'rejected'}


@dataclass(frozen=True)
class SupplierReceivingConditionReading(ContractorCloseoutConditionReading):
    """Exact original invocation and an actual explicitly selected query version."""
    contract: ActionContract | None = None


def check_supplier_receiving_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    kind = 'Shipment' if code == SHIPMENT_CODE else 'DeliveryReplacementProposal'
    if (code not in {SHIPMENT_CODE, REPLACEMENT_CODE} or terminal and code != REPLACEMENT_CODE
            or source['action_id'] != 'SUPPLIER-A09' or source['role'] != 'Supplier' or source['purpose'] != 'action'
            or check.condition.trigger != 'dependency_change' or tuple(ref.kind for ref in check.condition.object_refs) != (kind,)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, SupplierReceivingConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Receiving recovery requires original typed shipment/replacement wait and private Supplier')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'SUPPLIER-A09'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Receiving recovery replaces original input, working scope or actual current authority')
    reading.check_method_context(context, 'SUPPLIER-A09')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'SUPPLIER-A09' or contract.role != 'Supplier':
        raise TaskConflict('Receiving recovery requires the original registered action contract')

    def read(ref, schema, *, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Receiving recovery lacks exact typed original/query sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Receiving recovery injects a source unavailable at its recorded time')
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Receiving recovery repeats physical source histories')
        return result

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        shipment = read(ref_type('Shipment').model_validate(values['shipment_ref']), SupplierReceivingShipmentView, at=at)
        profile = read(shipment.response_profile_ref, SupplierDeliveryResponseProfileView, at=at)
        order = read(shipment.order_ref, SupplierLogisticsOrderView, at=at)
        if (shipment.organization_id != source['organization_id'] or shipment.run_id != source['run_id']
                or shipment.as_of != at or shipment.history_coverage != 'complete'
                or profile.shipment_ref != shipment.ref or profile.organization_id != source['organization_id']
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or profile.scope != invocation.scope or order.supplier_id != source['organization_id']
                or not scope_covers(order.scope, invocation.scope) or not profile.effective_window.contains(at)
                or content_digest(shipment.plan) != shipment.request_sha256):
            raise TaskConflict('Receiving recovery changes original complete shipment, request or Supplier profile')
        for field in _FIELDS:
            if keys([Reference.model_validate(ref) for ref in values[field]]) != keys(getattr(shipment, field)):
                raise TaskConflict('Receiving recovery omits actual arrival, receipt, inspection, discrepancy or receiver history')
        versions.append(dict(shipment=shipment, profile=profile, order=order))
    old, current = versions
    before, after = old['shipment'], current['shipment']
    immutable = ('organization_id', 'run_id', 'operation_id', 'command_id', 'business_key', 'physical_batch_key', 'slice_refs', 'plan', 'request_sha256')
    if (before.ref.key()[:2] != after.ref.key()[:2] or before.order_ref.key()[:2] != after.order_ref.key()[:2]
            or any(getattr(before, field) != getattr(after, field) for field in immutable)
            or before.core_event_id is not None and before.core_event_id != after.core_event_id
            or before.dispatched_at is not None and before.dispatched_at != after.dispatched_at
            or any(getattr(old['order'], field) != getattr(current['order'], field) for field in ('supplier_id', 'buyer_id'))):
        raise TaskConflict('Receiving recovery replaces original transport command, physical cargo, parties or established dispatch')
    for field in (*_FIELDS, 'traversal_refs'):
        keys(getattr(before, field)); keys(getattr(after, field))
        if not {ref.key()[:2] for ref in getattr(before, field)} <= {ref.key()[:2] for ref in getattr(after, field)}:
            raise TaskConflict('Receiving recovery drops original receiving or physical transport history')
    # This is the existing deterministic, read-only source checker. It calls
    # no runner, model, method or writer. Original sources are read under the
    # actual current grants; original business time authenticates their gate.
    original_input = contract.validate_input(raw)
    original_gate = respond_to_receiving(original, original_input, reading)
    if (original_gate.get('kind') != 'deferred' or original_gate.get('reason_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Receiving wait differs from original deterministic first history gate')
    ref = selected.history_ref
    if ref.key()[:2] != check.condition.object_refs[0].key()[:2]:
        raise TaskConflict('Receiving query replaces original physical shipment or replacement request')
    if code == SHIPMENT_CODE:
        history = read(ref, SupplierReceivingShipmentView, at=context.business_time)
        if ref != after.ref:
            raise TaskConflict('Shipment query must be the actual current receiving shipment version')
        if history.status == 'submitted_unknown' or history.query_status in {'unknown', 'not_queried'}:
            return 'waiting', None
        if before.status in {'rejected', 'failed'} and before.status != history.status:
            raise TaskConflict('Shipment query rewrites an established failure or rejection')
        if history.status in {'dispatched', 'in_transit', 'arrived', 'received'} and (
                history.query_status != 'present' or history.core_event_id is None or history.dispatched_at is None):
            raise TaskConflict('Shipment query invents actual dispatch without original present core execution')
        disposition = history.status
    else:
        first = read(check.condition.object_refs[0], SupplierDeliveryReplacementView, at=original.business_time)
        history = read(ref, SupplierDeliveryReplacementView, at=context.business_time)
        excluded = {'ref', 'shipment_ref', 'discrepancy_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}
        if (first.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
                or first.shipment_ref.key()[:2] != history.shipment_ref.key()[:2]
                or first.discrepancy_ref.key()[:2] != history.discrepancy_ref.key()[:2]
                or first.status in _REPLACEMENT_TERMINAL and first.status != history.status):
            raise TaskConflict('Replacement query rewrites original proposal quantities, author or established disposition')
        query_shipment = read(history.shipment_ref, SupplierReceivingShipmentView, at=context.business_time)
        query_issue = read(history.discrepancy_ref, SupplierDeliveryDiscrepancyView, at=context.business_time)
        if (query_shipment.ref.key()[:2] != before.ref.key()[:2]
                or any(getattr(query_shipment, field) != getattr(before, field) for field in immutable)
                or query_issue.shipment_ref.key()[:2] != before.ref.key()[:2]):
            raise TaskConflict('Replacement query borrows another shipment command, physical cargo or delivery issue')
        if history.status not in _REPLACEMENT_TERMINAL:
            return 'waiting', None
        if not terminal:
            issue_ref = next((r for r in after.discrepancy_refs if r.key()[:2] == first.discrepancy_ref.key()[:2]), None)
            if issue_ref is None:
                raise TaskConflict('Replacement recovery loses original delivery issue')
            issue = read(issue_ref, SupplierDeliveryDiscrepancyView, at=context.business_time)
            if (not issue.replacement_history_complete or issue.as_of != context.business_time
                    or ref.key() not in keys(issue.replacement_proposal_refs) or history.discrepancy_ref != issue.ref
                    or history.shipment_ref != after.ref):
                raise TaskConflict('Replacement query is absent from actual current complete issue history')
        disposition = history.status
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    if not history.evidence_refs:
        return 'waiting', None
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord, at=context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Receiving query requires independently observed actual native evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal and code == REPLACEMENT_CODE:
        current_result = respond_to_receiving(context, contract.validate_input(current_raw), reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_raw, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='supplier-receiving-history-resolution.v1', condition_code=code,
        disposition=disposition, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_shipment=before.model_dump(mode='json'), current_shipment=after.model_dump(mode='json'),
        original_gate=original_gate, current_result=current_result, sources=reading.evidence(), evidence=evidence)
    # Normalize gate references for the independent validator and journal.
    resolution['original_gate'] = contract.result_adapter.validate_python(original_gate).model_dump(mode='json')
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_receiving_replacement=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Receiving recovery lacks native command/receiver/inspection/use/current authority authentication')
    return 'ready', resolution


def supplier_original_receiving_profile(read_current, validate_relation, condition_code):
    if condition_code not in {SHIPMENT_CODE, REPLACEMENT_CODE} or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Receiving recovery requires original guarded history route and independent native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_supplier_receiving_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('SUPPLIER-A09', condition_code, '1', frozenset({'dependency_change'}), evaluate)
