"""Relate saved A02 lines to actual A03 ProductProposal sources without creating approval."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_product_results import SavedSupplierProduct
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.actions.contracts.supplier_quote_objects import (
    QuoteInquiryView, QuoteProductLine, QuoteProposalView, QuoteRequirementView, supplier_quote_schemas,
)
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierProductLineLink(StrictRecord):
    product_line_index: Annotated[int, Field(ge=0)]
    proposal_ref: ref_type('ProductProposal')
    proposal_line_key: TextId


class SupplierProductIssueLink(StrictRecord):
    issue_ref: ref_type('Issue')
    requirement_ref: ref_type('Requirement')
    # Observed independent resolution is explicit, never inferred from A02.
    resolution_evidence_ref: ref_type('Evidence') | None


class SupplierProductHandoffBasisView(GovReviewAuthored):
    ref: ref_type('SupplierProductHandoffBasis')
    run_id: TextId
    organization_id: TextId
    product_task_sha256: Digest
    product_record_sha256: Digest
    product_result_sha256: Digest
    product_audit_sha256: Digest
    product_source_reading_sha256: Digest
    proposal_refs: Annotated[list[ref_type('ProductProposal')], Field(min_length=1)]
    proposal_sha256s: dict[TextId, Digest]
    line_links: Annotated[list[SupplierProductLineLink], Field(min_length=1)]
    issue_links: list[SupplierProductIssueLink]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A03']


def supplier_product_handoff_schemas():
    schemas = supplier_quote_schemas()
    schemas.register_kind('SupplierProductHandoffBasis', SupplierProductHandoffBasisView, str)
    return schemas


def prepare_supplier_product_handoff(saved, *, context, reading, basis_ref, validate_current):
    """Check actual proposal lines and retained design gates; no native submission."""
    if (not isinstance(saved, SavedSupplierProduct) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A03'
            or not callable(validate_current)):
        raise ValueError('Product handoff requires saved original A02 evidence and current authorized A03 reading')
    reading.check_method_context(context, 'SUPPLIER-A03')
    if (saved.current_context != context or saved.identity.run_id != context.run_id
            or saved.identity.action_id != 'SUPPLIER-A02' or saved.identity.role != 'Supplier'
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Product handoff changes original run, Supplier, context or assembly evidence')
    if saved.result.kind != 'completed' or saved.result.payload.choice not in {'propose_original', 'propose_substitute'}:
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_product_proposal'],
            'requested_refs': [saved.action_input.inquiry_ref]}
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A02',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': task_digest(saved.result.model_dump(mode='json')),
        'operation_id': saved.context.operation_id, 'result_kind': 'completed'}
    if (any(saved.audit.get(key) != value for key, value in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Product handoff lacks its original successful authorized audit')
    now = context.business_time
    try:
        basis = reading.resolve(Reference.model_validate(basis_ref))
        if not isinstance(basis, SupplierProductHandoffBasisView):
            raise ValueError('Product handoff requires its concrete original source relation')
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'product_task_sha256': saved.identity.key, 'product_record_sha256': saved.record_sha256,
            'product_result_sha256': expected_audit['result_sha256'], 'product_audit_sha256': task_digest(saved.audit),
            'product_source_reading_sha256': saved.source_reading_sha256}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.available_at.clock_ref != now.clock_ref or basis.available_at.offset > now.offset
                or not basis.effective_window.contains(now)):
            raise ValueError('Product relation changes original evidence, scope or current time')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Product relation lacks original Supplier author authority')
        originals = [row for row in saved.source_reading
            if Reference.model_validate(row['ref']) == saved.action_input.inquiry_ref]
        if len(originals) != 1:
            raise ValueError('Product handoff lacks its original retained inquiry')
        original_inquiry = SupplyInquiryView.model_validate(originals[0]['projection'])
        inquiry = reading.resolve(saved.action_input.inquiry_ref)
        if (not isinstance(inquiry, QuoteInquiryView)
                or SupplyInquiryView.model_validate({key: inquiry.model_dump(mode='python')[key]
                    for key in SupplyInquiryView.model_fields}) != original_inquiry):
            raise ValueError('Quote inquiry substitutes the original product inquiry fields or version')
        unique_refs(basis.proposal_refs)
        proposals, actual_lines = {}, {}
        if set(basis.proposal_sha256s) != {ref.id for ref in basis.proposal_refs}:
            raise ValueError('Product relation lacks exact digests for its selected proposals')
        for ref in basis.proposal_refs:
            proposal = reading.resolve(ref)
            if (not isinstance(proposal, QuoteProposalView) or proposal.ref != ref
                    or proposal.inquiry_ref != original_inquiry.ref or proposal.supplier_organization_id != reading.organization_id
                    or task_digest(proposal.model_dump(mode='json')) != basis.proposal_sha256s[ref.id]
                    or proposal.available_at.clock_ref != now.clock_ref or proposal.available_at.offset > now.offset):
                raise ValueError('Quote product source changes original proposal/version/inquiry/Supplier')
            if proposal.status in {'withdrawn', 'rejected'} or not proposal.effective_window.contains(now):
                return {'kind': 'needs_information', 'missing_fields': ['current_original_product_proposal'], 'requested_refs': [ref]}
            proposals[ref.key()] = proposal
            actual_lines.update({(ref.key(), line.local_key): line.product for line in proposal.lines})
        links, lines = basis.line_links, saved.result.payload.lines
        if (len(links) != len(lines) or len(links) != len(actual_lines)
                or {link.product_line_index for link in links} != set(range(len(lines)))
                or {(link.proposal_ref.key(), link.proposal_line_key) for link in links} != set(actual_lines)):
            raise ValueError('Product relation adds, drops or repeats original proposed lines')
        for link in links:
            if QuoteProductLine.model_validate(lines[link.product_line_index].model_dump(mode='python')) != actual_lines[
                    (link.proposal_ref.key(), link.proposal_line_key)]:
                raise ValueError('Quote product source changes original product, quantity, destination or requirements/deviations')
        unique_refs([link.issue_ref for link in basis.issue_links])
        if {link.issue_ref.key() for link in basis.issue_links} != {ref.key() for ref in saved.result.payload.unresolved_refs}:
            raise ValueError('Product relation omits or adds original unresolved design issues')
        unresolved_requirements = set()
        for link in basis.issue_links:
            requirement = reading.resolve(link.requirement_ref)
            if (not isinstance(requirement, QuoteRequirementView) or requirement.inquiry_ref != inquiry.ref
                    or requirement.product_proposal_ref is None or requirement.product_proposal_ref.key() not in proposals):
                raise ValueError('Design issue gate names another original inquiry or proposal')
            proposal = proposals[requirement.product_proposal_ref.key()]
            if link.resolution_evidence_ref is None:
                if (proposal.status != 'pending_confirmation' or link.requirement_ref not in
                        [proposal.confirmation_requirement_ref, *proposal.prerequisite_refs]):
                    raise ValueError('Unresolved original design issue loses its quote confirmation gate')
                unresolved_requirements.add(link.requirement_ref.key())
        unique_refs(basis.relation_evidence_refs)
        observed = [*basis.relation_evidence_refs,
            *(link.resolution_evidence_ref for link in basis.issue_links if link.resolution_evidence_ref is not None)]
        for ref in {ref.key(): ref for ref in [*basis.evidence_refs, *observed, *grant.basis_refs, *assignment.basis_refs,
                *(ref for proposal in proposals.values() for ref in proposal.evidence_refs)]}.values():
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.effective_window is not None and not row.effective_window.contains(now)
                    or ref in observed and row.basis_kind != 'observed'):
                raise ValueError('Product relation and independent issue resolution require current observed evidence')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True),
                basis=basis.model_copy(deep=True), proposals=tuple(row.model_copy(deep=True) for row in proposals.values())) is not True:
            raise ValueError('Actual product source and independent issue resolution require explicit host validation')
        return {'kind': 'prepared', 'product_proposal_refs': list(basis.proposal_refs),
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'product_record_sha256': saved.record_sha256,
            'product_result_sha256': expected_audit['result_sha256'],
            'unresolved_confirmation_count': len(unresolved_requirements)}
    finally:
        reading.recheck()
