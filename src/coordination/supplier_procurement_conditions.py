"""Authenticate original offer-line waits without losing procurement commitments."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_planning_objects import (
    SupplierWorkAuthorityView, SupplierPlanningProfileView, SupplierProcurementAuthorityView,
    SupplierUpstreamCommitmentView,
)
from src.actions.roles.supplier_planning import plan_supply
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CODE = 'continue_original_upstream_procurement'
_DISPOSITIONS = {'effective', 'released', 'failed'}
_INPUT_FIELDS = ('requirement_refs', 'design_refs', 'upstream_offer_refs', 'method_refs')


@dataclass(frozen=True)
class SupplierProcurementConditionReading(ContractorCloseoutConditionReading):
    """Exact original invocation and actual explicitly selected commitment query."""
    contract: ActionContract | None = None


def check_supplier_procurement_history(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (source['action_id'] != 'SUPPLIER-A05' or source['role'] != 'Supplier' or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('UpstreamSupplyCommitment',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, SupplierProcurementConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Procurement recovery requires original typed offer-line wait and private Supplier')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'SUPPLIER-A05'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or raw['scope_ref'] != original.scope.model_dump(mode='json')
            or current_raw['scope_ref'] != context.scope.model_dump(mode='json')
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Procurement recovery changes original input, scope, time or actual current authority')
    reading.check_method_context(context, 'SUPPLIER-A05')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'SUPPLIER-A05' or contract.role != 'Supplier':
        raise TaskConflict('Procurement recovery requires its original registered action contract')

    def read(ref, schema, *, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Procurement recovery lacks exact typed original/current sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Procurement recovery injects a source unavailable at its recorded time')
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Procurement recovery repeats physical source histories')
        return result

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        mandate = read(ref_type('SupplyWorkAuthorization').model_validate(values['work_authority_ref']), SupplierWorkAuthorityView, at=at)
        profile = read(mandate.profile_ref, SupplierPlanningProfileView, at=at)
        if (mandate.organization_id != source['organization_id'] or profile.organization_id != source['organization_id']
                or profile.work_authority_ref != mandate.ref or profile.actor_id != invocation.actor_id
                or profile.function_ref != invocation.function_ref or profile.scope != invocation.scope
                or profile.choice != 'accept_upstream_offer' or profile.procurement_authority_ref is None):
            raise TaskConflict('Procurement recovery changes original authorized offer acceptance branch')
        procurement = read(profile.procurement_authority_ref, SupplierProcurementAuthorityView, at=at)
        if (procurement.organization_id != source['organization_id'] or procurement.work_authority_ref != mandate.ref
                or procurement.actor_id != invocation.actor_id or procurement.function_ref != invocation.function_ref
                or procurement.coverage != 'complete' or procurement.as_of != at):
            raise TaskConflict('Procurement recovery lacks complete actual original mandate commitment history')
        keys(procurement.commitment_refs)
        versions.append(dict(mandate=mandate, profile=profile, procurement=procurement))
    old, current = versions
    if (old['mandate'].ref.key()[:2] != current['mandate'].ref.key()[:2]
            or old['procurement'].ref.key()[:2] != current['procurement'].ref.key()[:2]
            or old['procurement'].limit != current['procurement'].limit
            or old['procurement'].allowed_payer_ids != current['procurement'].allowed_payer_ids
            or (old['mandate'].order_ref is None) != (current['mandate'].order_ref is None)
            or old['mandate'].order_ref is not None and old['mandate'].order_ref.key()[:2] != current['mandate'].order_ref.key()[:2]
            or old['mandate'].speculative_authority_ref != current['mandate'].speculative_authority_ref):
        raise TaskConflict('Procurement recovery substitutes original order, risk authority, payer or commitment limit')
    if not {ref.key()[:2] for ref in old['mandate'].order_line_refs} <= {
            ref.key()[:2] for ref in current['mandate'].order_line_refs}:
        raise TaskConflict('Procurement recovery omits original remaining customer order lines')
    for field in _INPUT_FIELDS:
        before = [Reference.model_validate(ref) for ref in raw[field]]
        after = [Reference.model_validate(ref) for ref in current_raw[field]]
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Procurement recovery omits original requirements, design, offers or methods')
    original_input = contract.validate_input(raw)
    original_gate = plan_supply(original, original_input, reading)
    if (original_gate.get('kind') != 'deferred' or original_gate.get('reason_code') != CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Procurement wait differs from original first overlapping offer-line commitment')
    ref = selected.history_ref
    if ref.key()[:2] != check.condition.object_refs[0].key()[:2]:
        raise TaskConflict('Procurement query replaces original physical commitment')
    first = read(check.condition.object_refs[0], SupplierUpstreamCommitmentView, at=original.business_time)
    history = read(ref, SupplierUpstreamCommitmentView, at=context.business_time)
    excluded = {'ref', 'work_authority_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}
    if (first.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
            or first.work_authority_ref.key()[:2] != history.work_authority_ref.key()[:2]
            or first.status in {'released', 'failed'} and first.status != history.status
            or first.status == 'effective' and history.status not in _DISPOSITIONS):
        raise TaskConflict('Procurement query rewrites original offer lines, terms, amount or established disposition')
    query_mandate = read(history.work_authority_ref, SupplierWorkAuthorityView, at=context.business_time)
    if (query_mandate.organization_id != source['organization_id']
            or query_mandate.ref.key()[:2] != old['mandate'].ref.key()[:2]
            or (query_mandate.order_ref is None) != (old['mandate'].order_ref is None)
            or query_mandate.order_ref is not None and query_mandate.order_ref.key()[:2] != old['mandate'].order_ref.key()[:2]
            or query_mandate.speculative_authority_ref != old['mandate'].speculative_authority_ref
            or not {ref.key()[:2] for ref in old['mandate'].order_line_refs} <= {
                ref.key()[:2] for ref in query_mandate.order_line_refs}):
        raise TaskConflict('Procurement query borrows another original work mandate')
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    if history.status not in _DISPOSITIONS or not history.evidence_refs:
        return 'waiting', None
    before_refs, after_refs = old['procurement'].commitment_refs, current['procurement'].commitment_refs
    if not {ref.key()[:2] for ref in before_refs} <= {ref.key()[:2] for ref in after_refs}:
        raise TaskConflict('Procurement recovery drops original outstanding commitment history')
    if not terminal:
        if ref.key() not in keys(after_refs):
            raise TaskConflict('Procurement query is absent from actual current complete commitment history')
        actual = {}
        for commitment_ref in after_refs:
            row = read(commitment_ref, SupplierUpstreamCommitmentView, at=context.business_time)
            actual[commitment_ref.key()[:2]] = row
        for commitment_ref in before_refs:
            before = read(commitment_ref, SupplierUpstreamCommitmentView, at=original.business_time)
            after = actual[commitment_ref.key()[:2]]
            if (before.model_dump(exclude=excluded) != after.model_dump(exclude=excluded)
                    or before.work_authority_ref.key()[:2] != after.work_authority_ref.key()[:2]
                    or before.status in {'released', 'failed'} and before.status != after.status
                    or before.status == 'effective' and after.status not in _DISPOSITIONS):
                raise TaskConflict('Procurement recovery rewrites original accepted lines, amounts or remaining duties')
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord, at=context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Procurement query requires independent observed actual native commitment evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal:
        current_input = contract.validate_input(current_raw)
        current_result = plan_supply(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='supplier-procurement-history-resolution.v1', condition_code=CODE,
        disposition=history.status, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_procurement=old['procurement'].model_dump(mode='json'), current_procurement=current['procurement'].model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'), current_result=current_result,
        sources=reading.evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, terminal_procurement_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Procurement recovery lacks native offer acceptance/commitment/remaining duty/current authority authentication')
    return 'ready', resolution


def supplier_original_procurement_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Procurement recovery requires original guarded history route and independent validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_supplier_procurement_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('SUPPLIER-A05', CODE, '1', frozenset({'dependency_change'}), evaluate)
