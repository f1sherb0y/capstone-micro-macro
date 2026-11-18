"""Independent initial private positions triggered by actual native payments.

No amount, currency, certificate, obligation or cash is derived from the native
aggregate request. These sources must be authored before runtime registration.
"""
from copy import deepcopy

from integration.final_account_discussion_development import initial_sources
from integration.native_lifecycle_actions import NativeLifecycleInput
from src.organization.registry import OrganizationSnapshot


def shared_initial_sources(*, run_id, project_id, organization_snapshot,
        owner_id, contractor_id, clock_id, tick=1,source_namespace=None,
        authorization_read_until_tick=None):
    """Reuse original A06/A10 workers with separate declared private positions.

    Owner responds to a real request; Contractor reviews a real delay only.
    Detailed disputed obligations are independent synthetic assumptions with
    unknown money. Neither private result is a formal payment submission.
    """
    if type(tick) is not int or tick < 1:
        raise ValueError('Progress-payment source tick must be an explicit positive integer')
    if authorization_read_until_tick is not None and (
            type(authorization_read_until_tick) is not int or authorization_read_until_tick < tick):
        raise ValueError('Private payment read horizon must include its original action tick')
    if source_namespace is not None and (not isinstance(source_namespace,str) or not source_namespace.strip()):
        raise ValueError('Private payment source namespace must be a nonempty string')
    prefix = 'progress-payment:' if tick == 1 else f'progress-payment:t{tick}:'
    suffix = '' if tick == 1 else f'-t{tick}'
    if source_namespace is not None:
        prefix+=source_namespace+':'
        suffix+='-'+source_namespace
    existing = {o['organization_id']: o for o in organization_snapshot['organizations']}
    roles = {owner_id: 'Owner', contractor_id: 'Contractor'}
    if (organization_snapshot['run_id'] != run_id or len(roles) != 2
            or any(org not in existing or role not in {a['role'] for a in existing[org]['assignments']}
                for org, role in roles.items())):
        raise ValueError('Progress-payment sources require the original shared Owner and Contractor')
    snapshot, document = initial_sources(run_id=run_id, project_id=project_id,
        successor=False, with_qs=False)
    names = {'owner': owner_id, 'native-contractor': contractor_id}

    def fresh(value, key=None):
        if isinstance(value, str):
            if key == 'actor_id' and value == 'owner-actor':
                return existing[owner_id]['actor_id']
            if key in {'operation_id', 'read_token'}:
                return prefix + value
            return names.get(value, value)
        if isinstance(value, list):
            return [fresh(v, key) for v in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {'clock_ref','offset'}:
            return {'clock_ref':fresh(value['clock_ref']),
                'offset':value['offset'] if value['offset'] <= 0 else value['offset'] + tick - 1}
        if set(value) == {'kind', 'id', 'version'}:
            row = deepcopy(value)
            if row['kind'] == 'ClockProfile':
                row['id'] = clock_id
            elif row['kind'] not in {'ActionContract', 'Project'}:
                row['id'] = prefix + row['id']
            return row
        return {k: fresh(v, k) for k, v in value.items()}

    snapshot, document = fresh(snapshot), fresh(document)
    snapshot['organizations'] = [o for o in snapshot['organizations'] if o['organization_id'] == owner_id]
    owner_org, = snapshot['organizations']
    owner_org.update(public_location=deepcopy(existing[owner_id]['public_location']),
        public_description='Explicit initial private progress-payment position; money remains unknown.')
    owner, = document['plans']
    owner.update(plan_id='shared-progress-payment-owner'+suffix, tick=tick, event_type='payment_requested',
        final_account_disclosure=None)
    rows = owner['objects']
    native = owner['native_evidence_ref']
    decision, = [r['value'] for r in rows if r['ref']['kind'] == 'PaymentAuthorization']
    decision.update(choice='negotiate',
        note='Review the actual aggregate payment request against the independently disputed item. '
             'Request status does not prove a detailed certificate, due amount, cash execution or debt clearance.')
    decision['evidence_refs'].append(deepcopy(native))
    owner['action_input']['evidence_refs'].append(deepcopy(native))
    for row in rows:
        if row['ref']['kind'] == 'CandidateSet':
            for candidate in row['value']['candidates']:
                candidate['permitted_choices'] = ['negotiate']

    # New Contractor declarations share no Owner authorization or private
    # result. The dispute itself needs an independent obligation and issue;
    # a native delay is only the trigger and observed basis, never that debt.
    context = deepcopy(owner['context'])
    def ref(kind, name):
        return {'kind': kind, 'id': prefix + 'contractor-' + name, 'version': '1'}
    context.update(actor_id=existing[contractor_id]['actor_id'], function_ref=ref('FunctionAssignment', 'function'),
        authorization_refs=[ref('Authorization', 'grant')],
        operation_id=prefix+'contractor-delay-dispute',
        contract_ref={'kind': 'ActionContract', 'id': 'CONTRACTOR-A10', 'version': '1'},
        task_ref=ref('DecisionTask', 'task'), candidate_set_ref=ref('CandidateSet', 'candidates'),
        read_token=prefix+'contractor-delay-dispute:read:1')
    scope, now = context['scope'], context['business_time']
    evidence = [deepcopy(r) for r in rows if r['ref']['kind'] == 'Evidence']
    assumed = next(r['ref'] for r in evidence if r['value']['basis_kind'] == 'assumed')
    native_contractor = ref('Evidence', 'actual-delay')
    evidence = [r for r in evidence if r['ref'] != native]
    observed = deepcopy(next(r['value'] for r in rows if r['ref'] == native))
    observed['ref'] = native_contractor
    evidence.append({'ref': native_contractor, 'value': observed})
    obligation = deepcopy(next(r['value'] for r in rows if r['ref']['kind'] == 'Obligation'))
    obligation.update(ref=ref('Obligation', 'independent-disputed-work'),
        source_ref=ref('FundingSource', 'independent-unsupplied-source'),
        component_refs=[ref('SettlementComponent', 'independent-unsupplied-component')])
    contract_ref, rule_ref = ref('Contract', 'initial-contract'), ref('SettlementRule', 'rule')
    procedure_ref, issue_ref = ref('SettlementProcedure', 'procedure'), ref('Issue', 'independent-disputed-item')
    common = {'scope': deepcopy(scope), 'available_at': deepcopy(now),
        'effective_window': deepcopy(decision['effective_window']), 'evidence_refs': [deepcopy(assumed)]}
    known = {'state': 'known', 'value': True}
    function = {'role': 'Contractor', 'function_ref': context['function_ref'],
        'configuration_version': '1', 'basis_refs': [deepcopy(assumed)]}
    grant = deepcopy(snapshot['authorizations'][0])
    grant.update(ref=context['authorization_refs'][0], organization_id=contractor_id,
        actor_id=context['actor_id'], function_ref=context['function_ref'], action_ids=['CONTRACTOR-A10'])
    objects = evidence + [deepcopy(r) for r in rows if r['ref']['kind'] == 'WorkScope']
    declarations = [
        (context['function_ref'], function),
        (context['candidate_set_ref'], {'operation_id': context['operation_id'], 'scope': scope, 'as_of': now,
            'candidates': [{'ref': obligation['ref'], 'permitted_choices': ['dispute']}],
            'search_profile_ref': ref('Profile', 'explicit-private-dispute')}),
        (contract_ref, {**common, 'ref': contract_ref, 'contractor_id': contractor_id, 'client_id': owner_id,
            'currency': 'HKD', 'effective': known, 'settlement_rule_ref': rule_ref,
            'measurement_application_refs': [], 'measurement_history_complete': False,
            'certificate_refs': [], 'obligation_refs': [obligation['ref']], 'execution_refs': [],
            'payment_history_complete': False, 'as_of': now}),
        (procedure_ref, {**common, 'ref': procedure_ref, 'contract_ref': contract_ref,
            'permitted_choices': ['dispute'], 'permitted': known, 'recipient_ids': [owner_id],
            'valuation_basis_refs': []}),
        (rule_ref, {**common, 'ref': rule_ref, 'contract_ref': contract_ref, 'organization_id': contractor_id,
            'actor_id': context['actor_id'], 'function_ref': context['function_ref'], 'authority_ref': grant['ref'],
            'procedure_ref': procedure_ref, 'choice': 'dispute', 'business_key': context['operation_id'],
            'measurement': None, 'component_refs': [], 'account_ref': None, 'lines': [], 'allow_partial': False,
            'financing': None, 'execution_refs': [], 'obligation_refs': [obligation['ref']], 'issue_refs': [issue_ref],
            'basis_refs': [assumed, native_contractor],
            'note': 'Review the actual native payment delay against an independently disputed obligation. '
                'The obligation amounts and payment history remain unknown; no debt or cash is inferred.'}),
        (issue_ref, {**common, 'ref': issue_ref, 'contract_ref': contract_ref,
            'obligation_refs': [obligation['ref']], 'status': 'disputed'}),
        (obligation['ref'], obligation), (grant['ref'], grant),
    ]
    objects.extend({'ref': deepcopy(r), 'value': deepcopy(v)} for r, v in declarations)
    context['visible_refs'] = [deepcopy(r['ref']) for r in objects]
    grant['readable_refs'] = deepcopy(context['visible_refs'])
    next(r for r in objects if r['ref'] == grant['ref'])['value'] = deepcopy(grant)
    contractor = {'plan_id': 'shared-progress-payment-contractor'+suffix, 'organization_id': contractor_id,
        'project_id': project_id, 'tick': tick, 'event_type': 'payment_delayed', 'context': context,
        'native_evidence_ref': native_contractor, 'objects': objects,
        'action_input': {'contract_ref': contract_ref, 'work_record_refs': [], 'certificate_refs': [],
            'obligation_refs': [obligation['ref']], 'account_refs': [], 'execution_refs': [],
            'settlement_rule_ref': rule_ref}}
    contractor_org = deepcopy(existing[contractor_id])
    contractor_org.update(assignments=[function], source_ids=['synthetic:independent-private-payment-dispute'],
        evidence_refs=[assumed], members=[],
        public_description='Explicit initial Contractor private dispute; no native debt or currency conversion.')
    if source_namespace is not None:
        contractor_org['source_ids']=['synthetic:independent-private-payment-dispute:'+contractor_id+':'+source_namespace]
    snapshot['organizations'].append(contractor_org)
    snapshot['authorizations'].append(grant)
    document['plans'] = [owner, contractor]
    if authorization_read_until_tick is not None:
        # Initial scenario authority for retaining private evidence through the
        # declared review window. Keep every party, scope, action and read set.
        # Current-time authorization/revocation checks remain unchanged.
        for authorization in snapshot['authorizations']:
            end = authorization['validity'].get('end')
            if end is not None:
                end['offset'] = max(end['offset'], authorization_read_until_tick + 1)
        key = lambda ref: (ref['kind'], ref['id'], ref['version'])
        by_ref = {key(g['ref']): g for g in snapshot['authorizations']}
        for plan in document['plans']:
            for row in plan['objects']:
                if row['ref']['kind'] == 'Authorization' and key(row['ref']) in by_ref:
                    row['value'] = deepcopy(by_ref[key(row['ref'])])
    return (OrganizationSnapshot.model_validate(snapshot).model_dump(mode='json'),
        NativeLifecycleInput.model_validate(document).model_dump(mode='json'))
