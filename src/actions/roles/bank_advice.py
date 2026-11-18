"""BANK-A13 conditional scenario advice; no financing or reservation effects."""
from src.actions.contracts.bank_advice_objects import (
    AdviceAssumptionView, AdviceAuthorizationView, AdviceBriefView, AdviceConditionView,
    AdviceForecastView, AdviceIssueView, AdviceMethodView, AdviceRiskMethodView,
    AdviceRiskObservationView, AdviceRuleView, AdviceSubjectView, AdviceUseView,
)
from src.actions.contracts.bank_credit_objects import CreditRiskDimensionView, unique_identities
from src.actions.contracts.common import EvidenceRecord
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.bank_credit import CreditCashInput, CreditRiskInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def advise_financing(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id
    sources, basis = {}, {}

    def current(window):
        if window.start.clock_ref != now.clock_ref:
            _unsupported('bank-advice-clock-alignment')
        if not window.contains(now):
            _needs('current_advisory_source')

    def available(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('bank-advice-clock-alignment')
        if point.offset > now.offset:
            _needs('available_advisory_source')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('bank-advice-evidence-schema')
            if row.effective_window is not None:
                current(row.effective_window)
            basis[ref.key()] = ref

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'bank-advice-projection:{ref.kind}')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'effective_window'):
            current(row.effective_window)
        if hasattr(row, 'available_at'):
            available(row.available_at)
        sources[ref.key()] = ref
        return row

    def subject(row):
        if row.owner_id != brief.owner_id or row.brief_ref != brief.ref or row.scope_ref != brief.scope_ref:
            raise ValueError('Advisory source changes owner, original brief version or scope')

    def calculate(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == 'ok':
            return result.value
        if result.kind == 'invalid_input':
            raise ValueError('Invalid declared advisory method input')
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information':
            raw['requested_refs'] = []
        raise ObservationGap(raw)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields}}

    try:
        brief = read(action_input.brief_ref, AdviceBriefView)
        advisory = read(action_input.advisory_scope_ref, AdviceAuthorizationView)
        method = read(action_input.feasibility_method_ref, AdviceMethodView)
        if (advisory.lender_id != lender or method.lender_id != lender or advisory.owner_id != brief.owner_id
                or advisory.brief_ref != brief.ref or action_input.scope_ref != brief.scope_ref
                or advisory.scope_ref != brief.scope_ref or not scope_covers(context.scope, brief.scope_ref)):
            raise ValueError('Advisory decision exceeds the original lender, brief or scope')
        if action_input.borrower != brief.borrower:
            raise ValueError('Advisory borrower state differs from the disclosed original brief')
        grant = read(advisory.authority_ref, Authorization)
        assignment = read(advisory.author_function_ref, RoleAssignment)
        current(grant.validity)
        if (grant.organization_id != lender or grant.actor_id != advisory.author_actor_id
                or grant.function_ref != advisory.author_function_ref or assignment.role != 'Bank'
                or 'BANK-A13' not in grant.action_ids
                or not any(scope_covers(s, brief.scope_ref) for s in grant.scopes)):
            _needs('authorized_advisory_scope')
        evidence(grant.basis_refs + assignment.basis_refs)
        for supplied, declared in ((action_input.option_refs, brief.option_refs),
                                  (action_input.demand_refs, brief.demand_refs),
                                  (action_input.cashflow_refs, brief.cashflow_refs)):
            unique_identities(supplied)
            if set(supplied) != set(declared):
                _needs('complete_disclosed_advisory_inputs', declared)
        allowed_subjects = {ref.key() for ref in [brief.ref, *brief.option_refs]}
        if advisory.subject_ref.key() not in allowed_subjects:
            raise ValueError('Advisory target is not an exact supplied brief or option version')
        for ref in [*brief.option_refs, *brief.demand_refs]:
            subject(read(ref, AdviceSubjectView))
        forecasts = []
        for ref in brief.cashflow_refs:
            row = read(ref, AdviceForecastView)
            subject(row)
            if row.subject_ref.key() not in allowed_subjects:
                _needs('same_version_advisory_forecast', [row.subject_ref])
            if row.subject_ref == advisory.subject_ref:
                forecasts.append(row)
        if action_input.funding_plan.state == 'known':
            subject(read(action_input.funding_plan.value, AdviceSubjectView))
        for row in forecasts:
            if row.funding_plan != action_input.funding_plan:
                _needs('same_version_advisory_funding_plan')
        decision = _known(advisory.decision, 'declared_advisory_policy')
        if decision == 'decline':
            return completed('decline_advice', note='Decline this consultation under its original authorized advisory policy; no loan decision')

        use = read(advisory.permitted_use_ref, AdviceUseView)
        if (use.brief_ref != brief.ref or use.subject_ref != advisory.subject_ref or use.scope_ref != brief.scope_ref):
            raise ValueError('Advisory permitted use changes the exact subject version or scope')
        unique_identities(advisory.unresolved_refs)
        issues = {ref.key(): ref for ref in advisory.unresolved_refs}
        for ref in issues.values():
            row = read(ref, AdviceIssueView)
            subject(row)
            if row.status != 'open' or row.subject_ref.key() not in allowed_subjects:
                _needs('current_original_advisory_issue', [ref])

        # Resolve all dependencies. A cycle remains unknown regardless of source order.
        conditions, pending = {}, list(advisory.condition_refs)
        while pending:
            ref = pending.pop()
            if ref.key() in conditions:
                continue
            unique_identities([*(r.ref for r in conditions.values()), ref])
            row = read(ref, AdviceConditionView)
            if row.brief_ref != brief.ref or row.scope_ref != brief.scope_ref:
                raise ValueError('Advisory condition changes original brief or scope')
            conditions[ref.key()] = row
            pending.extend(row.dependency_refs)
        states = {}
        for key, row in conditions.items():
            state = 'unknown'
            if (row.outcome.state == 'known' and row.verifier_authority_ref is not None and row.verified_at is not None
                    and row.verifier_function_ref is not None and row.verifier_actor_id is not None and row.verifier_action_id is not None):
                available(row.verified_at)
                verifier = read(row.verifier_authority_ref, Authorization)
                verifier_function = read(row.verifier_function_ref, RoleAssignment)
                prefixes = {'Owner': 'OWN', 'Bank': 'BANK', 'Government': 'GOV', 'Engineer': 'ENGINEER',
                            'QS': 'QS', 'Architect': 'ARCHITECT', 'Contractor': 'CONTRACTOR', 'Supplier': 'SUPPLIER'}
                if (verifier.organization_id == row.responsible_id and verifier.actor_id == row.verifier_actor_id
                        and verifier.function_ref == row.verifier_function_ref and row.verifier_action_id in verifier.action_ids
                        and row.verifier_action_id.startswith(prefixes[verifier_function.role] + '-')
                        and verifier.validity.contains(row.verified_at)
                        and any(scope_covers(s, row.scope_ref) for s in verifier.scopes)
                        and {ref.key() for ref in row.evidence_refs} <= {ref.key() for ref in verifier.readable_refs}
                        and row.evidence_refs):
                    state = row.outcome.value
            states[key] = state
        for key in conditions:
            stack, seen = [r.key() for r in conditions[key].dependency_refs], set()
            while stack:
                node = stack.pop()
                if node == key:
                    states[key] = 'unknown'
                    break
                if node not in seen:
                    seen.add(node)
                    stack.extend(r.key() for r in conditions[node].dependency_refs)
        changed = True
        while changed:
            changed = False
            for key, row in conditions.items():
                if states[key] != 'satisfied':
                    continue
                dependencies = [states[r.key()] for r in row.dependency_refs]
                state = 'unknown' if 'unknown' in dependencies else 'unsatisfied' if 'unsatisfied' in dependencies else 'satisfied'
                if state != states[key]:
                    states[key], changed = state, True
        output_conditions = []
        for key, row in conditions.items():
            output_conditions.append({'requirement_ref': row.ref, 'scope_ref': row.scope_ref,
                'responsible_id': row.responsible_id, 'evidence_refs': row.evidence_refs, 'outcome': states[key]})
            if states[key] != 'satisfied':
                issue = read(row.issue_ref, AdviceIssueView)
                subject(issue)
                if issue.status != 'open' or issue.subject_ref.key() not in allowed_subjects:
                    _needs('open_advisory_condition_issue', [issue.ref])
                issues[issue.ref.key()] = issue.ref

        risk = read(method.risk_method_ref, AdviceRiskMethodView)
        if risk.lender_id != lender:
            raise ValueError('Advisory risk method belongs to another lender')
        unique_identities(risk.dimension_refs)
        unique_identities(risk.observation_refs)
        observations = {}
        for ref in risk.observation_refs:
            row = read(ref, AdviceRiskObservationView)
            if row.subject_ref == advisory.subject_ref:
                if row.interval.state == 'known':
                    evidence([row.interval.value.lower.basis_ref, row.interval.value.upper.basis_ref])
                if row.dimension_ref.key() in observations:
                    raise ValueError('Advisory dimension has duplicate observations')
                observations[row.dimension_ref.key()] = row
        dimensions = []
        dimension_sources = {}
        for ref in risk.dimension_refs:
            dimension = read(ref, CreditRiskDimensionView)
            if dimension.risk_method_ref != risk.ref:
                raise ValueError('Advisory dimension changes its original risk method')
            observation = observations.get(ref.key())
            interval = observation.interval if observation else {'state': 'unknown', 'reason_code': 'not_disclosed', 'missing_refs': []}
            evidence([dimension.threshold.basis_ref])
            dimensions.append({'dimension_ref': ref, 'predicate': dimension.predicate,
                               'threshold': dimension.threshold, 'interval': interval})
            dimension_sources[ref.key()] = dimension
        risk_report = calculate(risk.host_method_ref, CreditRiskInput(dimensions=dimensions, source_refs=list(sources.values())))
        findings = [{'dimension_ref': r.dimension_ref, 'conclusion': r.conclusion,
                     'evidence_refs': list(basis.values()), 'method_ref': risk.ref} for r in risk_report.findings]

        assumptions = {ref.key(): ref for ref in method.assumption_refs}
        for forecast in forecasts:
            assumptions.update({ref.key(): ref for ref in forecast.assumption_refs})
        for ref in assumptions.values():
            row = read(ref, AdviceAssumptionView)
            if row.brief_ref != brief.ref:
                raise ValueError('Advisory assumption changes original brief')
        if not assumptions:
            _needs('explicit_advisory_financing_assumptions')
        unknown = {'state': 'unknown', 'reason_code': 'incomplete_disclosed_advisory_scenario', 'missing_refs': []}
        lower = upper = unknown
        hard_failure = next((dimension_sources[r.dimension_ref.key()] for r in risk_report.findings
                             if r.conclusion == 'unacceptable' and dimension_sources[r.dimension_ref.key()].hard), None)

        def inapplicable(ref):
            rule = read(ref, AdviceRuleView)
            if rule.lender_id != lender or rule.scope_ref != brief.scope_ref:
                raise ValueError('Advisory inapplicability rule changes bank or scope')
            return {'state': 'not_applicable', 'rule_ref': rule.ref}

        complete = len(forecasts) == 1 and forecasts[0].coverage == 'complete' and forecasts[0].opening_cash.state == 'known'
        if hard_failure is not None:
            lower = upper = inapplicable(hard_failure.failure_rule_ref)
        elif complete:
            forecast = forecasts[0]
            amounts = [forecast.opening_cash.value, method.minimum, method.maximum, method.requested]
            amounts.extend(value for flow in forecast.flows for value in (flow.amount.lower, flow.amount.upper))
            if any(value.currency != method.currency for value in amounts):
                _unsupported('bank-advice-currency-conversion')
            evidence([forecast.opening_cash.value.basis_ref, method.minimum.basis_ref, method.maximum.basis_ref, method.requested.basis_ref])
            for flow in forecast.flows:
                evidence(flow.evidence_refs + [flow.amount.lower.basis_ref, flow.amount.upper.basis_ref])
            cash = calculate(method.host_method_ref, CreditCashInput(
                as_of=now, horizon=forecast.horizon, currency=method.currency, minor_places=method.minor_places,
                minimum=method.minimum, maximum=method.maximum, requested=method.requested,
                opening=[{'account_ref': forecast.scenario_account_ref, 'unrestricted': forecast.opening_cash.value}],
                movements=[{'local_key': r.local_key, 'account_ref': forecast.scenario_account_ref,
                            'time': r.time, 'direction': r.direction, 'amount': r.amount} for r in forecast.flows],
                loan_account_ref=forecast.scenario_account_ref, loan_schedule=method.loan_schedule,
                basis_refs=list(basis.values()), source_refs=list(sources.values())))
            if cash.feasible:
                lower, upper = {'state': 'known', 'value': cash.rounded_lower}, {'state': 'known', 'value': cash.rounded_upper}
            else:
                lower = upper = inapplicable(method.infeasible_rule_ref)
        uncertain = not complete or any(r['conclusion'] == 'unknown' for r in findings) or action_input.borrower.state != 'known' or action_input.funding_plan.state != 'known'
        if uncertain and not issues:
            _needs('sourced_advisory_missing_input_issues')
        advice_basis = {'kind': 'brief', 'brief_ref': brief.ref} if advisory.subject_ref.key() == brief.ref.key() else {
            'kind': 'option', 'option_ref': next(ref for ref in brief.option_refs if ref.key() == advisory.subject_ref.key())}
        return completed('indicative_opinion', basis=advice_basis,
            range={'lower': lower, 'upper': upper, 'method_ref': method.ref, 'assumptions': list(assumptions.values())},
            findings=findings, conditions=output_conditions, permitted_use_ref=use.ref,
            unresolved_refs=list(issues.values()), note='Versioned scenario comparison only; forecasts and hypothetical principal are neither cash nor a quote, commitment or construction approval')
    except ObservationGap as gap:
        return gap.result
