"""GOV-A04 checks only original disclosed evidence and current scoped rules."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView, GovReviewAssignmentView, GovSchedulingDependencyView
from src.actions.contracts.government_review_objects import (
    GovReviewSubmissionView, GovReviewTaskView, GovReviewRuleView, GovReviewApplicabilityView,
    GovReviewFactView, GovProfessionalFinding, GovProfessionalOpinionView, GovReviewResultView,
    GovReviewQuestionView, GovReviewConditionView, GovReviewConditionAuthorityView,
    GovReviewMethodView, GovReviewConditionBindingView, GovReviewReuseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.government_rules import GOV_RULE_METHOD, GovRuleInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def review_case(context, action_input, reading):
    now, scope, organization = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-review-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-review-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
            sources[ref.key()] = row

    def read(ref, schema, historic=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-review-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(scope, row.scope):
            raise ValueError('Government review record leaves original authorized scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_government_review_record', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('effective_original_government_review_record', [ref])
        sources[ref.key()] = row
        return row

    def authorize(ref, actor, function, org, action, at):
        row = read(ref, Authorization); assignment = read(function, RoleAssignment)
        prefixes = {'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-', 'Architect': 'ARCHITECT-',
            'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}
        evidence(row.basis_refs + assignment.basis_refs); clock(at); clock(row.validity.start)
        if (row.actor_id != actor or row.function_ref != function or row.organization_id != org
                or not action.startswith(prefixes[assignment.role]) or action not in row.action_ids
                or not any(scope_covers(s, scope) for s in row.scopes)):
            raise ValueError('Government review source changes original independent author authority')
        if not row.validity.contains(at):
            _needs('original_review_source_authorization_at_execution', [ref])
        return row, assignment

    def author(row, government=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Review record is not available/applicable at its original creation')
        grant, function = authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at)
        if government and (row.author_organization_id != organization or row.author_action_id != 'GOV-A04'):
            raise ValueError('Original government verification substitutes responsible agency/action')
        return grant, function

    def bound(row, rule=None):
        if (row.submission_ref != submission.ref or row.content_sha256 != submission.content_sha256
                or (hasattr(row, 'case_ref') and row.case_ref != case.ref)
                or (rule is not None and hasattr(row, 'rule_ref') and row.rule_ref != rule.ref)):
            raise ValueError('Review source substitutes final submission version/content/case or rule')

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Scoped evidence review only; unresolved checks remain open. No signed decision, permission, condition satisfaction or work suspension effect.', **fields}}

    def technical(ref):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': 'original_government_review_execution_failed'}, 'retryability': 'unknown'})

    def questions(refs):
        output = []; keys(refs)
        for ref in refs:
            row = read(ref, GovReviewQuestionView); bound(row)
            question = row.question
            if row.task_ref != task.ref or question.scope != row.scope or ref.key() not in keys(question.target_refs):
                raise ValueError('Review question substitutes original task, scope or evidence target')
            if question.requirement_ref not in action_input.rule_refs:
                raise ValueError('Review question invents a legal rule outside this review')
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref or response.scope != question.scope:
                raise ValueError('Review response requirement concerns another original rule/scope')
            for target in question.target_refs:
                original = read(target, GovReviewQuestionView); bound(original)
                if original.task_ref != task.ref or original.question != question:
                    raise ValueError('Review question mixes unrelated original targets')
            if not question.recipient_refs:
                _needs('original_review_verification_recipients')
            for ref in question.recipient_refs:
                recipient = read(ref, GovRecipientView)
                if recipient.scope != question.scope:
                    raise ValueError('Verification recipient is not bound to original question scope')
            evidence(question.evidence_refs)
            output.append(question.model_dump(mode='python'))
        return output

    try:
        case = read(action_input.case_ref, GovSchedulingCaseView)
        submission = read(action_input.submission_ref, GovReviewSubmissionView)
        task = read(action_input.task_ref, GovReviewTaskView)
        if (case.organization_id != organization or task.organization_id != organization or task.case_ref != case.ref
                or case.current_submission_ref != submission.ref or task.submission_ref != submission.ref
                or task.content_sha256 != submission.content_sha256 or task.ref not in case.task_refs
                or submission.recipient_organization_id != organization or submission.matter_ref != case.matter_ref
                or submission.jurisdiction_ref != case.jurisdiction_ref or submission.procedure_ref != case.procedure_ref):
            raise ValueError('Review task/case substitutes final received submission, agency or procedure')
        authorize(task.authority_ref, context.actor_id, task.function_ref, organization, 'GOV-A04', now)
        if task.function_ref != context.function_ref:
            raise ValueError('Review task uses another acting government function')
        if submission.status != 'active' or submission.receipt_status != 'received' or case.status in {'closed', 'withdrawn'} or task.status != 'authorized':
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'government_review_case_task_not_ready', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [case.ref, task.ref, submission.ref], 'earliest_time': None,
                'condition_code': 'government.review.original_case_task_ready'}}
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView); matter = read(case.matter_ref, GovMatterView)
        region = _known(case.region_id, 'original_review_region')
        if (jurisdiction.organization_id != organization or matter.matter_code not in _known(jurisdiction.covered_matter_codes, 'original_review_matters')
                or region not in _known(jurisdiction.covered_project_region_ids, 'original_review_regions')
                or region != _known(matter.project_region_id, 'original_matter_review_region')
                or not any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)):
            raise ValueError('Government has no original lawful jurisdiction for this review')
        assignment = read(task.assignment_ref, GovReviewAssignmentView)
        if (assignment.task_ref != task.ref or assignment.case_ref != case.ref or assignment.organization_id != organization
                or assignment.status != 'effective' or not assignment.window.contains(now)):
            _needs('effective_original_review_assignment_at_work_time', [assignment.ref])
        for ref in task.dependency_refs:
            dep = read(ref, GovSchedulingDependencyView)
            if dep.task_ref != task.ref or dep.as_of != now or not isinstance(dep.satisfied, Known) or not dep.satisfied.value:
                _needs('fulfilled_original_review_dependencies', [ref])
        for given, expected in ((action_input.rule_refs, task.rule_refs), (action_input.professional_refs, task.professional_refs),
                (action_input.verified_evidence_refs, task.verified_evidence_refs), (action_input.method_result_refs, task.method_result_refs)):
            if keys(given) != keys(expected):
                _needs('exact_original_review_rules_professionals_verified_evidence_and_results')
        evidence(action_input.verified_evidence_refs)
        rules = [read(ref, GovReviewRuleView) for ref in action_input.rule_refs]
        for rule in rules:
            bound(rule)
            if rule.organization_id != organization or rule.jurisdiction_ref != jurisdiction.ref:
                raise ValueError('Review rule substitutes original legal agency/jurisdiction')
        opinions = []; verifications = {}
        for ref in action_input.professional_refs:
            opinion = read(ref, GovProfessionalOpinionView, historic=True)
            _, function = author(opinion)
            assessment_actions = {'Architect': {'ARCHITECT-A06', 'ARCHITECT-A13'},
                'Engineer': {'ENGINEER-A06', 'ENGINEER-A13'},
                'QS': {'QS-A04', 'QS-A06', 'QS-A07', 'QS-A08', 'QS-A09', 'QS-A13'}}
            if opinion.author_action_id not in assessment_actions.get(function.role, set()):
                raise ValueError('Professional evidence substitutes original responsible profession')
            if opinion.status != 'available':
                _needs('original_available_professional_review', [ref])
            opinions.append((opinion, function.role))
            keys(opinion.verification_refs)
            for ref in opinion.verification_refs:
                original = read(ref, GovProfessionalFinding, historic=True)
                original_grant, original_function = author(original)
                if (original.assessment_ref != opinion.ref or original_function.role != function.role
                        or original.author_organization_id != opinion.author_organization_id
                        or original.submission_ref != opinion.submission_ref or original.content_sha256 != opinion.content_sha256
                        or original.available_at.offset > opinion.authored_at.offset):
                    raise ValueError('Professional opinion substitutes original execution, discipline or target content')
                # Keep original historical execution/provenance. Its failure or
                # support status matters only when a current rule actually uses
                # it through the same submission or an explicit reuse basis.
                verifications[ref.key()] = original
        reuse = [read(ref, GovReviewReuseView) for ref in task.reuse_basis_refs]
        keys(task.reuse_basis_refs)
        for row in reuse:
            bound(row); author(row, government=True)
            if row.task_ref != task.ref or row.rule_ref not in action_input.rule_refs or row.assessment_ref not in action_input.professional_refs:
                raise ValueError('Review reuse basis concerns an unrelated original rule or opinion')
        if task.choice == 'request_verification':
            if task.verification_method_ref is None:
                _needs('original_supported_verification_method')
            method = read(task.verification_method_ref, GovReviewMethodView)
            if method.purpose != 'verification' or not keys(method.rule_refs) <= keys(action_input.rule_refs):
                raise ValueError('Verification method changes original review rule coverage')
            if not _known(method.supported, 'original_verification_method_support'):
                _unsupported('government-review-requested-verification-method')
            authorize(method.executor_authority_ref, method.executor_actor_id, method.executor_function_ref,
                method.organization_id, method.execution_action_id, now)
            output = questions(task.question_refs)
            if not output:
                _needs('specific_original_review_verification_questions')
            return completed('request_verification', questions=output, method_ref=method.ref)

        checks, pending_questions = [], list(task.question_refs)
        expected_results = []
        for rule in rules:
            if rule.criterion == 'unmodeled' or rule.method_ref != GOV_RULE_METHOD:
                _unsupported('government-review-unmodeled-rule:' + rule.ref.id)
            applicability = read(rule.applicability_ref, GovReviewApplicabilityView); bound(applicability, rule); author(applicability, True)
            data_sources = [rule.ref, applicability.ref, submission.ref, task.ref]
            facts, measured, code = [], None, None
            if rule.fact_ref is not None:
                fact = read(rule.fact_ref, GovReviewFactView); bound(fact, rule); author(fact)
                if not keys(fact.verification_evidence_refs) <= keys(action_input.verified_evidence_refs):
                    _needs('original_lawfully_verified_rule_evidence', fact.verification_evidence_refs)
                evidence(fact.verification_evidence_refs)
                if any(sources[ref.key()].basis_kind == 'assumed' for ref in fact.verification_evidence_refs):
                    _needs('verified_review_evidence_instead_of_assumption', fact.verification_evidence_refs)
                measured, code = fact.measured_value, fact.code_value
                if measured is not None and measured.state == 'known':
                    if measured.value.basis_ref not in fact.verification_evidence_refs:
                        raise ValueError('Measured rule value lacks its original verified evidence')
                facts = fact.verification_evidence_refs; data_sources += [fact.ref, *facts]
            findings, covered = [], set()
            for opinion, profession in opinions:
                if profession not in rule.required_professions or rule.discipline_code not in opinion.discipline_codes:
                    continue
                same_version = opinion.submission_ref == submission.ref and opinion.content_sha256 == submission.content_sha256
                source_rule = rule.ref
                if not same_version:
                    matches = [row for row in reuse if row.assessment_ref == opinion.ref and row.rule_ref == rule.ref
                        and row.source_submission_ref == opinion.submission_ref and row.source_content_sha256 == opinion.content_sha256
                        and row.scope == rule.scope and isinstance(row.reusable, Known) and row.reusable.value]
                    if len(matches) != 1:
                        continue
                    data_sources.append(matches[0].ref)
                    source_rule = matches[0].source_rule_ref
                if not scope_covers(opinion.scope, rule.scope):
                    continue
                matched = [verifications[ref.key()] for ref in opinion.verification_refs
                    if verifications[ref.key()].rule_ref == source_rule and scope_covers(verifications[ref.key()].scope, rule.scope)]
                for original in matched:
                    if original.status == 'failed':
                        technical(original.ref)
                    if original.status == 'unsupported':
                        _unsupported('government-review-original-professional-method')
                    # Consume an original saved execution, never rerun its method
                    # or turn an unknown finding into a successful verification.
                    reading.resolve(original.method_ref)
                    findings.append(original.finding if original.status == 'ok' else 'unknown')
                    data_sources.append(original.ref)
                if matched:
                    covered.add(profession); data_sources.append(opinion.ref)
            data_sources = list({ref.key(): ref for ref in data_sources}.values())
            data = GovRuleInput(criterion=rule.criterion, applicable=applicability.applicable, measured_value=measured,
                code_value=code, unit=rule.unit, minimum=rule.minimum, maximum=rule.maximum, expected_code=rule.expected_code,
                professional_findings=findings, professional_complete=set(rule.required_professions) <= covered, source_refs=data_sources)
            saved = None
            finding = 'unknown'; basis_evidence = list(dict.fromkeys([*rule.evidence_refs, *applicability.evidence_refs, *facts]))
            if rule.result_ref is not None:
                expected_results.append(rule.result_ref)
                if rule.result_ref not in action_input.method_result_refs:
                    _needs('declared_original_review_rule_result', [rule.result_ref])
                saved = read(rule.result_ref, GovReviewResultView); bound(saved, rule)
                grant, _ = author(saved, True)
                original_method = read(rule.method_descriptor_ref or rule.method_ref, GovReviewMethodView)
                if rule.method_descriptor_ref is not None and original_method.calculation_method_ref!=rule.method_ref:
                    raise ValueError('Original rule descriptor substitutes its declared calculation method')
                if (original_method.purpose != 'rule_check' or rule.ref not in original_method.rule_refs
                        or original_method.organization_id != organization
                        or original_method.executor_actor_id != saved.author_actor_id
                        or original_method.executor_function_ref != saved.author_function_ref
                        or original_method.executor_authority_ref != saved.author_authority_ref
                        or original_method.execution_action_id != 'GOV-A04'):
                    raise ValueError('Original rule method descriptor changes agency or supported rule coverage')
                if not _known(original_method.supported, 'original_rule_check_method_support'):
                    _unsupported('government-review-original-rule-method')
                if saved.task_ref != task.ref or saved.method_ref != GOV_RULE_METHOD:
                    raise ValueError('Original rule execution substitutes the current task or method')
                if saved.status == 'failed':
                    technical(saved.ref)
                if saved.status == 'unsupported':
                    _unsupported('government-review-saved-rule-method')
                if saved.status == 'ok':
                    if saved.input_sha256 != content_digest(data) or not keys(data_sources) <= keys(grant.readable_refs):
                        raise ValueError('Saved rule execution substitutes original inputs or source read authority')
                    for ref in data_sources:
                        row = sources[ref.key()]
                        if hasattr(row, 'available_at') and row.available_at.offset > saved.authored_at.offset:
                            _needs('review_execution_after_original_input_versions', [saved.ref])
                    result = reading.calculate(GOV_RULE_METHOD, data)
                    if result.kind != 'ok':
                        if result.kind == 'invalid_input':
                            raise ValueError('Original legal rule arithmetic violates declared domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information':
                            raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    if saved.report != result.value:
                        raise ValueError('Original saved rule finding differs from disclosed evidence recomputation')
                    finding = result.value.finding
            if finding == 'unknown':
                pending_questions.extend(rule.question_refs)
            checks.append({'rule_ref': rule.ref, 'covered_scope': rule.scope, 'evidence_refs': basis_evidence,
                'method_result_ref': saved.ref if saved is not None and saved.status == 'ok' else None, 'finding': finding})
        if keys(expected_results) != keys(action_input.method_result_refs):
            raise ValueError('Review contains a result outside the current original rule set')
        assessment = {'target_ref': submission.ref, 'task_ref': task.ref, 'checks': checks,
            'proposed_questions': questions(list({ref.key(): ref for ref in pending_questions}.values())), 'explanation': task.explanation}
        if task.choice == 'assess':
            return completed('assess', assessment=assessment)
        conditions = []; keys(task.condition_refs)
        for ref in task.condition_refs:
            condition = read(ref, GovReviewConditionView); bound(condition)
            if condition.task_ref != task.ref or condition.condition_rule_ref not in action_input.rule_refs:
                raise ValueError('Proposed condition invents a rule or changes original task')
            authority = read(condition.proposal_authority_ref, GovReviewConditionAuthorityView)
            if (authority.organization_id != organization or authority.actor_id != context.actor_id
                    or authority.function_ref != context.function_ref or authority.condition_ref != condition.ref):
                raise ValueError('Condition proposal lacks independent original authority binding')
            for field in ('responsible_party_ids', 'verifier_binding_ref', 'affected_action_refs', 'required_evidence_refs',
                          'verification_method_ref', 'due_rule_ref'):
                if getattr(authority, field) != getattr(condition, field):
                    raise ValueError('Condition proposal changes independently authorized responsibilities or requirements')
            if not _known(authority.permitted, 'original_condition_proposal_permission'):
                _needs('authorized_original_condition_proposal', [authority.ref])
            verifier = read(condition.verifier_binding_ref, RoleAssignment)
            evidence(verifier.basis_refs)
            method = read(condition.verification_method_ref, GovReviewMethodView)
            if (method.executor_function_ref != verifier.function_ref or condition.condition_rule_ref not in method.rule_refs
                    or method.purpose != 'verification'):
                raise ValueError('Condition verification method substitutes bound verifier or legal rule')
            if not _known(method.supported, 'original_condition_verification_method_support'):
                _unsupported('government-review-condition-verification-method')
            authorize(method.executor_authority_ref, method.executor_actor_id, method.executor_function_ref,
                method.organization_id, method.execution_action_id, now)
            for ref in [*condition.affected_action_refs, *condition.required_evidence_refs, *([condition.due_rule_ref] if condition.due_rule_ref else [])]:
                binding = read(ref, GovReviewConditionBindingView)
                if binding.condition_ref != condition.ref or binding.rule_ref != condition.condition_rule_ref or binding.scope != condition.scope:
                    raise ValueError('Condition action/evidence/clock requirement changes original legal coverage')
            conditions.append({'condition_rule_ref': condition.condition_rule_ref, 'covered_scope': condition.scope,
                'responsible_party_ids': condition.responsible_party_ids, 'verifier_binding_ref': condition.verifier_binding_ref,
                'affected_action_refs': condition.affected_action_refs, 'required_evidence_refs': condition.required_evidence_refs,
                'verification_method_ref': condition.verification_method_ref, 'due_rule_ref': condition.due_rule_ref})
        if not conditions:
            _needs('specific_original_authorized_condition_proposals')
        return completed('propose_conditions', assessment=assessment, conditions=conditions)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
