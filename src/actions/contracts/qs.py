"""QS cross-record rules; valuation does not confer certification or payment authority."""


def validate_decision(action_id, action_input, payload):
    if payload.scope != action_input.scope:
        raise ValueError("QS output scope differs from input")
    if action_id == 'QS-A12':
        if payload.choice == 'analyze_error':
            if (payload.forecast_ref.key() not in {r.key() for r in action_input.forecast_refs}
                    or payload.outcome_ref.key() not in {r.key() for r in action_input.outcome_refs}
                    or action_input.comparability_result_ref is None):
                raise ValueError('QS error analysis must retain original forecast/outcome and independent comparability result')
        else:
            from src.actions.contracts.service_learning import validate_service_learning
            validate_service_learning(action_input, payload, capability_from_input=False)
    if action_id == 'QS-A11':
        from src.actions.contracts.service_transition import validate_service_transition
        validate_service_transition(action_input, payload, document_input='deliverable_refs')
    if action_id == 'QS-A09':
        from src.actions.contracts.qs_final_account_objects import QSFinalAccount
        from src.actions.contracts.owner_study_objects import unique_refs
        if payload.choice == 'request_evidence':
            if not payload.questions or any(question.scope != action_input.scope for question in payload.questions):
                raise ValueError('Final account evidence request requires specific original scoped questions')
        else:
            account = QSFinalAccount.model_validate(payload.account.model_dump(mode='python'))
            unique_refs(account.unresolved_claim_refs);unique_refs(account.source_statement_refs)
            if (account.contract_ref != action_input.contract_ref or action_input.reconciliation_result_ref is None
                    or account.reconciliation_result_ref != action_input.reconciliation_result_ref
                    or {r.key() for r in account.unresolved_claim_refs} != {r.key() for r in action_input.unresolved_claim_refs}):
                raise ValueError('Final account must preserve original contract, reconciliation and unresolved claims')
            if payload.choice == 'determine_authorized' and account.determined_total.state != 'known':
                raise ValueError('Final price determination cannot replace unknown original price with a decision')
    if action_id == 'QS-A01':
        if payload.choice == 'track' and payload.opportunity_ref not in action_input.opportunity_refs:
            raise ValueError('Market tracking invents an undeclared opportunity')
        if payload.choice == 'register_source':
            if (not payload.source_refs or not set(payload.source_refs) <= set(action_input.price_source_refs)
                    or payload.source_refs != [payload.applicability.price_source_ref]):
                raise ValueError('Market source registration must preserve one declared original source')
        if payload.choice == 'prepare':
            if (payload.request.scope != action_input.scope
                    or payload.request.purpose not in {'preparation', 'investigation'}
                    or action_input.research_authority_ref is None
                    or payload.request.authority_basis_refs != [action_input.research_authority_ref]):
                raise ValueError('Market preparation requires independent original scoped research authority')
    if action_id == "QS-A02" and payload.choice == "accept" and payload.terms_ref != action_input.terms_ref:
        raise ValueError("Acceptance must name the offered service terms version")
    if action_id == "QS-A03" and payload.choice in {"confirm", "confirm_and_plan"}:
        if payload.appointment_ref != action_input.appointment_ref or payload.accepted_terms_ref != action_input.accepted_terms_ref:
            raise ValueError("Confirmation must preserve appointment and accepted terms")
    if action_id == 'QS-A03':
        if payload.choice == 'request_amendment' and not payload.questions:
            raise ValueError('QS appointment amendment needs original questions')
        if payload.choice in {'confirm_and_plan', 'revise_plan'}:
            if action_input.work_profile_ref is None or payload.plan.work_profile_ref != action_input.work_profile_ref:
                raise ValueError('QS plan requires the exact declared work profile')
            if not payload.plan.items or {r.task_ref.key() for r in payload.plan.items} != {r.key() for r in action_input.task_refs}:
                raise ValueError('QS plan must cover the exact nonempty original task set')
            if len({r.task_ref.key() for r in payload.plan.items}) != len(payload.plan.items):
                raise ValueError('QS plan repeats an original task')
            for row in payload.plan.items:
                if not row.resource_ids or len(set(row.resource_ids)) != len(row.resource_ids):
                    raise ValueError('QS plan requires distinct original resources')
                if row.existing_allocation_ref is not None and row.existing_allocation_ref not in action_input.existing_allocation_refs:
                    raise ValueError('QS plan borrows an undeclared allocation')
    if action_id == "QS-A08" and payload.choice in {"certify", "correct_certificate"}:
        if action_input.certification_authority_ref is None:
            raise ValueError("Certification requires separate authority")
    if action_id == 'QS-A08':
        _validate_payment_statement(action_input, payload)
    if action_id == 'QS-A04':
        _validate_cost_plan(action_input, payload)
    if action_id == 'QS-A05':
        _validate_procurement(action_input, payload)
    if action_id == 'QS-A06':
        _validate_bid_evaluation(action_input, payload)
    if action_id == 'QS-A07':
        _validate_change_valuation(action_input, payload)
    if action_id == 'QS-A10':
        _validate_service_fee(action_input, payload)
    if action_id == 'QS-A13':
        _validate_research_comparison(action_input, payload)


