"""Prepare BANK-A11 from original remaining commitments, debts and issues."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_closeout_objects import (
    BankCloseoutArrangementView, BankCloseoutCommitmentView, BankCloseoutDebtView,
    BankCloseoutIssueView, BankCloseoutProfileView, BankCloseoutExecutionView,
    BankCloseoutSecurityView, bank_closeout_schemas,
)
from src.actions.contracts.bank_debt_objects import BankDebtExecutionView
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_closeout_selection(action_input, *, organization_id, resolve):
    """Check identities without clearing debt or releasing unresolved commitments."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Closeout selection changes an original typed source reference')
        return row

    arrangement = read(action_input.arrangement_ref, BankCloseoutArrangementView)
    profile = read(arrangement.closeout_profile_ref, BankCloseoutProfileView)
    if (arrangement.lender_id != organization_id or profile.organization_id != organization_id
            or profile.arrangement_ref.key() != arrangement.ref.key()):
        raise ValueError('Closeout selection changes original bank, facility or profile')
    for refs, schema in ((action_input.unused_commitment_refs, BankCloseoutCommitmentView),
            (action_input.debt_refs, BankCloseoutDebtView),
            (action_input.pending_execution_refs, BankDebtExecutionView),
            (action_input.security_refs, BankCloseoutSecurityView),
            (action_input.unresolved_refs, BankCloseoutIssueView)):
        for ref in refs:
            row = read(ref, schema)
            if (row.arrangement_ref.key() != arrangement.ref.key()
                    or hasattr(row, 'lender_id') and row.lender_id != organization_id
                    or hasattr(row, 'borrower_id') and row.borrower_id != arrangement.borrower_id):
                raise ValueError('Closeout source selection changes original facility or parties')
    # Empty unused-commitment lists are valid. Actual ledger completeness,
    # uncleared obligations, verified release limits and unknown-execution
    # queries remain the original processor's responsibility.


def validate_closeout_execution_history(action_input, *, organization_id, sources):
    """Bind supplied original closing profiles to the original execution scope."""
    arrangement = sources[action_input.arrangement_ref.key()]
    profile = sources[arrangement.closeout_profile_ref.key()]
    for ref in arrangement.closeout_execution_refs:
        execution = sources.get(ref.key())
        if execution is not None and (not isinstance(execution, BankCloseoutExecutionView)
                or execution.organization_id != organization_id
                or execution.arrangement_ref.key()[:2] != arrangement.ref.key()[:2]):
            raise ValueError('Closeout history substitutes its original bank or physical facility')
        if execution is not None and execution.business_key == profile.business_key:
            original = sources.get(execution.profile_ref.key())
            if original is not None and (not isinstance(original, BankCloseoutProfileView)
                    or original.arrangement_ref != execution.arrangement_ref
                    or original.organization_id != execution.organization_id or original.scope != execution.scope
                    or original.business_key != execution.business_key or original.scope_ref != execution.affected_scope):
                raise ValueError('Closeout execution substitutes its original profile, facility or affected scope')


@dataclass(frozen=True)
class PreparedBankCloseout(PreparedBankIntake):
    """A local retain/closure proposal, without changing actual debt or security."""


class BankCloseoutActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A11'
    SOURCE_SCHEMAS = staticmethod(bank_closeout_schemas)

    def build(self, context, *, arrangement_ref, unused_commitment_refs, debt_refs,
            pending_execution_refs, security_refs, unresolved_refs):
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('unused_commitment_refs', unused_commitment_refs), ('debt_refs', debt_refs),
             ('pending_execution_refs', pending_execution_refs), ('security_refs', security_refs),
             ('unresolved_refs', unresolved_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'arrangement_ref': Reference.model_validate(arrangement_ref)},
            prepared_type=PreparedBankCloseout, validate_sources=validate_closeout_selection,
            validate_source_history=validate_closeout_execution_history)
