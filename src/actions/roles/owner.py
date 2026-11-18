"""Owner A01 screening without acquiring rights or creating formal projects."""
from decimal import Decimal
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.owner_objects import (
    OwnerCaseView, OwnerDemandObservationView, OwnerManagementCapacityView,
    OwnerObjectiveView, OwnerObservationSourceView, OwnerOpportunityView,
)


class ObservationGap(Exception):
    def __init__(self, result):
        self.result = result


def _needs(field, refs=()):
    raise ObservationGap({"kind": "needs_information", "missing_fields": [field], "requested_refs": list(refs)})


def _unsupported(capability):
    raise ObservationGap({"kind": "unsupported", "capability_ref": {
        "kind": "Capability", "id": capability, "version": "1"}})


def _known(state, field):
    if isinstance(state, Known):
        return state.value
    if state.state == "not_supported":
        raise ObservationGap({"kind": "unsupported", "capability_ref": state.capability_ref})
    if state.state == "not_applicable":
        _unsupported(f"owner-screening-applicability:{field}")
    _needs(field, state.missing_refs)


def observe_opportunities(context, action_input, reading):
    basis = {}
    now = context.business_time

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported("owner-screening-clock-alignment")

    def current(window):
        clock(window.start)
        return window.contains(now)

    def evidence(ref):
        value = reading.resolve(ref)
        if not isinstance(value, EvidenceRecord):
            _unsupported("owner-screening-evidence-schema")
        if value.effective_window is not None and not current(value.effective_window):
            _needs("current_screening_evidence", [ref])
        basis[ref.key()] = ref

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"owner-screening-projection:{ref.kind}")
        for ref in value.evidence_refs:
            evidence(ref)
        return value

    def completed(choice, note, **extra):
        if objective.monthly_demand_observation_ref is not None:
            from src.actions.roles.owner_monthly_demand import analyze_monthly_demand
            note=analyze_monthly_demand(context,action_input,reading,objective=objective,choice=choice).model_dump_json()
        return {"kind": "completed", "payload": {"choice": choice,
                "basis_refs": list(basis.values()), "note": note, **extra}}

    def unique(refs):
        keys = [(ref.kind, ref.id) for ref in refs]
        if len(set(keys)) != len(keys):
            raise ValueError("Screening snapshot repeats a physical source or case")

    try:
        if action_input.scope_ref != context.scope:
            raise ValueError("Observation scope differs from the invocation scope")
        if context.scope.kind == "organization" and context.scope.ref.id != reading.organization_id:
            raise ValueError("Observation organization scope belongs to another owner")
        for refs in (action_input.observations, action_input.opportunity_refs, action_input.existing_case_refs):
            unique(refs)
        objective = read(action_input.objective_ref, OwnerObjectiveView)
        capacity = read(action_input.capacity_ref, OwnerManagementCapacityView)
        if objective.organization_id != reading.organization_id or capacity.organization_id != reading.organization_id:
            raise ValueError("Objective or management capacity belongs to another owner")
        if not current(objective.effective_window):
            _needs("current_owner_objective", [objective.ref])
        if not current(capacity.effective_window):
            _needs("current_management_capacity", [capacity.ref])
        regions = _known(objective.allowed_region_ids, "objective_regions")
        uses = _known(objective.allowed_use_codes, "objective_uses")
        rules = {rule.signal_code: rule for rule in _known(objective.signal_rules, "objective_signal_rules")}
        if not rules:
            _needs("objective_signal_rules")
        age_limit = _known(objective.maximum_observation_age, "maximum_observation_age")
        cases = [read(ref, OwnerCaseView) for ref in action_input.existing_case_refs]
        for case in cases:
            if case.organization_id != reading.organization_id:
                raise ValueError("Assessment case belongs to another owner")
            clock(case.updated_at)
            if case.updated_at.offset > now.offset:
                _needs("assessment_case_at_read_point", [case.ref])
        if context.scope.kind == "assessment_case" and not any(case.ref == context.scope.ref for case in cases):
            _needs("scoped_assessment_case", [context.scope.ref])
        if context.scope.kind == "project":
            _unsupported("owner-screening-project-scope")

        observations = [read(ref, OwnerDemandObservationView) for ref in action_input.observations]
        opportunities = [read(ref, OwnerOpportunityView) for ref in action_input.opportunity_refs]
        # An opportunity can bring its own authorized signal projection.
        by_key = {value.ref.key(): value for value in observations}
        for opportunity in opportunities:
            clock(opportunity.learned_at)
            if opportunity.learned_at.offset > now.offset:
                _needs("opportunity_available_at_read_point", [opportunity.ref])
            for ref in opportunity.observation_refs:
                if ref.key() not in by_key:
                    value = read(ref, OwnerDemandObservationView)
                    by_key[ref.key()] = value
        observations = list(by_key.values())
        unique([value.ref for value in observations])
        interesting = []
        for value in observations:
            clock(value.observed_at)
            clock(value.learned_at)
            if value.observed_at.offset > value.learned_at.offset:
                raise ValueError("Observation is learned before its stated measurement time")
            if value.learned_at.offset > now.offset:
                _needs("observation_available_at_read_point", [value.ref])
            if not current(value.effective_window) or now.offset - value.observed_at.offset > age_limit:
                _needs("current_demand_observation", [value.ref])
            if value.region_id not in regions or value.use_code not in uses or value.signal_code not in rules:
                continue
            if not _known(value.research_permitted, "signal_research_permission"):
                continue
            rule = rules[value.signal_code]
            quantity = _known(value.measure, f"signal:{value.ref.id}")
            evidence(quantity.basis_ref)
            evidence(rule.threshold.basis_ref)
            if quantity.unit != rule.threshold.unit:
                _unsupported("owner-screening-unit-conversion")
            actual, threshold = Decimal(quantity.value), Decimal(rule.threshold.value)
            if (actual >= threshold if rule.comparison == "at_least" else actual <= threshold):
                source = read(value.source_ref, OwnerObservationSourceView)
                if source.demand_ref != value.ref:
                    raise ValueError("Observation output source differs from its demand version")
                interesting.append(value)
        active_opportunities = []
        for opportunity in opportunities:
            if (opportunity.region_id not in regions or opportunity.use_code not in uses
                    or not current(opportunity.effective_window)):
                continue
            if _known(opportunity.status, "opportunity_status") != "active":
                continue
            if not _known(opportunity.research_permitted, "opportunity_research_permission"):
                continue
            signals = [value for value in interesting if value.ref in opportunity.observation_refs]
            if any(value.region_id != opportunity.region_id or value.use_code != opportunity.use_code for value in signals):
                raise ValueError("Opportunity and its demand signal disagree on region or use")
            if signals:
                active_opportunities.append(opportunity)
        if not observations:
            _needs("observation_or_opportunity")
        if not interesting:
            return completed("ignore", f"No supplied signal meets the declared {objective.template} screening rules")
        if len({(value.region_id, value.use_code) for value in interesting}) > 1:
            _needs("bounded_region_use_selection", [value.ref for value in interesting])

        matches = [case for case in cases if any(
            any(ref.id == value.ref.id for ref in case.observation_refs) for value in interesting)
            or any(any(ref.id == opportunity.ref.id for ref in case.opportunity_refs) for opportunity in active_opportunities)]
        if context.scope.kind == "assessment_case":
            matches = [case for case in matches if case.ref == context.scope.ref]
            if not matches:
                _needs("signals_associated_with_scoped_case", [context.scope.ref])
        if len(matches) > 1:
            _needs("unambiguous_existing_case", [case.ref for case in matches])
        if matches:
            case = matches[0]
            if any(value.region_id != case.region_id or value.use_code != case.use_code for value in interesting):
                raise ValueError("Assessment case and current signal disagree on region or use")
            linked = [value.ref for value in interesting]
            linked_opportunities = [value.ref for value in active_opportunities]
            unchanged = (case.objective_ref == objective.ref
                         and all(ref in case.observation_refs for ref in linked)
                         and all(ref in case.opportunity_refs for ref in linked_opportunities))
            if unchanged and case.status == "active":
                return completed("follow", "Reuse the original private case for unchanged source versions",
                                 target={"kind": "case", "case_ref": case.ref})
            if case.status == "closed" and not _known(objective.allow_reopen, "allow_case_reopen"):
                return completed("ignore", "The owner's declared policy leaves the closed private case unchanged")

        total = _known(capacity.total, "management_total")
        required = _known(capacity.screening_requirement, "screening_requirement")
        evidence(total.basis_ref)
        evidence(required.basis_ref)
        if total.unit != required.unit:
            _unsupported("owner-screening-management-unit-conversion")
        used = Fraction(0)
        for load in capacity.commitments:
            clock(load.window.start)
            if load.window.bounds != "closed_open":
                _unsupported("owner-screening-management-window-bounds")
            if load.window.contains(now):
                if load.quantity.unit != total.unit:
                    _unsupported("owner-screening-management-unit-conversion")
                evidence(load.quantity.basis_ref)
                used += Fraction(Decimal(load.quantity.value))
        if used + Fraction(Decimal(required.value)) > Fraction(Decimal(total.value)):
            return {"kind": "deferred", "reason_code": "management_capacity_exhausted",
                    "resume_condition": {"trigger": "dependency_change", "object_refs": [capacity.ref],
                                         "earliest_time": None, "condition_code": "management_capacity_revalidated"}}
        if matches:
            return completed("revise_case", "Reassess changed source versions on the existing private case", case_ref=matches[0].ref)
        if active_opportunities:
            if len(active_opportunities) > 1:
                _needs("opportunity_selection", [value.ref for value in active_opportunities])
            return completed("follow", "Follow the currently researchable opportunity without acquiring rights",
                             target={"kind": "opportunity", "opportunity_ref": active_opportunities[0].ref})
        choice = _known(objective.new_signal_choice, "new_signal_choice")
        return completed(choice, f"Use declared {objective.template} policy for sourced private assessment only",
                         source_refs=[value.source_ref for value in interesting])
    except ObservationGap as gap:
        return gap.result
