"""GOV-A11 separates actual completion, use assessment and continuing obligations."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_use_objects import (
    GovUseApplicationView, GovUseApplicationAuthorityView, GovUseProcedureView, GovUseWorkFactView,
    GovUseConditionView, GovUseDecisionBasisView, GovUseRuleView, GovUseQuestionView,
    GovUsePlanView, GovUseCapacityResultView, GovUseCaseView, GovReviewSubmissionView, GovDecisionIssueView,
    GovDecisionAuthorityView, GovDecisionCheckView, GovDecisionFindingView, GovDecisionAssessmentView,
    GovDecisionApplicabilityView, GovProcedureCompletionView, GovProcedureVerificationView,
    GovProcedureRequirementView, GovDecisionConditionBasisView, GovDecisionEffectView,
    GovDecisionBindingView, GovDecisionMethodView, GovPermitView, GovRecipientView,
    GovResponseRequirementView, GovSchedulingTaskView, GovSchedulingWorkProfileView,
    GovSchedulingEstimateView, GovSchedulingDependencyView, GovReviewCalendarView,
    GovReviewResourceView, GovReviewQualificationView, GovReviewAssignmentView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityCommitment, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def review_use_and_supervision(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-use-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-use-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-use-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Use source widens original application scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_use_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_use_source', [ref])
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope=scope):
        grant = read(ref, Authorization, True); assignment = read(function, RoleAssignment, True)
        roles = {'GOV': 'Government', 'OWN': 'Owner', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Use source substitutes independent author/function/action/scope authority')
        evidence(grant.basis_refs + assignment.basis_refs); clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at):
            _needs('original_use_authority_at_execution', [ref])
        return grant

    def author(row, actions=None, own=False):
        clock(row.authored_at)
        if (row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at)
                or actions is not None and row.author_action_id not in actions
                or own and row.author_organization_id != org):
            raise ValueError('Use source substitutes original execution/author or responsible regulator')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def bound(row):
        if (row.case_ref != case.ref or row.submission_ref != submission.ref or row.content_sha256 != application.content_sha256):
            raise ValueError('Use evidence substitutes current independent use case/version/content')

    def original_rule(ref):
        row = read(ref, GovUseRuleView)
        if row.application_ref != application.ref or not _known(row.permitted, 'original_use_rule_permission'):
            _needs('original_current_use_rule_permission', [ref])
        return row

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'scope': scope, 'choice': choice, **fields,
            'note': 'Use-specific proposal only; A07 owns formal signing and effect, A10 owns continuing supervision. Existing conditions persist. Case closure releases only formally unused review assignments; no physical handover, stock addition, fee clearance, loan discharge or permit effect is inferred.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def covers(outer, inner):
        clock(outer.start); clock(inner.start)
        if outer.bounds != 'closed_open' or inner.bounds != 'closed_open':
            _unsupported('government-use-half-open-work-window')
        return outer.start.offset <= inner.start.offset < inner.end.offset <= outer.end.offset

    try:
        case = read(action_input.case_ref, GovUseCaseView)
        application = read(action_input.use_application_ref, GovUseApplicationView)
        submission = read(application.submission_ref, GovReviewSubmissionView)
        procedure = read(action_input.procedure_ref, GovUseProcedureView)
        if (case.organization_id != org or application.case_ref != case.ref or application.applicant_id != case.applicant_id
                or application.recipient_organization_id != org or case.current_submission_ref != submission.ref
                or submission.applicant_id != application.applicant_id or submission.recipient_organization_id != org
                or submission.content_sha256 != application.content_sha256 or application.scope != scope
                or procedure.organization_id != org or procedure.case_ref != case.ref or procedure.application_ref != application.ref
                or procedure.content_sha256 != application.content_sha256 or procedure.ref != case.procedure_ref
                or procedure.ref != application.procedure_ref or submission.procedure_ref != procedure.ref
                or submission.matter_ref != case.matter_ref or submission.jurisdiction_ref != case.jurisdiction_ref
                or not application.use_codes or set(application.use_codes) != set(procedure.use_codes)):
            raise ValueError('Use processing changes original agency/applicant/current version/independent procedure or use')
        if (application.history_coverage != 'complete' or application.as_of != now
                or case.history_coverage != 'complete' or case.as_of != now):
            _needs('complete_current_original_use_application_history')
        for field in ('completed_scope_refs', 'professional_proof_refs', 'test_result_refs', 'permit_refs', 'remaining_condition_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(application, field)):
                _needs('complete_original_use_application_' + field)
        if procedure.actor_id != context.actor_id or procedure.function_ref != context.function_ref or procedure.authorization_ref not in context.authorization_refs:
            raise ValueError('Use procedure substitutes original acting regulator/function')
        authorize(procedure.authorization_ref, context.actor_id, context.function_ref, org, 'GOV-A11', now)
        if not procedure.modeled:
            _unsupported('government-use-procedure-unmodeled')
        if not _known(procedure.permitted, 'independent_original_use_procedure_permission'):
            _needs('permitted_original_use_procedure')
        clock(application.submitted_at)
        if (application.submitted_at.offset > application.available_at.offset or application.receipt_status != 'received'
                or application.status != 'active' or submission.receipt_status != 'received' or submission.status != 'active'
                or not _known(application.signed, 'original_use_application_signature')):
            _needs('received_active_signed_original_use_application')
        request_authority = read(application.application_authority_ref, GovUseApplicationAuthorityView, True)
        if (request_authority.application_ref != application.ref or request_authority.applicant_id != application.applicant_id
                or request_authority.submitter_id != application.submitter_id
                or not request_authority.effective_window.contains(application.submitted_at)
                or not _known(request_authority.permitted, 'original_use_applicant_submitter_delegation')):
            _needs('authorized_original_use_application_submitter')
        authorize(request_authority.authorization_ref, request_authority.actor_id, request_authority.function_ref,
            request_authority.organization_id, request_authority.action_id, application.submitted_at)
        for ref in action_input.permit_refs:
            permit = read(ref, GovPermitView, True, True)
            if permit.organization_id != org or not scope_covers(permit.scope, scope):
                raise ValueError('Use application substitutes existing regulator/permit coverage')
        conditions = [read(ref, GovUseConditionView, linked=True) for ref in action_input.remaining_condition_refs]
        for row in conditions:
            if row.permit_ref.key() not in keys(action_input.permit_refs) or row.status in {'released', 'satisfied'}:
                raise ValueError('Remaining use condition substitutes an existing permit or cleared obligation')
            if original_rule(row.condition_rule_ref).condition_ref != row.ref:
                raise ValueError('Continuing use condition substitutes its independent original rule')
        choice = procedure.choice
        if choice == 'request_evidence':
            if not procedure.question_refs:
                _needs('concrete_original_use_evidence_questions')
            keys(procedure.question_refs); questions = []
            for ref in procedure.question_refs:
                row = read(ref, GovUseQuestionView); q = row.question
                basis = original_rule(q.requirement_ref)
                if (row.application_ref != application.ref or basis.question_ref != row.ref
                        or not scope_covers(scope, q.scope) or row.ref.key() not in keys(q.target_refs) or not q.recipient_refs):
                    raise ValueError('Use evidence question substitutes current application/rule/target/scope')
                response = read(q.response_requirement_ref, GovResponseRequirementView)
                if response.rule_ref != basis.ref or response.scope != q.scope:
                    raise ValueError('Use question substitutes its original response requirement')
                for target in q.target_refs:
                    original = read(target, GovUseQuestionView)
                    if original.application_ref != application.ref or original.question != q:
                        raise ValueError('Use question mixes unrelated original targets')
                for recipient_ref in q.recipient_refs:
                    recipient = read(recipient_ref, GovRecipientView)
                    if not scope_covers(recipient.scope, q.scope):
                        raise ValueError('Use question recipient lacks local coverage')
                keys(q.recipient_refs); evidence(q.evidence_refs); questions.append(q.model_dump(mode='python'))
            return complete(choice, questions=questions)

        if choice in {'plan_verification', 'continue_supervision'}:
            if procedure.plan_ref is None:
                _needs('original_independently_prepared_use_plan')
            plan_source = read(procedure.plan_ref, GovUsePlanView); author(plan_source, {'GOV-A03'}, True)
            expected_purpose = 'use_verification' if choice == 'plan_verification' else 'continuing_supervision'
            if plan_source.application_ref != application.ref or plan_source.content_sha256 != application.content_sha256 or plan_source.purpose != expected_purpose:
                raise ValueError('Use plan substitutes current application/version or verification/supervision purpose')
            plan = plan_source.plan
            if not plan.items or keys([i.task_ref for i in plan.items]) != keys(plan_source.task_refs):
                raise ValueError('Use plan changes complete original authorized task set')
            if choice == 'continue_supervision':
                if not conditions or any(not c.supervision_task_refs for c in conditions) or not {r.key() for c in conditions for r in c.supervision_task_refs} <= keys(plan_source.task_refs):
                    _needs('original_supervision_tasks_for_all_retained_conditions')
            work = read(plan.work_profile_ref, GovSchedulingWorkProfileView)
            calendar = read(plan_source.resource_calendar_ref, GovReviewCalendarView)
            if work.organization_id != org or calendar.organization_id != org or calendar.coverage != 'complete' or calendar.as_of != now:
                _needs('complete_current_original_use_plan_resource_snapshot')
            resources = {}; personnel = set(); required_sources = [work.ref, calendar.ref]
            for embedded in calendar.resources:
                row = read(embedded.ref, GovReviewResourceView)
                if row != embedded or row.organization_id != org:
                    raise ValueError('Use calendar substitutes original resource capacity')
                persons = _known(row.personnel_ids, 'original_use_review_personnel')
                if len(set(persons)) != len(persons) or personnel.intersection(persons):
                    raise ValueError('Use review calendar repeats the same physical person in distinct resources')
                personnel.update(persons); resources[row.ref.key()] = row; required_sources.append(row.ref)
                evidence([row.total.basis_ref])
            keys([row.ref for row in calendar.resources]); keys([row.commitment_ref for row in calendar.commitments])
            commitments = {row.commitment_ref.key(): read(row.commitment_ref, CapacityCommitment) for row in calendar.commitments}
            if any(commitments[row.commitment_ref.key()] != row or row.resource_ref.key() not in resources for row in calendar.commitments):
                raise ValueError('Use calendar substitutes actual original commitment/resource')
            required_sources.extend(row.commitment_ref for row in calendar.commitments)
            demands, reused, investments = [], set(), set()
            productivity = decimal_fraction(work.effort_per_capacity_tick)
            if productivity <= 0:
                raise ValueError('Use review productivity must be positive')
            for item in plan.items:
                task = read(item.task_ref, GovSchedulingTaskView); required_sources.append(task.ref)
                action = 'GOV-A11' if choice == 'plan_verification' else 'GOV-A10'
                if (task.organization_id != org or task.case_ref != case.ref or task.execution_action_id != action
                        or task.work_profile_ref != work.ref or task.status != 'authorized' or task.as_of != now
                        or item.window != task.planned_window or item.existing_assignment_ref != task.existing_assignment_ref
                        or keys(item.dependency_refs) != keys(task.dependency_refs)):
                    raise ValueError('Use plan changes actual original task, execution function, current window or dependencies')
                duration = item.window.end.offset - item.window.start.offset
                if (duration <= 0 or item.window.start.offset < now.offset or duration > work.maximum_assignment_ticks
                        or not covers(work.effective_window, item.window) or not covers(task.effective_window, item.window)):
                    _needs('finite_current_original_use_work_window')
                for ref in item.dependency_refs:
                    dependency = read(ref, GovSchedulingDependencyView); required_sources.append(ref)
                    if dependency.task_ref != task.ref or dependency.as_of != now or not _known(dependency.satisfied, 'original_use_task_dependency'):
                        return wait('government-use-verification-dependency-wait', [ref])
                estimate = read(task.estimate_ref, GovSchedulingEstimateView); required_sources.append(estimate.ref); clock(estimate.executed_at)
                if (estimate.task_ref != task.ref or estimate.work_profile_ref != work.ref or estimate.effort.unit != work.effort_unit
                        or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset)):
                    raise ValueError('Use plan substitutes original task effort estimate/unit/execution')
                if estimate.status == 'failed':
                    technical('government-use-original-plan-estimate-failed')
                if estimate.status != 'succeeded' or task.work_fact_coverage != 'complete':
                    _needs('successful_original_use_work_estimate_and_history')
                remaining = decimal_fraction(estimate.effort.value); evidence([estimate.effort.basis_ref])
                keys(task.work_fact_refs)
                for ref in task.work_fact_refs:
                    fact = read(ref, GovUseWorkFactView, True); author(fact, own=True); required_sources.append(ref); clock(fact.window.end)
                    if (fact.work_kind != 'review_effort' or fact.task_ref != task.ref or fact.case_ref != case.ref
                            or fact.investment_key in investments or fact.effort.unit != work.effort_unit
                            or fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset)):
                        raise ValueError('Use plan substitutes or repeats actual completed review investment')
                    investments.add(fact.investment_key); evidence([fact.effort.basis_ref]); spent = decimal_fraction(fact.effort.value)
                    if spent <= 0:
                        raise ValueError('Use review waiting is not actual positive investment')
                    remaining -= spent
                if decimal_fraction(estimate.effort.value) <= 0:
                    raise ValueError('Original use work estimate must be positive')
                declared = _known(task.remaining_effort, 'original_use_plan_remaining_effort')
                if (remaining <= 0 or declared.unit != work.effort_unit or decimal_fraction(declared.value) != remaining or item.effort != declared):
                    raise ValueError('Use plan effort differs from original estimate minus actual completed work')
                evidence([declared.basis_ref]); shares = [decimal_fraction(s.share) for s in task.resource_shares]
                if any(s <= 0 for s in shares) or sum(shares, Fraction()) != 1 or item.resource_ids != [s.resource_ref.id for s in task.resource_shares]:
                    raise ValueError('Use plan changes physical resource shares/identities or total effort')
                keys([s.resource_ref for s in task.resource_shares])
                if item.existing_assignment_ref is not None:
                    assignment = read(item.existing_assignment_ref, GovReviewAssignmentView); required_sources.append(assignment.ref)
                    if (assignment.task_ref != task.ref or assignment.organization_id != org or assignment.case_ref != case.ref
                            or assignment.work_profile_ref != work.ref or assignment.window != item.window or assignment.status != 'effective'
                            or keys(assignment.resource_refs) != keys([s.resource_ref for s in task.resource_shares]) or not assignment.commitment_refs):
                        raise ValueError('Use plan changes the original continuing assignment')
                    for ref in assignment.commitment_refs:
                        row = commitments.get(ref.key())
                        if row is None or ref.key() in reused or row.resource_ref.key() not in keys(assignment.resource_refs) or row.window != item.window:
                            raise ValueError('Use plan repeats or borrows another original assignment occupancy')
                        reused.add(ref.key())
                for share, fraction in zip(task.resource_shares, shares):
                    resource = resources.get(share.resource_ref.key())
                    if resource is None or not covers(resource.effective_window, item.window) or task.function_code not in resource.function_codes:
                        _needs('suitable_available_original_use_review_resource')
                    if not _known(resource.personnel_ids, 'actual_use_review_personnel'):
                        _needs('nonempty_original_use_review_personnel')
                    grant = authorize(resource.authority_ref, resource.actor_id, resource.function_ref, org, action, item.window.start, task.scope)
                    if not covers(grant.validity, item.window) or not set(task.discipline_codes) <= set(resource.discipline_codes):
                        _needs('original_use_review_executor_for_full_window')
                    qualifications = [read(ref, GovReviewQualificationView) for ref in resource.qualification_refs]
                    required_sources.extend(resource.qualification_refs); keys(resource.qualification_refs)
                    for person in _known(resource.personnel_ids, 'use_plan_actual_reviewer'):
                        for discipline in task.discipline_codes:
                            if not any(q.organization_id == org and q.region_id == resource.region_id and person in q.personnel_ids
                                    and discipline in q.discipline_codes and task.function_code in q.function_codes
                                    and isinstance(q.valid, Known) and q.valid.value and covers(q.effective_window, item.window) for q in qualifications):
                                _needs('qualified_original_use_review_personnel')
                    demands.append({'resource_kind': resource.ref.id, 'region_id': resource.region_id, 'unit': work.capacity_unit,
                        'amount': ExactAmount.from_fraction(remaining * fraction / (duration * productivity)), 'window': item.window,
                        'basis_refs': task.evidence_refs})
            saved = read(plan_source.capacity_result_ref, GovUseCapacityResultView, True); grant = author(saved, {'GOV-A03'}, True)
            if saved.status == 'failed':
                technical('government-use-original-plan-calculation-failed')
            if saved.status == 'unsupported':
                _unsupported('government-use-original-plan-capacity-unmodeled')
            if saved.status != 'ok' or saved.report is None:
                _needs('successful_original_use_plan_capacity_result')
            data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
                resources=[{'resource_ref': r.ref, 'resource_kind': r.ref.id, 'region_id': r.region_id,
                    'total': r.total, 'effective_window': r.effective_window} for r in resources.values()],
                commitments=[r for key, r in commitments.items() if key not in reused], source_refs=saved.data.source_refs)
            if (saved.plan_ref != plan_source.ref or saved.method_ref != CAPACITY_METHOD or saved.plan_sha256 != content_digest(plan)
                    or data != saved.data or not {r.key() for r in required_sources} <= keys(saved.data.source_refs)
                    or not keys(saved.data.source_refs) <= keys(grant.readable_refs)):
                raise ValueError('Use plan saved result substitutes original full plan, current occupancy or original source read authority')
            if any(getattr(reading.resolve(ref), 'available_at', saved.authored_at).offset > saved.authored_at.offset for ref in saved.data.source_refs):
                raise ValueError('Use plan capacity execution predates its original readable source records')
            result = reading.calculate(CAPACITY_METHOD, data)
            if result.kind != 'ok':
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information':
                    raw['requested_refs'] = []
                raise ObservationGap(raw)
            if result.value != saved.report:
                raise ValueError('Use plan saved capacity result differs from current original sources')
            if not result.value.feasible:
                return wait('government-use-resource-capacity-wait', [calendar.ref])
            return complete(choice, plan=plan.model_dump(mode='python'), **({'condition_refs': action_input.remaining_condition_refs} if choice == 'continue_supervision' else {}))

        if procedure.decision_basis_ref is None:
            _needs('independent_original_use_decision_basis')
        basis = read(procedure.decision_basis_ref, GovUseDecisionBasisView); author(basis, {'GOV-A11'}, True)
        draft = basis.draft; outcome = draft.outcome
        if (basis.application_ref != application.ref or basis.content_sha256 != application.content_sha256
                or draft.case_ref != case.ref or draft.submission_ref != submission.ref or draft.covered_scope != scope
                or draft.decision_basis_ref != basis.ref or draft.prior_decision_ref is not None
                or keys(draft.assessment_refs) != keys(action_input.professional_proof_refs)
                or keys(basis.retained_condition_refs) != keys(action_input.remaining_condition_refs)):
            raise ValueError('Use draft substitutes current use case/application/proof scope or drops existing obligations')
        source_rule = original_rule(basis.decision_rule_ref); decision_rule = source_rule.decision
        if (decision_rule is None or decision_rule.case_ref != case.ref or decision_rule.procedure_ref != procedure.ref
                or decision_rule.outcome != outcome or not _known(decision_rule.permitted, 'independent_use_outcome_permission')):
            _needs('original_independent_use_outcome_rule')
        authority = read(basis.authority_ref, GovDecisionAuthorityView)
        if (authority.organization_id != org or authority.actor_id != basis.signer_actor_id or authority.function_ref != basis.signer_function_ref
                or authority.case_ref != case.ref or authority.submission_ref != submission.ref or authority.decision_basis_ref != basis.ref
                or outcome not in authority.outcomes or not _known(authority.permitted, 'independent_use_signing_authority')):
            _needs('independent_original_A07_use_signing_authority')
        authorize(basis.signer_authorization_ref, basis.signer_actor_id, basis.signer_function_ref, org, 'GOV-A07', now)
        checks = [read(ref, GovDecisionCheckView) for ref in procedure.required_check_refs]
        check_map = {r.ref.key(): r for r in checks}; keys(procedure.required_check_refs)
        if not checks:
            _needs('independent_necessary_use_checks')
        for check in checks:
            if original_rule(check.rule_ref).check_ref != check.ref:
                raise ValueError('Necessary use check has no independently bound current application rule')
        issues = [read(ref, GovDecisionIssueView) for ref in case.unresolved_issue_refs]
        if keys(decision_rule.issue_refs) != keys(case.unresolved_issue_refs):
            raise ValueError('Use outcome rule drops current unresolved original case issues')
        for issue in issues:
            if issue.case_ref != case.ref or issue.submission_ref != submission.ref or issue.status != 'open':
                raise ValueError('Use procedure substitutes current original unresolved issue')
        findings = {r.ref.key(): [] for r in checks}; supplied_results = set()
        for ref in action_input.professional_proof_refs:
            assessment = read(ref, GovDecisionAssessmentView); author(assessment, {'GOV-A04', 'GOV-A06', 'GOV-A08', 'GOV-A10', 'GOV-A11'}, True); bound(assessment)
            if assessment.status != 'valid':
                _needs('original_valid_current_use_proof')
            keys(assessment.check_result_refs)
            for result_ref in assessment.check_result_refs:
                if result_ref.key() not in keys(action_input.test_result_refs) or result_ref.key() in supplied_results:
                    raise ValueError('Use proof borrows an undeclared or repeated original test result')
                supplied_results.add(result_ref.key()); result = read(result_ref, GovDecisionFindingView); grant = author(result, own=True)
                if (result.assessment_ref != assessment.ref or result.submission_ref != submission.ref
                        or result.content_sha256 != application.content_sha256 or result.check_ref.key() not in check_map
                        or result.author_action_id not in {'GOV-A04', 'GOV-A06', 'GOV-A08', 'GOV-A10', 'GOV-A11'}
                        or not scope_covers(result.scope, check_map[result.check_ref.key()].scope)
                        or not keys(result.verification_evidence_refs) <= keys(grant.readable_refs)
                        or result.available_at.offset > assessment.authored_at.offset):
                    raise ValueError('Use result substitutes current use version or independent executed scope/read authority')
                evidence(result.verification_evidence_refs); reading.resolve(result.method_ref)
                if result.status == 'failed':
                    technical('government-use-original-proof-execution-failed')
                if result.status == 'unsupported':
                    _unsupported('government-use-original-proof-method-unmodeled')
                finding = result.finding if result.status == 'ok' else 'unknown'
                if finding != 'unknown' and not result.verification_evidence_refs:
                    _needs('original_successful_use_proof_evidence')
                if finding == 'not_applicable':
                    if result.applicability_basis_ref is None:
                        _needs('original_use_check_inapplicability')
                    applicability = read(result.applicability_basis_ref, GovDecisionApplicabilityView); author(applicability, own=True)
                    if (applicability.submission_ref != submission.ref or applicability.content_sha256 != application.content_sha256
                            or applicability.check_ref != result.check_ref or not isinstance(applicability.applicable, Known) or applicability.applicable.value):
                        raise ValueError('Use check has no current independent inapplicability basis')
                findings[result.check_ref.key()].append(finding)
        if supplied_results != keys(action_input.test_result_refs):
            _needs('all_original_current_use_test_results_bound_to_professional_proofs')
        states = {key: ('nonconforms' if 'nonconforms' in values else ('unknown' if not values or 'unknown' in values
            or {'conforms', 'not_applicable'} <= set(values) else ('not_applicable' if set(values) == {'not_applicable'} else 'conforms'))) for key, values in findings.items()}
        actual_scopes, events = set(), set()
        for ref in action_input.completed_scope_refs:
            fact = read(ref, GovUseWorkFactView, True); author(fact)
            if fact.work_kind != 'completed_scope' or fact.case_ref != case.ref or fact.core_event_id in events:
                raise ValueError('Use completion substitutes actual work type/case or repeats the original core event')
            events.add(fact.core_event_id); clock(fact.window.end)
            if fact.status == 'failed':
                technical('government-use-original-completion-fact-failed')
            if fact.author_action_id.split('-')[0] not in {'CONTRACTOR', 'SUPPLIER', 'ENGINEER', 'GOV'}:
                raise ValueError('Use actual completion fact substitutes the original executing or verifying function')
            evidence([fact.effort.basis_ref])
            if (fact.status == 'committed' and _known(fact.actual_verified, 'original_actual_completed_scope')
                    and fact.window.end.offset <= fact.authored_at.offset):
                if any(reading.resolve(r).basis_kind != 'observed' for r in fact.evidence_refs):
                    _needs('actual_observed_original_use_completion_evidence')
                for ref in fact.completed_scope_refs:
                    if ref.key() in actual_scopes or ref.key() not in keys(scope.coverage_refs):
                        raise ValueError('Use completion repeats or expands actual completed scope')
                    reading.resolve(ref); actual_scopes.add(ref.key())
        necessary_ready = all(states[c.ref.key()] in {'conforms', 'not_applicable'} for c in checks if c.required_before_approval)
        complete_scopes = keys(procedure.required_completed_scope_refs) <= actual_scopes
        if outcome in {'approve', 'approve_with_conditions'}:
            if (not complete_scopes or not necessary_ready or any(c.required_before_use for c in conditions)
                    or any(issue.blocks_approval for issue in issues)):
                _needs('actual_complete_scope_and_all_necessary_use_requirements')
        elif outcome == 'refuse':
            if not decision_rule.required_nonconforming_check_refs or any(states.get(ref.key()) != 'nonconforms' for ref in decision_rule.required_nonconforming_check_refs):
                _needs('original_confirmed_nonconforming_use_refusal_basis')
        if outcome in {'approve', 'approve_with_conditions'} or not decision_rule.permits_incomplete_review:
            if procedure.completion_ref is None:
                _needs('original_complete_use_procedure')
            completion = read(procedure.completion_ref, GovProcedureCompletionView); author(completion, own=True); bound(completion)
            if completion.procedure_ref != procedure.ref or completion.status != 'complete':
                _needs('original_complete_use_procedure')
            verified = []
            for ref in completion.verification_refs:
                row = read(ref, GovProcedureVerificationView); author(row, own=True); bound(row)
                requirement = read(row.requirement_ref, GovProcedureRequirementView)
                if requirement.procedure_ref != procedure.ref or not _known(row.satisfied, 'original_use_procedure_satisfaction'):
                    _needs('original_satisfied_use_procedure_requirement')
                if row.available_at.offset > completion.authored_at.offset:
                    raise ValueError('Use procedure completion predates its actual necessary verification')
                verified.append(row.requirement_ref)
            keys(completion.verification_refs)
            if keys(verified) != keys(procedure.required_procedure_refs):
                _needs('complete_original_use_procedure_requirement_coverage')
        effect = read(draft.effect_rule_ref, GovDecisionEffectView)
        if (not effect.modeled or effect.decision_rule_ref != decision_rule.ref or effect.outcome != outcome
                or decision_rule.effect_rule_ref != draft.effect_rule_ref or decision_rule.expiry_rule_ref != draft.expiry_rule_ref
                or keys(decision_rule.next_procedure_refs) != keys(draft.next_procedure_refs)
                or set(effect.notification_recipient_ids) != set(draft.notification_recipient_ids)
                or application.applicant_id not in draft.notification_recipient_ids or not draft.reason.strip()):
            raise ValueError('Use draft changes original outcome/effect/expiry/procedure or actual recipients')
        if outcome in {'refuse', 'defer_by_procedure'} and (draft.expiry_rule_ref is not None or effect.mode != 'no_permission'):
            raise ValueError('Use refusal/deferment cannot establish permission or carry an approval expiry')
        if outcome in {'approve', 'approve_with_conditions'} and effect.mode == 'no_permission':
            raise ValueError('Use approval requires its original explicit permission-effect rule')
        if len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids):
            raise ValueError('Use draft repeats an actual notification recipient')
        if draft.expiry_rule_ref is not None:
            expiry = read(draft.expiry_rule_ref, GovDecisionBindingView)
            if expiry.decision_basis_ref != basis.ref:
                raise ValueError('Use expiry belongs to another original decision basis')
        for ref in draft.next_procedure_refs:
            next_procedure = read(ref, GovUseProcedureView)
            if next_procedure.application_ref != application.ref or next_procedure.case_ref != case.ref:
                raise ValueError('Use next procedure substitutes original case/application')
        approved_conditions = []
        for ref in basis.condition_basis_refs:
            row = read(ref, GovDecisionConditionBasisView); author(row, {'GOV-A11'}, True)
            if row.decision_basis_ref != basis.ref or not _known(row.permitted, 'original_use_condition_permission'):
                _needs('independent_original_use_condition_basis')
            if any(check_map[r.key()].required_before_approval for r in row.deferred_check_refs if r.key() in check_map):
                raise ValueError('Use condition cannot defer a necessary pre-use check')
            if not keys(row.deferred_check_refs) <= set(check_map):
                raise ValueError('Use condition invents an undeclared deferred check')
            if original_rule(row.condition.condition_rule_ref).condition_basis_ref != row.ref:
                raise ValueError('Use condition rule substitutes its independently authorized condition basis')
            approved_conditions.append(row.condition)
        keys(basis.condition_basis_refs)
        if sorted(content_digest(c) for c in approved_conditions) != sorted(content_digest(c) for c in draft.conditions):
            raise ValueError('Use conditions differ from independently authorized original bases')
        if (outcome == 'approve_with_conditions' and not draft.conditions) or (outcome != 'approve_with_conditions' and draft.conditions):
            raise ValueError('Only conditional use approval may carry new concrete conditions')
        for condition in draft.conditions:
            condition_rule = original_rule(condition.condition_rule_ref)
            if condition_rule.condition_basis_ref is None:
                raise ValueError('Use condition substitutes an unrelated original rule purpose')
            if not scope_covers(scope, condition.covered_scope):
                raise ValueError('Use condition widens original covered scope')
            method = read(condition.verification_method_ref, GovDecisionMethodView)
            if method.function_ref != condition.verifier_binding_ref or not _known(method.supported, 'use_condition_verifier_method'):
                _needs('original_supported_use_condition_verifier')
            authorize(method.authority_ref, method.actor_id, method.function_ref, method.organization_id, method.action_id, now, condition.covered_scope)
            for ref in [*condition.affected_action_refs, *condition.required_evidence_refs, *([condition.due_rule_ref] if condition.due_rule_ref else [])]:
                binding = read(ref, GovDecisionBindingView)
                if binding.decision_basis_ref != basis.ref or not scope_covers(condition.covered_scope, binding.scope):
                    raise ValueError('Use condition substitutes original affected actions/evidence/deadline')
        released = keys(basis.release_assignment_refs); retained = keys(basis.retained_assignment_refs)
        if released & retained or released | retained != keys(case.review_assignment_refs):
            raise ValueError('Use closure drops, repeats or recreates original review assignment identities')
        if outcome == 'defer_by_procedure' and released:
            raise ValueError('Deferred use case cannot silently release active review assignments')
        continuing_tasks = {ref.key() for condition in conditions for ref in condition.supervision_task_refs}
        for ref in case.review_assignment_refs:
            assignment = read(ref, GovReviewAssignmentView)
            if assignment.organization_id != org or assignment.case_ref != case.ref or assignment.status != 'effective':
                raise ValueError('Use closure substitutes another original active review assignment')
            if ref.key() in released:
                task = read(assignment.task_ref, GovSchedulingTaskView)
                if (task.ref.key() in continuing_tasks or task.organization_id != org or task.case_ref != case.ref
                        or task.as_of != now or task.status not in {'complete', 'cancelled'}):
                    _needs('only_original_unused_review_assignments_releasable')
                if task.status == 'complete' and decimal_fraction(_known(task.remaining_effort, 'completed_review_remaining_effort').value) != 0:
                    raise ValueError('Completed use review cannot release unfinished original effort')
        return complete(choice, draft=draft.model_dump(mode='python'))
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
