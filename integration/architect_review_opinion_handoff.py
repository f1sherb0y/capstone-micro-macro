"""Read full original reviewer opinions lawfully received by their author."""
from copy import deepcopy

from integration.architect_review_results import SavedArchitectReview
from src.actions.contracts.architect_review_objects import (
    ArchitectRegisteredReviewOpinion, ArchitectReviewCommentView, ArchitectReviewOpinionReceiptView,
    ArchitectReviewRequestView, ArchitectReviewTargetView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest


def prepare_received_architect_review_opinion(saved, *, context, action_input, reading,
        receipt_ref, native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Return actual received peer opinion; never turn it into an author response.

    Caller holds its source guard. Independent actual service/author/privacy
    and native receipt checks must relate the complete reviewer output to the
    received comment and separate author task. Opinion receipt grants no use,
    approval, closed issues, revised content or completed author response.
    """
    if (not isinstance(saved, SavedArchitectReview) or saved.identity.action_id != 'ARCHITECT-A08'
            or saved.identity.role != 'Architect' or saved.identity.run_id != context.run_id
            or context.contract_ref.id != 'ARCHITECT-A08' or saved.current_context.contract_ref.id != 'ARCHITECT-A08'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'scope', 'business_time', 'execution_mode'))
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'review'
            or saved.context.scope != context.scope or action_input.scope != context.scope
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Opinion handoff requires original saved review and separately authorized current author reading')
    reading.check_method_context(context, 'ARCHITECT-A08')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'ARCHITECT-A08', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Opinion handoff lacks original successful reviewer audit')
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Opinion reception requires separate native and independent relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        original_target = ArchitectReviewTargetView.model_validate(originals[saved.action_input.target_ref.key()])
        original_request = ArchitectReviewRequestView.model_validate(originals[saved.action_input.review_request_ref.key()])
        opinion = ArchitectRegisteredReviewOpinion.model_validate(saved.result.payload.opinion.model_dump(mode='python'))
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, ArchitectReviewOpinionReceiptView) or receipt.run_id != context.run_id
                or receipt.reviewer_organization_id != saved.identity.organization_id
                or receipt.author_organization_id != reading.organization_id or receipt.author_actor_id != context.actor_id
                or receipt.task_sha256 != saved.identity.key or receipt.record_sha256 != saved.record_sha256
                or receipt.result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.opinion != opinion or receipt.opinion_content_sha256 != content_digest(opinion)
                or receipt.target_content_sha256 != original_target.content_sha256
                or receipt.scope != saved.context.scope or receipt.author_review_request_ref != action_input.review_request_ref
                or opinion.target_ref != original_target.ref or opinion.review_request_ref != original_request.ref
                or opinion.requested_use != original_request.requested_use
                or opinion.check_result_refs != saved.action_input.check_result_refs
                or original_request.choice != 'review' or original_request.organization_id != saved.identity.organization_id
                or original_target.author_organization_id != reading.organization_id or original_target.author_actor_id != context.actor_id):
            raise TaskConflict('Received opinion substitutes reviewer result, author, target, check refs or scope')
        unique_refs(opinion.check_result_refs)
        unique_refs(opinion.unresolved_issue_refs)
        now = context.business_time
        if (receipt.available_at.clock_ref != now.clock_ref or saved.context.business_time.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= receipt.available_at.offset <= now.offset
                or not receipt.effective_window.contains(now)):
            raise TaskConflict('Opinion receipt changes original review or observation chronology')
        if receipt.reception_status != 'received':
            code = 'original_architect_review_opinion_' + receipt.reception_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [receipt.ref], 'earliest_time': None, 'condition_code': code}}
        target = reading.resolve(action_input.target_ref)
        request = reading.resolve(action_input.review_request_ref)
        comment = reading.resolve(receipt.comment_ref)
        if (not isinstance(target, ArchitectReviewTargetView) or target != original_target
                or not isinstance(request, ArchitectReviewRequestView) or request.choice not in {'respond', 'propose_revision'}
                or request.target_ref != target.ref or request.content_sha256 != target.content_sha256
                or request.organization_id != reading.organization_id or request.requested_use != opinion.requested_use
                or request.scope != context.scope or request.independence_rule != 'author_response'
                or not isinstance(comment, ArchitectReviewCommentView) or content_digest(comment) != receipt.comment_sha256
                or comment.ref not in action_input.comment_refs or comment.ref not in request.comment_refs
                or comment.target_ref != target.ref or comment.content_sha256 != target.content_sha256
                or comment.review_request_ref != request.ref or comment.scope != context.scope
                or comment.author_organization_id != saved.identity.organization_id
                or comment.author_actor_id != saved.context.actor_id or comment.author_function_ref != saved.context.function_ref
                or comment.author_authority_ref != original_request.authority_ref or comment.author_action_id != 'ARCHITECT-A08'
                or receipt.received_at is None):
            raise TaskConflict('Opinion reception changes original reviewer authorship, actual comment, target or separate author task')
        points = [saved.context.business_time, comment.authored_at, receipt.received_at, comment.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or receipt.received_at.offset > receipt.available_at.offset or not comment.effective_window.contains(now)
                or not request.effective_window.contains(now)):
            raise TaskConflict('Opinion reception changes original review, actual receipt or author-task chronology')
        if comment.status != 'received' or request.status != 'authorized':
            code = 'original_architect_review_opinion_or_author_task_withdrawn'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [comment.ref, request.ref], 'earliest_time': None, 'condition_code': code}}
        evidence = {}
        for ref in [native, *relations, *receipt.evidence_refs, *comment.evidence_refs, *target.evidence_refs, *request.evidence_refs]:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic'
                    or ref in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise TaskConflict('Opinion reception lacks current actual native, relation or received source evidence')
            if ref in [native, *relations]:
                evidence[ref.key()] = row.model_dump(mode='json')
        if evidence[native.key()]['content_hash'] != native_source_sha256:
            raise TaskConflict('Opinion receipt changes its actual native observation hash')
        if validate_current(saved=deepcopy(saved), opinion=opinion.model_copy(deep=True), receipt=receipt.model_copy(deep=True),
                comment=comment.model_copy(deep=True), target=target.model_copy(deep=True), request=request.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Opinion reception requires actual reviewer/service authority, original receipt relation and private access checks')
        if reading.method_evidence() != before:
            raise TaskConflict('Opinion reception source gate must not execute methods')
        return {'kind': 'prepared', 'source_mode': 'formal', 'received_opinion': opinion,
            'comment_ref': comment.ref, 'provenance': {'task_sha256': saved.identity.key,
                'record_sha256': saved.record_sha256, 'result_sha256': result_sha,
                'source_reading_sha256': saved.source_reading_sha256, 'opinion_sha256': content_digest(opinion),
                'receipt_sha256': content_digest(receipt), 'comment_sha256': content_digest(comment),
                'native_source_sha256': native_source_sha256, 'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
