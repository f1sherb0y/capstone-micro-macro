"""Assemble original Contractor A13 bounded preliminary consulting inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_advice_objects import (
    ContractorAdviceAuthorityView, ContractorAdviceBriefView, ContractorAdviceCapabilityView,
    ContractorAdviceCaseView, ContractorAdviceExecutionView, ContractorAdviceFeeView,
    ContractorAdviceMethodView, ContractorAdviceOptionView, ContractorAdviceProfileView,
    ContractorAdviceProposalView, ContractorAdviceRequestView, ContractorAdviceSupplierView,
    ContractorAdviceTaskView, contractor_advice_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedContractorAdvice(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A13'


class ContractorAdviceActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze exact brief/options and supplied bounded advisory work provenance.

    The actual application holds its current source/authorization guard. Original
    processor checks disclosure, finite service authority, actual effort/cost,
    constructability and duration methods. A null work authority stays null.
    Assembly creates no free study, service fee, construction reservation,
    supplier commitment, awarded contract or professional approval.
    """
    ACTION_ID = 'CONTRACTOR-A13'
    SOURCE_SCHEMAS = staticmethod(contractor_advice_schemas)

    def build(self, context, *, brief_ref, option_refs, advisory_request_ref,
            advisory_authority_ref, capability_ref, supplier_evidence_refs, method_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'brief_ref': brief_ref, 'option_refs': option_refs,
            'advisory_request_ref': advisory_request_ref, 'advisory_authority_ref': advisory_authority_ref,
            'capability_ref': capability_ref, 'supplier_evidence_refs': supplier_evidence_refs,
            'method_refs': method_refs}, prepared_type=PreparedContractorAdvice,
            validate_sources=validate_contractor_advice_sources)


def validate_contractor_advice_sources(action_input, *, context, organization_id, sources):
    """Check original request and study identities without performing consulting work."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Contractor advice lacks its exact original concrete source')
        return source

    for refs in (action_input.option_refs, action_input.supplier_evidence_refs, action_input.method_refs):
        unique_refs(refs)
    brief = read(action_input.brief_ref, ContractorAdviceBriefView)
    request = read(action_input.advisory_request_ref, ContractorAdviceRequestView)
    capability = read(action_input.capability_ref, ContractorAdviceCapabilityView)
    if (request.brief_ref.key() != brief.ref.key() or organization_id not in request.recipient_organization_ids
            or capability.organization_id != organization_id):
        raise TaskConflict('Contractor advice changes the original brief, recipient or private capability')
    bases = {brief.ref.key()}
    for ref in action_input.option_refs:
        option = read(ref, ContractorAdviceOptionView)
        if option.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Contractor advisory option changes its original brief')
        bases.add(ref.key())
    for ref in action_input.supplier_evidence_refs:
        if read(ref, ContractorAdviceSupplierView).basis_ref.key() not in bases:
            raise TaskConflict('Contractor supply advice changes the original brief or option basis')
    for ref in action_input.method_refs:
        read(ref, ContractorAdviceMethodView)
    profile = sources.get(request.profile_ref.key())
    if profile is not None:
        if (not isinstance(profile, ContractorAdviceProfileView) or profile.organization_id != organization_id
                or profile.request_ref.key() != request.ref.key()):
            raise TaskConflict('Contractor advisory profile changes original contractor or request')
        if profile.proposal_ref is not None:
            proposal = sources.get(profile.proposal_ref.key())
            if proposal is not None and (not isinstance(proposal, ContractorAdviceProposalView)
                    or proposal.organization_id != organization_id or proposal.request_ref.key() != request.ref.key()
                    or proposal.scope != context.scope):
                raise TaskConflict('Contractor paid study proposal changes original request, contractor or scope')
        for ref in profile.case_refs:
            case = sources.get(ref.key())
            if case is not None and (not isinstance(case, ContractorAdviceCaseView)
                    or case.organization_id != organization_id or case.request_ref.key() != request.ref.key()
                    or case.basis_ref.key() not in bases):
                raise TaskConflict('Constructability assessment changes its original contractor, request or basis')
    if action_input.advisory_authority_ref is None:
        return
    authority = read(action_input.advisory_authority_ref, ContractorAdviceAuthorityView)
    if (authority.organization_id != organization_id or authority.request_ref.key() != request.ref.key()
            or authority.scope != context.scope or authority.delegate_actor_id != context.actor_id
            or authority.delegate_function_ref.key() != context.function_ref.key()):
        raise TaskConflict('Contractor consulting work authority changes original request, delegate or scope')
    task = sources.get(authority.task_ref.key())
    if task is not None:
        if (not isinstance(task, ContractorAdviceTaskView) or task.organization_id != organization_id
                or task.authority_ref.key() != authority.ref.key() or task.request_ref.key() != request.ref.key()
                or task.scope != authority.scope):
            raise TaskConflict('Contractor consulting task changes its original bounded work authority')
        for ref in task.execution_refs:
            work = sources.get(ref.key())
            if work is not None and (not isinstance(work, ContractorAdviceExecutionView)
                    or work.organization_id != organization_id or work.task_ref.key() != task.ref.key()
                    or work.authority_ref.key() != authority.ref.key() or work.scope != task.scope):
                raise TaskConflict('Contractor consulting execution changes original task, authority or scope')
    if authority.fee_obligation_ref is not None:
        fee = sources.get(authority.fee_obligation_ref.key())
        if fee is not None and (not isinstance(fee, ContractorAdviceFeeView)
                or fee.authority_ref.key() != authority.ref.key() or fee.creditor_id != organization_id
                or fee.debtor_id != authority.issuer_organization_id):
            raise TaskConflict('Contractor advisory fee changes its original service authority or legal parties')
