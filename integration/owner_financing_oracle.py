"""Reconstruct synthetic financing evidence without production executors."""
from fractions import Fraction


def source_oracle(data, result, audit, projections):
    def key(ref):
        return ref['kind'], ref['id'], ref['version']

    source = {key(row['ref']): row['value'] for row in projections}

    def get(ref):
        return source[key(ref)]

    def require(value, message):
        if not value:
            raise ValueError(message)

    def known(state):
        require(state['state'] == 'known', 'Oracle requires an explicit known source fact')
        return state['value']

    def number(amount):
        return Fraction(amount['value'])

    now = data['business_time']
    profile = get(data['input']['funding_profile_ref'])
    for row in data['objects']:
        require(get(row['ref']) == row['value'], 'Frozen projection differs from supplied source')

    def active(window, point=now):
        require(window['start']['clock_ref'] == point['clock_ref'] == window['end']['clock_ref'], 'Source clock mismatch')
        left = point['offset'] >= window['start']['offset'] if window['bounds'].startswith('closed') else point['offset'] > window['start']['offset']
        right = point['offset'] <= window['end']['offset'] if window['bounds'].endswith('closed') else point['offset'] < window['end']['offset']
        return left and right

    def authorized(ref, organization, actor, function, action, scope, point=now):
        grant = get(ref)
        require(grant['organization_id'] == organization and grant['actor_id'] == actor and grant['function_ref'] == function,
                'Authority changes the original legal party or function')
        require(action in grant['action_ids'] and active(grant['validity'], point), 'Required action authority is absent')
        require(any(row['kind'] == scope['kind'] and row['ref'] == scope['ref']
                    and {key(r) for r in scope['coverage_refs']} <= {key(r) for r in row['coverage_refs']}
                    for row in grant['scopes']), 'Authority does not cover the original scope')

    def compare_flow(actual, expected):
        require(len(actual) == len(expected), 'Calendar drops or duplicates a source flow')
        for a, e in zip(actual, expected):
            require(all(a[field] == e[field] for field in ('local_key', 'source_ref', 'time')), 'Calendar changes source flow identity/time')
            require(a['amount']['currency'] == e['amount']['currency'] and a['amount']['basis_ref'] == e['amount']['basis_ref']
                    and number(a['amount']) == number(e['amount']), 'Calendar changes sourced amount or monetary basis')

    def loan(ref):
        offer = get(ref)
        terms = offer['terms']
        require(offer['status'] == 'offered' and active(offer['effective_window']) and active(get(terms['validity_ref'])), 'Accepted loan is not current')
        require(terms['borrower_id'] == profile['borrower_id'] and offer['scope_ref'] == profile['scope_ref']
                and terms['purpose_ref'] == profile['purpose_ref'], 'Loan changes borrower, scope or purpose')
        authorized(offer['authority_ref'], offer['lender_id'], offer['author_actor_id'], offer['author_function_ref'],
                   'BANK-A04', offer['scope_ref'], offer['issued_at'])
        product, application = get(terms['product_ref']), get(offer['application_ref'])
        require(product['lender_id'] == application['lender_id'] == offer['lender_id']
                and application['borrower_id'] == profile['borrower_id'] and application['scope_ref'] == offer['scope_ref']
                and application['purpose_ref'] == terms['purpose_ref'] and terms['product_ref'] in application['product_candidates'],
                'Loan mixes product, application, party, purpose or version')
        principal, costs = [], []
        refs = [terms['pricing_ref'], *terms['fee_rule_refs'], terms['repayment_rule_ref']]
        for rule_ref in refs:
            rule = get(rule_ref)
            require(rule['offer_ref'] == offer['ref'] and rule['borrower_id'] == profile['borrower_id']
                    and rule['lender_id'] == offer['lender_id'] and rule['scope_ref'] == offer['scope_ref'], 'Rule mixes exact offer or party')
            require(rule['coverage'] == 'complete', 'Incomplete rule schedule')
            (principal if rule_ref['kind'] == 'RepaymentRule' else costs).extend(known(rule['schedule']))
        require(sum(number(row['amount']) for row in offer['proposed_releases']) == number(terms['principal_limit'])
                == sum(number(row['amount']) for row in principal), 'Loan changes or creates principal')
        return offer, principal, costs

    cash_calls = [call for call in audit['method_calls'] if call['method_ref']['id'] == 'micro.owner.financing_cash_calendar']
    calendars = []
    for index, call in enumerate(cash_calls):
        actual = call['input']
        choice = result.payload.choice if result.kind == 'completed' else None
        revision = known(profile['policy']) == 'resize' or choice == 'resize' and index > 0
        lines = get(profile['revision_ref'])['revised_lines'] if revision else data['input']['funding_lines']
        opening, inflows, outflows, planned = [], [], [], []
        required_refs = {key(profile['ref']), *[key(ref) for ref in profile['arrangement_refs']]}
        for ref in profile['source_refs']:
            row = get(ref)
            account = get(row['account_ref'])
            require(row['organization_id'] == account['organization_id'] == profile['borrower_id'] and account['source_ref'] == ref,
                    'Source copies another borrower account')
            require(row['as_of'] == account['as_of'] == now and row['coverage'] == account['coverage'] == 'complete', 'Cash is stale/incomplete')
            cash, restricted = known(account['actual_cash']), known(account['restricted_cash'])
            require(row['actual_cash'] == account['actual_cash'] and row['restricted_cash'] == account['restricted_cash'], 'Source changes actual balance')
            opening.append((ref, number(cash) - number(restricted), cash['basis_ref']))
            required_refs.update((key(ref), key(account['ref'])))
            for release in row['releases']:
                if release['state'] != 'committed':
                    continue
                require(release['time']['offset'] > now['offset'], 'Calendar treats a due unreconciled release as cash')
                require(release['approval_ref']['kind'] == 'FundingApproval', 'This synthetic oracle supports explicit nonbank approvals')
                approval = get(release['approval_ref'])
                require(known(approval['approved']) and approval['source_ref'] == ref
                        and approval['organization_id'] == profile['borrower_id'] and approval['release_time'] == release['time']
                        and number(approval['amount']) == number(known(release['amount'])), 'Calendar inflow lacks same-version approval')
                inflows.append({'local_key': f"release:{release['ref']['id']}", 'source_ref': ref,
                                'time': release['time'], 'amount': known(release['amount'])})
                required_refs.add(key(approval['ref']))
        require(len({key(get(ref)['account_ref']) for ref in profile['source_refs']}) == len(profile['source_refs']), 'Account was copied into multiple sources')
        for ref in profile['debt_refs']:
            debt = get(ref)
            arrangement = get(debt['arrangement_ref'])
            require(debt['borrower_id'] == profile['borrower_id'] and debt['lender_id'] == arrangement['lender_id']
                    and debt['origin_scope'] == arrangement['scope_ref'], 'Debt changes original legal party or project')
            required_refs.add(key(ref))
        for ref in profile['obligation_refs']:
            row = get(ref)
            require(row['debtor_id'] == profile['borrower_id'], 'Obligation changes original debtor')
            due, paid = known(row['actual_due']), known(row['actual_paid'])
            value = {**due, 'value': str(number(due) - number(paid))}
            time = row['due_at'] if row['due_at']['offset'] >= now['offset'] else now
            outflows.append({'local_key': f"obligation:{ref['id']}", 'source_ref': row['source_ref'], 'time': time, 'amount': value})
            required_refs.add(key(ref))
        for position, row in enumerate(lines):
            desired = get(row['window_ref'])
            require(desired['start']['offset'] >= now['offset'], 'Calendar moves planned spending into the past')
            planned.append({'local_key': f'planned:{position}', 'source_ref': row['source_ref'],
                            'time': desired['start'], 'amount': known(row['planned_use'])})
            required_refs.add(key(row['window_ref']))
        offers = [ref for ref in actual['source_refs'] if ref['kind'] == 'FinanceOffer']
        require(len(offers) <= 1, 'One calendar combines mutually exclusive offers')
        if offers:
            offer, repayments, costs = loan(offers[0])
            require(offers[0] in data['input']['offers'], 'Calendar uses an unreceived loan offer')
            for payments, target in ((offer['proposed_releases'], inflows), (repayments + costs, outflows)):
                target.extend({**row, 'local_key': f"offer:{row['local_key']}"} for row in payments)
            required_refs.update(key(ref) for ref in (offer['ref'], offer['application_ref'], offer['terms']['product_ref'],
                offer['terms']['pricing_ref'], offer['terms']['repayment_rule_ref'], offer['terms']['tenor_ref'],
                offer['terms']['validity_ref'], *offer['terms']['fee_rule_refs']))
        require(actual['clock_ref'] == now['clock_ref'] and actual['as_of'] == now, 'Calendar uses another clock or read point')
        require(len(actual['accounts']) == len(opening), 'Calendar omits or duplicates source account')
        for a, (ref, free, basis) in zip(actual['accounts'], opening):
            require(a['source_ref'] == ref and number(a['opening_available']) == free
                    and a['opening_available']['basis_ref'] == basis, 'Calendar opening cash differs from actual less restricted cash')
        compare_flow(actual['inflows'], inflows)
        compare_flow(actual['existing_outflows'], outflows)
        compare_flow(actual['proposed_outflows'], planned)
        require({key(ref) for ref in actual['source_refs']} == required_refs, 'Calendar omits/changes its exact source references')
        balances, checkpoints = [], []
        for ref, free, _ in opening:
            events = {}
            for sign, rows in ((1, inflows), (-1, outflows + planned)):
                for row in rows:
                    if row['source_ref'] == ref:
                        t = row['time']['offset']
                        events[t] = events.get(t, Fraction()) + sign * number(row['amount'])
            running = free
            for time in sorted({now['offset'], *events}):
                running += events.get(time, 0)
                balances.append(running)
                checkpoints.append({'source_ref': ref, 'time': {**now, 'offset': time},
                                    'available': {'numerator': running.numerator, 'denominator': running.denominator}})
        require(call['result']['kind'] == 'ok', 'Oracle replay expects a successful registered cash method')
        report = call['result']['value']
        require(report['checkpoints'] == checkpoints and report['feasible'] == all(v >= 0 for v in balances), 'Cash report differs from independent source arithmetic')
        calendars.append({'offer_ref': offers[0] if offers else None, 'feasible': report['feasible'], 'checkpoints': checkpoints})
    selections = [row for row in audit['method_calls'] if row['method_ref']['id'] == 'micro.owner.declared_financing_selection']

    def expected_offers():
        """Rebuild the assessment universe from sources, never method candidates."""
        borrower = get(profile['borrower_ref'])
        purpose = get(profile['purpose_ref'])
        pinned = profile['selected_offer_ref']
        received = data['input']['offers']
        require(pinned is None or pinned in received, 'Pinned offer was not received')
        expected = []
        for ref in [pinned] if pinned is not None else received:
            offer = get(ref)
            terms = offer['terms']
            if offer['status'] != 'offered' or not active(offer['effective_window']) or not active(get(terms['validity_ref'])):
                continue
            grant = get(offer['authority_ref'])
            require(grant['organization_id'] == offer['lender_id'] and grant['actor_id'] == offer['author_actor_id']
                    and grant['function_ref'] == offer['author_function_ref']
                    and get(offer['author_function_ref'])['role'] == 'Bank', 'Quote changes its authorized author')
            if not active(grant['validity'], offer['issued_at']) or 'BANK-A04' not in grant['action_ids']:
                continue
            scope = offer['scope_ref']
            if not any(s['kind'] == scope['kind'] and s['ref'] == scope['ref']
                       and {key(r) for r in scope['coverage_refs']} <= {key(r) for r in s['coverage_refs']}
                       for s in grant['scopes']):
                continue
            product, application = get(terms['product_ref']), get(offer['application_ref'])
            if application['status'] != 'submitted' or not active(product['effective_window']):
                continue
            checks = ((borrower['registration_region_id'], product['allowed_registration_region_ids']),
                      (purpose['project_region_id'], product['allowed_project_region_ids']),
                      (purpose['purpose_code'], product['allowed_purpose_codes']),
                      (purpose['stage'], product['allowed_stages']))
            if any(known(value) not in known(allowed) for value, allowed in checks):
                continue
            regions = known(borrower['operating_region_ids'])
            require(regions, 'Borrower operating regions are unknown/empty')
            if not set(regions) <= set(known(product['allowed_operating_region_ids'])):
                continue
            if terms['principal_limit']['currency'] not in known(product['allowed_currencies']):
                continue
            if not number(known(product['minimum_request'])) <= number(terms['principal_limit']) <= number(known(product['maximum_request'])):
                continue
            authorized(application['applicant_authority_ref'], profile['borrower_id'], application['applicant_actor_id'],
                       application['applicant_function_ref'], application['originating_action_id'], application['scope_ref'], application['submitted_at'])
            refs = {key(r): r for r in [*profile['required_condition_refs'], *product['required_condition_refs'], *terms['condition_refs']]}
            permitted = True
            for requirement_ref in refs.values():
                condition = get(requirement_ref)
                require(condition['offer_ref'] == ref and condition['arrangement_ref'] is None
                        and condition['borrower_id'] == profile['borrower_id'] and condition['lender_id'] == offer['lender_id'],
                        'Condition changes its exact offer stage or parties')
                require(condition['scope_ref']['kind'] == scope['kind'] and condition['scope_ref']['ref'] == scope['ref']
                        and {key(r) for r in scope['coverage_refs']} <= {key(r) for r in condition['scope_ref']['coverage_refs']},
                        'Condition fails to cover the requested offer scope')
                require(active(condition['effective_window']) and condition['verified_at']['clock_ref'] == now['clock_ref']
                        and condition['verified_at']['offset'] <= now['offset'], 'Condition is stale or unavailable')
                role = get(condition['verifier_function_ref'])['role']
                require(condition['verifier_action_id'] in {'Owner': {'OWN-A05'}, 'Bank': {'BANK-A05', 'BANK-A06'}}.get(role, set()),
                        'Condition verifier action is outside its role')
                organization = profile['borrower_id'] if role == 'Owner' else offer['lender_id']
                authorized(condition['verifier_authority_ref'], organization, condition['verifier_actor_id'],
                           condition['verifier_function_ref'], condition['verifier_action_id'], condition['scope_ref'], condition['verified_at'])
                if not known(condition['permitted']):
                    permitted = False
                    break
            if permitted:
                loan(ref)
                expected.append(ref)
        return expected

    policy = known(profile['policy'])
    complete_assessment = (policy in {'accept_offer', 'evaluate'}
                           and (selections or result.kind == 'completed' and result.payload.choice != 'own_funds'))
    if complete_assessment:
        complete_assessment = known(get(profile['borrower_ref'])['legal_standing'])
        for line in data['input']['funding_lines']:
            window = get(line['window_ref'])
            for ref in line['restriction_refs']:
                restriction = get(ref)
                if (not active(restriction['effective_window'], window['start'])
                        or restriction['effective_window']['end']['offset'] < window['end']['offset']
                        or not known(restriction['permitted'])):
                    complete_assessment = False
    if complete_assessment:
        expected = expected_offers()
        assessed = [v['offer_ref'] for v in calendars if v['offer_ref'] is not None]
        require(len(assessed) == len(expected) and {key(r) for r in assessed} == {key(r) for r in expected},
                'Cash calendars omit or duplicate an eligible source offer')
        feasible = [v['offer_ref'] for v in calendars if v['offer_ref'] is not None and v['feasible']]
        require(len(selections) == (1 if feasible else 0), 'A feasible offer set lacks its complete selection method')
    for call in selections:
        actual = call['input']
        feasible = [v['offer_ref'] for v in calendars if v['offer_ref'] is not None and v['feasible']]
        selected_refs = [row['offer_ref'] for row in actual['candidates']]
        require(len(selected_refs) == len(feasible) and {key(r) for r in selected_refs} == {key(r) for r in feasible},
                'Selection omits or duplicates a feasible source offer')
        eligible = []
        expected_costs, excluded = [], []
        for row in actual['candidates']:
            offer, repayments, costs = loan(row['offer_ref'])
            require(row == {'offer_ref': offer['ref'], 'priority': known(offer['priority']), 'principal': offer['terms']['principal_limit'],
                'tenor': get(offer['terms']['tenor_ref']), 'disbursements': offer['proposed_releases'], 'repayments': repayments, 'costs': costs},
                'Selection method changes exact offer terms or schedules')
            require(any(v['offer_ref'] == row['offer_ref'] and v['feasible'] for v in calendars), 'Selection uses an infeasible/unassessed calendar')
            total = sum(number(item['amount']) for item in costs)
            principal = number(offer['terms']['principal_limit'])
            expected_costs.append({'offer_ref': offer['ref'], 'principal': {'numerator': principal.numerator, 'denominator': principal.denominator},
                'nominal_cost': {'numerator': total.numerator, 'denominator': total.denominator}})
            if total > number(known(profile['financing_cost_cap'])):
                excluded.append(row['offer_ref'])
            else:
                eligible.append(row)
        require(actual['cost_cap'] == known(profile['financing_cost_cap']), 'Selection changes sourced finance cost cap')
        best = min((v['priority'] for v in eligible), default=None)
        ties = sorted((v['offer_ref'] for v in eligible if v['priority'] == best), key=lambda r: repr(key(r)))
        expected = {'selected_ref': ties[0] if len(ties) == 1 else None, 'ambiguous_refs': ties if len(ties) > 1 else [],
                    'excluded_refs': excluded, 'costs': expected_costs}
        require(call['result']['kind'] == 'ok' and call['result']['value'] == expected, 'Selection differs from independent cost/cap/preference oracle')
    if result.kind == 'completed':
        payload = result.payload.model_dump(mode='json')
        choice = payload['choice']
        grant = get(profile['authority_ref'])
        authorized(profile['authority_ref'], data['organization_id'], data['actor_id'], grant['function_ref'], 'OWN-A05', profile['scope_ref'])
        if choice == 'own_funds':
            require(len(calendars) == 1 and calendars[0]['offer_ref'] is None and calendars[0]['feasible'], 'Own-funds success lacks a feasible actual cash calendar')
        if choice == 'accept_offer':
            require(len(selections) == 1 and selections[0]['result']['value']['selected_ref'] == payload['offer_ref'], 'Accepted offer bypasses source selection')
        if choice == 'resize':
            require(calendars and calendars[-1]['feasible'], 'Resize is not checked against all existing obligations')
        if choice == 'apply':
            require(payload['application'] == profile['application'], 'Application differs from the original declared borrower draft')
            grant = get(payload['application']['applicant_authority_ref'])
            authorized(grant['ref'], profile['borrower_id'], data['actor_id'], grant['function_ref'], 'OWN-A05', profile['scope_ref'])
        if choice == 'negotiate':
            require(payload['offer_ref'] == profile['selected_offer_ref'], 'Negotiation substitutes another lender offer')
            require([row['issue_ref'] for row in payload['questions']] == profile['question_refs'], 'Negotiation changes original issue set')
    return {'source_reconstructed': True, 'calendars': calendars, 'selections': len(selections), 'formal_effects': 0}
