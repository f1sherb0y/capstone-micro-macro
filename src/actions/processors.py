"""Deterministic processors for the locally supported representative actions.

These processors produce micro decisions from the supplied, authorized input
only. They never create a formal project, loan, contract, inventory record or
macro receipt.
"""
from __future__ import annotations

from src.actions.registry import ActionRegistry
from src.actions.contracts.common import walk_references


def _key(reference):
    return reference.kind, reference.id, reference.version


def _visible(context, *references):
    visible = {_key(reference) for reference in context.visible_refs}
    return all(reference is not None and _key(reference) in visible for reference in references)


def _refs(value):
    """Return references nested in a validated input value in source order."""
    return tuple(walk_references(value))


def _missing_visible(context, fields):
    """Find required input fields that are empty or outside the read projection.

    The caller still owns the input object; visibility is checked against the
    references actually needed by the selected branch.  An empty list is a
    missing fact, while an unavailable reference can be requested explicitly.
    """
    visible = {_key(reference) for reference in context.visible_refs}
    missing_fields = []
    requested = []
    seen = set()
    for field, value in fields:
        refs = _refs(value)
        if not refs:
            missing_fields.append(field)
            continue
        unavailable = [reference for reference in refs if _key(reference) not in visible]
        if unavailable:
            missing_fields.append(field)
            for reference in unavailable:
                key = _key(reference)
                if key not in seen:
                    requested.append(reference)
                    seen.add(key)
    return missing_fields, requested


def _needs(fields, references=()):
    return {"kind": "needs_information", "missing_fields": list(fields),
            "requested_refs": [reference for reference in references if reference is not None]}


def contractor_a01(context, action_input, registration=None, reading=None):
    required = [
        ("package_ref", action_input.package_ref),
        ("capability_ref", action_input.capability_ref),
        ("commitments_ref", action_input.commitments_ref),
        ("screening_profile_ref", action_input.screening_profile_ref),
    ]
    if action_input.qualification_refs:
        required.append(("qualification_refs", action_input.qualification_refs))
    # An invitation is optional in the source contract, but when supplied it
    # is part of the facts used for screening and must be visible as a whole.
    if action_input.invitation_refs:
        required.append(("invitation_refs", action_input.invitation_refs))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.contractor import screen_participation
    return screen_participation(context, action_input, reading)


