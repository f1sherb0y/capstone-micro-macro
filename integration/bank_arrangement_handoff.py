"""Relate saved A05 confirmation to actual registered facility sources for A06."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from integration.bank_arrangement_results import SavedBankArrangement
from src.actions.contracts.bank_arrangement_objects import ArrangementAcceptanceView, ArrangementOfferView
from src.actions.contracts.bank_draw_objects import (
    BankDrawArrangementView, BankDrawConditionView, BankDrawTermsView, bank_draw_schemas,
)
from src.actions.contracts.bank_quote_objects import QuoteConditionView
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_financing_objects import FinancingTerms
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.models import Digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class BankArrangementRecordView(CostSource):
    """Host-supplied original registration, never constructed by this bridge."""
    ref: ref_type('BankArrangementRecord')
    run_id: TextId
    lender_id: TextId
    borrower_id: TextId
    offer_ref: ref_type('FinanceOffer')
    offer_sha256: Digest
    acceptance_ref: ref_type('PartyAcceptance')
    acceptance_sha256: Digest
    confirmation_task_sha256: Digest
    confirmed_conditions_sha256: Digest
    accepted_terms: FinancingTerms
    arrangement_ref: ref_type('FinanceArrangement')
    arrangement_sha256: Digest
    terms_ref: ref_type('FinanceTerms')
    terms_sha256: Digest
    signed_at: TimePoint
    native_arrangement_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class BankArrangementConditionRelation(StrictRecord):
    original_ref: ref_type('Requirement')
    original_sha256: Digest
    current_ref: ref_type('Requirement')
    current_sha256: Digest


class BankArrangementHandoffBasisView(GovReviewAuthored):
    ref: ref_type('BankArrangementHandoffBasis')
    run_id: TextId
    organization_id: TextId
    formation_task_sha256: Digest
    formation_record_sha256: Digest
    formation_input_sha256: Digest
    formation_context_sha256: Digest
    formation_result_sha256: Digest
    formation_audit_sha256: Digest
    formation_source_reading_sha256: Digest
    native_record_ref: ref_type('BankArrangementRecord')
    native_record_sha256: Digest
    condition_relations: list[BankArrangementConditionRelation]
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['BANK-A06']


def bank_arrangement_handoff_schemas():
    schemas = bank_draw_schemas()
    schemas.register_kind('BankArrangementRecord', BankArrangementRecordView, str)
    schemas.register_kind('BankArrangementHandoffBasis', BankArrangementHandoffBasisView, str)
    return schemas


def prepare_bank_arrangement_handoff(saved, *, context, reading, basis_ref, arrangement_ref, validate_current):
    if (not isinstance(saved, SavedBankArrangement) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A06'
            or not callable(validate_current)):
        raise ValueError('Arrangement handoff requires saved A05 and independent current A06 authority')
    reading.check_method_context(context, 'BANK-A06')
    if (saved.current_context != context or saved.identity.action_id != 'BANK-A05' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256 or saved.result.kind != 'completed'):
        raise ValueError('Arrangement handoff substitutes original completed task or source content')
    if saved.result.payload.choice != 'confirm':
        return {'kind': 'needs_information', 'missing_fields': ['original_bank_arrangement_confirmation'],
            'requested_refs': [saved.action_input.offer_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise ValueError('Arrangement handoff changes actually audited original confirmation')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Arrangement handoff requires exact source schema and version')
        return row

    try:
        basis = read(basis_ref, BankArrangementHandoffBasisView)
        native = read(basis.native_record_ref, BankArrangementRecordView)
        arrangement = read(arrangement_ref, BankDrawArrangementView)
        terms = read(arrangement.terms_ref, BankDrawTermsView)
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        offer = ArrangementOfferView.model_validate(originals[saved.action_input.offer_ref.key()])
        acceptance = ArrangementAcceptanceView.model_validate(originals[saved.action_input.borrower_acceptance_ref.key()])
        confirmed = [row.model_dump(mode='json') for row in saved.result.payload.conditions]
        expected = {'formation_task_sha256': saved.identity.key, 'formation_record_sha256': saved.record_sha256,
            'formation_input_sha256': saved.identity.input_sha256, 'formation_context_sha256': saved.identity.context_sha256,
            'formation_result_sha256': result_sha, 'formation_audit_sha256': task_digest(saved.audit),
            'formation_source_reading_sha256': saved.source_reading_sha256,
            'native_record_sha256': task_digest(native.model_dump(mode='json'))}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or native.run_id != context.run_id
                or basis.organization_id != reading.organization_id
                or any(row.lender_id != reading.organization_id for row in (offer, native, arrangement, terms))
                or any(row.borrower_id != offer.terms.borrower_id for row in (native, arrangement, terms))
                or native.confirmation_task_sha256 != saved.identity.key
                or native.offer_ref != saved.result.payload.offer_ref or native.offer_ref != offer.ref
                or native.acceptance_ref != saved.result.payload.acceptance_ref or native.acceptance_ref != acceptance.ref
                or native.offer_sha256 != task_digest(offer.model_dump(mode='json'))
                or native.acceptance_sha256 != task_digest(acceptance.model_dump(mode='json'))
                or native.confirmed_conditions_sha256 != task_digest(confirmed)
                or native.accepted_terms != offer.terms or acceptance.accepted_terms != offer.terms
                or acceptance.decision != 'accept' or acceptance.offer_ref != offer.ref
                or native.arrangement_ref != arrangement.ref or native.terms_ref != terms.ref
                or terms.arrangement_ref != arrangement.ref
                or native.arrangement_sha256 != task_digest(arrangement.model_dump(mode='json'))
                or native.terms_sha256 != task_digest(terms.model_dump(mode='json'))
                or any(row.scope != offer.scope_ref for row in (basis, native, arrangement, terms))
                or not scope_covers(saved.context.scope, offer.scope_ref)
                or terms.facility_limit.currency != offer.terms.principal_limit.currency
                or Decimal(terms.facility_limit.value) != Decimal(offer.terms.principal_limit.value)):
            raise ValueError('Actual arrangement changes original offer, acceptance, confirmation, amount or scope')
        times = [acceptance.accepted_at, saved.context.business_time, native.signed_at,
            native.available_at, basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or any(point.clock_ref != context.business_time.clock_ref or point.offset > native.available_at.offset
                    for point in (arrangement.available_at, terms.available_at))
                or not native.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Arrangement handoff changes formal signature, observation or independent author chronology')

        # Carry every confirmed condition into its actual facility stage. A
        # later independent verification may change its outcome, never its
        # original responsibility, scope or ongoing per-draw applicability.
        mappings = {row.original_ref.key(): row for row in basis.condition_relations}
        original_conditions = {row.requirement_ref.key() for row in saved.result.payload.conditions}
        if (len(mappings) != len(basis.condition_relations) or mappings.keys() != original_conditions
                or len(original_conditions) != len(saved.result.payload.conditions)):
            raise ValueError('Arrangement relation omits or duplicates a confirmed original condition')
        formation, each_draw = set(), set()
        unique_refs([row.current_ref for row in basis.condition_relations])
        unique_refs(arrangement.formation_condition_refs)
        unique_refs(arrangement.each_draw_condition_refs)
        for key, relation in mappings.items():
            original = QuoteConditionView.model_validate(originals[key])
            current = read(relation.current_ref, BankDrawConditionView)
            stage = 'formation' if original.stage == 'arrangement_effective' else 'each_draw'
            if any(ref.key() not in mappings for ref in original.dependency_refs):
                raise ValueError('Arrangement relation omits an original confirmed condition prerequisite')
            unique_refs(current.dependency_refs)
            if (relation.original_sha256 != task_digest(originals[key])
                    or relation.current_sha256 != task_digest(current.model_dump(mode='json'))
                    or current.arrangement_ref != arrangement.ref or current.stage != stage
                    or current.scope != original.scope_ref or current.responsible_id != original.responsible_id
                    or {ref.key() for ref in current.dependency_refs}
                        != {mappings[ref.key()].current_ref.key() for ref in original.dependency_refs}):
                raise ValueError('Formal condition mapping changes original source, scope, responsibility or stage')
            (formation if stage == 'formation' else each_draw).add(current.ref.key())
        if (formation != {ref.key() for ref in arrangement.formation_condition_refs}
                or each_draw != {ref.key() for ref in arrangement.each_draw_condition_refs}):
            raise ValueError('Actual arrangement drops or adds formation/ongoing draw conditions outside confirmation')

        original_authority = read(saved.action_input.bank_authority_ref, Authorization)
        original_assignment = reading.resolve(saved.context.function_ref)
        original_reads = {ref.key() for value in (saved.action_input, saved.result.payload)
            for ref in walk_references(value)}
        if (not isinstance(original_assignment, RoleAssignment) or original_assignment.role != 'Bank'
                or original_assignment.function_ref != saved.context.function_ref
                or originals.get(saved.context.function_ref.key()) != original_assignment.model_dump(mode='json')
                or originals.get(original_authority.ref.key()) != original_authority.model_dump(mode='json')
                or original_authority.ref not in saved.context.authorization_refs
                or original_authority.function_ref != saved.context.function_ref
                or original_authority.actor_id != saved.context.actor_id
                or original_authority.organization_id != reading.organization_id
                or 'BANK-A05' not in original_authority.action_ids
                or not original_authority.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, offer.scope_ref) for scope in original_authority.scopes)
                or not original_reads <= {ref.key() for ref in original_authority.readable_refs}):
            raise ValueError('Signed arrangement changes original independently authorized confirmation authorship')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        authored_reads = {ref.key() for ref in (native.ref, arrangement.ref, terms.ref, native.native_evidence_ref,
            *basis.evidence_refs, *basis.relation_evidence_refs, *native.evidence_refs,
            *arrangement.evidence_refs, *terms.evidence_refs, terms.facility_limit.basis_ref,
            *(row.current_ref for row in basis.condition_relations))}
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Bank'
                or assignment.function_ref != basis.author_function_ref or grant.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or basis.author_action_id not in grant.action_ids
                or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not authored_reads <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Arrangement relation lacks independent original author authority')
        unique_refs(basis.relation_evidence_refs)
        if native.native_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native registration evidence cannot replace independent confirmation relation evidence')
        handoff_evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs]
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
                    raise ValueError('Arrangement confirmation authority basis changes its original saved source content')
                if ref.kind == 'Evidence':
                    original_authority_evidence_refs.append(ref)
        # Confirmation, native signature and later independent relation retain
        # their own evidence times; current facility/terms facts stay current.
        for point, refs in ((saved.context.business_time, original_authority_evidence_refs),
                (native.signed_at, [*native.evidence_refs, native.native_evidence_ref]),
                (basis.authored_at, handoff_evidence_refs),
                (context.business_time, [*arrangement.evidence_refs, *terms.evidence_refs, terms.facility_limit.basis_ref])):
            for ref in refs:
                evidence = read(ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(point)
                        or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                    raise ValueError('Arrangement relation contains unavailable or unobserved relation evidence')
        observed = read(native.native_evidence_ref, EvidenceRecord)
        if observed.basis_kind != 'observed' or observed.content_hash != native.native_source_sha256:
            raise ValueError('Arrangement handoff requires independently observed actual native registration')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True), native=native.model_copy(deep=True),
                offer=offer.model_copy(deep=True), acceptance=acceptance.model_copy(deep=True),
                arrangement=arrangement.model_copy(deep=True), terms=terms.model_copy(deep=True),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise ValueError('Arrangement handoff requires actual current host source and signed-terms relation validation')
        return {'kind': 'prepared', 'source_mode': reading._resolver.source_mode,
            'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
                'basis_sha256': task_digest(basis.model_dump(mode='json')),
                'native_arrangement_id': native.native_arrangement_id, 'native_event_id': native.native_event_id}}
    finally:
        reading.recheck()
