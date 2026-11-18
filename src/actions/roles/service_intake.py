"""Common professional intake checks; role hooks only add checks, never authority."""
from decimal import Decimal
from fractions import Fraction

from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceDeliverableRequirementView,
    ServiceFeeBasisView, ServiceFeeCalculationView, ServiceIntakeCapabilityView,
    ServiceQualificationView, ServiceResourceCalendarView, ServiceResponseRequirementView,
    ServiceMethodView, ServiceRequestView, ServiceTermsView,
    ServiceWorkProfileView, ServiceCommissionAuthorityView,
)
from src.actions.contracts.common import EvidenceRecord, Known
from src.organization.registry import scope_covers


class ServiceIntakeGap(Exception):
    def __init__(self, result):
        self.result = result


def _needs(field, refs=()):
    raise ServiceIntakeGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(code):
    raise ServiceIntakeGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": code, "version": "1"}})


def known_service_value(state, field, role_key="architect"):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise ServiceIntakeGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"{role_key}-service-applicability:{field}")
    _needs(field, state.missing_refs)


def recheck_original_service_policy_wait(context, action_input, reading, *, original_processor=None, **options):
    """Authenticate a defer policy before entering eligibility or method branches."""
    pricing_ref = options.get('price_basis_ref') or getattr(action_input, 'price_basis_ref', None)
    if pricing_ref is None:
        request = reading.resolve(action_input.request_ref)
        if not isinstance(request, ServiceRequestView):
            raise ValueError('Historical service wait requires its original received request')
        pricing_ref = request.fee_basis_ref
    if pricing_ref is None:
        raise ValueError('Historical service wait requires its original fee policy')
    pricing = reading.resolve(pricing_ref)
    if (not isinstance(pricing, ServiceFeeBasisView) or not isinstance(pricing.new_work_policy, Known)
            or pricing.new_work_policy.value != 'defer'):
        raise ValueError('Historical service wait cannot evaluate a non-deferred policy')
    processor = original_processor or assess_professional_service
    result = processor(context, action_input, reading, **options)
    if result.get('kind') != 'deferred' or result.get('reason_code') != 'provider_policy_defers_new_work':
        raise ValueError('Original service sources do not reproduce their deferred policy')
    return result


