"""Relate original A06 approval to an independently registered DrawApproval for A07."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from integration.bank_draw_results import SavedBankDraw
from src.actions.contracts.bank_draw_objects import (
    BankDrawArrangementView, BankDrawDecisionView, BankDrawRequestView, BankDrawTermsView,
)
from src.actions.contracts.bank_execution_objects import (
    BankExecutionApprovalView, BankExecutionArrangementView, bank_execution_schemas,
)
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.models import Digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class BankDrawHandoffBasisView(GovReviewAuthored):
    ref: ref_type('BankDrawHandoffBasis')
    run_id: TextId
    organization_id: TextId
    draw_task_sha256: Digest
    draw_record_sha256: Digest
    draw_input_sha256: Digest
    draw_context_sha256: Digest
    draw_result_sha256: Digest
    draw_audit_sha256: Digest
    draw_source_reading_sha256: Digest
    draw_request_ref: ref_type('DrawRequest')
    draw_request_sha256: Digest
    draw_arrangement_sha256: Digest
    draw_terms_sha256: Digest
    draw_conditions_sha256: Digest
    execution_arrangement_sha256: Digest
    approval_ref: ref_type('DrawApproval')
    approval_sha256: Digest
    registered_at: TimePoint
    native_approval_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['BANK-A07']


def bank_draw_handoff_schemas():
    schemas = bank_execution_schemas()
    schemas.register_kind('BankDrawHandoffBasis', BankDrawHandoffBasisView, str)
    return schemas


def prepare_bank_draw_handoff(saved, *, context, reading, basis_ref, approval_ref, arrangement_ref, validate_current):
    if (not isinstance(saved, SavedBankDraw) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A07'
            or not callable(validate_current)):
        raise ValueError('Draw handoff requires saved A06 and independently authorized current A07')
    reading.check_method_context(context, 'BANK-A07')
    if (saved.current_context != context or saved.identity.action_id != 'BANK-A06' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256 or saved.result.kind != 'completed'):
        raise ValueError('Draw handoff substitutes its original completed task or source content')
    if saved.result.payload.choice != 'approve_draw':
        return {'kind': 'needs_information', 'missing_fields': ['original_bank_draw_approval'],
            'requested_refs': [saved.action_input.draw_request_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise ValueError('Draw handoff changes the actually audited original batch approval')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Draw handoff requires exact original source schemas and versions')
        return row

    try:
        basis = read(basis_ref, BankDrawHandoffBasisView)
        approval = read(approval_ref, BankExecutionApprovalView)
        arrangement = read(arrangement_ref, BankExecutionArrangementView)
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        request = BankDrawRequestView.model_validate(originals[saved.action_input.draw_request_ref.key()])
        original_arrangement = BankDrawArrangementView.model_validate(originals[saved.action_input.arrangement_ref.key()])
        terms = BankDrawTermsView.model_validate(originals[original_arrangement.terms_ref.key()])
        profile = BankDrawDecisionView.model_validate(originals[request.decision_profile_ref.key()])
        expected = {'draw_task_sha256': saved.identity.key, 'draw_record_sha256': saved.record_sha256,
            'draw_input_sha256': saved.identity.input_sha256, 'draw_context_sha256': saved.identity.context_sha256,
            'draw_result_sha256': result_sha, 'draw_audit_sha256': task_digest(saved.audit),
            'draw_source_reading_sha256': saved.source_reading_sha256,
            'draw_request_sha256': task_digest(request.model_dump(mode='json')),
            'draw_arrangement_sha256': task_digest(original_arrangement.model_dump(mode='json')),
            'draw_terms_sha256': task_digest(terms.model_dump(mode='json')),
            'draw_conditions_sha256': task_digest([row.model_dump(mode='json') for row in saved.result.payload.conditions]),
            'execution_arrangement_sha256': task_digest(arrangement.model_dump(mode='json')),
            'approval_sha256': task_digest(approval.model_dump(mode='json'))}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or basis.draw_request_ref != request.ref or basis.approval_ref != approval.ref
                or arrangement.ref != saved.action_input.arrangement_ref or approval.arrangement_ref != arrangement.ref
                or request.arrangement_ref != arrangement.ref
                or any(row.lender_id != reading.organization_id for row in (request, original_arrangement, terms, arrangement, approval))
                or any(row.borrower_id != request.borrower_id for row in (original_arrangement, terms, arrangement, approval))
                or approval.terms_ref != terms.ref or arrangement.terms_ref != terms.ref
                or approval.batch_key != request.batch_key
                or any(row.scope != request.scope for row in (basis, original_arrangement, terms, arrangement, approval))
                or not scope_covers(saved.context.scope, request.scope)
                or approval.approver_actor_id != saved.context.actor_id
                or approval.approver_function_ref != saved.context.function_ref
                or approval.approver_authority_ref != profile.authority_ref
                or approval.approved_at != saved.context.business_time
                or approval.amount.currency != saved.result.payload.approved_amount.currency
                or Decimal(approval.amount.value) != Decimal(saved.result.payload.approved_amount.value)
                or [line.transfer.model_dump(mode='json') for line in approval.lines]
                    != [line.model_dump(mode='json') for line in saved.result.payload.transfer_lines]):
            raise ValueError('Registered draw approval changes original batch, facility, author, amount or transfer lines')
        times = [saved.context.business_time, basis.registered_at, approval.available_at,
            basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or not basis.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Draw handoff changes actual approval registration, observation or independent author chronology')
        if len({line.local_key for line in approval.lines}) != len(approval.lines):
            raise ValueError('Actual approval repeats an execution transfer identity')

        original_authority = read(approval.approver_authority_ref, Authorization)
        original_function = reading.resolve(approval.approver_function_ref)
        if (originals.get(original_authority.ref.key()) != original_authority.model_dump(mode='json')
                or originals.get(approval.approver_function_ref.key()) != original_function.model_dump(mode='json')
                or not isinstance(original_function, RoleAssignment) or original_function.role != 'Bank'
                or original_function.function_ref != approval.approver_function_ref
                or original_authority.actor_id != saved.context.actor_id
                or original_authority.organization_id != reading.organization_id
                or original_authority.function_ref != saved.context.function_ref
                or 'BANK-A06' not in original_authority.action_ids
                or not original_authority.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, request.scope) for scope in original_authority.scopes)):
            raise ValueError('Registered approval changes original independently authorized batch authorship')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        approval_evidence_refs = [*approval.evidence_refs, *[ref for value in (approval.amount, approval.lines)
            for ref in walk_references(value) if ref.kind == 'Evidence']]
        authored_reads = {ref.key() for ref in (approval.ref, arrangement.ref,
            basis.native_evidence_ref, *basis.evidence_refs, *basis.relation_evidence_refs,
            *approval_evidence_refs, *arrangement.evidence_refs)}
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Bank'
                or assignment.function_ref != basis.author_function_ref or grant.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or basis.author_action_id not in grant.action_ids
                or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not authored_reads <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Draw approval relation lacks independent original author authority')
        unique_refs(basis.relation_evidence_refs)
        if basis.native_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native approval evidence cannot replace independent batch relation evidence')
        handoff_evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs]
        for row in (grant, assignment):
            for ref in row.basis_refs:
                if ref.kind == 'Evidence':
                    handoff_evidence_refs.append(ref)
                else:
                    reading.resolve(ref)
        original_authority_evidence_refs = []
        for row in (original_authority, original_function):
            for ref in row.basis_refs:
                current_basis = reading.resolve(ref)
                if originals.get(ref.key()) != current_basis.model_dump(mode='json'):
                    raise ValueError('Draw approval authority basis changes its original saved source content')
                if ref.kind == 'Evidence':
                    original_authority_evidence_refs.append(ref)
        # Original approval, native registration and later independent relation
        # retain their own times; a shared ref must satisfy every use.
        for point, refs in ((approval.approved_at, original_authority_evidence_refs),
                (approval.approved_at, approval_evidence_refs),
                (basis.registered_at, [basis.native_evidence_ref]),
                (basis.authored_at, handoff_evidence_refs),
                (context.business_time, arrangement.evidence_refs)):
            for ref in refs:
                evidence = read(ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(point)
                        or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                    raise ValueError('Draw relation contains unavailable or unobserved relation evidence')
        native = read(basis.native_evidence_ref, EvidenceRecord)
        if native.basis_kind != 'observed' or native.content_hash != basis.native_source_sha256:
            raise ValueError('Draw handoff requires independently observed actual approval registration')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True), request=request.model_copy(deep=True),
                original_arrangement=original_arrangement.model_copy(deep=True), terms=terms.model_copy(deep=True),
                approval=approval.model_copy(deep=True), arrangement=arrangement.model_copy(deep=True),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise ValueError('Draw handoff requires actual current host approval registration and amount-split validation')
        return {'kind': 'prepared', 'source_mode': reading._resolver.source_mode,
            'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
                'basis_sha256': task_digest(basis.model_dump(mode='json')),
                'native_approval_id': basis.native_approval_id, 'native_event_id': basis.native_event_id}}
    finally:
        reading.recheck()
