"""SUPPLIER-A01: exact scoped intent screening without committing supply."""
from decimal import Decimal
from fractions import Fraction
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord, Known, Reference, ScopeRef, TimeWindow
from src.actions.contracts.supplier_objects import (
    SupplyInquiryView, SupplyMarketObservationView, SupplyRequirementView, SupplyScreeningProfileView,
    SupplyWorkMethodView, SupplierCapabilityView, SupplierCapacityView, SupplierFunctionAuthorityView,
)
from src.organization.registry import scope_covers
from src.methods.action import MethodDecisionGap, capacity_feasible
from src.methods.capacity import CapacityInput, ExactAmount
from src.actions.roles.professional_outreach import outreach_constraint


class SupplyGap(Exception):
    def __init__(self, result):
        self.result = result


@dataclass(frozen=True)
class SupplyDemand:
    scope: ScopeRef
    resource_kind: str
    region_id: str
    window: TimeWindow
    unit: str
    rate: Fraction
    method_ref: Reference
    requirement_ref: Reference
    basis_ref: Reference


def _needs(field, refs=()):
    raise SupplyGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(code):
    raise SupplyGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": code, "version": "1"}})


def _known(state, field):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise SupplyGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"supplier-screening-applicability:{field}")
    _needs(field, state.missing_refs)


def recheck_original_supplier_policy_wait(context, action_input, reading):
    """Reproduce only the original defer policy before any capacity invocation."""
    profile = reading.resolve(action_input.screening_profile_ref)
    if not isinstance(profile, SupplyScreeningProfileView) or profile.policy != 'defer_new_work':
        raise ValueError('Historical supplier policy must remain the original defer policy')
    result = screen_demand(context, action_input, reading)
    if result.get('kind') != 'deferred' or result.get('reason_code') != 'supplier_policy_deferred':
        raise ValueError('Original screening sources do not reproduce their deferred policy')
    return result


