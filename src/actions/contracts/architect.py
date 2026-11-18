"""Architect cross-record rules; branch fields come from the frozen source."""


def validate_decision(action_id, action_input, payload):
    if payload.scope != action_input.scope:
        raise ValueError("Architect output scope differs from input")
    if action_id == 'ARCHITECT-A12':
        from src.actions.contracts.service_learning import validate_service_learning
        validate_service_learning(action_input, payload)
    if action_id == 'ARCHITECT-A11':
        from src.actions.contracts.service_transition import validate_service_transition
        validate_service_transition(action_input, payload)
    if action_id == 'ARCHITECT-A01':
        if payload.choice == 'prepare':
            if (payload.request.scope != action_input.scope
                    or payload.request.purpose not in {'preparation', 'investigation'}
                    or action_input.preparation_authority_ref is None
                    or payload.request.authority_basis_refs != [action_input.preparation_authority_ref]):
                raise ValueError('Discovery preparation needs independent original scoped authority')
        if payload.choice == 'clarify' and (not payload.questions
                or any(question.scope != action_input.scope for question in payload.questions)):
            raise ValueError('Discovery clarification needs original nonempty scoped questions')
    if action_id == "ARCHITECT-A02" and payload.choice == "accept":
        if payload.accepted_terms_ref != action_input.terms_ref:
            raise ValueError("Acceptance must name the offered service terms version")
    if action_id == "ARCHITECT-A03" and payload.choice == "confirm":
        if payload.appointment_ref != action_input.appointment_ref or payload.accepted_terms_ref != action_input.accepted_terms_ref:
            raise ValueError("Confirmation must preserve appointment and accepted terms")
    if action_id == 'ARCHITECT-A10':
        if payload.choice in {'claim', 'correct'}:
            claim = payload.claim
            if (claim.engagement_ref.key() != action_input.engagement_ref.key()
                    or claim.billing_clause_ref.key() != action_input.billing_clause_ref.key()
                    or action_input.calculation_ref is None or claim.calculation_ref.key() != action_input.calculation_ref.key()
                    or claim.prior_claim_ref != action_input.prior_claim_ref
                    or {ref.key() for ref in claim.work_fact_refs} != {ref.key() for ref in action_input.work_fact_refs}):
                raise ValueError('Fee claim must retain original engagement/clause/work/calculation/prior identities')
            from decimal import Decimal
            if Decimal(claim.amount.value) <= 0: raise ValueError('Fee claim amount must be positive')
            if payload.choice == 'correct' and (action_input.prior_claim_ref is None
                    or payload.prior_claim_ref.key() != action_input.prior_claim_ref.key()):
                raise ValueError('Fee correction must retain original nonempty prior claim')
        else:
            if action_input.prior_claim_ref is None or payload.claim_ref.key() != action_input.prior_claim_ref.key():
                raise ValueError('Fee dispute/reconciliation/reminder needs original existing claim')
            if payload.choice == 'reconcile' and (not payload.receipt_refs
                    or {ref.key() for ref in payload.receipt_refs} != {ref.key() for ref in action_input.receipt_refs}):
                raise ValueError('Fee reconciliation must retain original nonempty receipt set')
            if payload.choice == 'dispute' and payload.issue.scope != action_input.scope:
                raise ValueError('Fee dispute must preserve original scoped question')
    if action_id == 'ARCHITECT-A09':
        if payload.choice == 'explain':
            if payload.issue_ref.key() != action_input.issue_ref.key() or not payload.basis_refs:
                raise ValueError('Design explanation must preserve original issue and explicit evidence')
        elif payload.choice == 'propose_change':
            draft = payload.draft
            if draft.prior_deliverable_ref.key() != action_input.used_deliverable_ref.key() or draft.instruction_ref != action_input.instruction_ref:
                raise ValueError('Design change must preserve original used version and instruction')
            if draft.impact_result_ref is not None and draft.impact_result_ref.key() not in {ref.key() for ref in action_input.impact_result_refs}:
                raise ValueError('Design change cannot invent an unexecuted impact result')
            if draft.impact_result_ref is None and not draft.unresolved_questions:
                raise ValueError('Unevaluated design impact must retain explicit unresolved questions')
            refs = [row.variable_ref.key() for row in draft.proposed_variable_changes]
            if len(set(refs)) != len(refs): raise ValueError('Design change repeats an original variable')
        elif not payload.questions or any(question.scope != action_input.scope for question in payload.questions):
            raise ValueError('Design authority request requires specific original scoped questions')
    if action_id == 'ARCHITECT-A08':
        if payload.choice == 'review':
            opinion = payload.opinion
            if (opinion.target_ref.key() != action_input.target_ref.key()
                    or opinion.review_request_ref.key() != action_input.review_request_ref.key()
                    or {ref.key() for ref in opinion.check_result_refs} != {ref.key() for ref in action_input.check_result_refs}):
                raise ValueError('Architect review must retain original target/request/check identities')
            if opinion.opinion == 'support' and (not opinion.check_result_refs or opinion.unresolved_issue_refs):
                raise ValueError('Support needs actual original checks and no unresolved issues')
            for refs in (opinion.check_result_refs, opinion.unresolved_issue_refs):
                if len({ref.key() for ref in refs}) != len(refs): raise ValueError('Architect review repeats an original reference')
        elif payload.choice == 'respond':
            if payload.comment_ref.key() not in {ref.key() for ref in action_input.comment_refs} or not payload.basis_refs:
                raise ValueError('Author response needs original received comment and explicit evidence')
        elif (payload.affected_ref.key() != action_input.target_ref.key() or not payload.questions
                or any(question.scope != action_input.scope for question in payload.questions)):
            raise ValueError('Revision must retain original target version and scoped questions')
    if action_id == 'ARCHITECT-A07':
        if (payload.deliverable_ref.key() != action_input.deliverable_ref.key()
                or payload.requested_use != action_input.requested_use or payload.recipient_ids != action_input.recipient_ids
                or not payload.recipient_ids or len(set(payload.recipient_ids)) != len(payload.recipient_ids)):
            raise ValueError('Submission must retain original deliverable version, requested use and distinct recipients')
        if len({ref.key() for ref in payload.unresolved_issue_refs}) != len(payload.unresolved_issue_refs):
            raise ValueError('Submission repeats an original unresolved issue')
        if payload.choice == 'request_review' and (action_input.review_requirement_ref is None
                or payload.review_requirement_ref.key() != action_input.review_requirement_ref.key()):
            raise ValueError('Review request needs its original nonempty intake requirement')
        if payload.choice == 'release_for_use':
            refs = [ref.key() for ref in payload.release_basis_refs]
            if not refs or len(set(refs)) != len(refs) or set(refs) != {ref.key() for ref in action_input.release_basis_refs}:
                raise ValueError('Use release needs original nonempty independent release basis')
    if action_id == 'ARCHITECT-A06':
        if payload.choice == 'integrate':
            draft = payload.draft
            if (draft.option_ref.key() != action_input.option_ref.key() or action_input.integration_authority_ref is None
                    or draft.integration_authority_ref.key() != action_input.integration_authority_ref.key()
                    or {ref.key() for ref in draft.included_assessment_refs} != {ref.key() for ref in action_input.professional_refs}
                    or {ref.key() for ref in draft.included_cost_refs} != {ref.key() for ref in action_input.cost_refs}
                    or {ref.key() for ref in draft.open_issue_refs} != {ref.key() for ref in action_input.open_issue_refs}
                    or not draft.consistency_result_refs):
                raise ValueError('Integration must retain original option, author inputs, open issues and delegated authority')
            for refs in (draft.included_assessment_refs, draft.included_cost_refs, draft.interface_refs, draft.open_issue_refs, draft.consistency_result_refs):
                if len({ref.key() for ref in refs}) != len(refs): raise ValueError('Integration repeats an original reference')
        elif payload.choice == 'escalate':
            if not payload.issue_refs or {ref.key() for ref in payload.issue_refs} != {ref.key() for ref in action_input.open_issue_refs}:
                raise ValueError('Escalation must retain original nonempty unresolved issue identities')
        else:
            questions = payload.issues if payload.choice == 'raise_interfaces' else payload.questions
            if not questions or any(question.scope != action_input.scope for question in questions):
                raise ValueError('Interface report/input request requires specific original scoped questions')
    if action_id == 'ARCHITECT-A05':
        if payload.choice == 'produce':
            if not payload.options: raise ValueError('Design compilation requires nonempty original option drafts')
            for option in payload.options:
                if (option.scope != action_input.scope or option.brief_ref.key() != action_input.brief_ref.key()
                        or option.design_profile_ref.key() != action_input.design_profile_ref.key()
                        or not {ref.key() for ref in option.basis_refs} <= {ref.key() for ref in action_input.basis_refs}
                        or not {ref.key() for ref in option.method_result_refs} <= {ref.key() for ref in action_input.method_result_refs}):
                    raise ValueError('Design draft must retain original brief/profile/scope/evidence/method inputs')
                if option.relation != 'original' and (option.parent_option_ref is None or action_input.prior_option_ref is None
                        or option.parent_option_ref.key() != action_input.prior_option_ref.key()):
                    raise ValueError('Design revision/alternative must retain original parent version')
        elif payload.choice == 'compare':
            comparison = payload.comparison
            if (set(ref.key() for ref in comparison.option_refs) != set(ref.key() for ref in action_input.available_option_refs)
                    or set(ref.key() for ref in comparison.professional_refs) != set(ref.key() for ref in action_input.professional_refs)
                    or set(ref.key() for ref in comparison.cost_refs) != set(ref.key() for ref in action_input.cost_refs)
                    or action_input.comparison_scope_ref is None or comparison.comparable_scope_ref.key() != action_input.comparison_scope_ref.key()
                    or comparison.comparison_method_ref != action_input.comparison_method_ref):
                raise ValueError('Design comparison must retain original registered options, inputs, scope and method')
            for refs in (comparison.option_refs, comparison.professional_refs, comparison.cost_refs,
                         comparison.recommended_option_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                    raise ValueError('Design comparison repeats a physical source across versions')
            if comparison.recommended_option_refs and (comparison.comparison_method_ref is None or comparison.unresolved_questions):
                raise ValueError('Design recommendation needs an applicable method and no unresolved blocking questions')
            if any(question.scope != action_input.scope for question in comparison.unresolved_questions):
                raise ValueError('Design comparison questions must preserve original scope')
        elif not payload.questions or any(question.scope != action_input.scope for question in payload.questions):
            raise ValueError('Design input request requires original scoped questions')
    if action_id == 'ARCHITECT-A04':
        if payload.choice == 'request_inputs':
            if not payload.questions or any(question.scope != action_input.scope for question in payload.questions):
                raise ValueError('Design planning requires explicit original scoped questions')
        else:
            plan = payload.plan
            if plan.work_profile_ref.key() != action_input.work_profile_ref.key() or not plan.items:
                raise ValueError('Design plan needs original work profile and nonempty authorized task items')
            seen = set()
            for item in plan.items:
                key = item.task_ref.key()
                if key in seen or key not in {ref.key() for ref in action_input.task_refs} or not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids):
                    raise ValueError('Design plan repeats or invents an original task/resource')
                seen.add(key)
                if item.existing_allocation_ref is not None and item.existing_allocation_ref.key() not in {ref.key() for ref in action_input.existing_allocation_refs}:
                    raise ValueError('Design plan must retain original allocation identity')
    if action_id == 'ARCHITECT-A03' and payload.choice == 'request_amendment' and not payload.questions:
        raise ValueError('Appointment amendment requires specific original questions')
    if action_id == 'ARCHITECT-A13':
        if payload.choice == 'recommend_investigation':
            if (not payload.questions or payload.request.questions != payload.questions
                    or payload.request.scope != action_input.scope
                    or payload.request.purpose not in {'preparation', 'investigation'}
                    or payload.request.authority_basis_refs != [action_input.research_authority_ref]):
                raise ValueError('Preliminary investigation requires the exact scoped questions and independent original delegation')
        else:
            comparison = payload.comparison
            if (set(comparison.option_refs) != set(action_input.available_option_refs)
                    or set(comparison.professional_refs) != set(action_input.professional_refs)
                    or set(comparison.cost_refs) != set(action_input.cost_refs)
                    or comparison.comparable_scope_ref != action_input.comparison_scope_ref
                    or comparison.comparison_method_ref != action_input.comparison_method_ref):
                raise ValueError('Preliminary comparison changes original options, inputs, scope or selected method')
            for refs in (comparison.option_refs, comparison.professional_refs, comparison.cost_refs,
                         comparison.recommended_option_refs):
                if len({(r.kind, r.id) for r in refs}) != len(refs):
                    raise ValueError('Preliminary comparison repeats a physical source across versions')
            if not set(comparison.recommended_option_refs) <= set(comparison.option_refs):
                raise ValueError('Preliminary comparison invents an undeclared option')
            if comparison.recommended_option_refs and (comparison.comparison_method_ref is None or comparison.unresolved_questions):
                raise ValueError('Recommendation requires selected applicable method and no unresolved blocking questions')
            if payload.choice == 'compare' and (not comparison.option_refs or not comparison.recommended_option_refs):
                raise ValueError('Comparison needs an original candidate and a supported recommendation')
            if payload.choice in {'no_recommendation', 'deliver_at_limit'} and comparison.recommended_option_refs:
                raise ValueError('Limited report cannot invent a successful recommendation')
            if payload.choice == 'deliver_at_limit' and payload.remaining_questions != comparison.unresolved_questions:
                raise ValueError('Limit report must preserve all original unresolved questions')
            if any(q.scope != action_input.scope for q in comparison.unresolved_questions):
                raise ValueError('Research comparison questions must preserve original scope')
