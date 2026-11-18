"""Relate an original A02 decision to independently observed actual intake for A03."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.bank_intake_results import SavedBankIntake
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.bank_credit_objects import bank_credit_schemas
from src.actions.contracts.bank_objects import FinanceApplicationView, FinanceProductProfileView
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class BankIntakeRecordView(CostSource):
    """Host projection of an actual native intake record, never created by this bridge."""
    ref: ref_type('BankIntakeRecord')
    run_id: TextId
    organization_id: TextId
    as_of: TimePoint
    application_ref: ref_type('FinanceApplication')
    application_sha256: Digest
    product_ref: ref_type('FinanceProductProfile')
    product_sha256: Digest
    borrower_id: TextId
    required_condition_refs: list[ref_type('Requirement')]
    accepted_at: TimePoint
    review_task_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class BankIntakeHandoffBasisView(GovReviewAuthored):
    ref: ref_type('BankIntakeHandoffBasis')
    run_id: TextId
    organization_id: TextId
    intake_task_sha256: Digest
    intake_record_sha256: Digest
    intake_input_sha256: Digest
    intake_context_sha256: Digest
    intake_result_sha256: Digest
    intake_audit_sha256: Digest
    intake_source_reading_sha256: Digest
    native_record_ref: ref_type('BankIntakeRecord')
    native_record_sha256: Digest
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['BANK-A03']


def bank_intake_handoff_schemas():
    schemas = bank_credit_schemas()
    schemas.register_kind('BankIntakeRecord', BankIntakeRecordView, str)
    schemas.register_kind('BankIntakeHandoffBasis', BankIntakeHandoffBasisView, str)
    return schemas


def prepare_bank_intake_handoff(saved, *, context, reading, basis_ref, application_ref, product_ref, validate_current):
    if (not isinstance(saved, SavedBankIntake) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A03'
            or not callable(validate_current)):
        raise ValueError('Bank intake handoff requires original saved A02 and current authorized A03')
    reading.check_method_context(context, 'BANK-A03')
    if (saved.current_context != context or saved.identity.action_id != 'BANK-A02' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Bank intake handoff substitutes original task, recipient or saved source content')
    if saved.result.kind != 'completed' or saved.result.payload.choice != 'accept_for_review':
        return {'kind': 'needs_information', 'missing_fields': ['original_bank_acceptance_for_review'],
            'requested_refs': [saved.action_input.application_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise ValueError('Bank intake handoff changes the actually audited original result')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Bank intake handoff requires exact original source schemas and versions')
        return row

    try:
        basis = read(basis_ref, BankIntakeHandoffBasisView)
        native = read(basis.native_record_ref, BankIntakeRecordView)
        application = read(application_ref, FinanceApplicationView)
        product = read(product_ref, FinanceProductProfileView)
        expected = {'intake_task_sha256': saved.identity.key, 'intake_record_sha256': saved.record_sha256,
            'intake_input_sha256': saved.identity.input_sha256, 'intake_context_sha256': saved.identity.context_sha256,
            'intake_result_sha256': result_sha, 'intake_audit_sha256': task_digest(saved.audit),
            'intake_source_reading_sha256': saved.source_reading_sha256,
            'native_record_sha256': task_digest(native.model_dump(mode='json'))}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or native.run_id != context.run_id
                or any(row.organization_id != reading.organization_id for row in (basis, native))
                or application.ref != saved.action_input.application_ref or native.application_ref != application.ref
                or saved.result.payload.application_ref != application.ref
                or saved.result.payload.product_ref != product.ref or native.product_ref != product.ref
                or native.application_sha256 != task_digest(application.model_dump(mode='json'))
                or native.product_sha256 != task_digest(product.model_dump(mode='json'))
                or application.lender_id != reading.organization_id or product.lender_id != reading.organization_id
                or native.borrower_id != application.borrower_id
                or native.required_condition_refs != list(saved.result.payload.required_condition_refs)
                or native.required_condition_refs != product.required_condition_refs
                or basis.scope != application.scope_ref or native.scope != application.scope_ref
                or native.as_of != context.business_time):
            raise ValueError('Bank intake relation changes original acceptance, application, product, conditions or actual source')
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        if (originals.get(application.ref.key()) != application.model_dump(mode='json')
                or originals.get(product.ref.key()) != product.model_dump(mode='json')):
            raise ValueError('Current application or product changed since original intake; obtain a new independent decision')
        times = [saved.context.business_time, native.accepted_at, native.available_at,
            basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or not native.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Bank intake handoff changes actual acceptance, observation or independent relation chronology')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        authored_reads = {ref.key() for ref in (application.ref, product.ref, native.ref,
            native.native_evidence_ref, *native.evidence_refs, *native.required_condition_refs,
            *basis.evidence_refs, *basis.relation_evidence_refs)}
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Bank'
                or assignment.function_ref != basis.author_function_ref or grant.function_ref != basis.author_function_ref
                or grant.organization_id != basis.author_organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or basis.author_action_id not in grant.action_ids
                or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not authored_reads <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Bank intake relation lacks independent original author authority')
        unique_refs(native.required_condition_refs)
        unique_refs(basis.relation_evidence_refs)
        relation_evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs]
        intake_evidence_refs = [*native.evidence_refs, native.native_evidence_ref]
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                relation_evidence_refs.append(ref)
            else:
                reading.resolve(ref)
        # Actual acceptance and the later independent relation have separate
        # occurrence times. Shared evidence must satisfy each original use.
        for point, refs in ((native.accepted_at, intake_evidence_refs),
                (basis.authored_at, relation_evidence_refs)):
            for ref in refs:
                evidence = read(ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(point)
                        or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                    raise ValueError('Bank intake relation contains unavailable source evidence')
        native_evidence = read(native.native_evidence_ref, EvidenceRecord)
        if native_evidence.basis_kind != 'observed' or native_evidence.content_hash != native.native_source_sha256:
            raise ValueError('Bank intake needs independently observed actual native acceptance')
        if native.native_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Native intake evidence cannot replace independent acceptance-to-source relation evidence')
        for ref in native.required_condition_refs:
            reading.resolve(ref)
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True),
                native=native.model_copy(deep=True), application=application.model_copy(deep=True),
                product=product.model_copy(deep=True), context=context.model_copy(deep=True), reading=reading) is not True:
            raise ValueError('Bank intake handoff requires actual current host source and independent relation validation')
        return {'kind': 'prepared', 'source_mode': reading._resolver.source_mode,
            'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
                'basis_sha256': task_digest(basis.model_dump(mode='json')),
                'review_task_id': native.review_task_id, 'native_event_id': native.native_event_id}}
    finally:
        reading.recheck()
