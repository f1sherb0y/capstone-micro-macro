"""CONTRACTOR-A01 eligibility and declared-policy screening, without submission."""
from decimal import Decimal
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.contractor_objects import (
    CommitmentSnapshotView, ContractorCapabilityView, InvitationView,
    OpportunityScreeningProfileView, ProcurementPackageView, QualificationView,
    ScreeningRequirementView, WorkMethodSupportView,
)
from src.methods.action import MethodDecisionGap, capacity_feasible
from src.methods.capacity import CapacityInput, ExactAmount


class ScreeningGap(Exception):
    def __init__(self, result):
        self.result = result


def _needs(field, refs=()):
    raise ScreeningGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(identity):
    raise ScreeningGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": identity, "version": "1"}})


def _known(state, field):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise ScreeningGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"screening-rule-applicability:{field}")
    _needs(field, state.missing_refs)


def _covers(outer, inner):
    if outer.start.clock_ref != inner.start.clock_ref:
        _unsupported("screening-clock-alignment")
    if outer.bounds != "closed_open" or inner.bounds != "closed_open":
        _unsupported("screening-window-boundaries")
    return outer.start.offset <= inner.start.offset and outer.end.offset >= inner.end.offset


def _interval(window, clock):
    if window.start.clock_ref != clock or window.bounds != "closed_open":
        _unsupported("screening-resource-time-model")
    if window.start.offset == window.end.offset:
        _needs("nonempty_resource_window")
    return window.start.offset, window.end.offset


def _quantity(measured):
    # Fraction preserves every decimal digit, independent of Decimal context.
    return Fraction(Decimal(measured.value))


def _capacity_sufficient(demands, capability, commitments, work_window, check_quantity, reading, source_refs):
    if not demands:
        return True
    if capability.resource_coverage != "complete" or commitments.coverage != "complete":
        _needs("complete_resource_and_commitment_coverage")
    clock = work_window.start.clock_ref
    resources = {item.resource_ref.key(): item for item in capability.resources}
    for allocation in commitments.allocations:
        if allocation.resource_ref.key() not in resources:
            _needs("commitment_resource_coverage", [allocation.resource_ref])
    groups = {(demand.resource_kind, demand.region_id, demand.quantity.unit) for demand in demands}
    method_resources, method_commitments = {}, {}
    for kind, region, unit in sorted(groups):
        required = [demand for demand in demands if (demand.resource_kind, demand.region_id, demand.quantity.unit) == (kind, region, unit)]
        for item in required:
            check_quantity(item.quantity)
        pool = []
        for resource in capability.resources:
            if resource.resource_kind != kind:
                continue
            location = _known(resource.region_id, "resource_location")
            if location != region:
                continue
            quantity = _known(resource.total, "resource_capacity")
            if quantity.unit != unit:
                _unsupported("screening-resource-unit-conversion")
            check_quantity(quantity)
            pool.append((resource, quantity))
            _interval(resource.effective_window, clock)
            method_resources[resource.resource_ref.key()] = {"resource_ref": resource.resource_ref,
                "resource_kind": resource.resource_kind, "region_id": location, "total": quantity,
                "effective_window": resource.effective_window}
        # Each demand is already in its physical region. This comparison never
        # relocates a resource or generates a reservation to make a plan fit.
        allocations = [item for item in commitments.allocations
                       if item.resource_ref.key() in {resource.resource_ref.key() for resource, _ in pool}]
        if any(item.quantity.unit != unit for item in allocations):
            _unsupported("screening-commitment-unit-conversion")
        for item in allocations:
            check_quantity(item.quantity)
            _interval(item.window, clock)
            method_commitments[item.commitment_ref.key()] = item.model_dump(mode="python")
        for item in required:
            _interval(item.window, clock)
    data = CapacityInput(clock_ref=clock, source_refs=source_refs, resources=list(method_resources.values()),
        commitments=list(method_commitments.values()), demands=[{"resource_kind": item.resource_kind,
            "region_id": item.region_id, "unit": item.quantity.unit, "window": item.window,
            "amount": ExactAmount.from_fraction(_quantity(item.quantity)), "basis_refs": [item.quantity.basis_ref]}
            for item in demands])
    try:
        return capacity_feasible(reading, data)
    except MethodDecisionGap as gap:
        raise ScreeningGap(gap.result) from gap


