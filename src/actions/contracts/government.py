"""Government cross-record rules; source submissions and decisions remain distinct."""


def validate_decision(action_id, action_input, payload):
    if payload.scope != action_input.scope:
        raise ValueError("Government output scope differs from input")
    if action_id == 'GOV-A12':
        from src.actions.contracts.government_feedback_objects import GovFeedbackRequest, GovFeedbackPlan, GovFeedbackPolicyProposal
        from src.actions.contracts.owner_study_objects import unique_refs

        def keys(refs):
            unique_refs(refs)
            return {r.key() for r in refs}

        def request_check(request, purpose):
            if (request.scope != action_input.scope or request.purpose != purpose
                    or request.authority_basis_refs != [action_input.working_authority_ref]
                    or not request.output_requirement_refs
                    or not keys([action_input.observation_profile_ref, *action_input.feedback_refs,
                        *action_input.visible_statistic_refs]) <= keys(request.input_refs)):
                raise ValueError('Government feedback task must retain original inputs, scoped purpose and working authority')
            keys(request.output_requirement_refs);keys(request.dependency_refs)

        if payload.choice == 'record_feedback':
            if keys(payload.feedback_refs) != keys(action_input.feedback_refs):
                raise ValueError('Government feedback record changes original received feedback')
        elif payload.choice == 'investigate':
            request = GovFeedbackRequest.model_validate(payload.request.model_dump(mode='python'))
            request_check(request, 'investigation')
            if not payload.questions or request.questions != payload.questions or any(q.scope != action_input.scope for q in payload.questions):
                raise ValueError('Investigation must preserve original specific scoped questions')
        elif payload.choice == 'change_work_arrangement':
            plan = GovFeedbackPlan.model_validate(payload.plan.model_dump(mode='python'))
            if payload.basis_ref != action_input.working_authority_ref or not plan.items:
                raise ValueError('Government work arrangement needs original independent working authority and actual tasks')
            keys([i.task_ref for i in plan.items])
            for item in plan.items:
                keys(item.dependency_refs)
                if not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
                    raise ValueError('Government work arrangement repeats or omits resources')
        else:
            proposal = GovFeedbackPolicyProposal.model_validate(payload.proposal.model_dump(mode='python'))
            if (proposal.target_scope != action_input.scope or proposal.observation_profile_ref != action_input.observation_profile_ref
                    or keys(proposal.issue_refs) != keys(action_input.feedback_refs)
                    or keys(proposal.statistic_refs) != keys(action_input.visible_statistic_refs)
                    or not proposal.proposed_instrument_refs or not proposal.evidence_refs):
                raise ValueError('Policy proposal must retain original visible issues, statistics, scope and evidence')
            keys(proposal.proposed_instrument_refs);keys(proposal.evidence_refs)
            request_check(proposal.evaluation_request, 'policy_evaluation')
    if action_id == 'GOV-A03':
        _validate_review_plan(action_input, payload)
    if action_id == 'GOV-A04':
        _validate_evidence_review(action_input, payload)
    if action_id == 'GOV-A05':
        _validate_consultation(action_input, payload)
    if action_id == 'GOV-A06':
        _validate_supplement(action_input, payload)
    if action_id == 'GOV-A07':
        _validate_formal_decision(action_input, payload)
    if action_id == 'GOV-A08':
        _validate_permit_verification(action_input, payload)
    if action_id == 'GOV-A09':
        _validate_transition(action_input, payload)
    if action_id == 'GOV-A10':
        _validate_inspection(action_input, payload)
    if action_id == 'GOV-A11':
        _validate_use(action_input, payload)
    if action_id == 'GOV-A01':
        if payload.choice == 'advise':
            advice = payload.advice
            if (advice.matter_ref != action_input.matter_ref
                    or advice.jurisdiction_ref != action_input.jurisdiction_ref):
                raise ValueError('Preliminary advice changes original matter or jurisdiction')
            for refs in (advice.basis_refs, advice.information_requirement_refs, advice.update_trigger_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                    raise ValueError('Preliminary advice repeats an original physical reference')
            if advice.applicability != 'unknown' and not advice.basis_refs:
                raise ValueError('Known preliminary applicability requires original rule basis')
            questions = advice.known_gap_questions
        else:
            questions = payload.questions
            if payload.choice == 'clarify' and not questions:
                raise ValueError('Preliminary clarification requires original scoped questions')
        if any(question.scope != action_input.scope for question in questions):
            raise ValueError('Preliminary consultation question changes original scope')
    if action_id == "GOV-A02":
        if payload.choice == "acknowledge" and payload.submission_ref != action_input.submission_ref:
            raise ValueError("Acknowledgement must preserve the received submission")
        if payload.choice in {"accept_for_processing", "request_correction"}:
            if payload.check.submission_ref != action_input.submission_ref or payload.check.procedure_ref != action_input.procedure_ref:
                raise ValueError("Completeness must check the exact submission and procedure versions")
            check = payload.check
            if check.scope != action_input.scope:
                raise ValueError("Completeness scope differs from the submission scope")
            for refs in (check.checked_requirement_refs, check.missing_requirement_refs):
                if len({ref.key() for ref in refs}) != len(refs):
                    raise ValueError("Completeness requirement repeated")
            if not check.checked_requirement_refs or not set(ref.key() for ref in check.missing_requirement_refs) <= set(
                    ref.key() for ref in check.checked_requirement_refs):
                raise ValueError("Missing requirements must belong to the nonempty checked requirement set")
            if any(question.scope != action_input.scope for question in check.unresolved_questions):
                raise ValueError("Completeness question exceeds the submission scope")
            if payload.choice == "request_correction":
                if (not payload.questions or not (check.missing_requirement_refs or check.unresolved_questions)
                        or payload.questions != check.unresolved_questions):
                    raise ValueError("Correction requires the same concrete unresolved checklist questions")
        if payload.choice == "decline_processing" and (not payload.reason.strip() or not payload.basis_refs):
            raise ValueError("Intake decline requires a reason and applicable rule basis")
        if payload.choice == "accept_for_processing" and (payload.check.missing_requirement_refs or payload.check.unresolved_questions):
            raise ValueError("Incomplete submission cannot be accepted for processing")
    if action_id in {"GOV-A07", "GOV-A09"} and hasattr(payload, "draft"):
        if payload.draft.outcome != payload.choice:
            raise ValueError("Decision outcome must match its selected branch")
    if action_id == "GOV-A11" and payload.choice == "propose_use_decision":
        if payload.draft.outcome not in {"approve", "approve_with_conditions", "refuse", "defer_by_procedure"}:
            raise ValueError("Use decision has an invalid outcome")


def _validate_permit_verification(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'request_evidence':
        if not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
            raise ValueError('Permit evidence request requires original scoped questions')
    elif payload.choice == 'request_condition_change':
        if payload.condition_ref not in action_input.condition_refs or not payload.basis_refs or not payload.reason.strip():
            raise ValueError('Condition-change request requires the selected original condition and legal grounds')
        unique_refs(payload.basis_refs)
    else:
        unique_refs([row.condition_ref for row in payload.results])
        if not payload.results or {row.condition_ref.key() for row in payload.results} != {r.key() for r in action_input.condition_refs}:
            raise ValueError('Permit verification must retain every declared original applicable condition')
        for row in payload.results:
            if row.action_ref != action_input.intended_action_ref or not scope_covers(action_input.scope, row.covered_scope):
                raise ValueError('Condition result must preserve intended action and local permit scope')
            if row.verification_result_ref is None and row.result != 'undetermined':
                raise ValueError('Known condition fulfillment requires original successful verification')
            if not {r.key() for r in row.evidence_refs} <= {r.key() for r in action_input.evidence_refs}:
                raise ValueError('Condition result invents undeclared fulfillment evidence')
            if any(not scope_covers(row.covered_scope, q.scope) for q in row.remaining_questions):
                raise ValueError('Condition question leaves the original condition coverage')


def _validate_use(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'request_evidence':
        if not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
            raise ValueError('Use evidence request requires concrete questions within original scope')
    elif payload.choice in {'plan_verification', 'continue_supervision'}:
        if not payload.plan.items:
            raise ValueError('Use verification plan requires original authorized tasks')
        unique_refs([item.task_ref for item in payload.plan.items])
        for item in payload.plan.items:
            if not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
                raise ValueError('Use plan omits or repeats original physical resource identities')
            unique_refs(item.dependency_refs)
        if payload.choice == 'continue_supervision':
            unique_refs(payload.condition_refs)
            if not payload.condition_refs or {r.key() for r in payload.condition_refs} != {r.key() for r in action_input.remaining_condition_refs}:
                raise ValueError('Continuing use supervision must retain all original selected conditions')
    else:
        draft = payload.draft
        if (draft.case_ref != action_input.case_ref or draft.covered_scope != action_input.scope
                or draft.prior_decision_ref is not None or not draft.reason.strip()
                or {r.key() for r in draft.assessment_refs} != {r.key() for r in action_input.professional_proof_refs}
                or not draft.notification_recipient_ids or len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids)):
            raise ValueError('Use draft substitutes current case/scope/proofs or lacks distinct actual recipients')
        unique_refs(draft.assessment_refs); unique_refs(draft.next_procedure_refs)
        if (draft.outcome == 'approve_with_conditions' and not draft.conditions) or (draft.outcome != 'approve_with_conditions' and draft.conditions):
            raise ValueError('Only conditional use approval carries independently authorized new conditions')
        if draft.outcome in {'refuse', 'defer_by_procedure'} and draft.expiry_rule_ref is not None:
            raise ValueError('Use refusal/deferment cannot carry a new approval expiry')


def _validate_inspection(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'plan':
        if len(payload.plan.items) != 1 or payload.plan.items[0].task_ref != action_input.task_ref:
            raise ValueError('Inspection plan must preserve the original authorized task')
        item = payload.plan.items[0]
        if not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
            raise ValueError('Inspection plan omits or repeats actual resource identities')
        unique_refs(item.dependency_refs)
    elif payload.choice == 'require_response':
        if not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
            raise ValueError('Inspection response request requires original local questions')
    elif payload.choice == 'report':
        row = payload.assessment
        if row.task_ref != action_input.task_ref or not row.checks:
            raise ValueError('Inspection assessment changes original task or omits checks')
        unique_refs(payload.observation_refs)
        if {r.key() for r in payload.observation_refs} != {r.key() for r in action_input.observation_refs}:
            raise ValueError('Inspection report invents or drops original received observations')
        unique_refs([check.rule_ref for check in row.checks])
        for check in row.checks:
            if not scope_covers(action_input.scope, check.covered_scope):
                raise ValueError('Inspection check leaves original task scope')
            if check.finding != 'unknown' and check.method_result_ref is None:
                raise ValueError('Known inspection finding requires its original successful execution')
            unique_refs(check.evidence_refs)
        if any(not scope_covers(action_input.scope, q.scope) for q in row.proposed_questions):
            raise ValueError('Inspection proposed question leaves original task scope')
    elif payload.choice == 'order_measure':
        measure = payload.measure
        if (not scope_covers(action_input.scope, measure.affected_scope) or not measure.evidence_refs
                or not measure.affected_action_refs or not measure.recipient_ids
                or len(set(measure.recipient_ids)) != len(measure.recipient_ids)):
            raise ValueError('Regulatory measure lacks original scope, actions, evidence or distinct recipients')
        unique_refs(measure.affected_action_refs); unique_refs(measure.evidence_refs)
    else:
        unique_refs([r.issue_ref for r in payload.resolutions])
        if not payload.resolutions or {r.issue_ref.key() for r in payload.resolutions} != {r.key() for r in action_input.prior_issue_refs}:
            raise ValueError('Inspection recheck must preserve the complete original selected issue set')
        for row in payload.resolutions:
            for refs in (row.response_refs, row.retained_requirement_refs, row.affected_assessment_refs, row.reusable_assessment_refs):
                unique_refs(refs)
            if {r.key() for r in row.affected_assessment_refs} & {r.key() for r in row.reusable_assessment_refs}:
                raise ValueError('Inspection recheck cannot invalidate and reuse the same original assessment')
            if row.resolution != 'unresolved' and row.verification_result_ref is None:
                raise ValueError('Inspection issue closure requires original successful scoped verification')
            if row.resolution == 'resolved' and row.retained_requirement_refs:
                raise ValueError('Inspection resolved issue cannot retain unmet original requirements')
            if row.resolution == 'partially_resolved' and not row.retained_requirement_refs:
                raise ValueError('Partial inspection resolution must preserve remaining requirements')


def _validate_transition(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'confirm_coverage':
        if payload.covered_scope != action_input.scope or not payload.basis_refs:
            raise ValueError('Continued coverage requires the original scope and independent rules')
        unique_refs(payload.basis_refs)
    elif payload.choice == 'open_review':
        if not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
            raise ValueError('Review requires concrete questions within original scope')
    elif payload.choice == 'record_scheduled_expiry':
        if action_input.permit_ref is None or payload.permit_ref != action_input.permit_ref:
            raise ValueError('Expiry record must reference the original actual permit')
    else:
        draft = payload.draft
        if (draft.outcome != payload.choice or draft.prior_decision_ref != action_input.prior_decision_ref
                or action_input.affected_submission_ref is None or draft.submission_ref != action_input.affected_submission_ref
                or draft.covered_scope != action_input.scope or not draft.reason.strip()
                or not draft.notification_recipient_ids
                or len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids)):
            raise ValueError('Change draft must preserve original decision, affected version, scope and actual recipients')
        unique_refs(draft.assessment_refs); unique_refs(draft.next_procedure_refs)


def _validate_formal_decision(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    draft = payload.draft
    if (draft.outcome != payload.choice or draft.case_ref != action_input.case_ref
            or draft.submission_ref != action_input.current_submission_ref
            or draft.covered_scope != action_input.scope or draft.decision_basis_ref != action_input.decision_basis_ref
            or {ref.key() for ref in draft.assessment_refs} != {ref.key() for ref in action_input.assessment_refs}):
        raise ValueError('Formal decision draft changes original outcome, case, application, scope, basis or assessments')
    unique_refs(draft.assessment_refs); unique_refs(draft.next_procedure_refs)
    if (not draft.reason.strip() or not draft.notification_recipient_ids
            or len(set(draft.notification_recipient_ids)) != len(draft.notification_recipient_ids)):
        raise ValueError('Decision requires an original reason and distinct actual notification recipients')
    if draft.prior_decision_ref is not None:
        raise ValueError('GOV-A07 creates an original decision; prior decision changes require GOV-A09')
    if payload.choice == 'approve_with_conditions':
        if not draft.conditions:
            raise ValueError('Conditional approval requires concrete independently authorized conditions')
        for condition in draft.conditions:
            if (not scope_covers(action_input.scope, condition.covered_scope) or not condition.responsible_party_ids
                    or not condition.affected_action_refs or not condition.required_evidence_refs):
                raise ValueError('Decision conditions lack original scope, responsibilities, actions or required evidence')
            unique_refs(condition.affected_action_refs); unique_refs(condition.required_evidence_refs)
    elif draft.conditions:
        raise ValueError('Only conditional approval can carry permission conditions')
    if payload.choice in {'refuse', 'defer_by_procedure'} and draft.expiry_rule_ref is not None:
        raise ValueError('Refusal/deferment cannot carry an approval expiry field')


def _validate_supplement(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'request_supplement':
        if not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
            raise ValueError('Supplement request requires original scoped questions')
    elif payload.choice == 'process_delay':
        unique_refs(payload.issue_refs)
        if not payload.issue_refs or {r.key() for r in payload.issue_refs} != {r.key() for r in action_input.issue_refs}:
            raise ValueError('Delay handling must preserve the original nonempty issue set')
    else:
        unique_refs([row.issue_ref for row in payload.resolutions])
        if not payload.resolutions or {row.issue_ref.key() for row in payload.resolutions} != {ref.key() for ref in action_input.issue_refs}:
            raise ValueError('Response verification must preserve every original issue')
        for row in payload.resolutions:
            for refs in (row.response_refs, row.retained_requirement_refs, row.affected_assessment_refs, row.reusable_assessment_refs):
                unique_refs(refs)
            if not {r.key() for r in row.response_refs} <= {r.key() for r in action_input.response_refs}:
                raise ValueError('Issue verification invents undeclared responses')
            affected = {r.key() for r in row.affected_assessment_refs}
            reusable = {r.key() for r in row.reusable_assessment_refs}
            if affected & reusable or reusable != {r.key() for r in action_input.reusable_assessment_refs}:
                raise ValueError('Affected and reusable review coverage must be distinct and original')
            if row.verification_result_ref is None and row.resolution != 'unresolved':
                raise ValueError('Issue closure requires an original successful scoped verification')
            if row.resolution in {'resolved', 'partially_resolved'} and not row.response_refs:
                raise ValueError('Issue closure cannot infer a response from silence')
            if row.resolution == 'resolved' and row.retained_requirement_refs:
                raise ValueError('Resolved issue cannot retain unmet original requirements')
            if row.resolution != 'resolved' and not row.retained_requirement_refs:
                raise ValueError('Unresolved issue must preserve its unmet original requirements')


def _validate_consultation(action_input, payload):
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    if payload.choice == 'initiate':
        row = payload.draft
        if (action_input.prior_consultation_ref is not None or row.case_ref != action_input.case_ref
                or row.disclosure_package_ref != action_input.disclosure_package_ref
                or {r.key() for r in row.recipient_refs} != {r.key() for r in action_input.recipient_refs}):
            raise ValueError('Consultation draft changes original case, disclosed package or channels')
        unique_refs(row.recipient_refs)
        if any(not scope_covers(action_input.scope, q.scope) for q in row.questions):
            raise ValueError('Consultation draft questions leave original authorized scope')
    elif payload.choice in {'register_response', 'analyze'}:
        if action_input.prior_consultation_ref is None or payload.consultation_ref != action_input.prior_consultation_ref:
            raise ValueError('Consultation response/analysis requires the original existing consultation')
        if payload.choice == 'register_response':
            unique_refs(payload.response_refs)
            if not payload.response_refs or not {r.key() for r in payload.response_refs} <= {r.key() for r in action_input.response_refs}:
                raise ValueError('Response registration must use actual declared original opinion records')
        else:
            assessment = payload.assessment
            if assessment.target_ref != action_input.case_ref or len(assessment.checks) != 1:
                raise ValueError('Consultation analysis must preserve original case and procedure rule')
            check = assessment.checks[0]
            if (check.rule_ref != action_input.consultation_rule_ref or not scope_covers(action_input.scope, check.covered_scope)
                    or check.finding == 'nonconforms' or (check.finding != 'unknown' and check.method_result_ref is None)):
                raise ValueError('Opinions cannot invent a substantive refusal or unexecuted completed procedure')
            if any(not scope_covers(action_input.scope, q.scope) for q in assessment.proposed_questions):
                raise ValueError('Consultation analysis question leaves original authorized scope')
    elif not payload.questions or any(not scope_covers(action_input.scope, q.scope) for q in payload.questions):
        raise ValueError('Consultation referral requires original scoped questions')


def _validate_evidence_review(action_input, payload):
    if payload.choice == 'request_verification':
        if not payload.questions or any(not q.target_refs or not q.recipient_refs for q in payload.questions):
            raise ValueError('Government verification requires specific original targets and recipients')
        return
    row = payload.assessment
    if row.target_ref != action_input.submission_ref or row.task_ref != action_input.task_ref:
        raise ValueError('Government assessment changes original submission version or task')
    from src.actions.contracts.owner_study_objects import unique_refs
    from src.organization.registry import scope_covers
    unique_refs([check.rule_ref for check in row.checks])
    if not row.checks or {check.rule_ref.key() for check in row.checks} != {ref.key() for ref in action_input.rule_refs}:
        raise ValueError('Government assessment must retain every original necessary rule')
    for check in row.checks:
        if not scope_covers(action_input.scope, check.covered_scope):
            raise ValueError('Government finding leaves the original review scope')
        if check.method_result_ref is None and check.finding != 'unknown':
            raise ValueError('Known government finding requires an original successful scoped execution')
        if check.method_result_ref is not None and check.method_result_ref not in action_input.method_result_refs:
            raise ValueError('Government assessment invents an undeclared execution')
    if any(not scope_covers(action_input.scope, question.scope) for question in row.proposed_questions):
        raise ValueError('Government review question leaves the authorized scope')
    if payload.choice == 'propose_conditions':
        if not payload.conditions:
            raise ValueError('Condition proposal must carry concrete authorized conditions')
        for condition in payload.conditions:
            if (condition.condition_rule_ref not in action_input.rule_refs or not condition.responsible_party_ids
                    or not condition.affected_action_refs or not condition.required_evidence_refs
                    or not scope_covers(action_input.scope, condition.covered_scope)):
                raise ValueError('Condition proposal must preserve original rule, responsibility and scope bindings')


def _validate_review_plan(action_input, payload):
    if payload.choice == 'request_cooperation':
        if not payload.questions or any(question.scope != action_input.scope for question in payload.questions):
            raise ValueError('Review cooperation requires original scoped questions')
        return
    from src.actions.contracts.owner_study_objects import unique_refs
    unique_refs([item.task_ref for item in payload.plan.items])
    if not payload.plan.items or {item.task_ref.key() for item in payload.plan.items} != {ref.key() for ref in action_input.task_refs}:
        raise ValueError('Review plan must cover exactly the original nonempty authorized task set')
    expected = {ref.key() for ref in action_input.existing_assignment_refs}
    observed = []
    for item in payload.plan.items:
        if not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
            raise ValueError('Review plan repeats or omits actual resource identities')
        if item.existing_assignment_ref is not None:
            if item.existing_assignment_ref.key() not in expected:
                raise ValueError('Review plan borrows an undeclared original assignment')
            observed.append(item.existing_assignment_ref)
    unique_refs(observed)
    if {ref.key() for ref in observed} != expected:
        raise ValueError('Continuing review plan cannot drop original selected assignment identities')
    if payload.choice == 'reprioritize' and payload.case_ref != action_input.case_ref:
        raise ValueError('Lawful reprioritization must preserve the original case')
