"""OWN-A02 forms a bounded study decision without spending or clearing debt."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.owner_proposal_objects import ProposalFundingView, ProposalPriorBriefView
from src.actions.contracts.owner_study_objects import (
    StudyCaseView, StudyProfileView, StudyCandidateView, StudyIssueView, StudyWorkScopeView,
    StudyRequirementView, StudyPriorPlanView, StudyObligationView, StudyReassessmentView,
    StudyResourceView, StudyServiceOfferView, unique_refs,
)
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.owner_study import STUDY_METHOD, StudyBudgetCandidate, StudyBudgetInput
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def authorize_study(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported("owner-study-clock")

    def available(point, field):
        clock(point)
        if point.offset > now.offset: _needs(field)

    def current(window, field):
        clock(window.start)
        if not window.contains(now): _needs(field)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported("owner-study-evidence-schema")
            if row.effective_window is not None: current(row.effective_window, "current_study_evidence")

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f"owner-study-projection:{ref.kind}")
        if hasattr(row, "evidence_refs"): evidence(row.evidence_refs)
        return row

    def money(value, currency):
        evidence([value.basis_ref])
        if value.currency != currency: _unsupported("owner-study-currency-conversion")
        amount = decimal_fraction(value.value)
        if amount < 0: raise ValueError("Study money cannot be negative")
        return amount

    def measure(value, unit):
        evidence([value.basis_ref])
        if value.unit != unit: _unsupported("owner-study-unit-conversion")
        amount = decimal_fraction(value.value)
        if amount < 0: raise ValueError("Study capacity cannot be negative")
        return amount

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == "ok": return result.value
        if result.kind == "invalid_input": raise ValueError("Invalid declared study method input")
        raw = result.model_dump(mode="python")
        if result.kind == "needs_information": raw["requested_refs"] = []
        raise ObservationGap(raw)

    def completed(choice, note, **fields):
        reading.recheck()
        return {"kind": "completed", "payload": {"choice": choice, "note": note, **fields}}

    def unavailable(reason):
        policy = _known(profile.on_unavailable, "study_unavailable_policy")
        if policy == "stop": return completed("stop", reason + "; actual incurred fees and existing obligations remain unchanged")
        reading.recheck()
        return {"kind": "deferred", "reason_code": "owner_study_no_current_feasible_plan", "resume_condition": {
            "trigger": "dependency_change", "object_refs": [profile.ref, profile.funding_ref],
            "earliest_time": None, "condition_code": "owner.study.conditions_changed"}}

    def scope(value):
        if value.kind != "assessment_case" or value.ref != case.ref or not value.coverage_refs:
            raise ValueError("Study requires nonempty work scope within the exact private case")
        unique_refs(value.coverage_refs)
        if not scope_covers(context.scope, value) or not scope_covers(profile.permitted_scope, value):
            raise ValueError("Study exceeds invocation or profile authority scope")
        for ref in value.coverage_refs:
            work = read(ref, StudyWorkScopeView)
            if work.case_ref != case.ref: raise ValueError("Study work belongs to another case")
            current(work.effective_window, "current_study_work")
            if not _known(work.research_permitted, "study_work_permission"): return False
        return True

    def authority(ref, organization, actor, function, action, requested_scope):
        row = read(ref, Authorization)
        evidence(row.basis_refs)
        current(row.validity, "current_study_authority")
        if (row.organization_id != organization or row.actor_id != actor or row.function_ref != function):
            raise ValueError("Study authority changes organization, author or function")
        assignment = read(function, RoleAssignment)
        evidence(assignment.basis_refs)
        if organization == owner and assignment.role != "Owner":
            raise ValueError("Limited-study authorization requires the owner's assigned function")
        if action not in row.action_ids or not any(scope_covers(value, requested_scope) for value in row.scopes):
            return False
        return True

    def condition(ref, requested_scope):
        row = read(ref, StudyRequirementView)
        if row.case_ref != case.ref or not scope_covers(row.scope, requested_scope):
            raise ValueError("Study condition belongs to another case/scope")
        current(row.effective_window, "current_study_condition")
        available(row.verified_at, "available_study_condition")
        return _known(row.verified, "study_condition_verification")

    try:
        unique_refs(action_input.issue_refs)
        unique_refs(action_input.service_candidates)
        case = read(action_input.case_ref, StudyCaseView)
        profile = read(action_input.study_profile_ref, StudyProfileView)
        if case.organization_id != owner or profile.organization_id != owner or profile.case_ref != case.ref:
            raise ValueError("Study case/profile changes owner or case version")
        if context.scope.kind != "assessment_case" or context.scope.ref != case.ref:
            _unsupported("owner-study-assessment-scope")
        available(case.updated_at, "available_study_case")
        current(profile.effective_window, "current_study_profile")
        available(profile.available_at, "available_study_profile")
        if profile.as_of != now or profile.history_coverage != "complete": _needs("current_complete_study_history")
        if set(profile.history_refs) != set(case.study_refs): raise ValueError("Study profile omits or changes case history")
        currency = action_input.spending_limit.currency
        money(action_input.spending_limit, currency)
        if action_input.brief_ref is None:
            if not action_input.issue_refs: _needs("registered_study_issue_without_brief")
        else:
            if action_input.brief_ref not in case.brief_refs: raise ValueError("Brief is not associated with this private case")
            brief = read(action_input.brief_ref, ProposalPriorBriefView)
            if brief.organization_id != owner or brief.case_ref != case.ref or brief.objective_ref != case.objective_ref:
                raise ValueError("Study brief changes owner, case or objective")
            current(brief.effective_window, "current_study_brief")
            available(brief.available_at, "available_study_brief")
            if brief.status != "active": _needs("active_study_brief")
            if any(ref not in action_input.issue_refs for ref in brief.brief.unresolved_refs):
                _needs("supplied_brief_unresolved_issues", brief.brief.unresolved_refs)
        issues, codes = {}, set()
        for ref in action_input.issue_refs:
            if ref not in case.issue_refs: raise ValueError("Study issue is not associated with the exact case")
            row = read(ref, StudyIssueView)
            if row.case_ref != case.ref or row.scope.kind != "assessment_case" or row.scope.ref != case.ref:
                raise ValueError("Study question belongs to another private case")
            if row.question_code in codes: raise ValueError("Study question repeated under different issue identities")
            codes.add(row.question_code)
            available(row.available_at, "available_study_issue")
            current(row.effective_window, "current_study_issue")
            issues[ref.key()] = row
        histories, incurred = {}, {}
        all_obligations = set()
        for ref in profile.history_refs:
            prior = read(ref, StudyPriorPlanView)
            if (prior.organization_id != owner or prior.case_ref != case.ref or prior.scope.kind != "assessment_case"
                    or prior.scope.ref != case.ref or prior.linked_project_ref != case.linked_project_ref):
                raise ValueError("Study history changes owner, case or project lineage")
            available(prior.available_at, "available_prior_study")
            evidence(prior.information_basis_refs)
            money(prior.expenditure_cap, currency)
            spent_value = _known(prior.incurred_cost, "actual_incurred_study_cost")
            spent = money(spent_value, currency)
            if not set(prior.remaining_work_refs) <= set(prior.scope.coverage_refs):
                raise ValueError("Remaining study work exceeds original scope")
            actual_due = Fraction()
            for debt_ref in prior.obligation_refs:
                if (debt_ref.kind, debt_ref.id) in all_obligations: raise ValueError("Study obligation repeated across history")
                all_obligations.add((debt_ref.kind, debt_ref.id))
                debt = read(debt_ref, StudyObligationView)
                if (debt.debtor_organization_id != owner or debt.origin_case_ref != case.ref
                        or debt.origin_study_ref != prior.ref or debt.linked_project_ref != case.linked_project_ref):
                    raise ValueError("Actual study obligation changes original debtor or lineage")
                if debt.as_of != now: _needs("current_actual_study_obligation")
                due, paid = money(debt.actual_due, currency), money(debt.actual_paid, currency)
                if paid > due: raise ValueError("Paid amount exceeds actual study obligation")
                actual_due += due
            if actual_due > spent: raise ValueError("Actual study obligations exceed recorded incurred fees")
            histories[prior.ref.key()], incurred[prior.ref.key()] = prior, spent_value
        if _known(profile.policy, "limited_study_policy") == "stop" or case.status == "closed":
            return completed("stop", "No new research is authorized; past results, actual incurred fees and existing obligations remain unchanged")
        if profile.algorithm_code != "declared_limited_study_v1": _unsupported("owner-study-selection-method")
        if len(profile.candidate_refs) > 64: _unsupported("owner-study-candidate-count-domain")
        if not any(row.status == "unresolved" for row in issues.values()):
            return completed("stop", "No supplied question remains unresolved; existing results and actual obligations are retained")
        if not authority(profile.authority_ref, owner, context.actor_id, context.function_ref, "OWN-A02", profile.permitted_scope):
            _needs("permitted_limited_study_authority")
        feasible, budgets, keys = {}, [], set()
        for ref in profile.candidate_refs:
            candidate = read(ref, StudyCandidateView)
            if candidate.organization_id != owner or candidate.case_ref != case.ref or candidate.local_key in keys:
                raise ValueError("Study candidate changes owner, case or repeats task identity")
            keys.add(candidate.local_key)
            available(candidate.available_at, "available_study_candidate")
            current(candidate.effective_window, "current_study_candidate")
            if not _known(candidate.research_permitted, "candidate_study_permission"): continue
            if not scope(candidate.task_scope.scope_ref): continue
            evidence(candidate.task_scope.basis_refs)
            unique_refs(candidate.task_scope.condition_refs)
            if not all(condition(ref, candidate.task_scope.scope_ref) for ref in candidate.task_scope.condition_refs): continue
            selected_issues = []
            for issue_ref in candidate.issue_refs:
                if issue_ref.key() not in issues: _needs("supplied_exact_candidate_study_issues", candidate.issue_refs)
                row = issues[issue_ref.key()]
                if row.status != "unresolved": break
                if not scope_covers(candidate.task_scope.scope_ref, row.scope): raise ValueError("Study scope omits its question")
                selected_issues.append(row)
            if len(selected_issues) != len(candidate.issue_refs): continue
            question_codes = {row.question_code for row in selected_issues}
            supported = set()
            for scope_ref in candidate.task_scope.scope_ref.coverage_refs:
                work_questions = set(read(scope_ref, StudyWorkScopeView).question_codes)
                if not work_questions <= question_codes:
                    raise ValueError("Study scope introduces work unrelated to its selected questions")
                supported.update(work_questions)
            if not question_codes <= supported: raise ValueError("Study scope does not support its declared questions")
            window = read(candidate.window_ref, TimeWindow)
            clock(window.start)
            if window.bounds != "closed_open": _unsupported("owner-study-half-open-window")
            if window.start.offset < now.offset or window.start.offset >= window.end.offset: _needs("current_future_study_window", [candidate.window_ref])
            cap = _known(candidate.expenditure_cap, "limited_study_expenditure_cap")
            cost = _known(candidate.future_cost, "sourced_future_study_cost")
            money(cap, currency)
            money(cost, currency)
            prior = None
            if candidate.choice == "narrow":
                if candidate.prior_study_ref.key() not in histories: _needs("associated_exact_prior_study", [candidate.prior_study_ref])
                prior = histories[candidate.prior_study_ref.key()]
                if prior.status != "active": _needs("active_prior_study_for_narrowing")
                if not scope_covers(profile.permitted_scope, prior.scope) or not scope_covers(context.scope, prior.scope):
                    raise ValueError("Narrowing cannot remove original work outside the current authority")
                if not question_codes <= set(prior.question_codes): raise ValueError("Narrowing introduces unrelated research questions")
                retained = set(candidate.task_scope.scope_ref.coverage_refs)
                if not retained < set(prior.remaining_work_refs): raise ValueError("Narrowing must strictly reduce remaining work scope")
            reassessments = {}
            for change_ref in candidate.reassessment_refs:
                change = read(change_ref, StudyReassessmentView)
                if (change.organization_id != owner or change.case_ref != case.ref or change.prior_study_ref.key() not in histories
                        or change.prior_study_ref.key() in reassessments): raise ValueError("Reassessment changes owner/case or repeats prior history")
                current(change.effective_window, "current_study_reassessment")
                available(change.available_at, "available_study_reassessment")
                if not _known(change.permitted, "study_reassessment_permission") or not condition(change.requirement_ref, candidate.task_scope.scope_ref):
                    _needs("verified_study_reassessment_condition")
                unique_refs(change.changed_evidence_refs)
                evidence(change.changed_evidence_refs)
                previous = histories[change.prior_study_ref.key()]
                if change.trigger_code == "changed_information":
                    previous_hashes = {read(ref, EvidenceRecord).content_hash for ref in previous.information_basis_refs}
                    if (not change.changed_evidence_refs
                            or any(ref in previous.information_basis_refs for ref in change.changed_evidence_refs)
                            or any(read(ref, EvidenceRecord).content_hash in previous_hashes for ref in change.changed_evidence_refs)):
                        raise ValueError("Changed-information reassessment carries no new evidence content")
                if change.trigger_code == "failed_study_remedy" and previous.status != "failed":
                    raise ValueError("Remedy reassessment does not refer to a failed study")
                reassessments[change.prior_study_ref.key()] = change
            repeat = False
            for previous in histories.values():
                overlap = question_codes & set(previous.question_codes)
                if not overlap or prior is not None and previous.ref == prior.ref: continue
                if previous.status == "active": repeat = True; break
                change = reassessments.get(previous.ref.key())
                if change is None or not overlap <= set(change.question_codes): repeat = True; break
            if repeat: continue
            if candidate.choice == "commission":
                if candidate.offer_ref not in action_input.service_candidates: _needs("received_exact_limited_service_offer", [candidate.offer_ref])
                offer = read(candidate.offer_ref, StudyServiceOfferView)
                if (offer.client_organization_id != owner or offer.payer_organization_id != owner or offer.case_ref != case.ref
                        or offer.scope != candidate.task_scope.scope_ref or set(offer.issue_refs) != set(candidate.issue_refs)
                        or offer.window_ref != candidate.window_ref): raise ValueError("Commission changes client, payer, case, scope, questions or window")
                available(offer.available_at, "available_study_service_offer")
                current(offer.effective_window, "current_study_service_offer")
                if offer.status != "offered": continue
                if not _known(offer.research_permitted, "service_offer_research_permission") or not _known(offer.qualified, "study_provider_qualification"): continue
                if not question_codes <= set(_known(offer.supported_question_codes, "study_provider_question_support")): continue
                if not authority(offer.authority_ref, offer.provider_organization_id, offer.author_actor_id,
                        offer.author_function_ref, offer.authority_action_id, offer.scope): continue
                assignment = read(offer.author_function_ref, RoleAssignment)
                if {"ARCHITECT-A02": "Architect", "ENGINEER-A02": "Engineer", "QS-A02": "QS"}[offer.authority_action_id] != assignment.role:
                    raise ValueError("Study offer author function does not match its professional authority")
                if money(_known(offer.fee, "limited_service_offer_fee"), currency) != money(cost, currency):
                    raise ValueError("Candidate research cost differs from exact received service fee")
            if candidate.choice == "internal_study":
                groups = {}
                for allocation in candidate.allocations:
                    pool = read(allocation.resource_ref, StudyResourceView)
                    if pool.organization_id != owner: raise ValueError("Internal study cannot allocate another organization's staff")
                    if pool.as_of != now or pool.coverage != "complete": _needs("current_complete_study_resource_load")
                    current(pool.effective_window, "current_study_resource")
                    if not _known(pool.qualified, "internal_study_qualification") or not _known(pool.research_permitted, "internal_study_permission"):
                        groups = {}; break
                    if not question_codes <= set(_known(pool.supported_question_codes, "internal_study_question_support")):
                        groups = {}; break
                    if not authority(pool.authorization_ref, owner, context.actor_id, pool.function_ref, "OWN-A02", candidate.task_scope.scope_ref):
                        groups = {}; break
                    total = _known(pool.total, "actual_study_resource_capacity")
                    measure(total, total.unit)
                    quantity = measure(allocation.quantity, total.unit)
                    if quantity <= 0: raise ValueError("Internal study allocation must be positive")
                    identity = pool.ref.key()
                    if identity not in groups: groups[identity] = [pool, total, Fraction()]
                    groups[identity][2] += quantity
                if not groups: continue
                resources, demands, loads = [], [], []
                for identity, (pool, total, needed) in groups.items():
                    resources.append({"resource_ref": pool.ref, "resource_kind": pool.ref.id, "region_id": case.region_id,
                        "total": total, "effective_window": pool.effective_window})
                    demands.append({"resource_kind": pool.ref.id, "region_id": case.region_id, "unit": total.unit,
                        "amount": ExactAmount.from_fraction(needed), "window": window, "basis_refs": pool.evidence_refs})
                    for load in pool.commitments:
                        clock(load.window.start)
                        if load.window.bounds != "closed_open": _unsupported("owner-study-commitment-window")
                        if measure(load.quantity, total.unit) <= 0: raise ValueError("Actual study commitments must be positive")
                        loads.append({"commitment_ref": load.ref, "resource_ref": pool.ref, "quantity": load.quantity, "window": load.window})
                report = method(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, resources=resources, demands=demands,
                    commitments=loads, source_refs=[candidate.ref, *[group[0].ref for group in groups.values()]]))
                if not report.feasible: continue
            spent = incurred[prior.ref.key()] if prior is not None else cost.model_copy(update={"value": "0"})
            budgets.append(StudyBudgetCandidate(local_key=candidate.local_key, priority=_known(candidate.priority, "declared_study_priority"),
                expenditure_cap=cap, future_cost=cost, incurred_cost=spent, prior_cap=prior.expenditure_cap if prior is not None else None))
            feasible[candidate.local_key] = candidate
        if not feasible:
            return unavailable("No new applicable bounded study is available; existing results are reused and repeated questions need an explicit reassessment trigger")
        funding = read(profile.funding_ref, ProposalFundingView)
        if funding.organization_id != owner: raise ValueError("Study funding belongs to another owner")
        if funding.as_of != now or funding.coverage != "complete": _needs("current_complete_study_funding")
        _known(funding.deduction_policy, "disjoint_study_cash_deductions")
        actual = _known(funding.actual_cash, "actual_study_cash")
        committed = _known(funding.committed_cash, "committed_study_cash")
        restricted = _known(funding.restricted_cash, "restricted_study_cash")
        cash = money(actual, currency) - money(committed, currency) - money(restricted, currency)
        if cash < 0: raise ValueError("Committed plus restricted study cash exceeds actual cash")
        ranking = method(STUDY_METHOD, StudyBudgetInput(spending_limit=action_input.spending_limit,
            available_cash=actual.model_copy(update={"value": exact_decimal(cash)}), candidates=budgets,
            source_refs=[profile.ref, funding.ref, *[row.ref for row in feasible.values()]]))
        if ranking.ambiguous_keys: _needs("unique_declared_study_priority", [feasible[key].ref for key in ranking.ambiguous_keys])
        if ranking.selected_key is None: return unavailable("Current cash or expenditure limits do not support an applicable research plan")
        selected = feasible[ranking.selected_key]
        fields = {"task_scope": selected.task_scope.model_dump(mode="python"), "expenditure_cap": _known(selected.expenditure_cap, "study_cap"),
            "window_ref": selected.window_ref}
        if selected.choice == "internal_study": fields["allocations"] = [row.model_dump(mode="python") for row in selected.allocations]
        elif selected.choice == "commission": fields["offer_ref"] = selected.offer_ref
        else: fields["prior_study_ref"] = selected.prior_study_ref
        return completed(selected.choice, "Bounded preliminary research decision only; external provider acceptance and formal tasks/spending remain separate; past results, actual fees and original debtor obligations remain unchanged", **fields)
    except ObservationGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
            "code": "owner_study_projection_invalid"}, "retryability": "non_retryable"}