def _validate_service_fee(action_input, payload):
    if payload.choice in {'claim', 'correct'}:
        claim = payload.claim
        if (claim.engagement_ref.key() != action_input.engagement_ref.key()
                or claim.billing_clause_ref.key() != action_input.billing_clause_ref.key()
                or action_input.calculation_ref is None or claim.calculation_ref.key() != action_input.calculation_ref.key()
                or claim.prior_claim_ref != action_input.prior_claim_ref
                or {ref.key() for ref in claim.work_fact_refs} != {ref.key() for ref in action_input.work_fact_refs}):
            raise ValueError('QS fee claim changes original engagement/clause/work/calculation/prior identities')
        from decimal import Decimal
        if Decimal(claim.amount.value) < 0:
            raise ValueError('QS fee net amount cannot be negative')
        if payload.choice == 'correct' and (action_input.prior_claim_ref is None
                or payload.prior_claim_ref.key() != action_input.prior_claim_ref.key()):
            raise ValueError('QS fee correction requires the original prior claim')
    else:
        if action_input.prior_claim_ref is None or payload.claim_ref.key() != action_input.prior_claim_ref.key():
            raise ValueError('QS fee dispute/reconciliation/reminder requires the original existing claim')
        if payload.choice == 'reconcile' and (not payload.receipt_refs
                or {ref.key() for ref in payload.receipt_refs} != {ref.key() for ref in action_input.receipt_refs}):
            raise ValueError('QS fee reconciliation must preserve the original receipt set')
        if payload.choice == 'dispute' and payload.issue.scope != action_input.scope:
            raise ValueError('QS fee dispute changes the original question scope')


def _validate_payment_statement(action_input, payload):
    if payload.choice == 'request_evidence':
        if not payload.questions or any(q.scope != action_input.scope for q in payload.questions):
            raise ValueError('Payment verification request needs original scoped questions')
        return
    row = payload.statement
    if (row.contract_ref != action_input.contract_ref or row.source_application_ref != action_input.application_ref
            or row.covered_scope != action_input.scope or row.calculation_ref not in action_input.measurement_result_refs):
        raise ValueError('Payment statement changes original contract, application, scope or measurement result')
    for ref in (row.retention_result_ref, row.deduction_result_ref):
        if ref is not None and ref not in action_input.measurement_result_refs:
            raise ValueError('Payment statement invents an undeclared adjustment calculation')
    if row.entitlement_refs:
        raise ValueError('Payment verification cannot invent undeclared entitlement decisions')
    from src.actions.contracts.owner_study_objects import unique_refs
    unique_refs(row.prior_statement_refs)
    if payload.choice == 'correct_certificate' and payload.prior_certificate_ref not in action_input.prior_certificate_refs:
        raise ValueError('Correction must preserve a declared original certificate')
    if payload.choice in {'certify', 'correct_certificate'} and row.recognized_amount.state != 'known':
        raise ValueError('Formal certificate needs known original entitlement conditions')


