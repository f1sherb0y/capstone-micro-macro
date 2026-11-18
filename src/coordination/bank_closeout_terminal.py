"""Keep the original complete remaining-obligation ledger when archiving closeout."""
from src.actions.contracts.bank_closeout_objects import (
    BankCloseoutCommitmentView, BankCloseoutDebtView, BankCloseoutSecurityView,
    BankCloseoutIssueView, BankRemainingObligationView,
)
from src.actions.contracts.bank_debt_objects import BankDebtReceiptView
from src.actions.contracts.common import Known
from src.actions.roles.qs_change import content_digest
from src.coordination.bank_resolution_terminal import BankResolutionTerminalReading, check_bank_resolution_terminal
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


EXECUTION_CODE = 'query_original_finance_closeout_or_payment'


def check_original_closeout_ledger(*, original_input, arrangement, payments, read, original_context):
    """Retain original remaining sources without assuming closure released anything."""
    at = original_context.business_time
    sources, remaining, physical_debts, physical_commitments, events, expected_unused = {}, set(), set(), set(), set(), set()
    for refs in (arrangement.debt_refs, arrangement.commitment_refs, arrangement.security_refs,
            arrangement.issue_refs, arrangement.remaining_obligation_refs, arrangement.payment_execution_refs):
        if len({ref.key() for ref in refs}) != len(refs):
            raise TaskConflict('Closeout archive duplicates original ledger sources')

    def amount(value):
        number = decimal_fraction(value.value)
        if value.currency != arrangement.currency or number < 0:
            raise TaskConflict('Closeout archive changes original ledger currency or nonnegative balance')
        return number

    for ref in arrangement.debt_refs:
        debt = read(ref, BankCloseoutDebtView, original=True)
        if (debt.arrangement_ref != arrangement.ref or debt.lender_id != arrangement.lender_id
                or debt.borrower_id != arrangement.borrower_id or debt.as_of != at
                or debt.physical_component_key in physical_debts):
            raise TaskConflict('Closeout archive replaces or duplicates original physical debt ledger')
        physical_debts.add(debt.physical_component_key)
        paid, due = amount(debt.cash_paid) + amount(debt.actual_offset), amount(debt.actual_due)
        if paid > due:
            raise TaskConflict('Closeout archive counts paid/offset above original due amount')
        sources[ref.key()] = debt
        if (not isinstance(debt.outstanding_balance, Known) or amount(debt.outstanding_balance.value) > 0
                or debt.accrual_complete_through != at or paid < due):
            remaining.add(ref.key())
    payment_commands, payment_business = set(), set()
    for payment in payments:
        if payment.command_id in payment_commands or payment.business_key in payment_business:
            raise TaskConflict('Closeout archive repeats an original payment command/business key')
        payment_commands.add(payment.command_id)
        payment_business.add(payment.business_key)
        sources[payment.ref.key()] = payment
        if payment.status in {'unknown', 'pending', 'partial'}:
            remaining.add(payment.ref.key())
        if payment.status == 'succeeded' and not payment.receipt_refs:
            raise TaskConflict('Closeout archive lacks original successful payment receipts')
        if len({ref.key() for ref in payment.receipt_refs}) != len(payment.receipt_refs):
            raise TaskConflict('Closeout archive duplicates original payment receipt references')
        for ref in payment.receipt_refs:
            receipt = read(ref, BankDebtReceiptView, original=True)
            if (receipt.execution_ref != payment.ref or receipt.arrangement_ref != arrangement.ref
                    or receipt.lender_id != arrangement.lender_id or receipt.borrower_id != arrangement.borrower_id
                    or receipt.command_id != payment.command_id or receipt.business_key != payment.business_key
                    or receipt.event_id in events):
                raise TaskConflict('Closeout archive duplicates or substitutes original cash receipt history')
            if (any(point.clock_ref != at.clock_ref for point in (
                    receipt.effective_at, receipt.verified_at, receipt.available_at))
                    or not receipt.effective_at.offset <= receipt.verified_at.offset <= receipt.available_at.offset <= at.offset):
                raise TaskConflict('Closeout archive introduces a receipt not effective and verified at original wait time')
            received = amount(receipt.amount)
            if received <= 0:
                raise TaskConflict('Closeout archive requires positive original actual receipt amount')
            effects = [effect.debt_component_ref.key() for effect in receipt.principal_effects]
            if len(set(effects)) != len(effects):
                raise TaskConflict('Closeout archive duplicates original receipt principal effects')
            principal_total = 0
            for effect in receipt.principal_effects:
                component = sources.get(effect.debt_component_ref.key())
                if not isinstance(component, BankCloseoutDebtView) or component.kind != 'principal':
                    raise TaskConflict('Closeout archive receipt changes original principal component')
                principal_total += amount(effect.amount)
            if principal_total > received:
                raise TaskConflict('Closeout archive receipt principal effects exceed original actual amount')
            events.add(receipt.event_id)
    if {ref.key() for ref in original_input.pending_execution_refs} != {
            row.ref.key() for row in payments if row.status in {'unknown', 'pending', 'partial'}}:
        raise TaskConflict('Closeout archive drops original unknown payment occupancy')
    for ref in arrangement.commitment_refs:
        row = read(ref, BankCloseoutCommitmentView, original=True)
        if (row.arrangement_ref != arrangement.ref or row.lender_id != arrangement.lender_id
                or row.as_of != at or row.physical_commitment_key in physical_commitments
                or not {value.key() for value in row.execution_refs} <= {value.ref.key() for value in payments}):
            raise TaskConflict('Closeout archive replaces original commitments or pending execution links')
        physical_commitments.add(row.physical_commitment_key)
        sources[ref.key()] = row
        if row.status != 'closed':
            remaining.add(ref.key())
        if row.status == 'unknown' or row.status == 'active' and (
                not isinstance(row.unused_amount, Known) or amount(row.unused_amount.value) > 0):
            expected_unused.add(ref.key())
    if {ref.key() for ref in original_input.unused_commitment_refs} != expected_unused:
        raise TaskConflict('Closeout archive omits original commitment ledger')
    for ref in arrangement.security_refs:
        row = read(ref, BankCloseoutSecurityView, original=True)
        if (row.arrangement_ref != arrangement.ref or row.holder_id != arrangement.lender_id
                or not {value.key() for value in row.debt_refs} <= {value.key() for value in arrangement.debt_refs}):
            raise TaskConflict('Closeout archive changes original security holder or covered debt')
        sources[ref.key()] = row
        if row.status != 'released':
            remaining.add(ref.key())
    issues = []
    for ref in arrangement.issue_refs:
        row = read(ref, BankCloseoutIssueView, original=True)
        if row.arrangement_ref != arrangement.ref:
            raise TaskConflict('Closeout archive changes original unresolved issue facility')
        issues.append(row)
        sources[ref.key()] = row
        if row.status != 'resolved':
            remaining.add(ref.key())
    if {ref.key() for ref in original_input.unresolved_refs} != {row.ref.key() for row in issues if row.status != 'resolved'}:
        raise TaskConflict('Closeout archive drops original unresolved finance issues')
    seen = set()
    for ref in arrangement.remaining_obligation_refs:
        row = read(ref, BankRemainingObligationView, original=True)
        key = row.source_ref.key()
        if (row.arrangement_ref != arrangement.ref or row.as_of != at or key not in sources or key in seen
                or row.source_sha256 != content_digest(sources[key])):
            raise TaskConflict('Closeout archive rewrites original remaining-obligation sources')
        seen.add(key)
    if not remaining <= seen:
        raise TaskConflict('Closeout archive omits original remaining debt, occupancy, security or issues')


def check_bank_closeout_terminal(check, selected, validate_relation, *, terminal=False):
    return check_bank_resolution_terminal(check, selected, validate_relation, terminal=terminal, closeout=True)
