"""OWN-A16 bounded private proposals, without acquiring rights or investing."""
from fractions import Fraction
import json

from src.actions.contracts.common import EvidenceRecord, TimeWindow, Known
from src.actions.contracts.owner_objects import OwnerObjectiveView, OwnerDemandObservationView, OwnerManagementCapacityView
from src.actions.contracts.owner_proposal_objects import (
    ProposalCaseView, ProposalSpaceView, ProposalCandidateView, ProposalPurposeView, ProposalInternalNeedView,
    ProposalFundingView, ProposalTechnologyView, ProposalRightsView, ProposalIssueView, ProposalScaleMethodView,
    ProposalApplicabilityRuleView, ProposalPriorBriefView,
)
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.owner_proposal import SCALE_METHOD, PROPOSAL_METHOD, ProposalScaleInput, ProposalPriorityInput, ProposalRankCandidate
from src.methods.pricing import decimal_fraction, exact_decimal


def brief_content(brief):
    """Measurement provenance alone is not a substantive proposal change."""
    value = brief.model_dump(mode="json")
    for endpoint in ("lower", "upper"):
        state = value["scale"][endpoint]
        if state["state"] == "known":
            state["value"].pop("basis_ref")
            # Decimal spelling is transport, not a change in physical scale.
            amount = decimal_fraction(state["value"]["value"])
            state["value"]["value"] = [amount.numerator, amount.denominator]
    for field in ("region_ids", "alternatives", "rights_refs", "unresolved_refs"):
        value[field] = sorted(value[field], key=lambda row: json.dumps(row, sort_keys=True))
    return json.dumps(value, sort_keys=True)