def _validate_change_valuation(action_input, payload):
    if payload.choice == 'request_evidence':
        if not payload.questions or any(q.scope != action_input.scope for q in payload.questions):
            raise ValueError('Change valuation request requires original scoped questions')
        return
    row = payload.valuation
    if (action_input.valuation_result_ref is None or row.calculation_ref != action_input.valuation_result_ref
            or row.contract_ref != action_input.contract_ref or row.source_application_ref != action_input.claim_or_change_ref
            or row.covered_scope != action_input.scope):
        raise ValueError('Change valuation must preserve declared original contract, claim, scope and calculation')
    expected = [] if action_input.entitlement_ref is None else [action_input.entitlement_ref]
    if row.entitlement_refs != expected:
        raise ValueError('Change valuation cannot invent entitlement decisions')
    if not expected and (row.recognized_amount.state == 'known' or row.disputed_amount.state == 'known'):
        raise ValueError('Valuation alone cannot determine a recognized entitlement split')
    if row.basis == 'incremental' and row.prior_statement_refs:
        raise ValueError('Incremental valuation cannot subtract cumulative history')
    from src.actions.contracts.owner_study_objects import unique_refs
    unique_refs(row.prior_statement_refs)


def _validate_research_comparison(action_input, payload):
    if payload.choice == 'request_research':
        if (not payload.questions or payload.request.scope != action_input.scope
                or payload.request.questions != payload.questions or not payload.request.authority_basis_refs):
            raise ValueError('Research request requires original scoped questions and authority')
        if payload.request.authority_basis_refs != [action_input.research_authority_ref]:
            raise ValueError('Research request cannot borrow another delegation')
        return
    comparison = payload.comparison
    if (set(comparison.option_refs) != set(action_input.option_refs)
            or set(comparison.cost_plan_refs) != set(action_input.cost_plan_refs)
            or comparison.comparison_basis_ref != action_input.comparison_basis_ref):
        raise ValueError('Research comparison must preserve original options, submitted plans and basis')
    for refs in (comparison.option_refs, comparison.cost_plan_refs, comparison.ranked_option_refs):
        if len({r.key() for r in refs}) != len(refs): raise ValueError('Research comparison repeats an original reference')
    if not set(comparison.ranked_option_refs) <= set(action_input.option_refs):
        raise ValueError('Research ranking invents an undeclared option')
    if not comparison.comparable and comparison.ranked_option_refs:
        raise ValueError('Cannot rank incomparable research options')
    if payload.choice == 'compare' and (not action_input.cost_plan_refs or not comparison.comparable):
        raise ValueError('Comparison requires at least one submitted, compatible scoped cost plan')
    if payload.choice == 'cannot_rank' and comparison.ranked_option_refs:
        raise ValueError('Cannot-rank report must not include a ranking')
    if payload.choice == 'deliver_at_limit' and payload.remaining_questions != comparison.missing_items:
        raise ValueError('Limited research delivery must preserve original unresolved questions')


def _validate_bid_evaluation(action_input, payload):
    if payload.choice in {'evaluate', 'no_valid_bid'}:
        rows = payload.evaluations
        if {r.bid_ref for r in rows} != set(action_input.bid_refs) or len(rows) != len(action_input.bid_refs):
            raise ValueError('Bid evaluations require the exact complete original bid set')
        for row in rows:
            if row.round_ref != action_input.round_ref or not row.rule_refs:
                raise ValueError('Bid evaluation changes original round or lacks original rules')
            if not set(row.normalization_result_refs) <= set(action_input.method_result_refs):
                raise ValueError('Bid evaluation invents a normalization result')
            if row.status == 'comparable' and row.unresolved_questions:
                raise ValueError('Unresolved bid cannot be called comparable')
        if payload.choice == 'no_valid_bid' and any(r.status != 'exclusion_recommended' for r in rows):
            raise ValueError('Unknown eligibility or comparison cannot imply no valid bid')
        if payload.choice == 'evaluate' and payload.ranking_ref is not None and payload.ranking_ref not in action_input.method_result_refs:
            raise ValueError('Bid evaluation invents an undeclared ranking result')
    elif payload.choice == 'clarify':
        if not payload.questions or any(q.scope != action_input.scope for q in payload.questions):
            raise ValueError('Bid clarification needs original scoped questions')
    elif payload.choice == 'exclude_authorized':
        if payload.bid_ref not in action_input.bid_refs or not payload.evidence_refs:
            raise ValueError('Bid exclusion needs the selected original bid and original evidence')


