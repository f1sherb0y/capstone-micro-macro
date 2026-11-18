"""Bind saved screening to an actual received product inquiry without creating demand."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_screening_results import SavedSupplierScreening
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.actions.contracts.supplier_product_objects import ProductRequirementView, supplier_product_schemas
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierScreeningRequirementLink(StrictRecord):
    original_requirement_ref: ref_type('Requirement')
    current_requirement_ref: ref_type('Requirement')
    current_requirement_sha256: Digest


class SupplierScreeningHandoffBasisView(GovReviewAuthored):
    ref: ref_type('SupplierScreeningHandoffBasis')
    run_id: TextId
    organization_id: TextId
    screening_task_sha256: Digest
    screening_record_sha256: Digest
    screening_result_sha256: Digest
    screening_audit_sha256: Digest
    screening_source_reading_sha256: Digest
    inquiry_ref: ref_type('SupplyInquiry')
    inquiry_sha256: Digest
    requirement_links: Annotated[list[SupplierScreeningRequirementLink], Field(min_length=1)]
    received_source_sha256: Digest
    received_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A02']


def supplier_screening_handoff_schemas():
    schemas = supplier_product_schemas()
    schemas.register_kind('SupplierScreeningHandoffBasis', SupplierScreeningHandoffBasisView, str)
    return schemas


def prepare_supplier_screening_handoff(saved, *, context, reading, basis_ref, inquiry_ref, requirement_refs, validate_current):
    """Require actual independently received scope and complete requirement correspondence."""
    if (not isinstance(saved, SavedSupplierScreening) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A02'
            or not callable(validate_current)):
        raise ValueError('Screening handoff requires original saved A01 and actual authorized A02 reading')
    reading.check_method_context(context, 'SUPPLIER-A02')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A01'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Screening handoff changes original Supplier, task, input/context or retained sources')
    if saved.result.kind != 'completed' or saved.result.payload.choice == 'track_market':
        return {'kind': 'needs_information', 'missing_fields': ['original_selected_received_inquiry'],
            'requested_refs': list(saved.action_input.inquiry_refs)}
    payload = saved.result.payload
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A01',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Screening handoff lacks original successful authorized audit')
    now = context.business_time
    try:
        basis = reading.resolve(Reference.model_validate(basis_ref))
        if (not isinstance(basis, SupplierScreeningHandoffBasisView)
                or basis.available_at.clock_ref != now.clock_ref or basis.available_at.offset > now.offset
                or not basis.effective_window.contains(now)):
            raise ValueError('Screening relation requires exact current concrete basis')
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'screening_task_sha256': saved.identity.key, 'screening_record_sha256': saved.record_sha256,
            'screening_result_sha256': result_sha, 'screening_audit_sha256': task_digest(saved.audit),
            'screening_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Screening relation substitutes original saved evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Screening relation lacks independent Supplier author authority')
        if payload.inquiry_ref not in saved.action_input.inquiry_refs:
            raise ValueError('Screening result substitutes originally selected inquiry')
        rows = [row for row in saved.source_reading if Reference.model_validate(row['ref']) == payload.inquiry_ref]
        if len(rows) != 1:
            raise ValueError('Screening handoff lacks original retained inquiry')
        original = SupplyInquiryView.model_validate(rows[0]['projection'])
        if original.ref != payload.inquiry_ref:
            raise ValueError('Retained screening inquiry changes its original reference')
        selected = Reference.model_validate(inquiry_ref)
        inquiry = reading.resolve(selected)
        if (not isinstance(inquiry, SupplyInquiryView) or inquiry.ref != selected or basis.inquiry_ref != selected
                or task_digest(inquiry.model_dump(mode='json')) != basis.inquiry_sha256
                or inquiry.buyer_id != original.buyer_id or inquiry.recipient_organization_id != reading.organization_id
                or inquiry.recipient_id != context.actor_id or inquiry.received_at.clock_ref != now.clock_ref
                or not original.received_at.offset <= inquiry.received_at.offset <= now.offset
                or not scope_covers(context.scope, inquiry.scope)):
            raise ValueError('Product inquiry changes original buyer, recipient, selected version or available scope')
        if inquiry.ref == original.ref and inquiry.model_dump(mode='json') != original.model_dump(mode='json'):
            raise ValueError('Received inquiry cannot change content under the original immutable reference')
        if inquiry.status != 'active' or not inquiry.response_window.contains(now):
            return {'kind': 'needs_information', 'missing_fields': ['current_active_received_inquiry_response_window'],
                'requested_refs': [inquiry.ref]}
        if payload.choice == 'clarify':
            if inquiry.model_dump(mode='json') != original.model_dump(mode='json'):
                raise ValueError('Clarification handoff substitutes original unresolved inquiry')
            allowed = original.lines
        elif payload.choice in {'respond', 'limited_scope'}:
            allowed = [line for line in original.lines if any(scope_covers(scope, line.scope) for scope in payload.offered_scope_refs)]
            if payload.choice == 'respond' and len(allowed) != len(original.lines):
                raise ValueError('Full screening response loses original inquiry scope')
            if payload.choice == 'limited_scope' and not original.allow_partial_scope:
                raise ValueError('Limited screening scope lacks original buyer permission')
        else:
            raise ValueError('Unsupported original screening branch')
        links = basis.requirement_links
        unique_refs([link.original_requirement_ref for link in links])
        unique_refs([link.current_requirement_ref for link in links])
        if ({link.original_requirement_ref for link in links} != {line.requirement_ref for line in allowed}
                or {link.current_requirement_ref for link in links} != {line.requirement_ref for line in inquiry.lines}):
            raise ValueError('Product inquiry must preserve the complete originally offered line correspondence')
        old_lines = {line.requirement_ref: line for line in allowed}
        new_lines = {line.requirement_ref: line for line in inquiry.lines}
        requirements = []
        for link in links:
            prior, current = old_lines[link.original_requirement_ref], new_lines[link.current_requirement_ref]
            if prior.model_dump(mode='json', exclude={'requirement_ref'}) != current.model_dump(mode='json', exclude={'requirement_ref'}):
                raise ValueError('Received product inquiry changes original quantity, region, scope, function or window')
            row = reading.resolve(link.current_requirement_ref)
            if (not isinstance(row, ProductRequirementView) or row.ref != link.current_requirement_ref
                    or row.inquiry_ref != inquiry.ref or row.scope != current.scope
                    or task_digest(row.model_dump(mode='json')) != link.current_requirement_sha256):
                raise ValueError('Product requirement substitutes actual received inquiry line or version')
            requirements.append(row)
        actual_refs = [Reference.model_validate(ref) for ref in requirement_refs]
        unique_refs(actual_refs)
        if set(actual_refs) != {line.requirement_ref for line in inquiry.lines}:
            raise ValueError('Product input loses complete actual inquiry requirements')
        if payload.choice == 'clarify' and not set(payload.requirement_refs) <= set(actual_refs):
            raise ValueError('Product input drops original clarification requirements')
        unique_refs(basis.relation_evidence_refs)
        if basis.received_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Received inquiry evidence cannot replace independent source relation')
        refs = [*basis.evidence_refs, *basis.relation_evidence_refs, basis.received_evidence_ref,
            *original.evidence_refs, *inquiry.evidence_refs, *grant.basis_refs, *assignment.basis_refs,
            *[ref for row in requirements for ref in row.evidence_refs]]
        for ref in {ref.key(): ref for ref in refs}.values():
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or ref in [basis.received_evidence_ref, *basis.relation_evidence_refs] and evidence.basis_kind != 'observed'
                    or ref == basis.received_evidence_ref and evidence.content_hash != basis.received_source_sha256):
                raise ValueError('Actual received inquiry and relation require exact current observed evidence')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                original=original.model_copy(deep=True), inquiry=inquiry.model_copy(deep=True), requirements=deepcopy(requirements)) is not True:
            raise ValueError('Actual buyer inquiry, partial scope acceptance and requirement provenance require host verification')
        return {'kind': 'prepared', 'inquiry_ref': selected, 'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'screening_record_sha256': saved.record_sha256, 'screening_result_sha256': result_sha,
            'limitations': ['Source relation only; original A02 product evidence and independent design checks remain required.']}
    finally:
        reading.recheck()
