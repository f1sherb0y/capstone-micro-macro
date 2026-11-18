"""Recover original claim gates without conflating requests, debt and actual cash."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_payment_objects import SupplierSettlementRuleView, SupplierPaymentLedgerView, SupplierPaymentClaimView
from src.actions.roles.supplier_payment import manage_supplier_cash, recheck_original_supplier_claim_wait
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


SAME_CODE = 'continue_original_supplier_payment_claim'
NODE_CODE = 'continue_original_existing_contract_node_claim'
_TERMINAL = {'recognized', 'withdrawn', 'rejected'}
_FIELDS = ('order_refs', 'obligation_refs', 'delivery_evidence_refs', 'account_refs', 'execution_refs')


@dataclass(frozen=True)
class SupplierPaymentConditionReading(ContractorCloseoutConditionReading):
    """Original immutable invocation plus the selected actual claim query version."""
    contract: ActionContract | None = None


def check_supplier_payment_claim_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    if (code not in {SAME_CODE, NODE_CODE} or terminal and code != SAME_CODE
            or source['action_id'] != 'SUPPLIER-A10' or source['role'] != 'Supplier' or source['purpose'] != 'action'
            or check.condition.trigger != 'dependency_change' or tuple(ref.kind for ref in check.condition.object_refs) != ('PaymentClaim',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, SupplierPaymentConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Supplier claim recovery requires its original typed private payment/node wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'SUPPLIER-A10'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Supplier claim recovery replaces original input, scope, time or actual current read authority')
    reading.check_method_context(context, 'SUPPLIER-A10')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'SUPPLIER-A10' or contract.role != 'Supplier':
        raise TaskConflict('Supplier claim recovery requires the original registered action contract')

    def read(ref, schema, *, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Supplier claim recovery lacks exact typed original/query sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Supplier claim recovery imports sources unavailable at their recorded time')
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Supplier claim recovery repeats physical source histories')
        return result

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        rule = read(ref_type('SettlementRule').model_validate(values['settlement_rule_ref']), SupplierSettlementRuleView, at=at)
        ledger = read(rule.ledger_ref, SupplierPaymentLedgerView, at=at)
        if (rule.organization_id != source['organization_id'] or rule.actor_id != invocation.actor_id
                or rule.function_ref != invocation.function_ref or rule.scope != invocation.scope
                or ledger.organization_id != source['organization_id'] or ledger.coverage != 'complete' or ledger.as_of != at
                or not rule.effective_window.contains(at)):
            raise TaskConflict('Supplier claim recovery changes actual original rule, Supplier or complete core ledger')
        for field in _FIELDS:
            refs = [Reference.model_validate(ref) for ref in values[field]]
            keys(refs)
            for ref in refs:
                reading.resolve(ref)
        for field in ('obligation_refs', 'execution_refs'):
            if keys([Reference.model_validate(ref) for ref in values[field]]) != keys(getattr(ledger, field)):
                raise TaskConflict('Supplier claim recovery omits complete original debt/payment ledger inputs')
        keys(ledger.claim_refs)
        versions.append(dict(rule=rule, ledger=ledger))
    old, current = versions
    if (old['ledger'].ref.key()[:2] != current['ledger'].ref.key()[:2]
            or old['rule'].currency != current['rule'].currency):
        raise TaskConflict('Supplier claim recovery replaces original core ledger or currency')
    for field in _FIELDS:
        if not {Reference.model_validate(ref).key()[:2] for ref in raw[field]} <= {Reference.model_validate(ref).key()[:2] for ref in current_raw[field]}:
            raise TaskConflict('Supplier claim recovery drops original orders, delivery, independent debt, accounts or execution history')
    for field in ('claim_refs', 'obligation_refs', 'execution_refs'):
        before, after = getattr(old['ledger'], field), getattr(current['ledger'], field)
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Supplier claim recovery erases original claim, debt or paid/unknown cash history')
    original_gate = recheck_original_supplier_claim_wait(original, contract.validate_input(raw), reading)
    if (original_gate.get('reason_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Supplier claim wait differs from original first same-business/overlapping-node gate')
    ref = selected.history_ref
    if ref.key()[:2] != check.condition.object_refs[0].key()[:2]:
        raise TaskConflict('Supplier claim query replaces original physical application')
    first = read(check.condition.object_refs[0], SupplierPaymentClaimView, at=original.business_time)
    history = read(ref, SupplierPaymentClaimView, at=context.business_time)
    excluded = {'ref', 'claim', 'status', 'available_at', 'effective_window', 'evidence_refs'}
    if (first.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
            or first.claim.model_dump(exclude={'settlement_rule_ref'}) != history.claim.model_dump(exclude={'settlement_rule_ref'})
            or first.claim.settlement_rule_ref.key()[:2] != history.claim.settlement_rule_ref.key()[:2]
            or first.status in _TERMINAL and first.status != history.status):
        raise TaskConflict('Supplier claim query rewrites original payer, amount, node coverage or known disposition')
    for claim_ref in walk_references(history.claim):
        reading.resolve(claim_ref)
    query_rule = read(history.claim.settlement_rule_ref, SupplierSettlementRuleView, at=context.business_time)
    if query_rule.organization_id != source['organization_id'] or query_rule.currency != old['rule'].currency:
        raise TaskConflict('Supplier claim query borrows another Supplier or currency')
    if code == NODE_CODE and history.status not in {'withdrawn', 'rejected'}:
        return 'waiting', None
    if history.status not in _TERMINAL or not history.evidence_refs:
        return 'waiting', None
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    if not terminal:
        if ref.key() not in keys(current['ledger'].claim_refs):
            raise TaskConflict('Supplier claim query is absent from actual current complete claim ledger')
        actual, businesses = {}, set()
        for claim_ref in current['ledger'].claim_refs:
            row = read(claim_ref, SupplierPaymentClaimView, at=context.business_time)
            if row.organization_id != source['organization_id'] or row.business_key in businesses:
                raise TaskConflict('Supplier claim recovery borrows or duplicates current application business')
            businesses.add(row.business_key)
            actual[claim_ref.key()[:2]] = row
        for claim_ref in old['ledger'].claim_refs:
            before = read(claim_ref, SupplierPaymentClaimView, at=original.business_time)
            after = actual[claim_ref.key()[:2]]
            if (before.model_dump(exclude=excluded) != after.model_dump(exclude=excluded)
                    or before.claim.model_dump(exclude={'settlement_rule_ref'}) != after.claim.model_dump(exclude={'settlement_rule_ref'})
                    or before.claim.settlement_rule_ref.key()[:2] != after.claim.settlement_rule_ref.key()[:2]
                    or before.status in _TERMINAL and before.status != after.status):
                raise TaskConflict('Supplier claim recovery rewrites prior requests, coverage or established results')
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord, at=context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Supplier claim query requires independently observed actual native history evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal:
        current_input = contract.validate_input(current_raw)
        current_result = manage_supplier_cash(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='supplier-payment-claim-resolution.v1', condition_code=code,
        disposition=history.status, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_ledger=old['ledger'].model_dump(mode='json'), current_ledger=current['ledger'].model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=current_result, sources=reading.evidence(), methods=reading.method_evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_payment_claim=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Supplier claim recovery lacks native node/debt/cash/claim/current authority authentication')
    return 'ready', resolution


def supplier_original_payment_claim_profile(read_current, validate_relation, condition_code):
    if condition_code not in {SAME_CODE, NODE_CODE} or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier claim recovery requires original guarded history route and native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_supplier_payment_claim_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('SUPPLIER-A10', condition_code, '2', frozenset({'dependency_change'}), evaluate)