def assess_professional_service(context, action_input, reading, *, role_key="architect",
                                price_basis_ref=None, accepted_field="accepted_terms_ref",
                                check_terms=None, check_fee_method=None, resource_allowed=None):
    def _known(state, field):
        return known_service_value(state, field, role_key)

    now = context.business_time
    organization_id = reading.organization_id

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported(f"{role_key}-service-clock-alignment")

    def current(window, field):
        clock(window.start)
        if not window.contains(now):
            _needs(field)

    def evidence(ref):
        value = reading.resolve(ref)
        if not isinstance(value, EvidenceRecord):
            _unsupported(f"{role_key}-service-evidence-schema")
        if value.effective_window is not None:
            current(value.effective_window, "applicable_service_evidence")

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"{role_key}-service-projection:{ref.kind}")
        for source in value.evidence_refs:
            evidence(source)
        return value

    def completed(choice, note, **extra):
        return {"kind": "completed", "payload": {
            "choice": choice, "scope": action_input.scope, "note": note, **extra}}

    def decline(reason):
        return completed("decline", reason, reason=reason)

    def within_capacity(terms):
        if terms.work_profile_ref is None:
            _needs("work_profile", [terms.ref])
        work = read(terms.work_profile_ref, ServiceWorkProfileView)
        current(work.effective_window, "current_work_profile")
        if (work.method != "constant_capacity_over_half_open_window_v1"
                or _known(terms.region_id, "service_region") not in work.region_ids
                or _known(terms.service_code, "service_code") not in work.service_codes
                or _known(terms.object_type, "service_object_type") not in work.object_types):
            _unsupported(f"{role_key}-work-profile-domain")
        if work.clock_ref != now.clock_ref or work.effective_window.bounds != "closed_open":
            _unsupported(f"{role_key}-work-profile-clock-or-bounds")
        window = _known(terms.desired_window, "desired_work_window")
        clock(window.start)
        if window.bounds != "closed_open" or window.start.offset >= window.end.offset:
            _unsupported(f"{role_key}-capacity-window-model")
        if window.start.offset < now.offset:
            _needs("future_service_work_window", [terms.ref])
        if not (work.effective_window.start.offset <= window.start.offset
                and window.end.offset <= work.effective_window.end.offset):
            return False
        effort = _known(terms.effort_estimate, "service_effort_estimate")
        evidence(effort.basis_ref)
        if effort.unit != work.effort_unit:
            _unsupported(f"{role_key}-effort-conversion")
        # Total effort / (effort per capacity per tick * window duration).
        demand = (Fraction(Decimal(effort.value)) / Fraction(Decimal(work.effort_per_capacity_tick))
                  / (window.end.offset - window.start.offset))
        resources = {row.resource_ref.key(): row for row in calendar.resources}
        allocations = []
        for item in calendar.commitments:
            resource = resources.get(item.resource_ref.key())
            if resource is None:
                raise ValueError("Commitment resource is absent or has another version in the complete calendar")
            if resource.resource_kind == work.resource_kind:
                clock(item.window.start)
                if item.window.bounds != "closed_open":
                    _unsupported(f"{role_key}-commitment-window-model")
                if item.quantity.unit != work.capacity_unit:
                    _unsupported(f"{role_key}-commitment-unit-conversion")
                evidence(item.quantity.basis_ref)
        for resource in calendar.resources:
            if resource.resource_kind != work.resource_kind:
                continue
            clock(resource.effective_window.start)
            if resource.effective_window.bounds != "closed_open":
                _unsupported(f"{role_key}-resource-window-model")
            if _known(resource.region_id, "resource_region") != _known(terms.region_id, "service_region"):
                continue
            if resource_allowed is not None and not resource_allowed(resource, terms, read, _known):
                continue
            quantity = _known(resource.total, "resource_capacity")
            evidence(quantity.basis_ref)
            if quantity.unit != work.capacity_unit:
                _unsupported(f"{role_key}-capacity-unit-conversion")
            allocations.append((resource, Fraction(Decimal(quantity.value))))
        points = {window.start.offset, window.end.offset}
        for resource, _ in allocations:
            points.update(point for point in (resource.effective_window.start.offset, resource.effective_window.end.offset)
                          if window.start.offset < point < window.end.offset)
        for item in calendar.commitments:
            if any(item.resource_ref == resource.resource_ref for resource, _ in allocations):
                points.update(point for point in (item.window.start.offset, item.window.end.offset)
                              if window.start.offset < point < window.end.offset)
        points = sorted(points)
        for start, _ in zip(points, points[1:]):
            available = Fraction()
            for resource, total in allocations:
                if not resource.effective_window.start.offset <= start < resource.effective_window.end.offset:
                    continue
                used = sum((Fraction(Decimal(item.quantity.value)) for item in calendar.commitments
                            if item.resource_ref == resource.resource_ref
                            and item.window.start.offset <= start < item.window.end.offset), Fraction())
                available += max(Fraction(), total - used)
            if demand > available:
                return False
        return True

    def validate_terms(terms):
        if (terms.request_ref != request.ref or terms.scope != request.scope
                or terms.provider_id != context.actor_id or terms.client_id != request.client_id
                or terms.payer_id != request.payer_id or terms.relation != offered.relation):
            raise ValueError("Service terms change the exact request, scope or parties")
        clock(terms.issued_at)
        if terms.issued_at.offset > now.offset:
            _needs("issued_terms_at_read_point", [terms.ref])
        current(terms.effective_window, "active_service_terms")

    def eligible_terms(terms):
        validate_terms(terms)
        if check_terms is not None:
            reason = check_terms(terms, request, capability, calendar, read, current, clock, _known)
            if reason is not None:
                return reason
        region = _known(terms.region_id, "service_region")
        service = _known(terms.service_code, "service_code")
        obj = _known(terms.object_type, "service_object_type")
        uses = _known(terms.requested_uses, "requested_service_uses")
        responsibilities = _known(terms.responsibility_codes, "service_responsibilities")
        if (service not in request.permitted_service_codes
                or service not in _known(capability.service_codes, "capability_service_codes")
                or region not in _known(capability.region_ids, "capability_regions")
                or obj not in _known(capability.object_types, "capability_object_types")
                or not set(uses) <= set(_known(capability.allowed_uses, "capability_allowed_uses"))
                or not set(responsibilities) <= set(_known(capability.responsibility_codes, "capability_responsibility_codes"))):
            return "The service exceeds the request or declared professional capability"
        for authority, entity, actor, purpose in (
            (client_authority, request.client_organization_id, request.client_id, "commission_service"),
            (payer_authority, request.payer_organization_id, request.payer_id, "authorize_payment"),
        ):
            current(authority.validity, "current_client_or_payer_authority")
            if authority.organization_id != entity or authority.actor_id != actor:
                raise ValueError("Client or payer authority identity differs from the request")
            if (purpose not in authority.purposes or service not in authority.service_codes
                    or not any(scope_covers(scope, terms.scope) for scope in authority.scopes)):
                return "The client or payer lacks applicable service authority"
        required_quals = _known(terms.required_qualification_codes, "required_qualifications")
        if capability.qualification_coverage != "complete":
            _needs(f"complete_{role_key}_qualification_coverage", [capability.ref])
        qualifications = [read(ref, ServiceQualificationView) for ref in capability.qualification_refs]
        for item in qualifications:
            if item.organization_id != organization_id:
                raise ValueError("Qualification belongs to another professional organization")
            clock(item.effective_window.start)
        for code in required_quals:
            matches = [item for item in qualifications if item.code == code and item.effective_window.contains(now)
                       and region in item.region_ids and service in item.service_codes]
            if not matches:
                return "No current declared qualification covers the requested service"
            gaps, covered = [], False
            for item in matches:
                try:
                    covered |= _known(item.standing, "qualification_standing")
                except ServiceIntakeGap as gap:
                    gaps.append(gap)
            if not covered:
                if gaps:
                    raise gaps[0]
                return "A required qualification is not in good standing"
        methods = _known(terms.required_method_refs, "required_service_methods")
        if not set(methods) <= set(_known(capability.method_refs, f"{role_key}_methods")):
            _unsupported(f"{role_key}-required-service-method")
        for ref in methods:
            method = read(ref, ServiceMethodView)
            current(method.effective_window, "current_service_method")
            if (service not in method.service_codes or obj not in method.object_types
                    or region not in method.region_ids or method.purpose != "service_support"):
                _unsupported(f"{role_key}-required-service-method-domain")
        for ref in terms.deliverable_requirement_refs:
            requirement = read(ref, ServiceDeliverableRequirementView)
            if (requirement.request_ref != request.ref or requirement.scope != terms.scope
                    or requirement.requested_use not in uses):
                raise ValueError("Deliverable requirement differs from the request, scope or allowed uses")
        fee = _known(terms.fee, "service_fee")
        minimum = _known(pricing.minimum_fee, "minimum_fee")
        risk = _known(terms.payment_risk, "payment_risk")
        maximum = _known(pricing.maximum_payment_risk, "maximum_payment_risk")
        for value in (fee, minimum, risk, maximum):
            evidence(value.basis_ref)
        if fee.currency != minimum.currency:
            _unsupported(f"{role_key}-fee-currency-conversion")
        if risk.unit != maximum.unit:
            _unsupported(f"{role_key}-payment-risk-unit-conversion")
        if Decimal(fee.value) < Decimal(minimum.value):
            return "The offered fee is below the sourced minimum"
        if Decimal(risk.value) > Decimal(maximum.value):
            return "The sourced payment-risk limit is exceeded"
        if not within_capacity(terms):
            return "The requested service window exceeds declared available capacity"
        return None

    def clarification():
        questions = []
        for ref in request.open_question_refs:
            target = read(ref, ServiceClarificationTargetView)
            requirement = read(target.response_requirement_ref, ServiceResponseRequirementView)
            for item in (target, requirement):
                if item.request_ref != request.ref or item.scope != request.scope:
                    raise ValueError("Clarification differs from the exact request/scope")
            if (not set(target.recipient_ids) <= set(requirement.recipient_ids)
                    or not set(target.recipient_ids) <= {request.client_id, request.payer_id}
                    or not set(target.blocking_uses) <= set(_known(offered.requested_uses, "requested_service_uses"))):
                raise ValueError("Clarification recipients or uses exceed the request")
            questions.append({"scope": request.scope, "target_refs": [target.ref], "question": target.question,
                "recipient_ids": target.recipient_ids, "evidence_refs": target.evidence_refs,
                "blocking_uses": target.blocking_uses, "response_requirement_ref": requirement.ref})
        return completed("clarify", "Ask the request's registered blocking questions", questions=questions)

    def counteroffer():
        if not pricing.counteroffer_terms_refs or not pricing.counteroffer_calculation_refs:
            _needs("sourced_counteroffer_terms_and_calculation", [pricing.ref])
        if len(pricing.counteroffer_terms_refs) != len(pricing.counteroffer_calculation_refs):
            raise ValueError("Counteroffer terms and calculation references are not paired")
        pairs, gaps = [], []
        for terms_ref, calculation_ref in zip(pricing.counteroffer_terms_refs, pricing.counteroffer_calculation_refs):
            try:
                terms = read(terms_ref, ServiceTermsView)
                calculation = read(calculation_ref, ServiceFeeCalculationView)
                if (terms.status != "proposal" or terms.prior_terms_ref != offered.ref
                        or calculation.terms_ref != terms.ref or calculation.fee_basis_ref != pricing.ref
                        or calculation.scope != action_input.scope or calculation.organization_id != organization_id):
                    raise ValueError("Counteroffer calculation differs from the exact proposed terms or prior offer")
                if calculation.execution_status != "succeeded":
                    _needs("successful_counteroffer_calculation", [calculation.ref])
                clock(calculation.executed_at)
                if calculation.executed_at.offset > now.offset:
                    _needs("counteroffer_calculation_at_read_point", [calculation.ref])
                fee = _known(terms.fee, "counteroffer_fee")
                evidence(calculation.amount.basis_ref)
                if (calculation.amount.currency != fee.currency
                        or Decimal(calculation.amount.value) != Decimal(fee.value)):
                    raise ValueError("Counteroffer amount differs from the terms fee")
                method = read(calculation.method_ref, ServiceMethodView)
                current(method.effective_window, "current_fee_calculation_method")
                if (method.purpose != "fee_calculation"
                        or _known(terms.region_id, "service_region") not in method.region_ids
                        or _known(terms.service_code, "service_code") not in method.service_codes
                        or _known(terms.object_type, "service_object_type") not in method.object_types):
                    _unsupported(f"{role_key}-fee-calculation-method-domain")
                if check_fee_method is not None:
                    check_fee_method(method, terms, _known)
                if eligible_terms(terms) is None:
                    pairs.append((terms, calculation))
            except ServiceIntakeGap as gap:
                gaps.append(gap)
        if not pairs:
            if gaps:
                raise gaps[0]
            _needs("eligible_counteroffer_terms", pricing.counteroffer_terms_refs)
        # Higher sourced priority wins; row order never selects an alternative.
        priorities = [(_known(terms.selection_priority, "counteroffer_selection_priority"), terms, calculation)
                      for terms, calculation in pairs]
        best = max(row[0] for row in priorities)
        selected = [row for row in priorities if row[0] == best]
        if len(selected) != 1:
            _needs("unique_counteroffer_selection", [row[1].ref for row in selected])
        _, terms, calculation = selected[0]
        return completed("counteroffer", "Present sourced terms; no capacity reservation or engagement is formed",
            offer={"scope": terms.scope, "client_id": terms.client_id, "payer_id": terms.payer_id,
                "proposed_terms_ref": terms.ref, "fee_basis_ref": pricing.ref, "fee_calculation_ref": calculation.ref,
                "capacity_request": {"scope": terms.scope, "purpose": "service_delivery", "input_refs": [request.ref, offered.ref],
                    "output_requirement_refs": terms.deliverable_requirement_refs, "work_profile_ref": terms.work_profile_ref,
                    "effort_estimate": terms.effort_estimate, "desired_window": terms.desired_window,
                    "authority_basis_refs": [], "dependency_refs": [], "questions": []},
                "validity": terms.effective_window, "deliverable_requirement_refs": terms.deliverable_requirement_refs})

    try:
        request = read(action_input.request_ref, ServiceRequestView)
        offered = read(action_input.terms_ref, ServiceTermsView)
        capability = read(action_input.capability_ref, ServiceIntakeCapabilityView)
        calendar = read(action_input.capacity_ref, ServiceResourceCalendarView)
        pricing_ref = price_basis_ref
        if pricing_ref is None:
            pricing_ref = getattr(action_input, "price_basis_ref", None)
        if pricing_ref is None:
            pricing_ref = getattr(request, "fee_basis_ref", None)
        if pricing_ref is None:
            _needs("fee_basis", [request.ref])
        pricing = read(pricing_ref, ServiceFeeBasisView)
        if (request.provider_organization_id != organization_id or capability.organization_id != organization_id
                or calendar.organization_id != organization_id or pricing.organization_id != organization_id
                or request.provider_id != context.actor_id or offered.provider_id != context.actor_id):
            raise ValueError("Service projections target another provider organization or actor")
        if request.scope != action_input.scope or request.offered_terms_ref != offered.ref:
            raise ValueError("Service request scope or offered terms version differs from the invocation")
        if offered.status != "offered" or request.status != "active":
            return decline("The exact request or service terms are no longer offered")
        clock(request.received_at)
        if request.received_at.offset > now.offset:
            _needs("request_received_at_read_point", [request.ref])
        current(request.effective_window, "active_service_request")
        current(capability.effective_window, f"current_{role_key}_capability")
        current(pricing.effective_window, "current_fee_basis")
        clock(calendar.as_of)
        if calendar.as_of != now or calendar.coverage != "complete":
            _needs("complete_current_resource_calendar", [calendar.ref])
        if not scope_covers(context.scope, request.scope) or not any(
                scope_covers(scope, request.scope) for scope in request.permitted_offer_scopes):
            raise ValueError("Service request is outside the accepted offer scope")
        if not scope_covers(pricing.scope, request.scope):
            _needs("fee_basis_for_service_scope", [pricing.ref])
        validate_terms(offered)
        if offered.relation == "internal":
            if request.client_organization_id != organization_id or request.payer_organization_id != organization_id:
                raise ValueError("Internal service has an external client or payer organization")
            fee = _known(offered.fee, "internal_service_fee")
            evidence(fee.basis_ref)
            if Decimal(fee.value) != 0:
                return decline("Internal work cannot create an external self-invoice")
            _needs("internal_task_authorization", [request.ref])
        if request.client_organization_id == organization_id or request.payer_organization_id == organization_id:
            raise ValueError("External service cannot disguise an internal client or payer relationship")
        client_authority = read(request.client_authority_ref, ServiceCommissionAuthorityView)
        payer_authority = read(request.payer_authority_ref, ServiceCommissionAuthorityView)
        if request.open_question_refs:
            return clarification()
        policy = _known(pricing.new_work_policy, "new_work_policy")
        if policy == "decline":
            return decline("The sourced provider policy declines new work")
        if policy == "defer":
            return {"kind": "deferred", "reason_code": "provider_policy_defers_new_work", "resume_condition": {
                "trigger": "dependency_change", "object_refs": [offered.ref, pricing.ref], "earliest_time": None,
                "condition_code": "service_terms_or_provider_policy_reassessed"}}
        reason = eligible_terms(offered)
        if reason is not None:
            if pricing.counteroffer_terms_refs:
                return counteroffer()
            return decline(reason)
        return completed("accept", "The exact offered terms, authority, qualifications, fees and current capacity are eligible",
                         **{accepted_field: offered.ref})
    except ServiceIntakeGap as gap:
        return gap.result
