"""Wake original debt allocation waits from actual complete receipt/debt sources."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_debt_objects import (
    BankDebtArrangementView, BankDebtProfileView, BankDebtTermsView, BankDebtAllocationRuleView,
    BankDebtComponentView, BankDebtReceiptView, BankDebtPostingView, BankDebtExecutionView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.roles.bank_debt import account_debt
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


DEBT_CODE = 'verified_receipt_or_original_due_component_changes'
_LINKS = {'debt_components': 'debt_component_refs', 'verified_receipts': 'receipt_refs',
    'prior_posting_refs': 'posting_refs', 'execution_refs': 'execution_refs'}


@dataclass(frozen=True)
class BankDebtConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_context: ActionContext
    original_action_input: object
    action_input: object


def bank_original_debt_receipt_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Debt recovery requires actual guarded readings and independent source authentication')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'BANK-A09' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != DEBT_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('FinanceArrangement',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Debt recovery substitutes original task, recipient or allocation wait')
        selected = read_current(deepcopy(check))
        if not isinstance(selected, BankDebtConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Debt recovery requires an exact typed original/current reading')
        context, reading, original_context = selected.context, selected.reading, selected.original_context
        old_input, action_input = selected.original_action_input, selected.action_input
        if (not isinstance(context, ActionContext) or not isinstance(original_context, ActionContext)
                or task_digest(old_input.model_dump(mode='json')) != source['input_sha256']
                or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                or original_context.operation_id != source['request_id']
                or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A09'
                or context.scope != original_context.scope or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset
                or context.operation_id == source['request_id'] or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                or tuple(check.condition.object_refs) != (old_input.arrangement_ref,)
                or action_input.arrangement_ref.key()[:2] != old_input.arrangement_ref.key()[:2]):
            raise TaskConflict('Debt recovery replaces original snapshot, facility, scope or fresh invocation')
        reading.check_method_context(context, 'BANK-A09')
        try:
            def read(ref, schema, at=None):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Debt recovery lacks exact typed original/current facility sources')
                point = context.business_time if at is None else at
                if row.available_at.clock_ref != point.clock_ref or row.available_at.offset > point.offset:
                    raise TaskConflict('Debt recovery introduces history unavailable at its original/current read point')
                return row

            old = read(old_input.arrangement_ref, BankDebtArrangementView, at=original_context.business_time)
            current = read(action_input.arrangement_ref, BankDebtArrangementView)
            profiles = [read(value.calculation_profile_ref, BankDebtProfileView, at=point)
                for value, point in ((old_input, original_context.business_time), (action_input, context.business_time))]
            if (old.lender_id != source['organization_id'] or current.lender_id != old.lender_id
                    or current.borrower_id != old.borrower_id or current.currency != old.currency or current.scope != old.scope
                    or old.coverage != 'complete' or old.as_of != original_context.business_time
                    or any(profile.choice != 'allocate_receipt' for profile in profiles)
                    or profiles[0].arrangement_ref != old.ref or profiles[1].arrangement_ref != current.ref
                    or current.terms_ref.key()[:2] != old.terms_ref.key()[:2]):
                raise TaskConflict('Debt recovery changes original lender/borrower/terms or allocation branch')
            for value, arrangement in ((old_input, old), (action_input, current)):
                for field, saved in _LINKS.items():
                    refs = getattr(value, field)
                    if {ref.key() for ref in refs} != {ref.key() for ref in getattr(arrangement, saved)}:
                        raise TaskConflict('Debt recovery omits complete original/current accounting sources')
                    if len({ref.key()[:2] for ref in refs}) != len(refs):
                        raise TaskConflict('Debt recovery repeats a physical accounting source')
            for field in _LINKS:
                if not {ref.key()[:2] for ref in getattr(old_input, field)} <= {ref.key()[:2] for ref in getattr(action_input, field)}:
                    raise TaskConflict('Debt recovery drops original debt, receipts, postings or executions')
            # Updated observations may add records and advance command states;
            # original verified cash events and append-only postings stay intact.
            history = (
                ('debt_components', BankDebtComponentView, ('debt_id', 'lender_id', 'borrower_id', 'kind', 'scope')),
                ('verified_receipts', BankDebtReceiptView, ('lender_id', 'borrower_id', 'command_id', 'business_key',
                    'event_id', 'kind', 'amount', 'effective_at', 'scope')),
                ('prior_posting_refs', BankDebtPostingView, ('business_key', 'kind', 'amount', 'accrual_window',
                    'receipt_event_id', 'scope')),
                ('execution_refs', BankDebtExecutionView, ('lender_id', 'borrower_id', 'command_id', 'business_key', 'scope')),
            )
            for field, schema, immutable in history:
                after_rows = {ref.key()[:2]: read(ref, schema) for ref in getattr(action_input, field)}
                for ref in getattr(old_input, field):
                    before = read(ref, schema, at=original_context.business_time)
                    after = after_rows[ref.key()[:2]]
                    if (before.arrangement_ref != old.ref or after.arrangement_ref != current.ref
                            or any(getattr(before, name) != getattr(after, name) for name in immutable)):
                        raise TaskConflict('Debt recovery rewrites original debt, verified cash, posting or command identity')
                    if field == 'verified_receipts':
                        before_effects = {effect.debt_component_ref.key()[:2]: effect.amount for effect in before.principal_effects}
                        after_effects = {effect.debt_component_ref.key()[:2]: effect.amount for effect in after.principal_effects}
                        if (before.execution_ref.key()[:2] != after.execution_ref.key()[:2]
                                or len(before_effects) != len(before.principal_effects)
                                or len(after_effects) != len(after.principal_effects) or before_effects != after_effects):
                            raise TaskConflict('Debt recovery rewrites original receipt execution or effective principal effects')
                    elif field == 'prior_posting_refs':
                        before_roots = {item.key()[:2] for item in before.original_posting_refs}
                        after_roots = {item.key()[:2] for item in after.original_posting_refs}
                        if (before.debt_component_ref.key()[:2] != after.debt_component_ref.key()[:2]
                                or len(before_roots) != len(before.original_posting_refs)
                                or len(after_roots) != len(after.original_posting_refs) or before_roots != after_roots):
                            raise TaskConflict('Debt recovery rewrites original posting component or append-only correction roots')
                    elif field == 'execution_refs':
                        before_receipts = {item.key()[:2] for item in before.receipt_refs}
                        after_receipts = {item.key()[:2] for item in after.receipt_refs}
                        if (len(before_receipts) != len(before.receipt_refs)
                                or len(after_receipts) != len(after.receipt_refs) or not before_receipts <= after_receipts
                                or before.status in {'succeeded', 'failed'} and before.status != after.status):
                            raise TaskConflict('Debt recovery drops command receipts or rewrites an original terminal outcome')
            terms = [read(arrangement.terms_ref, BankDebtTermsView, at=point)
                for arrangement, point in ((old, original_context.business_time), (current, context.business_time))]
            for field in ('rate_mode', 'fixed_annual_rate', 'commitment_fee_annual_rate', 'repayment_effective_rule',
                    'minor_places', 'rounding'):
                if getattr(terms[0], field) != getattr(terms[1], field):
                    raise TaskConflict('Debt recovery silently reprices original contractual debt')
            if terms[0].allocation_rule_ref.key()[:2] != terms[1].allocation_rule_ref.key()[:2]:
                raise TaskConflict('Debt recovery substitutes the original contractual allocation rule')
            rules = [read(row.allocation_rule_ref, BankDebtAllocationRuleView, at=point)
                for row, point in zip(terms, (original_context.business_time, context.business_time))]
            if any(getattr(rules[0], field) != getattr(rules[1], field)
                    for field in ('priority', 'allow_not_due', 'excess_treatment')):
                raise TaskConflict('Debt recovery changes original contractual receipt allocation priority')
            for field in ('permitted_reset_refs', 'permitted_calendar_refs'):
                if not {ref.key()[:2] for ref in getattr(terms[0], field)} <= {ref.key()[:2] for ref in getattr(terms[1], field)}:
                    raise TaskConflict('Debt recovery drops original contractual rate/calendar sources')
            for ref in (*walk_references(old_input), *walk_references(action_input)):
                reading.resolve(ref)
            # The existing deterministic processor calculates a proposal only.
            # It checks verified execution-linked receipts, posting deduplication,
            # due balances and contractual priority; it has no ledger/cash writer.
            result = account_debt(context, action_input, reading)
            if result['kind'] != 'completed' or result['payload']['choice'] != 'allocate_receipt':
                return 'unavailable' if result['kind'] == 'unsupported' else 'waiting'
            allocations = result['payload']['allocations']
            if not allocations:
                return 'waiting'
            observed = []
            for allocation in allocations:
                receipt_ref = Reference.model_validate(allocation['receipt_ref']) if isinstance(allocation['receipt_ref'], dict) else allocation['receipt_ref']
                receipt = reading.resolve(receipt_ref)
                for evidence_ref in (*receipt.evidence_refs, receipt.amount.basis_ref):
                    evidence = reading.resolve(evidence_ref)
                    if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                        raise TaskConflict('Debt recovery requires actual observed receipt evidence')
                    observed.append(evidence.model_dump(mode='json'))
            if validate_relation(source_identity=deepcopy(source), condition_code=DEBT_CODE,
                    original_context=original_context.model_copy(deep=True), original_action_input=old_input.model_dump(mode='json'),
                    context=context.model_copy(deep=True), action_input=action_input.model_dump(mode='json'),
                    allocations=deepcopy(allocations), receipt_evidence=observed, reading=reading) is not True:
                raise TaskConflict('Debt recovery lacks native original receipt/posting/debt history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('BANK-A09', DEBT_CODE, '2', frozenset({'dependency_change'}), evaluate)
