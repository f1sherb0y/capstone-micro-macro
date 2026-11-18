"""GOV-A09 prepares lawful transitions; applications never change existing effect."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionPermitView, GovTransitionApplicationView,
    GovTransitionApplicantAuthorityView,
    GovTransitionRuleView, GovChangeBasisView, GovChangeAuthorityView, GovChangeProcedureView,
    GovChangeEffectView, GovExpiryFactView, GovTransitionQuestionView,
    GovReviewSubmissionView, GovDecisionCommandView, GovDecisionNotificationView,
    GovDecisionAssessmentView, GovDecisionFindingView, GovChangeCheckView,
    GovDecisionConditionBasisView, GovDecisionBindingView, GovDecisionMethodView,
    GovProcedureCompletionView, GovProcedureVerificationView, GovProcedureRequirementView,
    GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_decision_transition(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-transition-clock-alignment')

    def evidence(refs):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-transition-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-transition-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Transition record leaves the original authorized scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_transition_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if row.effective_window.end is not None:
                clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_transition_source', [ref])
        return row

    def authorize(ref, actor, function, organization, action, at):
        grant = read(ref, Authorization, True); assignment = read(function, RoleAssignment, True)
        evidence(grant.basis_refs + assignment.basis_refs); clock(at); clock(grant.validity.start)
        roles = {'GOV': 'Government', 'OWN': 'Owner', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Transition substitutes original author/function/action/scope authority')
        if not grant.validity.contains(at):
            _needs('original_transition_authority_at_execution', [ref])

    def author(row, own=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Transition source predates its original execution')
        if own and (row.author_organization_id != org or row.author_action_id != 'GOV-A09'):
            raise ValueError('Transition source substitutes responsible agency or change function')
        authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at)

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope, **fields,
            'note': 'Original history and effect are preserved. Applications/drafts do not extend or stop effect; scheduled expiry only references a received core fact. Formal changes and notifications require the decision service.'}}

    def bound_rule(ref, purpose):
        row = read(ref, GovTransitionRuleView, historic=purpose == 'expiry', linked=True)
        if (row.organization_id != org or row.prior_decision_ref != prior.ref or row.permit_ref != action_input.permit_ref
                or row.application_ref != action_input.application_ref or row.affected_submission_ref != action_input.affected_submission_ref
                or row.content_sha256 != (submission.content_sha256 if submission else None) or row.purpose != purpose
                or not scope_covers(row.scope, scope) or not scope_covers(row.transition_scope, scope)):
            raise ValueError('Transition rule substitutes original decision, application, version or transitional coverage')
        clock(row.published_at); clock(row.policy_effective_at)
        if row.published_at.offset > row.available_at.offset:
            raise ValueError('Transition rule was received before publication')
        if row.applicability == 'unmodeled':
            _unsupported('government-transition-unmodeled-policy-applicability')
        if row.applicability == 'future' or row.policy_effective_at.offset > now.offset:
            _needs('applicable_original_policy_effective_time', [ref])
        if not _known(row.permitted, 'original_transition_rule_permission'):
            _needs('permitted_original_transition_rule', [ref])
        return row

    def delivered(decision, effect):
        keys(decision.notification_refs)
        if len(set(effect.notification_recipient_ids)) != len(effect.notification_recipient_ids):
            raise ValueError('Transition effect repeats notification recipients')
        recipients = set()
        for ref in decision.notification_refs:
            row = read(ref, GovDecisionNotificationView, True, True)
            if row.decision_ref != decision.ref or row.recipient_id not in effect.notification_recipient_ids:
                raise ValueError('Transition notification substitutes original decision or recipient')
            if row.status == 'delivered':
                if row.delivered_at is None:
                    raise ValueError('Actual delivery requires its original time')
                clock(row.delivered_at)
                if row.delivered_at.offset > now.offset or row.delivered_at.offset > row.available_at.offset:
                    raise ValueError('Transition notification claims future/unreceived delivery')
                recipients.add(row.recipient_id)
        if effect.mode == 'on_actual_delivery' and not set(effect.notification_recipient_ids) <= recipients:
            _needs('actual_original_transition_decision_delivery', decision.notification_refs)

    try:
        evidence(action_input.evidence_refs)
        prior = read(action_input.prior_decision_ref, GovTransitionDecisionView, True, True)
        if prior.organization_id != org or not scope_covers(prior.scope, scope):
            raise ValueError('Transition substitutes responsible agency or original decision coverage')
        permit = None
        if action_input.permit_ref != prior.permit_ref:
            raise ValueError('Transition omits or invents the original actual permit')
        if action_input.permit_ref is not None:
            permit = read(action_input.permit_ref, GovTransitionPermitView, True, True)
            if permit.decision_ref != prior.ref or permit.organization_id != org or not scope_covers(permit.scope, scope):
                raise ValueError('Transition permit belongs to another decision/agency/scope')
            if permit.as_of != now:
                _needs('current_original_permit_status')
        submission = None
        if action_input.affected_submission_ref is not None:
            submission = read(action_input.affected_submission_ref, GovReviewSubmissionView)
            if submission.recipient_organization_id != org or submission.applicant_id != prior.applicant_id:
                raise ValueError('Transition changes original applicant or submission recipient')
            clock(submission.submitted_at)
            if submission.submitted_at.offset > submission.available_at.offset:
                raise ValueError('Affected submission was received before original submission')
            if submission.receipt_status != 'received' or submission.status != 'active':
                _needs('received_active_original_affected_submission')
        if action_input.application_ref is not None:
            application = read(action_input.application_ref, GovTransitionApplicationView); author(application)
            if (application.applicant_id != prior.applicant_id or application.recipient_organization_id != org
                    or application.prior_decision_ref != prior.ref or application.permit_ref != action_input.permit_ref
                    or application.affected_submission_ref != action_input.affected_submission_ref
                    or application.content_sha256 != (submission.content_sha256 if submission else None)):
                raise ValueError('Transition application changes original parties, decision, permit or affected version')
            if application.status != 'received':
                _needs('received_original_transition_application', [application.ref])
            submitter = read(application.submitter_authority_ref, GovTransitionApplicantAuthorityView, True)
            if (submitter.application_ref != application.ref or submitter.applicant_id != prior.applicant_id
                    or submitter.submitter_actor_id != application.author_actor_id
                    or submitter.submitter_function_ref != application.author_function_ref
                    or submitter.submitter_organization_id != application.author_organization_id):
                raise ValueError('Transition application substitutes applicant delegation or actual submitter')
            if not submitter.effective_window.contains(application.authored_at) or not _known(submitter.permitted, 'original_transition_applicant_delegation'):
                _needs('original_applicant_authorized_transition_request')
        rule = bound_rule(action_input.transition_rule_ref, 'transition')
        choice = rule.choice
        if choice is None:
            _needs('explicit_original_transition_choice', [rule.ref])
        if choice == 'record_scheduled_expiry':
            if permit is None or permit.expiry_event_ref is None or rule.expiry_rule_ref != permit.expiry_rule_ref:
                _needs('received_core_scheduled_expiry_fact')
            bound_rule(rule.expiry_rule_ref, 'expiry')
            fact = read(permit.expiry_event_ref, GovExpiryFactView, True, True); clock(fact.occurred_at)
            if (fact.permit_ref != permit.ref or fact.prior_decision_ref != prior.ref or fact.expiry_rule_ref != rule.expiry_rule_ref
                    or fact.occurred_at.offset > now.offset or fact.occurred_at.offset > fact.available_at.offset
                    or permit.status != 'expired'):
                raise ValueError('Scheduled expiry must reference the received original core expiry fact')
            return complete(choice, permit_ref=permit.ref, expiry_rule_ref=rule.expiry_rule_ref)
        if choice == 'open_review':
            if rule.review_rule_ref is None or not rule.question_refs:
                _needs('original_review_basis_and_concrete_questions')
            bound_rule(rule.review_rule_ref, 'review'); keys(rule.question_refs)
            questions = []
            for ref in rule.question_refs:
                row = read(ref, GovTransitionQuestionView); q = row.question
                if row.prior_decision_ref != prior.ref or not scope_covers(scope, q.scope) or not q.recipient_refs or not q.target_refs:
                    raise ValueError('Review question changes original decision/scope or omits targets/recipients')
                if ref.key() not in keys(q.target_refs):
                    raise ValueError('Review question omits its original target')
                bound_rule(q.requirement_ref, 'question')
                requirement = read(q.response_requirement_ref, GovResponseRequirementView)
                if requirement.rule_ref != q.requirement_ref or requirement.scope != q.scope:
                    raise ValueError('Review question substitutes original response requirement')
                for target in q.target_refs:
                    original = read(target, GovTransitionQuestionView)
                    if original.prior_decision_ref != prior.ref or original.question != q:
                        raise ValueError('Review question mixes unrelated original targets')
                for recipient in q.recipient_refs:
                    person = read(recipient, GovRecipientView)
                    if not scope_covers(person.scope, q.scope):
                        raise ValueError('Review recipient lacks original question coverage')
                evidence(q.evidence_refs); keys(q.recipient_refs)
                questions.append(q.model_dump(mode='python'))
            return complete(choice, questions=questions, review_basis_ref=rule.review_rule_ref)
        if choice == 'confirm_coverage':
            if prior.as_of != now or not prior.effective_window.contains(now):
                _needs('current_original_decision_coverage')
            if not rule.coverage_rule_refs:
                _needs('independent_original_unchanged_coverage_rules')
            keys(rule.coverage_rule_refs)
            for ref in rule.coverage_rule_refs:
                bound_rule(ref, 'coverage')
            if not _known(prior.effective, 'original_decision_current_effect'):
                _needs('effective_original_decision_coverage')
            if permit is not None and (permit.status != 'valid' or not _known(permit.effective, 'original_permit_current_effect')
                    or not permit.effective_window.contains(now)):
                _needs('valid_original_permit_coverage')
            effect = read(prior.effect_rule_ref, GovChangeEffectView, True, True)
            if effect.decision_ref != prior.ref or effect.outcome != prior.outcome:
                raise ValueError('Original coverage effect belongs to another decision')
            delivered(prior, effect)
            return complete(choice, covered_scope=scope, basis_refs=rule.coverage_rule_refs)

        if rule.decision_basis_ref is None or submission is None:
            _needs('original_change_basis_and_affected_submission')
        basis = read(rule.decision_basis_ref, GovChangeBasisView); author(basis, True)
        draft = basis.draft
        if (basis.transition_rule_ref != rule.ref or basis.application_ref != action_input.application_ref
                or basis.content_sha256 != submission.content_sha256 or draft.outcome != choice
                or draft.prior_decision_ref != prior.ref or draft.case_ref != prior.case_ref or draft.submission_ref != submission.ref
                or draft.covered_scope != scope or draft.decision_basis_ref != basis.ref):
            raise ValueError('Change draft substitutes original prior decision, case, version, scope or independent basis')
        if permit is None and not _known(prior.changeable, 'original_decision_changeability'):
            _needs('actual_permit_or_changeable_original_decision')
        if permit is not None:
            if permit.status == 'unknown':
                _needs('known_original_permit_status')
            if choice == 'restore' and permit.status != 'suspended':
                _needs('original_suspended_permit_for_restoration')
            if choice in {'suspend', 'revoke'} and permit.status not in {'valid', 'suspended'}:
                _needs('original_applicable_permit_for_change')
        outcome_rule = bound_rule(basis.outcome_rule_ref, 'outcome')
        if outcome_rule.choice != choice or outcome_rule.decision_basis_ref != basis.ref:
            raise ValueError('Change outcome lacks its independent original rule')
        authority = read(basis.authority_ref, GovChangeAuthorityView)
        if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                or authority.prior_decision_ref != prior.ref or authority.permit_ref != action_input.permit_ref
                or authority.decision_basis_ref != basis.ref or choice not in authority.outcomes
                or not _known(authority.permitted, 'original_independent_change_authority')):
            _needs('independent_original_change_signer_authority', [authority.ref])
        if basis.signer_authorization_ref not in context.authorization_refs:
            raise ValueError('Change signer authorization is absent from the acting context')
        authorize(basis.signer_authorization_ref, context.actor_id, context.function_ref, org, 'GOV-A09', now)
        effect = read(draft.effect_rule_ref, GovChangeEffectView)
        if (effect.decision_basis_ref != basis.ref or effect.outcome != choice or effect.expiry_rule_ref != draft.expiry_rule_ref
                or keys(effect.next_procedure_refs) != keys(draft.next_procedure_refs)
                or not draft.reason.strip() or not draft.notification_recipient_ids
                or len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids)
                or set(draft.notification_recipient_ids) != set(effect.notification_recipient_ids)
                or prior.applicant_id not in draft.notification_recipient_ids):
            raise ValueError('Change effect or recipients differ from original authorized draft')
        command = read(basis.command_ref, GovDecisionCommandView)
        if (command.case_ref != prior.case_ref or command.submission_ref != submission.ref or command.decision_basis_ref != basis.ref
                or command.operation_id != context.operation_id or command.draft_sha256 != content_digest(draft)):
            raise ValueError('Change command substitutes original operation, business draft, case or version')
        if prior.history_coverage != 'complete' or prior.as_of != now:
            _needs('complete_current_original_decision_change_history')
        keys(prior.history_refs)
        existing = [read(ref, GovTransitionDecisionView, True, True) for ref in prior.history_refs]
        if any(row.case_ref != prior.case_ref for row in existing):
            raise ValueError('Change history substitutes another original case')
        same = [row for row in existing if row.business_key == command.business_key]
        if len(same) > 1:
            raise ValueError('Change history repeats the original business decision')
        if same:
            official = same[0]
            if (official.command_ref != command.ref or official.draft_sha256 != command.draft_sha256
                    or official.submission_ref != submission.ref or official.signer_actor_id != context.actor_id
                    or official.signer_function_ref != context.function_ref):
                raise ValueError('Original recorded change differs from its original command/draft/signer')
            delivered(official, effect)
            return wait('government-transition-recorded-change-notification-continuation', [official.ref])
        if command.official_decision_ref is not None or command.status == 'recorded' or command.lookup_status == 'present':
            _needs('original_recorded_change_in_complete_history')
        if command.status == 'submitted_unknown' or command.lookup_status == 'unknown':
            return wait('government-transition-query-original-command', [command.ref])
        if command.status == 'failed':
            technical('government-transition-original-command-failed')
        old_conditions = keys([row.condition_rule_ref for row in prior.conditions])
        new_conditions = keys([row.condition_rule_ref for row in draft.conditions])
        if keys(basis.removed_condition_rule_refs) != old_conditions - new_conditions:
            raise ValueError('Change draft silently drops or invents removed original conditions')
        for ref in basis.removed_condition_rule_refs:
            bound_rule(ref, 'condition')
        approved_conditions = []
        for ref in basis.condition_basis_refs:
            row = read(ref, GovDecisionConditionBasisView); author(row, True)
            if (row.decision_basis_ref != basis.ref or row.deferred_check_refs
                    or not _known(row.permitted, 'original_change_condition_permission')):
                _needs('independently_authorized_original_change_conditions', [ref])
            approved_conditions.append(row.condition)
        keys(basis.condition_basis_refs)
        if sorted(content_digest(c) for c in approved_conditions) != sorted(content_digest(c) for c in draft.conditions):
            raise ValueError('Change conditions differ from complete independently authorized condition bases')
        for condition in draft.conditions:
            bound_rule(condition.condition_rule_ref, 'condition')
            if not scope_covers(scope, condition.covered_scope):
                raise ValueError('Change condition leaves authorized local scope')
            read(condition.verifier_binding_ref, RoleAssignment)
            method = read(condition.verification_method_ref, GovDecisionMethodView)
            if method.function_ref != condition.verifier_binding_ref or not _known(method.supported, 'change_condition_method_support'):
                _needs('original_supported_change_condition_verifier')
            authorize(method.authority_ref, method.actor_id, method.function_ref, method.organization_id, method.action_id, now)
            for ref in [*condition.affected_action_refs, *condition.required_evidence_refs,
                    *([condition.due_rule_ref] if condition.due_rule_ref else [])]:
                binding = read(ref, GovDecisionBindingView)
                if binding.decision_basis_ref != basis.ref or not scope_covers(condition.covered_scope, binding.scope):
                    raise ValueError('Change condition substitutes original actions, requirements or deadline')
        if draft.expiry_rule_ref is not None:
            expiry = read(draft.expiry_rule_ref, GovDecisionBindingView)
            if expiry.decision_basis_ref != basis.ref:
                raise ValueError('Change expiry belongs to another independent basis')
        for ref in draft.next_procedure_refs:
            next_procedure = read(ref, GovChangeProcedureView)
            if next_procedure.decision_basis_ref != basis.ref:
                raise ValueError('Next change procedure belongs to another independent basis')
        # This local change route requires a complete current procedure and current-version findings.
        procedure = read(basis.procedure_ref, GovChangeProcedureView)
        if not procedure.modeled:
            _unsupported('government-transition-unmodeled-change-procedure')
        if procedure.decision_basis_ref != basis.ref:
            raise ValueError('Change procedure belongs to another independent basis')
        checks = keys(procedure.required_check_refs)
        findings = {key: [] for key in checks}
        for ref in draft.assessment_refs:
            assessment = read(ref, GovDecisionAssessmentView, True); author(assessment)
            if (assessment.author_organization_id != org or assessment.case_ref != prior.case_ref
                    or assessment.submission_ref != submission.ref or assessment.content_sha256 != submission.content_sha256
                    or assessment.status != 'valid'):
                _needs('original_current_version_change_assessments', [ref])
            keys(assessment.check_result_refs)
            for result_ref in assessment.check_result_refs:
                result = read(result_ref, GovDecisionFindingView, True); author(result)
                if (result.assessment_ref != assessment.ref or result.submission_ref != submission.ref
                        or result.content_sha256 != submission.content_sha256 or result.check_ref.key() not in checks
                        or result.author_organization_id != org):
                    raise ValueError('Change finding substitutes original assessment, version or necessary check')
                check = read(result.check_ref, GovChangeCheckView)
                check_rule = bound_rule(check.rule_ref, 'outcome')
                if check.decision_basis_ref != basis.ref or check_rule.choice != choice or not check.allowed_findings:
                    raise ValueError('Change check substitutes independent outcome-specific requirements')
                evidence(result.verification_evidence_refs); reading.resolve(result.method_ref)
                if result.status == 'failed':
                    technical('government-transition-original-verification-failed')
                if result.status == 'unsupported':
                    _unsupported('government-transition-original-verification-unmodeled')
                if result.status != 'ok' or result.finding not in check.allowed_findings or not result.verification_evidence_refs:
                    _needs('successful_original_change_check', [result_ref])
                findings[result.check_ref.key()].append(result.ref)
        keys(draft.assessment_refs)
        if any(not values for values in findings.values()):
            _needs('complete_original_change_checks')
        completion = read(procedure.completion_ref, GovProcedureCompletionView); author(completion)
        if (completion.procedure_ref != procedure.ref or completion.case_ref != prior.case_ref
                or completion.submission_ref != submission.ref or completion.content_sha256 != submission.content_sha256
                or completion.status != 'complete' or completion.author_organization_id != org):
            _needs('complete_original_change_procedure')
        verified = []
        for ref in completion.verification_refs:
            row = read(ref, GovProcedureVerificationView); author(row)
            requirement = read(row.requirement_ref, GovProcedureRequirementView)
            if (requirement.procedure_ref != procedure.ref or row.case_ref != prior.case_ref
                    or row.submission_ref != submission.ref or row.content_sha256 != submission.content_sha256
                    or row.author_organization_id != org or not _known(row.satisfied, 'original_change_procedure_satisfaction')):
                _needs('satisfied_original_change_procedure_requirement', [ref])
            verified.append(row.requirement_ref)
        keys(completion.verification_refs)
        if keys(verified) != keys(procedure.required_procedure_refs):
            _needs('complete_original_change_procedure_requirements')
        return complete(choice, draft=draft.model_dump(mode='python'))
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
