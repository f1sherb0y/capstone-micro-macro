"""Authenticate original fee conditions while retaining actual debts, work and receipts."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference
from src.actions.contracts.architect_billing_objects import (
    ArchitectBillingEngagementView, ArchitectBillingProfileView, ArchitectBillingClauseView,
    ArchitectBillingWorkFactView, ArchitectBillingClaimView, ArchitectBillingReceiptView, ArchitectBillingExecutionView,
    ArchitectBillingCostAccountingView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_billing import handle_service_fees
from src.methods.pricing import decimal_fraction
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CONDITIONS_CODE = 'original_billing_conditions_not_satisfied'
CLAIM_CODE = 'query_original_fee_claim_before_duplicate'
REMINDER_CODE = 'original_fee_not_overdue_or_already_received'
INTERNAL_CODE = 'internal_design_costs_require_actual_work_accounting_without_self_fee_claim'
_KINDS = {CONDITIONS_CODE: 'BillingClause', CLAIM_CODE: 'FeeClaim', REMINDER_CODE: 'FeeClaim', INTERNAL_CODE: 'Engagement'}


@dataclass(frozen=True)
class ArchitectBillingConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_architect_billing_conditions(check, selected, validate_relation):
    if check.condition.condition_code != CONDITIONS_CODE:
        raise TaskConflict('Billing condition checker substitutes the original wait branch')
    return _check_architect_billing_history(check, selected, validate_relation)


def check_architect_billing_claim(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != CLAIM_CODE:
        raise TaskConflict('Billing claim checker substitutes the original wait branch')
    return _check_architect_billing_history(check, selected, validate_relation, terminal=terminal)


def check_architect_billing_reminder(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != REMINDER_CODE:
        raise TaskConflict('Billing reminder checker substitutes the original wait branch')
    return _check_architect_billing_history(check, selected, validate_relation, terminal=terminal)


def _check_architect_billing_history(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code == INTERNAL_CODE:
        return check_architect_billing_internal_cost(check, selected, validate_relation, terminal=terminal)
    source = check.source['identity']
    code = check.condition.condition_code
    if (source['action_id'] != 'ARCHITECT-A10' or source['role'] != 'Architect' or source['purpose'] != 'action'
            or code not in _KINDS or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (_KINDS.get(code),)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectBillingConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code not in {CLAIM_CODE, REMINDER_CODE}):
        raise TaskConflict('Billing recovery requires the original private fee clause wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id']
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ARCHITECT-A10' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Billing recovery substitutes original snapshot, scope, time or current read authority')
    reading.check_method_context(context, 'ARCHITECT-A10')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ARCHITECT-A10' or contract.role != 'Architect':
        raise TaskConflict('Billing recovery lacks its actual registered original A10 contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Billing recovery aliases physical work, claim or receipt histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref or getattr(row, 'scope', context.scope) != context.scope:
            raise TaskConflict('Billing recovery lacks exact typed original/current fee sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Billing recovery introduces sources unavailable at their original/query time')
        return row

    versions = []
    for index, (values, at) in enumerate(((original_input, original.business_time), (current_input, context.business_time))):
        if terminal:
            at = original.business_time
        engagement = read(values.engagement_ref, ArchitectBillingEngagementView, at)
        profile = read(engagement.billing_profile_ref, ArchitectBillingProfileView, at)
        clause = read(values.billing_clause_ref, ArchitectBillingClauseView, at)
        if (values.scope != context.scope or engagement.organization_id != source['organization_id']
                or profile.engagement_ref != engagement.ref or clause.engagement_ref != engagement.ref
                or clause.contract_ref != engagement.contract_ref or clause.payer_id != engagement.payer_id):
            raise TaskConflict('Billing recovery changes original engagement, contract, payer or provider')
        facts = {key: read(ref, ArchitectBillingWorkFactView, at) for key, ref in physical(engagement.work_fact_refs).items()}
        claims = {key: read(ref, ArchitectBillingClaimView, at) for key, ref in physical(engagement.claim_refs).items()}
        history_at = at
        if terminal and index == 1:
            query = read(selected.history_ref, ArchitectBillingClaimView, context.business_time)
            key = check.condition.object_refs[0].key()[:2]
            if query.ref.key()[:2] != key or key not in claims:
                raise TaskConflict('Billing archive substitutes the original fee claim query')
            claims[key] = query
            history_at = context.business_time
        receipt_refs = {ref.key(): ref for ref in (*values.receipt_refs, *(ref for claim in claims.values() for ref in claim.receipt_refs))}
        receipts = {key: read(ref, ArchitectBillingReceiptView, history_at) for key, ref in physical(list(receipt_refs.values())).items()}
        execution_refs = {row.execution_ref.key(): row.execution_ref for row in receipts.values()}
        executions = {key: read(ref, ArchitectBillingExecutionView, history_at) for key, ref in physical(list(execution_refs.values())).items()}
        versions.append(dict(engagement=engagement, profile=profile, clause=clause, facts=facts,
            claims=claims, receipts=receipts, executions=executions))
    old, current = versions
    for name in ('engagement', 'profile', 'clause'):
        before, after = old[name], current[name]
        if before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after:
            raise TaskConflict('Billing recovery replaces original physical sources or rewrites immutable versions')
    for name in ('scope', 'organization_id', 'client_id', 'payer_id', 'payer_organization_id', 'relation'):
        if getattr(old['engagement'], name) != getattr(current['engagement'], name):
            raise TaskConflict('Billing recovery changes original service parties or converts internal cost to an external fee')
    if old['engagement'].contract_ref.key()[:2] != current['engagement'].contract_ref.key()[:2]:
        raise TaskConflict('Billing recovery substitutes the original service contract')
    for name in (('billing_key',) if code == CLAIM_CODE else ('choice', 'billing_key')):
        if getattr(old['profile'], name) != getattr(current['profile'], name):
            raise TaskConflict('Billing condition recovery substitutes the original fee business or branch')
    for name in ('mode', 'fixed_amount', 'unit_rate', 'effort_unit', 'minimum_effort', 'currency',
            'minor_places', 'allowed_correction', 'cumulative_limit'):
        if getattr(old['clause'], name) != getattr(current['clause'], name):
            raise TaskConflict('Billing condition recovery rewrites original known fee prices, rights or limits')
    for name in ('billing_clause_refs', 'work_fact_refs', 'claim_refs'):
        if not set(physical(getattr(old['engagement'], name))) <= set(physical(getattr(current['engagement'], name))):
            raise TaskConflict('Billing recovery drops original work, clauses or outstanding fee histories')
    before, after = original_input.prior_claim_ref, current_input.prior_claim_ref
    query_branch = code == CLAIM_CODE and not terminal and current['profile'].choice != 'claim'
    if query_branch:
        if after != selected.history_ref or current['profile'].ref == old['profile'].ref:
            raise TaskConflict('Claim recovery requires an actual independently authorized original-claim handling branch')
    elif (before is None) != (after is None) or before is not None and before.key()[:2] != after.key()[:2]:
        raise TaskConflict('Billing condition recovery removes or replaces the original prior fee claim')
    for group in ('facts', 'claims', 'receipts', 'executions'):
        if not set(old[group]) <= set(current[group]):
            raise TaskConflict('Billing recovery loses original actual investment, debt or payment history')
        for key, before in old[group].items():
            after = current[group][key]
            if before.ref == after.ref and before != after or before.engagement_ref.key()[:2] != after.engagement_ref.key()[:2]:
                raise TaskConflict('Billing recovery rewrites an immutable business or receipt version')
    for key, before in old['facts'].items():
        after = current['facts'][key]
        if (before.organization_id != source['organization_id'] or after.organization_id != source['organization_id']
                or before.task_ref.key()[:2] != after.task_ref.key()[:2]
                or any(getattr(before, name) != getattr(after, name) for name in ('investment_key', 'effort', 'internal_cost', 'window'))
                or before.status == 'committed' and after.status != 'committed'):
            raise TaskConflict('Billing recovery erases original actual work or internal costs')
    cash_changes = []
    for key, before in old['claims'].items():
        after = current['claims'][key]
        if (before.billing_clause_ref.key()[:2] != after.billing_clause_ref.key()[:2]
                or any(getattr(before, name) != getattr(after, name) for name in ('payer_id', 'payee_organization_id', 'billing_key', 'amount'))
                or before.actual_received.currency != after.actual_received.currency
                or decimal_fraction(after.actual_received.value) < decimal_fraction(before.actual_received.value)
                or not set(before.recognized_event_ids) <= set(after.recognized_event_ids)
                or not set(physical(before.work_fact_refs)) <= set(physical(after.work_fact_refs))
                or not set(physical(before.receipt_refs)) <= set(physical(after.receipt_refs))):
            raise TaskConflict('Billing recovery rewrites original fee amount, paid cash or recognized receipt history')
        if before.actual_received != after.actual_received:
            cash_changes.append(dict(original=before.model_dump(mode='json'), current=after.model_dump(mode='json')))
    for key, before in old['receipts'].items():
        after = current['receipts'][key]
        if (any(getattr(before, name) != getattr(after, name) for name in
                ('payer_id', 'beneficiary_organization_id', 'command_id', 'business_key', 'event_id', 'sequence', 'semantics', 'effective_at'))
                or before.claim_ref.key()[:2] != after.claim_ref.key()[:2]
                or before.execution_ref.key()[:2] != after.execution_ref.key()[:2]
                or before.status in {'verified_partial', 'verified_final'} and after.status not in {'verified_partial', 'verified_final'}
                or before.status == 'verified_final' and after.status != 'verified_final'
                or isinstance(before.amount, Known) and before.amount != after.amount):
            raise TaskConflict('Billing recovery rewrites an original payment event, cash value or command identity')
    for key, before in old['executions'].items():
        after = current['executions'][key]
        if (any(getattr(before, name) != getattr(after, name) for name in
                ('payer_id', 'beneficiary_organization_id', 'command_id', 'business_key'))
                or before.claim_ref.key()[:2] != after.claim_ref.key()[:2]
                or not set(physical(before.receipt_refs)) <= set(physical(after.receipt_refs))):
            raise TaskConflict('Billing recovery replaces original payment execution or its receipt history')
    clause = current['clause']
    if old['profile'].choice not in ({'remind'} if code == REMINDER_CODE else {'claim', 'correct'}):
        raise TaskConflict('Original billing wait must preserve its original claim/correction branch')
    if code == CONDITIONS_CODE:
        if (check.condition.object_refs[0] != old['clause'].ref or selected.history_ref != clause.ref
                or not isinstance(old['clause'].conditions_satisfied, Known) or old['clause'].conditions_satisfied.value):
            raise TaskConflict('Original billing sources do not reproduce the original false billing condition')
        history = clause
    else:
        key = check.condition.object_refs[0].key()[:2]
        before_claim, history = old['claims'].get(key), current['claims'].get(key)
        if (before_claim is None or history is None or before_claim.ref != check.condition.object_refs[0]
                or history.ref != selected.history_ref or code == CLAIM_CODE and history.billing_key != old['profile'].billing_key
                or history.billing_clause_ref.key()[:2] != old['clause'].ref.key()[:2]
                or history.engagement_ref.key()[:2] != old['engagement'].ref.key()[:2]
                or history.payee_organization_id != source['organization_id'] or history.payer_id != old['engagement'].payer_id):
            raise TaskConflict('Fee claim query substitutes original billing business, clause, payer or provider')
        if code == REMINDER_CODE and (original_input.prior_claim_ref != before_claim.ref
                or not terminal and current_input.prior_claim_ref != history.ref):
            raise TaskConflict('Fee reminder recovery substitutes its original/current explicit receivable')
        if history.status == 'unknown':
            return 'waiting', None
        if not terminal and current['profile'].choice == 'claim' and history.status == 'rejected':
            if decimal_fraction(history.actual_received.value) != 0 or any(row.status in {'verified_partial', 'verified_final', 'unknown'}
                    and (not isinstance(row.amount, Known) or decimal_fraction(row.amount.value.value) > 0)
                    for row in current['receipts'].values() if row.claim_ref.key()[:2] == key):
                return 'waiting', None
    original_gate = handle_service_fees(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Billing wait differs from the actual original fee processor gate')
    if code == CONDITIONS_CODE:
        if not isinstance(clause.conditions_satisfied, Known) or not clause.conditions_satisfied.value:
            return 'waiting', None
        if clause.ref == old['clause'].ref:
            raise TaskConflict('Billing recovery requires an actual new satisfied-condition version')
    if code == REMINDER_CODE and terminal:
        if (history.receipt_coverage != 'complete'
                or decimal_fraction(history.actual_received.value) < decimal_fraction(history.amount.value)):
            return 'waiting', None
        receipts = {row.event_id: row for row in current['receipts'].values()
            if row.claim_ref.key()[:2] == history.ref.key()[:2] and row.status in {'verified_partial', 'verified_final'}}
        if not set(history.recognized_event_ids) <= set(receipts):
            return 'unavailable', None
        if decimal_fraction(history.actual_received.value) > 0 and not history.recognized_event_ids:
            return 'unavailable', None
        for event_id in history.recognized_event_ids:
            row = receipts[event_id]
            execution = current['executions'].get(row.execution_ref.key()[:2])
            if (not isinstance(row.amount, Known) or row.amount.value.currency != history.actual_received.currency
                    or decimal_fraction(row.amount.value.value) < 0 or row.effective_at.clock_ref != context.business_time.clock_ref
                    or row.effective_at.offset > min(context.business_time.offset, row.available_at.offset)
                    or execution is None or execution.claim_ref.key()[:2] != history.ref.key()[:2]
                    or execution.command_id != row.command_id or execution.business_key != row.business_key
                    or row.payer_id != history.payer_id or row.beneficiary_organization_id != source['organization_id']
                    or execution.payer_id != row.payer_id or execution.beneficiary_organization_id != row.beneficiary_organization_id
                    or row.ref not in execution.receipt_refs):
                raise TaskConflict('Received reminder archive lacks actual verified payment event and execution provenance')
    evidence = []
    for ref in (clause.condition_evidence_refs if code == CONDITIONS_CODE else history.evidence_refs):
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Billing recovery requires observed actual condition evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json')) for name, value in version.items()}

    if cash_changes or code == REMINDER_CODE and terminal:
        ledger = dict(schema_version='architect-billing-receipt-history-resolution.v1', cash_changes=cash_changes,
            original_sources=dump(old), current_sources=dump(current), sources=reading.evidence())
        if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(ledger),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Billing recovery lacks independent native cash/receipt recognition history')
    current_result = None
    if not terminal:
        current_result = handle_service_fees(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
    resolution = dict(schema_version=('architect-billing-condition-resolution.v1' if code == CONDITIONS_CODE
        else 'architect-billing-reminder-resolution.v1' if code == REMINDER_CODE
        else 'architect-billing-claim-resolution.v1'), condition_code=code,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), cash_changes=cash_changes,
        evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if current_result is not None:
        resolution['current_result'] = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    if code == CLAIM_CODE:
        resolution['disposition'] = 'original_claim_status_archive' if terminal else 'independent_current_fee_handling'
    if code == REMINDER_CODE:
        resolution['disposition'] = 'received_fee_reminder_archive' if terminal else 'actual_overdue_fee_reminder'
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Billing recovery lacks actual independent condition authority and outstanding-duty authentication')
    return 'ready', resolution


def check_architect_billing_internal_cost(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (source['action_id'] != 'ARCHITECT-A10' or source['role'] != 'Architect' or source['purpose'] != 'action'
            or check.condition.condition_code != INTERNAL_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('Engagement',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectBillingConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Internal cost recovery requires the actual original private engagement wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'ARCHITECT-A10'
            or context.scope != original.scope or context.execution_mode != 'llm' or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original.business_time.clock_ref or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Internal cost recovery substitutes original snapshot, scope, time or independent current read authority')
    reading.check_method_context(context, 'ARCHITECT-A10')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ARCHITECT-A10' or contract.role != 'Architect':
        raise TaskConflict('Internal cost recovery lacks its actual original registered A10 contract')
    original_input = contract.validate_input(raw)
    contract.validate_input(current_raw)

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref or getattr(row, 'scope', context.scope) != context.scope:
            raise TaskConflict('Internal cost recovery lacks its exact original/current scoped native source')
        point = getattr(row, 'available_at', None)
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Internal cost recovery introduces a source unavailable at its original/query time')
        return row

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Internal accounting aliases original work or fee histories')
        return result

    old = read(original_input.engagement_ref, ArchitectBillingEngagementView, original.business_time)
    history = read(selected.history_ref, ArchitectBillingEngagementView, context.business_time)
    if (old.ref != check.condition.object_refs[0] or history.ref.key()[:2] != old.ref.key()[:2]
            or old.organization_id != source['organization_id'] or original_input.scope != original.scope
            or old.ref == history.ref and old != history):
        raise TaskConflict('Internal cost recovery substitutes its original physical or immutable engagement')
    for field in ('scope', 'organization_id', 'client_id', 'payer_id', 'payer_organization_id', 'relation'):
        if getattr(old, field) != getattr(history, field):
            raise TaskConflict('Internal cost recovery converts original parties or internal work to external fees')
    if (old.contract_ref.key()[:2] != history.contract_ref.key()[:2]
            or not set(physical(old.work_fact_refs)) <= set(physical(history.work_fact_refs))
            or set(physical(old.claim_refs)) != set(physical(history.claim_refs))):
        raise TaskConflict('Internal cost recovery replaces original contract, loses work or introduces fee claims')
    original_gate = handle_service_fees(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != INTERNAL_CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Internal cost wait differs from the actual original no-self-fee processor gate')
    # Accounting is an independently authorized native service. A10 never resumes self billing.
    if not terminal:
        return 'waiting', None
    if history.coverage != 'complete' or history.as_of != context.business_time or history.cost_accounting_ref is None:
        return 'waiting', None
    accounting = read(history.cost_accounting_ref, ArchitectBillingCostAccountingView, context.business_time)
    if (accounting.run_id != source['run_id'] or accounting.organization_id != source['organization_id']
            or accounting.engagement_ref.key()[:2] != history.ref.key()[:2] or accounting.as_of != context.business_time):
        raise TaskConflict('Internal accounting query changes original run, organization, engagement or actual query time')
    if accounting.status != 'posted' or accounting.coverage != 'complete' or not accounting.lines:
        return 'waiting', None
    line_refs = physical([line.work_fact_ref for line in accounting.lines])
    if set(line_refs) != set(physical(history.work_fact_refs)):
        return 'waiting', None
    if len({line.posting_key for line in accounting.lines}) != len(accounting.lines):
        raise TaskConflict('Internal accounting repeats a native posting under different work slices')
    facts, totals, investments = [], {}, set()
    original_facts = physical(old.work_fact_refs)
    for line in accounting.lines:
        fact = read(line.work_fact_ref, ArchitectBillingWorkFactView, context.business_time)
        if (fact.organization_id != source['organization_id'] or fact.engagement_ref.key()[:2] != history.ref.key()[:2]
                or fact.status != 'committed' or line.work_fact_sha256 != task_digest(fact.model_dump(mode='json'))
                or line.investment_key != fact.investment_key or fact.investment_key in investments
                or line.effort != fact.effort or line.internal_cost != fact.internal_cost
                or any(point.clock_ref != context.business_time.clock_ref for point in
                    (fact.window.start, fact.window.end, fact.available_at, line.posted_at))
                or not fact.window.end.offset <= fact.available_at.offset <= line.posted_at.offset <= accounting.available_at.offset
                or decimal_fraction(fact.effort.value) < 0 or decimal_fraction(fact.internal_cost.value) < 0):
            raise TaskConflict('Internal accounting changes actual work/cost, duplicates investment or invents a posting chronology')
        original_ref = original_facts.get(fact.ref.key()[:2])
        if original_ref is not None:
            before = read(original_ref, ArchitectBillingWorkFactView, original.business_time)
            if (before.task_ref.key()[:2] != fact.task_ref.key()[:2]
                    or any(getattr(before, field) != getattr(fact, field) for field in
                        ('organization_id', 'investment_key', 'effort', 'internal_cost', 'window'))
                    or before.status == 'committed' and fact.status != 'committed'):
                raise TaskConflict('Internal accounting rewrites original investments or known internal cost')
        investments.add(fact.investment_key)
        totals[fact.internal_cost.currency] = totals.get(fact.internal_cost.currency, 0) + decimal_fraction(fact.internal_cost.value)
        facts.append(fact.model_dump(mode='json'))
    if (len({total.currency for total in accounting.totals}) != len(accounting.totals)
            or {total.currency: decimal_fraction(total.value) for total in accounting.totals} != totals):
        raise TaskConflict('Native internal accounting totals differ from actual cost slices or convert currencies')
    refs = {ref.key(): ref for ref in (*accounting.evidence_refs, *accounting.posting_authority_evidence_refs,
        *(fact_ref for line in accounting.lines for fact_ref in (line.effort.basis_ref, line.internal_cost.basis_ref)),
        *(total.basis_ref for total in accounting.totals))}
    if not accounting.posting_authority_evidence_refs:
        return 'unavailable', None
    evidence = []
    for ref in refs.values():
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Internal accounting requires observed native posting and separate accounting authority evidence')
        evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version='architect-billing-internal-cost-resolution.v1', condition_code=INTERNAL_CODE,
        disposition='actual_internal_cost_accounting_archive', history=history.model_dump(mode='json'),
        accounting=accounting.model_dump(mode='json'), original_engagement=old.model_dump(mode='json'), facts=facts,
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=INTERNAL_CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Internal cost archive lacks independently authenticated native accounting service/authority and no-fee effects')
    return 'ready', resolution


def architect_original_billing_profile(read_current, validate_relation, condition_code=CONDITIONS_CODE):
    if condition_code not in _KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Billing recovery requires actual guarded fee sources and native authority validation')
    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Billing condition profile substitutes the original wait branch')
        selected = read_current(deepcopy(check))
        try:
            return _check_architect_billing_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ARCHITECT-A10', condition_code, '1', frozenset({'dependency_change'}), evaluate)
