"""OWN-A11 scoped owner proposals, with no unilateral price or payment effects."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.owner_contract_objects import (
    OwnerContractView, OwnerContractDecisionView, OwnerContractTermsView, OwnerContractRuleView,
    OwnerContractIssueView, OwnerContractEvidenceView, OwnerContractRecordView, OwnerContractAssessmentView,
    OwnerContractRequirementView, OwnerContractChangeView, OwnerContractAcceptanceView, OwnerContractClaimView,
    OwnerContractFundingView, OwnerContractCashSourceView, OwnerContractReservationView, OwnerContractReferenceView,
    contract_change_digest,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def manage_contract(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-contract-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-contract-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now): _needs('current_original_contract_management_evidence', [ref])

    def read(ref, schema, scope=None, covered=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-contract-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, scope or context.scope):
            raise ValueError('Contract decision input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset or not row.effective_window.contains(now):
                _needs('received_current_original_contract_management_input', [ref])
        evidence(getattr(row, 'evidence_refs', [])); return row

    def authorize(ref, actor, function_ref, organization, action, roles, scope=None):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.role not in roles or action not in grant.action_ids
                or not any(scope_covers(s, scope or context.scope) for s in grant.scopes)):
            raise ValueError('Contract decision lacks independent original actor/party/action/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_contract_management_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs])

    def bound(row):
        if not same(row.contract_ref, contract.ref) or not same(row.terms_ref, original_terms.ref):
            raise ValueError('Contract source changes the original effective contract/terms version')

    def authored(row, roles, scope=None):
        bound(row)
        role = read(row.author_function_ref, RoleAssignment).role
        prefixes = {'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-', 'Architect': 'ARCHITECT-',
                    'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-'}
        if role not in roles or not row.author_action_id.startswith(prefixes.get(role, '!')):
            raise ValueError('Contract source action does not match its independent role')
        authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                  row.author_organization_id, row.author_action_id, roles, scope)
        return role

    def committed(refs, scope=None):
        if not keys(refs) <= keys(action_input.evidence_refs): _needs('received_original_committed_contract_evidence', refs)
        for ref in refs:
            source = read(ref, OwnerContractEvidenceView, scope)
            if not same(source.contract_ref, contract.ref): raise ValueError('Committed evidence belongs to another contract')
            record = read(source.original_record_ref, OwnerContractRecordView, scope)
            authored(record, {'Owner', 'Contractor', 'Supplier', 'Architect', 'Engineer', 'QS', 'Government'}, scope)
            if record.status == 'failed': raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                'correlation_id': context.operation_id, 'code': 'original_committed_contract_record_failed'}, 'retryability': 'unknown'})
            if record.status != 'recorded': _needs('actual_original_committed_contract_record', [source.original_record_ref])
            if source.content_sha256 != record.content_sha256: raise ValueError('Committed evidence changes the original recorded content digest')
            evidence(source.original_evidence_refs)

    def assessment(ref, target, scope=None):
        if ref.key() not in keys(action_input.assessment_refs): _needs('received_original_independent_contract_assessment', [ref])
        row = read(ref, OwnerContractAssessmentView, scope)
        authored(row, {'Architect', 'Engineer', 'QS', 'Government'}, scope)
        if not same(row.target_ref, target): raise ValueError('Professional assessment covers another original change/claim/requirement')
        if not row.committed_evidence_refs: _needs('original_recorded_basis_for_professional_contract_assessment')
        committed(row.committed_evidence_refs, scope)
        if row.status == 'failed': raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': 'original_contract_assessment_failed'}, 'retryability': 'unknown'})
        if row.status != 'ok': _unsupported('owner-contract-professional-assessment-method')
        return row

    def acknowledge(refs, scope=None):
        if not keys(refs) <= keys(action_input.issue_refs) or not keys(refs) <= keys(profile.acknowledged_issue_refs):
            _needs('all_original_affected_contract_issues_acknowledged', refs)
        for ref in refs:
            row = read(ref, OwnerContractIssueView, scope)
            authored(row, {'Owner', 'Contractor', 'Supplier', 'Architect', 'Engineer', 'QS', 'Government'}, scope)
            if row.status == 'resolved':
                if row.resolution_basis_ref is None: _needs('original_contract_issue_resolution_basis')
                evidence([row.resolution_basis_ref])

    def money(state, field):
        amount = _known(state, field); evidence([amount.basis_ref])
        if decimal_fraction(amount.value) < 0: raise ValueError('Original expenditure/claim amount cannot be negative')
        return amount

    def fund(demands):
        if not demands: return
        funding = read(action_input.funding_ref, OwnerContractFundingView, covered=False); clock(funding.as_of)
        if funding.organization_id != owner: raise ValueError('Contract management funding belongs to another organization')
        if funding.as_of != now or funding.coverage != 'complete': _needs('complete_current_cross_project_contract_management_cash')
        source_keys = keys(funding.source_refs)
        for key, (source_ref, need, currency) in demands.items():
            if key not in source_keys: _needs('original_permitted_funding_source_for_affected_scope')
            source = read(source_ref, OwnerContractCashSourceView, covered=False); clock(source.as_of)
            if source.organization_id != owner or contract.ref.key() not in keys(source.permitted_contract_refs):
                raise ValueError('Contract work expenditure leaves original account purpose/organization')
            if source.as_of != now or source.coverage != 'complete': _needs('current_actual_cash_and_restrictions_for_contract_work')
            cash = money(source.actual_cash, 'actual_contract_work_cash'); restricted = money(source.restricted_cash, 'actual_contract_work_restrictions')
            if cash.currency != currency or restricted.currency != currency: _unsupported('owner-contract-cash-currency-domain')
            held = Fraction(); keys(source.reservation_refs)
            for ref in source.reservation_refs:
                reservation = read(ref, OwnerContractReservationView, covered=False); clock(reservation.as_of)
                if reservation.organization_id != owner or not same(reservation.source_ref, source.ref): raise ValueError('Reservation changes real funding account')
                if reservation.as_of != now: _needs('all_current_cross_project_cash_reservations')
                evidence([reservation.disposition_basis_ref, reservation.amount.basis_ref])
                if reservation.amount.currency != currency or decimal_fraction(reservation.amount.value) < 0: _unsupported('owner-contract-reservation-currency-domain')
                if reservation.status == 'held': held += decimal_fraction(reservation.amount.value)
            if decimal_fraction(cash.value) - decimal_fraction(restricted.value) - held < need:
                _needs('affected_scope_cash_shortfall_preserves_other_work_and_existing_debts')

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    try:
        contract = read(action_input.contract_ref, OwnerContractView)
        if contract.owner_id != owner: raise ValueError('Contract management belongs to another owner')
        if contract.status == 'pending': _needs('already_formed_original_contract')
        original_terms = read(contract.terms_ref, OwnerContractTermsView)
        if (not same(original_terms.contract_ref, contract.ref) or original_terms.owner_id != owner
                or original_terms.contractor_id != contract.contractor_id or original_terms.status != 'effective'):
            _needs('original_current_effective_contract_terms')
        profile = read(contract.decision_profile_ref, OwnerContractDecisionView)
        if profile.organization_id != owner or not same(profile.contract_ref, contract.ref) or not same(profile.authority_ref, action_input.authority_ref):
            raise ValueError('Owner contract choice changes original contract/authority')
        authorize(action_input.authority_ref, context.actor_id, context.function_ref, owner, 'OWN-A11', {'Owner'})
        rule = read(contract.change_rule_ref, OwnerContractRuleView)
        if not same(rule.contract_ref, contract.ref) or not same(rule.terms_ref, original_terms.ref): raise ValueError('Contract management rule uses another original terms version')
        if profile.choice not in rule.permitted_choices: _needs('original_contract_permission_for_owner_action')
        if profile.choice in {'instruct', 'verify', 'remedy'}:
            scope = profile.scope_choice
            if not scope_covers(context.scope, scope.scope_ref) or not scope.basis_refs or not profile.requested_requirement_refs:
                _needs('explicit_affected_work_scope_basis_and_requested_requirements')
            evidence(scope.basis_refs); keys(profile.requested_requirement_refs); keys(scope.condition_refs)
            demands = {}
            for ref in list({r.key(): r for r in [*scope.condition_refs, *profile.requested_requirement_refs]}.values()):
                req = read(ref, OwnerContractRequirementView, scope.scope_ref)
                roles = {'regulatory': {'Government'}, 'professional': {'Architect', 'Engineer', 'QS'},
                         'funding': {'Owner', 'QS'}, 'rights': {'Owner', 'Government'},
                         'other': {'Owner', 'Architect', 'Engineer', 'QS'}}
                authored(req, roles[req.condition_kind], scope.scope_ref)
                if profile.choice not in req.permitted_choices or not _known(req.permitted, 'original_scoped_owner_instruction_permission'):
                    _needs('original_scoped_owner_instruction_permission', [ref])
                if profile.choice != 'verify' and not _known(req.satisfied, 'original_affected_work_dependency'):
                    _needs('original_affected_work_dependency', [ref])
                for assessment_ref in req.assessment_refs:
                    evaluated = assessment(assessment_ref, req.ref, scope.scope_ref)
                    if profile.choice != 'verify' and not _known(evaluated.accepted, 'independent_scope_instruction_assessment'):
                        _needs('independent_scope_instruction_assessment')
                if req.requires_expenditure:
                    amount = money(req.expenditure_cap, 'original_incremental_scoped_instruction_budget')
                    if req.funding_source_ref is None: _needs('original_instruction_funding_source')
                    key = req.funding_source_ref.key()
                    old = demands.get(key, (req.funding_source_ref, Fraction(), amount.currency))
                    if old[2] != amount.currency: _unsupported('owner-instruction-budget-currency-domain')
                    demands[key] = (req.funding_source_ref, old[1] + decimal_fraction(amount.value), amount.currency)
            fund(demands)
            return completed(profile.choice, scope=scope.model_dump(mode='python'), requested_requirement_refs=profile.requested_requirement_refs)
        if profile.choice == 'agree_change':
            if contract.status != 'effective': _needs('effective_contract_for_new_pending_change')
            if profile.change_ref is None or profile.terms_ref is None: _needs('original_complete_change_and_replacement_terms')
            change = read(profile.change_ref, OwnerContractChangeView)
            authored(change, {'Owner', 'Contractor', 'Architect', 'Engineer', 'QS'})
            if change.status != 'proposed' or change.basis_kind == 'cost_overrun_only': _needs('original_contractual_change_basis_not_cost_overrun')
            if not same(change.replacement_terms_ref, profile.terms_ref): raise ValueError('Owner change selects another replacement terms version')
            acknowledge(change.issue_refs)
            for ref in change.issue_refs:
                issue = read(ref, OwnerContractIssueView)
                if change.ref.key() not in keys(issue.change_refs): raise ValueError('Change is absent from its original issue attribution')
            if not change.basis_evidence_refs: _needs('original_recorded_contractual_change_basis')
            committed(change.basis_evidence_refs)
            codes = set(); keys(change.assessment_refs)
            for ref in change.assessment_refs:
                assessed = assessment(ref, change.ref)
                if not _known(assessed.accepted, 'independent_original_contract_change_assessment'): _needs('independent_original_contract_change_assessment')
                if assessed.assessment_code in codes: raise ValueError('Change repeats one required assessment code')
                codes.add(assessed.assessment_code)
            if not set(rule.required_change_assessment_codes) <= codes: _needs('all_original_price_time_scope_change_assessments')
            replacement = read(profile.terms_ref, OwnerContractTermsView)
            if (not same(replacement.contract_ref, contract.ref) or replacement.owner_id != owner
                    or replacement.contractor_id != contract.contractor_id or replacement.prior_terms_ref is None
                    or not same(replacement.prior_terms_ref, original_terms.ref) or replacement.change_ref is None
                    or not same(replacement.change_ref, change.ref) or replacement.status != 'proposed'):
                raise ValueError('Pending change does not retain original contract/party/prior terms')
            if not keys(original_terms.retained_obligation_refs) <= keys(replacement.retained_obligation_refs):
                _needs('existing_effective_obligations_retained_in_pending_contract_change')
            for terms in (original_terms, replacement):
                if not terms.scope_keys or len(set(terms.scope_keys)) != len(terms.scope_keys) or not terms.clause_refs:
                    _needs('explicit_original_scope_and_clauses_for_complete_contract_terms')
                evidence([terms.price.basis_ref]); w = read(terms.work_window_ref, TimeWindow); clock(w.start)
                for ref in terms.clause_refs:
                    clause = read(ref, OwnerContractReferenceView)
                    if not same(clause.contract_ref, contract.ref) or not same(clause.terms_ref, terms.ref): raise ValueError('Change clause belongs to another terms version')
                    if not _known(clause.permitted, 'original_contract_clause_use'): _needs('original_contract_clause_use')
            if replacement.price.currency != original_terms.price.currency: _unsupported('owner-contract-change-price-currency-domain')
            if decimal_fraction(replacement.price.value) <= 0: raise ValueError('Replacement price must be positive')
            incremental = money(change.incremental_amount, 'original_incremental_change_budget')
            if incremental.currency != replacement.price.currency: _unsupported('owner-contract-change-budget-currency-domain')
            if decimal_fraction(incremental.value) < max(Fraction(), decimal_fraction(replacement.price.value) - decimal_fraction(original_terms.price.value)):
                _needs('original_budget_covers_pending_incremental_contract_price')
            digest = contract_change_digest(replacement)
            if profile.reviewed_terms_sha256 != digest: _needs('owner_review_of_exact_pending_replacement_terms')
            parties = set(); keys(change.acceptance_refs)
            for ref in change.acceptance_refs:
                acceptance = read(ref, OwnerContractAcceptanceView)
                authored(acceptance, {'Owner', 'Contractor'})
                if (acceptance.run_id != context.run_id or not same(acceptance.change_ref, change.ref)
                        or not same(acceptance.replacement_terms_ref, replacement.ref) or acceptance.agreement_sha256 != digest):
                    _needs('same_original_party_acceptance_for_pending_change', [ref])
                if acceptance.status != 'active': continue
                if acceptance.party_id != acceptance.author_organization_id or acceptance.party_id not in rule.required_acceptance_party_ids:
                    raise ValueError('Change acceptance belongs to another actual legal party')
                if acceptance.party_id in parties: raise ValueError('Change repeats a party decision')
                parties.add(acceptance.party_id)
                if acceptance.choice != 'accept' or not _known(acceptance.explicit_acceptance, 'independent_explicit_change_acceptance'):
                    _needs('counterparty_rejected_or_revised_change_terms')
            # Missing necessary parties leave the change pending; this is only the owner's decision.
            if decimal_fraction(incremental.value) > 0:
                if change.funding_source_ref is None: _needs('original_pending_change_funding_source')
                fund({change.funding_source_ref.key(): (change.funding_source_ref, decimal_fraction(incremental.value), incremental.currency)})
            return completed('agree_change', change_ref=change.ref, terms_ref=replacement.ref)
        if not profile.component_refs: _needs('explicit_original_claim_components_for_dispute_or_partial_acceptance')
        keys(profile.component_refs)
        if profile.choice == 'accept_undisputed' and not rule.allow_partial_undisputed: _needs('original_contract_permission_for_undisputed_partial_acceptance')
        for ref in profile.component_refs:
            component = read(ref, OwnerContractClaimView)
            authored(component, {'Contractor', 'Supplier', 'QS'})
            if component.claimant_id != contract.contractor_id:
                raise ValueError('Claim component changes the actual original contract counterparty')
            acknowledge([component.issue_ref])
            issue = read(component.issue_ref, OwnerContractIssueView)
            if component.ref.key() not in keys(issue.component_refs): raise ValueError('Selected claim component is absent from its original issue')
            committed(component.committed_evidence_refs)
            if profile.choice == 'accept_undisputed':
                if not component.committed_evidence_refs: _needs('original_recorded_entitlement_for_undisputed_component')
                if component.disputed or component.basis_kind == 'cost_overrun_only': _needs('original_undisputed_contractual_component_not_raw_cost_overrun')
                if not component.assessment_refs: _needs('independent_original_undisputed_component_assessment')
                claimed = money(component.claimed_amount, 'original_undisputed_claim_amount'); verified = []
                for assessment_ref in component.assessment_refs:
                    result = assessment(assessment_ref, component.ref)
                    if not _known(result.accepted, 'original_undisputed_component_verified'): _needs('original_undisputed_component_verified')
                    if result.approved_amount.state == 'known': verified.append(money(result.approved_amount, 'original_approved_component_amount'))
                if not verified or any(m.currency != claimed.currency or m.value != claimed.value for m in verified):
                    _needs('exact_original_professionally_assessed_undisputed_amount')
        return completed(profile.choice, component_refs=profile.component_refs)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
