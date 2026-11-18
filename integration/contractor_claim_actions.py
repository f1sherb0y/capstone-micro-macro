"""Assemble original Contractor A09 contract interfaces, changes and claims."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.common import Known
from src.actions.contracts.contractor_claim_objects import (
    ContractorActualCostView, ContractorChangeProposalView, ContractorClaimAmountView,
    ContractorClaimContractView, ContractorClaimDesignView, ContractorClaimInstructionView,
    ContractorClaimProcedureView, ContractorClaimProfileView, ContractorClaimRequirementView,
    ContractorClaimView, ContractorInstructionAuthorityView, ContractorInterfaceIssueView,
    ContractorTimeImpactView, contractor_claim_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorClaim(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A09'


class ContractorClaimActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze explicit contract versions and independently supplied impact sources.

    The actual application holds its current source/authorization guard. Original
    processor checks instruction authority, notice procedure, affected scope,
    original cost components, valuation and time methods. Unknown impact and
    empty actual-cost sets stay explicit. Assembly creates no entitlement,
    recognized claim, revised price, extension, permit or suspended obligation.
    """
    ACTION_ID = 'CONTRACTOR-A09'
    SOURCE_SCHEMAS = staticmethod(contractor_claim_schemas)

    def build(self, context, *, contract_ref, baseline_design_refs, instruction_refs,
            issue_refs, actual_cost_refs, claim_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'contract_ref': contract_ref, 'baseline_design_refs': baseline_design_refs,
            'instruction_refs': instruction_refs, 'issue_refs': issue_refs,
            'actual_cost_refs': actual_cost_refs, 'claim_profile_ref': claim_profile_ref},
            prepared_type=PreparedContractorClaim, validate_sources=validate_contractor_claim_sources)


def validate_contractor_claim_sources(action_input, *, context, organization_id, sources):
    """Check supplied contract and original event identities without valuing a claim."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Contract claim lacks its exact original concrete source')
        return source

    for refs in (action_input.baseline_design_refs, action_input.instruction_refs,
            action_input.issue_refs, action_input.actual_cost_refs):
        unique_refs(refs)
    contract = read(action_input.contract_ref, ContractorClaimContractView)
    profile = read(action_input.claim_profile_ref, ContractorClaimProfileView)
    if (contract.contractor_id != organization_id or not scope_covers(contract.scope, context.scope)
            or profile.organization_id != organization_id or profile.contract_ref.key() != contract.ref.key()
            or profile.scope != context.scope):
        raise TaskConflict('Contract claim changes original contract, contractor or authorized scope')
    for ref in action_input.baseline_design_refs:
        if read(ref, ContractorClaimDesignView).contract_ref.key() != contract.ref.key():
            raise TaskConflict('Contract claim baseline design changes the original contract')
    for ref in action_input.instruction_refs:
        instruction = read(ref, ContractorClaimInstructionView)
        if instruction.contract_ref.key() != contract.ref.key():
            raise TaskConflict('Contract instruction changes its original contract')
        authority = sources.get(instruction.authority_ref.key())
        if authority is not None and (not isinstance(authority, ContractorInstructionAuthorityView)
                or authority.contract_ref.key() != contract.ref.key()
                or authority.actor_id != instruction.author_actor_id
                or authority.function_ref.key() != instruction.author_function_ref.key()
                or authority.organization_id != instruction.author_organization_id
                or not scope_covers(authority.scope, instruction.scope)
                or authority.available_at.clock_ref != instruction.authored_at.clock_ref
                or authority.available_at.offset > instruction.authored_at.offset
                or authority.effective_window.start.clock_ref != instruction.authored_at.clock_ref
                or authority.effective_window.end.clock_ref != instruction.authored_at.clock_ref
                or not authority.effective_window.contains(instruction.authored_at)):
            raise TaskConflict('Contract instruction substitutes its independent original author authority')
    for ref in action_input.issue_refs:
        issue = read(ref, ContractorInterfaceIssueView)
        if issue.contract_ref.key() != contract.ref.key():
            raise TaskConflict('Contract interface issue changes its original contract')
        requirement = sources.get(issue.requirement_ref.key())
        if requirement is not None and (not isinstance(requirement, ContractorClaimRequirementView)
                or requirement.contract_ref.key() != contract.ref.key() or requirement.issue_ref.key() != issue.ref.key()):
            raise TaskConflict('Contract interface requirement changes its original contract or issue')
    for ref in action_input.actual_cost_refs:
        cost = read(ref, ContractorActualCostView)
        if cost.contract_ref.key() != contract.ref.key() or cost.author_organization_id != organization_id:
            raise TaskConflict('Contract cost record changes its original contract or author organization')
        # Actual/estimate status, duplicate components, amounts and source
        # authority remain original processor checks; none imply entitlement.
    procedure = sources.get(profile.procedure_ref.key())
    if procedure is not None and (not isinstance(procedure, ContractorClaimProcedureView)
            or procedure.contract_ref.key() != contract.ref.key()):
        raise TaskConflict('Contract claim procedure changes its original contract')
    change = sources.get(profile.change_ref.key()) if profile.change_ref is not None else None
    if change is not None and (not isinstance(change, ContractorChangeProposalView)
            or change.contract_ref.key() != contract.ref.key() or change.author_organization_id != organization_id):
        raise TaskConflict('Contract change proposal changes its original contract or author organization')
    claim = sources.get(profile.claim_ref.key()) if profile.claim_ref is not None else None
    if claim is not None and (not isinstance(claim, ContractorClaimView)
            or claim.contract_ref.key() != contract.ref.key() or claim.claimant_id != organization_id):
        raise TaskConflict('Contract claim changes its original contract or claimant')
    if profile.amount_result_ref is not None:
        amount = sources.get(profile.amount_result_ref.key())
        if amount is not None and (not isinstance(amount, ContractorClaimAmountView)
                or amount.author_organization_id != organization_id
                or profile.change_ref is not None and amount.change_ref.key() != profile.change_ref.key()):
            raise TaskConflict('Contract claim valuation changes its original proposal or author organization')
    if isinstance(profile.time_impact, Known):
        impact = sources.get(profile.time_impact.value.key())
        if impact is not None and (not isinstance(impact, ContractorTimeImpactView)
                or profile.change_ref is not None and impact.change_ref.key() != profile.change_ref.key()):
            raise TaskConflict('Contract claim time impact changes its original proposal')
