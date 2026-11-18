"""Independent reconstruction of the explicitly synthetic BANK-A03 support domain.

No production processor, projection model or method executor is imported. This
checks raw frozen sources, complete graph/portfolio sets and exact mathematics;
it does not establish real credit calibration or any formal banking effect.
"""
from fractions import Fraction
import re


RISK_HOST = ('Method', 'micro.bank.declared_risk_intervals', '1')
CASH_HOST = ('Method', 'micro.bank.indicative_cash_bounds', '1')


def key(ref):
    return ref['kind'], ref['id'], ref['version']


def require(condition, message):
    if not condition:
        raise ValueError(message)


class SourceExit(Exception):
    def __init__(self, kind, reason):
        self.kind, self.reason = kind, reason


def source_oracle(data, result, audit, projections, *, method_catalog=None, method_failures=()):
    """Require the result and every method record to agree with original sources.

    ``method_catalog`` is supplied by the verified host assembly, not inferred
    from an audit's claim of unsupported. Explicit synthetic outage replays may
    name their failing host versions via ``method_failures``.
    """
    source = {key(row['ref']): row['value'] for row in projections}
    require(len(source) == len(projections), 'Oracle snapshot repeats an object version')
    for row in data['objects']:
        require(source.get(key(row['ref'])) == row['value'], 'Frozen projection differs from supplied source')
    registered = {RISK_HOST, CASH_HOST} if method_catalog is None else {RISK_HOST, CASH_HOST} & {
        key(row['definition']['method_ref']) for row in method_catalog
        if 'BANK-A03' in row['definition']['action_ids']}
    failure_keys = {key(ref) for ref in method_failures}
    output = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
    calls, used = audit['method_calls'], 0
    inp, now = data['input'], data['business_time']
    lender = data['organization_id']
    sources, evidence_seen = {}, {}
    expected_findings, expected_conditions, cash_summary = [], [], None

    def exit_source(kind, reason):
        raise SourceExit(kind, reason)

    def clock(point):
        if point['clock_ref'] != now['clock_ref']:
            exit_source('unsupported', 'clock_alignment')

    def active(window, point=None):
        point = point or now
        clock(window['start'])
        require(window['start']['clock_ref'] == window['end']['clock_ref'], 'Window mixes clock versions')
        return ((point['offset'] >= window['start']['offset'] if window['bounds'].startswith('closed')
                 else point['offset'] > window['start']['offset'])
                and (point['offset'] <= window['end']['offset'] if window['bounds'].endswith('closed')
                     else point['offset'] < window['end']['offset']))

    def current(window, reason, point=None):
        if not active(window, point):
            exit_source('needs_information', reason)

    def available(point, reason, exact=False):
        clock(point)
        if point['offset'] > now['offset'] or exact and point != now:
            exit_source('needs_information', reason)

    def evidence(refs, point=None):
        for ref in refs:
            row = source.get(key(ref))
            require(row is not None and row['ref'] == ref and ref['kind'] == 'Evidence', 'Missing source evidence')
            if row['effective_window'] is not None:
                current(row['effective_window'], 'current_evidence', point)
            evidence_seen[key(ref)] = ref

    def get(ref, point=None):
        require(key(ref) in source, 'Oracle cannot discover an undisclosed object')
        row = source[key(ref)]
        require(row.get('ref', row.get('function_ref')) == ref, 'Source identity differs from reference')
        evidence(row.get('evidence_refs', []), point)
        sources[key(ref)] = ref
        return row

    def known(state, reason):
        if state['state'] == 'not_supported':
            exit_source('unsupported', reason)
        if state['state'] == 'not_applicable':
            exit_source('unsupported', reason)
        if state['state'] != 'known':
            exit_source('needs_information', reason)
        return state['value']

    def identities(refs):
        require(len({(ref['kind'], ref['id']) for ref in refs}) == len(refs), 'Repeated physical source identity')

    def covers(granted, requested):
        return (granted['kind'] == requested['kind'] and granted['ref'] == requested['ref']
                and {key(ref) for ref in requested['coverage_refs']} <= {key(ref) for ref in granted['coverage_refs']})

    def authorized(ref, actor, organization, function, action, scope, point):
        grant, assignment = get(ref, point), get(function, point)
        evidence(grant['basis_refs'], point)
        evidence(assignment['basis_refs'], point)
        clock(grant['validity']['start'])
        prefixes = {'Owner': 'OWN', 'Bank': 'BANK', 'Government': 'GOV', 'Engineer': 'ENGINEER',
                    'QS': 'QS', 'Architect': 'ARCHITECT', 'Contractor': 'CONTRACTOR', 'Supplier': 'SUPPLIER'}
        return (grant['organization_id'] == organization and grant['actor_id'] == actor
            and grant['function_ref'] == function and action in grant['action_ids']
            and active(grant['validity'], point) and any(covers(scope_, scope) for scope_ in grant['scopes'])
            and action.split('-', 1)[0] == prefixes[assignment['role']])

    def number(money):
        evidence([money['basis_ref']])
        if money['currency'] != application['requested']['currency']:
            exit_source('unsupported', 'currency_conversion')
        return Fraction(money['value'])

    def rational(raw):
        require(raw['denominator'] > 0, 'Report rational denominator is invalid')
        return Fraction(raw['numerator'], raw['denominator'])

    def refs_in(value):
        if isinstance(value, dict):
            if set(value) == {'kind', 'id', 'version'}:
                yield value
            else:
                for item in value.values():
                    yield from refs_in(item)
        elif isinstance(value, list):
            for item in value:
                yield from refs_in(item)

    def invoke(ref, expected_input, report_checker):
        nonlocal used
        require(used < len(calls), 'Required credit method invocation omitted')
        call = calls[used]
        used += 1
        require(call['method_ref'] == ref, 'Credit method uses another host version')
        actual = call['input']
        require(set(actual) == set(expected_input), 'Credit method input schema changed')
        for field, expected in expected_input.items():
            if field in {'source_refs', 'basis_refs'}:
                identities(actual[field])
                require({key(r) for r in actual[field]} == {key(r) for r in expected}, f'Method omits source set: {field}')
            else:
                require(actual[field] == expected, f'Method changes original source input: {field}')
        raw = call['result']
        if key(ref) not in registered:
            require(raw['kind'] == 'unsupported', 'Unregistered credit method fabricated execution')
            exit_source('unsupported', 'unregistered_host_method')
        if key(ref) in failure_keys:
            require(raw['kind'] == 'technical_error', 'Method outage disguised as business opinion')
            exit_source('technical_error', 'method_execution_failed')
        require(raw['kind'] == 'ok' and raw['method_ref'] == ref, 'Supported credit method did not return its real report')
        require(re.fullmatch('[0-9a-f]{64}', raw['input_digest']) is not None, 'Method input provenance digest missing')
        require(len(raw['input_refs']) == len(expected_input['source_refs'])
                and {key(row['ref']) for row in raw['input_refs']} == {key(r) for r in expected_input['source_refs']},
                'Method result drops its complete input source set')
        require(all(row['data_space'] == {'kind': 'run', 'id': audit['run_id']} for row in raw['input_refs']),
                'Method report belongs to another run')
        expected_basis = {key(r) for r in refs_in(actual) if r['kind'] == 'Evidence'}
        require(len(raw['basis_refs']) == len(expected_basis) and {key(r) for r in raw['basis_refs']} == expected_basis,
                'Method result changes its evidence basis set')
        report_checker(raw['value'])

    def decline(rule_ref):
        rule = get(rule_ref)
        require(rule['lender_id'] == lender and rule['product_ref'] == product['ref'], 'Decline rule changes lender/product')
        current(rule['effective_window'], 'current_decline_rule')
        return {'choice': 'decline', 'findings': expected_findings, 'conditions': expected_conditions,
                'assessed_amount': {'state': 'not_applicable', 'rule_ref': rule_ref}}

    def conditions(roots):
        rows, stack = {}, list(roots)
        while stack:
            ref = stack.pop()
            if key(ref) in rows:
                continue
            identities([row['ref'] for row in rows.values()] + [ref])
            row = get(ref)
            require(row['application_ref'] == application['ref'] and row['product_ref'] == product['ref']
                    and covers(row['scope_ref'], application['scope_ref']), 'Condition changes original scope or version')
            current(row['effective_window'], 'current_condition')
            rows[key(ref)] = row
            stack.extend(row['dependency_refs'])
        raw_states = {}
        for identity, row in rows.items():
            state = row['outcome']['value'] if row['outcome']['state'] == 'known' else 'unknown'
            verifier = row['verification']
            if verifier is not None:
                available(verifier['verified_at'], 'available_condition_verification')
                if (verifier['organization_id'] not in known(row['authorized_verifier_organization_ids'], 'known_verifiers')
                        or verifier['action_id'] not in known(row['authorized_verifier_action_ids'], 'known_verifier_actions')
                        or not authorized(verifier['authority_ref'], verifier['actor_id'], verifier['organization_id'],
                            verifier['function_ref'], verifier['action_id'], row['scope_ref'], verifier['verified_at'])):
                    exit_source('needs_information', 'authorized_condition_verifier')
                grant = get(verifier['authority_ref'], verifier['verified_at'])
                if not {key(ref) for ref in row['evidence_refs']} <= {key(ref) for ref in grant['readable_refs']}:
                    exit_source('needs_information', 'authorized_condition_evidence')
                evidence(row['evidence_refs'], verifier['verified_at'])
            elif state == 'satisfied':
                require(False, 'Satisfied source condition has no verifier')
            elif state == 'unsatisfied':
                state = 'unknown'
            raw_states[identity] = state
        # Independent graph closure: a satisfied node needs an acyclic path
        # whose full transitive prerequisites are themselves verified satisfied.
        cyclic = set()
        for start in rows:
            reachable = {key(ref) for ref in rows[start]['dependency_refs']}
            frontier = set(reachable)
            while frontier:
                following = {key(ref) for identity in frontier for ref in rows[identity]['dependency_refs']} - reachable
                reachable.update(following)
                frontier = following
            if start in reachable:
                cyclic.add(start)

        def transitive(start):
            pending, visited = [start], set()
            failed, uncertain = False, False
            while pending:
                identity = pending.pop()
                if identity in visited:
                    continue
                visited.add(identity)
                state = raw_states[identity]
                if state == 'unsatisfied':
                    failed = True
                    continue
                if state == 'unknown':
                    uncertain = True
                    continue
                if identity in cyclic:
                    uncertain = True
                for ref in rows[identity]['dependency_refs']:
                    pending.append(key(ref))
            return 'unknown' if uncertain else 'unsatisfied' if failed else 'satisfied'
        result_conditions = []
        for identity, row in sorted(rows.items(), key=lambda item: repr(item[0])):
            state = raw_states[identity]
            if state == 'satisfied':
                state = transitive(identity)
            result_conditions.append({'requirement_ref': row['ref'], 'scope_ref': row['scope_ref'],
                'responsible_id': row['responsible_id'], 'evidence_refs': row['evidence_refs'], 'outcome': state})
        return result_conditions

    def reconstruct():
        nonlocal application, product, risk, expected_findings, expected_conditions, cash_summary
        application, product, risk = get(inp['application_ref']), get(inp['product_ref']), get(inp['risk_method_ref'])
        require(application['lender_id'] == product['lender_id'] == risk['lender_id'] == lender
                and risk['product_ref'] == product['ref'] and product['ref'] in application['product_candidates'],
                'Review changes exact lender, application or product')
        for field in ('disclosures', 'forecast_refs', 'debt_refs', 'permit_risk_refs'):
            identities(inp[field])
        if not {key(ref) for ref in application['disclosure_refs']} <= {key(ref) for ref in inp['disclosures']}:
            exit_source('needs_information', 'complete_disclosures')
        evidence(inp['disclosures'])
        current(risk['effective_window'], 'current_risk_method')
        current(product['effective_window'], 'current_product')
        available(application['submitted_at'], 'submitted_application')
        if application['status'] == 'draft': exit_source('needs_information', 'submitted_application')
        if application['status'] == 'withdrawn': return decline(risk['decline_rule_ref'])
        if not authorized(application['applicant_authority_ref'], application['applicant_actor_id'],
            application['borrower_id'], application['applicant_function_ref'], application['originating_action_id'],
            application['scope_ref'], application['submitted_at']):
            return decline(risk['decline_rule_ref'])
        borrower, purpose = get(application['borrower_ref']), get(application['purpose_ref'])
        require(purpose['borrower_ref'] == borrower['ref'] and purpose['scope_ref'] == application['scope_ref'],
                'Purpose changes original borrower/scope')
        scope = application['scope_ref']
        if scope['kind'] != 'organization':
            scope_object = get(scope['ref'])
            require(scope_object['borrower_id'] == application['borrower_id'], 'Scope belongs to another borrower')
            if scope['kind'] == 'project':
                require(scope_object['region_id'] == known(purpose['project_region_id'], 'project_region'),
                        'Funding purpose changes original formal project region')
            available(scope_object['available_at'], 'available_scope')
            if scope_object['status'] != 'active': exit_source('needs_information', 'active_scope')
        else:
            require(scope['ref'] == borrower['ref'], 'Organizational scope changes borrower')
        for ref in scope['coverage_refs']:
            work = get(ref)
            require(work['borrower_id'] == application['borrower_id'] and covers(work['scope_ref'], scope), 'Work changes borrower/scope')
            current(work['effective_window'], 'current_work_scope')
        current(borrower['effective_window'], 'current_borrower')
        current(purpose['effective_window'], 'current_purpose')
        if not known(borrower['legal_standing'], 'legal_standing'): return decline(risk['decline_rule_ref'])
        for fact, allowed in ((borrower['registration_region_id'], product['allowed_registration_region_ids']),
            (purpose['project_region_id'], product['allowed_project_region_ids']),
            (purpose['purpose_code'], product['allowed_purpose_codes']), (purpose['stage'], product['allowed_stages'])):
            if known(fact, 'applicability') not in known(allowed, 'product_applicability'):
                return decline(risk['decline_rule_ref'])
        operating = known(borrower['operating_region_ids'], 'operating_regions')
        if not operating: exit_source('needs_information', 'operating_regions')
        if not set(operating) <= set(known(product['allowed_operating_region_ids'], 'product_operating_regions')):
            return decline(risk['decline_rule_ref'])
        if application['requested']['currency'] not in known(product['allowed_currencies'], 'product_currencies'):
            return decline(risk['decline_rule_ref'])
        if number(application['requested']) <= 0: return decline(risk['decline_rule_ref'])
        disclosed = {row['disclosure_code']: row['evidence_ref'] for row in application['disclosures']}
        for code in known(product['required_disclosure_codes'], 'required_disclosures'):
            if code not in disclosed: exit_source('needs_information', 'required_disclosure')
            evidence([disclosed[code]])
        feasibility = get(risk['feasibility_method_ref'])
        require(feasibility['lender_id'] == lender and feasibility['product_ref'] == product['ref'], 'Feasibility method changes lender/product')
        current(feasibility['effective_window'], 'current_feasibility_method')
        if feasibility['currency'] != application['requested']['currency']: exit_source('unsupported', 'currency_conversion')
        if not inp['forecast_refs']: exit_source('needs_information', 'complete_forecast')
        forecasts = [get(ref) for ref in inp['forecast_refs']]
        first = forecasts[0]
        assumptions = {key(ref): ref for ref in feasibility['assumption_refs']}
        for row in forecasts:
            require(row['application_ref'] == application['ref'] and row['borrower_id'] == application['borrower_id']
                    and row['scope_ref'] == scope and row['portfolio_ref'] == first['portfolio_ref']
                    and row['loan_account_ref'] == first['loan_account_ref'] and row['horizon'] == first['horizon'],
                    'Forecast mixes original borrower, application, portfolio or horizon')
            if {key(ref) for ref in row['review_forecast_refs']} != {key(ref) for ref in inp['forecast_refs']}:
                exit_source('needs_information', 'complete_forecast_set')
            available(row['as_of'], 'current_forecast', exact=True)
            if row['coverage'] != 'complete': exit_source('needs_information', 'complete_forecast')
            require(row['ordinary_flows_exclude_debt_and_new_financing'], 'Forecast includes duplicated financing/debt effects')
            for flow in row['flows']: assumptions[key(flow['assumption_ref'])] = flow['assumption_ref']
        for ref in assumptions.values():
            row = get(ref)
            require(row['method_ref'] == feasibility['ref'], 'Assumption changes public feasibility method')
            current(row['effective_window'], 'current_assumption')
        observations = {key(ref): get(ref) for ref in
            [ref for row in forecasts for ref in row['risk_observation_refs']] + inp['permit_risk_refs']}
        if {identity for identity, row in observations.items() if row['category'] == 'permit'} != {key(ref) for ref in inp['permit_risk_refs']}:
            exit_source('needs_information', 'complete_permit_observations')
        by_dimension = {}
        for row in observations.values():
            require(row['application_ref'] == application['ref'] and row['borrower_id'] == application['borrower_id']
                    and covers(row['scope_ref'], scope), 'Observation changes borrower, scope or application')
            available(row['observed_at'], 'available_observation')
            current(row['effective_window'], 'current_observation')
            require(key(row['dimension_ref']) not in by_dimension, 'Risk dimension has duplicate observations')
            by_dimension[key(row['dimension_ref'])] = row
        if set(by_dimension) != {key(ref) for ref in risk['dimension_refs']}:
            exit_source('needs_information', 'complete_dimensions')
        dimensions, risk_input, conclusions = [], [], {}
        for ref in risk['dimension_refs']:
            dimension, observation = get(ref), by_dimension[key(ref)]
            require(dimension['risk_method_ref'] == risk['ref'], 'Dimension changes public risk method')
            current(dimension['effective_window'], 'current_dimension')
            evidence([dimension['threshold']['basis_ref']])
            interval = observation['interval']
            if interval['state'] in {'not_supported', 'not_applicable'}: exit_source('unsupported', 'risk_observation_domain')
            conclusion = 'unknown'
            if interval['state'] == 'known':
                endpoints = interval['value']
                for value in endpoints.values():
                    evidence([value['basis_ref']])
                    if value['unit'] != dimension['threshold']['unit']: exit_source('unsupported', 'risk_unit_conversion')
                lo, hi, threshold = Fraction(endpoints['lower']['value']), Fraction(endpoints['upper']['value']), Fraction(dimension['threshold']['value'])
                if dimension['predicate'] == 'at_most':
                    conclusion = 'acceptable' if hi <= threshold else 'unacceptable' if lo > threshold else 'unknown'
                else:
                    conclusion = 'acceptable' if lo >= threshold else 'unacceptable' if hi < threshold else 'unknown'
            conclusions[key(ref)] = conclusion
            dimensions.append(dimension)
            risk_input.append({'dimension_ref': ref, 'predicate': dimension['predicate'],
                               'threshold': dimension['threshold'], 'interval': interval})
        def check_risk(report):
            require(report == {'findings': [{'dimension_ref': row['ref'], 'conclusion': conclusions[key(row['ref'])]}
                                           for row in dimensions]}, 'Risk report changes or omits a dimension/outcome')
        invoke(risk['host_method_ref'], {'dimensions': risk_input, 'source_refs': list(sources.values())}, check_risk)
        for dimension in dimensions:
            obs = by_dimension[key(dimension['ref'])]
            refs = dimension['evidence_refs'] + obs['evidence_refs'] + [dimension['threshold']['basis_ref']]
            if obs['interval']['state'] == 'known':
                refs += [obs['interval']['value'][end]['basis_ref'] for end in ('lower', 'upper')]
            expected_findings.append({'dimension_ref': dimension['ref'], 'conclusion': conclusions[key(dimension['ref'])],
                'evidence_refs': list({key(ref): ref for ref in refs}.values()), 'method_ref': risk['ref']})
        expected_conditions = conditions(product['required_condition_refs'] +
            [row['remedial_condition_ref'] for row in dimensions if row['remedial_condition_ref'] is not None])
        for row in dimensions:
            if row['hard'] and conclusions[key(row['ref'])] == 'unacceptable': return decline(row['failure_rule_ref'])
        if any(row['hard'] and conclusions[key(row['ref'])] == 'unknown' for row in dimensions):
            exit_source('needs_information', 'determinate_hard_risk')
        portfolio = get(first['portfolio_ref'])
        require(portfolio['borrower_id'] == application['borrower_id'], 'Portfolio changes legal borrower')
        available(portfolio['as_of'], 'current_portfolio', exact=True)
        if portfolio['coverage'] != 'complete': exit_source('needs_information', 'complete_portfolio')
        if {key(ref) for ref in portfolio['debt_refs']} != {key(ref) for ref in inp['debt_refs']}:
            exit_source('needs_information', 'complete_debt_set')
        opening, accounts = [], {}
        for ref in portfolio['account_refs']:
            row = get(ref)
            require(row['borrower_id'] == portfolio['borrower_id'], 'Actual account changes original borrower')
            available(row['as_of'], 'current_account', exact=True)
            if row['currency'] != feasibility['currency']: exit_source('unsupported', 'currency_conversion')
            free = number(known(row['actual_cash'], 'actual_cash')) - number(known(row['restricted_cash'], 'restricted_cash'))
            require(free >= 0, 'Restricted cash exceeds original cash')
            accounts[key(ref)] = row
            opening.append({'account_ref': ref, 'unrestricted': {
                'value': str(free.numerator) if free.denominator == 1 else finite_decimal(free),
                'currency': feasibility['currency'], 'basis_ref': row['evidence_refs'][0]}})
        identities([row['account_ref'] for row in opening])
        project_region = known(purpose['project_region_id'], 'project_region')
        def path(ref):
            require(key(ref) in accounts, 'Forecast uses undisclosed original account')
            if project_region not in known(accounts[key(ref)]['permitted_project_region_ids'], 'account_paths'):
                exit_source('unsupported', 'account_region_path')
        path(first['loan_account_ref'])
        movements, components = [], {}
        def remaining(row):
            require(row['borrower_id'] == portfolio['borrower_id'] and key(row['account_ref']) in accounts,
                    'Original obligation changes borrower/account')
            available(row['as_of'], 'current_obligation', exact=True)
            clock(row['due_at'])
            due, paid = known(row['actual_due'], 'actual_due'), known(row['actual_paid'], 'actual_paid')
            unpaid = number(due) - number(paid)
            require(unpaid >= 0, 'Obligation is overpaid')
            return unpaid, due
        def add_due(row):
            unpaid, due = remaining(row)
            if unpaid and row['due_at']['offset'] > first['horizon']['end']['offset']:
                exit_source('needs_information', 'horizon_covers_obligations')
            if unpaid:
                amount = {**due, 'value': finite_decimal(unpaid)}
                movements.append({'local_key': f"{row['ref']['kind']}:{row['ref']['id']}", 'account_ref': row['account_ref'],
                    'time': now if row['due_at']['offset'] < now['offset'] else row['due_at'],
                    'direction': 'outflow', 'amount': {'lower': amount, 'upper': amount}})
        for ref in portfolio['debt_refs']:
            row = get(ref)
            require(row['borrower_id'] == portfolio['borrower_id'], 'Debt changes original borrower')
            available(row['as_of'], 'current_debt', exact=True)
            if row['coverage'] != 'complete': exit_source('needs_information', 'complete_debt_components')
            for ref in row['component_refs']:
                component = get(ref)
                require(component['debt_ref'] == row['ref'] and component['borrower_id'] == row['borrower_id']
                        and component['payee_id'] == row['lender_id'] and component['origin_scope'] == row['origin_scope'],
                        'Original debt component changes debt, borrower, payee or project')
                require(key(ref) not in components, 'Original debt component appears twice')
                components[key(ref)] = component
                add_due(component)
        identities([row['ref'] for row in components.values()])
        for ref in portfolio['obligation_refs']:
            row = get(ref)
            if row['debt_component_ref'] is None:
                add_due(row)
            else:
                original = components.get(key(row['debt_component_ref']))
                require(original is not None, 'Mirror obligation omits original component')
                require(all(row[field] == original[field] for field in ('borrower_id', 'payee_id', 'origin_scope',
                    'account_ref', 'actual_due', 'actual_paid', 'due_at', 'as_of')), 'Mirror changes actual original debt facts')
                remaining(row)
        for row in forecasts:
            for flow in row['flows']:
                path(flow['account_ref'])
                interval = known(flow['amount'], 'forecast_flow')
                number(interval['lower']); number(interval['upper'])
                movements.append({'local_key': f"forecast:{flow['local_key']}", 'account_ref': flow['account_ref'],
                    'time': flow['time'], 'direction': flow['direction'], 'amount': interval})
        require(len({row['local_key'] for row in movements}) == len(movements), 'Cash event copied between forecasts')
        minimum, maximum = known(product['minimum_request'], 'product_minimum'), known(product['maximum_request'], 'product_maximum')
        low, high = number(minimum), number(maximum)
        capacity = get(risk['capacity_ref'])
        bank_portfolio = get(capacity['portfolio_ref'])
        require(capacity['lender_id'] == bank_portfolio['lender_id'] == lender, 'Bank capacity changes lender')
        available(capacity['as_of'], 'current_lending_capacity', exact=True)
        available(bank_portfolio['as_of'], 'current_bank_portfolio', exact=True)
        if bank_portfolio['coverage'] != 'complete': exit_source('needs_information', 'complete_bank_portfolio')
        if capacity['currency'] != feasibility['currency']: exit_source('unsupported', 'capacity_currency')
        limit_amount = known(capacity['commitment_limit'], 'bank_commitment_limit')
        remaining_capacity = number(limit_amount)
        identities(bank_portfolio['commitment_refs'])
        for ref in bank_portfolio['commitment_refs']:
            commitment = get(ref)
            require(commitment['lender_id'] == lender, 'Bank portfolio reads another lender commitment')
            available(commitment['as_of'], 'current_commitment', exact=True)
            if commitment['status'] == 'released':
                require(commitment['release_evidence_ref'] is not None, 'Bank occupancy released without evidence')
                evidence([commitment['release_evidence_ref']])
            else:
                remaining_capacity -= number(known(commitment['amount'], 'actual_bank_occupancy'))
        remaining_capacity = max(0, remaining_capacity)
        if remaining_capacity < low or remaining_capacity <= 0: return decline(risk['decline_rule_ref'])
        if remaining_capacity < high:
            maximum = {**limit_amount, 'value': finite_decimal(remaining_capacity)}
        cash_input = {'as_of': now, 'horizon': first['horizon'], 'currency': feasibility['currency'],
            'minor_places': feasibility['minor_places'], 'minimum': minimum, 'maximum': maximum,
            'requested': application['requested'], 'opening': opening, 'movements': movements,
            'loan_account_ref': first['loan_account_ref'], 'loan_schedule': feasibility['schedule'],
            'basis_refs': list(evidence_seen.values()), 'source_refs': list(sources.values())}
        cash_summary = cash_oracle(cash_input)
        def check_cash(report):
            expected = cash_summary
            require(report['feasible'] == expected['feasible'], 'Cash report changes interval feasibility')
            require(rational(report['exact_lower']) == expected['exact_lower']
                    and rational(report['exact_upper']) == expected['exact_upper'], 'Cash report invents exact principal bounds')
            require(len(report['constraints']) == len(expected['constraints']), 'Cash report omits or duplicates account checkpoints')
            for actual, expected_row in zip(report['constraints'], expected['constraints']):
                require(actual['account_ref'] == expected_row['account_ref'] and actual['time'] == expected_row['time']
                        and rational(actual['ordinary_free_cash']) == expected_row['free']
                        and rational(actual['loan_coefficient']) == expected_row['coefficient'], 'Cash report changes original balance or loan factor')
            for field in ('rounded_lower', 'rounded_upper'):
                require(report[field] == expected[field], 'Cash report changes inward-rounded indicative range or basis')
        invoke(feasibility['host_method_ref'], cash_input, check_cash)
        if not cash_summary['feasible']: return decline(risk['decline_rule_ref'])
        return {'choice': 'conditional' if (any(row['conclusion'] != 'acceptable' for row in expected_findings)
                or any(row['outcome'] != 'satisfied' for row in expected_conditions)) else 'recommend',
            'findings': expected_findings, 'conditions': expected_conditions,
            'assessed_amount': {'state': 'known', 'value': {
                'lower': {'state': 'known', 'value': cash_summary['rounded_lower']},
                'upper': {'state': 'known', 'value': cash_summary['rounded_upper']},
                'method_ref': feasibility['ref'], 'assumptions': list(assumptions.values())}}}

    application = product = risk = None
    try:
        expected = reconstruct()
        expected_kind = 'completed'
        require(output['kind'] == expected_kind, 'Valid source review disguised as missing data or failure')
        payload = output['payload']
        require(set(payload) == {'choice', 'findings', 'conditions', 'assessed_amount', 'note'}, 'Review payload carries invented effects')
        for field, value in expected.items():
            require(payload[field] == value, f'Credit result differs from complete source reconstruction: {field}')
        reason = expected['choice']
    except SourceExit as exc:
        expected_kind, reason = exc.kind, exc.reason
        require(output['kind'] == expected_kind, f'Source requires {expected_kind}; result fabricates a business opinion')
        require('payload' not in output, 'Incomplete credit review carries a hidden business decision')
    require(used == len(calls), 'Extra or repeated method records do not belong to source review')
    return {'status': 'passed', 'source_based': True, 'expected_kind': expected_kind, 'reason': reason,
        'dimensions': len(expected_findings), 'conditions': len(expected_conditions), 'method_calls': used,
        'cash_feasible': cash_summary['feasible'] if cash_summary is not None else None,
        'formal_effects': 0, 'calibration': 'synthetic_mathematical_only'}