def screen_demand(context, action_input, reading):
    basis = {}

    def current(window, field, point=None):
        if window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("supplier-screening-clock-alignment")
        if not window.contains(point or context.business_time):
            _needs(field)

    def evidence(ref):
        record = reading.resolve(ref)
        if not isinstance(record, EvidenceRecord):
            _unsupported("supplier-screening-evidence-schema")
        if record.effective_window is not None:
            current(record.effective_window, "current_screening_evidence")
        basis[ref.key()] = ref

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"supplier-screening-projection:{ref.kind}")
        for source in value.evidence_refs:
            evidence(source)
        return value

    def completed(choice, note, **fields):
        if choice=='track_market' and (profile.monthly_price_policy_ref is not None or profile.monthly_price_observation_ref is not None):
            if profile.monthly_price_policy_ref is None or profile.monthly_price_observation_ref is None:
                raise ValueError('Monthly price policy and actual observations must be declared together')
            from src.actions.roles.supplier_monthly_prices import analyze_monthly_prices
            note=analyze_monthly_prices(context,action_input,reading,profile=profile,market_refs=fields['market_refs']).model_dump_json()
        return {"kind": "completed", "payload": {"choice": choice, "basis_refs": list(basis.values()),
            "note": note, **fields}}

    def capacity_fits(demands):
        if not demands:
            return False
        if capacity.resource_coverage != "complete" or capacity.commitment_coverage != "complete":
            _needs("complete_resource_and_commitment_coverage", [capacity.ref])
        resources = {item.resource_ref.key(): item for item in capacity.resources}

        def interval(window):
            if window.start.clock_ref != context.business_time.clock_ref or window.bounds != "closed_open":
                _unsupported("supplier-screening-resource-time-model")
            if window.end.offset <= window.start.offset:
                _needs("nonempty_resource_window", [capacity.ref])
            return window.start.offset, window.end.offset

        for allocation in capacity.commitments:
            if allocation.resource_ref.key() not in resources:
                _needs("commitment_resource_coverage", [allocation.resource_ref])
            interval(allocation.window)
            evidence(allocation.quantity.basis_ref)
        groups = {(item.resource_kind, item.region_id, item.unit) for item in demands}
        method_resources, method_commitments = {}, {}
        for kind, region, unit in sorted(groups):
            pool = []
            for resource in capacity.resources:
                if resource.resource_kind != kind:
                    continue
                if _known(resource.region_id, "resource_location") != region:
                    continue
                quantity = _known(resource.total, "resource_capacity")
                if quantity.unit != unit:
                    _unsupported("supplier-screening-resource-unit-conversion")
                evidence(quantity.basis_ref)
                interval(resource.effective_window)
                pool.append(resource)
                method_resources[resource.resource_ref.key()] = {"resource_ref": resource.resource_ref,
                    "resource_kind": resource.resource_kind, "region_id": region,
                    "total": quantity, "effective_window": resource.effective_window}
            allocations = [item for item in capacity.commitments
                           if item.resource_ref.key() in {resource.resource_ref.key() for resource in pool}]
            if any(item.quantity.unit != unit for item in allocations):
                _unsupported("supplier-screening-commitment-unit-conversion")
            for allocation in allocations:
                method_commitments[allocation.commitment_ref.key()] = allocation.model_dump(mode="python")
        sources = {ref.key(): ref for ref in [capability.ref, capacity.ref, profile.ref, *action_input.inquiry_refs,
                   *[item.method_ref for item in demands], *[item.requirement_ref for item in demands]]}
        data = CapacityInput(clock_ref=context.business_time.clock_ref,
            demands=[{"resource_kind": item.resource_kind, "region_id": item.region_id, "unit": item.unit,
                      "amount": ExactAmount.from_fraction(item.rate), "window": item.window, "basis_refs": [item.basis_ref]}
                     for item in demands], resources=list(method_resources.values()),
            commitments=list(method_commitments.values()), source_refs=list(sources.values()))
        try:
            return capacity_feasible(reading, data)
        except MethodDecisionGap as gap:
            raise SupplyGap(gap.result) from gap

    def line_demand(line, inquiry):
        requirement = read(line.requirement_ref, SupplyRequirementView)
        if requirement.inquiry_ref != inquiry.ref or requirement.scope != line.scope:
            raise ValueError("Supply requirement differs from the exact inquiry line and scope")
        product = _known(line.product_code, "inquiry_product")
        quantity = _known(line.quantity, "inquiry_quantity")
        evidence(quantity.basis_ref)
        production = _known(line.production_region_id, "production_region")
        delivery = _known(line.delivery_region_id, "delivery_region")
        window = _known(line.work_window, "supply_work_window")
        if window.start.clock_ref != context.business_time.clock_ref or window.bounds != "closed_open":
            _unsupported("supplier-screening-resource-time-model")
        if window.start.offset < context.business_time.offset:
            _needs("future_supply_work_window", [inquiry.ref])
        if window.end.offset <= window.start.offset:
            raise ValueError("Supply work window must be nonempty")
        functions = _known(line.required_function_codes, "supply_functions")
        modes = _known(line.allowed_fulfillment_modes, "fulfillment_modes")
        if not functions or not modes:
            _needs("nonempty_functions_and_fulfillment_modes", [line.requirement_ref])
        support = next((item for item in capability.products if item.product_code == product), None)
        if support is None:
            if capability.product_coverage != "complete":
                _needs("complete_product_capability", [capability.ref])
            return None
        if (not set(functions) <= set(_known(support.function_codes, "supported_functions"))
                or production not in _known(capability.operating_region_ids, "supplier_operating_regions")
                or production not in _known(support.production_region_ids, "supported_production_regions")
                or delivery not in _known(support.delivery_region_ids, "supported_delivery_regions")):
            return None
        for function in set(functions) - {"supply"}:
            authorities = [read(ref, SupplierFunctionAuthorityView) for ref in capability.function_authority_refs]
            if any(item.organization_id != reading.organization_id or item.actor_id != context.actor_id for item in authorities):
                raise ValueError("Extended supply function authority belongs to another organization or actor")
            if not any(function in item.function_codes and scope_covers(item.scope, line.scope)
                       and item.effective_window.start.clock_ref == context.business_time.clock_ref
                       and item.effective_window.contains(context.business_time)
                       and item.effective_window.start.offset <= window.start.offset
                       and item.effective_window.end.offset >= window.end.offset
                       and item.effective_window.bounds == "closed_open" for item in authorities):
                _needs("authorized_extended_supply_function", capability.function_authority_refs)
        method = read(support.method_ref, SupplyWorkMethodView)
        if method.organization_id != reading.organization_id or method.product_code != product:
            raise ValueError("Supply method differs from the exact organization or product")
        current(method.effective_window, "current_supply_method")
        if (method.fulfillment_mode not in modes or method.production_region_id != production
                or delivery not in method.delivery_region_ids or not set(functions) <= set(method.function_codes)):
            return None
        if quantity.unit != method.quantity_unit:
            _unsupported("supplier-screening-product-unit-conversion")
        if (method.effective_window.bounds != "closed_open"
                or method.effective_window.start.offset > window.start.offset
                or method.effective_window.end.offset < window.end.offset):
            _needs("method_for_entire_supply_window", [method.ref])
        rate = Fraction(Decimal(quantity.value)) / Fraction(Decimal(method.units_per_capacity_tick))
        rate /= window.end.offset - window.start.offset
        return SupplyDemand(line.scope, method.resource_kind, production, window, method.capacity_unit, rate,
                            method.ref, requirement.ref, quantity.basis_ref)

    def validate_inquiry(inquiry):
        if inquiry.recipient_id != context.actor_id or inquiry.recipient_organization_id != reading.organization_id:
            raise ValueError("Inquiry is addressed to another supplier")
        if context.scope.kind != "organization" and not scope_covers(context.scope, inquiry.scope):
            raise ValueError("Inquiry exceeds the invocation business scope")
        if inquiry.received_at.clock_ref != context.business_time.clock_ref:
            _unsupported("supplier-screening-clock-alignment")
        if inquiry.received_at.offset > context.business_time.offset:
            _needs("received_inquiry_at_current_read_point", [inquiry.ref])
        if inquiry.response_window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("supplier-screening-clock-alignment")
        if not inquiry.response_window.contains(context.business_time):
            _needs("current_inquiry_response_window", [inquiry.ref])

    def assess(inquiry):
        if inquiry.status == "withdrawn":
            return None
        if inquiry.clarification_requirement_refs:
            for ref in inquiry.clarification_requirement_refs:
                requirement = read(ref, SupplyRequirementView)
                if requirement.inquiry_ref != inquiry.ref or not scope_covers(inquiry.scope, requirement.scope):
                    raise ValueError("Clarification requirement differs from the exact received inquiry")
            return ("clarify", {"inquiry_ref": inquiry.ref, "requirement_refs": inquiry.clarification_requirement_refs})
        selected, demands, gaps = [], [], []
        for line in inquiry.lines:
            try:
                demand = line_demand(line, inquiry)
                if demand is not None:
                    selected.append(line.scope)
                    demands.append(demand)
            except SupplyGap as gap:
                gaps.append(gap.result)
        # Unknown lines cannot be silently removed from a purported full response.
        if gaps:
            raise SupplyGap(gaps[0])
        if not demands:
            return None
        combined_fits = capacity_fits(demands)
        if len(selected) == len(inquiry.lines) and combined_fits:
            return ("respond", {"inquiry_ref": inquiry.ref, "offered_scope_refs": selected})
        if not profile.allow_limited_scope or not inquiry.allow_partial_scope:
            return None
        if combined_fits:
            return ("limited_scope", {"inquiry_ref": inquiry.ref, "offered_scope_refs": selected})
        # Scope is indivisible. Avoid an arbitrary greedy choice when multiple
        # valid subsets compete for the same capacity; request an explicit policy.
        feasible = [index for index, demand in enumerate(demands) if capacity_fits([demand])]
        if len(feasible) == 1:
            return ("limited_scope", {"inquiry_ref": inquiry.ref, "offered_scope_refs": [selected[feasible[0]]]})
        if feasible:
            _needs("unambiguous_limited_supply_scope", [inquiry.ref])
        return None

    try:
        capability = read(action_input.capability_ref, SupplierCapabilityView)
        capacity = read(action_input.capacity_ref, SupplierCapacityView)
        profile = read(action_input.screening_profile_ref, SupplyScreeningProfileView)
        if any(item.organization_id != reading.organization_id for item in (capability, capacity, profile)):
            raise ValueError("Supplier screening facts belong to different organizations")
        if context.scope.kind == "organization" and context.scope.ref.id != reading.organization_id:
            raise ValueError("Supplier organization scope differs from the actor organization")
        current(capability.effective_window, "current_supplier_capability")
        current(profile.effective_window, "current_supplier_profile")
        _known(capability.registration_region_id, "supplier_registration_region")
        if capacity.as_of != context.business_time:
            _needs("current_supplier_capacity", [capacity.ref])
        markets = [read(ref, SupplyMarketObservationView) for ref in action_input.market_refs]
        for market in markets:
            for point in (market.observed_at, market.available_at):
                if point.clock_ref != context.business_time.clock_ref:
                    _unsupported("supplier-screening-clock-alignment")
                if point.offset > context.business_time.offset:
                    _needs("market_observation_at_current_read_point", [market.ref])
            if market.observed_at.offset > market.available_at.offset:
                raise ValueError("Market observation is available before it occurred")
        if not action_input.inquiry_refs:
            if not markets:
                _needs("inquiry_or_visible_market_observation")
            return completed("track_market", "Track received observations only; forecasts create no order, stock or capacity allocation",
                             market_refs=[item.ref for item in markets])
        inquiries = [read(ref, SupplyInquiryView) for ref in action_input.inquiry_refs]
        if len({(item.ref.kind, item.ref.id) for item in inquiries}) != len(inquiries):
            raise ValueError("Inquiry identity repeated across versions")
        for inquiry in inquiries:
            validate_inquiry(inquiry)
        if profile.policy == "decline_new_work":
            return completed("decline", "The sourced supplier policy declines the exact received input inquiry set")
        if profile.policy == "defer_new_work":
            return {"kind": "deferred", "reason_code": "supplier_policy_deferred", "resume_condition": {"trigger": "dependency_change",
                "object_refs": [profile.ref], "earliest_time": None, "condition_code": "supplier_policy_revision"}}
        priorities = {item.inquiry_ref.key(): item.priority for item in profile.inquiry_priorities}
        choices, gaps = [], []
        for inquiry in inquiries:
            try:
                assessed = assess(inquiry)
                if assessed is not None:
                    if len(inquiries) == 1:
                        choices.append((0, assessed))
                    else:
                        if inquiry.ref.key() not in priorities:
                            _needs("inquiry_selection_priority", [inquiry.ref])
                        choices.append((_known(priorities[inquiry.ref.key()], "inquiry_selection_priority"), assessed))
            except SupplyGap as gap:
                gaps.append(gap.result)
        if gaps:
            raise SupplyGap(gaps[0])
        if not choices:
            return completed("decline", "No exact received inquiry has a supported and feasible supply scope")
        first = min(priority for priority, _ in choices)
        preferred = [choice for priority, choice in choices if priority == first]
        if len(preferred) != 1:
            _needs("unambiguous_inquiry_selection", [item.ref for item in inquiries])
        choice, fields = preferred[0]
        if choice in {'respond', 'limited_scope'}:
            constraint = outreach_constraint(context, reading, profile.outreach_limits)
            if constraint is not None and not constraint[0]:
                return completed('decline', constraint[1])
        return completed(choice, "Sourced product, function, geography and shared-capacity facts support this intent only", **fields)
    except SupplyGap as gap:
        return gap.result
