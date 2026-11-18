"""Link saved A03 review to an independently recorded assessment for A04."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.bank_credit_results import SavedBankCredit
from src.actions.contracts.bank_quote_objects import (
    QuoteCreditAssessmentView, QuoteRecordedReviewView, bank_quote_schemas, projection_digest,
)
from src.actions.contracts.common import (
    EvidenceRecord, Reference, StrictRecord, TextId, ref_type, walk_references,
)
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.bank_credit import CREDIT_CASH_METHOD, CreditCashInput
from src.methods.models import Digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class BankCreditProjectionRelation(StrictRecord):
    """Same source version in two explicit action-specific schema views."""
    ref: Reference
    source_sha256: Digest
    target_sha256: Digest
    extension: Literal['quote_policy_ref', 'stage']


class BankCreditHandoffBasisView(GovReviewAuthored):
    ref: ref_type('BankCreditHandoffBasis')
    run_id: TextId
    organization_id: TextId
    credit_task_sha256: Digest
    credit_record_sha256: Digest
    credit_input_sha256: Digest
    credit_context_sha256: Digest
    credit_result_sha256: Digest
    credit_audit_sha256: Digest
    credit_source_reading_sha256: Digest
    assessment_ref: ref_type('CreditAssessment')
    assessment_sha256: Digest
    recorded_decision_ref: ref_type('RecordedDecision')
    recorded_decision_sha256: Digest
    native_record_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    projection_relations: list[BankCreditProjectionRelation]
    author_action_id: Literal['BANK-A04']


def bank_credit_handoff_schemas():
    schemas = bank_quote_schemas()
    schemas.register_kind('BankCreditHandoffBasis', BankCreditHandoffBasisView, str)
    return schemas


def prepare_bank_credit_handoff(saved, *, context, reading, basis_ref, assessment_ref, validate_current):
    """Validate a supplied recorded source; never construct or register one."""
    if (not isinstance(saved, SavedBankCredit) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A04'
            or not callable(validate_current)):
        raise ValueError('Credit handoff requires saved A03 and independent current A04 authority')
    reading.check_method_context(context, 'BANK-A04')
    if (saved.current_context != context or saved.identity.action_id != 'BANK-A03' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.result.kind != 'completed'):
        raise ValueError('Credit handoff substitutes its original completed task or source content')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise ValueError('Credit handoff changes the original audited review result')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Credit handoff requires exact source schemas and versions')
        return row

    try:
        basis = read(basis_ref, BankCreditHandoffBasisView)
        assessment = read(assessment_ref, QuoteCreditAssessmentView)
        recorded = read(assessment.recorded_decision_ref, QuoteRecordedReviewView)
        expected = {'credit_task_sha256': saved.identity.key, 'credit_record_sha256': saved.record_sha256,
            'credit_input_sha256': saved.identity.input_sha256, 'credit_context_sha256': saved.identity.context_sha256,
            'credit_result_sha256': result_sha, 'credit_audit_sha256': task_digest(saved.audit),
            'credit_source_reading_sha256': saved.source_reading_sha256,
            'assessment_sha256': projection_digest(assessment), 'recorded_decision_sha256': projection_digest(recorded)}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or basis.assessment_ref != assessment.ref or basis.recorded_decision_ref != recorded.ref
                or basis.scope != saved.context.scope or assessment.scope_ref != saved.context.scope
                or assessment.lender_id != saved.identity.organization_id
                or assessment.source_run_id != saved.context.run_id
                or assessment.author_actor_id != saved.context.actor_id
                or assessment.author_function_ref != saved.context.function_ref
                or assessment.authority_refs != saved.context.authorization_refs
                or assessment.reviewed_at != saved.context.business_time
                or assessment.review_input != saved.action_input or assessment.review_payload != saved.result.payload
                or recorded.source_run_id != assessment.source_run_id or recorded.organization_id != assessment.lender_id
                or recorded.actor_id != assessment.author_actor_id or recorded.function_ref != assessment.author_function_ref
                or recorded.authority_refs != assessment.authority_refs or recorded.scope_ref != assessment.scope_ref
                or recorded.business_time != assessment.reviewed_at
                or recorded.input != assessment.review_input or recorded.payload != assessment.review_payload):
            raise ValueError('Credit relation changes the original review, recorded author, scope or result')
        times = [assessment.reviewed_at, assessment.available_at, basis.authored_at,
            basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in times)
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or not basis.effective_window.contains(basis.authored_at)
                or not basis.effective_window.contains(context.business_time)):
            raise ValueError('Credit relation changes source observation or independent author chronology')

        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        relations = {row.ref.key(): row for row in basis.projection_relations}
        if len(relations) != len(basis.projection_relations):
            raise ValueError('Credit relation repeats a projection identity')
        required = {ref.key() for value in (saved.action_input, saved.result.payload,
            saved.context.scope, saved.context.function_ref, saved.context.authorization_refs)
            for ref in walk_references(value)}
        # Include the actual indirect financial inputs used by the audited
        # method, rather than deriving new forecasts or rerunning calculations.
        core_kinds = {'FinanceApplication', 'FinanceProductProfile', 'FundingPurpose', 'Organization',
            'OwnerCase', 'Project', 'WorkScope', 'RiskMethod', 'RiskDimension', 'RiskObservation',
            'FinancialForecast', 'BorrowerPortfolio', 'Account', 'Debt', 'DebtComponent', 'Obligation',
            'FinanceFeasibilityMethod', 'Assumption'}
        for row in saved.audit.get('method_calls', []):
            if Reference.model_validate(row['method_ref']).key() == CREDIT_CASH_METHOD.key():
                cash = CreditCashInput.model_validate(row['input'])
                required.update(ref.key() for ref in cash.source_refs if ref.kind in core_kinds)
        dependencies = {row.ref.key() for row in assessment.source_dependencies}
        if not required <= dependencies or not required <= originals.keys():
            raise ValueError('Recorded assessment omits an actual original review source')
        used_relations = set()
        for dependency in assessment.source_dependencies:
            current = reading.resolve(dependency.ref)
            target = current.model_dump(mode='json')
            if projection_digest(current) != dependency.projection_sha256:
                raise ValueError('Recorded assessment dependency changed its supplied version or content')
            original = originals.get(dependency.ref.key())
            if original is None or original == target:
                continue
            relation = relations.get(dependency.ref.key())
            allowed = {'FinanceProductProfile': 'quote_policy_ref', 'Requirement': 'stage'}
            extension = allowed.get(dependency.ref.kind)
            if (relation is None or extension is None or relation.extension != extension
                    or relation.source_sha256 != task_digest(original) or relation.target_sha256 != task_digest(target)
                    or set(target) != set(original) | {extension}
                    or {key: value for key, value in target.items() if key != extension} != original):
                raise ValueError('Quote projection changes original credit facts without an exact declared schema relation')
            used_relations.add(dependency.ref.key())
        if used_relations != relations.keys():
            raise ValueError('Credit relation contains unused or unrelated projection extensions')

        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        authored_reads = {ref.key() for ref in (assessment.ref, recorded.ref, basis.native_evidence_ref,
            *basis.relation_evidence_refs)}
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Bank'
                or assignment.function_ref != basis.author_function_ref or grant.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or basis.author_action_id not in grant.action_ids
                or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not authored_reads <= {ref.key() for ref in grant.readable_refs}):
            raise ValueError('Credit relation lacks independently authorized original authorship')
        unique_refs(basis.relation_evidence_refs)
        if basis.native_evidence_ref in basis.relation_evidence_refs:
            raise ValueError('Recorded-source evidence cannot replace independent review relation evidence')
        handoff_evidence_refs = [*basis.evidence_refs, *basis.relation_evidence_refs, basis.native_evidence_ref]
        review_evidence_refs = [*assessment.evidence_refs, *assessment.method_audit_refs, *recorded.evidence_refs]
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                handoff_evidence_refs.append(ref)
            else:
                reading.resolve(ref)
        # Original review and later registration/relation attestations have
        # distinct occurrence times. A shared ref must satisfy both uses.
        for point, refs in ((basis.authored_at, handoff_evidence_refs),
                (assessment.reviewed_at, review_evidence_refs)):
            for ref in refs:
                evidence = read(ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(point)
                        or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                    raise ValueError('Credit relation contains unavailable or unobserved relation evidence')
        native = read(basis.native_evidence_ref, EvidenceRecord)
        if native.basis_kind != 'observed' or native.content_hash != basis.native_source_sha256:
            raise ValueError('Credit handoff requires independently observed actual recorded source evidence')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True),
                assessment=assessment.model_copy(deep=True), recorded=recorded.model_copy(deep=True),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise ValueError('Credit handoff requires actual current host source and relation validation')
        return {'kind': 'prepared', 'source_mode': reading._resolver.source_mode,
            'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
                'basis_sha256': task_digest(basis.model_dump(mode='json')),
                'native_record_id': basis.native_record_id, 'native_event_id': basis.native_event_id}}
    finally:
        reading.recheck()
