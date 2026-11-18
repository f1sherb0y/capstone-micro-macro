"""Engineer cross-record rules; professional evidence remains independently checked."""


def validate_decision(action_id, action_input, payload):
    if payload.scope != action_input.scope:
        raise ValueError("Engineer output scope differs from input")
    if action_id == 'ENGINEER-A12':
        if payload.choice == 'request_qualification_update':
            from src.actions.contracts.owner_study_objects import unique_refs
            unique_refs(payload.evidence_refs)
            if (payload.qualification_ref.key() not in {r.key() for r in action_input.qualification_refs}
                    or not payload.evidence_refs):
                raise ValueError('Qualification verification request needs original input credential and independent evidence')
        else:
            from src.actions.contracts.service_learning import validate_service_learning
            validate_service_learning(action_input, payload, capability_from_input=False)
    if action_id == 'ENGINEER-A11':
        from src.actions.contracts.service_transition import validate_service_transition
        validate_service_transition(action_input, payload, document_input='deliverable_refs')
    if action_id == 'ENGINEER-A10':
        if payload.choice in {'claim', 'correct'}:
            claim = payload.claim
            if (claim.engagement_ref.key() != action_input.engagement_ref.key()
                    or claim.billing_clause_ref.key() != action_input.billing_clause_ref.key()
                    or action_input.calculation_ref is None or claim.calculation_ref.key() != action_input.calculation_ref.key()
                    or claim.prior_claim_ref != action_input.prior_claim_ref
                    or {ref.key() for ref in claim.work_fact_refs} != {ref.key() for ref in action_input.work_fact_refs}):
                raise ValueError('Engineering fee claim changes original engagement/clause/work/calculation/prior identities')
            from decimal import Decimal
            if Decimal(claim.amount.value) < 0: raise ValueError('Engineering fee net amount cannot be negative')
            if payload.choice == 'correct' and (action_input.prior_claim_ref is None
                    or payload.prior_claim_ref.key() != action_input.prior_claim_ref.key()):
                raise ValueError('Engineering fee correction requires original prior claim')
        else:
            if action_input.prior_claim_ref is None or payload.claim_ref.key() != action_input.prior_claim_ref.key():
                raise ValueError('Engineering fee dispute/reconciliation/reminder needs original existing claim')
            if payload.choice == 'reconcile' and (not payload.receipt_refs
                    or {ref.key() for ref in payload.receipt_refs} != {ref.key() for ref in action_input.receipt_refs}):
                raise ValueError('Engineering fee reconciliation requires original receipt set')
            if payload.choice == 'dispute' and payload.issue.scope != action_input.scope:
                raise ValueError('Engineering fee dispute changes original question scope')
    if action_id == 'ENGINEER-A09':
        if payload.choice == 'propose_remedy':
            if (payload.request.scope != action_input.scope or payload.request.purpose not in {'remedy', 'investigation'}
                    or not payload.affected_refs or not payload.request.authority_basis_refs):
                raise ValueError('Remedy proposal requires original scoped bounded task request')
            if len({ref.key() for ref in payload.affected_refs}) != len(payload.affected_refs):
                raise ValueError('Remedy proposal repeats affected original versions')
        if payload.choice == 'revise':
            if payload.draft.scope != action_input.scope or payload.draft.parent_option_ref is None:
                raise ValueError('Professional revision must retain original scope and parent version')
            if ({ref.key() for ref in payload.draft.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
                    or not {ref.key() for ref in payload.draft.evidence_refs} <= {ref.key() for ref in action_input.evidence_refs}):
                raise ValueError('Professional revision changes original method/evidence inputs')
        if payload.choice == 'reassess':
            assessment = payload.assessment
            if assessment.target_ref.key() != action_input.prior_deliverable_ref.key():
                raise ValueError('Professional recheck changes original target version')
            if len({item.check_spec_ref.key() for item in assessment.check_items}) != len(assessment.check_items):
                raise ValueError('Professional recheck repeats original check')
            for item in assessment.check_items:
                if item.method_result_ref is not None and item.method_result_ref.key() not in {ref.key() for ref in action_input.method_result_refs}:
                    raise ValueError('Professional recheck invents saved method result')
                if item.result is not None and item.method_result_ref is None:
                    raise ValueError('Professional recheck finding requires original saved execution')
                if item.result in {'satisfied', 'conflict'} and item.missing_field_paths:
                    raise ValueError('Known professional recheck cannot retain missing inputs')
            if any(item.result == 'conflict' for item in assessment.check_items) and assessment.opinion != 'revise':
                raise ValueError('Professional recheck cannot average away conflict')
            if assessment.opinion == 'support_limited_option' and (not assessment.check_items or assessment.uncovered_scope_refs
                    or any(item.result != 'satisfied' or item.evidence_status != 'sufficient' or item.issue_refs for item in assessment.check_items)):
                raise ValueError('Professional recheck support requires covered sufficient successful checks')
        if payload.choice == 'request_test' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
            raise ValueError('Professional remedy test request requires original scoped questions')
    if action_id == 'ENGINEER-A08':
        if payload.choice == 'plan_inspection':
            if (len(payload.plan.items) != 1 or payload.plan.items[0].task_ref.key() != action_input.inspection_task_ref.key()
                    or not payload.plan.items[0].resource_ids
                    or len(set(payload.plan.items[0].resource_ids)) != len(payload.plan.items[0].resource_ids)):
                raise ValueError('Inspection plan must preserve original task and distinct actual resources')
        if payload.choice == 'report':
            assessment = payload.assessment
            if (assessment.target_ref.key() != action_input.applicable_design_ref.key()
                    or assessment.task_ref.key() != action_input.inspection_task_ref.key()
                    or payload.observation_refs != action_input.observation_refs):
                raise ValueError('Inspection report changes original task/design/observations')
            if len({item.check_spec_ref.key() for item in assessment.check_items}) != len(assessment.check_items):
                raise ValueError('Inspection report repeats original check')
            for item in assessment.check_items:
                if item.result is not None and item.method_result_ref is None:
                    raise ValueError('Substantive inspection findings require original saved method result')
                if item.result in {'satisfied', 'conflict'} and item.missing_field_paths:
                    raise ValueError('Known inspection finding cannot have missing inputs')
            if any(item.result == 'conflict' for item in assessment.check_items) and assessment.opinion != 'revise':
                raise ValueError('Inspection report cannot average away conflict')
            if assessment.opinion == 'support_limited_option' and (not assessment.check_items or assessment.uncovered_scope_refs
                    or any(item.result != 'satisfied' or item.evidence_status != 'sufficient' or item.issue_refs for item in assessment.check_items)):
                raise ValueError('Inspection support requires sufficient covered checks without unresolved issues')
        if payload.choice == 'respond' and (payload.question_ref.key() not in {ref.key() for ref in action_input.query_refs} or not payload.basis_refs):
            raise ValueError('Inspection response requires original received query and evidence')
        if payload.choice == 'request_test' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
            raise ValueError('Inspection test request requires original scoped questions')
    if action_id == 'ENGINEER-A07':
        if payload.deliverable_ref.key() != action_input.deliverable_ref.key() or payload.requested_use != action_input.requested_use:
            raise ValueError('Professional publication changes original deliverable/use')
        if payload.choice == 'submit':
            if (not payload.recipient_ids or payload.recipient_ids != action_input.recipient_ids
                    or len(set(payload.recipient_ids)) != len(payload.recipient_ids)):
                raise ValueError('Professional submission requires original distinct recipients')
            if len({ref.key() for ref in payload.unresolved_issue_refs}) != len(payload.unresolved_issue_refs):
                raise ValueError('Professional submission repeats unresolved issues')
        if payload.choice == 'sign':
            refs = payload.signing_basis_refs
            if not refs or refs != action_input.signing_basis_refs or len({ref.key() for ref in refs}) != len(refs):
                raise ValueError('Professional signature requires exact original signing bases')
        if payload.choice == 'release_for_use':
            refs = payload.release_basis_refs
            if not refs or refs != action_input.release_basis_refs or len({ref.key() for ref in refs}) != len(refs):
                raise ValueError('Professional release requires exact original use release bases')
    if action_id == 'ENGINEER-A06':
        if payload.choice == 'assess':
            assessment = payload.assessment
            if assessment.target_ref.key() != action_input.target_ref.key():
                raise ValueError('Professional review changes original target')
            keys = [item.check_spec_ref.key() for item in assessment.check_items]
            if len(set(keys)) != len(keys) or set(keys) != {ref.key() for ref in action_input.check_spec_refs}:
                raise ValueError('Professional review omits, repeats or invents original check specifications')
            for item in assessment.check_items:
                if item.method_result_ref is not None and item.method_result_ref.key() not in {ref.key() for ref in action_input.method_result_refs}:
                    raise ValueError('Professional review invents original saved execution')
                if item.result is not None and item.method_result_ref is None:
                    raise ValueError('Substantive professional result requires original saved execution')
                if item.result in {'satisfied', 'conflict'} and item.missing_field_paths:
                    raise ValueError('Known professional result cannot retain missing inputs')
            if assessment.opinion == 'support_limited_option' and (not assessment.check_items or assessment.uncovered_scope_refs
                    or any(item.result != 'satisfied' or item.evidence_status != 'sufficient' or item.issue_refs for item in assessment.check_items)):
                raise ValueError('Professional support requires all original scoped checks without unresolved issues')
            if any(item.result == 'conflict' for item in assessment.check_items) and assessment.opinion != 'revise':
                raise ValueError('Professional review cannot average away a known conflict')
        if payload.choice == 'request_evidence' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
            raise ValueError('Professional evidence request requires original scoped questions')
        if payload.choice == 'request_coordination' and (not payload.issue_refs or len({ref.key() for ref in payload.issue_refs}) != len(payload.issue_refs)):
            raise ValueError('Professional coordination requires distinct original issues')
    if action_id == 'ENGINEER-A05':
        if payload.choice == 'produce':
            draft = payload.draft
            if (draft.scope != action_input.scope or draft.brief_ref.key() != action_input.brief_ref.key()
                    or draft.engineering_profile_ref.key() != action_input.engineering_profile_ref.key()
                    or (draft.parent_option_ref is None) != (action_input.prior_option_ref is None)
                    or (draft.parent_option_ref is not None and draft.parent_option_ref.key() != action_input.prior_option_ref.key())):
                raise ValueError('Professional draft changes original brief/profile/scope/parent')
            for refs in (draft.selected_parameter_refs, draft.method_result_refs, draft.interface_refs, draft.quantity_basis_refs):
                if len({ref.key() for ref in refs}) != len(refs): raise ValueError('Professional draft repeats original inputs')
            if ({ref.key() for ref in draft.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
                    or not {ref.key() for ref in draft.evidence_refs} <= {ref.key() for ref in action_input.evidence_refs}):
                raise ValueError('Professional draft changes original methods or evidence')
            if any(q.scope != action_input.scope for q in draft.unresolved_questions):
                raise ValueError('Professional draft questions change scope')
        if payload.choice == 'request_investigation' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
            raise ValueError('Professional investigation requires original scoped questions')
        if payload.choice == 'report_limit':
            assessment = payload.assessment
            if assessment.task_ref.key() != action_input.task_ref.key() or assessment.target_ref.key() not in {
                    action_input.brief_ref.key(), *((action_input.prior_option_ref.key(),) if action_input.prior_option_ref else ())}:
                raise ValueError('Professional assessment changes original task/target')
            if assessment.opinion == 'support_limited_option' and (not assessment.check_items or assessment.uncovered_scope_refs
                    or any(item.result != 'satisfied' or item.evidence_status != 'sufficient' or item.issue_refs for item in assessment.check_items)):
                raise ValueError('Professional support requires sufficient successful original scoped checks')
    if action_id == 'ENGINEER-A04':
        if payload.choice in {'allocate', 'revise_plan'}:
            if payload.plan.work_profile_ref.key() != action_input.work_profile_ref.key() or not payload.plan.items:
                raise ValueError('Professional plan requires original work profile and selected tasks')
            keys = [item.task_ref.key() for item in payload.plan.items]
            if len(set(keys)) != len(keys) or not set(keys) <= {ref.key() for ref in action_input.task_refs}:
                raise ValueError('Professional plan repeats or invents authorized tasks')
            for item in payload.plan.items:
                if not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
                    raise ValueError('Professional plan requires distinct actual resources')
                if item.existing_allocation_ref is not None and item.existing_allocation_ref.key() not in {ref.key() for ref in action_input.existing_allocation_refs}:
                    raise ValueError('Professional plan invents original allocation')
        if payload.choice == 'request_investigation' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
            raise ValueError('Investigation requires original scoped questions')
    if action_id == 'ENGINEER-A01':
        if payload.choice == 'prepare':
            if (payload.request.scope != action_input.scope
                    or payload.request.purpose not in {'preparation', 'investigation'}
                    or action_input.preparation_authority_ref is None
                    or payload.request.authority_basis_refs != [action_input.preparation_authority_ref]):
                raise ValueError('Engineering discovery preparation requires independent original scoped authority')
        if payload.choice == 'clarify' and (not payload.questions
                or any(question.scope != action_input.scope for question in payload.questions)):
            raise ValueError('Engineering discovery clarification requires original scoped questions')
    if action_id == "ENGINEER-A02" and payload.choice == "accept" and payload.terms_ref != action_input.terms_ref:
        raise ValueError("Acceptance must name the offered service terms version")
    if action_id == "ENGINEER-A03" and payload.choice == "confirm":
        if payload.appointment_ref != action_input.appointment_ref or payload.accepted_terms_ref != action_input.accepted_terms_ref:
            raise ValueError("Confirmation must preserve appointment and accepted terms")
    if action_id == 'ENGINEER-A03':
        if payload.choice in {'disclose_conflict', 'request_amendment'} and not payload.questions:
            raise ValueError('Engineer appointment requires specific original questions')
        if payload.choice == 'disclose_conflict' and not payload.conflict_refs:
            raise ValueError('Conflict disclosure needs original conflict records')
    if action_id == 'ENGINEER-A13':
        if payload.choice == 'recommend_investigation':
            if (not payload.questions or payload.request.questions != payload.questions
                    or payload.request.scope != action_input.scope
                    or payload.request.purpose not in {'preparation', 'investigation'}
                    or payload.request.authority_basis_refs != [action_input.research_authority_ref]
                    or any(q.scope != action_input.scope for q in payload.questions)):
                raise ValueError('Engineering investigation needs exact original scoped questions and independent delegation')
            return
        if payload.choice == 'compare' and not payload.assessments:
            raise ValueError('Engineering comparison requires at least one limited assessment')
        targets = {action_input.brief_ref, *action_input.option_refs}
        if len({row.target_ref.key() for row in payload.assessments}) != len(payload.assessments):
            raise ValueError('Engineering research repeats a target assessment')
        for row in payload.assessments:
            if row.target_ref not in targets or row.task_ref != action_input.task_ref or row.requested_use != 'research':
                raise ValueError('Engineering assessment changes original target, task or authorized research use')
            if len({item.check_spec_ref.key() for item in row.check_items}) != len(row.check_items):
                raise ValueError('Engineering assessment repeats an original check specification')
            for item in row.check_items:
                if item.check_spec_ref not in action_input.check_spec_refs:
                    raise ValueError('Engineering assessment invents an undeclared original check')
                if item.method_result_ref is not None and item.method_result_ref not in action_input.method_result_refs:
                    raise ValueError('Engineering assessment invents a saved execution result')
                if item.result is not None and item.method_result_ref is None:
                    raise ValueError('Substantive engineering result requires original saved execution')
                if item.result in {'satisfied', 'conflict'} and item.missing_field_paths:
                    raise ValueError('Known engineering check cannot retain missing execution inputs')
            if row.opinion == 'support_limited_option' and (not row.check_items or row.uncovered_scope_refs
                    or any(item.result != 'satisfied' or item.evidence_status != 'sufficient' for item in row.check_items)):
                raise ValueError('Limited support requires sufficient evidence for all declared checks and covered scope')
        if payload.choice == 'deliver_at_limit' and any(q.scope != action_input.scope for q in payload.remaining_questions):
            raise ValueError('Engineering limit report questions must preserve original scope')