def screen_participation(context, action_input, reading):
    basis = {}

    def check_evidence(evidence_ref):
        evidence = reading.resolve(evidence_ref)
        if not isinstance(evidence, EvidenceRecord):
            _unsupported("contractor-screening-evidence-schema")
        if evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time):
            _needs("current_screening_evidence", [evidence_ref])
        basis[evidence_ref.key()] = evidence_ref

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"contractor-screening-projection:{ref.kind}")
        for evidence_ref in value.evidence_refs:
            check_evidence(evidence_ref)
        return value

    def completed(choice, reason, **extra):
        if profile.monthly_jv_policy_ref is not None or profile.monthly_jv_observation_ref is not None:
            if profile.monthly_jv_policy_ref is None or profile.monthly_jv_observation_ref is None:
                raise ValueError('Monthly JV review requires both policy and observation')
            if profile.monthly_region_policy_ref is not None or profile.monthly_region_observation_ref is not None:
                raise ValueError('A monthly JV review cannot substitute the distinct regional entry review')
            from src.actions.roles.contractor_jv_review import analyze_jv_review
            reason=analyze_jv_review(context,action_input,reading,profile=profile,package=package,
                screening_choice=choice,screening_note=reason).model_dump_json()
        if profile.monthly_region_policy_ref is not None or profile.monthly_region_observation_ref is not None:
            if profile.monthly_region_policy_ref is None or profile.monthly_region_observation_ref is None:
                raise ValueError('Monthly regional review requires both policy and observation')
            from src.actions.roles.contractor_region_review import analyze_region_review
            reason=analyze_region_review(context,action_input,reading,profile=profile,package=package,
                screening_choice=choice,screening_note=reason).model_dump_json()
        return {"kind": "completed", "payload": {"choice": choice, "package_ref": action_input.package_ref,
                "basis_refs": list(basis.values()), "note": reason, **extra}}

    try:
        package = read(action_input.package_ref, ProcurementPackageView)
        capability = read(action_input.capability_ref, ContractorCapabilityView)
        commitments = read(action_input.commitments_ref, CommitmentSnapshotView)
        profile = read(action_input.screening_profile_ref, OpportunityScreeningProfileView)
        if (capability.organization_ref != commitments.organization_ref
                or capability.organization_ref != profile.organization_ref
                or capability.organization_ref.id != reading.organization_id
                or context.scope.kind == "organization" and context.scope.ref != capability.organization_ref):
            raise ValueError("Screening facts belong to different organizations")
        region = _known(package.region_id, "package_region")
        work_types = _known(package.work_types, "package_work_types")
        if not work_types:
            _needs("nonempty_package_work_types")
        participation_window = _known(package.participation_window, "participation_window")
        work_window = _known(package.work_window, "work_window")
        if participation_window.start.clock_ref != context.business_time.clock_ref or work_window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("screening-clock-alignment")
        if work_window.start.offset == work_window.end.offset:
            _needs("nonempty_work_window")
        if not participation_window.contains(context.business_time):
            return completed("decline", "The exact package participation window is closed")
        for label, projection in (("capability", capability), ("screening_profile", profile)):
            if not projection.effective_window.contains(context.business_time):
                _needs(f"current_{label}", [projection.ref])
        if commitments.as_of != context.business_time:
            _needs("current_commitment_snapshot", [commitments.ref])
        if not _covers(capability.effective_window, work_window):
            _needs("capability_for_work_window", [capability.ref])
        if context.scope.kind != "organization" and context.scope != package.scope:
            raise ValueError("Package scope differs from the action scope")
        invitations = [read(ref, InvitationView) for ref in action_input.invitation_refs]
        if package.access_mode == "invitation_only" and not any(
            invite.package_ref == package.ref and invite.issuer_ref == package.employer_ref
            and invite.recipient_actor_id == context.actor_id and invite.effective_window.contains(context.business_time)
            for invite in invitations
        ):
            _needs("applicable_invitation", action_input.invitation_refs)
        supported_work = _known(capability.work_types, "supported_work_types")
        if not set(work_types) <= set(supported_work):
            return completed("decline", "The package requires a work type outside the declared capability")
        supported_methods = _known(capability.method_refs, "supported_work_methods")
        for method_ref in _known(package.required_method_refs, "required_work_methods"):
            if method_ref not in supported_methods:
                return completed("decline", "A required work method is outside the declared capability")
            method = read(method_ref, WorkMethodSupportView)
            if region not in method.region_ids or not set(work_types) <= set(method.work_types) or not _covers(method.effective_window, work_window):
                return completed("decline", "A required work method does not cover this region, work type or time")
        qualifications = [read(ref, QualificationView) for ref in action_input.qualification_refs]
        if any(item.organization_ref != capability.organization_ref for item in qualifications):
            raise ValueError("A qualification belongs to another organization")
        for requirement in _known(package.qualification_requirements, "qualification_requirements"):
            candidates = [item for item in qualifications if item.qualification_code == requirement.qualification_code
                          and requirement.region_id in item.region_ids and requirement.work_type in item.work_types
                          and _covers(item.effective_window, work_window)]
            if any(item.standing.state == "known" and item.standing.value for item in candidates):
                continue
            for item in candidates:
                if item.standing.state == "not_supported":
                    _known(item.standing, "applicable_qualification")
            if any(item.standing.state != "known" for item in candidates) or capability.qualification_coverage != "complete":
                _needs("applicable_qualification", [item.ref for item in candidates])
            return completed("decline", "Complete qualification records do not contain a valid applicable qualification")
        if package.clarification_requirement_refs:
            for requirement_ref in package.clarification_requirement_refs:
                requirement = read(requirement_ref, ScreeningRequirementView)
                if requirement.package_ref != package.ref:
                    raise ValueError("Clarification requirement belongs to another package version")
            return completed("clarify", "The supplied package has specific unresolved procurement requirements",
                             requirement_refs=package.clarification_requirement_refs)
        demands = _known(package.resource_demands, "resource_demands")
        if any(demand.region_id != region for demand in demands):
            _unsupported("screening-multiregion-work")
        if any(not _covers(work_window, demand.window) for demand in demands):
            raise ValueError("Resource demand lies outside the package work window")
        if not _capacity_sufficient(demands, capability, commitments, work_window,
                                    lambda quantity: check_evidence(quantity.basis_ref), reading,
                                    [package.ref, capability.ref, commitments.ref, profile.ref]):
            return completed("decline", "Existing commitments leave insufficient same-location resource capacity")
        if profile.require_known_funding_signal or profile.decline_on_negative_funding_signal:
            signal = _known(package.funding_signal, "package_funding_signal")
            if not signal and profile.decline_on_negative_funding_signal:
                return completed("decline", "The declared screening policy rejects the supplied negative funding signal")
        if profile.policy == "decline_new_work":
            return completed("decline", "The organization has explicitly chosen to decline new work")
        from src.actions.roles.professional_outreach import outreach_constraint
        constraint=outreach_constraint(context,reading,profile.outreach_limits)
        if constraint and not constraint[0]:return completed('decline',constraint[1])
        return completed("participate", "Applicable invitation, qualification, method and capacity checks support participation intent only")
    except ScreeningGap as gap:
        return gap.result
