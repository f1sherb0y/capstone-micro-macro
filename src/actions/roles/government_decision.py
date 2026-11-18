"""GOV-A07 prepares independently authorized decisions and recovers original facts."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView
from src.actions.contracts.government_review_objects import GovReviewSubmissionView, GovReviewMethodView
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionBasisView, GovDecisionAuthorityView, GovDecisionProcedureView,
    GovDecisionRuleView, GovDecisionCheckView, GovDecisionFindingView, GovDecisionAssessmentView,
    GovDecisionReuseView, GovDecisionApplicabilityView, GovDecisionIssueView,
    GovProcedureRequirementView, GovProcedureVerificationView, GovProcedureCompletionView,
    GovDecisionConditionBasisView, GovDecisionEffectView, GovDecisionBindingView,
    GovDecisionMethodView, GovDecisionCommandView, GovFormalDecisionView, GovDecisionNotificationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_decision(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-decision-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-decision-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, historic=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-decision-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(scope, row.scope):
            raise ValueError('Decision source leaves original authorized scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_decision_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_decision_source', [ref])
        return row

    def authorize(ref, actor, function, organization, action, at):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        roles = {'GOV': 'Government', 'OWN': 'Owner', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        evidence(grant.basis_refs + assignment.basis_refs); clock(at); clock(grant.validity.start)
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Decision record changes original author/action/scope authority')
        if not grant.validity.contains(at):
            _needs('original_decision_authority_at_execution', [ref])
        return grant

    def author(row, action=None):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Decision source predates its original applicable execution')
        if action is not None and (row.author_organization_id != org or row.author_action_id != action):
            raise ValueError('Decision source substitutes responsible agency or original function')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at)

    def bound(row):
        if (getattr(row, 'case_ref', case.ref) != case.ref or row.submission_ref != submission.ref
                or row.content_sha256 != submission.content_sha256):
            raise ValueError('Decision evidence substitutes final application version/content or case')

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    try:
        case = read(action_input.case_ref, GovDecisionCaseView)
        submission = read(action_input.current_submission_ref, GovReviewSubmissionView)
        basis = read(action_input.decision_basis_ref, GovDecisionBasisView); author(basis, 'GOV-A07')
        bound(basis)
        draft = basis.draft; outcome = draft.outcome
        if (case.organization_id != org or case.current_submission_ref != submission.ref
                or submission.recipient_organization_id != org or submission.applicant_id != case.applicant_id
                or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref
                or submission.procedure_ref != case.procedure_ref
                or draft.case_ref != case.ref or draft.submission_ref != submission.ref or draft.covered_scope != scope
                or draft.decision_basis_ref != basis.ref or basis.signer_actor_id != context.actor_id
                or basis.signer_function_ref != context.function_ref):
            raise ValueError('Decision changes original agency/applicant/procedure/draft or acting signer')
        # Check specialization before any saved-decision/query return as well.
        # An unrelated checklist must never borrow the received procedure.
        if basis.procedure_ref != case.procedure_ref:
            checklist = read(basis.procedure_ref, GovDecisionProcedureView)
            if checklist.case_ref != case.ref or checklist.source_procedure_ref != case.procedure_ref:
                raise ValueError('Decision checklist changes its original case or received source procedure')
        if draft.prior_decision_ref is not None:
            _unsupported('government-decision-prior-decision-change-requires-GOV-A09')
        if case.history_coverage != 'complete' or case.as_of != now:
            _needs('complete_current_original_case_decision_history')
        if (keys(case.assessment_refs) != keys(action_input.assessment_refs)
                or keys(case.unresolved_issue_refs) != keys(action_input.unresolved_issue_refs)
                or keys(draft.assessment_refs) != keys(action_input.assessment_refs)):
            _needs('complete_original_decision_assessments_and_open_issues')
        keys(case.decision_refs)
        command = read(basis.command_ref, GovDecisionCommandView)
        draft_hash = content_digest(draft)
        if (command.case_ref != case.ref or command.submission_ref != submission.ref or command.decision_basis_ref != basis.ref
                or command.operation_id != context.operation_id or command.draft_sha256 != draft_hash):
            raise ValueError('Decision command changes original operation, application, basis or complete draft')
        effect = read(draft.effect_rule_ref, GovDecisionEffectView)
        if not effect.modeled:
            _unsupported('government-decision-unmodeled-effect')
        if (effect.decision_rule_ref != basis.decision_rule_ref or effect.outcome != outcome
                or not draft.notification_recipient_ids or len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids)
                or set(draft.notification_recipient_ids) != set(effect.notification_recipient_ids)
                or case.applicant_id not in draft.notification_recipient_ids):
            raise ValueError('Decision effect/notification plan changes original authorized outcome or recipients')

        # Known formal facts take precedence over replaying a command. Do not create a second decision.
        existing = [read(ref, GovFormalDecisionView, True) for ref in case.decision_refs]
        if any(row.case_ref != case.ref for row in existing):
            raise ValueError('Decision history substitutes another original case')
        same_business = [row for row in existing if row.business_key == command.business_key]
        if len(same_business) > 1:
            raise ValueError('Formal decision history repeats an original decision business identity')
        official = same_business[0] if same_business else None
        if official is not None:
            if (official.command_ref != command.ref or official.draft_sha256 != draft_hash
                    or official.submission_ref != submission.ref
                    or official.signer_actor_id != basis.signer_actor_id or official.signer_function_ref != basis.signer_function_ref
                    or command.official_decision_ref not in (None, official.ref)):
                raise ValueError('Recovered formal decision differs from original command/draft/signer')
            keys(official.notification_refs)
            notified = set()
            for ref in official.notification_refs:
                notification = read(ref, GovDecisionNotificationView, True)
                if notification.decision_ref != official.ref or notification.recipient_id not in draft.notification_recipient_ids:
                    raise ValueError('Decision notification concerns another original fact or recipient')
                if notification.status == 'delivered':
                    if notification.delivered_at is None:
                        raise ValueError('Actual decision delivery needs its original delivery time')
                    clock(notification.delivered_at)
                    if notification.delivered_at.offset > notification.available_at.offset:
                        raise ValueError('Decision notification predates actual delivery')
                    notified.add(notification.recipient_id)
            if effect.mode == 'on_actual_delivery' and isinstance(official.effective, Known) and official.effective.value:
                if notified != set(draft.notification_recipient_ids):
                    _needs('actual_original_decision_delivery_before_effect', [official.ref])
            return wait('government_decision_recorded_resume_notification_without_resubmission', [official.ref])
        if command.official_decision_ref is not None or command.lookup_status == 'present' or command.status == 'recorded':
            _needs('original_formal_decision_fact_for_command', [command.ref])
        if command.status in {'submitted_unknown', 'failed'} and command.lookup_status != 'absent':
            return wait('government_decision_query_unknown_submission_before_retry', [command.ref])
        if command.lookup_status == 'unknown':
            return wait('government_decision_query_unresolved_formal_fact', [command.ref])
        if submission.receipt_status != 'received' or submission.status != 'active' or case.status in {'closed', 'withdrawn'}:
            return wait('government_decision_case_not_ready', [case.ref, submission.ref])
        authorize(basis.signer_authorization_ref, context.actor_id, context.function_ref, org, 'GOV-A07', now)
        authority = read(basis.decision_authority_ref, GovDecisionAuthorityView)
        if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                or authority.case_ref != case.ref or authority.submission_ref != submission.ref or authority.decision_basis_ref != basis.ref
                or outcome not in authority.outcomes):
            raise ValueError('Decision lacks independent original outcome/signer authority')
        if not _known(authority.permitted, 'original_independent_decision_signing_permission'):
            _needs('authorized_original_decision_signing', [authority.ref])
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView); matter = read(case.matter_ref, GovMatterView)
        region = _known(case.region_id, 'decision_case_region')
        if (jurisdiction.organization_id != org or region not in _known(jurisdiction.covered_project_region_ids, 'decision_jurisdiction_regions')
                or matter.matter_code not in _known(jurisdiction.covered_matter_codes, 'decision_jurisdiction_matters')
                or region != _known(matter.project_region_id, 'decision_matter_region')
                or not any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)):
            raise ValueError('Agency lacks original lawful decision jurisdiction')
        procedure = read(basis.procedure_ref, GovDecisionProcedureView)
        rule = read(basis.decision_rule_ref, GovDecisionRuleView)
        if not procedure.modeled:
            _unsupported('government-decision-unmodeled-procedure')
        if (procedure.case_ref != case.ref
                or (procedure.source_procedure_ref or procedure.ref) != case.procedure_ref
                or rule.case_ref != case.ref or rule.procedure_ref != procedure.ref
                or rule.outcome != outcome or rule.effect_rule_ref != effect.ref or rule.expiry_rule_ref != draft.expiry_rule_ref
                or keys(rule.next_procedure_refs) != keys(draft.next_procedure_refs)):
            raise ValueError('Decision draft changes original independent procedure/outcome/effect rules')
        if not _known(rule.permitted, 'original_outcome_rule_permission'):
            _needs('permitted_original_decision_outcome', [rule.ref])
        for ref in draft.next_procedure_refs:
            read(ref, GovDecisionProcedureView)
        if draft.expiry_rule_ref is not None:
            expiry = read(draft.expiry_rule_ref, GovDecisionBindingView)
            if expiry.decision_basis_ref != basis.ref:
                raise ValueError('Decision expiry rule belongs to another original basis')
        checks = [read(ref, GovDecisionCheckView) for ref in procedure.required_check_refs]
        check_map = {check.ref.key(): check for check in checks}
        keys(procedure.required_check_refs); keys(procedure.required_procedure_refs)
        if not checks:
            _needs('nonempty_original_necessary_decision_checks')
        findings = {check.ref.key(): [] for check in checks}
        for ref in action_input.assessment_refs:
            assessment = read(ref, GovDecisionAssessmentView, True); author(assessment)
            if (assessment.case_ref != case.ref or assessment.status != 'valid'
                    or assessment.author_action_id not in {'GOV-A04', 'GOV-A05', 'GOV-A06', 'GOV-A08', 'GOV-A10', 'GOV-A11'}
                    or assessment.author_organization_id != org):
                _needs('original_valid_responsible_agency_review', [ref])
            reused = None
            if assessment.submission_ref != submission.ref or assessment.content_sha256 != submission.content_sha256:
                if assessment.reuse_basis_ref is None:
                    _needs('original_explicit_final_version_review_reuse', [ref])
                reused = read(assessment.reuse_basis_ref, GovDecisionReuseView); author(reused, 'GOV-A06'); bound(reused)
                if (reused.assessment_ref != assessment.ref or reused.original_submission_ref != assessment.submission_ref
                        or reused.original_content_sha256 != assessment.content_sha256
                        or keys(reused.reusable_check_refs) & keys(reused.affected_check_refs)):
                    raise ValueError('Decision reuse mixes affected checks or original/final content versions')
                if not _known(reused.permitted, 'original_decision_review_reuse_permission'):
                    _needs('permitted_original_final_version_review_reuse', [ref])
            keys(assessment.check_result_refs)
            for result_ref in assessment.check_result_refs:
                result = read(result_ref, GovDecisionFindingView, True); result_grant = author(result)
                if (result.assessment_ref != assessment.ref or result.submission_ref != assessment.submission_ref
                        or result.content_sha256 != assessment.content_sha256 or result.author_organization_id != org
                        or result.available_at.offset > assessment.authored_at.offset):
                    raise ValueError('Decision finding lacks its original reviewed version and responsible execution')
                if result.check_ref.key() not in findings:
                    raise ValueError('Assessment includes a check outside the original decision procedure')
                if not scope_covers(result.scope, check_map[result.check_ref.key()].scope):
                    _needs('original_review_execution_covers_necessary_check_scope', [result.ref])
                if not keys(result.verification_evidence_refs) <= keys(result_grant.readable_refs):
                    raise ValueError('Original finding author lacks read authority for its verification evidence')
                if reused is not None and result.check_ref not in reused.reusable_check_refs:
                    continue
                if result.status == 'failed':
                    technical('original_decision_review_method_failed')
                if result.status == 'unsupported':
                    _unsupported('government-decision-original-review-method')
                evidence(result.verification_evidence_refs)
                descriptor=(read(result.method_descriptor_ref,GovReviewMethodView)
                    if result.method_descriptor_ref is not None else reading.resolve(result.method_ref))
                if result.method_descriptor_ref is not None and (
                        getattr(descriptor,'calculation_method_ref',None)!=result.method_ref
                        or getattr(descriptor,'organization_id',None)!=org
                        or getattr(descriptor,'executor_authority_ref',None)!=result.author_authority_ref
                        or getattr(descriptor,'executor_function_ref',None)!=result.author_function_ref
                        or getattr(descriptor,'executor_actor_id',None)!=result.author_actor_id
                        or getattr(descriptor,'execution_action_id',None)!=result.author_action_id
                        or descriptor.purpose!='rule_check' or check_map[result.check_ref.key()].rule_ref not in descriptor.rule_refs
                        or not _known(descriptor.supported,'original_review_descriptor_method_support')):
                    raise ValueError('Decision finding changes its original calculation descriptor or executor')
                finding = result.finding if result.status == 'ok' else 'unknown'
                if finding != 'unknown' and not result.verification_evidence_refs:
                    _needs('original_successful_review_verification_evidence', [result.ref])
                if finding == 'not_applicable':
                    if result.applicability_basis_ref is None:
                        _needs('original_inapplicability_basis', [result.ref])
                    applicability = read(result.applicability_basis_ref, GovDecisionApplicabilityView); author(applicability); bound(applicability)
                    if applicability.check_ref != result.check_ref or not isinstance(applicability.applicable, Known) or applicability.applicable.value:
                        raise ValueError('Unknown/positive applicability cannot yield an inapplicable decision check')
                findings[result.check_ref.key()].append(finding)
        states = {}
        for key, values in findings.items():
            states[key] = 'nonconforms' if 'nonconforms' in values else (
                'unknown' if not values or 'unknown' in values or {'conforms', 'not_applicable'} <= set(values)
                else ('not_applicable' if set(values) == {'not_applicable'} else 'conforms'))
        issues = [read(ref, GovDecisionIssueView) for ref in action_input.unresolved_issue_refs]
        for issue in issues:
            if issue.case_ref != case.ref or issue.submission_ref != submission.ref or issue.status != 'open':
                raise ValueError('Decision open issue set substitutes final case/submission or resolved status')
        complete = not procedure.required_procedure_refs
        if action_input.procedure_completion_ref is not None:
            completion = read(action_input.procedure_completion_ref, GovProcedureCompletionView); author(completion); bound(completion)
            if completion.author_organization_id != org or not completion.author_action_id.startswith('GOV-'):
                raise ValueError('Procedure completion is not from the responsible original agency')
            if completion.procedure_ref != procedure.ref:
                raise ValueError('Necessary procedure completion covers another original procedure')
            keys(completion.verification_refs); verified = {}
            for ref in completion.verification_refs:
                row = read(ref, GovProcedureVerificationView); author(row); bound(row)
                if (row.author_organization_id != org or not row.author_action_id.startswith('GOV-')
                        or row.available_at.offset > completion.authored_at.offset):
                    raise ValueError('Procedure completion predates responsible original verification')
                requirement = read(row.requirement_ref, GovProcedureRequirementView)
                if requirement.procedure_ref != procedure.ref or row.requirement_ref.key() in verified:
                    raise ValueError('Necessary procedure evidence repeats or substitutes original requirement')
                verified[row.requirement_ref.key()] = isinstance(row.satisfied, Known) and row.satisfied.value
            complete = (completion.status == 'complete' and set(verified) == keys(procedure.required_procedure_refs) and all(verified.values()))
        blocked = [check for check in checks if states[check.ref.key()] not in {'conforms', 'not_applicable'}]
        if outcome in {'approve', 'approve_with_conditions'}:
            if not complete or any(issue.blocks_approval for issue in issues):
                _needs('all_original_approval_procedures_and_blocking_issues_satisfied')
            if any(check.required_before_approval for check in blocked):
                _needs('all_original_preapproval_necessary_checks_satisfied')
        elif not rule.permits_incomplete_review and (not complete or blocked):
            _needs('original_required_review_before_adverse_or_deferred_decision')
        if outcome == 'refuse':
            keys(rule.required_nonconforming_check_refs)
            if not rule.required_nonconforming_check_refs or any(states.get(ref.key()) != 'nonconforms' for ref in rule.required_nonconforming_check_refs):
                _needs('independent_original_proven_refusal_grounds')
        if not keys(rule.issue_refs) <= keys(action_input.unresolved_issue_refs):
            raise ValueError('Outcome rule cites an issue outside the original open set')
        if outcome in {'refuse', 'defer_by_procedure'}:
            if draft.conditions or draft.expiry_rule_ref is not None or effect.mode != 'no_permission':
                raise ValueError('Refusal/deferment cannot carry permission conditions or approval effect')
        elif effect.mode == 'no_permission':
            raise ValueError('Approval must have an explicitly modeled original permission effect')
        deferred_checks = set()
        if outcome == 'approve_with_conditions':
            if not draft.conditions or not basis.condition_basis_refs:
                _needs('independent_original_conditional_approval_conditions')
            keys(basis.condition_basis_refs); condition_bases = []
            for ref in basis.condition_basis_refs:
                row = read(ref, GovDecisionConditionBasisView); author(row, 'GOV-A07')
                if row.decision_basis_ref != basis.ref or not _known(row.permitted, 'original_condition_permission'):
                    raise ValueError('Condition has no independent original decision basis')
                condition_bases.append(row)
                deferred_checks |= keys(row.deferred_check_refs)
            if [row.condition for row in condition_bases] != draft.conditions:
                raise ValueError('Draft conditions differ from original independently authorized conditions')
            if not {check.ref.key() for check in blocked} <= deferred_checks or not deferred_checks <= keys(procedure.required_check_refs):
                _needs('every_deferred_postapproval_check_bound_to_authorized_condition')
            if any(check.required_before_approval and check.ref.key() in deferred_checks for check in checks):
                raise ValueError('Conditional approval cannot defer a necessary preapproval check')
            for condition in draft.conditions:
                if not scope_covers(scope, condition.covered_scope):
                    raise ValueError('Condition leaves original decision scope')
                reading.resolve(condition.condition_rule_ref)
                read(condition.verifier_binding_ref, RoleAssignment)
                method = read(condition.verification_method_ref, GovDecisionMethodView)
                if method.function_ref != condition.verifier_binding_ref or not _known(method.supported, 'condition_verifier_method_support'):
                    _needs('original_supported_condition_verifier_binding')
                authorize(method.authority_ref, method.actor_id, method.function_ref, method.organization_id, method.action_id, now)
                for ref in [*condition.affected_action_refs, *condition.required_evidence_refs, *([condition.due_rule_ref] if condition.due_rule_ref else [])]:
                    binding = read(ref, GovDecisionBindingView)
                    if binding.decision_basis_ref != basis.ref or not scope_covers(condition.covered_scope, binding.scope):
                        raise ValueError('Condition requirement changes original authorized basis/scope')
        elif draft.conditions or basis.condition_basis_refs:
            raise ValueError('Only conditional approval may carry postapproval conditions')
        if outcome == 'approve' and blocked:
            _needs('all_original_approval_checks_satisfied')
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': outcome, 'scope': scope, 'draft': draft.model_dump(mode='python'),
            'note': 'Authorized draft only; the formal service creates the signed ID and effect. No applicant acceptance gate, cash, fee clearance or project start is inferred. Actual delivery is required when the effect rule requires it.'}}
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
