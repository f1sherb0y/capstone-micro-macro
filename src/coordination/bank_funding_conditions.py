"""Recompute original BANK-A07 currency/path cash waits without releasing reservations."""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction

from src.actions.contracts.bank_execution_objects import (
    BankExecutionAccountView, BankExecutionApprovalView, BankExecutionPathView, BankExecutionReservationView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


class _UnavailableEvidence(Exception):
    pass


@dataclass(frozen=True)
class BankFundingConditionReading:
    context: ActionContext
    reading: ActionReadView
    account_ref: Reference
    path_ref: Reference
    original_approval_ref: Reference
    approval_ref: Reference
    action_input: dict | None = None


def bank_currency_path_cash_profile(read_current, validate_relation):
    """Use actual current account and all cross-facility reservations.

    The reader supplies old/current source versions under current own authority.
    validate_relation independently binds the original waiting task to its
    approval and authenticates the complete current account/reservation/path
    observations. A dependency hint cannot supply money or release a hold.
    Readiness only permits a fresh action; normal A07 checks still run later.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Funding wait requires an independent current reader and native complete-ledger validator')
    code = 'actual_same_currency_path_cash_after_original_reservations_available'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'BANK-A07' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 2 or {ref.kind for ref in old_refs} != {'Account', 'FundingPath'}):
            raise TaskConflict('Funding wait changes original task, recipient or selected account/path dependencies')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, BankFundingConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or any(not isinstance(ref, Reference) for ref in (selected.account_ref, selected.path_ref,
                    selected.original_approval_ref, selected.approval_ref))):
            raise TaskConflict('Funding wait needs a typed current authorized account/path/approval reading')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        old = {ref.kind: ref for ref in old_refs}
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A07'
                or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or (selected.account_ref.kind, selected.account_ref.id) != (old['Account'].kind, old['Account'].id)
                or (selected.path_ref.kind, selected.path_ref.id) != (old['FundingPath'].kind, old['FundingPath'].id)
                or selected.original_approval_ref.kind != 'DrawApproval'
                or (selected.approval_ref.kind, selected.approval_ref.id) != (
                    selected.original_approval_ref.kind, selected.original_approval_ref.id)):
            raise TaskConflict('Funding wait substitutes original physical sources/approval or current run/action/time')
        reading.check_method_context(context, 'BANK-A07')
        now = context.business_time
        observed = {}

        def current(row):
            return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                and row.effective_window.contains(now))

        def evidence(ref, *, at=None):
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Funding condition requires independent actual observed ledger evidence')
            if row.effective_window is not None and not row.effective_window.contains(at or now):
                raise _UnavailableEvidence
            observed[ref.key()] = row.model_dump(mode='json')

        def amount(money, currency, *, at=None):
            if money.currency != currency:
                raise TaskConflict('Funding wait cannot convert currencies')
            number = decimal_fraction(money.value)
            if number < 0:
                raise TaskConflict('Funding wait cannot use negative cash, reservation or approved debit')
            evidence(money.basis_ref, at=at)
            return number

        try:
            before_account, before_path = reading.resolve(old['Account']), reading.resolve(old['FundingPath'])
            account, path = reading.resolve(selected.account_ref), reading.resolve(selected.path_ref)
            original, approval = reading.resolve(selected.original_approval_ref), reading.resolve(selected.approval_ref)
            if (not all(isinstance(row, BankExecutionAccountView) for row in (before_account, account))
                    or not all(isinstance(row, BankExecutionPathView) for row in (before_path, path))
                    or not all(isinstance(row, BankExecutionApprovalView) for row in (original, approval))
                    or before_account.ref != old['Account'] or before_path.ref != old['FundingPath']
                    or account.ref != selected.account_ref or path.ref != selected.path_ref
                    or original.ref != selected.original_approval_ref or approval.ref != selected.approval_ref
                    or account.organization_id != source['organization_id'] or path.lender_id != source['organization_id']
                    or approval.lender_id != source['organization_id']
                    or account.organization_id != before_account.organization_id or account.currency != before_account.currency
                    or path.lender_id != before_path.lender_id or path.arrangement_ref != before_path.arrangement_ref
                    or path.currency != before_path.currency or path.source_account_ref != account.ref
                    or (before_path.source_account_ref.kind, before_path.source_account_ref.id) != (account.ref.kind, account.ref.id)
                    or any(getattr(original, field) != getattr(approval, field) for field in (
                        'lender_id', 'borrower_id', 'arrangement_ref', 'terms_ref', 'batch_key', 'amount', 'lines', 'scope',
                        'approved_at', 'approver_actor_id', 'approver_function_ref', 'approver_authority_ref'))
                    or path.arrangement_ref != approval.arrangement_ref or path.currency != approval.amount.currency
                    or account.currency != approval.amount.currency or path.ref not in account.permitted_path_refs):
                raise TaskConflict('Funding wait changes original participants, account, currency, path or approved financial split')
            if not all(current(row) for row in (account, path, approval)) or account.as_of != now:
                return 'unavailable'
            if any(row.approved_at.clock_ref != now.clock_ref or row.available_at.clock_ref != now.clock_ref
                    or row.approved_at.offset > min(now.offset, row.available_at.offset) for row in (original, approval)):
                return 'unavailable'
            if (account.coverage != 'complete' or account.actual_cash.state != 'known' or account.restricted_cash.state != 'known'
                    or path.conditions_satisfied.state != 'known' or approval.execution_coverage != 'complete'):
                return 'unavailable'
            if (path.status != 'available' or not path.execution_window.contains(now)
                    or path.conditions_satisfied.value is not True or approval.status != 'approved' or approval.execution_refs):
                return 'waiting'
            for row in (account, path):
                for ref in row.evidence_refs:
                    evidence(ref)
            for ref in approval.evidence_refs:
                evidence(ref, at=approval.approved_at)
            currency = account.currency
            cash, restricted = amount(account.actual_cash.value, currency), amount(account.restricted_cash.value, currency)
            if len(set(account.reservation_refs)) != len(account.reservation_refs):
                raise TaskConflict('Funding wait repeats a cash reservation')
            held, reservations = Fraction(), []
            for ref in account.reservation_refs:
                reservation = reading.resolve(ref)
                if (not isinstance(reservation, BankExecutionReservationView) or reservation.ref != ref
                        or reservation.organization_id != account.organization_id
                        or reservation.account_ref != account.ref or reservation.as_of != now or not current(reservation)):
                    raise TaskConflict('Funding wait omits current cross-facility reservations or substitutes another account')
                for evidence_ref in [reservation.disposition_basis_ref, *reservation.evidence_refs]:
                    evidence(evidence_ref)
                reserved = amount(reservation.amount, currency)
                if reservation.status == 'held':
                    held += reserved
                reservations.append(reservation.model_dump(mode='json'))
            if len({line.local_key for line in approval.lines}) != len(approval.lines):
                raise TaskConflict('Funding wait repeats an approved transfer line')
            needed, principal = Fraction(), Fraction()
            approved_amount = amount(approval.amount, currency, at=approval.approved_at)
            if approved_amount <= 0:
                raise TaskConflict('Funding wait cannot use a nonpositive original approval')
            for line in approval.lines:
                figures = {field: amount(getattr(line.amounts, field), currency, at=approval.approved_at) for field in (
                    'principal', 'beneficiary_cash', 'withheld_fee', 'capitalized_fee', 'separate_fee_cash', 'bank_debit')}
                if (figures['principal'] != figures['beneficiary_cash'] + figures['withheld_fee'] + figures['capitalized_fee']
                        or figures['bank_debit'] != figures['beneficiary_cash'] + figures['separate_fee_cash']
                        or figures['principal'] <= 0
                        or amount(line.transfer.requested, currency, at=approval.approved_at) != figures['beneficiary_cash']):
                    raise TaskConflict('Funding wait changes original approved principal/cash/fee split')
                needed += figures['bank_debit']
                principal += figures['principal']
            if principal != approved_amount:
                raise TaskConflict('Funding wait changes original approved principal total')
            if validate_relation(source_identity=deepcopy(source), original_account=before_account.model_copy(deep=True),
                    original_path=before_path.model_copy(deep=True), original_approval=original.model_copy(deep=True),
                    account=account.model_copy(deep=True), path=path.model_copy(deep=True), approval=approval.model_copy(deep=True),
                    reservations=deepcopy(reservations), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Funding wait lacks authentic complete cash/restriction/reservation and original approval provenance')
            return 'ready' if cash - restricted - held >= needed else 'waiting'
        except _UnavailableEvidence:
            return 'unavailable'
        finally:
            reading.recheck()

    return ConditionProfile('BANK-A07', code, '3', frozenset({'dependency_change'}), evaluate)
