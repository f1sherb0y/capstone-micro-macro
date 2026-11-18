"""Rejudge original GOV-A04 readiness without creating a professional finding."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.actions.contracts.government_review_objects import GovReviewSubmissionView, GovReviewTaskView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government.review.original_case_task_ready'
_CODES = (_CODE,)
_FIELDS = frozenset({'scope', 'case_ref', 'submission_ref', 'task_ref', 'rule_refs',
    'professional_refs', 'verified_evidence_refs', 'method_result_refs'})
_BASES = (('case_ref', 'RegulatoryCase', GovSchedulingCaseView),
    ('submission_ref', 'Submission', GovReviewSubmissionView), ('task_ref', 'Task', GovReviewTaskView))
_LISTS = {'rule_refs': 'Rule', 'professional_refs': 'Assessment',
    'verified_evidence_refs': 'Evidence', 'method_result_refs': 'MethodResult'}


@dataclass(frozen=True)
class GovernmentReviewConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    review_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None


def government_original_review_task_profile(read_current, validate_relation):
    """Ready sources permit a fresh review; all substantive checks still run."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government review recovery requires actual sources and independent native history validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Government review recovery duplicates a physical source')
        return keys

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A04' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != ('RegulatoryCase', 'Task', 'Submission')
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government review recovery replaces original case/task/submission wait or agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentReviewConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government review recovery requires typed original/current invocation sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'GOV-A04' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('Government review recovery changes original snapshot, scope or actual current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Government review recovery leaves original authorized coverage')
            reading.check_method_context(context, 'GOV-A04')
            versions, proof_rows, proof_refs = [], [], []
            for raw in (original_input, action_input):
                refs = {field: ref_type(kind).model_validate(raw[field]) for field, kind, _ in _BASES}
                rows = {}
                for field, _, schema in _BASES:
                    row = reading.resolve(refs[field])
                    if not isinstance(row, schema) or row.ref != refs[field] or not scope_covers(scope, row.scope):
                        raise TaskConflict('Government review recovery lacks exact original/current scoped sources')
                    rows[field] = row
                    proof_rows.append(row)
                case, submission, task = (rows[field] for field, _, _ in _BASES)
                if (case.organization_id != source['organization_id'] or task.organization_id != source['organization_id']
                        or task.case_ref != case.ref or case.current_submission_ref != submission.ref
                        or task.submission_ref != submission.ref or task.content_sha256 != submission.content_sha256
                        or task.ref not in case.task_refs or submission.recipient_organization_id != source['organization_id']
                        or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref
                        or submission.procedure_ref != case.procedure_ref):
                    raise TaskConflict('Government review recovery borrows another agency/task/final submission')
                rows['input_lists'] = {field: [ref_type(kind).model_validate(ref) for ref in raw[field]]
                    for field, kind in _LISTS.items()}
                for refs in rows['input_lists'].values():
                    identities(refs)
                    for ref in refs:
                        reading.resolve(ref)
                versions.append(rows)
            old, current = versions
            old_case, old_submission, old_task = (old[field] for field, _, _ in _BASES)
            case, submission, task = (current[field] for field, _, _ in _BASES)
            if tuple(waited) != (old_case.ref, old_task.ref, old_submission.ref):
                raise TaskConflict('Government review wait differs from exact original invocation references')
            if (old_submission.status == 'active' and old_submission.receipt_status == 'received'
                    and old_case.status not in {'closed', 'withdrawn'} and old_task.status == 'authorized'):
                raise TaskConflict('Government review recovery does not match an original source readiness gap')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or old_task.content_sha256 != task.content_sha256 or old_submission.content_sha256 != submission.content_sha256
                    or old_case.applicant_id != case.applicant_id or old_case.matter_ref != case.matter_ref
                    or old_case.procedure_ref.key()[:2] != case.procedure_ref.key()[:2]
                    or old_case.jurisdiction_ref.key()[:2] != case.jurisdiction_ref.key()[:2]
                    or old_task.choice != task.choice or old_task.function_ref.key()[:2] != task.function_ref.key()[:2]
                    or old_task.assignment_ref.key()[:2] != task.assignment_ref.key()[:2]
                    or identities(old_case.linked_submission_refs) - identities(case.linked_submission_refs)
                    or any(identities(old['input_lists'][field]) - identities(current['input_lists'][field]) for field in _LISTS)
                    or any(identities(getattr(old_task, field)) - identities(getattr(task, field)) for field in (
                        *_LISTS, 'dependency_refs', 'reuse_basis_refs', 'question_refs', 'condition_refs'))):
                raise TaskConflict('Government review recovery rewrites original content, choice or retained source histories')
            if (submission.status != 'active' or submission.receipt_status != 'received'
                    or case.status in {'closed', 'withdrawn'} or task.status != 'authorized'):
                return 'waiting'
            now = context.business_time
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (case, submission, task)):
                return 'unavailable'
            grant, function = reading.resolve(task.authority_ref), reading.resolve(task.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != task.authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != task.function_ref
                    or function.role != 'Government' or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                    or task.function_ref != context.function_ref or 'GOV-A04' not in grant.action_ids
                    or not grant.validity.contains(now) or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                raise TaskConflict('Government review recovery lacks current actual agency/task review authority')
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            for row in proof_rows:
                proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Government review recovery requires observed original/current source evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=_CODE,
                    original_action_input=original_input, action_input=action_input,
                    original_case=old_case.model_dump(mode='json'), case=case.model_dump(mode='json'),
                    original_task=old_task.model_dump(mode='json'), task=task.model_dump(mode='json'),
                    original_submission=old_submission.model_dump(mode='json'), submission=submission.model_dump(mode='json'),
                    review_sources=deepcopy(selected.review_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Government review recovery lacks native source readiness and retained review history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A04', _CODE, '1', frozenset({'dependency_change'}), evaluate)