def _validate_procurement(action_input, payload):
    if payload.choice == 'prepare':
        draft = payload.draft
        if (draft.procurement_scope_ref != action_input.procurement_scope_ref
                or set(draft.design_refs) != set(action_input.design_refs)
                or draft.quantity_schedule_ref != action_input.quantity_schedule_ref
                or draft.measurement_rule_ref != action_input.measurement_rule_ref
                or draft.prior_document_ref != action_input.prior_document_ref):
            raise ValueError('Procurement draft must preserve original input versions and predecessor')
        for values in (draft.design_refs, draft.exclusions):
            if len({r.key() for r in values}) != len(values): raise ValueError('Procurement draft repeats original references')
    if payload.choice == 'identify_gaps' and (not payload.questions or any(q.scope != action_input.scope for q in payload.questions)):
        raise ValueError('Procurement gaps require original scoped questions')
    if payload.choice == 'publish_authorized' and action_input.publication_authority_ref is None:
        raise ValueError('Procurement publication requires separate original publication authority')


def _validate_cost_plan(action_input, payload):
    from fractions import Fraction
    from src.methods.pricing import decimal_fraction

    if payload.choice in {'request_quantity', 'request_price'}:
        if not payload.questions or any(q.scope != action_input.scope for q in payload.questions):
            raise ValueError('Cost requests require original scoped missing-item questions')
        return
    draft = payload.draft
    if (draft.option_ref != action_input.option_ref or draft.cost_scope_ref != action_input.cost_scope_ref
            or draft.comparison_basis_ref != action_input.comparison_basis_ref):
        raise ValueError('Cost plan changes original design, cost scope or comparison versions')
    if len({r.line_key for r in draft.lines}) != len(draft.lines):
        raise ValueError('Cost plan repeats a local line identity')
    if draft.calculation_ref is not None and draft.calculation_ref not in action_input.method_result_refs:
        raise ValueError('Cost plan invents an undeclared calculation')
    for row in draft.lines:
        if row.price_ref is not None and row.price_ref not in action_input.price_refs:
            raise ValueError('Cost line uses an undeclared original price')
        if row.calculation_ref != draft.calculation_ref:
            raise ValueError('Cost line and subtotal must use the same calculation')
        if row.amount.state == 'known' and (row.quantity.state != 'known' or row.calculation_ref is None):
            raise ValueError('Known line amount requires original calculated quantity and execution')
    known = [r.amount.value for r in draft.lines if r.amount.state == 'known']
    if draft.known_subtotal.state == 'known':
        subtotal = draft.known_subtotal.value
        if (not known or draft.calculation_ref is None or any(m.currency != subtotal.currency for m in known)
                or sum((decimal_fraction(m.value) for m in known), Fraction()) != decimal_fraction(subtotal.value)):
            raise ValueError('Cost subtotal must sum computed disjoint lines in one currency')
    elif known:
        raise ValueError('Computed cost lines require their known subtotal')
    if draft.complete_total is not None:
        if (len(known) != len(draft.lines) or not known or draft.known_subtotal.state != 'known'
                or draft.complete_total != draft.known_subtotal.value or draft.missing_items):
            raise ValueError('Complete cost total requires all declared lines and no missing items')
    if payload.choice == 'estimate' and (not known or draft.calculation_ref is None):
        raise ValueError('Estimate requires a saved applicable calculation and a computed range')
