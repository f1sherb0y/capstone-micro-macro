"""Relate original A07 review requests to actual A08 tasks across authorities."""
from copy import deepcopy

from integration.architect_deliverable_results import SavedArchitectDeliverable
from src.actions.contracts.architect_review_objects import (
    ArchitectReviewRequestView, ArchitectReviewTargetView, ArchitectReviewTaskRegistrationView,
)
from src.actions.contracts.architect_submission_objects import (
    ArchitectSubmissionDeliverableView, ArchitectSubmissionProfileView, ArchitectSubmissionReviewView,
    ArchitectSubmissionRecipientView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization


def prepare_architect_review_task_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect received review intake; never create tasks or infer independence.

    Caller holds its source guard. Independent host validation checks native
    request/submission relation, intake delegation to the actual reviewer,
    service authority and lawful access across submitting/reviewing firms.
    Original A08 personnel independence and required checks remain separate.
    """
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedArchitectDeliverable) or saved.identity.action_id != 'ARCHITECT-A07'
            or saved.identity.role != 'Architect' or saved.identity.run_id != context.run_id
            or saved.current_context.contract_ref.id != 'ARCHITECT-A07' or context.contract_ref.id != 'ARCHITECT-A08'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed' or saved.result.payload.choice != 'request_review'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Review task handoff requires original request_review evidence and separately authorized A07/A08 reads')
    reading.check_method_context(context, 'ARCHITECT-A08')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'ARCHITECT-A07', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Review task handoff lacks original successful submission audit')
    ref = Reference.model_validate(registration_ref)
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(item) for item in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Review intake requires separate native and independent relation evidence')
    try:
        before = reading.method_evidence()
        sources = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        deliverable = ArchitectSubmissionDeliverableView.model_validate(sources[saved.action_input.deliverable_ref.key()])
        profile = ArchitectSubmissionProfileView.model_validate(sources[deliverable.submission_profile_ref.key()])
        requirement = ArchitectSubmissionReviewView.model_validate(sources[saved.action_input.review_requirement_ref.key()])
        payload = saved.result.payload
        registration = reading.resolve(ref)
        if (not isinstance(registration, ArchitectReviewTaskRegistrationView) or registration.ref != ref
                or registration.run_id != context.run_id or registration.requester_organization_id != saved.identity.organization_id
                or registration.reviewer_organization_id != reading.organization_id
                or registration.reviewer_actor_id != context.actor_id or registration.reviewer_function_ref != context.function_ref
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.submission_command_id != profile.command_id or registration.submission_business_key != profile.business_key
                or registration.review_requirement_ref != requirement.ref or payload.review_requirement_ref != requirement.ref
                or registration.target_ref != deliverable.ref or payload.deliverable_ref != deliverable.ref
                or registration.content_sha256 != deliverable.content_sha256 or registration.scope != saved.context.scope
                or registration.requested_use != payload.requested_use or registration.requested_use != requirement.requested_use
                or registration.recipient_ids != payload.recipient_ids or payload.recipient_ids != saved.action_input.recipient_ids
                or registration.selected_recipient_id not in registration.recipient_ids
                or registration.unresolved_issue_refs != payload.unresolved_issue_refs
                or registration.unresolved_issue_refs != deliverable.unresolved_issue_refs
                or deliverable.issue_coverage != 'complete'):
            raise TaskConflict('Review intake replaces original request, submission identity, target, use, recipients or unresolved issues')
        unique_refs(registration.unresolved_issue_refs)
        if len(set(registration.recipient_ids)) != len(registration.recipient_ids):
            raise TaskConflict('Review intake repeats original recipient identities')
        recipients = [ArchitectSubmissionRecipientView.model_validate(sources[item.key()]) for item in profile.recipient_refs]
        matching = [row for row in recipients if row.recipient_id == registration.selected_recipient_id]
        if (len(matching) != 1 or matching[0].organization_id != reading.organization_id
                or matching[0].intake_action_id not in requirement.intake_action_ids
                or registration.requested_use not in matching[0].permitted_uses
                or registration.selected_recipient_id not in requirement.recipient_ids):
            raise TaskConflict('Review task changes original authorized intake organization, selected recipient or use')
        now = context.business_time
        points = [saved.context.business_time, registration.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(now)):
            raise TaskConflict('Review intake changes original request or observation chronology')
        if registration.registration_status != 'registered':
            code = 'original_architect_review_task_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        target = reading.resolve(invocation.action_input.target_ref)
        request = reading.resolve(invocation.action_input.review_request_ref)
        common_fields = ('ref', 'content_sha256', 'author_organization_id', 'author_actor_id', 'author_function_ref',
            'author_authority_ref', 'author_action_id', 'authored_at', 'unresolved_issue_refs', 'issue_coverage', 'scope')
        if (not isinstance(target, ArchitectReviewTargetView) or not isinstance(request, ArchitectReviewRequestView)
                or any(getattr(target, name) != getattr(deliverable, name) for name in common_fields)
                or content_digest(target) != registration.review_target_sha256
                or request.ref != registration.review_request_ref or content_digest(request) != registration.review_request_sha256
                or request.target_ref != target.ref or request.content_sha256 != deliverable.content_sha256
                or request.organization_id != reading.organization_id or request.scope != registration.scope
                or request.choice != 'review' or request.requested_use != registration.requested_use
                or request.requested_use not in target.reviewable_uses
                or not set(target.reviewable_uses) <= set(deliverable.intended_uses)
                or registration.registered_at is None):
            raise TaskConflict('Review task substitutes actual target, request, reviewer organization or intended use')
        points = [saved.context.business_time, registration.registered_at, request.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or registration.registered_at.offset > registration.available_at.offset
                or target.available_at.clock_ref != now.clock_ref or target.available_at.offset > now.offset
                or not target.effective_window.contains(now) or not request.effective_window.contains(now)):
            raise TaskConflict('Review intake changes actual task, target or receipt time')
        if request.status != 'authorized':
            code = 'original_registered_architect_review_request_withdrawn'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [request.ref], 'earliest_time': None, 'condition_code': code}}
        grant = reading.resolve(request.authority_ref)
        if grant not in reading._organizations.grants(context, 'ARCHITECT-A08', 'Architect') or not isinstance(grant, Authorization):
            raise TaskConflict('Actual review task lacks original current reviewer authority')
        evidence = {}
        for item in [native, *relations, *registration.evidence_refs, *target.evidence_refs, *request.evidence_refs, *grant.basis_refs]:
            row = reading.resolve(item)
            if (not isinstance(row, EvidenceRecord) or row.ref != item or row.source_kind == 'synthetic'
                    or item in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise TaskConflict('Review intake lacks current actual native, relation, target or authority evidence')
            if item in [native, *relations]:
                evidence[item.key()] = row.model_dump(mode='json')
        if evidence[native.key()]['content_hash'] != native_source_sha256:
            raise TaskConflict('Review task changes its actual native intake source hash')
        if validate_current(saved=deepcopy(saved), registration=registration.model_copy(deep=True),
                requirement=requirement.model_copy(deep=True), recipient=matching[0].model_copy(deep=True),
                target=target.model_copy(deep=True), request=request.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Review intake requires actual service authority, delegated intake/task relation and cross-organization privacy checks')
        if reading.method_evidence() != before:
            raise TaskConflict('Review intake source gate must not execute methods')
        return {'kind': 'prepared', 'source_mode': 'formal', 'review_request_ref': request.ref,
            'provenance': {'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
                'registration_sha256': content_digest(registration), 'target_sha256': content_digest(target),
                'review_request_sha256': content_digest(request), 'native_source_sha256': native_source_sha256,
                'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
