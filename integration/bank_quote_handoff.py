"""Relate original saved A04 terms to an actual registered offer for A05."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.bank_quote_results import SavedBankQuote
from src.actions.contracts.bank_arrangement_objects import ArrangementOfferView, bank_arrangement_schemas
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.bank_quote_objects import QuoteReservationView, QuoteAuthorityPolicyView
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.models import Digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class BankQuoteHandoffBasisView(GovReviewAuthored):
    ref: ref_type('BankQuoteHandoffBasis')
    run_id: TextId
    organization_id: TextId
    quote_task_sha256: Digest
    quote_record_sha256: Digest
    quote_input_sha256: Digest
    quote_context_sha256: Digest
    quote_result_sha256: Digest
    quote_audit_sha256: Digest
    quote_source_reading_sha256: Digest
    offer_ref: ref_type('FinanceOffer')
    offer_sha256: Digest
    native_offer_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['BANK-A05']


def bank_quote_handoff_schemas():
    schemas = bank_arrangement_schemas()
    schemas.register_kind('BankQuoteHandoffBasis', BankQuoteHandoffBasisView, str)
    # Original A04 mandates may cite their typed quote policy as authority
    # basis. A05 must read that same policy, without dropping the grant basis.
    schemas.register_kind('QuoteAuthorityPolicy', QuoteAuthorityPolicyView, str)
    return schemas


def prepare_bank_quote_handoff(saved, *, context, reading, basis_ref, offer_ref, validate_current):
    """Check actual registration and original terms; never publish an offer."""
    if (not isinstance(saved, SavedBankQuote) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A05'
            or not callable(validate_current)):
        raise ValueError('Quote handoff requires saved A04 and independently authorized current A05')
    reading.check_method_context(context, 'BANK-A05')
    if (saved.current_context != context or saved.identity.action_id != 'BANK-A04' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.result.kind != 'completed'):
        raise ValueError('Quote handoff substitutes original task, recipient or source content')
    if saved.result.payload.choice not in {'offer', 'conditional_offer'}:
        return {'kind': 'needs_information', 'missing_fields': ['original_bank_quotation_offer'],
            'requested_refs': [saved.action_input.application_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise ValueError('Quote handoff changes the actually audited original quotation')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Quote handoff requires exact original source schemas and versions')
        return row

    try:
        basis = read(basis_ref, BankQuoteHandoffBasisView)
        offer = read(offer_ref, ArrangementOfferView)
        application = read(offer.application_ref, FinanceApplicationView)
        reservation = read(offer.reservation_policy_ref, QuoteReservationView)
        original_authority = read(offer.authority_ref, Authorization)
        expected = {'quote_task_sha256': saved.identity.key, 'quote_record_sha256': saved.record_sha256,
            'quote_input_sha256': saved.identity.input_sha256, 'quote_context_sha256': saved.identity.context_sha256,
            'quote_result_sha256': result_sha, 'quote_audit_sha256': task_digest(saved.audit),
            'quote_source_reading_sha256': saved.source_reading_sha256,
            'offer_sha256': task_digest(offer.model_dump(mode='json'))}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or basis.offer_ref != offer.ref or offer.lender_id != saved.identity.organization_id
                or offer.application_ref != saved.action_input.application_ref
                or offer.author_actor_id != saved.context.actor_id or offer.author_function_ref != saved.context.function_ref
                or offer.authority_ref != saved.action_input.authority_ref
                or offer.terms.model_dump(mode='json') != saved.result.payload.terms.model_dump(mode='json')
                or offer.reservation_policy_ref != saved.result.payload.reservation_policy_ref
                or application.lender_id != offer.lender_id or offer.terms.borrower_id != application.borrower_id
                or offer.scope_ref != application.scope_ref or basis.scope != offer.scope_ref
                or not scope_covers(saved.context.scope, offer.scope_ref)):
            raise ValueError('Quote relation changes original terms, application, lender, borrower, author or scope')
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        for row in (application, reservation, original_authority):
            if originals.get(row.ref.key()) != row.model_dump(mode='json'):
                raise ValueError('Registered offer changes the original application, reservation policy or quote authority')
        times = [saved.context.business_time, offer.issued_at, offer.available_at,
            basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or not basis.effective_window.contains(basis.authored_at)
                or not basis.effective_window.contains(context.business_time)):
            raise ValueError('Quote relation changes original registration, observation or independent author chronology')

        original_assignment = reading.resolve(offer.author_function_ref)
        required_reads = {ref.key() for value in (saved.action_input, saved.result.payload)
            for ref in walk_references(value)}
        if (not isinstance(original_assignment, RoleAssignment) or original_assignment.role != 'Bank'
                or original_assignment.function_ref != offer.author_function_ref
                or originals.get(offer.author_function_ref.key()) != original_assignment.model_dump(mode='json')
                or original_authority.function_ref != offer.author_function_ref
                or original_authority.actor_id != offer.author_actor_id
                or original_authority.organization_id != offer.lender_id
                or 'BANK-A04' not in original_authority.action_ids
                or not original_authority.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, offer.scope_ref) for scope in original_authority.scopes)
                or not required_reads <= {ref.key() for ref in original_authority.readable_refs}):
            raise ValueError('Registered offer lacks original independently authorized quotation authorship')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        authored_reads = {ref.key() for ref in (offer.ref, basis.native_evidence_ref,
            *offer.evidence_refs, *basis.evidence_refs, *basis.relation_evidence_refs)}
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Bank'
                or assignment.function_ref != basis.author_function_ref or grant.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or basis.author_action_id not in grant.action_ids
                or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not authored_reads <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Quote relation lacks independent original author authority')
        unique_refs(basis.relation_evidence_refs)
        if basis.native_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native offer evidence cannot replace independent quotation relation evidence')
        handoff_evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs, basis.native_evidence_ref]
        for row in (grant, assignment):
            for ref in row.basis_refs:
                if ref.kind == 'Evidence':
                    handoff_evidence_refs.append(ref)
                else:
                    reading.resolve(ref)
        original_authority_evidence_refs = []
        for row in (original_authority, original_assignment):
            for ref in row.basis_refs:
                current_basis = reading.resolve(ref)
                if originals.get(ref.key()) != current_basis.model_dump(mode='json'):
                    raise ValueError('Quote authority basis changes its original saved source content')
                if ref.kind == 'Evidence':
                    original_authority_evidence_refs.append(ref)
        # Each fact retains its own occurrence time. Shared evidence must be
        # applicable at every use; current application/policy checks stay current.
        for point, refs in ((saved.context.business_time, original_authority_evidence_refs),
                (offer.issued_at, offer.evidence_refs), (basis.authored_at, handoff_evidence_refs),
                (context.business_time, [*application.evidence_refs, *reservation.evidence_refs])):
            for ref in refs:
                evidence = read(ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(point)
                        or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                    raise ValueError('Quote relation contains unavailable or unobserved relation evidence')
        native = read(basis.native_evidence_ref, EvidenceRecord)
        if native.basis_kind != 'observed' or native.content_hash != basis.native_source_sha256:
            raise ValueError('Quote handoff requires observed actual native offer registration')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True), offer=offer.model_copy(deep=True),
                application=application.model_copy(deep=True), reservation=reservation.model_copy(deep=True),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise ValueError('Quote handoff requires actual current host registration and independent relation validation')
        return {'kind': 'prepared', 'source_mode': reading._resolver.source_mode,
            'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
                'basis_sha256': task_digest(basis.model_dump(mode='json')),
                'native_offer_id': basis.native_offer_id, 'native_event_id': basis.native_event_id}}
    finally:
        reading.recheck()
