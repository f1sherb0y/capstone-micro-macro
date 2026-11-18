"""OWN-A03 compares sourced options and proposes bounded investment authority."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_investment_objects import (
    InvestmentCaseView, InvestmentObjectiveView, InvestmentComparisonView, InvestmentOptionView,
    InvestmentAnalysisView, InvestmentConditionView, InvestmentWorkView, InvestmentPlanView,
    InvestmentRegistrationView, InvestmentPortfolioView, InvestmentFundingSourceView,
    InvestmentFundingRestrictionView, InvestmentFinanceView, InvestmentObligationView, InvestmentResourceView,
    InvestmentIssueView,
)
from src.actions.contracts.owner_proposal_objects import ProposalPriorBriefView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.owner_investment import COMPARISON_METHOD, CASH_METHOD, OptionComparisonInput, OptionMetric, CashCalendarInput
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers

ROLE_ACTIONS = {'Owner': ('OWN', 16), 'Bank': ('BANK', 13), 'Architect': ('ARCHITECT', 13),
    'Engineer': ('ENGINEER', 13), 'QS': ('QS', 13), 'Government': ('GOV', 12), 'Contractor': ('CONTRACTOR', 13), 'Supplier': ('SUPPLIER', 13)}
GOAL_METRIC = {'investment_return': 'expected_return', 'own_use': 'functional_coverage', 'public_service': 'service_coverage'}


def decide_investment(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-investment-clock')

    def available(point, field):
        clock(point)
        if point.offset > now.offset: _needs(field)

    def current(window, field):
        clock(window.start)
        if not window.contains(now): _needs(field)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-investment-evidence-schema')
            if row.effective_window is not None: current(row.effective_window, 'current_investment_evidence')

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-investment-projection:{ref.kind}')
        if hasattr(row, 'evidence_refs'): evidence(row.evidence_refs)
        return row

    def amount(value, currency):
        evidence([value.basis_ref])
        if value.currency != currency: _unsupported('owner-investment-currency-conversion')
        result = decimal_fraction(value.value)
        if result < 0: raise ValueError('Investment money cannot be negative')
        return result

    def measure(value, unit=None):
        evidence([value.basis_ref])
        if unit is not None and value.unit != unit: _unsupported('owner-investment-unit-conversion')
        return decimal_fraction(value.value)

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == 'ok': return result.value
        if result.kind == 'invalid_input': raise ValueError('Invalid sourced investment method input')
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information': raw['requested_refs'] = []
        raise ObservationGap(raw)

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'note': note, **fields}}

    def authority(ref, organization, actor, function, action, scope):
        grant = read(ref, Authorization)
        assignment = read(function, RoleAssignment)
        evidence(grant.basis_refs)
        evidence(assignment.basis_refs)
        current(grant.validity, 'current_investment_authority')
        prefix, count = ROLE_ACTIONS[assignment.role]
        if action not in {f'{prefix}-A{i:02}' for i in range(1, count + 1)}:
            raise ValueError('Authority action does not belong to the author function')
        if grant.organization_id != organization or grant.actor_id != actor or grant.function_ref != function:
            raise ValueError('Investment source authority changes organization, actor or function')
        if action not in grant.action_ids or not any(scope_covers(value, scope) for value in grant.scopes): return False
        return True

    def condition(ref, option=None):
        row = read(ref, InvestmentConditionView)
        if row.organization_id != owner or row.case_ref != case.ref or (option is not None and row.option_ref != option.ref):
            raise ValueError('Investment condition changes owner, case or option')
        if row.scope.kind != 'assessment_case' or row.scope.ref != case.ref or not scope_covers(comparison.scope, row.scope):
            raise ValueError('Investment condition changes assessment scope')
        current(row.effective_window, 'current_investment_condition')
        available(row.verified_at, 'available_investment_condition')
        evidence(row.verification_evidence_refs)
        if row.verification != 'unknown':
            if not row.verification_evidence_refs: _needs('authorized_known_condition_evidence', [row.ref])
            if not authority(row.verifier_authority_ref, row.responsible_id, row.verifier_actor_id,
                    row.verifier_function_ref, row.verifier_action_id, row.scope):
                _needs('authorized_investment_condition_verification', [row.ref])
            role = read(row.verifier_function_ref, RoleAssignment).role
            if row.condition_code == 'investment_authority' and (role != 'Owner' or row.responsible_id != owner):
                raise ValueError('Other roles cannot grant the owner investment authority')
            if row.condition_code == 'public_budget' and (role not in {'Owner', 'Government'} or role == 'Owner' and row.responsible_id != owner):
                raise ValueError('Public budget verification is outside the applicable owner/government function')
        return row

    def followup(choice, reason):
        if choice == 'reject': return completed('reject', reason + '; no project, contract or spending is created')
        if choice == 'defer':
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'owner_investment_dependencies_pending', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [comparison.ref, profile.ref, portfolio.ref],
                'earliest_time': None, 'condition_code': 'owner.investment.inputs_changed'}}
        refs, targets = profile.followup_issue_refs, profile.followup_option_refs
        if not refs: _needs('registered_investment_followup_issues')
        unique_refs(refs)
        unique_refs(targets)
        covered_options = set()
        if any(ref not in comparison.option_refs for ref in targets): raise ValueError('Followup selects an option outside the comparison')
        if targets: candidates.check_selected(choice, targets)
        for ref in refs:
            if ref not in comparison.issue_refs or ref not in case.issue_refs: raise ValueError('Followup uses an unregistered comparison issue')
            issue = read(ref, InvestmentIssueView)
            current(issue.effective_window, 'current_investment_issue')
            available(issue.available_at, 'available_investment_issue')
            if issue.case_ref != case.ref or issue.comparison_ref != comparison.ref or issue.remedy != choice:
                raise ValueError('Followup changes issue case/comparison or declared remedy')
            if issue.scope.kind != 'assessment_case' or issue.scope.ref != case.ref or not scope_covers(comparison.scope, issue.scope):
                raise ValueError('Followup changes the registered comparison scope')
            if issue.status != 'unresolved': _needs('unresolved_investment_followup_issue')
            if not targets:
                if issue.scope != comparison.scope or issue.option_refs: raise ValueError('Whole-comparison followup must retain its exact scope')
            elif not set(issue.option_refs) <= set(targets) or not issue.option_refs:
                raise ValueError('Targeted followup changes its registered option scope')
            else:
                if not issue.scope.coverage_refs: raise ValueError('Targeted issue has no bounded work')
                work_options = set()
                for item in issue.scope.coverage_refs:
                    work = read(item, InvestmentWorkView)
                    current(work.effective_window, 'current_investment_followup_work')
                    if work.case_ref != case.ref or work.option_ref not in issue.option_refs:
                        raise ValueError('Targeted issue imports work outside its own registered options')
                    work_options.add(work.option_ref)
                if work_options != set(issue.option_refs): raise ValueError('Targeted issue omits registered option work')
                covered_options.update(issue.option_refs)
        if targets and covered_options != set(targets): raise ValueError('Followup adds options without a registered issue')
        return completed(choice, reason, target_option_refs=targets, issue_refs=refs)

    def window(ref):
        value = read(ref, TimeWindow)
        clock(value.start)
        if value.bounds != 'closed_open': _unsupported('owner-investment-half-open-window')
        if value.start.offset < now.offset or value.start.offset >= value.end.offset: _needs('future_investment_planning_window', [ref])
        return value

    try:
        case = read(action_input.case_ref, InvestmentCaseView)
        objective = read(action_input.objective_ref, InvestmentObjectiveView)
        comparison = read(action_input.comparison_ref, InvestmentComparisonView)
        profile = read(action_input.registration_profile_ref, InvestmentRegistrationView)
        portfolio = read(action_input.portfolio_ref, InvestmentPortfolioView)
        candidates = read(context.candidate_set_ref, CandidateSet)
        if (case.organization_id != owner or objective.organization_id != owner or case.objective_ref != objective.ref
                or comparison.organization_id != owner or comparison.case_ref != case.ref or comparison.objective_ref != objective.ref
                or comparison.ref not in case.comparison_refs or profile.organization_id != owner
                or profile.case_ref != case.ref or profile.comparison_ref != comparison.ref or portfolio.organization_id != owner):
            raise ValueError('Investment input changes owner, objective, case or comparison version')
        if (context.scope.kind != 'assessment_case' or context.scope.ref != case.ref
                or comparison.scope.kind != 'assessment_case' or comparison.scope.ref != case.ref
                or not scope_covers(context.scope, comparison.scope) or not scope_covers(profile.permitted_scope, comparison.scope)):
            raise ValueError('Comparison exceeds the invocation or registration profile scope')
        for row, name in ((objective, 'objective'), (comparison, 'comparison'), (profile, 'registration_profile')):
            current(row.effective_window, f'current_investment_{name}')
            if hasattr(row, 'available_at'): available(row.available_at, f'available_investment_{name}')
        available(case.updated_at, 'available_investment_case')
        if portfolio.as_of != now or portfolio.coverage != 'complete': _needs('current_complete_owner_portfolio')
        supplied_lines = [row.model_dump(mode='python') for row in action_input.funding_lines]
        if supplied_lines != [row.model_dump(mode='python') for row in portfolio.funding_lines]:
            raise ValueError('Investment funding lines omit or change the current portfolio funding plan')
        policy = _known(profile.policy, 'declared_investment_policy')
        if policy == 'reject' or case.status == 'closed': return completed('reject', 'No new investment is authorized; existing fees and obligations remain unchanged')
        if policy in {'revise', 'study_more', 'defer'}: return followup(policy, 'Apply the declared bounded investment followup')
        on_infeasible = _known(profile.on_infeasible, 'investment_infeasibility_policy')
        if comparison.status != 'comparable': return followup(on_infeasible, 'The received option versions are not comparable')
        if comparison.algorithm_code != 'declared_conservative_intervals_v1': _unsupported('owner-investment-comparison-method')
        criteria = _known(objective.criteria, 'declared_objective_comparison_criteria')
        criterion_map = {row.code: row for row in criteria}
        required_metrics = {GOAL_METRIC[objective.template], 'lifecycle_cost', 'delivery_delay', 'risk'}
        if objective.template == 'public_service': required_metrics.add('accessibility')
        if not required_metrics <= set(criterion_map): _needs('complete_template_specific_comparison_criteria')
        if criterion_map[GOAL_METRIC[objective.template]].direction != 'maximize' or any(criterion_map[code].direction != 'minimize' for code in ('lifecycle_cost', 'delivery_delay', 'risk')):
            raise ValueError('Objective comparison reverses its applicable benefit/cost/time/risk meaning')
        if objective.template == 'public_service' and criterion_map['accessibility'].direction != 'maximize':
            raise ValueError('Public service comparison reverses accessibility benefit')
        if not {'cost', 'schedule', 'outcome'} <= set(comparison.required_analysis_codes): _needs('required_professional_and_outcome_analysis')
        allowed_regions = set(_known(objective.allowed_region_ids, 'investment_objective_regions'))
        allowed_uses = set(_known(objective.allowed_use_codes, 'investment_objective_uses'))
        if case.region_id not in allowed_regions or case.use_code not in allowed_uses:
            raise ValueError('Investment case changes objective region or use scope')
        option_rows, comparable, plans, conditions, problems = {}, [], {}, {}, set()
        for ref in comparison.option_refs:
            option = read(ref, InvestmentOptionView)
            if (option.organization_id != owner or option.case_ref != case.ref or option.comparison_ref != comparison.ref
                    or option.objective_ref != objective.ref or option.brief_ref not in case.brief_refs):
                raise ValueError('Option changes owner, objective, comparison, case or registered brief')
            available(option.available_at, 'available_investment_option')
            current(option.effective_window, 'current_investment_option')
            brief = read(option.brief_ref, ProposalPriorBriefView)
            current(brief.effective_window, 'current_investment_brief')
            available(brief.available_at, 'available_investment_brief')
            if (brief.organization_id != owner or brief.case_ref != case.ref or brief.objective_ref != objective.ref
                    or brief.status != 'active' or brief.brief.intervention != option.intervention):
                raise ValueError('Option is detached from the exact active brief')
            if not set(brief.brief.region_ids) <= allowed_regions or case.use_code not in allowed_uses:
                raise ValueError('Option changes objective region or use scope')
            if (ref in comparison.non_build_option_refs) != (option.intervention == 'non_build'):
                raise ValueError('Comparison disguises a construction option as the non-build baseline')
            metrics, analyses = {}, set()
            for analysis_ref in option.analysis_refs:
                analysis = read(analysis_ref, InvestmentAnalysisView)
                for supplied, expected in ((analysis.option_ref, option.ref), (analysis.brief_ref, option.brief_ref), (analysis.objective_ref, objective.ref)):
                    if (supplied.kind, supplied.id) != (expected.kind, expected.id):
                        raise ValueError('Comparison imports an analysis of another option/brief/objective')
                    if supplied.version != expected.version:
                        _needs('same_version_comparable_investment_analyses', [analysis.ref])
                available(analysis.available_at, 'available_investment_analysis')
                current(analysis.effective_window, 'current_investment_analysis')
                if analysis.status != 'final': _needs('final_current_investment_analysis', [analysis.ref])
                if not _known(analysis.qualified, 'investment_analysis_qualification'): _needs('qualified_investment_analysis')
                if not authority(analysis.authority_ref, analysis.organization_id, analysis.author_actor_id,
                        analysis.author_function_ref, analysis.authority_action_id, comparison.scope): _needs('authorized_investment_analysis')
                if analysis.analysis_code in analyses: raise ValueError('Analysis category repeated')
                analyses.add(analysis.analysis_code)
                for metric in analysis.metrics:
                    if metric.code in metrics: raise ValueError('Forecast criterion double counted')
                    bounds = _known(metric.value, 'known_forecast_interval')
                    if metric.code not in criterion_map: raise ValueError('Forecast adds an undeclared criterion')
                    if metric.code == 'lifecycle_cost' and analysis.analysis_code != 'cost' or metric.code == 'delivery_delay' and analysis.analysis_code != 'schedule':
                        raise ValueError('Cost or schedule forecast is detached from its declared analysis category')
                    measure(bounds.lower, criterion_map[metric.code].scale.unit)
                    measure(bounds.upper, criterion_map[metric.code].scale.unit)
                    metrics[metric.code] = OptionMetric(code=metric.code, lower=bounds.lower, upper=bounds.upper)
            if not set(comparison.required_analysis_codes) <= analyses or set(metrics) != set(criterion_map): _needs('complete_comparable_investment_analyses')
            comparable.append({'option_ref': option.ref, 'metrics': list(metrics.values())})
            current_conditions = {item.key(): condition(item, option) for item in option.condition_refs}
            conditions[option.ref.key()] = current_conditions
            if not set(brief.brief.unresolved_refs) <= set(option.issue_refs): raise ValueError('Option drops an unresolved brief dependency')
            for issue_ref in option.issue_refs:
                if issue_ref not in case.issue_refs or issue_ref not in comparison.issue_refs: raise ValueError('Option uses an unregistered issue')
                issue = read(issue_ref, InvestmentIssueView)
                current(issue.effective_window, 'current_investment_option_issue')
                available(issue.available_at, 'available_investment_option_issue')
                if issue.case_ref != case.ref or issue.comparison_ref != comparison.ref or option.ref not in issue.option_refs:
                    raise ValueError('Option issue changes case/comparison/scope')
                if issue.scope.kind != 'assessment_case' or issue.scope.ref != case.ref or not scope_covers(comparison.scope, issue.scope):
                    raise ValueError('Option issue changes its comparison work scope')
                if issue.status == 'unresolved': problems.add(option.ref.key())
            option_plans = []
            for plan_ref, choice in ((option.investment_plan_ref, 'invest'), (option.preparation_plan_ref, 'authorize_preparation')):
                if plan_ref is None: continue
                plan = read(plan_ref, InvestmentPlanView)
                if (plan.organization_id != owner or plan.case_ref != case.ref or plan.option_ref != option.ref or plan.choice != choice
                        or plan.scope.scope_ref.kind != 'assessment_case' or plan.scope.scope_ref.ref != case.ref):
                    raise ValueError('Investment plan changes owner, option, choice or case scope')
                current(plan.effective_window, 'current_investment_plan')
                available(plan.available_at, 'available_investment_plan')
                unique_refs(plan.scope.scope_ref.coverage_refs)
                unique_refs(plan.scope.condition_refs)
                evidence(plan.scope.basis_refs)
                if not plan.scope.scope_ref.coverage_refs or not scope_covers(comparison.scope, plan.scope.scope_ref): raise ValueError('Plan is outside the bounded comparison work')
                if not set(plan.required_condition_refs) <= set(option.condition_refs) or not set(plan.scope.condition_refs) <= set(option.condition_refs):
                    raise ValueError('Plan imports conditions outside the selected option')
                if not set(plan.required_condition_refs) <= set(plan.scope.condition_refs): raise ValueError('Plan hides its required conditions from the authorized scope')
                if plan.cost_analysis_ref not in option.analysis_refs or read(plan.cost_analysis_ref, InvestmentAnalysisView).analysis_code != 'cost':
                    raise ValueError('Plan is detached from the exact option cost analysis')
                currency = criterion_map['lifecycle_cost'].scale.unit
                incurred = amount(_known(plan.incurred_cost, 'actual_incurred_option_cost'), currency)
                cap = amount(_known(plan.expenditure_cap, 'bounded_option_expenditure_cap'), currency)
                future = sum((amount(_known(row.amount, 'complete_option_cash_schedule'), currency) for row in plan.cash_uses), Fraction())
                if incurred + future > cap: continue
                if choice == 'invest' and incurred + future != measure(metrics['lifecycle_cost'].upper, currency):
                    _needs('complete_cost_analysis_aligned_cash_schedule')
                work_allowed = True
                for work_ref in plan.scope.scope_ref.coverage_refs:
                    work = read(work_ref, InvestmentWorkView)
                    current(work.effective_window, 'current_investment_work')
                    if work.case_ref != case.ref or work.option_ref != option.ref: raise ValueError('Plan imports work from another option')
                    work_allowed &= choice in work.permitted_choices
                if not _known(plan.permitted, 'investment_plan_permission') or not work_allowed: continue
                if not authority(plan.authority_ref, owner, context.actor_id, context.function_ref, 'OWN-A03', plan.scope.scope_ref): continue
                if read(context.function_ref, RoleAssignment).role != 'Owner': raise ValueError('Investment permission requires the Owner function')
                hard = set(plan.required_condition_refs) | set(plan.scope.condition_refs)
                if choice == 'invest':
                    required_codes = {'investment_authority', 'rights', 'project_registration', *profile.required_investment_condition_codes}
                    if objective.template == 'public_service': required_codes.add('public_budget')
                    by_code = {}
                    for row in current_conditions.values(): by_code.setdefault(row.condition_code, []).append(row)
                    if not required_codes <= set(by_code): _needs('declared_complete_project_registration_conditions')
                    hard.update(row.ref for code in required_codes for row in by_code[code])
                    if not hard <= set(plan.scope.condition_refs): raise ValueError('Investment scope hides necessary registration conditions')
                    if policy == 'prepare_only' or option.ref.key() in problems: continue
                if any(current_conditions[item.key()].verification != 'met' or not scope_covers(current_conditions[item.key()].scope, plan.scope.scope_ref) for item in hard): continue
                option_plans.append(plan)
            plans[option.ref.key()] = option_plans
            option_rows[option.ref.key()] = option
        # Preserve the complete comparison before financial/authority exclusions.
        method(COMPARISON_METHOD, OptionComparisonInput(criteria=criteria, options=comparable, source_refs=[objective.ref, comparison.ref, *comparison.option_refs]))
        sources, accounts, inflows, outflows, arrangement_used = {}, [], [], [], {}
        currency = criterion_map['lifecycle_cost'].scale.unit
        releases = set()
        for ref in portfolio.source_refs:
            source = read(ref, InvestmentFundingSourceView)
            if source.organization_id != owner: raise ValueError('Funding source belongs to another organization')
            if source.as_of != now or source.coverage != 'complete': _needs('current_complete_investment_cash_sources')
            _known(source.deduction_policy, 'investment_cash_deduction_policy')
            cash = _known(source.actual_cash, 'actual_investment_cash')
            restricted = _known(source.restricted_cash, 'restricted_investment_cash')
            free = amount(cash, currency) - amount(restricted, currency)
            if free < 0: raise ValueError('Restricted investment cash exceeds actual cash')
            sources[source.ref.key()] = source
            accounts.append({'source_ref': source.ref, 'opening_available': cash.model_copy(update={'value': exact_decimal(free)})})
            for release in source.releases:
                identity = (release.ref.kind, release.ref.id)
                if identity in releases: raise ValueError('Funding release repeated across sources')
                releases.add(identity)
                available(release.available_at, 'available_funding_release')
                clock(release.time)
                if release.state in {'forecast', 'cancelled'}: continue
                if release.state == 'received':
                    if release.time.offset > now.offset: raise ValueError('Future funding cannot be received now')
                    continue
                if release.time.offset < now.offset: _needs('reconciled_overdue_funding_release')
                if release.arrangement_ref is None: _needs('effective_exact_finance_arrangement')
                arrangement = read(release.arrangement_ref, InvestmentFinanceView)
                current(arrangement.effective_window, 'current_investment_finance_arrangement')
                if arrangement.borrower_organization_id != owner or arrangement.source_ref != source.ref:
                    raise ValueError('Funding release changes borrower or account')
                if arrangement.status != 'active': continue
                unique_refs(release.condition_refs)
                unique_refs(arrangement.condition_refs)
                if not set(arrangement.condition_refs) <= set(release.condition_refs): raise ValueError('Funding release omits finance conditions')
                if any(condition(item).verification != 'met' for item in release.condition_refs): continue
                release_amount = _known(release.amount, 'known_committed_funding_release')
                drawn = amount(release_amount, currency)
                limit = amount(_known(arrangement.undrawn_amount, 'actual_undrawn_finance_limit'), currency)
                used = arrangement_used.get(arrangement.ref.key(), Fraction()) + drawn
                if used > limit: raise ValueError('Future releases exceed the actual undrawn arrangement limit')
                arrangement_used[arrangement.ref.key()] = used
                inflows.append({'local_key': 'release:'+release.ref.id, 'source_ref': source.ref, 'time': release.time, 'amount': release_amount})
        for ref in portfolio.obligation_refs:
            debt = read(ref, InvestmentObligationView)
            if debt.debtor_organization_id != owner or debt.source_ref.key() not in sources: raise ValueError('Portfolio changes the original debt payer or source')
            if debt.as_of != now: _needs('current_actual_investment_obligations')
            clock(debt.due_at)
            due, paid = _known(debt.actual_due, 'actual_due_investment_obligation'), _known(debt.actual_paid, 'actual_paid_investment_obligation')
            outstanding = amount(due, currency) - amount(paid, currency)
            if outstanding < 0: raise ValueError('Portfolio payment exceeds actual debt')
            if outstanding:
                outflows.append({'local_key': 'debt:'+debt.ref.id, 'source_ref': debt.source_ref,
                    'time': debt.due_at.model_copy(update={'offset': max(debt.due_at.offset, now.offset)}),
                    'amount': due.model_copy(update={'value': exact_decimal(outstanding)})})
        lines = {}
        for line in portfolio.funding_lines:
            if line.source_ref.key() not in sources: raise ValueError('Funding plan imports a source outside the owner portfolio')
            w = window(line.window_ref)
            unique_refs(line.restriction_refs)
            declared = _known(line.available, 'sourced_period_funding_availability')
            planned = _known(line.planned_use, 'bounded_period_funding_use')
            if amount(planned, currency) > amount(declared, currency): return followup(on_infeasible, 'The declared period funding plan exceeds its available limit')
            lines[(line.source_ref.key(), line.window_ref.key())] = (line, w)
        resources = {}
        for ref in portfolio.resource_refs:
            pool = read(ref, InvestmentResourceView)
            if pool.organization_id != owner: raise ValueError('Portfolio cannot copy another owner management pool')
            if pool.as_of != now or pool.coverage != 'complete': _needs('current_complete_investment_management_load')
            current(pool.effective_window, 'current_investment_management_pool')
            resources[ref.key()] = pool
        viable = {}
        for option_key, option_plans in plans.items():
            for plan in option_plans:
                proposed, period_uses, restricted_plan = [], {}, False
                for use in plan.cash_uses:
                    item = lines.get((use.source_ref.key(), use.window_ref.key()))
                    if item is None: _needs('registered_exact_option_funding_period')
                    line, w = item
                    value = _known(use.amount, 'known_option_cash_use')
                    cost = amount(value, currency)
                    identity = (use.source_ref.key(), use.window_ref.key())
                    period_uses[identity] = period_uses.get(identity, Fraction()) + cost
                    if period_uses[identity] > amount(_known(line.planned_use, 'period_funding_limit'), currency): restricted_plan = True
                    for restriction_ref in line.restriction_refs:
                        restriction = read(restriction_ref, InvestmentFundingRestrictionView)
                        current(restriction.effective_window, 'current_investment_funding_restriction')
                        if restriction.organization_id != owner or restriction.source_ref != use.source_ref: raise ValueError('Funding restriction changes owner or source')
                        if not _known(restriction.permitted, 'investment_funding_scope_permission') or not scope_covers(restriction.permitted_scope, plan.scope.scope_ref): restricted_plan = True
                    proposed.append({'local_key': 'proposal:'+use.local_key, 'source_ref': use.source_ref, 'time': w.start, 'amount': value})
                if restricted_plan: continue
                cash_report = method(CASH_METHOD, CashCalendarInput(clock_ref=now.clock_ref, as_of=now, accounts=accounts,
                    inflows=inflows, existing_outflows=outflows, proposed_outflows=proposed, source_refs=[portfolio.ref, plan.ref, *portfolio.source_refs, *portfolio.obligation_refs]))
                if not cash_report.feasible: continue
                cap_resources, demands, commitments, groups = [], [], [], {}
                for allocation in plan.allocations:
                    if allocation.resource_ref.key() not in resources: raise ValueError('Plan imports an unlisted management pool')
                    pool = resources[allocation.resource_ref.key()]
                    if not authority(pool.authority_ref, owner, context.actor_id, pool.function_ref, 'OWN-A03', plan.scope.scope_ref):
                        restricted_plan = True; break
                    if read(pool.function_ref, RoleAssignment).role != 'Owner': raise ValueError('Management pool does not belong to the owner function')
                    total, quantity = _known(pool.total, 'actual_investment_management_capacity'), _known(allocation.quantity, 'known_investment_management_use')
                    if measure(total) < 0 or measure(quantity, total.unit) <= 0: raise ValueError('Management capacity/use has an invalid sign')
                    w = window(allocation.window_ref)
                    identity = (pool.ref.key(), allocation.window_ref.key())
                    if identity not in groups: groups[identity] = [pool, total, w, Fraction()]
                    groups[identity][3] += measure(quantity, total.unit)
                if restricted_plan: continue
                used_pools = {}
                for pool, total, w, needed in groups.values():
                    used_pools[pool.ref.key()] = (pool, total)
                    demands.append({'resource_kind': pool.ref.id, 'region_id': case.region_id, 'unit': total.unit,
                        'amount': ExactAmount.from_fraction(needed), 'window': w, 'basis_refs': pool.evidence_refs})
                for pool, total in used_pools.values():
                    cap_resources.append({'resource_ref': pool.ref, 'resource_kind': pool.ref.id, 'region_id': case.region_id,
                        'total': total, 'effective_window': pool.effective_window})
                    for load in pool.commitments:
                        clock(load.window.start)
                        if load.window.bounds != 'closed_open': _unsupported('owner-investment-load-window')
                        if measure(load.quantity, total.unit) <= 0: raise ValueError('Management commitment must be positive')
                        commitments.append({'commitment_ref': load.ref, 'resource_ref': pool.ref, 'quantity': load.quantity, 'window': load.window})
                capacity = method(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, resources=cap_resources, demands=demands,
                    commitments=commitments, source_refs=[portfolio.ref, plan.ref, *[pool.ref for pool, _ in used_pools.values()]]))
                if capacity.feasible:
                    viable[option_key] = plan
                    break
        eligible = [row for row in comparable if row['option_ref'].key() in viable]
        if not eligible: return followup(on_infeasible, 'Necessary conditions, current portfolio cash timing or shared management capacity do not support an applicable plan')
        ranking = method(COMPARISON_METHOD, OptionComparisonInput(criteria=criteria, options=eligible, source_refs=[objective.ref, comparison.ref, *[row['option_ref'] for row in eligible]]))
        if len(ranking.preferred_refs) != 1: _needs('unique_conservative_option_preference', ranking.preferred_refs)
        selected = option_rows[ranking.preferred_refs[0].key()]
        plan = viable[selected.ref.key()]
        if plan.choice == 'invest':
            if selected.intervention == 'non_build': _unsupported('owner-non-build-transaction-entry')
            if profile.registration_code != 'declared_construction_project_v1': _unsupported('owner-project-registration-path')
        candidates.check_selected(plan.choice, [selected.ref])
        rows = conditions[selected.ref.key()].values()
        if plan.choice == 'invest':
            rows = [row for row in rows if row.ref in plan.scope.condition_refs]
        output_conditions = [{'requirement_ref': row.ref, 'responsible_id': row.responsible_id,
            'evidence_refs': row.verification_evidence_refs, 'verification': row.verification} for row in rows]
        return completed(plan.choice, 'Select one exact compared option with bounded authority; forecast scores and contractual future cash do not create received money, a project, blanket construction permission or payment',
            option_ref=selected.ref, scope=plan.scope.model_dump(mode='python'), conditions=output_conditions)
    except ObservationGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
            'code': 'owner_investment_projection_invalid'}, 'retryability': 'non_retryable'}
