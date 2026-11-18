"""Freeze original Architect A08 review requests, checks and author responses."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_review_objects import (
    ArchitectReviewTargetView, ArchitectReviewRequestView, ArchitectReviewSpecView,
    ArchitectReviewMethodView, ArchitectReviewCheckView, ArchitectReviewCommentView,
    ArchitectReviewIndependenceView, ArchitectReviewIssueView, ArchitectReviewQuestionView,
    ArchitectAuthorReviewResponseView,
    architect_review_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, task_digest
from src.actions.roles.qs_change import content_digest


@dataclass(frozen=True)
class PreparedArchitectReview(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A08'


class ArchitectReviewActionAssembler(ArchitectOpportunityActionAssembler):
    """Preserve received checks, comments and optional independence evidence.

    Original processor distinguishes review from author response/revision and
    checks author authority, independence, method support and unresolved issues.
    Assembly produces no opinion, changed content, acceptance or permission.
    """
    ACTION_ID = 'ARCHITECT-A08'
    SOURCE_SCHEMAS = staticmethod(architect_review_schemas)

    def read_received_opinion(self, context, **sources):
        """Read the complete received opinion without preparing an author action."""
        return self._prepare_received_opinion(context, assemble_author=False, **sources)

    def build_from_received_opinion(self, context, **sources):
        """Freeze an author response/revision from the same actual received opinion.

        Uses the same guarded reviewer history, receipt and native relation
        checks as read_received_opinion. Independent author draft validation
        remains in the ordinary assembler and original action processor.
        """
        return self._prepare_received_opinion(context, assemble_author=True, **sources)

    def _prepare_received_opinion(self, context, *, assemble_author, reviewer_submission, reviewer_identity,
            reviewer_execution_versions, reviewer_read_context, receipt_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Keep received opinion and optional author assembly in one source guard."""
        from integration.architect_review_opinion_handoff import prepare_received_architect_review_opinion
        from integration.architect_review_results import ArchitectReviewResultWorker
        from integration.architect_submission import ArchitectResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.references import ActionReadView

        if (not isinstance(reviewer_submission, ArchitectResultSubmission)
                or reviewer_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(reviewer_submission.worker, ArchitectReviewResultWorker)
                or reviewer_submission.worker.registry is not self.registry
                or reviewer_submission.worker.store.run_id != self.organizations.run_id
                or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Opinion reception requires original A08 submission/worker and guarded actual sources')
        context = self._context(context)
        own_context = ActionContext.model_validate(reviewer_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != self.ACTION_ID
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Opinion reception requires separately authorized reviewer history at the author scope/time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = reviewer_submission.read_receipt(reviewer_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected reviewer submission cannot prove actual opinion reception')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, architect_review_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, self.ACTION_ID, 'Architect')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, self.ACTION_ID, 'Architect')
            reading = None
            try:
                saved = reviewer_submission.worker.read_completed(reviewer_identity, current_context=own_context,
                    reading=own_reading, execution_versions=reviewer_execution_versions, validate_current=validate_history)
                reading = self.build_result_reading(context)

                def validate_link(**sources):
                    if (sources['saved'].identity.as_dict() != receipt['identity']
                            or sources['saved'].record_sha256 != receipt['record_sha256']):
                        raise TaskConflict('Opinion receipt substitutes its original saved reviewer result')
                    # The actual opinion receipt is already named "receipt" in
                    # sources; preserve it separately from the submission receipt.
                    relation_sources = {key: value for key, value in sources.items() if key != 'receipt'}
                    return (validate_current(**sources) is True
                        and validate_receipt_relation(receipt=deepcopy(receipt),
                            opinion_receipt=sources['receipt'].model_copy(deep=True), **relation_sources) is True)

                handoff = prepare_received_architect_review_opinion(saved, context=context,
                    action_input=action_input, reading=reading, receipt_ref=receipt_ref,
                    native_evidence_ref=native_evidence_ref, native_source_sha256=native_source_sha256,
                    relation_evidence_refs=relation_evidence_refs, validate_current=validate_link)
                if reviewer_submission.read_receipt(reviewer_identity) != receipt:
                    raise TaskConflict('Original reviewer submission receipt changed during opinion reception')
                if handoff['kind'] != 'prepared':
                    return handoff
                prepared = {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt),
                    'author_reading_sha256': task_digest(reading.evidence())}}
                if not assemble_author:
                    return prepared
                invocation = self.build(context, **source_refs)
                if (invocation.context != context or invocation.action_input != action_input
                        or any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items())):
                    raise TaskConflict('Received opinion differs from the frozen author context/input/source snapshot')
                request = invocation.reading.resolve(action_input.review_request_ref)
                if (request.choice == 'respond' and request.response_comment_ref != handoff['comment_ref']):
                    raise TaskConflict('Author response selects a different comment than its original received opinion')
                reading.recheck()
                invocation.reading.recheck()
                if reviewer_submission.read_receipt(reviewer_identity) != receipt:
                    raise TaskConflict('Original reviewer submission receipt changed before author assembly completed')
                invocation_sha = task_digest(invocation.reading.evidence())
                return {**prepared, 'provenance': {**prepared['provenance'],
                    'invocation_reading_sha256': invocation_sha},
                    'invocation': replace(invocation, reading_sha256=invocation_sha)}
            finally:
                own_reading.recheck()
                if reading is not None:
                    reading.recheck()

    def build_from_review_task(self, context, *, deliverable_submission, deliverable_identity,
            deliverable_execution_versions, submission_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Link actual review intake while preserving separate sender/reviewer grants."""
        from integration.architect_review_task_handoff import prepare_architect_review_task_handoff
        from integration.architect_deliverable_results import ArchitectDeliverableResultWorker
        from integration.architect_submission import ArchitectResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.architect_submission_objects import architect_submission_schemas
        from src.actions.contracts.references import ActionReadView

        if (not isinstance(deliverable_submission, ArchitectResultSubmission)
                or deliverable_submission.ACTION_ID != 'ARCHITECT-A07'
                or not isinstance(deliverable_submission.worker, ArchitectDeliverableResultWorker)
                or deliverable_submission.worker.registry is not self.registry
                or deliverable_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Review task handoff requires original A07 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(submission_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'ARCHITECT-A07'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Review intake requires separately authorized A07 history at the same A08 scope/time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = deliverable_submission.read_receipt(deliverable_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected review request cannot prove actual task intake')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, architect_submission_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'ARCHITECT-A07', 'Architect')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'ARCHITECT-A07', 'Architect')
            saved = deliverable_submission.worker.read_completed(deliverable_identity, current_context=own_context,
                reading=own_reading, execution_versions=deliverable_execution_versions, validate_current=validate_history)
            reading = self.build_result_reading(context)
            preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Review request receipt substitutes its original saved proposal result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

            handoff = prepare_architect_review_task_handoff(saved, invocation=preflight,
                registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if deliverable_submission.read_receipt(deliverable_identity) != receipt:
                raise TaskConflict('Original request receipt changed during actual review intake linkage')
            own_reading.recheck()
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = self.build(context, **source_refs)
            if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                raise TaskConflict('Actual review intake linkage differs from the frozen A08 source snapshot')
            reading.recheck()
            invocation.reading.recheck()
            if deliverable_submission.read_receipt(deliverable_identity) != receipt:
                raise TaskConflict('Original request receipt changed before A08 assembly completed')
            return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build(self, context, *, scope, target_ref, review_request_ref,
            check_result_refs, comment_refs, independence_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'target_ref': target_ref, 'review_request_ref': review_request_ref,
            'check_result_refs': check_result_refs, 'comment_refs': comment_refs,
            'independence_ref': independence_ref}, prepared_type=PreparedArchitectReview,
            validate_sources=validate_architect_review_sources)


def validate_architect_review_sources(action_input, *, context, organization_id, sources):
    """Check original request/target/content associations without judging support."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect review lacks its exact original concrete source')
        return row

    def same_target(row):
        if row.target_ref.key() != target.ref.key():
            raise TaskConflict('Architect review source changes its original target version')
        return row

    def same_request(row):
        same_target(row)
        if row.review_request_ref.key() != request.ref.key():
            raise TaskConflict('Architect review source changes its original request')
        return row

    def same_content(row):
        same_request(row)
        if row.content_sha256 != target.content_sha256:
            raise TaskConflict('Architect review source changes its original target content')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect review changes its original invocation scope')
    target = read(action_input.target_ref, ArchitectReviewTargetView)
    request = same_target(read(action_input.review_request_ref, ArchitectReviewRequestView))
    if request.organization_id != organization_id or request.content_sha256 != target.content_sha256:
        raise TaskConflict('Architect review request changes original reviewing organization or content')
    for refs in (action_input.check_result_refs, action_input.comment_refs, target.unresolved_issue_refs,
            request.required_check_refs, request.received_check_result_refs, request.comment_refs, request.question_refs):
        unique_refs(refs)
    for ref in action_input.comment_refs:
        comment = same_content(read(ref, ArchitectReviewCommentView))
        unique_refs(comment.response_basis_refs)
    if request.author_response_ref is not None:
        response = same_request(read(request.author_response_ref, ArchitectAuthorReviewResponseView))
        if (request.choice != 'respond' or request.independence_rule != 'author_response'
                or request.response_comment_ref is None or response.comment_ref != request.response_comment_ref
                or response.comment_ref not in action_input.comment_refs
                or response.target_content_sha256 != target.content_sha256 or response.scope != context.scope
                or response.author_organization_id != organization_id or response.author_actor_id != context.actor_id
                or response.author_function_ref != context.function_ref or response.author_authority_ref != request.authority_ref):
            raise TaskConflict('Architect author response changes its original author/request/comment/content association')
        comment = read(response.comment_ref, ArchitectReviewCommentView)
        if response.comment_sha256 != content_digest(comment):
            raise TaskConflict('Architect author response substitutes the actual received comment content')
        unique_refs(response.response_basis_refs)
    issue_refs = list(target.unresolved_issue_refs)
    for ref in action_input.check_result_refs:
        result = same_content(read(ref, ArchitectReviewCheckView))
        if result.requested_use != request.requested_use:
            raise TaskConflict('Architect review result changes its original requested use')
        unique_refs(result.unresolved_issue_refs)
        issue_refs.extend(result.unresolved_issue_refs)
    for ref in issue_refs:
        if ref.key() in sources:
            same_target(read(ref, ArchitectReviewIssueView))
    if action_input.independence_ref is not None:
        independence = same_request(read(action_input.independence_ref, ArchitectReviewIndependenceView))
        if (independence.reviewer_organization_id != organization_id
                or independence.reviewer_actor_id != context.actor_id
                or independence.author_organization_id != target.author_organization_id
                or set(independence.reviewer_personnel_ids) != set(request.reviewer_personnel_ids)
                or set(independence.author_personnel_ids) != set(target.author_personnel_ids)):
            raise TaskConflict('Architect independence evidence changes its original authors or reviewers')
    for ref in request.required_check_refs:
        if ref.key() in sources:
            spec = same_request(read(ref, ArchitectReviewSpecView))
            if spec.requested_use != request.requested_use:
                raise TaskConflict('Architect check specification changes its original requested use')
            if spec.method_ref is not None and spec.method_ref.key() in sources:
                method = same_target(read(spec.method_ref, ArchitectReviewMethodView))
                if method.check_spec_ref.key() != spec.ref.key() or method.requested_use != request.requested_use:
                    raise TaskConflict('Architect review method changes its original specification or use')
    for ref in request.question_refs:
        if ref.key() in sources:
            question = same_request(read(ref, ArchitectReviewQuestionView))
            if question.question.scope != action_input.scope:
                raise TaskConflict('Architect revision question changes its original scope')