def finite_decimal(number):
    """Independent exact transport rendering without Decimal or method helpers."""
    n, d = number.numerator, number.denominator
    digits, scale = [], 1
    while d > 1:
        divisor = 2 if d % 2 == 0 else 5 if d % 5 == 0 else None
        require(divisor is not None, 'Oracle needs explicit monetary rounding for nonterminating decimals')
        d //= divisor
        digits.append(divisor)
    places = max(digits.count(2), digits.count(5))
    scale = 10 ** places
    integer = n * scale // number.denominator
    raw = str(abs(integer)).rjust(places + 1, '0')
    return ('-' if integer < 0 else '') + (raw[:-places] + '.' + raw[-places:] if places else raw)


def cash_oracle(data):
    """Build source constraints and intersect lower/upper half-lines independently."""
    now, end = data['as_of'], data['horizon']['end']
    require(end['clock_ref'] == now['clock_ref'] and end['offset'] > now['offset'], 'Unsupported oracle horizon')
    events = data['movements'] + data['loan_schedule']
    require(all(row['time']['clock_ref'] == now['clock_ref'] and now['offset'] <= row['time']['offset'] <= end['offset']
                for row in events), 'Oracle events lie outside the current clock/horizon')
    require(sum(Fraction(row['factor']) for row in data['loan_schedule'] if row['kind'] == 'draw') == 1
            and sum(Fraction(row['factor']) for row in data['loan_schedule'] if row['kind'] == 'principal') == 1,
            'Oracle loan does not conserve full principal')
    times = sorted({now['offset'], end['offset'], *(row['time']['offset'] for row in events)})
    lower_candidates = [Fraction(data['minimum']['value'])]
    upper_candidates = [Fraction(data['maximum']['value']), Fraction(data['requested']['value'])]
    constraints, impossible = [], False
    for account in sorted(data['opening'], key=lambda row: repr(key(row['account_ref']))):
        for time in times:
            incoming = sum((Fraction(row['amount']['lower']['value']) for row in data['movements']
                if row['account_ref'] == account['account_ref'] and row['time']['offset'] <= time and row['direction'] == 'inflow'), Fraction())
            outgoing = sum((Fraction(row['amount']['upper']['value']) for row in data['movements']
                if row['account_ref'] == account['account_ref'] and row['time']['offset'] <= time and row['direction'] == 'outflow'), Fraction())
            free = Fraction(account['unrestricted']['value']) + incoming - outgoing
            coefficient = Fraction()
            if account['account_ref'] == data['loan_account_ref']:
                draw = sum((Fraction(row['factor']) for row in data['loan_schedule'] if row['time']['offset'] <= time and row['kind'] == 'draw'), Fraction())
                repay = sum((Fraction(row['factor']) for row in data['loan_schedule'] if row['time']['offset'] <= time and row['kind'] == 'principal'), Fraction())
                require(draw >= repay, 'Oracle loan repays principal before cumulative draw')
                costs = sum((Fraction(row['factor']) for row in data['loan_schedule'] if row['time']['offset'] <= time and row['kind'] == 'cost'), Fraction())
                coefficient = draw - repay - costs
            constraints.append({'account_ref': account['account_ref'], 'time': {**now, 'offset': time},
                                'free': free, 'coefficient': coefficient})
            if coefficient == 0:
                impossible |= free < 0
            elif coefficient > 0:
                lower_candidates.append(-free / coefficient)
            else:
                upper_candidates.append(-free / coefficient)
    lower, upper = max(lower_candidates), min(upper_candidates)
    unit = Fraction(1, 10 ** data['minor_places'])
    low_units, high_units = lower / unit, upper / unit
    lower_ticks = max(1, low_units.numerator // low_units.denominator + (low_units.denominator != 1))
    upper_ticks = high_units.numerator // high_units.denominator
    feasible = not impossible and lower_ticks <= upper_ticks
    make_money = lambda ticks: {'value': finite_decimal(ticks * unit), 'currency': data['currency'],
                                'basis_ref': data['basis_refs'][0]}
    return {'feasible': feasible, 'exact_lower': lower, 'exact_upper': upper,
        'rounded_lower': make_money(lower_ticks) if feasible else None,
        'rounded_upper': make_money(upper_ticks) if feasible else None, 'constraints': constraints}
