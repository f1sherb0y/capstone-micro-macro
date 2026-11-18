"""Prepare BANK-A09 from original debts, verified receipts and posting sources."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_debt_objects import (
    BankDebtArrangementView, BankDebtComponentView, BankDebtExecutionView, BankDebtPostingView,
    BankDebtProfileView, BankDebtReceiptView, BankDebtTermsView, bank_debt_schemas,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_debt_selection(action_input, *, organization_id, resolve):
    """Check identities only; never calculate due amounts or fabricate actual receipts."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Debt selection changes an original typed source reference')
        return row

    arrangement = read(action_input.arrangement_ref, BankDebtArrangementView)
    profile = read(action_input.calculation_profile_ref, BankDebtProfileView)
    if arrangement.lender_id != organization_id or profile.arrangement_ref.key() != arrangement.ref.key():
        raise ValueError('Debt selection changes the original lender, facility or calculation profile')
    for refs, schema in ((action_input.debt_components, BankDebtComponentView),
            (action_input.verified_receipts, BankDebtReceiptView),
            (action_input.prior_posting_refs, BankDebtPostingView),
            (action_input.execution_refs, BankDebtExecutionView)):
        for ref in refs:
            row = read(ref, schema)
            if (row.arrangement_ref.key() != arrangement.ref.key()
                    or hasattr(row, 'lender_id') and row.lender_id != organization_id
                    or hasattr(row, 'borrower_id') and row.borrower_id != arrangement.borrower_id):
                raise ValueError('Debt source selection changes original facility, lender or borrower')
    if profile.choice != 'reconcile':
        terms = read(arrangement.terms_ref, BankDebtTermsView)
        if terms.arrangement_ref.key() != arrangement.ref.key():
            raise ValueError('Debt selection changes the original contractual terms facility')
    # Reconciliation may have no new receipt and does not require accrual
    # terms. Original methods, calendars, allocations, event deduplication and
    # append-only corrections remain entirely in the existing processor.


@dataclass(frozen=True)
class PreparedBankDebt(PreparedBankIntake):
    """A local accrual/allocation/query/correction invocation, without ledger writes."""


class BankDebtActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A09'
    SOURCE_SCHEMAS = staticmethod(bank_debt_schemas)

    def build(self, context, *, arrangement_ref, debt_components, accrual_window_ref,
            calculation_profile_ref, verified_receipts, prior_posting_refs, execution_refs):
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('debt_components', debt_components), ('verified_receipts', verified_receipts),
             ('prior_posting_refs', prior_posting_refs), ('execution_refs', execution_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'arrangement_ref': Reference.model_validate(arrangement_ref),
            'accrual_window_ref': Reference.model_validate(accrual_window_ref),
            'calculation_profile_ref': Reference.model_validate(calculation_profile_ref)},
            prepared_type=PreparedBankDebt, validate_sources=validate_debt_selection)