def contractor_a02(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('package_ref', 'capacity_ref', 'pricing_profile_ref')]
    for name in ('deliverable_refs', 'quantity_refs', 'cost_refs', 'allowed_method_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_bid import prepare_bid
    return prepare_bid(context, action_input, reading)


def contractor_a03(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('bid_ref', 'package_ref', 'round_ref', 'amendment_rule_ref')]
    for name in ('clarification_refs', 'reservation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_amendment import amend_bid
    return amend_bid(context, action_input, reading)


def contractor_a04(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('offer_ref', 'terms_ref', 'authority_ref', 'capacity_ref', 'funding_ref', 'formation_profile_ref')]
    if action_input.counterpart_acceptance_refs:
        required.append(('counterpart_acceptance_refs', action_input.counterpart_acceptance_refs))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_formation import decide_contract
    return decide_contract(context, action_input, reading)


def contractor_a05(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_planning import plan_work_and_supply
    return plan_work_and_supply(context, action_input, reading)


def contractor_a06(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_readiness import check_task_readiness
    return check_task_readiness(context, action_input, reading)


def contractor_a07(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_execution import execute_or_report
    return execute_or_report(context, action_input, reading)


def contractor_a08(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_quality import inspect_and_remedy
    return inspect_and_remedy(context, action_input, reading)


def contractor_a09(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_claim import handle_interfaces_and_claims
    return handle_interfaces_and_claims(context, action_input, reading)


def contractor_a10(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_payment import request_measurement_and_cash
    return request_measurement_and_cash(context, action_input, reading)


def contractor_a11(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_closeout import request_closeout
    return request_closeout(context, action_input, reading)


def contractor_a13(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('brief_ref', 'advisory_request_ref', 'capability_ref')]
    if action_input.advisory_authority_ref is not None: required.append(('advisory_authority_ref', action_input.advisory_authority_ref))
    for name in ('option_refs', 'supplier_evidence_refs', 'method_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_advice import give_preliminary_advice
    return give_preliminary_advice(context, action_input, reading)


def supplier_a13(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('brief_ref', 'advisory_request_ref', 'capability_ref', 'disclosure_profile_ref')]
    if action_input.advisory_scope_ref is not None: required.append(('advisory_scope_ref', action_input.advisory_scope_ref))
    for name in ('option_refs', 'professional_advice_refs', 'feasibility_method_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_advice import give_supply_advice
    return give_supply_advice(context, action_input, reading)


def owner_a06(context, action_input, registration=None, reading=None):
    required = [('scope_ref', action_input.scope_ref)]
    for name in ('account_refs', 'arrangement_refs', 'due_refs', 'evidence_refs', 'pending_execution_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_payment import instruct_cash
    return instruct_cash(context, action_input, reading)


def owner_a07(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('brief_ref', 'authority_ref')]
    for name in ('submission_refs', 'comparison_refs', 'issue_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_design import decide_design
    return decide_design(context, action_input, reading)


def owner_a08(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope_ref', 'regulatory_requirement_ref')]
    for name in ('authority_candidates', 'submission_refs', 'notice_refs', 'case_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_regulatory import handle_regulatory
    return handle_regulatory(context, action_input, reading)


def owner_a11(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('contract_ref', 'authority_ref', 'funding_ref')]
    for name in ('issue_refs', 'assessment_refs', 'evidence_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_contract import manage_contract
    return manage_contract(context, action_input, reading)


def owner_a12(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_closeout import decide_closeout
    return decide_closeout(context, action_input, reading)


def owner_a13(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_continuation import decide_continuation
    return decide_continuation(context, action_input, reading)


def owner_a14(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_asset import decide_asset_operation
    return decide_asset_operation(context, action_input, reading)


def owner_a15(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_operating import decide_owner_operations
    return decide_owner_operations(context, action_input, reading)


def bank_a09(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('arrangement_ref', 'accrual_window_ref', 'calculation_profile_ref')]
    for name in ('debt_components', 'verified_receipts', 'prior_posting_refs', 'execution_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_debt import account_debt
    return account_debt(context, action_input, reading)


def bank_a10(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_resolution import resolve_debt
    return resolve_debt(context, action_input, reading)


def bank_a11(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_closeout import close_arrangement
    return close_arrangement(context, action_input, reading)


def bank_a12(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_learning import learn_bank_outcomes
    return learn_bank_outcomes(context, action_input, reading)


def bank_a08(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('arrangement_ref', 'monitoring_profile_ref')]
    for name in ('disclosure_refs', 'covenant_refs', 'notice_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_monitoring import monitor_arrangement
    return monitor_arrangement(context, action_input, reading)


def bank_a07(context, action_input, registration=None, reading=None):
    required = [('arrangement_ref', action_input.arrangement_ref),
                ('operation_context', action_input.operation_context)]
    if action_input.receipt_refs:
        required.append(('receipt_refs', action_input.receipt_refs))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_execution import handle_execution
    return handle_execution(context, action_input, reading)


def bank_a06(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('draw_request_ref', 'arrangement_ref', 'capacity_snapshot_ref', 'purpose_ref')]
    for name in ('condition_evidence_refs', 'pending_execution_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_draw import decide_draw
    return decide_draw(context, action_input, reading)


def bank_a02(context, action_input, registration=None, reading=None):
    required = [
        ("application_ref", action_input.application_ref),
        ("applicant_authority_ref", action_input.applicant_authority_ref),
        ("purpose_ref", action_input.purpose_ref),
    ]
    if action_input.product_candidates:
        required.append(("product_candidates", action_input.product_candidates))
    if action_input.disclosure_refs:
        required.append(("disclosure_refs", action_input.disclosure_refs))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.bank import intake_application
    return intake_application(context, action_input, reading)


def owner_a01(context, action_input, registration=None, reading=None):
    base_missing, base_requested = _missing_visible(context, [
        ("scope_ref", action_input.scope_ref),
        ("objective_ref", action_input.objective_ref),
        ("capacity_ref", action_input.capacity_ref),
    ])
    if base_missing:
        return _needs(base_missing, base_requested)
    required = [(name, getattr(action_input, name)) for name in
                ("observations", "opportunity_refs", "existing_case_refs") if getattr(action_input, name)]
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.owner import observe_opportunities
    return observe_opportunities(context, action_input, reading)


def _professional_a02(context, action_input, role):
    required = [
        ("request_ref", action_input.request_ref),
        ("terms_ref", action_input.terms_ref),
        ("capability_ref", action_input.capability_ref),
        ("capacity_ref", action_input.capacity_ref),
    ]
    if role == "Architect":
        role_specific = ("price_basis_ref", action_input.price_basis_ref)
    elif role == "Engineer":
        role_specific = ("independence_requirement_ref", action_input.independence_requirement_ref)
    else:
        role_specific = ("conflict_check_ref", action_input.conflict_check_ref)
    if role_specific[1] is not None:
        required.append(role_specific)
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    terms_field = "accepted_terms_ref" if role == "Architect" else "terms_ref"
    return {"kind": "completed", "payload": {"choice": "accept", "scope": action_input.scope,
            terms_field: action_input.terms_ref,
            "note": f"Accept the visible {role} service request on the exact offered terms"}}


def architect_a01(context, action_input, registration=None, reading=None):
    required = [('opportunity_ref', action_input.opportunity_ref),
                ('strategy_ref', action_input.strategy_ref), ('capacity_ref', action_input.capacity_ref)]
    if action_input.preparation_authority_ref is not None:
        required.append(('preparation_authority_ref', action_input.preparation_authority_ref))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_opportunity import discover_opportunity
    return discover_opportunity(context, action_input, reading)


def architect_a02(context, action_input, registration=None, reading=None):
    required = [("request_ref", action_input.request_ref), ("terms_ref", action_input.terms_ref),
                ("capability_ref", action_input.capability_ref), ("capacity_ref", action_input.capacity_ref),
                ("price_basis_ref", action_input.price_basis_ref)]
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.architect import assess_service_request
    return assess_service_request(context, action_input, reading)


def engineer_a01(context, action_input, registration=None, reading=None):
    required = [('opportunity_ref', action_input.opportunity_ref),
                ('capability_ref', action_input.capability_ref), ('capacity_ref', action_input.capacity_ref)]
    if action_input.preparation_authority_ref is not None:
        required.append(('preparation_authority_ref', action_input.preparation_authority_ref))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_opportunity import discover_opportunity
    return discover_opportunity(context, action_input, reading)


def engineer_a02(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ("request_ref", "terms_ref", "capability_ref", "capacity_ref")]
    if action_input.independence_requirement_ref is not None:
        required.append(("independence_requirement_ref", action_input.independence_requirement_ref))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.engineer import assess_service_request
    return assess_service_request(context, action_input, reading)


def qs_a02(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ("request_ref", "terms_ref", "capability_ref", "capacity_ref")]
    if action_input.conflict_check_ref is not None:
        required.append(("conflict_check_ref", action_input.conflict_check_ref))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.qs import assess_service_request
    return assess_service_request(context, action_input, reading)


def gov_a01(context, action_input, registration=None, reading=None):
    required = [('consultation_ref', action_input.consultation_ref),
                ('matter_ref', action_input.matter_ref), ('jurisdiction_ref', action_input.jurisdiction_ref)]
    for name in ('brief_ref', 'procedure_ref', 'option_refs', 'evidence_refs'):
        if getattr(action_input, name):
            required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_advice import respond_to_consultation
    return respond_to_consultation(context, action_input, reading)


def gov_a02(context, action_input, registration=None, reading=None):
    required = [
        ("submission_ref", action_input.submission_ref),
        ("matter_ref", action_input.matter_ref),
        ("jurisdiction_ref", action_input.jurisdiction_ref),
        ("procedure_ref", action_input.procedure_ref),
    ]
    if action_input.agency_authority_ref is not None:
        required.append(("agency_authority_ref", action_input.agency_authority_ref))
    if action_input.prior_case_ref is not None:
        required.append(("prior_case_ref", action_input.prior_case_ref))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.government import intake_submission
    return intake_submission(context, action_input, reading)


def supplier_a01(context, action_input, registration=None, reading=None):
    required = [
        ("capability_ref", action_input.capability_ref),
        ("capacity_ref", action_input.capacity_ref),
        ("screening_profile_ref", action_input.screening_profile_ref),
    ]
    for field in ("inquiry_refs", "market_refs"):
        if getattr(action_input, field):
            required.append((field, getattr(action_input, field)))
    base_missing, base_requested = _missing_visible(context, required)
    if base_missing:
        return _needs(base_missing, base_requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.supplier import screen_demand
    return screen_demand(context, action_input, reading)


def supplier_a02(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ("inquiry_ref", "compatibility_method_ref")]
    for field in ("requirement_refs", "design_refs", "product_candidates", "design_authority_refs"):
        if getattr(action_input, field):
            required.append((field, getattr(action_input, field)))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.supplier_product import propose_products
    return propose_products(context, action_input, reading)


def register_representative_processors(registry: ActionRegistry) -> ActionRegistry:
    registry.register_processor('SUPPLIER-A12', 'supplier.original_goods_continuation.v1', supplier_a12)
    registry.register_processor('CONTRACTOR-A12', 'contractor.original_business_continuation.v1', contractor_a12)
    registry.register_processor('GOV-A12', 'government.observed_feedback_proposals.v1', gov_a12)
    registry.register_processor('QS-A12', 'qs.immutable_forecast_experience.v1', qs_a12,
        candidate_fields={'update_judgment': ('revision.changes.selected_value_ref',)})
    registry.register_processor('QS-A11', 'qs.original_service_handover.v1', qs_a11)
    registry.register_processor('QS-A09', 'qs.original_final_account.v1', qs_a09)
    registry.register_processor('ENGINEER-A12', 'engineer.experience_qualification_evidence.v1', engineer_a12,
        candidate_fields={'update_judgment': ('revision.changes.selected_value_ref',)})
    registry.register_processor('ENGINEER-A11', 'engineer.original_professional_transition.v1', engineer_a11)
    registry.register_processor('ARCHITECT-A12', 'architect.private_feedback_learning.v1', architect_a12,
        candidate_fields={'update_judgment': ('revision.changes.selected_value_ref',)})
    registry.register_processor('ARCHITECT-A11', 'architect.original_service_transition.v1', architect_a11)
    registry.register_processor('ARCHITECT-A10', 'architect.external_service_billing.v1', architect_a10)
    registry.register_processor('ARCHITECT-A09', 'architect.scoped_design_change.v1', architect_a09)
    registry.register_processor('ARCHITECT-A08', 'architect.scoped_review_response.v1', architect_a08)
    registry.register_processor('ARCHITECT-A07', 'architect.deliverable_submission.v1', architect_a07)
    registry.register_processor('ARCHITECT-A06', 'architect.scoped_interface_integration.v1', architect_a06)
    registry.register_processor('ARCHITECT-A05', 'architect.finite_design_compilation.v1', architect_a05,
        candidate_collection_fields={'compare': ('comparison.recommended_option_refs',)})
    registry.register_processor('ARCHITECT-A04', 'architect.task_planning.v1', architect_a04)
    registry.register_processor('BANK-A09', 'bank.debt_accounting.v1', bank_a09)
    registry.register_processor('BANK-A10', 'bank.original_debt_resolution.v1', bank_a10)
    registry.register_processor('BANK-A11', 'bank.partial_finance_closeout.v1', bank_a11)
    registry.register_processor('BANK-A12', 'bank.private_verified_lessons.v1', bank_a12,
        candidate_fields={'revise_strategy': ('strategy_ref',)})
    registry.register_processor('BANK-A08', 'bank.covenant_monitoring.v1', bank_a08)
    registry.register_processor('BANK-A07', 'bank.funding_execution.v1', bank_a07)
    registry.register_processor('BANK-A06', 'bank.batch_draw_decision.v1', bank_a06)
    registry.register_processor('OWN-A11', 'owner.contract_management.v1', owner_a11)
    registry.register_processor('OWN-A12', 'owner.scoped_acceptance_settlement.v1', owner_a12)
    registry.register_processor('OWN-A13', 'owner.scoped_continuation.v1', owner_a13)
    registry.register_processor('OWN-A14', 'owner.actual_asset_receipt.v1', owner_a14)
    registry.register_processor('OWN-A15', 'owner.private_operating_proposals.v1', owner_a15,
        candidate_fields={'revise_preferences': ('preference_profile_ref',)})
    registry.register_processor('OWN-A08', 'owner.regulatory_applications.v1', owner_a08,
        candidate_fields={choice: ('authority_ref',) for choice in ('submit', 'supplement', 'request_review')})
    registry.register_processor('OWN-A07', 'owner.design_choices.v1', owner_a07,
        candidate_fields={'choose_option': ('option_ref',)})
    registry.register_processor('OWN-A06', 'owner.cash_instructions.v1', owner_a06)
    registry.register_processor('SUPPLIER-A13', 'supplier.finite_supply_advice.v1', supplier_a13)
    registry.register_processor('CONTRACTOR-A13', 'contractor.finite_constructability_advice.v1', contractor_a13)
    registry.register_processor('CONTRACTOR-A04', 'contractor.contract_acceptance.v1', contractor_a04,
        candidate_fields={'accept': ('offer_ref',)})
    registry.register_processor('CONTRACTOR-A05', 'contractor.work_supply_planning.v1', contractor_a05,
        candidate_fields={'accept_supply_offer': ('offer_ref',)})
    registry.register_processor('CONTRACTOR-A06', 'contractor.task_readiness.v1', contractor_a06)
    registry.register_processor('CONTRACTOR-A07', 'contractor.scoped_work_inputs.v1', contractor_a07)
    registry.register_processor('CONTRACTOR-A08', 'contractor.visible_quality_remedy.v1', contractor_a08)
    registry.register_processor('CONTRACTOR-A09', 'contractor.scoped_change_claim.v1', contractor_a09)
    registry.register_processor('CONTRACTOR-A10', 'contractor.measurement_own_cash.v1', contractor_a10)
    registry.register_processor('CONTRACTOR-A11', 'contractor.actual_closeout.v1', contractor_a11)
    registry.register_processor('CONTRACTOR-A03', 'contractor.bid_amendment.v1', contractor_a03)
    registry.register_processor('CONTRACTOR-A02', 'contractor.priced_bid_plan.v1', contractor_a02)
    registry.register_processor("CONTRACTOR-A01", "contractor.participation.v2", contractor_a01,
        candidate_fields={choice: ("package_ref",) for choice in ("participate", "clarify", "decline")})
    registry.register_processor("BANK-A02", "bank.application_intake.v2", bank_a02,
        candidate_fields={"accept_for_review": ("product_ref",)})
    registry.register_processor("BANK-A03", "bank.credit_review.v1", bank_a03)
    registry.register_processor("BANK-A04", "bank.quotation.v1", bank_a04,
        candidate_fields={choice: ('terms.pricing_ref',) for choice in ('offer', 'conditional_offer')})
    registry.register_processor('BANK-A05', 'bank.arrangement_confirmation.v1', bank_a05,
        candidate_fields={'confirm': ('offer_ref',)})
    registry.register_processor('BANK-A01', 'bank.portfolio_strategy.v1', bank_a01,
        candidate_fields={'revise_strategy': ('strategy_ref',)})
    registry.register_processor('BANK-A13', 'bank.indicative_advice.v1', bank_a13)
    registry.register_processor("OWN-A01", "owner.opportunity_observation.v2", owner_a01,
        candidate_fields={"follow": ("target",), "revise_case": ("case_ref",),
                          "create_case": ("source_refs",), "propose": ("source_refs",)})
    registry.register_processor("OWN-A16", "owner.private_proposal.v1", owner_a16,
        candidate_fields={choice: ("briefs.purpose_ref",) for choice in ("propose", "revise")})
    registry.register_processor("OWN-A02", "owner.limited_study.v1", owner_a02,
        candidate_fields={"commission": ("offer_ref",), "narrow": ("prior_study_ref",)})
    registry.register_processor("OWN-A03", "owner.investment_decision.v1", owner_a03,
        candidate_fields={choice: ("option_ref",) for choice in ("authorize_preparation", "invest")})
    registry.register_processor("OWN-A04", "owner.professional_commission.v1", owner_a04,
        candidate_fields={"accept": ("offer_ref",)})
    registry.register_processor("OWN-A05", "owner.financing_plan.v1", owner_a05,
        candidate_fields={choice: ("offer_ref",) for choice in ('accept_offer', 'negotiate')})
    registry.register_processor('OWN-A09', 'owner.tender_round_decision.v1', owner_a09,
        candidate_fields={'negotiate': ('bid_ref',)},
        candidate_collection_fields={'evaluate': ('ranked_bid_refs',)})
    registry.register_processor('OWN-A10', 'owner.award_acceptance.v1', owner_a10,
        candidate_fields={'accept': ('offer_ref',)})
    registry.register_processor('ARCHITECT-A01', 'architect.opportunity_preparation.v1', architect_a01)
    registry.register_processor("ARCHITECT-A02", "architect.service_intake.v3", architect_a02,
        candidate_fields={"accept": ("accepted_terms_ref",), "counteroffer": ("offer.proposed_terms_ref",)})
    registry.register_processor('ARCHITECT-A03', 'architect.appointment_confirmation.v1', architect_a03)
    registry.register_processor('ARCHITECT-A13', 'architect.finite_research_comparison.v1', architect_a13,
        candidate_fields={'compare': ('comparison.recommended_option_refs',)})
    registry.register_processor('ENGINEER-A01', 'engineer.opportunity_preparation.v1', engineer_a01)
    registry.register_processor("ENGINEER-A02", "engineer.service_intake.v2", engineer_a02,
        candidate_fields={"accept": ("terms_ref",), "counteroffer": ("offer.proposed_terms_ref",)})
    registry.register_processor('ENGINEER-A03', 'engineer.appointment_confirmation.v1', engineer_a03)
    registry.register_processor('ENGINEER-A04', 'engineer.professional_task_planning.v1', engineer_a04)
    registry.register_processor('ENGINEER-A05', 'engineer.finite_professional_design.v1', engineer_a05)
    registry.register_processor('ENGINEER-A06', 'engineer.scoped_professional_review.v1', engineer_a06)
    registry.register_processor('ENGINEER-A07', 'engineer.professional_publication.v1', engineer_a07)
    registry.register_processor('ENGINEER-A08', 'engineer.site_inspection_support.v1', engineer_a08)
    registry.register_processor('ENGINEER-A09', 'engineer.professional_remedy_revision.v1', engineer_a09)
    registry.register_processor('ENGINEER-A10', 'engineer.external_service_billing.v1', engineer_a10)
    registry.register_processor('ENGINEER-A13', 'engineer.finite_research_assessment.v1', engineer_a13)
    registry.register_processor('QS-A01', 'qs.market_source_decision.v1', qs_a01,
        candidate_fields={'track': ('opportunity_ref',), 'register_source': ('source_refs',)})
    registry.register_processor("QS-A02", "qs.service_intake.v2", qs_a02,
        candidate_fields={"accept": ("terms_ref",), "counteroffer": ("offer.proposed_terms_ref",)})
    registry.register_processor('QS-A03', 'qs.appointment_task_plan.v1', qs_a03)
    registry.register_processor('QS-A04', 'qs.cost_plan.v1', qs_a04)
    registry.register_processor('QS-A05', 'qs.procurement_document.v1', qs_a05)
    registry.register_processor('QS-A06', 'qs.bid_cost_evaluation.v1', qs_a06,
        candidate_fields={'exclude_authorized': ('bid_ref',)})
    registry.register_processor('QS-A07', 'qs.change_valuation.v1', qs_a07)
    registry.register_processor('QS-A08', 'qs.payment_verification.v1', qs_a08)
    registry.register_processor('QS-A10', 'qs.external_service_billing.v1', qs_a10)
    registry.register_processor('QS-A13', 'qs.preliminary_cost_comparison.v1', qs_a13,
        candidate_collection_fields={choice: ('comparison.ranked_option_refs',)
            for choice in ('compare', 'deliver_at_limit')})
    registry.register_processor('GOV-A01', 'government.preliminary_consultation.v1', gov_a01)
    registry.register_processor("GOV-A02", "government.submission_intake.v2", gov_a02)
    registry.register_processor('GOV-A03', 'government.lawful_review_scheduling.v1', gov_a03)
    registry.register_processor('GOV-A04', 'government.scoped_evidence_review.v1', gov_a04)
    registry.register_processor('GOV-A05', 'government.consultation_participation.v1', gov_a05)
    registry.register_processor('GOV-A06', 'government.supplement_response.v1', gov_a06)
    registry.register_processor('GOV-A07', 'government.authorized_decision.v1', gov_a07)
    registry.register_processor('GOV-A08', 'government.scoped_permit_conditions.v1', gov_a08)
    registry.register_processor('GOV-A09', 'government.authorized_transition.v1', gov_a09)
    registry.register_processor('GOV-A10', 'government.scoped_inspection.v1', gov_a10)
    registry.register_processor('GOV-A11', 'government.current_use_review.v1', gov_a11)
    registry.register_processor("SUPPLIER-A01", "supplier.demand_screening.v2", supplier_a01,
        candidate_fields={"respond": ("inquiry_ref",), "limited_scope": ("inquiry_ref",),
                          "clarify": ("inquiry_ref",), "track_market": ("market_refs",)})
    registry.register_processor("SUPPLIER-A02", "supplier.product_proposal.v1", supplier_a02,
        candidate_fields={choice: ("lines.product_ref",) for choice in ("propose_original", "propose_substitute")})
    registry.register_processor("SUPPLIER-A03", "supplier.quote.v1", supplier_a03,
        candidate_fields={"quote": ("offer.lines.product.product_ref",)})
    registry.register_processor("SUPPLIER-A04", "supplier.order_acceptance.v1", supplier_a04,
        candidate_fields={choice: ("offer_ref",) for choice in ("accept", "accept_partial")})
    registry.register_processor('SUPPLIER-A05', 'supplier.sourced_supply_planning.v1', supplier_a05,
        candidate_fields={'accept_upstream_offer': ('offer_ref',)})
    registry.register_processor('SUPPLIER-A06', 'supplier.actual_supply_execution.v1', supplier_a06)
    registry.register_processor('SUPPLIER-A07', 'supplier.visible_batch_quality.v1', supplier_a07)
    registry.register_processor('SUPPLIER-A08', 'supplier.physical_transport_planning.v1', supplier_a08,
        candidate_fields={'dispatch': ('plans.route_ref',), 'split': ('plans.route_ref',),
            'reroute': ('replacement_route_ref',)})
    registry.register_processor('SUPPLIER-A09', 'supplier.independent_receiving_response.v1', supplier_a09)
    registry.register_processor('SUPPLIER-A10', 'supplier.contract_claim_own_cash.v1', supplier_a10)
    registry.register_processor('SUPPLIER-A11', 'supplier.scoped_supply_remedy.v1', supplier_a11)
    return registry


def supplier_a03(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
        ("inquiry_ref", "inventory_ref", "capacity_ref", "pricing_profile_ref")]
    for field in ("product_proposal_refs", "cost_basis_refs", "logistics_refs"):
        if getattr(action_input, field):
            required.append((field, getattr(action_input, field)))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.supplier_quote import form_quote
    return form_quote(context, action_input, reading)


def supplier_a04(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
        ("order_proposal_ref", "offer_ref", "inventory_ref", "capacity_ref", "funding_ref", "formation_profile_ref")]
    if action_input.counterpart_acceptance_refs:
        required.append(("counterpart_acceptance_refs", action_input.counterpart_acceptance_refs))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.supplier_order import accept_order
    return accept_order(context, action_input, reading)


def supplier_a05(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_planning import plan_supply
    return plan_supply(context, action_input, reading)


def supplier_a06(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_execution import request_supply_execution
    return request_supply_execution(context, action_input, reading)


def supplier_a07(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_quality import request_batch_quality
    return request_batch_quality(context, action_input, reading)


def supplier_a08(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_logistics import arrange_transport
    return arrange_transport(context, action_input, reading)


def supplier_a09(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_receiving import respond_to_receiving
    return respond_to_receiving(context, action_input, reading)


def supplier_a10(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_payment import manage_supplier_cash
    return manage_supplier_cash(context, action_input, reading)


def supplier_a11(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_remedy import propose_supply_remedy
    return propose_supply_remedy(context, action_input, reading)


def owner_a16(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ("case_ref", "objective_ref", "candidate_space_ref", "funding_ref")]
    for name in ("demand_refs", "internal_need_refs"):
        if getattr(action_input, name):
            required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.owner_proposal import form_proposals
    return form_proposals(context, action_input, reading)


def owner_a02(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ("case_ref", "study_profile_ref")]
    for name in ("brief_ref", "issue_refs", "service_candidates"):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.owner_study import authorize_study
    return authorize_study(context, action_input, reading)


def owner_a03(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
        ("case_ref", "comparison_ref", "objective_ref", "portfolio_ref", "registration_profile_ref")]
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(["business_projections"], _refs(action_input))
    from src.actions.roles.owner_investment import decide_investment
    return decide_investment(context, action_input, reading)


def owner_a04(context, action_input, registration=None, reading=None):
    required = [(name,getattr(action_input,name)) for name in
        ('scope_ref','procurement_profile_ref','service_scope_ref','authority_ref','capacity_ref')]
    for name in ('candidate_provider_refs','candidates'):
        if getattr(action_input,name):
            required.append((name,getattr(action_input,name)))
    missing,requested = _missing_visible(context,required)
    if missing:
        return _needs(missing,requested)
    if reading is None:
        return _needs(['business_projections'],_refs(action_input))
    from src.actions.roles.owner_commission import commission_services
    return commission_services(context,action_input,reading)


def owner_a10(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('round_ref', 'selected_offer_ref', 'final_terms_ref', 'authority_ref', 'commitment_snapshot_ref')]
    if action_input.party_acceptance_refs:
        required.append(('party_acceptance_refs', action_input.party_acceptance_refs))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_award import decide_award
    return decide_award(context, action_input, reading)


def owner_a09(context, action_input, registration=None, reading=None):
    required = [('package_context', action_input.package_context),
                ('evaluation_profile_ref', action_input.evaluation_profile_ref), ('funding_ref', action_input.funding_ref)]
    for name in ('round_refs', 'bidder_refs', 'bid_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_tender import organize_tender
    return organize_tender(context, action_input, reading)


def owner_a05(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope_ref', 'funding_profile_ref')]
    missing, requested = _missing_visible(context, required)
    if missing:
        return _needs(missing, requested)
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.owner_financing import plan_financing
    return plan_financing(context, action_input, reading)


def bank_a03(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_credit import review_credit
    return review_credit(context, action_input, reading)


def bank_a04(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_quote import quote_finance
    return quote_finance(context, action_input, reading)


def bank_a05(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_arrangement import form_arrangement
    return form_arrangement(context, action_input, reading)


def bank_a01(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_strategy import manage_strategy
    return manage_strategy(context, action_input, reading)


def bank_a13(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.bank_advice import advise_financing
    return advise_financing(context, action_input, reading)


def architect_a13(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('brief_ref', 'research_authority_ref', 'task_ref', 'design_profile_ref',
                 'expenditure_limit_ref', 'comparison_scope_ref')]
    for name in ('available_option_refs', 'professional_refs', 'cost_refs', 'comparison_method_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_research import compare_preliminary_options
    return compare_preliminary_options(context, action_input, reading)


def engineer_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'strategy_ref')]
    for name in ('qualification_refs', 'feedback_refs', 'learning_profile_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_learning import maintain_engineering_experience
    return maintain_engineering_experience(context, action_input, reading)


def engineer_a11(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'engagement_ref', 'transition_basis_ref')]
    for name in ('task_refs', 'allocation_refs', 'deliverable_refs', 'residual_obligation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_transition import transition_engineering_service
    return transition_engineering_service(context, action_input, reading)


def architect_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'strategy_ref', 'capability_ref')]
    for name in ('feedback_refs', 'learning_profile_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_learning import update_architect_experience
    return update_architect_experience(context, action_input, reading)


def architect_a11(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'engagement_ref', 'transition_basis_ref')]
    for name in ('task_refs', 'allocation_refs', 'usable_deliverable_refs', 'residual_obligation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_transition import transition_service
    return transition_service(context, action_input, reading)


def architect_a10(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'engagement_ref', 'billing_clause_ref')]
    for name in ('work_fact_refs', 'calculation_ref', 'prior_claim_ref', 'receipt_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_billing import handle_service_fees
    return handle_service_fees(context, action_input, reading)


def architect_a09(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'issue_ref', 'used_deliverable_ref', 'obligation_ref')]
    for name in ('instruction_ref', 'impact_method_ref', 'impact_result_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_change import support_design_change
    return support_design_change(context, action_input, reading)


def architect_a08(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'target_ref', 'review_request_ref')]
    for name in ('check_result_refs', 'comment_refs', 'independence_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_review import review_architecture
    return review_architecture(context, action_input, reading)


def architect_a07(context, action_input, registration=None, reading=None):
    if getattr(action_input, 'task_completion_ref', None) is None:
        return _needs(['input.task_completion_ref'])
    required = [(name, getattr(action_input, name)) for name in ('scope', 'deliverable_ref', 'task_completion_ref')]
    for name in ('dependency_refs', 'review_requirement_ref', 'release_basis_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_submission import submit_deliverable
    return submit_deliverable(context, action_input, reading)


def architect_a06(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'option_ref')]
    for name in ('professional_refs', 'cost_refs', 'supply_refs', 'integration_authority_ref', 'open_issue_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_integration import integrate_interfaces
    return integrate_interfaces(context, action_input, reading)


def architect_a05(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'brief_ref', 'task_ref', 'design_profile_ref')]
    for name in ('basis_refs', 'prior_option_ref', 'method_result_refs', 'available_option_refs',
                 'professional_refs', 'cost_refs', 'comparison_scope_ref', 'comparison_method_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_design import compile_design
    return compile_design(context, action_input, reading)


def architect_a04(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'work_profile_ref', 'capacity_ref')]
    for name in ('task_refs', 'dependency_refs', 'existing_allocation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_planning import plan_design_work
    return plan_design_work(context, action_input, reading)


def architect_a03(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.architect_appointment import confirm_appointment
    return confirm_appointment(context, action_input, reading)


def engineer_a13(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in
                ('brief_ref', 'research_authority_ref', 'task_ref', 'expenditure_limit_ref')]
    for name in ('option_refs', 'check_spec_refs', 'evidence_refs', 'available_assessment_refs', 'method_result_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_research import assess_preliminary_options
    return assess_preliminary_options(context, action_input, reading)


def engineer_a03(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_appointment import confirm_engineer_appointment
    return confirm_engineer_appointment(context, action_input, reading)


def engineer_a04(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'work_profile_ref', 'capacity_ref')]
    for name in ('task_refs', 'dependency_refs', 'existing_allocation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_planning import plan_professional_work
    return plan_professional_work(context, action_input, reading)


def engineer_a05(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'brief_ref', 'task_ref', 'engineering_profile_ref')]
    for name in ('evidence_refs', 'method_result_refs', 'prior_option_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_design import compile_professional_design
    return compile_professional_design(context, action_input, reading)


def engineer_a06(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'target_ref', 'review_request_ref')]
    for name in ('check_spec_refs', 'method_result_refs', 'independence_check_ref', 'interface_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_review import assess_professional_work
    return assess_professional_work(context, action_input, reading)


def engineer_a07(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'deliverable_ref', 'task_completion_ref')]
    for name in ('signing_basis_refs', 'release_basis_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_submission import submit_professional_deliverable
    return submit_professional_deliverable(context, action_input, reading)


def engineer_a08(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'inspection_task_ref', 'applicable_design_ref', 'observation_method_ref')]
    for name in ('access_ref', 'observation_refs', 'query_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_inspection import inspect_and_support
    return inspect_and_support(context, action_input, reading)


def engineer_a09(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'issue_ref', 'obligation_ref', 'prior_deliverable_ref')]
    for name in ('instruction_ref', 'evidence_refs', 'method_result_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_change import handle_professional_change
    return handle_professional_change(context, action_input, reading)


def engineer_a10(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'engagement_ref', 'billing_clause_ref')]
    for name in ('work_fact_refs', 'calculation_ref', 'prior_claim_ref', 'receipt_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.engineer_billing import handle_engineering_fees
    return handle_engineering_fees(context, action_input, reading)


def qs_a01(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_market import identify_market
    return identify_market(context, action_input, reading)


def qs_a03(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_appointment import confirm_qs_appointment
    return confirm_qs_appointment(context, action_input, reading)


def qs_a04(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_cost import compile_cost_plan
    return compile_cost_plan(context, action_input, reading)


def qs_a05(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_procurement import prepare_procurement
    return prepare_procurement(context, action_input, reading)


def qs_a06(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_bid import evaluate_bids
    return evaluate_bids(context, action_input, reading)


def qs_a07(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_change import value_change
    return value_change(context, action_input, reading, registration.contract if registration else None)


def qs_a08(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_payment import verify_payment
    return verify_payment(context, action_input, reading, registration.contract if registration else None)


def qs_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'strategy_ref')]
    for name in ('forecast_refs', 'outcome_refs', 'feedback_refs', 'comparability_result_ref', 'learning_profile_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_learning import learn_qs_cost_experience
    return learn_qs_cost_experience(context, action_input, reading)


def qs_a11(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'engagement_ref', 'transition_basis_ref')]
    for name in ('task_refs', 'allocation_refs', 'deliverable_refs', 'residual_obligation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_transition import transition_qs_service
    return transition_qs_service(context, action_input, reading)


def qs_a09(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'contract_ref')]
    for name in ('determined_change_refs', 'certificate_refs', 'payment_receipt_refs', 'unresolved_claim_refs', 'reconciliation_result_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_final_account import prepare_final_account
    return prepare_final_account(context, action_input, reading)


def qs_a10(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_billing import handle_qs_fees
    return handle_qs_fees(context, action_input, reading)


def gov_a03(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_scheduling import schedule_reviews
    return schedule_reviews(context, action_input, reading)


def gov_a04(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_review import review_case
    return review_case(context, action_input, reading)


def gov_a05(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_consultation import organize_consultation
    return organize_consultation(context, action_input, reading)


def gov_a06(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_supplement import handle_supplements
    return handle_supplements(context, action_input, reading)


def gov_a07(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_decision import prepare_decision
    return prepare_decision(context, action_input, reading)


def gov_a08(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_permit import verify_permit_conditions
    return verify_permit_conditions(context, action_input, reading)


def gov_a09(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_transition import handle_decision_transition
    return handle_decision_transition(context, action_input, reading)


def gov_a10(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_inspection import inspect_and_follow_up
    return inspect_and_follow_up(context, action_input, reading)


def supplier_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope_ref', 'continuation_profile_ref', 'authority_basis_refs')]
    for name in ('work_in_progress_refs', 'inventory_refs', 'shipment_refs', 'commitment_refs', 'obligation_refs', 'observation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.supplier_continuation import continue_supplier_business
    return continue_supplier_business(context, action_input, reading)


def contractor_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope_ref', 'continuation_profile_ref', 'authority_basis_refs')]
    for name in ('resource_commitment_refs', 'material_position_refs', 'obligation_refs', 'observation_refs'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.contractor_continuation import continue_contractor_business
    return continue_contractor_business(context, action_input, reading)


def gov_a12(context, action_input, registration=None, reading=None):
    required = [(name, getattr(action_input, name)) for name in ('scope', 'observation_profile_ref', 'working_authority_ref')]
    for name in ('feedback_refs', 'visible_statistic_refs', 'policy_control_profile_ref'):
        if getattr(action_input, name): required.append((name, getattr(action_input, name)))
    missing, requested = _missing_visible(context, required)
    if missing: return _needs(missing, requested)
    if reading is None: return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_feedback import analyze_government_feedback
    return analyze_government_feedback(context, action_input, reading)


def gov_a11(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.government_use import review_use_and_supervision
    return review_use_and_supervision(context, action_input, reading)


def qs_a13(context, action_input, registration=None, reading=None):
    if reading is None:
        return _needs(['business_projections'], _refs(action_input))
    from src.actions.roles.qs_research import compare_preliminary_costs
    return compare_preliminary_costs(context, action_input, reading)
