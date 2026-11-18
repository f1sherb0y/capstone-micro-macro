"""ARCHITECT-A08 opinions preserve unknown checks and independent author comments."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.architect_review_objects import (
    ArchitectReviewTargetView, ArchitectReviewRequestView, ArchitectReviewSpecView,
    ArchitectReviewMethodView, ArchitectReviewCheckView, ArchitectReviewCommentView,
    ArchitectReviewIndependenceView, ArchitectReviewIssueView, ArchitectReviewQuestionView,
    ArchitectAuthorReviewResponseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def review_architecture(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-review-clock-alignment')

    def evidence(refs, historical=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-review-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_architect_review_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-review-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Architect review input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_architect_review_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_architect_review_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, org, action, at):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        roles = {'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'SUPPLIER': 'Supplier',
                 'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != org
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Review/response lacks independent original author/action/scope authority')
        clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_architect_review_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope,
            'note': request.explanation, **fields}}

    def make_questions():
        questions = []
        keys(request.question_refs)
        for ref in request.question_refs:
            row = read(ref, ArchitectReviewQuestionView); question = row.question
            if (not same(row.review_request_ref, request.ref) or not same(row.target_ref, target.ref)
                    or question.scope != action_input.scope or not question.target_refs or not question.recipient_ids
                    or ref.key() not in keys(question.target_refs)):
                raise ValueError('Revision question changes original review/target/scope/recipients')
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not set(question.recipient_ids) <= set(response.recipient_ids): raise ValueError('Revision question exceeds original response recipients')
            for ref in question.target_refs:
                registered = read(ref, ArchitectReviewQuestionView)
                if not same(registered.target_ref, target.ref) or not same(registered.review_request_ref, request.ref) or registered.question != question:
                    raise ValueError('Revision question mixes unrelated original targets')
            evidence(question.evidence_refs); questions.append(question.model_dump(mode='python'))
        if not questions: _needs('specific_original_revision_or_missing_input_questions')
        return questions

    try:
        if action_input.scope != context.scope: raise ValueError('Architect review changes original action scope')
        target = read(action_input.target_ref, ArchitectReviewTargetView)
        request = read(action_input.review_request_ref, ArchitectReviewRequestView)
        if (not same(request.target_ref, target.ref) or request.content_sha256 != target.content_sha256
                or request.organization_id != organization): raise ValueError('Review request changes original target version/content or reviewing organization')
        if request.status != 'authorized': _needs('effective_original_architect_review_request')
        authorize(request.authority_ref, context.actor_id, context.function_ref, organization, 'ARCHITECT-A08', now)
        clock(target.authored_at)
        if target.authored_at.offset > min(now.offset, target.available_at.offset): _needs('original_target_authored_before_received')
        authorize(target.author_authority_ref, target.author_actor_id, target.author_function_ref,
                  target.author_organization_id, target.author_action_id, target.authored_at)
        if request.requested_use not in target.reviewable_uses: raise ValueError('Review request invents a target use outside its original scope')
        if keys(action_input.check_result_refs) != keys(request.received_check_result_refs) or keys(action_input.comment_refs) != keys(request.comment_refs):
            _needs('all_original_received_review_checks_and_comments')
        comments = {}
        for ref in action_input.comment_refs:
            comment = read(ref, ArchitectReviewCommentView, True)
            if (not same(comment.target_ref, target.ref) or not same(comment.review_request_ref, request.ref)
                    or comment.content_sha256 != target.content_sha256): raise ValueError('Review comment changes original target/request/content')
            clock(comment.authored_at)
            if comment.authored_at.offset > min(now.offset, comment.available_at.offset): _needs('review_comment_authored_before_received')
            authorize(comment.author_authority_ref, comment.author_actor_id, comment.author_function_ref,
                      comment.author_organization_id, comment.author_action_id, comment.authored_at)
            comments[ref.key()] = comment
        if request.choice != 'review':
            if target.author_organization_id != organization or target.author_actor_id != context.actor_id:
                raise ValueError('Author response/revision borrows another original author identity')
            if request.independence_rule != 'author_response':
                raise ValueError('Author response/revision requires its original author-response template')
            if not comments or any(comment.status != 'received' for comment in comments.values()): _needs('actual_received_original_review_comments')
            if request.choice == 'propose_revision':
                return completed('propose_revision', affected_ref=target.ref, questions=make_questions())
            if request.response_comment_ref is None or request.response_comment_ref.key() not in comments: _needs('original_comment_selected_for_author_response')
            comment = comments[request.response_comment_ref.key()]
            if request.author_response_ref is None:
                _needs('independent_original_author_review_response', [request.ref, comment.ref])
            response = read(request.author_response_ref, ArchitectAuthorReviewResponseView)
            if (not same(response.review_request_ref, request.ref) or not same(response.target_ref, target.ref)
                    or response.target_content_sha256 != target.content_sha256 or not same(response.comment_ref, comment.ref)
                    or response.comment_sha256 != content_digest(comment) or response.scope != action_input.scope
                    or response.author_organization_id != organization or response.author_actor_id != context.actor_id
                    or response.author_function_ref != context.function_ref or response.author_authority_ref != request.authority_ref):
                raise ValueError('Author response substitutes original author, received comment, request or target content')
            if response.status != 'prepared': _needs('available_original_author_review_response', [response.ref])
            clock(response.authored_at)
            if not comment.available_at.offset <= response.authored_at.offset <= min(now.offset, response.available_at.offset):
                _needs('author_response_after_original_comment_received', [response.ref, comment.ref])
            authorize(response.author_authority_ref, response.author_actor_id, response.author_function_ref,
                      response.author_organization_id, response.author_action_id, response.authored_at)
            if response.response_changes_content:
                return completed('propose_revision', affected_ref=target.ref, questions=make_questions())
            if not response.response_basis_refs: _needs('original_evidence_for_unchanged_content_response')
            evidence(response.response_basis_refs)
            return completed('respond', comment_ref=comment.ref, response=response.response, basis_refs=response.response_basis_refs)
        if request.independence_rule == 'author_response': raise ValueError('An author-response template cannot authorize an independent review')
        if len(set(request.reviewer_personnel_ids)) != len(request.reviewer_personnel_ids): raise ValueError('Review template repeats personnel identities')
        if request.independence_rule != 'no_requirement':
            if action_input.independence_ref is None: _needs('original_architect_review_independence_check')
            check = read(action_input.independence_ref, ArchitectReviewIndependenceView)
            if (not same(check.target_ref, target.ref) or not same(check.review_request_ref, request.ref)
                    or check.reviewer_organization_id != organization or check.reviewer_actor_id != context.actor_id
                    or set(check.reviewer_personnel_ids) != set(request.reviewer_personnel_ids)
                    or check.author_organization_id != target.author_organization_id
                    or set(check.author_personnel_ids) != set(target.author_personnel_ids)):
                raise ValueError('Review independence changes original target/authors/reviewers/template')
            if (len(set(check.reviewer_personnel_ids)) != len(check.reviewer_personnel_ids)
                    or len(set(check.author_personnel_ids)) != len(check.author_personnel_ids)):
                raise ValueError('Review independence repeats a real personnel identity')
            if check.coverage != 'complete' or check.as_of != now: _needs('complete_current_original_review_independence')
            clock(check.verified_at)
            if check.verified_at.offset > min(now.offset, check.available_at.offset): _needs('independence_verified_before_received')
            authorize(check.verifier_authority_ref, check.verifier_actor_id, check.verifier_function_ref,
                      check.verifier_organization_id, check.verifier_action_id, check.verified_at)
            if (context.actor_id == target.author_actor_id or set(request.reviewer_personnel_ids).intersection(target.author_personnel_ids)):
                _needs('reviewer_personnel_independent_of_original_authors')
            if request.independence_rule == 'unrelated_organization_and_personnel':
                if not isinstance(check.related_organization_ids, Known): _needs('known_original_review_organization_relations')
                if target.author_organization_id in {organization, *check.related_organization_ids.value}:
                    _needs('review_organization_independent_of_original_authors')
        if target.issue_coverage != 'complete': _needs('complete_original_review_target_open_issues')
        issues = keys(target.unresolved_issue_refs)
        keys(request.required_check_refs)
        specs = {ref.key(): read(ref, ArchitectReviewSpecView) for ref in request.required_check_refs}
        for spec in specs.values():
            if (not same(spec.target_ref, target.ref) or not same(spec.review_request_ref, request.ref)
                    or spec.requested_use != request.requested_use): raise ValueError('Review check specification changes original target/request/use')
            if spec.method_ref is None: _unsupported('architect-review-required-check-method')
            method = read(spec.method_ref, ArchitectReviewMethodView)
            if (not same(method.target_ref, target.ref) or not same(method.check_spec_ref, spec.ref)
                    or method.requested_use != request.requested_use): raise ValueError('Review method changes original supported target/spec/use')
            if not isinstance(method.supported, Known): _needs('known_original_architect_check_method_support')
            if not method.supported.value: _unsupported('architect-review-method-scope')
        passed, failed, unknown, seen = set(), set(), set(), set()
        result_issues = {}
        for ref in action_input.check_result_refs:
            result = read(ref, ArchitectReviewCheckView); clock(result.executed_at)
            spec = specs.get(result.check_spec_ref.key())
            if (spec is None or not same(result.target_ref, target.ref) or not same(result.review_request_ref, request.ref)
                    or result.content_sha256 != target.content_sha256 or not same(result.method_ref, spec.method_ref)
                    or result.requested_use != request.requested_use or result.executed_at.offset > min(now.offset, result.available_at.offset)):
                raise ValueError('Review result changes original method/spec/target/request/content/use or time')
            key = spec.ref.key()
            if key in seen: _needs('unique_reconciled_original_check_result_per_required_spec')
            seen.add(key)
            method = read(result.method_ref, ArchitectReviewMethodView)
            if not method.effective_window.contains(result.executed_at): _needs('original_review_method_valid_when_executed')
            if result.author_organization_id not in method.permitted_verifier_ids: raise ValueError('Review result uses a verifier outside the original method')
            authorize(result.author_authority_ref, result.author_actor_id, result.author_function_ref,
                      result.author_organization_id, result.author_action_id, result.executed_at)
            issues.update(keys(result.unresolved_issue_refs))
            result_issues.update({ref.key(): ref for ref in result.unresolved_issue_refs})
            if result.status == 'unsupported': _unsupported('architect-review-upstream-method-domain')
            if result.status != 'ok' or not isinstance(result.passed, Known): unknown.add(key)
            elif result.passed.value: passed.add(key)
            else:
                if not result.unresolved_issue_refs: _needs('original_issue_for_failed_architectural_check')
                failed.add(key)
        blocking = False
        refs = {ref.key(): ref for ref in target.unresolved_issue_refs}
        refs.update(result_issues)
        for ref in refs.values():
            issue = read(ref, ArchitectReviewIssueView)
            if not same(issue.target_ref, target.ref) or issue.status == 'closed': raise ValueError('Review issue changes original target or claims closure')
            blocking |= request.requested_use in issue.blocking_uses
        if failed: opinion = 'revise'
        elif blocking: opinion = 'undetermined'
        elif specs and passed == set(specs) and not issues: opinion = 'support'
        elif passed: opinion = 'limited_support'
        else: opinion = 'undetermined'
        explanation = request.explanation
        if unknown or set(specs) - seen: explanation += '; original required checks remain unverified'
        return completed('review', opinion={'target_ref': target.ref, 'review_request_ref': request.ref,
            'check_result_refs': action_input.check_result_refs, 'opinion': opinion, 'requested_use': request.requested_use,
            'unresolved_issue_refs': list(refs.values()), 'explanation': explanation})
    except ObservationGap as gap:
        reading.recheck(); return gap.result
