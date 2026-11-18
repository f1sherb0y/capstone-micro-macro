"""BANK-A09: deterministic accrual and receipt allocation proposals, never cash edits."""
import hashlib
import json
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.bank_debt_objects import (
    BankDebtArrangementView, BankDebtTermsView, BankDebtComponentView, BankDebtProfileView,
    BankDebtReceiptView, BankDebtPostingView, BankDebtExecutionView, BankDebtEvidenceView,
    BankDebtAllocationRuleView, BankDebtResetView, BankDebtCalendarView,
    BankDebtCommitmentView, BankDebtCommitmentChangeView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.bank_debt import DEBT_METHOD, calculate_debt_accrual
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def account_debt(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('bank-debt-clock-alignment')

    def evidence(refs, historical=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('bank-debt-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_debt_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'bank-debt-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Debt calculation changes original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_debt_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_debt_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def number(value, signed=False):
        if value.currency != arrangement.currency: _unsupported('bank-debt-currency-conversion')
        evidence([value.basis_ref], True)
        result = decimal_fraction(value.value)
        if result < 0 and not signed: raise ValueError('Actual debt/cash amounts cannot be negative')
        return result

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def original_event(receipt):
        return receipt.model_dump(mode='json', exclude={'ref', 'evidence_refs', 'available_at', 'effective_window', 'verified_at'})

    try:
        arrangement = read(action_input.arrangement_ref, BankDebtArrangementView)
        profile = read(action_input.calculation_profile_ref, BankDebtProfileView)
        if arrangement.lender_id != lender or not same(profile.arrangement_ref, arrangement.ref):
            raise ValueError('Debt calculation belongs to another bank/facility')
        grant = read(profile.authority_ref, Authorization); function = read(context.function_ref, RoleAssignment)
        if (grant.organization_id != lender or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or function.role != 'Bank' or 'BANK-A09' not in grant.action_ids
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise ValueError('Debt calculation lacks independent original bank actor/action/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_bank_debt_authority')
        evidence([*grant.basis_refs, *function.basis_refs])
        clock(arrangement.as_of)
        if arrangement.coverage != 'complete' or arrangement.as_of != now: _needs('complete_current_original_debt_and_receipt_history')
        for field, saved in (('debt_components', 'debt_component_refs'), ('verified_receipts', 'receipt_refs'),
                             ('prior_posting_refs', 'posting_refs'), ('execution_refs', 'execution_refs')):
            if keys(getattr(action_input, field)) != keys(getattr(arrangement, saved)):
                _needs(f'all_original_debt_{field}', getattr(arrangement, saved))
        executions = {}
        for ref in action_input.execution_refs:
            row = read(ref, BankDebtExecutionView, True)
            if (not same(row.arrangement_ref, arrangement.ref) or row.lender_id != lender
                    or row.borrower_id != arrangement.borrower_id): raise ValueError('Debt execution changes original parties/facility')
            executions[ref.key()] = row
        if len({row.command_id for row in executions.values()}) != len(executions) or len({row.business_key for row in executions.values()}) != len(executions):
            raise ValueError('Debt execution repeats an original payment command/business key')
        if profile.choice == 'reconcile':
            if not action_input.execution_refs: _needs('original_payment_executions_for_debt_reconciliation')
            return completed('reconcile', execution_refs=action_input.execution_refs)
        terms = read(arrangement.terms_ref, BankDebtTermsView, True)
        if not same(terms.arrangement_ref, arrangement.ref): raise ValueError('Debt terms belong to another original facility')
        components = {}
        for ref in action_input.debt_components:
            component = read(ref, BankDebtComponentView, True)
            if (not same(component.arrangement_ref, arrangement.ref) or component.lender_id != lender
                    or component.borrower_id != arrangement.borrower_id): raise ValueError('Debt component changes original parties/facility')
            clock(component.opening_at); clock(component.due_at)
            number(component.opening_balance); number(component.actual_due); number(component.cash_paid)
            if component.kind == 'principal' and number(component.cash_paid) > number(component.actual_due):
                raise ValueError('Principal paid cannot exceed original recorded principal')
            components[ref.key()] = component
        receipts, events = {}, {}
        for ref in action_input.verified_receipts:
            receipt = read(ref, BankDebtReceiptView, True)
            execution = executions.get(receipt.execution_ref.key())
            if (execution is None or not same(receipt.arrangement_ref, arrangement.ref) or receipt.lender_id != lender
                    or receipt.borrower_id != arrangement.borrower_id or receipt.command_id != execution.command_id
                    or receipt.business_key != execution.business_key or ref.key() not in keys(execution.receipt_refs)):
                raise ValueError('Verified receipt changes original execution/command/business/parties')
            clock(receipt.effective_at); clock(receipt.verified_at)
            if (receipt.effective_at.offset > now.offset or receipt.verified_at.offset > min(now.offset, receipt.available_at.offset)
                    or receipt.effective_at.offset > receipt.verified_at.offset): _needs('verified_original_product_receipt_effective_time')
            if number(receipt.amount) <= 0: raise ValueError('Verified actual receipt must be positive')
            keys([effect.debt_component_ref for effect in receipt.principal_effects])
            for effect in receipt.principal_effects:
                component = components.get(effect.debt_component_ref.key())
                if component is None or component.kind != 'principal': raise ValueError('Receipt principal effect changes original debt component')
                number(effect.amount)
            if sum((number(effect.amount) for effect in receipt.principal_effects), Fraction()) > number(receipt.amount):
                raise ValueError('Receipt principal effects exceed original verified amount')
            previous = events.get(receipt.event_id)
            if previous is not None and original_event(previous) != original_event(receipt):
                raise ValueError('Duplicate verified receipt event changes original content')
            events.setdefault(receipt.event_id, receipt); receipts[ref.key()] = receipt
        postings = {}
        for ref in action_input.prior_posting_refs:
            posting = read(ref, BankDebtPostingView, True)
            if not same(posting.arrangement_ref, arrangement.ref) or posting.debt_component_ref.key() not in components:
                raise ValueError('Prior posting changes original arrangement/debt component')
            number(posting.amount, signed=posting.kind == 'correction')
            if posting.kind == 'allocation' and (posting.receipt_event_id not in events or posting.accrual_window is not None):
                raise ValueError('Receipt allocation posting lacks its original verified cash event')
            if posting.kind != 'allocation' and posting.accrual_window is None:
                raise ValueError('Accrual posting needs its original interval')
            postings[ref.key()] = posting
        if len({row.business_key for row in postings.values()}) != len(postings):
            raise ValueError('Debt ledger repeats an original posting business key')
        for posting in postings.values():
            if posting.kind == 'correction':
                if not posting.original_posting_refs: _needs('original_accrual_posts_for_append_only_correction')
                keys(posting.original_posting_refs)
                for ref in posting.original_posting_refs:
                    original = postings.get(ref.key())
                    if (original is None or original.kind != 'accrual' or not same(original.debt_component_ref, posting.debt_component_ref)
                            or original.accrual_window != posting.accrual_window):
                        raise ValueError('Accrual correction changes its original posting/component/period')
        allocated_by_event, allocated_by_component = {}, {}
        for posting in postings.values():
            if posting.kind != 'allocation': continue
            event = events[posting.receipt_event_id]
            if event.kind != 'repayment': raise ValueError('Draw receipts cannot clear debt as repayments')
            amount = number(posting.amount)
            allocated_by_event[event.event_id] = allocated_by_event.get(event.event_id, Fraction()) + amount
            key = posting.debt_component_ref.key()
            allocated_by_component[key] = allocated_by_component.get(key, Fraction()) + amount
        if any(value > number(events[key].amount) for key, value in allocated_by_event.items()):
            raise ValueError('Existing allocations exceed original verified actual receipts')
        if any(value > number(components[key].cash_paid) for key, value in allocated_by_component.items()):
            _needs('component_cash_paid_including_original_allocation_posts')
        if profile.choice == 'allocate_receipt':
            rule = read(terms.allocation_rule_ref, BankDebtAllocationRuleView)
            if not same(rule.arrangement_ref, arrangement.ref) or len(set(rule.priority)) != len(rule.priority):
                raise ValueError('Settlement allocation rule changes arrangement or repeats a priority')
            if not {component.kind for component in components.values()} <= set(rule.priority):
                _needs('complete_contractual_component_allocation_priority')
            remaining = {key: max(Fraction(), number(row.actual_due) - number(row.cash_paid)) for key, row in components.items()}
            ordered = sorted(components.values(), key=lambda row: (rule.priority.index(row.kind), row.due_at.offset, row.ref.key()))
            allocations = []
            for event in sorted(events.values(), key=lambda row: (row.effective_at.offset, row.event_id)):
                if event.kind != 'repayment': continue
                available = number(event.amount) - allocated_by_event.get(event.event_id, Fraction())
                principal_allocated = {effect.debt_component_ref.key(): Fraction() for effect in event.principal_effects}
                for posting in postings.values():
                    if posting.kind == 'allocation' and posting.receipt_event_id == event.event_id:
                        key = posting.debt_component_ref.key()
                        if components[key].kind == 'principal':
                            principal_allocated[key] = principal_allocated.get(key, Fraction()) + number(posting.amount)
                for component in ordered:
                    if not rule.allow_not_due and component.due_at.offset > now.offset: continue
                    key = component.ref.key(); paid = min(available, remaining[key])
                    if paid <= 0: continue
                    allocations.append({'debt_component_ref': component.ref, 'receipt_ref': event.ref,
                        'allocated': {'value': exact_decimal(paid), 'currency': arrangement.currency, 'basis_ref': event.amount.basis_ref},
                        'allocation_rule_ref': rule.ref})
                    available -= paid; remaining[key] -= paid
                    if component.kind == 'principal': principal_allocated[key] = principal_allocated.get(key, Fraction()) + paid
                expected = {effect.debt_component_ref.key(): number(effect.amount) for effect in event.principal_effects}
                if {key: amount for key, amount in principal_allocated.items() if amount} != {key: amount for key, amount in expected.items() if amount}:
                    _needs('verified_principal_effects_consistent_with_original_contractual_receipt_allocation')
            if not allocations:
                reading.recheck(); return {'kind': 'deferred', 'reason_code': 'no_new_allocatable_verified_receipt',
                    'resume_condition': {'trigger': 'dependency_change', 'object_refs': [arrangement.ref],
                        'earliest_time': None, 'condition_code': 'verified_receipt_or_original_due_component_changes'}}
            return completed('allocate_receipt', allocations=allocations)
        if profile.method_ref is None or profile.method_ref.key() != DEBT_METHOD.key(): _unsupported('bank-debt-original-rate-calendar-method')
        data = profile.accrual_input
        if data is None: _needs('complete_original_debt_accrual_inputs')
        window = reading.resolve(action_input.accrual_window_ref)
        if data.window != window or data.window.end.offset > now.offset or data.currency != arrangement.currency:
            raise ValueError('Debt accrual changes original input window/currency or includes future accrual')
        clock(data.window.start)
        if (data.minor_places != terms.minor_places or data.rounding != terms.rounding):
            raise ValueError('Debt accrual changes original product rounding')
        required_sources = {arrangement.terms_ref.key(), action_input.accrual_window_ref.key()}
        prior_input = {row.posting_ref.key(): row for row in data.prior_postings}
        accrual_posts = {key: row for key, row in postings.items() if row.kind != 'allocation'}
        if set(prior_input) != set(accrual_posts): _needs('all_original_accrual_and_correction_posts_for_deterministic_difference')
        for key, item in prior_input.items():
            original = accrual_posts[key]
            if (item.business_key != original.business_key or item.debt_component_ref.key() != original.debt_component_ref.key()
                    or item.kind != original.kind or item.window != original.accrual_window or item.amount != original.amount):
                raise ValueError('Deterministic debt difference changes an original posting')
            required_sources.add(key)
        for line in data.lines:
            target = components.get(line.debt_component_ref.key())
            if target is None or target.kind not in {'interest', 'fee', 'commitment_fee'}:
                raise ValueError('Interest accrual cannot manufacture or capitalize principal')
            if (target.kind == 'commitment_fee') != (line.base_kind == 'undrawn_commitment'):
                raise ValueError('Commitment fee must use the original separate undrawn commitment balance')
            if target.balance_source_ref is None or not same(target.balance_source_ref, line.balance_source_ref):
                raise ValueError('Accrual changes its original actual balance source')
            required_sources.update((target.ref.key(), line.balance_source_ref.key()))
            if line.base_kind == 'actual_principal':
                source = components.get(line.balance_source_ref.key())
                if source is None or source.kind != 'principal' or source.debt_id != target.debt_id:
                    raise ValueError('Debt interest uses another debt or an undrawn/interest balance')
                opening = source.opening_balance
            else:
                source = read(line.balance_source_ref, BankDebtCommitmentView, True)
                if not same(source.arrangement_ref, arrangement.ref): raise ValueError('Commitment fee changes original facility')
                clock(source.as_of)
                if (source.coverage != 'complete' or source.as_of.offset > min(now.offset, source.available_at.offset)
                        or source.as_of.offset < data.window.end.offset):
                    _needs('complete_original_commitment_changes_through_accrual_window', [source.ref])
                keys(source.change_refs)
                changes = {}
                for ref in source.change_refs:
                    change = read(ref, BankDebtCommitmentChangeView, True); clock(change.effective_at)
                    if (not same(change.commitment_ref, source.ref)
                            or not source.opening_at.offset < change.effective_at.offset <= source.as_of.offset):
                        raise ValueError('Commitment change leaves its original opening balance or declared observation interval')
                    number(change.before); number(change.after)
                    changes[ref.key()] = change
                opening = source.opening_undrawn
            if source.opening_at != data.window.start: _needs('original_actual_balance_at_accrual_window_start')
            balance = number(opening)
            used_events = set()
            for index, segment in enumerate(line.balances):
                event_keys = keys(segment.effective_event_refs); required_sources.update(event_keys)
                if index == 0:
                    if event_keys != {source.ref.key()}: raise ValueError('Opening accrual balance lacks its original source component')
                elif line.base_kind == 'actual_principal':
                    for event_key in event_keys:
                        receipt = receipts.get(event_key)
                        if receipt is None or receipt.effective_at != segment.window.start: _needs('verified_receipt_at_original_principal_effective_boundary')
                        if receipt.event_id in used_events: raise ValueError('Accrual applies one receipt principal effect twice')
                        used_events.add(receipt.event_id)
                        effect = sum((number(row.amount) for row in receipt.principal_effects if same(row.debt_component_ref, source.ref)), Fraction())
                        if not effect: raise ValueError('Balance change lacks original verified principal effect')
                        balance += effect if receipt.kind == 'draw' else -effect
                else:
                    for event_ref in segment.effective_event_refs:
                        change = changes.get(event_ref.key())
                        if (change is None or change.effective_at != segment.window.start
                                or number(change.before) != balance or change.committed_basis_ref.key() not in keys(profile.basis_refs)):
                            raise ValueError('Undrawn commitment change lacks original committed before/after basis')
                        if change.ref.key() in used_events: raise ValueError('Accrual applies one original commitment change twice')
                        used_events.add(change.ref.key())
                        balance = number(change.after)
                if balance < 0 or number(segment.balance) != balance: raise ValueError('Accrual balance differs from actual effective cash history')
            if line.base_kind == 'actual_principal':
                relevant_events = {row.event_id for row in events.values() if data.window.start.offset < row.effective_at.offset < data.window.end.offset
                                   and any(same(effect.debt_component_ref, source.ref) and number(effect.amount) for effect in row.principal_effects)}
                if relevant_events != used_events: _needs('all_original_verified_effective_principal_changes_for_accrual')
            else:
                relevant_changes = {key for key, change in changes.items()
                    if data.window.start.offset < change.effective_at.offset < data.window.end.offset}
                if relevant_changes != used_events:
                    _needs('all_original_effective_commitment_changes_for_accrual',
                           [changes[key].ref for key in changes if key in relevant_changes - used_events])
            for rate in line.rates:
                evidence([rate.basis_ref], True)
                if line.base_kind == 'undrawn_commitment':
                    if (line.rate_mode != 'fixed' or terms.commitment_fee_annual_rate is None
                            or decimal_fraction(rate.annual_rate) != decimal_fraction(terms.commitment_fee_annual_rate)):
                        _unsupported('bank-debt-original-commitment-fee-rate')
                elif line.rate_mode != terms.rate_mode: raise ValueError('Debt accrual changes original fixed/floating product mechanism')
                elif terms.rate_mode == 'fixed':
                    if terms.fixed_annual_rate is None: _unsupported('bank-debt-fixed-rate-missing')
                    if decimal_fraction(rate.annual_rate) != decimal_fraction(terms.fixed_annual_rate): raise ValueError('Fixed debt rate changes original contract')
                else:
                    if rate.reset_ref is None or rate.reset_ref.key() not in keys(terms.permitted_reset_refs): _needs('original_contractual_floating_rate_reset')
                    reset = read(rate.reset_ref, BankDebtResetView, True); clock(reset.reset_at)
                    if (not same(reset.arrangement_ref, arrangement.ref) or not same(reset.terms_ref, terms.ref)
                            or reset.rate_window != rate.window or reset.reset_at != rate.window.start
                            or reset.rate_basis_ref.key() != rate.basis_ref.key()
                            or decimal_fraction(reset.annual_rate) != decimal_fraction(rate.annual_rate)):
                        raise ValueError('Floating rate differs from original product reset/version/basis')
                    required_sources.add(reset.ref.key())
            for calendar in line.calendars:
                if calendar.calendar_ref.key() not in keys(terms.permitted_calendar_refs): _unsupported('bank-debt-original-calendar-method')
                saved = read(calendar.calendar_ref, BankDebtCalendarView, True)
                if (not same(saved.arrangement_ref, arrangement.ref) or saved.calendar_window != calendar.window
                        or saved.ticks_per_year != calendar.ticks_per_year or saved.calendar_basis_ref.key() != calendar.basis_ref.key()):
                    raise ValueError('Debt calendar differs from original declared clock/year fraction')
                evidence([calendar.basis_ref], True); required_sources.add(saved.ref.key())
        if not required_sources <= keys(data.source_refs): _needs('all_original_accrual_method_sources')
        covered, committed = set(), {}
        keys(profile.basis_refs)
        for ref in profile.basis_refs:
            item = read(ref, BankDebtEvidenceView, True)
            if not same(item.arrangement_ref, arrangement.ref): raise ValueError('Committed debt evidence belongs to another original facility')
            original = reading.resolve(item.original_record_ref)
            raw = json.dumps(original.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            if hashlib.sha256(raw.encode()).hexdigest() != item.content_sha256: raise ValueError('Committed debt evidence changes original record content')
            evidence(item.original_evidence_refs, True)
            covered.add(item.original_record_ref.key()); committed[ref.key()] = item
        if not (keys(data.source_refs) | keys(action_input.prior_posting_refs)) <= covered:
            _needs('committed_original_accrual_and_prior_posting_basis')
        report = calculate_debt_accrual(data)
        if profile.saved_report is not None and report != profile.saved_report:
            raise ValueError('Saved debt accrual differs from deterministic original effective-time calculation')
        has_prior, negative_delta = False, False
        for result in report.lines:
            prior = Fraction()
            for posting in postings.values():
                if posting.kind == 'allocation' or not same(posting.debt_component_ref, result.debt_component_ref): continue
                if posting.accrual_window != data.window:
                    clock(posting.accrual_window.start)
                    if max(posting.accrual_window.start.offset, data.window.start.offset) < min(posting.accrual_window.end.offset, data.window.end.offset):
                        _needs('original_posting_period_partition_for_accrual_correction')
                    continue
                has_prior = True; prior += number(posting.amount, signed=posting.kind == 'correction')
            if prior < 0: raise ValueError('Original accrual plus corrections cannot have negative total')
            delta = decimal_fraction(result.accrued) - prior
            negative_delta |= delta < 0
        if profile.choice == 'calculate_due' and (has_prior or negative_delta):
            _needs('correct_accrual_choice_for_original_previously_posted_period')
        if profile.choice == 'correct_accrual' and not has_prior: _needs('original_accrual_posting_for_correction')
        return completed(profile.choice, calculation_profile_ref=profile.ref, basis_refs=profile.basis_refs)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
