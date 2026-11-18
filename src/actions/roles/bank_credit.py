"""BANK-A03 authorized review; no approval, commitment or loan effects."""
from src.actions.contracts.bank_credit_objects import (
    CreditAccountView, CreditAssumptionView, CreditConditionView,
    CreditDebtComponentView, CreditDebtView, CreditFeasibilityMethodView,
    CreditFinancialForecastView, CreditObligationView, CreditPortfolioView,
    CreditRiskDimensionView, CreditRiskMethodView, CreditRiskObservationView,
    CreditRuleView, CreditCaseView, CreditProjectView, CreditWorkView, unique_identities,
    CreditBankPortfolioView, CreditLendingCapacityView, CreditCommitmentView,
)
from src.actions.contracts.bank_objects import (
    BorrowerOrganizationView, FinanceApplicationView, FinanceProductProfileView,
    FundingPurposeView,
)
from src.actions.contracts.common import EvidenceRecord, Money
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.bank_credit import (
    CreditCashInput, CreditCashMovement, CreditOpeningCash, CreditRiskInput,
    CreditRiskInputDimension,
)
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def review_credit(context, action_input, reading, *, capacity_ref=None, extra_condition_refs=()):
    now, lender = context.business_time, reading.organization_id
    sources, basis = {}, {}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('bank-credit-clock-alignment')

    def current(window, field, point=None):
        clock(window.start)
        if not window.contains(point or now):
            _needs(field)

    def available(point, field, exact=False):
        clock(point)
        if point.offset > now.offset or (exact and point != now):
            _needs(field)

    def evidence(refs, point=None):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('bank-credit-evidence-schema')
            if row.effective_window is not None:
                current(row.effective_window, 'applicable_credit_evidence', point)
            basis[ref.key()] = ref

    def read(ref, schema, point=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'bank-credit-projection:{ref.kind}')
        evidence(getattr(row, 'evidence_refs', []), point)
        sources[ref.key()] = ref
        return row

    def amount(value):
        evidence([value.basis_ref])
        if value.currency != application.requested.currency:
            _unsupported('bank-credit-currency-conversion')
        return decimal_fraction(value.value)

    def money(value, ref):
        return Money(value=exact_decimal(value), currency=application.requested.currency, basis_ref=ref)

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == 'ok':
            return result.value
        if result.kind == 'invalid_input':
            raise ValueError('Invalid declared credit method input')
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information':
            raw['requested_refs'] = []
        raise ObservationGap(raw)

    def rule(ref):
        row = read(ref, CreditRuleView)
        if row.lender_id != lender or row.product_ref != product.ref:
            raise ValueError('Credit decline rule changes lender or product version')
        current(row.effective_window, 'current_credit_decline_rule')
        return row.ref

    def completed(choice, note, assessed, findings=(), conditions=()):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'findings': list(findings),
                'conditions': list(conditions), 'assessed_amount': assessed, 'note': note}}

    def decline(note, rule_ref=None, findings=(), conditions=()):
        return completed('decline', note, {'state': 'not_applicable',
                         'rule_ref': rule(rule_ref or risk.decline_rule_ref)}, findings, conditions)

    def applicable_authority(ref, actor, organization, function, action, scope, point):
        grant = read(ref, Authorization, point)
        assignment = read(function, RoleAssignment, point)
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], point)
            else:
                reading.resolve(basis_ref)
                sources[basis_ref.key()] = basis_ref
        clock(grant.validity.start)
        return (grant.actor_id == actor and grant.organization_id == organization and grant.function_ref == function
                and assignment.function_ref == function
                and action in grant.action_ids and grant.validity.contains(point)
                and any(scope_covers(value, scope) for value in grant.scopes)
                and action.split('-', 1)[0] == {'Owner': 'OWN', 'Bank': 'BANK', 'Government': 'GOV',
                    'Engineer': 'ENGINEER', 'QS': 'QS', 'Architect': 'ARCHITECT',
                    'Contractor': 'CONTRACTOR', 'Supplier': 'SUPPLIER'}[assignment.role])

    def condition_set(initial):
        """Resolve the full dependency graph and retain cycles as blockers."""
        rows, pending = {}, list(initial)
        while pending:
            ref = pending.pop()
            if ref.key() in rows:
                continue
            unique_identities([*(row.ref for row in rows.values()), ref])
            # Resolve the typed record before checking evidence: the generic
            # current read would reject valid historical verification first.
            row = reading.resolve(ref)
            if not isinstance(row, CreditConditionView):
                _unsupported(f'bank-credit-projection:{ref.kind}')
            point = row.verification.verified_at if row.verification is not None else now
            available(point, 'available_credit_condition_verification')
            evidence(row.evidence_refs, point)
            sources[ref.key()] = ref
            if (row.application_ref != application.ref or row.product_ref != product.ref
                    or not scope_covers(row.scope_ref, application.scope_ref)):
                raise ValueError('Credit condition changes application, product or scope')
            current(row.effective_window, 'current_credit_condition')
            rows[ref.key()] = row
            pending.extend(row.dependency_refs)
        verified_states = {}
        for key, row in rows.items():
            state = row.outcome.value if row.outcome.state == 'known' else 'unknown'
            if row.outcome.state == 'not_supported':
                _known(row.outcome, 'supported_credit_condition')
            if row.verification is not None:
                verification = row.verification
                if (verification.organization_id not in _known(row.authorized_verifier_organization_ids, 'credit_condition_verifiers')
                        or verification.action_id not in _known(row.authorized_verifier_action_ids, 'credit_condition_verifier_actions')):
                    _needs('applicable_credit_condition_verifier', [row.ref])
                if not applicable_authority(verification.authority_ref, verification.actor_id,
                    verification.organization_id, verification.function_ref, verification.action_id,
                    row.scope_ref, verification.verified_at):
                    _needs('authorized_credit_condition_verification', [verification.authority_ref])
                # The verifier must actually be permitted to read its asserted evidence.
                grant = read(verification.authority_ref, Authorization, verification.verified_at)
                if not {ref.key() for ref in row.evidence_refs} <= {ref.key() for ref in grant.readable_refs}:
                    _needs('authorized_credit_condition_evidence', list(row.evidence_refs))
                evidence(row.evidence_refs, verification.verified_at)
            elif state == 'unsatisfied':
                # An unverified negative assertion is uncertainty, not proven failure.
                state = 'unknown'
            verified_states[key] = state

        # A dependency cycle is unresolved even when every recorded local
        # assertion says satisfied. Find cycles independently of traversal order,
        # then propagate known unsatisfied/unknown prerequisites to a fixed point.
        statuses = dict(verified_states)
        for start in rows:
            stack, seen = [ref.key() for ref in rows[start].dependency_refs], set()
            while stack:
                key = stack.pop()
                if key == start:
                    if statuses[start] == 'satisfied':
                        statuses[start] = 'unknown'
                    break
                if key not in seen:
                    seen.add(key)
                    stack.extend(ref.key() for ref in rows[key].dependency_refs)
        changed = True
        while changed:
            changed = False
            for key, row in rows.items():
                if verified_states[key] != 'satisfied':
                    continue
                dependencies = [statuses[ref.key()] for ref in row.dependency_refs]
                state = 'unknown' if statuses[key] == 'unknown' or 'unknown' in dependencies else (
                    'unsatisfied' if 'unsatisfied' in dependencies else 'satisfied')
                if state != statuses[key]:
                    statuses[key] = state
                    changed = True

        return rows, [{'requirement_ref': row.ref, 'scope_ref': row.scope_ref,
            'responsible_id': row.responsible_id, 'evidence_refs': row.evidence_refs,
            'outcome': statuses[key]} for key, row in sorted(rows.items(), key=lambda pair: repr(pair[0]))]

    try:
        application = read(action_input.application_ref, FinanceApplicationView)
        product = read(action_input.product_ref, FinanceProductProfileView)
        risk = read(action_input.risk_method_ref, CreditRiskMethodView)
        if (application.lender_id != lender or product.lender_id != lender or risk.lender_id != lender
                or risk.product_ref != product.ref or product.ref not in application.product_candidates):
            raise ValueError('Credit review changes the exact application lender or selected product')
        if not (scope_covers(context.scope, application.scope_ref)
                or (context.scope.kind == 'organization' and context.scope.ref.id == lender)):
            raise ValueError('Credit review exceeds its authorized application scope')
        unique_identities(action_input.disclosures)
        unique_identities(action_input.forecast_refs)
        unique_identities(action_input.debt_refs)
        unique_identities(action_input.permit_risk_refs)
        if not set(application.disclosure_refs) <= set(action_input.disclosures):
            _needs('complete_application_disclosures', application.disclosure_refs)
        evidence(action_input.disclosures)
        current(risk.effective_window, 'current_risk_method')
        current(product.effective_window, 'current_credit_product')
        available(application.submitted_at, 'submitted_credit_application')
        if application.status == 'draft':
            _needs('submitted_credit_application')
        if application.status == 'withdrawn':
            return decline('The submitted application has been withdrawn')
        if not applicable_authority(application.applicant_authority_ref, application.applicant_actor_id,
            application.borrower_id, application.applicant_function_ref, application.originating_action_id,
            application.scope_ref, application.submitted_at):
            return decline('The submitted application lacks original borrower authority')
        borrower = read(application.borrower_ref, BorrowerOrganizationView)
        purpose = read(application.purpose_ref, FundingPurposeView)
        if purpose.borrower_ref != borrower.ref or purpose.scope_ref != application.scope_ref:
            raise ValueError('Credit purpose changes borrower or application scope')
        if application.scope_ref.kind != 'organization':
            scope_object = read(application.scope_ref.ref,
                CreditCaseView if application.scope_ref.kind == 'assessment_case' else CreditProjectView)
            if scope_object.borrower_id != application.borrower_id:
                raise ValueError('Application scope belongs to another borrower')
            if (application.scope_ref.kind == 'project'
                    and scope_object.region_id != _known(purpose.project_region_id, 'credit_project_region')):
                raise ValueError('Funding purpose changes the original formal project region')
            available(scope_object.available_at, 'available_credit_scope')
            if scope_object.status != 'active':
                _needs('active_credit_scope')
        elif application.scope_ref.ref != borrower.ref:
            raise ValueError('Organizational application scope differs from its borrower')
        for ref in application.scope_ref.coverage_refs:
            work = read(ref, CreditWorkView)
            if work.borrower_id != application.borrower_id or not scope_covers(work.scope_ref, application.scope_ref):
                raise ValueError('Application work scope changes borrower or coverage')
            current(work.effective_window, 'current_credit_work_scope')
        current(borrower.effective_window, 'current_credit_borrower')
        current(purpose.effective_window, 'current_credit_purpose')
        if not _known(borrower.legal_standing, 'borrower_legal_standing'):
            return decline('Known legal-standing evidence rules out this borrower')
        checks = [(borrower.registration_region_id, product.allowed_registration_region_ids, 'registration'),
                  (purpose.project_region_id, product.allowed_project_region_ids, 'project_region'),
                  (purpose.purpose_code, product.allowed_purpose_codes, 'purpose'),
                  (purpose.stage, product.allowed_stages, 'stage')]
        for actual, allowed, field in checks:
            if _known(actual, field) not in _known(allowed, f'product:{field}'):
                return decline(f'The selected product does not cover {field}')
        operating = _known(borrower.operating_region_ids, 'borrower_operating_regions')
        if not operating:
            _needs('borrower_operating_regions')
        if not set(operating) <= set(_known(product.allowed_operating_region_ids, 'product_operating_regions')):
            return decline('The selected product does not cover borrower operating regions')
        if application.requested.currency not in _known(product.allowed_currencies, 'product_currencies'):
            return decline('The selected product does not cover the requested currency')
        if amount(application.requested) <= 0:
            return decline('The submitted request is not positive')
        disclosures = {row.disclosure_code: row.evidence_ref for row in application.disclosures}
        for code in _known(product.required_disclosure_codes, 'required_credit_disclosures'):
            if code not in disclosures:
                _needs(f'disclosure:{code}')
            evidence([disclosures[code]])

        feasibility = read(risk.feasibility_method_ref, CreditFeasibilityMethodView)
        if feasibility.lender_id != lender or feasibility.product_ref != product.ref:
            raise ValueError('Feasibility method changes lender or product version')
        current(feasibility.effective_window, 'current_credit_feasibility_method')
        if feasibility.currency != application.requested.currency:
            _unsupported('bank-credit-currency-conversion')
        assumption_refs = {ref.key(): ref for ref in feasibility.assumption_refs}
        if not action_input.forecast_refs:
            _needs('complete_credit_forecast')
        forecasts = [read(ref, CreditFinancialForecastView) for ref in action_input.forecast_refs]
        first = forecasts[0]
        for forecast in forecasts:
            if (forecast.application_ref != application.ref or forecast.borrower_id != application.borrower_id
                    or forecast.scope_ref != application.scope_ref or forecast.portfolio_ref != first.portfolio_ref
                    or forecast.loan_account_ref != first.loan_account_ref or forecast.horizon != first.horizon):
                raise ValueError('Credit forecasts mix applications, borrowers, portfolios or horizons')
            if set(forecast.review_forecast_refs) != set(action_input.forecast_refs):
                _needs('complete_credit_forecast_set', forecast.review_forecast_refs)
            available(forecast.as_of, 'current_credit_forecast', exact=True)
            if forecast.coverage != 'complete':
                _needs('complete_credit_forecast_coverage')
            for flow in forecast.flows:
                assumption_refs[flow.assumption_ref.key()] = flow.assumption_ref
        for ref in assumption_refs.values():
            assumption = read(ref, CreditAssumptionView)
            if assumption.method_ref != feasibility.ref:
                raise ValueError('Cash forecast assumption changes its declared feasibility method')
            current(assumption.effective_window, 'current_credit_assumption')

        observations = {}
        for ref in [ref for forecast in forecasts for ref in forecast.risk_observation_refs] + action_input.permit_risk_refs:
            observations[ref.key()] = read(ref, CreditRiskObservationView)
        unique_identities([row.ref for row in observations.values()])
        if {row.ref for row in observations.values() if row.category == 'permit'} != set(action_input.permit_risk_refs):
            _needs('complete_permit_risk_observations')
        by_dimension = {}
        for observation in observations.values():
            if (observation.application_ref != application.ref or observation.borrower_id != application.borrower_id
                    or not scope_covers(observation.scope_ref, application.scope_ref)):
                raise ValueError('Risk observation changes application, borrower or scope')
            available(observation.observed_at, 'available_credit_risk_observation')
            current(observation.effective_window, 'current_credit_risk_observation')
            if observation.dimension_ref.key() in by_dimension:
                raise ValueError('Credit review requires one explicit observation per dimension')
            by_dimension[observation.dimension_ref.key()] = observation
        if set(by_dimension) != {ref.key() for ref in risk.dimension_refs}:
            _needs('complete_credit_risk_dimensions')
        dimensions, method_dimensions = [], []
        for ref in risk.dimension_refs:
            dimension = read(ref, CreditRiskDimensionView)
            if dimension.risk_method_ref != risk.ref:
                raise ValueError('Risk dimension changes its original risk method version')
            current(dimension.effective_window, 'current_credit_risk_dimension')
            evidence([dimension.threshold.basis_ref])
            observation = by_dimension[ref.key()]
            if observation.interval.state == 'not_supported':
                _known(observation.interval, 'credit_risk_observation')
            if observation.interval.state == 'not_applicable':
                _unsupported('bank-credit-risk-applicability')
            if observation.interval.state == 'known':
                for endpoint in (observation.interval.value.lower, observation.interval.value.upper):
                    evidence([endpoint.basis_ref])
                    if endpoint.unit != dimension.threshold.unit:
                        _unsupported('bank-credit-risk-unit-conversion')
            dimensions.append(dimension)
            method_dimensions.append(CreditRiskInputDimension(dimension_ref=ref, predicate=dimension.predicate,
                threshold=dimension.threshold, interval=observation.interval))
        risk_report = method(risk.host_method_ref, CreditRiskInput(dimensions=method_dimensions,
                             source_refs=list(sources.values())))
        if {row.dimension_ref for row in risk_report.findings} != set(risk.dimension_refs):
            raise ValueError('Risk method report omits or substitutes a dimension')
        conclusions = {row.dimension_ref.key(): row.conclusion for row in risk_report.findings}
        findings = []
        for dimension in dimensions:
            observation = by_dimension[dimension.ref.key()]
            evidence_refs = dimension.evidence_refs + observation.evidence_refs + [dimension.threshold.basis_ref]
            if observation.interval.state == 'known':
                evidence_refs += [observation.interval.value.lower.basis_ref, observation.interval.value.upper.basis_ref]
            findings.append({'dimension_ref': dimension.ref, 'conclusion': conclusions[dimension.ref.key()],
                'evidence_refs': list({ref.key(): ref for ref in evidence_refs}.values()), 'method_ref': risk.ref})
        condition_refs = list(product.required_condition_refs)
        condition_refs.extend(extra_condition_refs)
        condition_refs.extend(row.remedial_condition_ref for row in dimensions if row.remedial_condition_ref is not None)
        _, conditions = condition_set(condition_refs)
        for dimension in dimensions:
            conclusion = conclusions[dimension.ref.key()]
            if dimension.hard and conclusion == 'unacceptable':
                return decline('A supplied hard risk dimension is unacceptable', dimension.failure_rule_ref, findings, conditions)
        unknown_hard = [row.ref for row in dimensions if row.hard and conclusions[row.ref.key()] == 'unknown']
        if unknown_hard:
            _needs('determinate_hard_credit_risk', unknown_hard)

        portfolio = read(first.portfolio_ref, CreditPortfolioView)
        if portfolio.borrower_id != application.borrower_id:
            raise ValueError('Disclosed portfolio belongs to another legal borrower')
        available(portfolio.as_of, 'current_disclosed_credit_portfolio', exact=True)
        if portfolio.coverage != 'complete':
            _needs('complete_disclosed_credit_portfolio')
        if set(portfolio.debt_refs) != set(action_input.debt_refs):
            _needs('complete_disclosed_credit_debts', portfolio.debt_refs)
        accounts, opening = {}, []
        for ref in portfolio.account_refs:
            account = read(ref, CreditAccountView)
            if account.borrower_id != portfolio.borrower_id:
                raise ValueError('Account belongs to another original borrower')
            available(account.as_of, 'current_credit_account', exact=True)
            if account.currency != application.requested.currency:
                _unsupported('bank-credit-currency-conversion')
            free = amount(_known(account.actual_cash, 'actual_credit_account_cash'))
            free -= amount(_known(account.restricted_cash, 'restricted_credit_account_cash'))
            if free < 0:
                raise ValueError('Restricted credit cash exceeds the actual balance')
            accounts[ref.key()] = account
            opening.append(CreditOpeningCash(account_ref=ref, unrestricted=money(free, account.evidence_refs[0])))
        if first.loan_account_ref.key() not in accounts:
            raise ValueError('Hypothetical financing names an account outside the original portfolio')
        project_region = _known(purpose.project_region_id, 'credit_project_region')

        def path(ref):
            account = accounts.get(ref.key())
            if account is None:
                raise ValueError('Application forecast names an account outside the original portfolio')
            if project_region not in _known(account.permitted_project_region_ids, 'credit_account_region_paths'):
                _unsupported('bank-credit-inter-region-account-path')

        path(first.loan_account_ref)
        movements, components = [], {}

        def remaining(row):
            if row.borrower_id != portfolio.borrower_id or row.account_ref.key() not in accounts:
                raise ValueError('Original obligation changes borrower or account')
            available(row.as_of, 'current_credit_obligation', exact=True)
            clock(row.due_at)
            due = amount(_known(row.actual_due, 'actual_credit_obligation_due'))
            paid = amount(_known(row.actual_paid, 'actual_credit_obligation_paid'))
            if paid > due:
                raise ValueError('Actual paid obligation exceeds the original due amount')
            return due - paid

        def add_obligation(row):
            unpaid = remaining(row)
            if unpaid > 0 and row.due_at.offset > first.horizon.end.offset:
                _needs('credit_horizon_covering_disclosed_obligations', [row.ref])
            if unpaid:
                value = money(unpaid, row.actual_due.value.basis_ref)
                movements.append(CreditCashMovement(local_key=f'{row.ref.kind}:{row.ref.id}',
                    account_ref=row.account_ref, time=now if row.due_at.offset < now.offset else row.due_at,
                    direction='outflow', amount={'lower': value, 'upper': value}))

        for ref in portfolio.debt_refs:
            debt = read(ref, CreditDebtView)
            if debt.borrower_id != portfolio.borrower_id:
                raise ValueError('Debt belongs to another original borrower')
            available(debt.as_of, 'current_credit_debt', exact=True)
            if debt.coverage != 'complete':
                _needs('complete_disclosed_debt_components')
            for component_ref in debt.component_refs:
                component = read(component_ref, CreditDebtComponentView)
                if (component.debt_ref != debt.ref or component.borrower_id != debt.borrower_id
                        or component.origin_scope != debt.origin_scope or component.payee_id != debt.lender_id):
                    raise ValueError('Debt component changes original debt, borrower, payee or project')
                if component.ref.key() in components:
                    raise ValueError('Debt component is claimed by multiple original debts')
                components[component.ref.key()] = component
                add_obligation(component)
        unique_identities([row.ref for row in components.values()])
        for ref in portfolio.obligation_refs:
            obligation = read(ref, CreditObligationView)
            if obligation.debt_component_ref is None:
                add_obligation(obligation)
            else:
                original = components.get(obligation.debt_component_ref.key())
                if original is None:
                    raise ValueError('Debt-linked obligation omits its original component')
                for field in ('borrower_id', 'payee_id', 'origin_scope', 'account_ref', 'actual_due',
                              'actual_paid', 'due_at', 'as_of'):
                    if getattr(original, field) != getattr(obligation, field):
                        raise ValueError('Debt obligation mirror changes its original identity or actual amount')
                remaining(obligation)
        flow_keys = set()
        for forecast in forecasts:
            for flow in forecast.flows:
                if flow.local_key in flow_keys:
                    raise ValueError('Multiple forecasts duplicate an original cash-flow identity')
                flow_keys.add(flow.local_key)
                path(flow.account_ref)
                interval = _known(flow.amount, 'credit_forecast_flow')
                amount(interval.lower)
                amount(interval.upper)
                # Keep forecast assumptions separate from actual opening balances.
                movements.append(CreditCashMovement(local_key=f'forecast:{flow.local_key}', account_ref=flow.account_ref,
                    time=flow.time, direction=flow.direction, amount=interval))
        minimum = _known(product.minimum_request, 'credit_product_minimum')
        maximum = _known(product.maximum_request, 'credit_product_maximum')
        lower, upper = amount(minimum), amount(maximum)
        capacity = read(capacity_ref or risk.capacity_ref, CreditLendingCapacityView)
        bank_portfolio = read(capacity.portfolio_ref, CreditBankPortfolioView)
        if capacity.lender_id != lender or bank_portfolio.lender_id != lender:
            raise ValueError('Credit review capacity belongs to another lender')
        available(capacity.as_of, 'current_credit_lending_capacity', exact=True)
        available(bank_portfolio.as_of, 'current_credit_bank_portfolio', exact=True)
        if bank_portfolio.coverage != 'complete':
            _needs('complete_visible_credit_bank_portfolio')
        if capacity.currency != application.requested.currency:
            _unsupported('bank-credit-capacity-currency')
        limit = amount(_known(capacity.commitment_limit, 'credit_bank_commitment_limit'))
        occupancy = 0
        for ref in bank_portfolio.commitment_refs:
            commitment = read(ref, CreditCommitmentView)
            if commitment.lender_id != lender:
                raise ValueError('Bank portfolio mixes another lender commitment')
            available(commitment.as_of, 'current_credit_bank_commitment', exact=True)
            if commitment.status == 'released':
                evidence([commitment.release_evidence_ref])
            else:
                occupancy += amount(_known(commitment.amount, 'actual_credit_bank_occupancy'))
        remaining_capacity = max(0, limit - occupancy)
        if remaining_capacity < lower or remaining_capacity <= 0:
            return decline('Current visible bank occupancy leaves no positive product-applicable capacity',
                           findings=findings, conditions=conditions)
        if remaining_capacity < upper:
            maximum = money(remaining_capacity, capacity.commitment_limit.value.basis_ref)
        cash_report = method(feasibility.host_method_ref, CreditCashInput(as_of=now, horizon=first.horizon,
            currency=feasibility.currency, minor_places=feasibility.minor_places, minimum=minimum,
            maximum=maximum, requested=application.requested, opening=opening, movements=movements,
            loan_account_ref=first.loan_account_ref, loan_schedule=feasibility.schedule,
            basis_refs=list(basis.values()), source_refs=list(sources.values())))
        if not cash_report.feasible:
            return decline('No positive indicative amount satisfies all disclosed cash constraints', findings=findings, conditions=conditions)
        assessed = {'state': 'known', 'value': {'lower': {'state': 'known', 'value': cash_report.rounded_lower},
            'upper': {'state': 'known', 'value': cash_report.rounded_upper}, 'method_ref': feasibility.ref,
            'assumptions': list(assumption_refs.values())}}
        choice = 'conditional' if (any(row['outcome'] != 'satisfied' for row in conditions)
                or any(row['conclusion'] != 'acceptable' for row in findings)) else 'recommend'
        return completed(choice, 'Sourced risk and indicative cash review only; dependencies remain in the authorized review evidence',
                         assessed, findings, conditions)
    except ObservationGap as gap:
        return gap.result
