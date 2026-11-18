"""BANK-A07 execution proposals and identity-preserving receipt reconciliation."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.bank_execution_objects import (
    BankExecutionArrangementView, BankExecutionProfileView, BankExecutionApprovalView, BankExecutionPathView,
    BankExecutionAccountView, BankExecutionReservationView, BankExecutionFeeRuleView, BankExecutionObligationView,
    BankExecutionSavedView, BankExecutionReceiptView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers

AMOUNT_FIELDS = ('beneficiary_cash', 'principal', 'withheld_fee', 'capitalized_fee', 'separate_fee_cash', 'bank_debit')


def handle_execution(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('bank-execution-clock-alignment')

    def evidence(refs, historical=False, at=None):
        point = now if at is None else at
        clock(point)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('bank-execution-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if (at is not None or not historical) and not row.effective_window.contains(point):
                    _needs('current_original_funding_execution_evidence' if at is None
                           else 'original_funding_execution_evidence_valid_when_approved', [ref])

    def read(ref, schema, historical=False, covered=True, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'bank-execution-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Funding execution input changes original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_funding_execution_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_funding_execution_input', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > min(now.offset, row.available_at.offset):
                _needs('received_original_draw_approval_after_actual_decision', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical, at=point); return row

    def authorize(ref, actor, function_ref, action, historical=False, at=None, *, target_scope=None):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.organization_id != lender or grant.actor_id != actor or grant.function_ref != function_ref
                or function.function_ref != function_ref or action not in grant.action_ids or function.role != 'Bank'
                or not any(scope_covers(scope, target_scope or context.scope) for scope in grant.scopes)):
            raise ValueError('Funding execution lacks independent original bank actor/action/scope authority')
        point = now if at is None else at
        clock(grant.validity.start); clock(point)
        if not grant.validity.contains(point): _needs('valid_original_funding_execution_authority', [ref])
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], historical, at=at)
            else:
                reading.resolve(basis_ref)

    def money(value, currency, historical=False, *, at=None):
        if value.currency != currency: _unsupported('bank-execution-currency-conversion')
        number = decimal_fraction(value.value)
        if number < 0: raise ValueError('Original execution amount cannot be negative')
        evidence([value.basis_ref], historical, at=at); return number

    def amounts(row, currency, historical=False, *, at=None):
        numbers = {field: money(getattr(row, field), currency, historical, at=at) for field in AMOUNT_FIELDS}
        if (numbers['principal'] != numbers['beneficiary_cash'] + numbers['withheld_fee'] + numbers['capitalized_fee']
                or numbers['bank_debit'] != numbers['beneficiary_cash'] + numbers['separate_fee_cash']):
            raise ValueError('Original execution principal, actual beneficiary cash, fees and bank debit do not reconcile')
        return numbers

    def approval(ref, historical=False):
        row = read(ref, BankExecutionApprovalView, historical, evidence_at_field='approved_at')
        if row.lender_id != lender or row.borrower_id != arrangement.borrower_id or not same(row.arrangement_ref, arrangement.ref):
            raise ValueError('Execution approval changes original lender/borrower/facility')
        if not historical and not same(row.terms_ref, arrangement.terms_ref): raise ValueError('New execution uses another current arrangement terms version')
        authorize(row.approver_authority_ref, row.approver_actor_id, row.approver_function_ref,
                  'BANK-A06', historical, at=row.approved_at, target_scope=row.scope)
        currency = row.amount.currency
        if money(row.amount, currency, historical, at=row.approved_at) <= 0: raise ValueError('Draw approval must be positive')
        if len({line.local_key for line in row.lines}) != len(row.lines): raise ValueError('Approval repeats an original transfer line')
        keys([line.transfer.destination_ref for line in row.lines])
        total = Fraction()
        for line in row.lines:
            figures = amounts(line.amounts, currency, historical, at=row.approved_at)
            if money(line.transfer.requested, currency, historical, at=row.approved_at) != figures['beneficiary_cash'] or figures['principal'] <= 0:
                raise ValueError('Approval transfer cash differs from original actual-recipient amount')
            total += figures['principal']
        if total != decimal_fraction(row.amount.value): raise ValueError('Approval principal differs from its original transfer/fee split')
        return row

    def path(ref, approval_row, historical=False):
        row = read(ref, BankExecutionPathView, historical)
        if row.lender_id != lender or not same(row.arrangement_ref, arrangement.ref) or row.currency != approval_row.amount.currency:
            raise ValueError('Funding path changes original facility/lender/currency')
        if not keys([line.transfer.destination_ref for line in approval_row.lines]) <= keys(row.destination_refs):
            raise ValueError('Funding path does not cover original approved recipients')
        return row

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def reconcile_existing(refs):
        if not refs: _needs('original_payment_executions_for_reconciliation')
        keys(refs); executions = [read(ref, BankExecutionSavedView, True) for ref in refs]
        if len({row.command_id for row in executions}) != len(executions) or len({row.business_key for row in executions}) != len(executions):
            raise ValueError('Execution references repeat an original command/business payment')
        submitted_receipts = keys(action_input.receipt_refs)
        received, cancellable = set(), []
        original_approvals, paid_by_approval = {}, {}
        for execution in executions:
            if execution.lender_id != lender or execution.borrower_id != arrangement.borrower_id or not same(execution.arrangement_ref, arrangement.ref):
                raise ValueError('Historical execution changes original lender/borrower/facility')
            original = approval(execution.approval_ref, True); original_path = path(execution.path_ref, original, True)
            approval_identity = (original.ref.kind, original.ref.id)
            previous = original_approvals.setdefault(approval_identity, original)
            if any(getattr(previous, field) != getattr(original, field) for field in (
                    'lender_id', 'borrower_id', 'arrangement_ref', 'terms_ref', 'batch_key', 'amount', 'lines',
                    'approved_at', 'approver_actor_id', 'approver_function_ref', 'approver_authority_ref', 'scope')):
                raise ValueError('Historical commands change the original approval content across versions')
            if execution.lines != original.lines: raise ValueError('Historical execution changes its saved original approval split')
            if execution.ref.key() not in keys(original.execution_refs): _needs('original_execution_linked_to_saved_approval')
            currency = original.amount.currency
            evidence([execution.dispatch_evidence_ref], True)
            all_receipts = keys(execution.receipt_refs)
            if not all_receipts <= submitted_receipts or execution.receipt_coverage != 'complete':
                _needs('complete_received_original_execution_receipts', execution.receipt_refs)
            expected = {line.local_key: line for line in execution.lines}
            totals = {key: {field: Fraction() for field in AMOUNT_FIELDS} for key in expected}
            events, sequences, unknown_lines = {}, set(), set()
            receipt_unexecuted = None
            receipts = [read(ref, BankExecutionReceiptView, True) for ref in execution.receipt_refs]
            for receipt in sorted(receipts, key=lambda row: row.sequence):
                if (receipt.lender_id != lender or receipt.borrower_id != execution.borrower_id
                        or not same(receipt.execution_ref, execution.ref) or not same(receipt.arrangement_ref, arrangement.ref)
                        or not same(receipt.approval_ref, execution.approval_ref) or not same(receipt.path_ref, execution.path_ref)
                        or receipt.command_id != execution.command_id or receipt.business_key != execution.business_key):
                    raise ValueError('Receipt changes original command, business key, approval or funding path')
                clock(receipt.observed_at)
                if receipt.observed_at.offset > min(now.offset, receipt.available_at.offset): _needs('original_execution_receipt_observed_before_received')
                received.add(receipt.ref.key())
                payload = receipt.model_dump(mode='json', exclude={'ref', 'evidence_refs', 'available_at', 'effective_window', 'observed_at'})
                if receipt.event_id in events:
                    if events[receipt.event_id] != payload: raise ValueError('Duplicate receipt event changes its original content')
                    continue
                events[receipt.event_id] = payload
                if receipt.sequence in sequences: raise ValueError('Distinct receipt events share an ambiguous ledger sequence')
                sequences.add(receipt.sequence)
                if len({line.local_key for line in receipt.lines}) != len(receipt.lines): raise ValueError('Receipt repeats an original transfer line')
                for line in receipt.lines:
                    approved_line = expected.get(line.local_key)
                    if (approved_line is None or line.beneficiary_id != approved_line.transfer.beneficiary_id
                            or not same(line.destination_ref, approved_line.transfer.destination_ref)):
                        raise ValueError('Receipt applies cash to another original beneficiary/destination')
                if receipt.status in {'unknown', 'failed', 'rejected'}:
                    if receipt.status == 'unknown':
                        if receipt.lines:
                            unknown_lines.update(line.local_key for line in receipt.lines)
                        else:
                            unknown_lines.update(expected)
                    if any(any(value for value in amounts(line.amounts, currency, True).values()) for line in receipt.lines):
                        raise ValueError('Unverified/failed receipt cannot claim actual cash or principal')
                    continue
                for line in receipt.lines:
                    approved_line = expected[line.local_key]
                    values = amounts(line.amounts, currency, True)
                    old = totals[line.local_key]
                    if receipt.semantics == 'cumulative':
                        if any(values[field] < old[field] for field in AMOUNT_FIELDS): raise ValueError('Cumulative receipt regresses already observed actual amounts')
                        new = values
                    else: new = {field: old[field] + values[field] for field in AMOUNT_FIELDS}
                    cap = amounts(approved_line.amounts, currency, True)
                    if any(new[field] > cap[field] for field in AMOUNT_FIELDS): raise ValueError('Receipt actual amount exceeds original approved component')
                    totals[line.local_key] = new
                    if receipt.status == 'verified_final': unknown_lines.discard(line.local_key)
                if isinstance(receipt.confirmed_unexecuted_amount, Known):
                    receipt_unexecuted = money(receipt.confirmed_unexecuted_amount.value, currency, True)
                    if receipt_unexecuted > decimal_fraction(original.amount.value) - sum(values['principal'] for values in totals.values()):
                        raise ValueError('Receipt unexecuted amount exceeds original unpaid principal')
            paid = paid_by_approval.setdefault(approval_identity,
                {key: {field: Fraction() for field in AMOUNT_FIELDS} for key in expected})
            for key, values in totals.items():
                cap = amounts(expected[key].amounts, currency, True)
                for field in AMOUNT_FIELDS:
                    paid[key][field] += values[field]
                    if paid[key][field] > cap[field]:
                        raise ValueError('Historical commands together exceed original approved cash/principal/fee allocation')
            if profile.existing_choice != 'cancel_unexecuted':
                continue
            if set(execution.line_dispatch_states) != set(expected): _needs('original_dispatch_state_for_each_transfer_line')
            keys_ = execution.cancel_line_keys
            if len(set(keys_)) != len(keys_) or not set(keys_) <= set(expected): raise ValueError('Cancellation repeats or changes original line identity')
            cancel_amount = Fraction()
            for key in keys_:
                if (execution.line_dispatch_states[key] != 'undispatched' or key in unknown_lines
                        or any(totals[key].values())):
                    _needs('cancel_only_independently_verified_undispatched_unpaid_lines')
                cancel_amount += decimal_fraction(expected[key].amounts.principal.value)
            if keys_:
                actual_unexecuted = _known(execution.confirmed_unexecuted_amount, 'original_confirmed_unexecuted_remainder')
                if money(actual_unexecuted, currency, True) != cancel_amount or not original_path.permits_cancel_undispatched:
                    _needs('original_allowed_exact_undispatched_cancellation_remainder')
                if receipt_unexecuted is not None and cancel_amount > receipt_unexecuted:
                    _needs('cancellation_consistent_with_original_verified_receipt_remainder')
                cancellable.append(execution.ref)
        if received != submitted_receipts: raise ValueError('Receipt input includes observations from another original execution')
        if profile.existing_choice == 'cancel_unexecuted':
            if len(cancellable) != len(executions): _needs('explicit_positive_undispatched_remainder_for_each_cancellation')
            return completed('cancel_unexecuted', execution_refs=cancellable)
        return completed('reconcile', execution_refs=refs)

    try:
        operation = action_input.operation_context
        historical = operation.kind == 'existing'
        arrangement = read(action_input.arrangement_ref, BankExecutionArrangementView, historical)
        if arrangement.lender_id != lender: raise ValueError('Funding execution belongs to another bank')
        profile = read(arrangement.execution_profile_ref, BankExecutionProfileView)
        if profile.organization_id != lender or not same(profile.arrangement_ref, arrangement.ref): raise ValueError('Funding execution policy changes original facility/bank')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, 'BANK-A07')
        if historical: return reconcile_existing(operation.execution_refs)
        approved = approval(operation.draw_approval_ref)
        if approved.status != 'approved' or arrangement.status != 'active': _needs('current_valid_original_draw_approval_for_new_execution')
        if approved.execution_coverage != 'complete': _needs('complete_original_approval_execution_history')
        if keys(operation.prior_execution_refs) != keys(approved.execution_refs): _needs('all_original_prior_execution_identities', approved.execution_refs)
        if operation.prior_execution_refs:
            for ref in operation.prior_execution_refs:
                prior = read(ref, BankExecutionSavedView, True)
                if not same(prior.approval_ref, approved.ref) or not same(prior.arrangement_ref, arrangement.ref):
                    raise ValueError('Prior execution belongs to another original approval')
            reading.recheck(); return {'kind': 'deferred', 'reason_code': 'original_approval_execution_requires_existing_context',
                'resume_condition': {'trigger': 'event', 'object_refs': operation.prior_execution_refs, 'earliest_time': None,
                                     'condition_code': 'query_original_payment_command_before_new_execution'}}
        if action_input.receipt_refs: raise ValueError('New execution cannot reuse existing receipts')
        original_lines = [line.transfer.model_dump(mode='python') for line in approved.lines]
        if [line.model_dump(mode='python') for line in operation.lines] != original_lines:
            raise ValueError('New funding execution changes original approved transfers')
        chosen_path = path(operation.path_ref, approved)
        if not same(chosen_path.source_account_ref, operation.funding_account_ref): raise ValueError('Funding path changes its physical source account')
        clock(chosen_path.execution_window.start)
        if chosen_path.status != 'available' or not chosen_path.execution_window.contains(now) or not _known(chosen_path.conditions_satisfied, 'original_funding_path_conditions'):
            _needs('original_funding_path_currently_available')
        source = read(operation.funding_account_ref, BankExecutionAccountView, covered=False); clock(source.as_of)
        if (source.organization_id != lender or source.currency != approved.amount.currency
                or chosen_path.ref.key() not in keys(source.permitted_path_refs)):
            raise ValueError('Funding source belongs to another bank or path permission')
        if source.as_of != now or source.coverage != 'complete': _needs('complete_current_actual_bank_currency_account')
        currency = approved.amount.currency
        cash = money(_known(source.actual_cash, 'actual_bank_funding_cash'), currency)
        restricted = money(_known(source.restricted_cash, 'actual_bank_cash_restrictions'), currency)
        held, needed, all_obligations = Fraction(), Fraction(), set(); keys(source.reservation_refs)
        for ref in source.reservation_refs:
            reservation = read(ref, BankExecutionReservationView, covered=False); clock(reservation.as_of)
            if reservation.organization_id != lender or not same(reservation.account_ref, source.ref): raise ValueError('Execution reservation belongs to another actual source account')
            if reservation.as_of != now: _needs('current_original_cross_facility_bank_cash_reservations')
            evidence([reservation.disposition_basis_ref])
            if reservation.status == 'held': held += money(reservation.amount, currency)
        for line in approved.lines:
            figures = amounts(line.amounts, currency, at=approved.approved_at); needed += figures['bank_debit']
            transfer = line.transfer
            destination = read(transfer.destination_ref, BankExecutionAccountView, covered=False)
            if (destination.organization_id != transfer.beneficiary_id or destination.currency != currency
                    or chosen_path.ref.key() not in keys(destination.permitted_path_refs)):
                raise ValueError('Destination changes original beneficiary/currency/path')
            fees = {field: Fraction() for field in ('withheld_fee', 'capitalized_fee', 'separate_fee_cash')}
            if not keys(transfer.fee_rule_refs) <= keys(chosen_path.fee_rule_refs): raise ValueError('Funding execution changes path fee rules')
            for ref in transfer.fee_rule_refs:
                fee = read(ref, BankExecutionFeeRuleView)
                if not same(fee.arrangement_ref, arrangement.ref) or not same(fee.approval_ref, approved.ref) or not same(fee.destination_ref, transfer.destination_ref):
                    raise ValueError('Execution fee belongs to another approval or destination')
                for field in fees: fees[field] += money(getattr(fee, field), currency)
            if any(fees[field] != figures[field] for field in fees): raise ValueError('Execution fee split differs from original approved product rules')
            unpaid = Fraction(); keys(transfer.obligation_refs)
            for ref in transfer.obligation_refs:
                obligation_identity = (ref.kind, ref.id)
                if obligation_identity in all_obligations: raise ValueError('Funding execution pays one trade obligation twice across versions')
                all_obligations.add(obligation_identity); due = read(ref, BankExecutionObligationView)
                if due.borrower_id != arrangement.borrower_id or due.payee_id != transfer.beneficiary_id:
                    raise ValueError('Direct funding execution changes original borrower or actual creditor')
                if not _known(due.payable, 'actual_direct_funding_trade_obligation'): _needs('actual_direct_funding_trade_obligation')
                unpaid += money(_known(due.unpaid_amount, 'actual_direct_funding_unpaid_amount'), currency)
            if transfer.beneficiary_id != arrangement.borrower_id and (not transfer.obligation_refs or figures['beneficiary_cash'] > unpaid):
                _needs('direct_funding_within_original_actual_trade_obligation')
        if cash - restricted - held < needed:
            reading.recheck(); return {'kind': 'deferred', 'reason_code': 'actual_bank_currency_path_funding_shortfall',
                'resume_condition': {'trigger': 'dependency_change', 'object_refs': [source.ref, chosen_path.ref],
                    'earliest_time': None, 'condition_code': 'actual_same_currency_path_cash_after_original_reservations_available'}}
        return completed('execute', approval_ref=approved.ref, path_ref=chosen_path.ref, lines=original_lines)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
