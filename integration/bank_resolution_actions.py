"""Prepare BANK-A10 with original difficulty, debt, remedy and legal-right sources."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_resolution_objects import (
    BankDefaultNoticeView, BankRemedyProposalView, BankResolutionArrangementView,
    BankResolutionObligationView, BankResolutionProfileView, BankResolutionExecutionView,
    BankSecurityRightView, bank_resolution_schemas,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.organization.models import Authorization


def validate_resolution_selection(action_input, *, organization_id, resolve):
    """Check identities without confirming default, changing debt or enforcing rights."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Resolution selection changes an original typed source reference')
        return row

    arrangement = read(action_input.arrangement_ref, BankResolutionArrangementView)
    profile = read(action_input.resolution_profile_ref, BankResolutionProfileView)
    authority = read(action_input.authority_ref, Authorization)
    if (arrangement.lender_id != organization_id or profile.organization_id != organization_id
            or authority.organization_id != organization_id or profile.arrangement_ref.key() != arrangement.ref.key()
            or profile.authority_ref.key() != authority.ref.key()):
        raise ValueError('Resolution selection changes original bank, facility, profile or authority')
    for refs, schema in ((action_input.notice_refs, BankDefaultNoticeView),
            (action_input.unpaid_refs, BankResolutionObligationView),
            (action_input.security_refs, BankSecurityRightView),
            (action_input.remedy_refs, BankRemedyProposalView)):
        for ref in refs:
            row = read(ref, schema)
            if row.arrangement_ref.key() != arrangement.ref.key():
                raise ValueError('Resolution source selection changes the original facility')
    # Difficulty-stage remedies may lack default notices. Accounting writeoff
    # needs no collateral enforcement right and never forgives actual debt.
    # Party acceptance, legal gates and unknown executions stay in the processor.


def validate_resolution_execution_history(action_input, *, organization_id, sources):
    """Authenticate supplied historical profiles; completeness stays with the processor."""
    arrangement = sources[action_input.arrangement_ref.key()]
    profile = sources[action_input.resolution_profile_ref.key()]
    for ref in arrangement.resolution_execution_refs:
        execution = sources.get(ref.key())
        if execution is not None and (not isinstance(execution, BankResolutionExecutionView)
                or execution.organization_id != organization_id
                or execution.arrangement_ref.key()[:2] != arrangement.ref.key()[:2]):
            raise ValueError('Resolution history substitutes its original bank or physical facility')
        if execution is not None and execution.business_key == profile.business_key:
            original = sources.get(execution.profile_ref.key())
            if original is not None and (not isinstance(original, BankResolutionProfileView)
                    or original.arrangement_ref != execution.arrangement_ref
                    or original.organization_id != execution.organization_id or original.scope != execution.scope
                    or original.business_key != execution.business_key):
                raise ValueError('Resolution execution substitutes its original profile, facility or scope')


@dataclass(frozen=True)
class PreparedBankResolution(PreparedBankIntake):
    """Local resolution invocation without restructuring, enforcement or ledger effects."""


class BankResolutionActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A10'
    SOURCE_SCHEMAS = staticmethod(bank_resolution_schemas)

    def build(self, context, *, arrangement_ref, notice_refs, unpaid_refs, security_refs,
            remedy_refs, resolution_profile_ref, authority_ref):
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('notice_refs', notice_refs), ('unpaid_refs', unpaid_refs),
             ('security_refs', security_refs), ('remedy_refs', remedy_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'arrangement_ref': Reference.model_validate(arrangement_ref),
            'resolution_profile_ref': Reference.model_validate(resolution_profile_ref),
            'authority_ref': Reference.model_validate(authority_ref)},
            prepared_type=PreparedBankResolution, validate_sources=validate_resolution_selection,
            validate_source_history=validate_resolution_execution_history)
