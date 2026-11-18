"""Actual formal reassessment evidence for an original scoped supplement wait."""
from copy import deepcopy

from pydantic import Field

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_supplement_objects import GovSupplementRevisionView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class GovernmentSupplementReassessmentRecord(StrictRecord):
    completion_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    revision_basis_ref: ref_type('RevisionBasis')
    original_submission_ref: ref_type('Submission')
    original_content_sha256: Digest
    current_submission_ref: ref_type('Submission')
    current_content_sha256: Digest
    completed_at: TimePoint
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    action_id: TextId
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)


def read_supplement_reassessment(*, selected, source, waited, old, current, context, scope, read):
    """Return proof only when actual completion and the current legal route agree."""
    original_context = selected.original_context
    old_profile, profile = old['profile'], current['profile']
    if (original_context is None or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or old_profile.revision_basis_ref is None or profile.revision_basis_ref is None
            or old['original_submission_ref'].ref == old['current_submission_ref'].ref):
        raise TaskConflict('Government supplement reassessment recovery lacks original revision/context')
    revisions = []
    proof_refs = []
    for version, at in ((old, original_context.business_time), (current, context.business_time)):
        case, original, submission, profile = (version[field] for field in (
            'case_ref', 'original_submission_ref', 'current_submission_ref', 'profile'))
        revision = read(profile.revision_basis_ref, GovSupplementRevisionView)
        if (revision.case_ref != case.ref or revision.procedure_ref != case.procedure_ref
                or revision.original_submission_ref != original.ref or revision.original_content_sha256 != original.content_sha256
                or revision.current_submission_ref != submission.ref or revision.current_content_sha256 != submission.content_sha256
                or revision.author_organization_id != source['organization_id'] or revision.author_action_id != 'GOV-A06'
                or revision.authored_at.clock_ref != at.clock_ref or revision.available_at.clock_ref != at.clock_ref
                or revision.authored_at.offset > revision.available_at.offset or revision.available_at.offset > at.offset
                or not revision.effective_window.contains(revision.authored_at)):
            raise TaskConflict('Government supplement reassessment substitutes revision content/procedure/authorship')
        grant = selected.reading.resolve(revision.author_authority_ref)
        function = selected.reading.resolve(revision.author_function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != revision.author_authority_ref
                or not isinstance(function, RoleAssignment) or function.function_ref != revision.author_function_ref
                or function.role != 'Government' or grant.actor_id != revision.author_actor_id
                or grant.organization_id != source['organization_id'] or grant.function_ref != function.function_ref
                or 'GOV-A06' not in grant.action_ids or not grant.validity.contains(revision.authored_at)
                or not any(scope_covers(covered, scope) for covered in grant.scopes)):
            raise TaskConflict('Government supplement reassessment lacks independently authorized revision author')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])
        revisions.append(revision)
    old_revision, revision = revisions
    if (tuple(waited) != (old['case_ref'].ref, old_revision.ref, old['current_submission_ref'].ref)
            or old_revision.route != 'formal_reassessment' or old['case_ref'].status in {'closed', 'withdrawn'}
            or old['current_submission_ref'].status != 'active' or old['current_submission_ref'].receipt_status != 'received'
            or old_profile.coverage != 'complete' or old_profile.as_of != original_context.business_time
            or {ref.key() for ref in old_profile.issue_refs} != {ref.key() for ref in old['input_lists']['issue_refs']}
            or {ref.key() for ref in old_profile.response_refs} != {ref.key() for ref in old['input_lists']['response_refs']}
            or old_revision.ref.key()[:2] != revision.ref.key()[:2]):
        raise TaskConflict('Government supplement reassessment differs from original formal-reassessment wait')
    if (revision.route != 'continue_scoped_review' or selected.reassessment is None
            or not revision.effective_window.contains(context.business_time)):
        return None
    record = GovernmentSupplementReassessmentRecord.model_validate(deepcopy(selected.reassessment))
    if (record.source_identity_sha256 != task_digest(source) or record.run_id != source['run_id']
            or record.organization_id != source['organization_id'] or record.case_ref != current['case_ref'].ref
            or record.revision_basis_ref != revision.ref
            or record.original_submission_ref != current['original_submission_ref'].ref
            or record.original_content_sha256 != current['original_submission_ref'].content_sha256
            or record.current_submission_ref != current['current_submission_ref'].ref
            or record.current_content_sha256 != current['current_submission_ref'].content_sha256
            or record.completed_at.clock_ref != context.business_time.clock_ref
            or record.completed_at.offset < original_context.business_time.offset
            or record.completed_at.offset > context.business_time.offset
            or record.completed_at.offset > revision.authored_at.offset
            or len({ref.key() for ref in record.evidence_refs}) != len(record.evidence_refs)):
        raise TaskConflict('Government supplement reassessment completion substitutes original task/content/time')
    grant = selected.reading.resolve(record.authority_ref)
    function = selected.reading.resolve(record.function_ref)
    if (not isinstance(grant, Authorization) or grant.ref != record.authority_ref
            or not isinstance(function, RoleAssignment) or function.function_ref != record.function_ref
            or function.role != 'Government' or grant.actor_id != record.actor_id
            or grant.organization_id != source['organization_id'] or grant.function_ref != record.function_ref
            or record.action_id not in grant.action_ids or not grant.validity.contains(record.completed_at)
            or not any(scope_covers(covered, scope) for covered in grant.scopes)):
        raise TaskConflict('Government supplement reassessment completion lacks actual independent authority')
    proof_refs.extend([*record.evidence_refs, *grant.basis_refs, *function.basis_refs])
    return dict(original_revision=old_revision.model_dump(mode='json'), revision=revision.model_dump(mode='json'),
        reassessment=record.model_dump(mode='json'), proof_refs=proof_refs)