def form_proposals(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported("owner-proposal-clock")

    def available(point, field):
        clock(point)
        if point.offset > now.offset:
            _needs(field)

    def current(window, field):
        clock(window.start)
        if not window.contains(now):
            _needs(field)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported("owner-proposal-evidence-schema")
            if row.effective_window is not None:
                current(row.effective_window, "current_proposal_evidence")

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"owner-proposal-projection:{ref.kind}")
        if hasattr(value, "evidence_refs"):
            evidence(value.evidence_refs)
        return value

    def unique(refs):
        if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
            raise ValueError("Physical identity repeated across versions")

    def number(value, unit):
        evidence([value.basis_ref])
        if value.unit != unit:
            _unsupported("owner-proposal-unit-conversion")
        result = decimal_fraction(value.value)
        if result < 0:
            raise ValueError("Proposal quantities cannot be negative")
        return result

    def money(value, currency):
        evidence([value.basis_ref])
        if value.currency != currency:
            _unsupported("owner-proposal-currency-conversion")
        result = decimal_fraction(value.value)
        if result < 0:
            raise ValueError("Proposal money cannot be negative")
        return result

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == "ok":
            return result.value
        if result.kind == "invalid_input":
            raise ValueError("Proposal method input exceeds its declared domain")
        raw = result.model_dump(mode="python")
        if result.kind == "needs_information":
            raw["requested_refs"] = []
        raise ObservationGap(raw)

    def completed(choice, note, **fields):
        reading.recheck()
        return {"kind": "completed", "payload": {"choice": choice, "note": note, **fields}}

    def issue(ref, purpose):
        row = read(ref, ProposalIssueView)
        if row.case_ref != case.ref or row.purpose_ref != purpose.ref or row.status != "unresolved":
            raise ValueError("Proposal unresolved issue belongs to another case/purpose or is resolved")
        available(row.available_at, "available_proposal_issue")
        current(row.effective_window, "current_proposal_issue")
        return row

    def compare_signal(row, purpose):
        if row.region_id not in regions or row.use_code != purpose.use_code:
            return False
        rule = rules.get(row.signal_code)
        if rule is None:
            _needs("declared_proposal_signal_rule", [row.ref])
        value = _known(row.measure, "known_proposal_signal")
        evidence([value.basis_ref, rule.threshold.basis_ref])
        if value.unit != rule.threshold.unit:
            _unsupported("owner-proposal-signal-unit")
        actual, threshold = decimal_fraction(value.value), decimal_fraction(rule.threshold.value)
        return actual >= threshold if rule.comparison == "at_least" else actual <= threshold

    try:
        unique(action_input.demand_refs)
        unique(action_input.internal_need_refs)
        case = read(action_input.case_ref, ProposalCaseView)
        objective = read(action_input.objective_ref, OwnerObjectiveView)
        space = read(action_input.candidate_space_ref, ProposalSpaceView)
        if (case.organization_id != organization or objective.organization_id != organization or space.organization_id != organization
                or case.objective_ref != objective.ref or space.case_ref != case.ref or space.objective_ref != objective.ref):
            raise ValueError("Proposal case, objective or candidate space changes organization/version")
        if context.scope.kind == "assessment_case":
            if context.scope.ref != case.ref:
                raise ValueError("Proposal invocation belongs to another assessment case")
        elif context.scope.kind != "organization" or context.scope.ref.id != organization:
            _unsupported("owner-proposal-invocation-scope")
        available(case.updated_at, "available_proposal_case")
        current(objective.effective_window, "current_proposal_objective")
        current(space.effective_window, "current_proposal_space")
        available(space.available_at, "available_proposal_space")
        if case.status != "active":
            _needs("active_proposal_case", [case.ref])
        if space.policy == "no_proposal":
            return completed("no_proposal", "The owner's current sourced policy forms no proposal; no project or right is invented")
        if space.algorithm_code != "declared_private_candidates_v1":
            _unsupported("owner-proposal-selection-method")
        if not isinstance(space.maximum_briefs, Known):
            if space.maximum_briefs.state == "unknown":
                _unsupported("owner-proposal-explicit-candidate-count-limit")
            _known(space.maximum_briefs, "proposal_count_limit")
        maximum = space.maximum_briefs.value
        if maximum > 64 or len(space.candidate_refs) > 64:
            _unsupported("owner-proposal-candidate-count-domain")
        if maximum == 0 or not space.candidate_refs:
            return completed("no_proposal", "The explicitly bounded proposal space contains no admissible research candidate")
        for refs in (space.candidate_refs, space.allowed_purpose_refs, space.allowed_technology_refs, case.prior_brief_refs):
            unique(refs)
        if len(set(space.allowed_region_ids)) != len(space.allowed_region_ids) or len(set(space.allowed_interventions)) != len(space.allowed_interventions):
            raise ValueError("Allowed proposal region/intervention repeated")
        regions = set(_known(objective.allowed_region_ids, "proposal_objective_regions"))
        uses = set(_known(objective.allowed_use_codes, "proposal_objective_uses"))
        age_limit = _known(objective.maximum_observation_age, "proposal_signal_age_limit")
        rules = {rule.signal_code: rule for rule in _known(objective.signal_rules, "proposal_objective_signal_rules")}
        demands = {ref.key(): read(ref, OwnerDemandObservationView) for ref in action_input.demand_refs}
        needs = {ref.key(): read(ref, ProposalInternalNeedView) for ref in action_input.internal_need_refs}
        for row in demands.values():
            if row.ref not in case.observation_refs:
                raise ValueError("Demand input is not associated with the exact private case")
            available(row.learned_at, "learned_proposal_demand")
            clock(row.observed_at)
            if row.observed_at.offset > row.learned_at.offset:
                raise ValueError("Proposal demand is learned before measurement")
            current(row.effective_window, "current_proposal_demand")
            if now.offset - row.observed_at.offset > age_limit:
                _needs("fresh_proposal_demand", [row.ref])
        for row in needs.values():
            if row.organization_id != organization or row.case_ref != case.ref:
                raise ValueError("Internal need belongs to another owner or case")
            available(row.available_at, "available_internal_proposal_need")
            clock(row.observed_at)
            if row.observed_at.offset > row.available_at.offset:
                raise ValueError("Internal need is available before observation")
            current(row.effective_window, "current_internal_proposal_need")
            if now.offset - row.observed_at.offset > age_limit:
                _needs("fresh_internal_proposal_need", [row.ref])
        candidates, ranks, keys, revisions, contents = {}, [], set(), {}, set()
        for ref in space.candidate_refs:
            candidate = read(ref, ProposalCandidateView)
            if (candidate.organization_id != organization or candidate.case_ref != case.ref or candidate.objective_ref != objective.ref
                    or candidate.local_key in keys):
                raise ValueError("Proposal candidate changes owner, case, objective or repeats a draft identity")
            keys.add(candidate.local_key)
            available(candidate.available_at, "available_private_proposal_candidate")
            current(candidate.effective_window, "current_private_proposal_candidate")
            unique(candidate.demand_refs)
            unique(candidate.internal_need_refs)
            if not _known(candidate.research_permitted, "private_candidate_research_permission"):
                continue
            brief = candidate.brief
            if (brief.purpose_ref not in space.allowed_purpose_refs or not set(brief.region_ids) <= set(space.allowed_region_ids) & regions
                    or brief.intervention not in space.allowed_interventions or any(ref not in space.allowed_technology_refs for ref in brief.alternatives)):
                raise ValueError("Proposal candidate is outside the explicit allowed candidate space")
            purpose = read(brief.purpose_ref, ProposalPurposeView)
            if purpose.organization_id != organization or purpose.template != objective.template:
                raise ValueError("Proposal purpose belongs to another owner or objective template")
            current(purpose.effective_window, "current_proposal_purpose")
            if purpose.use_code not in uses:
                raise ValueError("Proposal purpose is outside the owner's allowed uses")
            if any(ref.key() not in demands for ref in candidate.demand_refs) or any(ref.key() not in needs for ref in candidate.internal_need_refs):
                _needs("supplied_exact_candidate_need_versions", [*candidate.demand_refs, *candidate.internal_need_refs])
            source_signals = [demands[ref.key()] for ref in candidate.demand_refs]
            internal_signals = [needs[ref.key()] for ref in candidate.internal_need_refs]
            if objective.template == "own_use" and not internal_signals:
                _needs("own_use_internal_need_basis")
            signals = internal_signals if objective.template == "own_use" else source_signals
            if not signals:
                _needs("proposal_goal_demand_basis")
            supported_regions = set()
            for row in signals:
                if row.region_id not in brief.region_ids:
                    raise ValueError("Candidate signal changes the proposed region")
                if _known(row.research_permitted, "proposal_signal_research_permission") and compare_signal(row, purpose):
                    supported_regions.add(row.region_id)
            if supported_regions != set(brief.region_ids):
                continue
            unresolved = {row.check_code: row for row in (issue(ref, purpose) for ref in brief.unresolved_refs)}
            if len(unresolved) != len(brief.unresolved_refs):
                raise ValueError("Unresolved proposal check repeated")
            delivery = read(brief.delivery_window_ref, TimeWindow)
            clock(delivery.start)
            if delivery.bounds != "closed_open":
                _unsupported("owner-proposal-delivery-window")
            if delivery.start.offset < now.offset or delivery.end.offset <= delivery.start.offset:
                _needs("current_nonempty_proposal_delivery_window", [brief.delivery_window_ref])
            for technology_ref in brief.alternatives:
                technology = read(technology_ref, ProposalTechnologyView)
                if (technology.purpose_ref != purpose.ref or not set(brief.region_ids) <= set(technology.region_ids)
                        or brief.intervention not in technology.interventions):
                    raise ValueError("Technology candidate changes purpose, region or intervention")
                current(technology.effective_window, "current_proposal_technology")
                available(technology.available_at, "available_proposal_technology")
                if not _known(technology.research_permitted, "technology_research_permission"):
                    _needs("permitted_proposal_technology", [technology.ref])
            for rights_ref in brief.rights_refs:
                rights = read(rights_ref, ProposalRightsView)
                if (rights.case_ref != case.ref or rights.purpose_ref != purpose.ref or not set(brief.region_ids) <= set(rights.region_ids)):
                    raise ValueError("Rights evidence changes private case, purpose or region")
                current(rights.effective_window, "current_proposal_rights_evidence")
                available(rights.available_at, "available_proposal_rights_evidence")
                if rights.status == "excluded" or not _known(rights.research_permitted, "rights_research_permission"):
                    _needs("lawful_proposal_research_path", [rights.ref])
                if rights.holder_organization_id.state == "not_supported":
                    _unsupported("owner-proposal-rights-holder")
                if rights.status == "prospective_route" or rights.holder_organization_id.state == "unknown":
                    if "rights_path" not in unresolved:
                        _needs("unresolved_proposal_rights_path")
                elif _known(rights.holder_organization_id, "current_rights_holder") != organization:
                    raise ValueError("Other-party current rights cannot be claimed as this owner's rights")
            if not brief.rights_refs and "rights_path" not in unresolved:
                _needs("explicit_rights_or_unresolved_path")
            scale = read(brief.scale.basis_ref, ProposalScaleMethodView)
            if scale.purpose_ref != purpose.ref or scale.asset_kind != purpose.asset_kind or brief.intervention not in scale.interventions:
                raise ValueError("Scale method does not apply to this exact purpose, asset and intervention")
            current(scale.effective_window, "current_proposal_scale_method")
            if scale.algorithm_code != "declared_inclusive_bounds_v1":
                _unsupported("owner-proposal-scale-method")
            if scale.applicability == "not_applicable":
                if scale.applicability_rule_ref is None:
                    raise ValueError("Non-applicable scale lacks a rule")
                rule = read(scale.applicability_rule_ref, ProposalApplicabilityRuleView)
                current(rule.effective_window, "current_scale_applicability_rule")
                if rule.purpose_ref != purpose.ref or rule.asset_kind != purpose.asset_kind or brief.intervention not in rule.interventions:
                    raise ValueError("Scale non-applicability rule changes purpose or asset")
                report = method(SCALE_METHOD, ProposalScaleInput(lower=brief.scale.lower, upper=brief.scale.upper, applicability="not_applicable",
                    minimum=None, maximum=None, applicability_rule_ref=rule.ref, source_refs=[candidate.ref, scale.ref, rule.ref],
                    basis_refs=[*candidate.evidence_refs, *scale.evidence_refs, *rule.evidence_refs]))
            else:
                minimum, maximum_scale = _known(scale.minimum, "declared_minimum_proposal_scale"), _known(scale.maximum, "declared_maximum_proposal_scale")
                evidence([minimum.basis_ref, maximum_scale.basis_ref])
                if any(state.state == "not_supported" for state in (brief.scale.lower, brief.scale.upper)):
                    _unsupported("owner-proposal-scale-endpoint")
                report = method(SCALE_METHOD, ProposalScaleInput(lower=brief.scale.lower, upper=brief.scale.upper, applicability="range",
                    minimum=minimum, maximum=maximum_scale, applicability_rule_ref=None, source_refs=[candidate.ref, scale.ref],
                    basis_refs=[*candidate.evidence_refs, *scale.evidence_refs]))
            if not report.fits_known_bounds:
                continue
            for endpoint in report.unknown_endpoints:
                if "scale_" + endpoint not in unresolved:
                    _needs("unresolved_proposal_scale_" + endpoint)
            if space.mode == "revise":
                if candidate.prior_brief_ref is None or candidate.prior_brief_ref not in case.prior_brief_refs:
                    _needs("associated_prior_proposal_brief", [] if candidate.prior_brief_ref is None else [candidate.prior_brief_ref])
                prior = read(candidate.prior_brief_ref, ProposalPriorBriefView)
                if prior.organization_id != organization or prior.case_ref != case.ref or prior.objective_ref != objective.ref:
                    raise ValueError("Revised brief belongs to another owner, case or objective")
                current(prior.effective_window, "current_prior_proposal_brief")
                available(prior.available_at, "available_prior_proposal_brief")
                if prior.status != "active":
                    _needs("active_prior_proposal_brief", [prior.ref])
                if brief_content(prior.brief) == brief_content(brief):
                    continue
                revisions[candidate.local_key] = prior.ref
            elif candidate.prior_brief_ref is not None:
                raise ValueError("New proposal cannot silently revise an existing brief")
            content = brief_content(brief)
            if content in contents:
                raise ValueError("The same proposal is repeated under another candidate identity")
            contents.add(content)
            candidates[candidate.local_key] = candidate
        if not candidates:
            return completed("no_proposal", "No supplied candidate has applicable sourced need, research permission and scale bounds; no project count is forced")
        funding = read(action_input.funding_ref, ProposalFundingView)
        capacity = read(space.capacity_ref, OwnerManagementCapacityView)
        if funding.organization_id != organization or capacity.organization_id != organization:
            raise ValueError("Proposal research funding or management capacity belongs to another owner")
        if funding.as_of != now or funding.coverage != "complete":
            _needs("current_complete_proposal_funding")
        _known(funding.deduction_policy, "disjoint_proposal_cash_deductions")
        current(capacity.effective_window, "current_proposal_management_capacity")
        actual = _known(funding.actual_cash, "proposal_actual_cash")
        committed = _known(funding.committed_cash, "proposal_committed_cash")
        restricted = _known(funding.restricted_cash, "proposal_restricted_cash")
        cash = money(actual, actual.currency) - money(committed, actual.currency) - money(restricted, actual.currency)
        if cash < 0:
            raise ValueError("Committed plus restricted proposal funds exceed actual cash")
        total = _known(capacity.total, "proposal_management_total")
        effort = number(total, total.unit)
        for load in capacity.commitments:
            clock(load.window.start)
            if load.window.bounds != "closed_open":
                _unsupported("owner-proposal-management-window")
            if load.window.contains(now):
                effort -= number(load.quantity, total.unit)
        effort = max(Fraction(), effort)
        for candidate in candidates.values():
            cost, work = _known(candidate.review_cost, "candidate_review_cost"), _known(candidate.review_effort, "candidate_review_effort")
            money(cost, actual.currency)
            number(work, total.unit)
            ranks.append(ProposalRankCandidate(local_key=candidate.local_key, priority=_known(candidate.priority, "candidate_proposal_priority"),
                review_cost=cost, review_effort=work))
        available_cash = actual.model_copy(update={"value": exact_decimal(cash)})
        available_effort = total.model_copy(update={"value": exact_decimal(effort)})
        ranking = method(PROPOSAL_METHOD, ProposalPriorityInput(maximum_briefs=maximum, available_cash=available_cash,
            available_effort=available_effort, candidates=ranks, source_refs=[space.ref, funding.ref, capacity.ref, *[row.ref for row in candidates.values()]]))
        if ranking.ambiguous_keys:
            _needs("unique_feasible_proposal_priority", [candidates[key].ref for key in ranking.ambiguous_keys])
        if not ranking.selected_keys:
            return completed("no_proposal", "Current uncommitted/unrestricted review funds and management capacity support no private candidate")
        selected = [candidates[key] for key in ranking.selected_keys]
        fields = {"briefs": [row.brief.model_dump(mode="python") for row in selected]}
        if space.mode == "revise":
            prior_refs = [revisions[row.local_key] for row in selected]
            unique(prior_refs)
            fields["prior_brief_refs"] = prior_refs
        return completed(space.mode, "Bounded private proposal drafts retain uncertainty and prospective rights; research does not create demand, rights, financing or a formal project", **fields)
    except ObservationGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
            "code": "owner_proposal_projection_invalid"}, "retryability": "non_retryable"}
