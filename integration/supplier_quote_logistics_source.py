"""Adopt an existing delivery assessment without inventing routes or capacity."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import (
    EvidenceRecord, Reference, StrictRecord, TextId, ValueState, ref_type, walk_references,
)
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quote_objects import (
    QuoteDelivery, QuoteInquiryView, QuoteLogisticsView, QuoteProposalView,
)
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierLogisticsSourceDigest(StrictRecord):
    ref: Reference
    sha256: Digest


class SupplierQuoteLogisticsSourceView(GovReviewAuthored):
    """Host projection of an actual assessment with its original complete plan."""
    ref: ref_type('SupplierQuoteLogisticsSource')
    run_id: TextId
    supplier_organization_id: TextId
    product_proposal_ref: ref_type('ProductProposal')
    inquiry_ref: ref_type('SupplyInquiry')
    feasible: ValueState[bool]
    prerequisite_refs: list[ref_type('Requirement')]
    deliveries: Annotated[list[QuoteDelivery], Field(min_length=1)]
    dependency_digests: Annotated[list[SupplierLogisticsSourceDigest], Field(min_length=1)]
    original_record_sha256: Digest
    original_record_evidence_ref: ref_type('Evidence')


class SupplierQuoteLogisticsAdoptionView(GovReviewAuthored):
    """Independent Supplier adoption of one exact assessment and target ref."""
    ref: ref_type('SupplierQuoteLogisticsAdoption')
    run_id: TextId
    organization_id: TextId
    source_ref: ref_type('SupplierQuoteLogisticsSource')
    source_sha256: Digest
    logistics_ref: ref_type('LogisticsAssessment')
    adoption_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A03']


def add_supplier_quote_logistics_schemas(schemas):
    schemas.register_kind('SupplierQuoteLogisticsSource', SupplierQuoteLogisticsSourceView, str)
    schemas.register_kind('SupplierQuoteLogisticsAdoption', SupplierQuoteLogisticsAdoptionView, str)
    return schemas


def prepare_supplier_quote_logistics(*, context, reading, adoption_ref, validate_current):
    """Copy original feasibility, prerequisites and deliveries at the current time.

    No routing, pricing, capacity calculation, reservation or professional
    approval happens here. A03 retains its original completeness and shared
    resource checks. Publish at a fresh authorized token before quote execution.
    """
    if (not isinstance(reading, ActionReadView) or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != 'SUPPLIER-A03' or not callable(validate_current)):
        raise ValueError('Logistics production requires original A03 reading and actual source validation')
    reading.check_method_context(context, 'SUPPLIER-A03')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Logistics source requires its exact concrete original projection')
        return row

    def current(row):
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Logistics source, adoption, inquiry or proposal is unavailable now')

    def author(row, *, supplier=False):
        grant = read(row.author_authority_ref, Authorization)
        assignment = reading.resolve(row.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.function_ref != row.author_function_ref
                or supplier and assignment.role != 'Supplier'
                or grant.organization_id != row.author_organization_id or grant.actor_id != row.author_actor_id
                or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, row.scope) for scope in grant.scopes)
                or row.authored_at.clock_ref != now.clock_ref or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at) or not grant.validity.contains(row.authored_at)):
            raise ValueError('Logistics record or adoption lacks its original author authority')
        return [*grant.basis_refs, *assignment.basis_refs]

    try:
        adoption = read(Reference.model_validate(adoption_ref), SupplierQuoteLogisticsAdoptionView)
        source = read(adoption.source_ref, SupplierQuoteLogisticsSourceView)
        current(adoption); current(source)
        if (adoption.run_id != context.run_id or source.run_id != context.run_id
                or adoption.organization_id != reading.organization_id
                or adoption.author_organization_id != reading.organization_id
                or source.supplier_organization_id != reading.organization_id
                or adoption.scope != context.scope or not scope_covers(source.scope, adoption.scope)
                or task_digest(source.model_dump(mode='json')) != adoption.source_sha256):
            raise ValueError('Logistics adoption changes original Supplier, run, scope or source digest')
        inquiry = read(source.inquiry_ref, QuoteInquiryView)
        proposal = read(source.product_proposal_ref, QuoteProposalView)
        current(proposal)
        if (inquiry.received_at.clock_ref != now.clock_ref or inquiry.received_at.offset > now.offset
                or not inquiry.response_window.contains(now)):
            raise ValueError('Original logistics inquiry is not received within its response window')
        if (inquiry.recipient_organization_id != reading.organization_id
                or inquiry.recipient_id != context.actor_id or not scope_covers(context.scope, inquiry.scope)
                or proposal.supplier_organization_id != reading.organization_id or proposal.inquiry_ref != inquiry.ref):
            raise ValueError('Logistics source changes original inquiry recipient, scope or proposal')
        # Every original plan dependency is bound to exact content as well as ref version.
        dependencies = {ref.key(): ref for ref in [source.inquiry_ref, source.product_proposal_ref,
            *source.prerequisite_refs, *walk_references(source.feasible), *walk_references(source.deliveries)]}
        unique_refs([row.ref for row in source.dependency_digests])
        if {row.ref.key() for row in source.dependency_digests} != set(dependencies):
            raise ValueError('Logistics source must bind all and only original plan dependencies')
        resolved = []
        for row in source.dependency_digests:
            value = reading.resolve(row.ref)
            if task_digest(value.model_dump(mode='json')) != row.sha256:
                raise ValueError('Original logistics dependency content changed')
            resolved.append(value.model_copy(deep=True))
        if len({row.local_key for row in source.deliveries}) != len(source.deliveries):
            raise ValueError('Original delivery batch identity repeated')
        authority_refs = [*author(adoption, supplier=True), *author(source)]
        unique_refs(adoption.adoption_evidence_refs)
        source_evidence = [*source.evidence_refs, source.original_record_evidence_ref,
            *(ref for ref in dependencies.values() if ref.kind == 'Evidence')]
        if set(adoption.adoption_evidence_refs).intersection(source_evidence):
            raise ValueError('Logistics source evidence cannot replace independent Supplier adoption')
        evidence_refs = list({ref.key(): ref for ref in [*adoption.evidence_refs,
            *adoption.adoption_evidence_refs, *source_evidence, *inquiry.evidence_refs,
            *proposal.evidence_refs, *authority_refs]}.values())
        for ref in evidence_refs:
            evidence = read(ref, EvidenceRecord)
            if (evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or ref in [source.original_record_evidence_ref, *adoption.adoption_evidence_refs]
                    and evidence.basis_kind != 'observed'
                    or ref == source.original_record_evidence_ref and evidence.content_hash != source.original_record_sha256):
                raise ValueError('Logistics original record and adoption require current observed evidence')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if (adoption.logistics_ref not in context.visible_refs or not any(isinstance(grant, Authorization)
                and grant.organization_id == reading.organization_id and grant.actor_id == context.actor_id
                and grant.function_ref == context.function_ref and 'SUPPLIER-A03' in grant.action_ids
                and grant.validity.contains(now) and adoption.logistics_ref in grant.readable_refs
                and any(scope_covers(scope, context.scope) for scope in grant.scopes) for grant in grants)):
            raise ValueError('Produced logistics target lacks original explicit current read authority')
        if validate_current(context=context.model_copy(deep=True), adoption=adoption.model_copy(deep=True),
                source=source.model_copy(deep=True), inquiry=inquiry.model_copy(deep=True),
                proposal=proposal.model_copy(deep=True), dependencies=resolved) is not True:
            raise ValueError('Actual original assessment, dependencies and adoption require host verification')
        projection = QuoteLogisticsView(ref=adoption.logistics_ref,
            supplier_organization_id=reading.organization_id, product_proposal_ref=proposal.ref, inquiry_ref=inquiry.ref,
            available_at=now, effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
            feasible=source.feasible.model_copy(deep=True), prerequisite_refs=list(source.prerequisite_refs),
            deliveries=[row.model_copy(deep=True) for row in source.deliveries], evidence_refs=evidence_refs)
        return {'kind': 'prepared', 'logistics_projection': projection,
            'logistics_sha256': task_digest(projection.model_dump(mode='json')),
            'source_sha256': adoption.source_sha256, 'original_record_sha256': source.original_record_sha256,
            'adoption_sha256': task_digest(adoption.model_dump(mode='json')),
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'dependency_digests': [row.model_dump(mode='json') for row in source.dependency_digests],
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'limitations': ['Snapshot only; publish at a fresh authorized read token.',
                'Original plan/unknown states retained; no routing, cost, capacity, reservation or approval inferred.']}
    finally:
        reading.recheck()
