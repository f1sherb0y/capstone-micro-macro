"""Restore actual Engineer billing conditions without resetting work, credits or debts."""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference
from src.actions.contracts.engineer_billing_objects import (
    EngineerBillingEngagementView, EngineerBillingProfileView, EngineerBillingClauseView,
    EngineerBillingWorkFactView, EngineerBillingCalculationView, EngineerBillingClaimView,
    EngineerBillingReceiptView, EngineerBillingExecutionView, EngineerBillingAdvanceCreditView,
    EngineerBillingPayableView,
    EngineerBillingCostAccountingView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.engineer_billing import handle_engineering_fees
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction


CONDITIONS_CODE = 'original_billing_conditions_not_satisfied'
CLAIM_CODE = 'query_original_fee_claim_before_duplicate'
REMINDER_CODE = 'original_fee_not_overdue_or_already_received'
LEDGER_CODE = 'verified_receipts_cover_fee_pending_ledger_recognition'
INTERNAL_CODE = 'internal_engineering_costs_require_actual_work_accounting_without_self_fee_claim'
_REF_KINDS = {CONDITIONS_CODE: ('BillingClause',), CLAIM_CODE: ('FeeClaim',),
    REMINDER_CODE: ('FeeClaim',), LEDGER_CODE: ('FeeClaim',), INTERNAL_CODE: ('Engagement',)}
_METADATA = {'ref', 'available_at', 'effective_window', 'evidence_refs'}
_VERSIONED = {'Engagement', 'BillingProfile', 'BillingClause', 'FeeCalculation', 'FeeClaim', 'WorkFact',
    'PaymentReceipt', 'PaymentExecution', 'AdvanceCredit', 'Obligation', 'Authorization', 'FunctionAssignment'}


@dataclass(frozen=True)
class EngineerBillingConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


@dataclass(frozen=True)
class ServiceBillingRecoveryPolicy:
    """Explicit role binding for the two roles using shared service billing."""
    action_id: str
    role: str
    reading_type: type
    handle_fees: object
    source_types: object
    internal_code: str

    def __post_init__(self):
        if ((self.role, self.action_id) not in {('Engineer', 'ENGINEER-A10'), ('QS', 'QS-A10')}
                or not issubclass(self.reading_type, ContractorCloseoutConditionReading)
                or not callable(self.handle_fees)):
            raise ValueError('Shared billing recovery requires an explicit supported role/action binding')
        object.__setattr__(self, 'source_types', MappingProxyType(dict(self.source_types)))


ENGINEER_POLICY = ServiceBillingRecoveryPolicy('ENGINEER-A10', 'Engineer', EngineerBillingConditionReading,
    handle_engineering_fees, {
        'Engagement': EngineerBillingEngagementView, 'BillingProfile': EngineerBillingProfileView,
        'BillingClause': EngineerBillingClauseView, 'WorkFact': EngineerBillingWorkFactView,
        'FeeCalculation': EngineerBillingCalculationView, 'FeeClaim': EngineerBillingClaimView,
        'PaymentReceipt': EngineerBillingReceiptView, 'PaymentExecution': EngineerBillingExecutionView,
        'AdvanceCredit': EngineerBillingAdvanceCreditView, 'Obligation': EngineerBillingPayableView,
        'WorkCostAccounting': EngineerBillingCostAccountingView,
    }, INTERNAL_CODE)


def _physical_values(value):
    if isinstance(value, dict):
        if set(value) == {'kind', 'id', 'version'} and value['kind'] in _VERSIONED:
            return value['kind'], value['id']
        return {key: _physical_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_physical_values(item) for item in value]
    return value


def check_engineer_billing_conditions(check, selected, validate_relation):
    if check.condition.condition_code != CONDITIONS_CODE:
        raise TaskConflict('Engineering billing condition checker substitutes its original clause wait')
    return _check_engineer_billing_history(check, selected, validate_relation)


def check_engineer_billing_claim(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != CLAIM_CODE:
        raise TaskConflict('Engineering billing claim checker substitutes its original duplicate query')
    return _check_engineer_billing_history(check, selected, validate_relation, terminal=terminal)


def check_engineer_billing_reminder(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code not in {REMINDER_CODE, LEDGER_CODE}:
        raise TaskConflict('Engineering reminder checker substitutes its original fee/time wait')
    return _check_engineer_billing_history(check, selected, validate_relation, terminal=terminal)


def _check_engineer_billing_history(check, selected, validate_relation, *, terminal=False, policy=ENGINEER_POLICY):
    source = check.source['identity']
    code = check.condition.condition_code
    if (source['action_id'] != policy.action_id or source['role'] != policy.role or source['purpose'] != 'action'
            or code not in {CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE} or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != _REF_KINDS.get(code)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, policy.reading_type) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code not in {CLAIM_CODE, REMINDER_CODE, LEDGER_CODE}):
        raise TaskConflict('Engineering billing recovery requires its original private billing-condition wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id']
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != policy.action_id or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Engineering billing recovery substitutes original invocation, time, scope or read authority')
    reading.check_method_context(context, policy.action_id)
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != policy.action_id or contract.role != policy.role:
        raise TaskConflict('Engineering billing recovery lacks its actual original registered A10 contract')
    old_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Engineering billing recovery aliases physical histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref or getattr(row, 'scope', context.scope) != context.scope:
            raise TaskConflict('Engineering billing recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Engineering billing recovery introduces unavailable original/current sources')
        return row

    versions = []
    for index, (values, at) in enumerate(((old_input, original.business_time), (current_input, context.business_time))):
        if terminal:
            at = original.business_time
        engagement = read(values.engagement_ref, policy.source_types['Engagement'], at)
        profile = read(engagement.billing_profile_ref, policy.source_types['BillingProfile'], at)
        clause = read(values.billing_clause_ref, policy.source_types['BillingClause'], at)
        if (engagement.organization_id != source['organization_id'] or profile.engagement_ref != engagement.ref
                or clause.engagement_ref != engagement.ref or clause.contract_ref != engagement.contract_ref
                or clause.payer_id != engagement.payer_id
                or code in {CONDITIONS_CODE, CLAIM_CODE} and (index == 0 or code == CONDITIONS_CODE) and profile.choice not in {'claim', 'correct'}
                or code in {REMINDER_CODE, LEDGER_CODE} and profile.choice != 'remind'):
            raise TaskConflict('Engineering billing recovery replaces original payer, engagement or claim purpose')
        facts = {key: read(ref, policy.source_types['WorkFact'], at) for key, ref in physical(
            list({ref.key(): ref for ref in (*engagement.work_fact_refs, *values.work_fact_refs)}.values())).items()}
        credits = {key: read(ref, policy.source_types['AdvanceCredit'], at) for key, ref in physical(
            list({ref.key(): ref for ref in (*engagement.advance_credit_refs, *profile.advance_credit_refs)}.values())).items()}
        payables = {key: read(ref, policy.source_types['Obligation'], at) for key, ref in physical(engagement.payable_obligation_refs).items()}
        claim_refs = list({ref.key(): ref for ref in (*engagement.claim_refs,
            *(() if values.prior_claim_ref is None else (values.prior_claim_ref,)),
            *(row.advance_claim_ref for row in credits.values()),
            *(row.applied_claim_ref for row in credits.values() if row.applied_claim_ref is not None))}.values())
        claims = {key: read(ref, policy.source_types['FeeClaim'], at) for key, ref in physical(claim_refs).items()}
        history_at = at
        if index == 1 and code in {CLAIM_CODE, REMINDER_CODE, LEDGER_CODE}:
            query = read(selected.history_ref, policy.source_types['FeeClaim'], context.business_time)
            if query.ref.key()[:2] != check.condition.object_refs[0].key()[:2]:
                raise TaskConflict('Engineering claim query changes its original physical fee item')
            claims[query.ref.key()[:2]] = query
            history_at = context.business_time
        receipt_refs = list({ref.key(): ref for ref in (*values.receipt_refs,
            *(ref for row in claims.values() for ref in row.receipt_refs))}.values())
        if index == 1 and terminal and code in {CLAIM_CODE, REMINDER_CODE, LEDGER_CODE}:
            # The persisted invocation keeps its original input references.
            # Only the explicitly queried native claim can select newer receipt
            # versions, which are compared with the original history below.
            queried_receipts = physical(query.receipt_refs)
            receipt_refs = [ref for ref in receipt_refs
                if ref.key()[:2] not in queried_receipts or ref == queried_receipts[ref.key()[:2]]]
        receipts = {key: read(ref, policy.source_types['PaymentReceipt'], history_at) for key, ref in physical(receipt_refs).items()}
        executions = {key: read(ref, policy.source_types['PaymentExecution'], history_at) for key, ref in physical(
            list({row.execution_ref.key(): row.execution_ref for row in receipts.values()}.values())).items()}
        calculation = None if values.calculation_ref is None else read(values.calculation_ref, policy.source_types['FeeCalculation'], at)
        versions.append(dict(engagement=engagement, profile=profile, clause=clause, facts=facts, credits=credits,
            payables=payables, claims=claims, receipts=receipts, executions=executions, calculation=calculation))
    old, current = versions
    if code in {REMINDER_CODE, LEDGER_CODE} and (old_input.prior_claim_ref != check.condition.object_refs[0]
            or current_input.prior_claim_ref != selected.history_ref):
        raise TaskConflict('Engineering reminder recovery changes its original selected fee claim')
    query_branch = code == CLAIM_CODE and not terminal and current['profile'].choice != 'claim'
    if code == CONDITIONS_CODE and (old['clause'].ref != check.condition.object_refs[0]
            or current['clause'].ref != selected.history_ref or not isinstance(old['clause'].conditions_satisfied, Known)
            or old['clause'].conditions_satisfied.value):
        raise TaskConflict('Engineering billing recovery replaces its original unmet clause conditions')
    if query_branch:
        if (current_input.prior_claim_ref != selected.history_ref or current['profile'].ref == old['profile'].ref
                or current['profile'].choice not in {'correct', 'dispute', 'reconcile', 'remind'}):
            raise TaskConflict('Engineering claim recovery lacks an independently authorized original-claim handling branch')
    elif ((old_input.prior_claim_ref is None) != (current_input.prior_claim_ref is None)
            or old_input.prior_claim_ref is not None and old_input.prior_claim_ref.key()[:2] != current_input.prior_claim_ref.key()[:2]):
        raise TaskConflict('Engineering billing recovery replaces its original prior fee claim')
    if (old_input.scope != current_input.scope
            or not set(physical(old_input.work_fact_refs)) <= set(physical(current_input.work_fact_refs))
            or not set(physical(old_input.receipt_refs)) <= set(physical(current_input.receipt_refs))):
        raise TaskConflict('Engineering billing recovery changes its original unmet conditions, work or prior claim')
    original_gate = policy.handle_fees(original, old_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Engineering billing wait differs from its actual original processor gate')

    def retain(before, after, *, mutable=()):
        excluded = _METADATA | set(mutable)
        if (before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after
                or _physical_values(before.model_dump(mode='json', exclude=excluded))
                != _physical_values(after.model_dump(mode='json', exclude=excluded))):
            raise TaskConflict('Engineering billing recovery rewrites original price, business key, work, credit or debt')
        for name in mutable:
            if name == 'condition_evidence_refs':
                continue
            a, b = getattr(before, name), getattr(after, name)
            if isinstance(a, list) and isinstance(b, list):
                if any(isinstance(row, Reference) for row in (*a, *b)):
                    if not set(physical(a)) <= set(physical(b)):
                        raise TaskConflict('Engineering billing recovery drops original referenced history')
                elif not set(a) <= set(b):
                    raise TaskConflict('Engineering billing recovery drops recognized native history')

    retain(old['engagement'], current['engagement'], mutable=('billing_clause_refs', 'work_fact_refs', 'advance_credit_refs',
        'payable_obligation_refs', 'claim_refs', 'coverage', 'as_of'))
    profile_fields = ('advance_credit_refs', 'work_fact_refs')
    if query_branch:
        profile_fields += ('choice', 'correction_basis_refs', 'dispute_question_ref', 'reminder_recipient_id', 'note')
    retain(old['profile'], current['profile'], mutable=profile_fields)
    retain(old['clause'], current['clause'], mutable=('conditions_satisfied', 'condition_evidence_refs'))
    mutable = {'facts': (), 'credits': ('status', 'applied_claim_ref'), 'payables': ('status',),
        'claims': ('status', 'actual_received', 'receipt_refs', 'recognized_event_ids', 'receipt_coverage'),
        'receipts': ('status',), 'executions': ('receipt_refs',)}
    for name, fields in mutable.items():
        if not set(old[name]) <= set(current[name]):
            raise TaskConflict('Engineering billing recovery loses actual investments, advance credits or payment obligations')
        for key, before in old[name].items():
            after = current[name][key]
            retain(before, after, mutable=fields)
            if name == 'facts' and before.status == 'committed' and after.status != 'committed':
                raise TaskConflict('Engineering billing recovery undoes actual committed work')
            if name == 'credits' and before.applied_claim_ref is not None and (after.applied_claim_ref is None
                    or before.applied_claim_ref.key()[:2] != after.applied_claim_ref.key()[:2]):
                raise TaskConflict('Engineering billing recovery resets an actually allocated advance credit')
            if name == 'claims' and (before.actual_received.currency != after.actual_received.currency
                    or decimal_fraction(after.actual_received.value) < decimal_fraction(before.actual_received.value)):
                raise TaskConflict('Engineering billing recovery loses actual received cash')
            if name == 'receipts' and before.status in {'verified_partial', 'verified_final'} and before.status != after.status:
                raise TaskConflict('Engineering billing recovery rewrites a verified actual receipt')
    if code in {CONDITIONS_CODE, CLAIM_CODE} and (old['calculation'] is None
            or code == CONDITIONS_CODE and current['calculation'] is None):
        raise TaskConflict('Engineering billing recovery lacks original and current independently successful calculations')
    if old['calculation'] is not None and current['calculation'] is not None:
        retain(old['calculation'], current['calculation'], mutable=('amount', 'executed_at', 'work_fact_refs', 'advance_credit_refs', 'prior_claim_ref'))
    clause = current['clause']
    history = clause
    if code == CONDITIONS_CODE:
        if not isinstance(clause.conditions_satisfied, Known) or not clause.conditions_satisfied.value:
            return 'waiting', None
        if clause.ref == old['clause'].ref:
            raise TaskConflict('Engineering billing recovery requires an actual new satisfied-condition version')
    else:
        key = check.condition.object_refs[0].key()[:2]
        before, history = old['claims'].get(key), current['claims'].get(key)
        if (before is None or before.ref != check.condition.object_refs[0] or history is None
                or history.ref != selected.history_ref or code == CLAIM_CODE and before.billing_key != old['profile'].billing_key
                or history.engagement_ref.key()[:2] != old['engagement'].ref.key()[:2]
                or history.payer_id != old['engagement'].payer_id or history.payee_organization_id != source['organization_id']):
            raise TaskConflict('Engineering claim query replaces its original business item, payer or beneficiary')
        if history.status == 'unknown':
            return 'waiting', None
        if not history.effective_window.contains(context.business_time):
            return 'unavailable', None
        if code == CLAIM_CODE and not terminal and not query_branch:
            actual = [row for row in current['receipts'].values() if row.claim_ref.key()[:2] == key]
            if (history.status not in {'rejected', 'superseded'} or history.receipt_coverage != 'complete'
                    or decimal_fraction(history.actual_received.value) != 0 or history.recognized_event_ids
                    or any(row.status not in {'failed', 'rejected', 'verified_partial', 'verified_final'}
                        or row.status in {'verified_partial', 'verified_final'} and (not isinstance(row.amount, Known)
                            or row.amount.value.currency != history.amount.currency
                            or decimal_fraction(row.amount.value.value) != 0) for row in actual)):
                return 'waiting', None
    receipt_ledger = None
    if code in {REMINDER_CODE, LEDGER_CODE} and terminal:
        if (history.receipt_coverage != 'complete'
                or decimal_fraction(history.actual_received.value) < decimal_fraction(history.amount.value)):
            return 'waiting', None
        receipt_ledger = _verify_engineer_billing_receipt_ledger(current, history, context)
        if receipt_ledger is None:
            return 'unavailable', None
    if code == LEDGER_CODE and not terminal:
        # Verified cash already covers this fee. Recognition belongs to the
        # native ledger; a second reminder or claim cannot resolve this wait.
        return 'waiting', None
    evidence = []
    for ref in (clause.condition_evidence_refs if code == CONDITIONS_CODE else history.evidence_refs):
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Engineering billing recovery requires observed actual satisfied-condition evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None

    def dump(version):
        return {name: None if value is None else {str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json') for name, value in version.items()}

    resolution_kind = ('conditions' if code == CONDITIONS_CODE else 'claim' if code == CLAIM_CODE
        else 'ledger' if code == LEDGER_CODE else 'reminder')
    resolution = dict(schema_version=f'{policy.role.lower()}-billing-{resolution_kind}-resolution.v1', condition_code=code,
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), original_sources=dump(old), current_sources=dump(current),
        history=history.model_dump(mode='json'), original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        evidence=evidence, sources=reading.evidence())
    if terminal:
        resolution['disposition'] = ('actual_original_fee_claim_status_observed' if code == CLAIM_CODE
            else 'actual_original_fee_receipts_cover_balance')
    if receipt_ledger is not None:
        resolution['receipt_ledger'] = receipt_ledger
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Engineering billing recovery lacks independent native condition/calculation/credit/debt authentication')
    if terminal:
        return 'ready', resolution
    result = policy.handle_fees(context, current_input, reading)
    if result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, result['payload'])
    resolution.update(current_result=contract.result_adapter.validate_python(result).model_dump(mode='json'), sources=reading.evidence())
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Engineering billing recovery lacks native validation of current fee proposal and remaining duties')
    return 'ready', resolution


def _verify_engineer_billing_receipt_ledger(version, claim, context):
    """Recheck fixed receipt arithmetic and identities; never recognize or write cash."""
    if claim.receipt_coverage != 'complete' or claim.actual_received.currency != claim.amount.currency:
        return None
    refs = {ref.key() for ref in claim.receipt_refs}
    if len(refs) != len(claim.receipt_refs):
        raise TaskConflict('Engineering receipt ledger repeats an original receipt reference')
    rows = [row for row in version['receipts'].values() if row.ref.key() in refs]
    if {row.ref.key() for row in rows} != refs:
        return None
    events, sequences, commands, declared, supplied = {}, set(), {}, {}, {}
    for row in rows:
        execution = version['executions'].get(row.execution_ref.key()[:2])
        if (row.claim_ref.key()[:2] != claim.ref.key()[:2] or row.engagement_ref.key()[:2] != claim.engagement_ref.key()[:2]
                or row.payer_id != claim.payer_id or row.beneficiary_organization_id != claim.payee_organization_id
                or row.effective_at.clock_ref != context.business_time.clock_ref
                or row.effective_at.offset > min(context.business_time.offset, row.available_at.offset)
                or execution is None or execution.ref != row.execution_ref
                or execution.claim_ref.key()[:2] != claim.ref.key()[:2]
                or execution.engagement_ref.key()[:2] != claim.engagement_ref.key()[:2]
                or execution.payer_id != row.payer_id or execution.beneficiary_organization_id != row.beneficiary_organization_id
                or execution.command_id != row.command_id or execution.business_key != row.business_key
                or row.ref not in execution.receipt_refs):
            raise TaskConflict('Engineering receipt ledger changes actual payment execution, fee, payer or chronology')
        execution_key = execution.ref.key()
        directory = {ref.key() for ref in execution.receipt_refs}
        if len(directory) != len(execution.receipt_refs) or not directory <= refs:
            return None
        declared[execution_key] = directory
        supplied.setdefault(execution_key, set()).add(row.ref.key())
        command = row.command_id, row.business_key
        if command in commands and commands[command] != execution_key:
            raise TaskConflict('Engineering receipt ledger reuses one command for different executions')
        commands[command] = execution_key
        payload = row.model_dump(mode='json', exclude=_METADATA)
        if row.event_id in events:
            if events[row.event_id].model_dump(mode='json', exclude=_METADATA) != payload:
                raise TaskConflict('Engineering receipt ledger rewrites duplicate event content')
            continue
        events[row.event_id] = row
        sequence = execution_key, row.sequence
        if sequence in sequences:
            raise TaskConflict('Engineering receipt ledger has ambiguous execution sequences')
        sequences.add(sequence)
    if any(supplied[key] != directory for key, directory in declared.items()):
        return None
    if len(set(claim.recognized_event_ids)) != len(claim.recognized_event_ids) or not set(claim.recognized_event_ids) <= set(events):
        return None
    totals, recognized = {}, {}
    for row in sorted(events.values(), key=lambda item: (item.execution_ref.key(), item.sequence)):
        value = None
        if isinstance(row.amount, Known):
            if row.amount.value.currency != claim.amount.currency:
                raise TaskConflict('Engineering receipt ledger cannot convert actual payment currencies')
            value = decimal_fraction(row.amount.value.value)
            if value < 0:
                raise TaskConflict('Engineering receipt ledger cannot infer refunds from negative payments')
        if row.status in {'unknown', 'failed', 'rejected'}:
            if value:
                raise TaskConflict('Engineering receipt ledger cannot recognize unverified positive cash')
            if row.event_id in claim.recognized_event_ids:
                return None
            continue
        if value is None:
            return None
        key = row.command_id, row.business_key
        before = totals.get(key, Fraction())
        if row.semantics == 'cumulative' and value < before:
            raise TaskConflict('Engineering cumulative payment receipt regresses actual cash')
        totals[key] = value if row.semantics == 'cumulative' else before + value
        if row.event_id in claim.recognized_event_ids:
            before = recognized.get(key, Fraction())
            if row.semantics == 'cumulative' and value < before:
                raise TaskConflict('Engineering recognized cumulative receipt regresses ledger cash')
            recognized[key] = value if row.semantics == 'cumulative' else before + value
    recorded = sum(recognized.values(), Fraction())
    if decimal_fraction(claim.actual_received.value) != recorded:
        return None
    return dict(verified_total=str(sum(totals.values(), Fraction())), recognized_total=str(recorded),
        event_ids=sorted(events), recognized_event_ids=list(claim.recognized_event_ids))


def _engineer_internal_financial_history(old, current, original_context, context, read, *, policy=ENGINEER_POLICY):
    """Retain native advances, external debts and received cash during cost posting."""
    versions = []
    for engagement, at in ((old, original_context.business_time), (current, context.business_time)):
        values = {}
        for name, schema, refs in (
                ('claims', policy.source_types['FeeClaim'], engagement.claim_refs),
                ('credits', policy.source_types['AdvanceCredit'], engagement.advance_credit_refs),
                ('payables', policy.source_types['Obligation'], engagement.payable_obligation_refs)):
            rows = {}
            for ref in refs:
                row = read(ref, schema, at)
                if row.engagement_ref != engagement.ref or ref.key()[:2] in rows:
                    raise TaskConflict('Internal accounting aliases original financial histories or engagement versions')
                if name == 'claims' and (row.payer_id != engagement.payer_id
                        or row.payee_organization_id != engagement.organization_id):
                    raise TaskConflict('Internal accounting changes original fee payer or beneficiary')
                if name == 'payables' and (row.payer_organization_id != engagement.organization_id
                        or row.beneficiary_organization_id == engagement.organization_id):
                    raise TaskConflict('Internal accounting replaces an independent external payment obligation')
                rows[ref.key()[:2]] = row
            values[name] = rows
        values['receipts'], values['executions'] = {}, {}
        for claim in values['claims'].values():
            for ref in claim.receipt_refs:
                row = read(ref, policy.source_types['PaymentReceipt'], at)
                if row.claim_ref != claim.ref or row.engagement_ref != engagement.ref:
                    raise TaskConflict('Internal accounting receipt changes its actual fee or engagement version')
                key = ref.key()[:2]
                if key in values['receipts']:
                    raise TaskConflict('Internal accounting aliases one receipt across fee histories')
                values['receipts'][key] = row
                execution = read(row.execution_ref, policy.source_types['PaymentExecution'], at)
                prior = values['executions'].get(execution.ref.key()[:2])
                if prior is not None and prior != execution:
                    raise TaskConflict('Internal accounting aliases actual payment executions')
                values['executions'][execution.ref.key()[:2]] = execution
        for credit in values['credits'].values():
            advance = values['claims'].get(credit.advance_claim_ref.key()[:2])
            if advance is None or advance.ref != credit.advance_claim_ref:
                raise TaskConflict('Internal accounting loses the actual original advance claim')
            if credit.applied_claim_ref is not None:
                applied = values['claims'].get(credit.applied_claim_ref.key()[:2])
                if (applied is None or applied.ref != credit.applied_claim_ref
                        or credit.ref not in applied.advance_credit_refs or credit.billing_key != applied.billing_key):
                    raise TaskConflict('Internal accounting loses an actual advance allocation')
        versions.append(values)
    before, after = versions
    mutable = {'claims': {'status', 'actual_received', 'receipt_refs', 'recognized_event_ids', 'receipt_coverage'},
        'credits': {'status', 'applied_claim_ref'}, 'payables': {'status'},
        'receipts': {'status'}, 'executions': {'receipt_refs'}}
    for name, fields in mutable.items():
        if not set(before[name]) <= set(after[name]):
            raise TaskConflict('Internal accounting drops actual cash, advance credits or external debts')
        for key, prior in before[name].items():
            row = after[name][key]
            if (prior.ref == row.ref and prior != row
                    or _physical_values(prior.model_dump(mode='json', exclude=_METADATA | fields))
                    != _physical_values(row.model_dump(mode='json', exclude=_METADATA | fields))):
                raise TaskConflict('Internal accounting rewrites original fee, credit, payment or debt terms')
            if name == 'claims':
                if (prior.actual_received.currency != row.actual_received.currency
                        or decimal_fraction(row.actual_received.value) < decimal_fraction(prior.actual_received.value)
                        or not set(prior.recognized_event_ids) <= set(row.recognized_event_ids)
                        or not {ref.key()[:2] for ref in prior.receipt_refs} <= {ref.key()[:2] for ref in row.receipt_refs}):
                    raise TaskConflict('Internal accounting loses recognized cash or receipt history')
            if name == 'credits' and prior.applied_claim_ref is not None and (
                    row.applied_claim_ref is None or prior.applied_claim_ref.key()[:2] != row.applied_claim_ref.key()[:2]
                    or row.status != prior.status):
                raise TaskConflict('Internal accounting releases an already allocated advance')
            if name == 'payables' and prior.status == 'settled' and row.status != 'settled':
                raise TaskConflict('Internal accounting reopens a settled external debt')
            if name == 'receipts' and prior.status in {'verified_partial', 'verified_final'} and row.status != prior.status:
                raise TaskConflict('Internal accounting rewrites a verified cash receipt')
            if name == 'executions' and not {ref.key()[:2] for ref in prior.receipt_refs} <= {ref.key()[:2] for ref in row.receipt_refs}:
                raise TaskConflict('Internal accounting drops actual payment execution history')
    ledgers = {}
    for key, claim in after['claims'].items():
        prior = before['claims'].get(key)
        changed = prior is not None and (prior.actual_received != claim.actual_received
            or prior.recognized_event_ids != claim.recognized_event_ids)
        if changed:
            ledger = _verify_engineer_billing_receipt_ledger(after, claim, context)
            if ledger is None:
                raise TaskConflict('Internal accounting lacks actual native receipt history for changed cash')
            ledgers[str(key)] = ledger
    return {name: {group: {str(key): row.model_dump(mode='json') for key, row in rows.items()}
        for group, rows in version.items()} for name, version in (('original', before), ('current', after))} | {'receipt_ledgers': ledgers}


def check_engineer_billing_internal_cost(check, selected, validate_relation, *, terminal=False, policy=ENGINEER_POLICY):
    source = check.source['identity']
    if (source['action_id'] != policy.action_id or source['role'] != policy.role or source['purpose'] != 'action'
            or check.condition.condition_code != policy.internal_code or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('Engagement',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, policy.reading_type) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Internal cost recovery requires the actual original private engagement wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != policy.action_id
            or context.scope != original.scope or context.execution_mode != 'llm' or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original.business_time.clock_ref or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Internal cost recovery substitutes original snapshot, scope, time or independent current read authority')
    reading.check_method_context(context, policy.action_id)
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != policy.action_id or contract.role != policy.role:
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

    old = read(original_input.engagement_ref, policy.source_types['Engagement'], original.business_time)
    history = read(selected.history_ref, policy.source_types['Engagement'], context.business_time)
    if (old.ref != check.condition.object_refs[0] or history.ref.key()[:2] != old.ref.key()[:2]
            or old.organization_id != source['organization_id'] or original_input.scope != original.scope
            or old.ref == history.ref and old != history):
        raise TaskConflict('Internal cost recovery substitutes its original physical or immutable engagement')
    for field in ('scope', 'organization_id', 'client_id', 'payer_id', 'payer_organization_id', 'relation'):
        if getattr(old, field) != getattr(history, field):
            raise TaskConflict('Internal cost recovery converts original parties or internal work to external fees')
    if (old.contract_ref.key()[:2] != history.contract_ref.key()[:2]
            or not set(physical(original_input.work_fact_refs)) <= set(physical(old.work_fact_refs))
            or not set(physical(old.work_fact_refs)) <= set(physical(history.work_fact_refs))
            or set(physical(old.claim_refs)) != set(physical(history.claim_refs))
            or set(physical(old.advance_credit_refs)) != set(physical(history.advance_credit_refs))
            or not set(physical(old.payable_obligation_refs)) <= set(physical(history.payable_obligation_refs))):
        raise TaskConflict('Internal cost recovery replaces original contract, loses work or introduces fee claims')
    financial_history = _engineer_internal_financial_history(old, history, original, context, read, policy=policy)
    original_gate = policy.handle_fees(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != policy.internal_code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Internal cost wait differs from the actual original no-self-fee processor gate')
    # Accounting is an independently authorized native service. A10 never resumes self billing.
    if not terminal:
        return 'waiting', None
    if history.coverage != 'complete' or history.as_of != context.business_time or history.cost_accounting_ref is None:
        return 'waiting', None
    accounting = read(history.cost_accounting_ref, policy.source_types['WorkCostAccounting'], context.business_time)
    if (accounting.run_id != source['run_id'] or accounting.organization_id != source['organization_id']
            or accounting.engagement_ref.key()[:2] != history.ref.key()[:2] or accounting.as_of != context.business_time):
        raise TaskConflict('Internal accounting query changes original run, organization, engagement or actual query time')
    if not accounting.effective_window.contains(context.business_time):
        return 'unavailable', None
    if accounting.status != 'posted' or accounting.coverage != 'complete' or not accounting.lines:
        return 'waiting', None
    line_refs = physical([line.work_fact_ref for line in accounting.lines])
    if line_refs != physical(history.work_fact_refs):
        return 'waiting', None
    if len({line.posting_key for line in accounting.lines}) != len(accounting.lines):
        raise TaskConflict('Internal accounting repeats a native posting under different work slices')
    facts, totals, investments = [], {}, set()
    original_facts = physical(old.work_fact_refs)
    for line in accounting.lines:
        fact = read(line.work_fact_ref, policy.source_types['WorkFact'], context.business_time)
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
            before = read(original_ref, policy.source_types['WorkFact'], original.business_time)
            if (before.ref == fact.ref and before != fact
                    or _physical_values(before.model_dump(mode='json', exclude=_METADATA))
                    != _physical_values(fact.model_dump(mode='json', exclude=_METADATA))):
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
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version=f'{policy.role.lower()}-billing-internal-cost-resolution.v1', condition_code=policy.internal_code,
        disposition='actual_internal_cost_accounting_archive', history=history.model_dump(mode='json'),
        accounting=accounting.model_dump(mode='json'), financial_history=financial_history, original_engagement=old.model_dump(mode='json'), facts=facts,
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=policy.internal_code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Internal cost archive lacks independently authenticated native accounting service/authority and no-fee effects')
    return 'ready', resolution


def engineer_original_billing_profile(read_current, validate_relation, condition_code=CONDITIONS_CODE):
    if condition_code not in _REF_KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Engineering billing recovery requires actual guarded sources and native authority validation')

    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Engineering billing profile substitutes its original condition wait')
        selected = read_current(deepcopy(check))
        try:
            checker = check_engineer_billing_internal_cost if condition_code == INTERNAL_CODE else _check_engineer_billing_history
            return checker(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A10', condition_code, '1', frozenset({'dependency_change'}), evaluate)
