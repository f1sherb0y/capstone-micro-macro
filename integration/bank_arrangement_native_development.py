"""Declare initial BANK-A05 mandates and exact authorized receipt projections."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from integration.contractor_tender_development import _write, known, ref
from src.coordination.tasks import task_digest


def initial_formation_limits(values):
    if values is None:
        return {}
    if not isinstance(values, dict) or set(values) - {'finance-bank-a', 'finance-bank-b'}:
        raise ValueError('Formation limits must identify explicitly configured Banks')
    result = {}
    for bank, value in values.items():
        try:
            amount = Decimal(value) if isinstance(value, str) else Decimal('NaN')
        except InvalidOperation:
            raise ValueError('Formation limits require finite nonnegative explicit decimal strings') from None
        if not amount.is_finite() or amount < 0:
            raise ValueError('Formation limits require finite nonnegative explicit decimal strings')
        result[bank] = format(amount, 'f')
    return result


def extend_sources(directory, *, run_id, bank_plans, owner_plans, snapshot, principal_limits=None, capacity_limits=None):
    from integration.bank_arrangement_native import BankArrangementPlan
    from integration.bank_arrangement_actions import BankArrangementActionAssembler
    from src.actions.contracts.common import Reference

    limits = initial_formation_limits(principal_limits)
    capacities = initial_formation_limits(capacity_limits)

    organizations = {o['organization_id']: o for o in snapshot['organizations']}
    grants = {task_digest(g['ref']): g for g in snapshot['authorizations']}
    plans = []
    allowed = {'Evidence', 'Authorization', 'FunctionAssignment', 'FinanceApplication', 'Project', 'OwnerCase',
        'LendingCapacity', 'FinancePortfolio', 'FinanceCommitment', 'ReservationPolicy', 'TimeWindow', 'Requirement', 'QuoteAuthorityPolicy'}
    for bank in bank_plans:
        organization_id, borrower = bank['organization_id'], bank['borrower_id']
        own, = [p for p in owner_plans if (p['organization_id'], p['project_id'], p['tick'])
            == (borrower, bank['project_id'], bank['tick'])]
        disclosure, = [d for d in own['disclosures'] if d['bank_id'] == organization_id]
        quote = bank['steps']['BANK-A04']
        context = deepcopy(quote['context'])
        tag = context['operation_id'] + '-arrangement'
        rr = lambda kind, name: ref(kind, tag + '-' + name)
        basis = bank['utility']['basis_ref']
        clock = context['business_time']['clock_ref']
        point = lambda t: {'clock_ref': clock, 'offset': t}
        window = {'start': point(0), 'end': point(99), 'bounds': 'closed_open'}
        function, authority = rr('FunctionAssignment', 'formation'), rr('Authorization', 'formation')
        native, quote_evidence, acceptance_evidence = [rr('Evidence', name) for name in ('received-native', 'original-quote', 'original-borrower-acceptance')]
        offer = disclosure['offer_ref']
        acceptance = rr('PartyAcceptance', 'received-acceptance')
        recorded = ref('RecordedDecision', acceptance['id'] + '-original-owner-decision')
        profile, time_rule, candidates = rr('FinanceFormationProfile', 'formation'), rr('FinanceTimeRule', 'expiry'), rr('CandidateSet', 'received-selection')
        objects = []

        def put(reference, **value):
            objects.append({'ref': reference, 'value': {'ref': reference, **value}})

        assignment = {'role': 'Bank', 'function_ref': function, 'configuration_version': '1', 'basis_refs': [basis]}
        organizations[organization_id]['assignments'].append(deepcopy(assignment))
        objects.append({'ref': function, 'value': assignment})
        for evidence in (native, quote_evidence, acceptance_evidence):
            put(evidence, source_kind='synthetic', basis_kind='observed', locator='actual-selected-financing-reception:' + tag,
                content_hash=None, effective_window=window)
        quote_refs = [deepcopy(r['ref']) for r in quote['objects'] if r['ref']['kind'] in allowed]
        borrower_grant = grants[task_digest(own['context']['authorization_refs'][0])]
        borrower_assignment, = [a for a in organizations[borrower]['assignments'] if a['function_ref'] == own['context']['function_ref']]
        borrower_refs = [deepcopy(borrower_grant['ref']), deepcopy(borrower_assignment['function_ref']),
            *deepcopy(borrower_grant['basis_refs']), *deepcopy(borrower_assignment['basis_refs'])]
        borrower_refs = list({task_digest(r): r for r in borrower_refs}.values())
        existing_origins = [{'ref': deepcopy(r['ref']), 'origin_offer_ref': None, 'origin_arrangement_ref': None}
            for r in quote['objects'] if r['ref']['kind'] == 'FinanceCommitment']
        requote = [r['ref'] for r in quote['objects'] if r['ref']['kind'] == 'Requirement']
        formation_basis = basis
        if organization_id in limits:
            formation_basis = rr('Evidence', 'independent-initial-formation-limit')
            put(formation_basis, source_kind='synthetic', basis_kind='assumed',
                locator='explicit-initial-A05-formation-principal-limit:' + organization_id,
                content_hash=task_digest({'lender_id': organization_id, 'borrower_id': borrower,
                    'scope': context['scope'], 'as_of': context['business_time'], 'currency': 'HKD',
                    'maximum_principal': limits[organization_id]}), effective_window=window)
        put(profile, evidence_refs=list({task_digest(r):r for r in [basis, formation_basis]}.values()), offer_ref=offer, borrower_id=borrower, lender_id=organization_id,
            scope_ref=context['scope'], authority_ref=authority,
            maximum_principal=known({'value': limits.get(organization_id, '100000000'), 'currency': 'HKD', 'basis_ref': formation_basis}),
            allowed_product_refs=[quote['action_input']['product_ref']],
            allowed_pricing_refs=quote['action_input']['pricing_candidates'], formation_condition_refs=[],
            requote_requirement_refs=requote, allow_signed_pending_conditions=False,
            time_rule_ref=time_rule, effective_window=window)
        put(time_rule, evidence_refs=[basis], lender_id=organization_id,
            product_ref=quote['action_input']['product_ref'], equality_rule='expiry_first', effective_window=window)
        objects.append({'ref': candidates, 'value': {'operation_id': tag, 'scope': context['scope'],
            'as_of': context['business_time'], 'candidates': [{'ref': offer, 'permitted_choices': ['confirm', 'requote', 'decline']}],
            'search_profile_ref': rr('Profile', 'actual-selected-financing-only')}})
        capacity_ref = quote['action_input']['capacity_snapshot_ref']
        if organization_id in capacities:
            # This is an independently supplied A05 view, not a rewrite of
            # the earlier A04 capacity, its portfolio or a native cash limit.
            original, = [r['value'] for r in quote['objects'] if r['ref'] == capacity_ref]
            capacity_ref = rr('LendingCapacity', 'independent-current-formation-capacity')
            capacity_basis = rr('Evidence', 'independent-initial-formation-capacity-limit')
            put(capacity_basis, source_kind='synthetic', basis_kind='assumed',
                locator='explicit-initial-A05-formation-capacity-limit:' + organization_id,
                content_hash=task_digest({'lender_id': organization_id, 'borrower_id': borrower,
                    'scope': context['scope'], 'as_of': context['business_time'], 'currency': 'HKD',
                    'commitment_limit': capacities[organization_id], 'portfolio_ref': original['portfolio_ref']}),
                effective_window=window)
            current = deepcopy(original)
            current.update(ref=capacity_ref, evidence_refs=[capacity_basis],
                commitment_limit=known({'value': capacities[organization_id], 'currency': 'HKD', 'basis_ref': capacity_basis}))
            objects.append({'ref': capacity_ref, 'value': current})
        visible = [*quote_refs, *borrower_refs, offer, acceptance, recorded, authority, *[r['ref'] for r in objects]]
        visible = list({task_digest(r): r for r in visible}.values())
        grant = {'ref': authority, 'organization_id': organization_id, 'actor_id': organizations[organization_id]['actor_id'],
            'function_ref': function, 'action_ids': ['BANK-A05'], 'scopes': [context['scope']],
            'readable_refs': visible, 'tool_ids': [], 'basis_refs': [basis], 'validity': window}
        snapshot['authorizations'].append(grant)
        objects.append({'ref': authority, 'value': deepcopy(grant)})
        context.update(function_ref=function, authorization_refs=[authority], operation_id=tag,
            contract_ref=ref('ActionContract', 'BANK-A05'), task_ref=rr('DecisionTask', 'formation'),
            candidate_set_ref=candidates, read_token=tag + '-read', visible_refs=visible)
        condition_basis = [r for row in quote['objects'] if row['ref']['kind'] == 'Requirement'
            for r in row['value']['evidence_refs']]
        condition_basis = list({task_digest(r): r for r in [native, quote_evidence, acceptance_evidence, *condition_basis]}.values())
        inputs = {'offer_ref': offer, 'borrower_acceptance_ref': acceptance, 'bank_authority_ref': authority,
            'condition_evidence_refs': condition_basis,
            'capacity_snapshot_ref': capacity_ref, 'formation_profile_ref': profile}
        plan = BankArrangementPlan.model_validate({'organization_id': organization_id, 'borrower_id': borrower,
            'project_id': bank['project_id'], 'tick': bank['tick'], 'context': context, 'action_input': inputs,
            'objects': objects, 'quote_read_refs': quote_refs, 'borrower_read_refs': borrower_refs,
            'prior_commitment_origins': existing_origins, 'native_evidence_ref': native,
            'quote_evidence_ref': quote_evidence, 'acceptance_evidence_ref': acceptance_evidence})
        schemas = BankArrangementActionAssembler.SOURCE_SCHEMAS()
        for row in plan.objects:
            value = deepcopy(row['value'])
            if row['ref']['kind'] == 'Evidence':
                value['content_hash'] = '0' * 64  # Static schema check only.
            schemas.validate_projection(Reference.model_validate(row['ref']), value)
        plans.append(plan.model_dump(mode='json'))
    snapshot['organizations'] = list(organizations.values())
    return {'version': '1', **_write(directory, 'bank-arrangement-input.json',
        {'schema_version': 'bank-arrangement-input.v1', 'run_id': run_id, 'plans': plans})}
