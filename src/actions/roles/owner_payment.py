"""OWN-A06 cash instructions only; core receipts own actual settlement."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentScopeView, OwnerPaymentAuthorizationView, OwnerPaymentAccountView, OwnerPaymentSourceView,
    OwnerPaymentArrangementView, OwnerPaymentDrawView, OwnerPaymentDrawConditionView,
    OwnerPaymentObligationView, OwnerPaymentComponentView, OwnerPaymentDebtView, OwnerPaymentDebtTermsView,
    OwnerPaymentExecutionView, OwnerPaymentReceiptView,
    OwnerPaymentReservationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def instruct_cash(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-payment-clock-alignment')

    def evidence(refs, historical=False, *, at=None):
        if at is not None: clock(at)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-payment-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if (at is not None or not historical) and not row.effective_window.contains(at or now):
                    _needs('current_original_payment_evidence', [ref])

    def read(ref, schema, historical=False, covered=True, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-payment-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Payment input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_payment_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_payment_input', [ref])
        point = None
        if evidence_at_field is not None:
            point = getattr(row, evidence_at_field); clock(point)
            if point.offset > now.offset or (hasattr(row, 'available_at') and point.offset > row.available_at.offset):
                _needs('available_original_payment_verification', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical, at=point); return row

    def authorize(ref, actor, function_ref, organization, action, roles, *, at=None, target_scope=None, required_reads=()):
        point = at or now; clock(point)
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        expected_role = {'OWN': 'Owner', 'BANK': 'Bank', 'QS': 'QS', 'ENGINEER': 'Engineer',
            'GOV': 'Government', 'ARCHITECT': 'Architect', 'CONTRACTOR': 'Contractor',
            'SUPPLIER': 'Supplier'}.get(action.split('-', 1)[0])
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.function_ref != function_ref or function.role not in roles or function.role != expected_role
                or action not in grant.action_ids
                or not any(scope_covers(scope, target_scope or context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in required_reads} <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Payment decision lacks original independent actor/organization/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(point): _needs('current_original_cash_authority', [ref])
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=point)
            else:
                reading.resolve(basis_ref)

    def amount(state, field):
        value = _known(state, field); evidence([value.basis_ref])
        if decimal_fraction(value.value) < 0: raise ValueError('Original cash/debt amount cannot be negative')
        return value

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': decision.note, **fields}}

    def execution(ref):
        row = read(ref, OwnerPaymentExecutionView, historical=True)
        if row.organization_id != owner: raise ValueError('Cash execution belongs to another legal organization')
        if decimal_fraction(row.amount.value) <= 0: raise ValueError('Original cash execution needs a positive amount')
        evidence([row.amount.basis_ref], True)
        if row.status in {'succeeded', 'failed', 'rejected'}:
            if row.receipt_ref is None: _needs('original_cash_execution_receipt', [ref])
            receipt = read(row.receipt_ref, OwnerPaymentReceiptView, historical=True)
            if (not same(receipt.execution_ref, row.ref) or receipt.command_id != row.command_id
                    or receipt.business_key != row.business_key or receipt.amount != row.amount
                    or receipt.beneficiary_id != row.beneficiary_id or receipt.status != row.status):
                raise ValueError('Cash receipt changes original command/payment identity')
        return row

    def reconcile(rows):
        if not rows: _needs('original_cash_executions_for_reconciliation')
        keys([row.ref for row in rows])
        if len({row.command_id for row in rows}) != len(rows) or len({row.business_key for row in rows}) != len(rows):
            raise ValueError('Reconciliation repeats the same original command or business payment')
        return completed('reconcile', execution_refs=[row.ref for row in rows])

    def obligation(ref, account=None):
        row = read(ref, OwnerPaymentObligationView, covered=False); clock(row.as_of); clock(row.due_at)
        if row.debtor_id != owner or (context.scope.kind != 'organization' and not scope_covers(context.scope, row.origin_scope)):
            raise ValueError('Cash instruction targets another debtor or unauthorized obligation scope')
        if row.as_of != now: _needs('current_original_unsettled_obligation', [ref])
        if account is not None and not same(row.source_ref, account.source_ref):
            raise ValueError('Payment uses an account outside original obligation funding permission')
        return row

    try:
        if action_input.scope_ref != context.scope: raise ValueError('Cash instruction changes invocation scope')
        subject = read(action_input.scope_ref.ref, OwnerPaymentScopeView)
        if subject.organization_id != owner: raise ValueError('Payment scope belongs to another organization')
        if subject.payment_authorization_ref is None: _needs('original_explicit_payment_authorization')
        decision = read(subject.payment_authorization_ref, OwnerPaymentAuthorizationView)
        if (decision.organization_id != owner or decision.actor_id != context.actor_id
                or decision.function_ref != context.function_ref or decision.scope != context.scope):
            raise ValueError('Cash decision changes original owner/actor/function/scope')
        authorize(decision.authority_ref, context.actor_id, context.function_ref, owner, 'OWN-A06', {'Owner'})
        keys(action_input.pending_execution_refs)
        if decision.choice == 'reconcile':
            if keys(decision.execution_refs) != keys(action_input.pending_execution_refs):
                _needs('exact_original_payment_executions_for_reconciliation', action_input.pending_execution_refs)
            return reconcile([execution(ref) for ref in decision.execution_refs])
        # Reconcile unknown prior commands before producing any fresh cash instruction.
        pending = [execution(ref) for ref in action_input.pending_execution_refs]
        uncertain = [row for row in pending if row.status in {'unknown', 'pending'}]
        if uncertain: return reconcile(uncertain)
        repeated_decision = [row for row in pending if same(row.authorization_ref, decision.ref)]
        if repeated_decision: return reconcile(repeated_decision)
        if decision.choice in {'dispute', 'negotiate'}:
            if not decision.obligation_refs or not keys(decision.obligation_refs) <= keys(action_input.due_refs):
                _needs('original_explicit_disputed_or_negotiated_obligations')
            for ref in decision.obligation_refs: obligation(ref)
            return completed(decision.choice, obligation_refs=decision.obligation_refs)
        if decision.choice == 'draw_request':
            if decision.draw_authorization_ref is None: _needs('original_explicit_draw_authorization')
            draw = read(decision.draw_authorization_ref, OwnerPaymentDrawView)
            if draw.organization_id != owner or draw.arrangement_ref.key() not in keys(action_input.arrangement_refs):
                raise ValueError('Draw request targets another organization or arrangement')
            repeated_draw = [row for row in pending if same(row.authorization_ref, draw.ref)]
            if repeated_draw: return reconcile(repeated_draw)
            arrangement = read(draw.arrangement_ref, OwnerPaymentArrangementView)
            clock(arrangement.as_of)
            if arrangement.borrower_id != owner or not scope_covers(arrangement.scope_ref, context.scope):
                raise ValueError('Draw request changes original borrower or authorized arrangement scope')
            if arrangement.status != 'active' or arrangement.as_of != now or arrangement.draw_coverage != 'complete':
                _needs('active_current_original_draw_arrangement')
            if draw.ref.key() not in keys(arrangement.allowed_draw_authorization_refs) or draw.beneficiary_id not in arrangement.allowed_beneficiary_ids:
                raise ValueError('Draw request leaves original draw authority or beneficiary permission')
            prior = [execution(ref) for ref in arrangement.pending_execution_refs]
            keys(arrangement.pending_execution_refs)
            for row in prior:
                if row.arrangement_ref is None or not same(row.arrangement_ref, arrangement.ref) or row.operation != 'draw_request':
                    raise ValueError('Arrangement pending draw belongs to another original arrangement')
            uncertain = [row for row in prior if row.status in {'unknown', 'pending'}]
            if uncertain: return reconcile(uncertain)
            if draw.original_execution_ref is not None:
                original = execution(draw.original_execution_ref)
                if (original.arrangement_ref is None or not same(original.arrangement_ref, arrangement.ref)
                        or original.operation != 'draw_request' or same(original.authorization_ref, draw.ref)):
                    raise ValueError('Additional draw changes its original arrangement execution identity')
                if not draw.additional_draw or original.status != 'succeeded': return reconcile([original])
            if any(same(row.authorization_ref, draw.ref) for row in prior): return reconcile([row for row in prior if same(row.authorization_ref, draw.ref)])
            evidence([draw.amount.basis_ref]); available = amount(arrangement.undrawn_amount, 'actual_original_undrawn_credit')
            if draw.amount.currency != available.currency: _unsupported('owner-draw-currency-conversion')
            if decimal_fraction(draw.amount.value) <= 0 or decimal_fraction(draw.amount.value) > decimal_fraction(available.value):
                _needs('positive_authorized_draw_within_actual_undrawn_amount')
            if keys(draw.condition_refs) != keys(arrangement.required_draw_condition_refs):
                _needs('complete_original_batch_draw_conditions')
            resolved_evidence = []
            for ref in draw.condition_refs:
                condition = read(ref, OwnerPaymentDrawConditionView, evidence_at_field='verified_at')
                if (not same(condition.arrangement_ref, arrangement.ref) or not same(condition.draw_authorization_ref, draw.ref)
                        or condition.borrower_id != owner): raise ValueError('Draw condition changes original arrangement/batch/borrower')
                authorize(condition.verifier_authority_ref, condition.verifier_actor_id, condition.verifier_function_ref,
                          condition.verifier_organization_id, condition.verifier_action_id, {'Bank', 'QS', 'Engineer', 'Government', 'Owner'},
                          at=condition.verified_at, target_scope=condition.scope, required_reads=[condition.evidence_ref])
                evidence([condition.evidence_ref], at=condition.verified_at)
                if not _known(condition.satisfied, 'original_verified_draw_condition'): _needs('original_verified_draw_condition', [ref])
                resolved_evidence.append(condition.evidence_ref)
            resolved_evidence = list({ref.key(): ref for ref in resolved_evidence}.values())
            if keys(draw.condition_evidence_refs) != keys(resolved_evidence) or not keys(resolved_evidence) <= keys(action_input.evidence_refs):
                _needs('original_received_verified_draw_evidence', resolved_evidence)
            if draw.beneficiary_id != owner:
                if draw.direct_payment_obligation_ref is None or draw.direct_payment_obligation_ref.key() not in keys(action_input.due_refs):
                    _needs('original_direct_bank_payment_obligation_and_beneficiary')
                due = obligation(draw.direct_payment_obligation_ref)
                total = amount(due.actual_due, 'original_direct_payment_due'); paid = amount(due.actual_paid, 'original_direct_payment_paid')
                offset = amount(due.actual_offset, 'original_direct_payment_offset')
                if (due.payee_id != draw.beneficiary_id or due.status != 'effective' or not _known(due.payable, 'original_direct_payment_payable')
                        or total.currency != draw.amount.currency or paid.currency != total.currency or offset.currency != total.currency
                        or decimal_fraction(draw.amount.value) > decimal_fraction(total.value) - decimal_fraction(paid.value) - decimal_fraction(offset.value)):
                    _needs('original_direct_payment_within_verified_unsettled_obligation')
            return completed('draw_request', arrangement_ref=arrangement.ref, amount=draw.amount,
                             beneficiary_id=draw.beneficiary_id, condition_refs=resolved_evidence)
        if decision.account_ref is None or decision.account_ref.key() not in keys(action_input.account_refs):
            _needs('original_authorized_payment_account')
        account = read(decision.account_ref, OwnerPaymentAccountView, covered=False); clock(account.as_of)
        if account.organization_id != owner: raise ValueError('Cash account belongs to another legal organization')
        if account.as_of != now or account.coverage != 'complete' or account.execution_coverage != 'complete':
            _needs('complete_current_actual_account_and_cross_project_cash_executions')
        source = read(account.source_ref, OwnerPaymentSourceView, covered=False); clock(source.as_of)
        if (source.organization_id != owner or not same(source.account_ref, account.ref)
                or source.actual_cash != account.actual_cash or source.restricted_cash != account.restricted_cash):
            raise ValueError('Account changes original actual cash, restrictions or funding source identity')
        if source.as_of != now or source.coverage != 'complete': _needs('current_complete_original_account_source')
        prior = [execution(ref) for ref in account.pending_execution_refs]
        keys(account.pending_execution_refs)
        for row in prior:
            if row.account_ref is None or not same(row.account_ref, account.ref): raise ValueError('Account pending payment belongs to another physical account')
        uncertain = [row for row in prior if row.status in {'unknown', 'pending'}]
        if uncertain: return reconcile(uncertain)
        repeated = [row for row in prior if same(row.authorization_ref, decision.ref)]
        if repeated: return reconcile(repeated)
        cash = amount(account.actual_cash, 'actual_cash_received_not_forecast')
        restricted = amount(account.restricted_cash, 'actual_restricted_account_cash')
        reserved = amount(account.reserved_cash, 'actual_current_other_payment_reservations')
        if any(m.currency != account.currency for m in (cash, restricted, reserved)): _unsupported('owner-payment-account-currency-domain')
        original_reserved = Fraction(); keys(account.reservation_refs)
        for ref in account.reservation_refs:
            reservation = read(ref, OwnerPaymentReservationView, covered=False); clock(reservation.as_of)
            if reservation.organization_id != owner or not same(reservation.account_ref, account.ref):
                raise ValueError('Cash reservation belongs to another original account/organization')
            if reservation.as_of != now: _needs('current_original_cross_project_cash_reservations')
            evidence([reservation.disposition_basis_ref]); value = amount(reservation.amount, 'actual_original_reserved_cash')
            if value.currency != account.currency: _unsupported('owner-payment-reservation-currency-domain')
            if reservation.status == 'held': original_reserved += decimal_fraction(value.value)
        if original_reserved != decimal_fraction(reserved.value): raise ValueError('Reserved cash differs from all original held reservations')
        free = decimal_fraction(cash.value) - decimal_fraction(restricted.value) - decimal_fraction(reserved.value)
        if free < 0: raise ValueError('Account restrictions/reservations exceed actual received cash')
        if not decision.lines: _needs('nonempty_original_authorized_cash_payment_lines')
        keys([line.obligation_ref for line in decision.lines]); due_input = keys(action_input.due_refs)
        if any(line.obligation_ref.key() not in due_input for line in decision.lines): raise ValueError('Payment adds an undeclared obligation')
        if len({line.priority for line in decision.lines}) != len(decision.lines): _needs('explicit_distinct_payment_priority_for_shared_actual_cash')
        plans, all_components = [], set()
        for line in sorted(decision.lines, key=lambda row: row.priority):
            due = obligation(line.obligation_ref, account)
            if due.ref.key() not in keys(account.obligation_refs): raise ValueError('Account does not permit this original obligation')
            if due.status != 'effective' or due.due_at.offset > now.offset or not _known(due.payable, 'verified_original_cash_payable'):
                _needs('effective_due_verified_original_obligation', [due.ref])
            evidence(due.verification_evidence_refs)
            if due.payee_id != line.payee_id: raise ValueError('Payment changes actual obligation payee')
            if (decision.choice == 'repay') != (due.kind in {'principal', 'interest', 'fee'} and due.debt_ref is not None):
                raise ValueError('Pay/repay choice changes original debt settlement meaning')
            expected = keys(due.component_refs); original, category_amounts = Fraction(), {}
            component_due = Fraction(); component_paid = Fraction(); component_offset = Fraction()
            for ref in due.component_refs:
                component = read(ref, OwnerPaymentComponentView, covered=False); clock(component.as_of)
                if (component.as_of != now or not same(component.obligation_ref, due.ref) or component.debtor_id != owner
                        or component.payee_id != due.payee_id or not same(component.source_ref, due.source_ref)
                        or (component.debt_ref.key() if component.debt_ref else None) != (due.debt_ref.key() if due.debt_ref else None)):
                    raise ValueError('Settlement component changes original debtor/payee/debt/account/obligation')
                total = amount(component.actual_due, 'original_component_due'); paid = amount(component.actual_cash_paid, 'original_component_cash_paid')
                offset = amount(component.actual_offset, 'original_component_non_cash_offset')
                if any(m.currency != account.currency for m in (total, paid, offset)): _unsupported('owner-payment-component-currency-domain')
                remaining = decimal_fraction(total.value) - decimal_fraction(paid.value) - decimal_fraction(offset.value)
                if remaining < 0: raise ValueError('Cash paid plus noncash offsets exceed original component')
                component_due += decimal_fraction(total.value)
                component_paid += decimal_fraction(paid.value)
                component_offset += decimal_fraction(offset.value)
                original += remaining; category_amounts[ref.key()] = (component, remaining)
            total = amount(due.actual_due, 'original_due_amount'); paid = amount(due.actual_paid, 'original_paid_amount'); offset = amount(due.actual_offset, 'original_non_cash_offset')
            if any(m.currency != account.currency for m in (total, paid, offset, line.amount)): _unsupported('owner-payment-line-currency-domain')
            if (component_due != decimal_fraction(total.value)
                    or component_paid != decimal_fraction(paid.value)
                    or component_offset != decimal_fraction(offset.value)
                    or original != decimal_fraction(total.value) - decimal_fraction(paid.value) - decimal_fraction(offset.value)):
                raise ValueError('Obligation totals differ from original principal/interest/cash/offset components')
            if due.debt_ref is not None:
                debt = read(due.debt_ref, OwnerPaymentDebtView, covered=False); clock(debt.as_of)
                if debt.borrower_id != owner or debt.lender_id != due.payee_id or due.ref.key() not in keys(debt.obligation_refs):
                    raise ValueError('Repayment changes actual original loan and lender')
                if debt.as_of != now or debt.coverage != 'complete': _needs('complete_current_original_loan_obligations')
                terms = read(debt.terms_ref, OwnerPaymentDebtTermsView, covered=False)
                if not same(terms.debt_ref, debt.ref) or terms.borrower_id != owner or terms.lender_id != due.payee_id:
                    raise ValueError('Repayment applies another loan terms version')
                by_category = {'principal': keys(terms.principal_component_refs), 'interest': keys(terms.interest_component_refs), 'fee': keys(terms.fee_component_refs)}
                keys([*terms.principal_component_refs, *terms.interest_component_refs, *terms.fee_component_refs])
                for key, (component, _) in category_amounts.items():
                    if key not in by_category.get(component.category, set()): raise ValueError('Repayment component has no original loan principal/interest/fee allocation')
            keys([part.component_ref for part in line.component_amounts]); requested = Fraction()
            for part in line.component_amounts:
                key = part.component_ref.key()
                if key not in expected or key in all_components: raise ValueError('Cash instruction duplicates or borrows a settlement component')
                all_components.add(key); component, remaining = category_amounts[key]
                evidence([part.amount.basis_ref]); value = decimal_fraction(part.amount.value)
                if component.settlement_mode != 'cash': raise ValueError('Noncash prepayment offset cannot become a new cash payment')
                if part.amount.currency != account.currency or value <= 0 or value > remaining: _needs('positive_payment_within_original_unsettled_component')
                requested += value
            evidence([line.amount.basis_ref])
            if requested != decimal_fraction(line.amount.value) or requested <= 0: raise ValueError('Authorized line amount differs from exact component allocation')
            plans.append((line, requested))
        total_requested = sum((value for _, value in plans), Fraction())
        if total_requested > free and not decision.allow_partial: _needs('actual_cash_shortfall_requires_explicit_partial_payment_or_revision')
        output = []
        for line, requested in plans:
            available = min(requested, free)
            if available <= 0: continue
            component_refs, rest = [], available
            for part in line.component_amounts:
                if rest <= 0: break
                component_refs.append(part.component_ref); rest -= min(rest, decimal_fraction(part.amount.value))
            output.append({'obligation_ref': line.obligation_ref, 'payee_id': line.payee_id,
                'amount': {'value': exact_decimal(available), 'currency': account.currency, 'basis_ref': line.amount.basis_ref},
                'component_refs': component_refs}); free -= available
        if not output: _needs('positive_actual_available_cash_for_authorized_payment')
        # Host uses the retained original component amounts and ordering for partial allocation;
        # the public action contract carries component identities, never a fabricated settlement ledger.
        return completed(decision.choice, account_ref=account.ref, lines=output)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
