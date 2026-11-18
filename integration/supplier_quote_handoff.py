"""Relate a saved A03 quote to an already existing authorized SupplyOffer for A04."""
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_quote_results import SavedSupplierQuote
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, TimeWindow, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.supplier_order_objects import FormationOfferView, OrderDeliveryLine, supplier_order_schemas
from src.actions.contracts.supplier_quote_objects import QuoteInquiryView
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierQuoteOfferLineLink(StrictRecord):
    quote_line_index: Annotated[int, Field(ge=0)]
    offer_line_key: TextId


class SupplierQuoteOfferBasisView(GovReviewAuthored):
    """Independently authored source relation; this grants no native registration right."""
    ref: ref_type('SupplierQuoteOfferBasis')
    run_id: TextId
    organization_id: TextId
    quote_task_sha256: Digest
    quote_record_sha256: Digest
    quote_input_sha256: Digest
    quote_context_sha256: Digest
    quote_result_sha256: Digest
    quote_audit_sha256: Digest
    quote_source_reading_sha256: Digest
    offer_ref: ref_type('SupplyOffer')
    offer_projection_sha256: Digest
    native_offer_source_sha256: Digest
    native_offer_evidence_ref: ref_type('Evidence')
    line_links: Annotated[list[SupplierQuoteOfferLineLink], Field(min_length=1)]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A04']


def supplier_quote_handoff_schemas():
    schemas = supplier_order_schemas()
    schemas.register_kind('SupplierQuoteOfferBasis', SupplierQuoteOfferBasisView, str)
    return schemas


def prepare_supplier_quote_handoff(saved, *, context, reading, basis_ref, validate_current):
    """Match complete quote lines to actual offer lines, without creating or submitting an offer."""
    if (not isinstance(saved, SavedSupplierQuote) or not isinstance(reading, ActionReadView)
            or context.contract_ref.id != 'SUPPLIER-A04' or not callable(validate_current)):
        raise ValueError('Quote handoff requires saved original A03 evidence and current authorized A04 reading')
    reading.check_method_context(context, 'SUPPLIER-A04')
    if (saved.current_context != context or saved.identity.run_id != context.run_id
            or saved.identity.role != 'Supplier' or saved.identity.action_id != 'SUPPLIER-A03'
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Quote handoff changes original run, Supplier, input/context or source snapshot')
    if saved.result.kind != 'completed' or saved.result.payload.choice != 'quote':
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_supplier_quote'],
                'requested_refs': [saved.action_input.inquiry_ref]}
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A03',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': task_digest(saved.result.model_dump(mode='json')),
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(key) != value for key, value in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Quote handoff lacks its original successful authorized audit')
    now = context.business_time
    try:
        basis = reading.resolve(Reference.model_validate(basis_ref))
        if not isinstance(basis, SupplierQuoteOfferBasisView):
            raise ValueError('Quote handoff requires its concrete original source relation')
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'quote_task_sha256': saved.identity.key, 'quote_record_sha256': saved.record_sha256,
            'quote_input_sha256': saved.identity.input_sha256, 'quote_context_sha256': saved.identity.context_sha256,
            'quote_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'quote_audit_sha256': task_digest(saved.audit), 'quote_source_reading_sha256': saved.source_reading_sha256}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.available_at.clock_ref != now.clock_ref or basis.available_at.offset > now.offset
                or not basis.effective_window.contains(now)):
            raise ValueError('Quote relation substitutes original evidence or is outside current scope/time')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Quote relation lacks independent original Supplier author authority')
        offer = reading.resolve(basis.offer_ref)
        if (not isinstance(offer, FormationOfferView) or offer.ref != basis.offer_ref
                or task_digest(offer.model_dump(mode='json')) != basis.offer_projection_sha256
                or offer.supplier_organization_id != reading.organization_id or not scope_covers(context.scope, offer.scope)
                or offer.available_at.clock_ref != now.clock_ref or offer.available_at.offset > now.offset):
            raise ValueError('Quote relation changes original actual SupplyOffer version or recipient')
        if offer.status != 'active':
            return {'kind': 'needs_information', 'missing_fields': ['active_original_supply_offer'], 'requested_refs': [offer.ref]}
        draft = saved.result.payload.offer
        if (offer.buyer_id != draft.buyer_id or offer.payer_id != draft.payer_id or offer.terms_ref != draft.terms_ref
                or offer.validity_ref != draft.validity_ref or offer.condition_refs != list(draft.condition_refs)):
            raise ValueError('Native offer changes original quoted buyer, payer, terms, validity or prerequisites')
        validity = reading.resolve(offer.validity_ref)
        if not isinstance(validity, TimeWindow) or not validity.contains(now):
            return {'kind': 'needs_information', 'missing_fields': ['current_original_supply_offer_validity'], 'requested_refs': [offer.validity_ref]}
        links = basis.line_links
        offer_lines = {row.local_key: row.delivery for row in offer.lines}
        if (len(links) != len(draft.lines) or len(links) != len(offer_lines)
                or {link.quote_line_index for link in links} != set(range(len(draft.lines)))
                or {link.offer_line_key for link in links} != set(offer_lines)):
            raise ValueError('Quote relation omits, duplicates or adds an original quote/offer line')
        for link in links:
            original = OrderDeliveryLine.model_validate(draft.lines[link.quote_line_index].model_dump(mode='python'))
            if original != offer_lines[link.offer_line_key]:
                raise ValueError('Native offer changes original product/version, quantity, price, destination, window or services')
        inquiries = [row for row in saved.source_reading if Reference.model_validate(row['ref']) == saved.action_input.inquiry_ref]
        if len(inquiries) != 1:
            raise ValueError('Quote relation lacks original retained inquiry evidence')
        inquiry = QuoteInquiryView.model_validate(inquiries[0]['projection'])
        if inquiry.scope != offer.scope or inquiry.buyer_id != offer.buyer_id:
            raise ValueError('Native offer changes the original quoted inquiry scope or buyer')
        unique_refs(basis.relation_evidence_refs)
        if basis.native_offer_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native offer source evidence cannot substitute independent quote relation evidence')
        evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs, basis.native_offer_evidence_ref,
                         *offer.evidence_refs, *grant.basis_refs, *assignment.basis_refs]
        for ref in {ref.key(): ref for ref in evidence_refs}.values():
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.effective_window is not None and not row.effective_window.contains(now)
                    or ref in [*basis.relation_evidence_refs, basis.native_offer_evidence_ref] and row.basis_kind != 'observed'
                    or ref == basis.native_offer_evidence_ref and row.content_hash != basis.native_offer_source_sha256):
                raise ValueError('Actual offer/relation evidence is not current and independently observed')
        from copy import deepcopy
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True),
                basis=basis.model_copy(deep=True), offer=offer.model_copy(deep=True)) is not None:
            raise ValueError('Actual native registration and original quote relation require current host validation')
        return {'kind': 'prepared', 'offer_ref': offer.ref, 'offer_projection_sha256': basis.offer_projection_sha256,
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'quote_record_sha256': saved.record_sha256,
            'quote_result_sha256': basis.quote_result_sha256, 'native_offer_source_sha256': basis.native_offer_source_sha256,
            'limitations': ['Source relation only; A04 independently checks the actual proposed order and each party acceptance.',
                           'No native offer creation, reservation, order formation or cash effect.']}
    finally:
        reading.recheck()
