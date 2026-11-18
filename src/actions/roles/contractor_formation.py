"""CONTRACTOR-A04 independent acceptance with current cash/crew checks."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentBidView, ContractorAmendmentSubmissionView
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidPackageView, ContractorBidReferenceView, ContractorBidProgrammeView,
    ContractorBidCapacityView, ContractorBidResourceView, ContractorBidCommitmentView,
    ContractorBidCostView, ContractorBidQuantityView,
)
from src.actions.contracts.contractor_formation_objects import (
    ContractorFormationOfferView, ContractorFormationTermsView, ContractorFormationProfileView,
    ContractorFormationAcceptanceView, ContractorFormationReferenceView, ContractorFormationRequirementView,
    ContractorFormationFundingView, ContractorFormationCashSourceView, ContractorFormationCashPaymentView,
    ContractorFormationCashPlanView, ContractorFormationContractPaymentView, ContractorFormationCashComponentView,
    contractor_agreement_digest,
)
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.owner_investment import CASH_METHOD, CashCalendarInput
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_contract(context, action_input, reading):
    now, sources = context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('contractor-formation-clock-alignment')

    def evidence(ref, historical=False, *, at=None):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset: _needs('received_original_contract_evidence_time', [ref])
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord): _unsupported('contractor-formation-evidence-schema')
        if row.effective_window is not None:
            clock(row.effective_window.start)
            if row.effective_window.start.offset > now.offset: _needs('received_original_contract_evidence', [ref])
            if (at is not None or not historical) and not row.effective_window.contains(point):
                _needs('original_contract_evidence_valid_at_use', [ref])
        sources[ref.key()] = ref

    def read(ref, schema, historical=False, covered=True, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'contractor-formation-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Contract input changes original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset: _needs('received_original_contract_input', [ref])
            if not historical and not row.effective_window.contains(now): _needs('current_original_contract_input', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > now.offset: _needs('received_original_contract_evidence_time', [ref])
            if point.offset > row.available_at.offset:
                raise ValueError('Contract source receipt precedes its original decision')
        for ref_ in getattr(row, 'evidence_refs', []): evidence(ref_, historical, at=point)
        sources[ref.key()] = ref; return row

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def authority(ref, actor, function_ref, organization, action, roles, at=now, *, target_scope=None):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.function_ref != function_ref or function.role not in roles or action not in grant.action_ids
                or not any(scope_covers(scope, target_scope or context.scope) for scope in grant.scopes)):
            raise ValueError('Contract decision lacks independent original party/actor/scope authority')
        clock(grant.validity.start); clock(at)
        if at.offset > now.offset: _needs('received_original_contract_author_time', [ref])
        if not grant.validity.contains(at): _needs('valid_original_contract_authority', [ref])
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence(basis_ref, at=at)
            else:
                reading.resolve(basis_ref); sources[basis_ref.key()] = basis_ref

    def bound(row):
        if not same(row.offer_ref, offer.ref) or not same(row.terms_ref, terms.ref) or not same(row.bid_ref, bid.ref):
            raise ValueError('Contract clause/condition/change belongs to another bid agreement')

    def contract_reference(ref):
        row = read(ref, ContractorFormationReferenceView); bound(row)
        if not _known(row.allowed, 'original_contract_reference_permission'):
            _needs('original_contract_reference_permission', [ref])
        return row

    def window(ref):
        row = read(ref, TimeWindow); clock(row.start); return row

    def method_value(result, capability):
        if result.kind == 'ok': return result.value
        if result.kind == 'invalid_input': _unsupported(capability)
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information': raw['requested_refs'] = []
        raise ObservationGap(raw)

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def check_funding():
        funding = read(action_input.funding_ref, ContractorFormationFundingView, covered=False)
        clock(funding.as_of)
        if funding.organization_id != reading.organization_id: raise ValueError('Funding belongs to another organization')
        if funding.as_of != now or funding.coverage != 'complete': _needs('complete_current_cross_project_funding_position')
        if profile.cash_plan_ref is None: _needs('original_complete_contract_working_capital_plan')
        plan = read(profile.cash_plan_ref, ContractorFormationCashPlanView)
        if (plan.organization_id != reading.organization_id or not same(plan.offer_ref, offer.ref)
                or not same(plan.terms_ref, terms.ref)):
            raise ValueError('Working capital plan changes the original final contract')
        if plan.coverage != 'complete' or not plan.proposed_outflow_refs:
            _needs('complete_original_contract_cost_and_payment_calendar')
        if keys(plan.cost_basis_refs) != keys(bid.draft.cost_basis_refs):
            _needs('all_selected_bid_costs_in_final_cash_plan')
        accounts = []; account_keys = keys(funding.source_refs)
        if not funding.source_refs: _needs('actual_original_contractor_funding_sources')
        for ref in funding.source_refs:
            source = read(ref, ContractorFormationCashSourceView, covered=False); clock(source.as_of)
            if source.organization_id != reading.organization_id: raise ValueError('Funding source changes organization')
            if source.as_of != now or source.coverage != 'complete': _needs('complete_current_actual_cash_and_restrictions')
            if offer.ref.key() not in keys(source.allowed_offer_refs): _needs('original_cash_use_permission_for_contract', [ref])
            evidence(source.permission_basis_ref)
            actual = _known(source.actual_cash, 'actual_original_contract_cash')
            restricted = _known(source.restricted_cash, 'actual_original_cash_restrictions')
            for amount in (actual, restricted): evidence(amount.basis_ref)
            if actual.currency != terms.price.currency or restricted.currency != actual.currency:
                _unsupported('contractor-formation-cash-currency-conversion')
            free = decimal_fraction(actual.value) - decimal_fraction(restricted.value)
            if free < 0 or decimal_fraction(restricted.value) < 0: raise ValueError('Original cash restriction exceeds actual balance')
            accounts.append({'source_ref': ref, 'opening_available': {'value': exact_decimal(free),
                             'currency': actual.currency, 'basis_ref': source.permission_basis_ref}})
        groups = [(funding.existing_payment_refs, 'existing', 'outflow'), (funding.inflow_refs, 'existing', 'inflow'),
                  (plan.proposed_outflow_refs, 'proposed', 'outflow'), (plan.proposed_inflow_refs, 'proposed', 'inflow')]
        keys([ref for refs, _, _ in groups for ref in refs])
        inflows, existing, proposed = [], [], []
        seen_components, mapped_payments, cost_amounts = set(), set(), {}
        contract_payments = {}; keys(terms.payment_refs)
        for ref in terms.payment_refs:
            row = read(ref, ContractorFormationContractPaymentView); clock(row.time)
            if (not same(row.offer_ref, offer.ref) or not same(row.terms_ref, terms.ref)
                    or row.payer_id != offer.client_id or row.payee_id != offer.contractor_id):
                raise ValueError('Contract payment changes original parties or final terms')
            amount = _known(row.amount, 'original_final_contract_payment'); evidence(amount.basis_ref)
            if amount.currency != terms.price.currency: _unsupported('contractor-formation-contract-payment-currency')
            if decimal_fraction(amount.value) <= 0: raise ValueError('Contract payment must be positive')
            contract_payments[ref.key()] = (row, amount)
        if sum((decimal_fraction(amount.value) for _, amount in contract_payments.values()), Fraction()) != decimal_fraction(terms.price.value):
            _needs('complete_original_contract_price_payment_schedule')
        for refs, group, direction in groups:
            for ref in refs:
                row = read(ref, ContractorFormationCashPaymentView, covered=group == 'proposed'); clock(row.time)
                if (row.organization_id != reading.organization_id or row.source_ref.key() not in account_keys
                        or row.direction != direction):
                    raise ValueError('Cash calendar changes original account, organization or payment direction')
                if group == 'proposed' and (row.offer_ref is None or row.terms_ref is None
                        or not same(row.offer_ref, offer.ref) or not same(row.terms_ref, terms.ref)):
                    raise ValueError('Proposed cash flow belongs to another final contract')
                evidence(row.disposition_basis_ref)
                amount = _known(row.amount, 'original_cash_flow_amount'); evidence(amount.basis_ref)
                if amount.currency != terms.price.currency: _unsupported('contractor-formation-cash-flow-currency')
                value = decimal_fraction(amount.value)
                if value <= 0: raise ValueError('Original cash flow must be positive')
                component_sum = Fraction(); keys(row.component_refs)
                for component_ref in row.component_refs:
                    component_identity = (component_ref.kind, component_ref.id)
                    if component_identity in seen_components: raise ValueError('Cash plan counts one liability/receipt component twice across versions')
                    seen_components.add(component_identity)
                    component = read(component_ref, ContractorFormationCashComponentView, covered=group == 'proposed')
                    if (component.organization_id != reading.organization_id or not same(component.source_ref, row.source_ref)
                            or component.direction != direction or component.time != row.time):
                        raise ValueError('Cash flow changes the original financial component')
                    part = _known(component.amount, 'original_cash_component_amount'); evidence(part.basis_ref)
                    if part.currency != amount.currency or decimal_fraction(part.value) <= 0:
                        _unsupported('contractor-formation-cash-component-domain')
                    component_sum += decimal_fraction(part.value)
                    if group == 'proposed' and direction == 'outflow' and component.cost_basis_ref is not None:
                        if component.cost_basis_ref.key() not in keys(plan.cost_basis_refs):
                            raise ValueError('Cash expense changes selected bid cost versions')
                        cost_amounts[component.cost_basis_ref.key()] = cost_amounts.get(component.cost_basis_ref.key(), Fraction()) + decimal_fraction(part.value)
                if component_sum != value: raise ValueError('Cash amount differs from its exact original components')
                if group == 'proposed' and direction == 'inflow':
                    if row.contract_payment_ref is None or row.contract_payment_ref.key() not in contract_payments:
                        _needs('original_contract_payment_for_planned_receipt')
                    payment, payment_amount = contract_payments[row.contract_payment_ref.key()]
                    if row.contract_payment_ref.key() in mapped_payments or row.time != payment.time or amount != payment_amount:
                        raise ValueError('Cash plan duplicates or changes a final contractual payment')
                    mapped_payments.add(row.contract_payment_ref.key())
                if row.status in {'released', 'paid', 'received'}:
                    if group == 'proposed': raise ValueError('New contract plan cannot reuse a released or already settled cash flow')
                    continue
                if direction == 'inflow' and not _known(row.planning_available, 'original_receipt_planning_permission'): continue
                if direction == 'inflow' and row.time.offset < now.offset: _needs('actual_overdue_receipt_or_current_revised_receipt_time', [ref])
                at = row.time if row.time.offset >= now.offset else now
                flow = {'local_key': f'{ref.kind}:{ref.id}:{ref.version}', 'source_ref': row.source_ref, 'time': at, 'amount': amount}
                (inflows if direction == 'inflow' else proposed if group == 'proposed' else existing).append(flow)
        if mapped_payments != set(contract_payments): _needs('complete_original_contract_receipts_in_cash_plan')
        for ref in plan.cost_basis_refs:
            cost = read(ref, ContractorBidCostView, historical=True)
            quantities = read(cost.quantity_basis_ref, ContractorBidQuantityView, historical=True)
            if (cost.organization_id != reading.organization_id or not same(cost.package_ref, offer.package_ref)
                    or not same(quantities.package_ref, offer.package_ref)):
                raise ValueError('Funding cost basis changes original selected bid package')
            if cost.status == 'failed' or quantities.status == 'failed':
                raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': context.operation_id, 'code': 'original_contract_quantity_price_failed'},
                    'retryability': 'unknown'})
            if cost.status != 'ok' or quantities.status != 'ok': _unsupported('contractor-formation-original-quantity-price-method')
            lines = [line for line in quantities.lines if line.local_key == cost.quantity_line_key]
            if len(lines) != 1: raise ValueError('Funding cost has no unique original quantity line')
            rate = _known(cost.unit_rate, 'original_contract_cash_cost_rate')
            quantity = _known(lines[0].quantity, 'original_contract_cash_cost_quantity')
            for basis in (rate.basis_ref, quantity.basis_ref): evidence(basis, True)
            if rate.currency != terms.price.currency or cost.quantity_unit != quantity.unit:
                _unsupported('contractor-formation-cost-unit-currency-domain')
            if decimal_fraction(rate.value) < 0 or decimal_fraction(quantity.value) <= 0:
                raise ValueError('Contract cash cost requires nonnegative rates and positive original quantities')
            if cost_amounts.get(ref.key(), Fraction()) < decimal_fraction(rate.value) * decimal_fraction(quantity.value):
                _needs('cash_plan_covers_all_original_selected_bid_costs')
        result = reading.calculate(CASH_METHOD, CashCalendarInput(clock_ref=now.clock_ref, as_of=now,
            accounts=accounts, inflows=inflows, existing_outflows=existing, proposed_outflows=proposed,
            source_refs=list(sources.values())))
        if not method_value(result, 'contractor-formation-cash-calendar-domain').feasible:
            _needs('original_contract_cash_shortfall_requires_explicit_revision_or_rejection')

    try:
        offer = read(action_input.offer_ref, ContractorFormationOfferView)
        terms = read(action_input.terms_ref, ContractorFormationTermsView)
        profile = read(action_input.formation_profile_ref, ContractorFormationProfileView)
        bid = read(offer.bid_ref, ContractorAmendmentBidView, historical=True)
        if (offer.contractor_id != reading.organization_id or offer.client_id == reading.organization_id
                or bid.organization_id != reading.organization_id or not same(offer.package_ref, bid.draft.package_ref)
                or not same(offer.round_ref, bid.round_ref) or not same(offer.terms_ref, terms.ref)
                or not same(terms.offer_ref, offer.ref) or not same(terms.bid_ref, bid.ref)
                or not same(terms.package_ref, offer.package_ref) or not same(terms.round_ref, offer.round_ref)
                or terms.contractor_id != offer.contractor_id or terms.client_id != offer.client_id
                or profile.organization_id != reading.organization_id or not same(profile.offer_ref, offer.ref)
                or not same(profile.terms_ref, terms.ref) or not same(profile.authority_ref, action_input.authority_ref)):
            raise ValueError('Final offer, terms, original bid and independent decision versions disagree')
        authority(action_input.authority_ref, context.actor_id, context.function_ref, reading.organization_id,
                  'CONTRACTOR-A04', {'Contractor'}, target_scope=terms.scope)
        authority(offer.author_authority_ref, offer.author_actor_id, offer.author_function_ref, offer.client_id,
                  offer.author_action_id, {'Owner'}, offer.available_at, target_scope=offer.scope)
        if profile.choice == 'reject': return completed('reject')
        if profile.choice == 'revise':
            if not profile.requirement_changes: _needs('original_explicit_contract_revision_requests')
            keys(profile.requirement_changes)
            for ref in profile.requirement_changes: contract_reference(ref)
            return completed('revise', requirement_changes=profile.requirement_changes)
        if not _known(profile.explicit_acceptance, 'original_explicit_contractor_acceptance'):
            _needs('contractor_choice_accept_conflicts_with_explicit_acceptance')
        if offer.status != 'active' or not window(offer.response_window_ref).contains(now):
            _needs('current_original_contract_offer_and_response_window', [offer.ref])
        package = read(offer.package_ref, ContractorBidPackageView)
        if package.status == 'superseded' or not same(package.round_ref, offer.round_ref):
            _needs('original_unsuperseded_bid_package_and_round')
        tender_round = read(offer.round_ref, ContractorBidReferenceView)
        if not same(tender_round.package_ref, package.ref) or not _known(tender_round.allowed, 'current_original_bid_round'):
            _needs('current_original_bid_round', [offer.round_ref])
        execution = read(bid.submission_ref, ContractorAmendmentSubmissionView)
        if (execution.organization_id != reading.organization_id or not same(execution.bid_ref, bid.ref)
                or not same(execution.package_ref, package.ref) or not same(execution.round_ref, offer.round_ref)):
            raise ValueError('Selected contract does not preserve the original submission identity')
        evidence(execution.result_basis_ref)
        if execution.status in {'unknown', 'pending'}:
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'selected_bid_submission_reconciliation_required',
                    'resume_condition': {'trigger': 'event', 'object_refs': [execution.ref, bid.ref], 'earliest_time': None,
                                         'condition_code': f'query_original_command:{execution.command_id}'}}
        if execution.status == 'failed':
            reading.recheck()
            return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': execution.command_id,
                    'code': 'selected_bid_submission_failed'}, 'retryability': 'unknown'}
        if execution.status != 'accepted': _needs('original_effective_selected_bid_submission')
        if (len(set(terms.required_party_ids)) != len(terms.required_party_ids)
                or not {offer.client_id, offer.contractor_id} <= set(terms.required_party_ids)):
            raise ValueError('Final contract omits or duplicates actual legal parties')
        if profile.reviewed_agreement_sha256 != contractor_agreement_digest(terms):
            _needs('independent_review_of_exact_final_agreement')
        if keys(profile.reviewed_clause_refs) != keys(terms.clause_refs): _needs('all_original_payment_design_time_and_risk_clauses_reviewed')
        for ref in terms.clause_refs: contract_reference(ref)
        contract_reference(terms.contract_template_ref)
        evidence(terms.price.basis_ref)
        if terms.price.currency != bid.draft.price.currency: _unsupported('contractor-formation-currency-conversion')
        if decimal_fraction(terms.price.value) <= 0: raise ValueError('Contract price must be positive')
        price_changed = decimal_fraction(terms.price.value) != decimal_fraction(bid.draft.price.value)
        changes = set(); keys(terms.amendment_refs)
        for ref in terms.amendment_refs: changes.update(contract_reference(ref).changed_field_codes)
        if changes != ({'price'} if price_changed else set()): _needs('explicit_original_final_price_amendment')
        if (not same(terms.programme_ref, bid.draft.programme_ref)
                or keys(terms.exclusion_refs) != keys(bid.draft.exclusion_refs)
                or keys(terms.deliverable_refs) != keys(package.deliverable_refs)
                or terms.scope != bid.draft.scope_ref):
            _needs('complete_revised_bid_for_changed_scope_design_or_programme')
        excluded = set()
        for ref in terms.exclusion_refs:
            row = read(ref, ContractorBidReferenceView)
            if not same(row.package_ref, package.ref): raise ValueError('Contract exclusion belongs to another package')
            excluded.update(row.excluded_coverage_keys)
        if len(set(terms.scope_keys)) != len(terms.scope_keys) or set(terms.scope_keys) != set(package.coverage_keys) - excluded:
            _needs('exact_original_included_contract_scope')
        keys(terms.condition_refs)
        for ref in terms.condition_refs:
            row = read(ref, ContractorFormationRequirementView)
            if row.formation is None: _needs('original_contract_condition_stage', [ref])
            bound(row.formation)
            if not same(row.package_ref, package.ref): raise ValueError('Contract condition changes original package')
            if not _known(row.allowed, 'original_contract_condition_permission'): _needs('original_contract_condition_permission', [ref])
            if row.formation.stage == 'acceptance' and not _known(row.formation.satisfied, 'original_acceptance_gate'):
                _needs('original_acceptance_gate', [ref])
        # Missing counterpart acceptances leave formation pending; they never impersonate this contractor's consent.
        keys(action_input.counterpart_acceptance_refs); accepted_parties = set()
        for ref in action_input.counterpart_acceptance_refs:
            row = read(ref, ContractorFormationAcceptanceView, historical=True, evidence_at_field='decided_at')
            if row.run_id != context.run_id or row.party_id == reading.organization_id or row.party_id not in terms.required_party_ids:
                raise ValueError('Counterpart acceptance belongs to another run or legal party')
            clock(row.decided_at)
            if row.decided_at.offset > row.available_at.offset: raise ValueError('Acceptance receipt precedes actual decision')
            if (row.status != 'active' or not row.effective_window.contains(now) or not same(row.offer_ref, offer.ref)
                    or not same(row.terms_ref, terms.ref) or not same(row.bid_ref, bid.ref)
                    or row.agreement_sha256 != contractor_agreement_digest(terms) or row.scope != terms.scope): continue
            role = read(row.author_function_ref, RoleAssignment).role
            allowed = {'Owner': {'OWN-A10'}, 'Contractor': {'CONTRACTOR-A04'}, 'Supplier': {'SUPPLIER-A04'}}
            if row.author_action_id not in allowed.get(role, set()): raise ValueError('Counterpart has no original independent signing action')
            if row.party_id == offer.client_id and role != 'Owner': raise ValueError('Client acceptance has another legal role')
            authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.party_id,
                      row.author_action_id, {role}, row.decided_at, target_scope=row.scope)
            if row.party_id in accepted_parties: raise ValueError('One party has multiple active agreement decisions')
            accepted_parties.add(row.party_id)
            if row.choice != 'accept': _needs('counterpart_revision_or_rejection_of_final_terms', [ref])
            if not _known(row.explicit_acceptance, 'original_explicit_counterpart_acceptance'):
                _needs('counterpart_accept_choice_conflicts_with_explicit_result', [ref])
        capacity = read(action_input.capacity_ref, ContractorBidCapacityView, covered=False)
        clock(capacity.as_of)
        if capacity.organization_id != reading.organization_id: raise ValueError('Contract capacity belongs to another organization')
        if capacity.as_of != now or capacity.coverage != 'complete' or capacity.qualification_coverage != 'complete':
            _needs('complete_current_cross_project_contractor_capacity_and_qualifications')
        qualified = set(); keys(capacity.qualification_refs)
        for ref in capacity.qualification_refs:
            row = read(ref, QualificationView, covered=False); clock(row.effective_window.start)
            if row.organization_ref.id != reading.organization_id: raise ValueError('Contract qualification changes organization')
            if (row.effective_window.contains(now) and _known(row.standing, 'current_contract_qualification')
                    and package.region_id in row.region_ids and package.work_type in row.work_types): qualified.add(row.qualification_code)
        if not set(package.required_qualification_codes) <= qualified: _needs('actual_current_region_and_work_qualifications')
        programme = read(terms.programme_ref, ContractorBidProgrammeView, historical=True)
        if programme.organization_id != reading.organization_id or not same(programme.package_ref, package.ref):
            raise ValueError('Final contract programme changes original bid organization/package')
        authority(programme.author_authority_ref, programme.author_actor_id, programme.author_function_ref,
                  reading.organization_id, 'CONTRACTOR-A02', {'Contractor'}, programme.available_at,
                  target_scope=programme.scope)
        allocations = [a for task in programme.tasks for a in task.allocations]
        if not allocations or allocations != bid.draft.proposed_resources: _needs('exact_selected_bid_programme_allocations')
        resources = {row.resource_ref.key(): row for row in capacity.resources}
        keys([row.resource_ref for row in capacity.resources]); keys([row.commitment_ref for row in capacity.commitments])
        for resource in capacity.resources:
            row = read(resource.resource_ref, ContractorBidResourceView, covered=False)
            if (row.organization_id != reading.organization_id or row.total != resource.total
                    or row.region_id != resource.region_id or row.resource_kind != resource.resource_kind
                    or row.effective_window != resource.effective_window):
                raise ValueError('Capacity snapshot changes a real resource or physical total')
            evidence(resource.total.basis_ref)
        for use in capacity.commitments:
            row = read(use.commitment_ref, ContractorBidCommitmentView, covered=False)
            if (row.organization_id != reading.organization_id or not same(row.resource_ref, use.resource_ref)
                    or row.quantity != use.quantity or row.window != use.window or use.resource_ref.key() not in resources):
                raise ValueError('Capacity snapshot changes original cross-project resource occupancy')
            evidence(use.quantity.basis_ref)
        demands = {}; clock(terms.work_window.start)
        if terms.work_window.start.offset < now.offset: _needs('current_or_future_original_contract_work_window')
        for allocation in allocations:
            resource = resources.get(allocation.resource_ref.key())
            if resource is None: _needs('actual_current_bid_resource_version', [allocation.resource_ref])
            w = window(allocation.window_ref); evidence(allocation.quantity.basis_ref)
            if (not scope_covers(terms.scope, allocation.task_scope_ref) or resource.region_id != package.region_id
                    or w.start.offset < max(now.offset, terms.work_window.start.offset) or w.end.offset > terms.work_window.end.offset):
                _needs('current_original_resource_scope_location_and_contract_window')
            if allocation.quantity.unit != resource.total.unit: _unsupported('contractor-formation-resource-unit-conversion')
            amount = decimal_fraction(allocation.quantity.value)
            if amount <= 0: raise ValueError('Contract resource amount must be positive')
            demands.setdefault(resource.resource_ref.key(), []).append({'resource_kind': resource.resource_kind,
                'region_id': resource.region_id, 'unit': allocation.quantity.unit, 'amount': ExactAmount.from_fraction(amount),
                'window': w, 'basis_refs': [allocation.quantity.basis_ref]})
        for key, selected in demands.items():
            result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, demands=selected,
                resources=[resources[key]], commitments=[row for row in capacity.commitments if row.resource_ref.key() == key],
                source_refs=list(sources.values())))
            if not method_value(result, 'contractor-formation-capacity-domain').feasible:
                _needs('shared_crew_conflict_requires_explicit_revision_or_rejection')
        check_funding()
        # Programme allocations are ContractorBidAllocation records. The A04
        # result contract uses ContractorAllocation; preserve every field at
        # the typed output boundary rather than returning a different model.
        return completed('accept', offer_ref=offer.ref, terms_ref=terms.ref,
                         proposed_allocations=[row.model_dump(mode='json') for row in allocations])
    except ObservationGap as gap:
        reading.recheck(); return gap.result
