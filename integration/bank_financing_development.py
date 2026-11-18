"""Independent assumed banking sources bound to actual native finance requests."""
from copy import deepcopy
from decimal import Decimal
import argparse
import hashlib
import json
from pathlib import Path

from integration.contractor_tender_development import _write, _write_launch_files, ref, known
from integration.project_financing_development import build_bundle as native_bundle
from integration.bank_financing_native import BankFinancingSettings, BankFinancingPlan, COMPONENTS
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest
from integration.development_owner_funding import initial_owner_fundings


def initial_credit_conditions(values):
    if values is None:
        return {}
    if (not isinstance(values, dict) or set(values) - {'finance-bank-a', 'finance-bank-b'}
            or any(value not in ('satisfied', 'unsatisfied') for value in values.values())):
        raise ValueError('Initial credit conditions require configured Bank identities and explicit verified outcomes')
    return deepcopy(values)


def initial_organization_actors(values, organization_ids):
    """Declare actors before constructing sources; business party IDs stay fixed."""
    actors = {organization: organization for organization in organization_ids}
    if values is not None:
        if (not isinstance(values, dict) or set(values) - set(actors)
                or any(type(actor) is not str or not actor.strip() for actor in values.values())):
            raise ValueError('Initial actors require known organizations and nonempty actor IDs')
        actors.update(values)
    if len(set(actors.values())) != len(actors):
        raise ValueError('Initial actors must be distinct across the original organizations')
    return actors


def build_bundle(directory, *, run_id, with_owner=False, feedback_followup=False, with_bank_strategy=False,
        with_arrangement=False, project_schedule=None, write_launch=True,owner_funding=None,
        intake_decline_banks=(),with_monthly_strategy=False,monthly_max_prior_reviews=1,monthly_strategy_ticks=None,
        allow_monthly_saved_recovery=False,query_saved_bank_monthly_on_error=False,credit_condition_outcomes=None,
        allow_saved_recovery=False,query_saved_financing_on_error=False,continue_unstarted_actions_on_error=False,
        arrangement_principal_limits=None,with_unconfirmed_arrangement_feedback=False,organization_actor_ids=None,
        arrangement_capacity_limits=None, prior_refusal_priority_penalty=0):
    actors = initial_organization_actors(organization_actor_ids,
        ['finance-owner-a','finance-owner-b','finance-bank-a','finance-bank-b',
            *['finance-' + role for role in ('architect','engineer','qs','government','contractor','supplier')]])
    if with_owner and 'disclosed-other-lender' in actors.values():
        raise ValueError('Initial actors must remain distinct from the independent existing debt author')
    condition_outcomes = initial_credit_conditions(credit_condition_outcomes)
    from integration.bank_arrangement_native_development import initial_formation_limits
    formation_limits = initial_formation_limits(arrangement_principal_limits)
    capacity_limits = initial_formation_limits(arrangement_capacity_limits)
    if arrangement_principal_limits is not None and not with_arrangement:
        raise ValueError('Independent formation limits require --with-arrangement')
    if arrangement_capacity_limits is not None and not with_arrangement:
        raise ValueError('Independent formation capacity limits require --with-arrangement')
    if with_unconfirmed_arrangement_feedback and not (with_arrangement and with_bank_strategy):
        raise ValueError('Unconfirmed arrangement feedback requires --with-arrangement and --with-bank-strategy')
    if query_saved_financing_on_error and not allow_saved_recovery:
        raise ValueError('Bank financing query requires --allow-saved-recovery')
    if allow_monthly_saved_recovery and not with_monthly_strategy:
        raise ValueError('Bank monthly saved recovery requires --with-monthly-strategy')
    if query_saved_bank_monthly_on_error and not allow_monthly_saved_recovery:
        raise ValueError('Bank monthly query requires --allow-monthly-saved-recovery')
    intake_decline_banks = tuple(intake_decline_banks)
    if (len(set(intake_decline_banks)) != len(intake_decline_banks)
            or set(intake_decline_banks) - {'finance-bank-a', 'finance-bank-b'}):
        raise ValueError('Intake refusal assumptions require distinct explicitly configured Bank identities')
    owner_funding=initial_owner_fundings(owner_funding)
    if set(owner_funding)-{'finance-owner-a','finance-owner-b'}:
        raise ValueError('Initial funding declarations must identify configured Owners')
    if with_arrangement and not with_owner:
        raise ValueError('Original Bank A05 reception requires --with-owner and its independent actual acceptance')
    if feedback_followup and not with_owner:
        raise ValueError('Financing feedback follow-up requires the original Owner micro worker')
    if project_schedule is not None:
        project_schedule = list(project_schedule)
        if (not project_schedule or any(not isinstance(p, (tuple, list)) or len(p) != 2
                or not isinstance(p[0], str) or not p[0] or type(p[1]) is not int or p[1] < 1
                for p in project_schedule)
                or len({tuple(p) for p in project_schedule}) != len(project_schedule)):
            raise ValueError('Explicit bank project schedule requires distinct project/time source selectors')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    if organization_actor_ids is not None:
        _write(directory,'initial-organization-actors.json',{'organization_actor_ids':actors,
            'boundary':'Explicit initial declarations before source sealing; no native agent, business party or saved history is renamed.'})
    if owner_funding:
        _write(directory,'initial-owner-funding.json',[row.model_dump(mode='json') for row in owner_funding.values()])
    if credit_condition_outcomes is not None:
        _write(directory, 'initial-credit-conditions.json', condition_outcomes)
    if arrangement_principal_limits is not None:
        _write(directory, 'initial-arrangement-principal-limits.json', formation_limits)
    if arrangement_capacity_limits is not None:
        _write(directory, 'initial-arrangement-capacity-limits.json', capacity_limits)
    native_bundle(directory / 'native', run_id=run_id)
    native_request = json.loads((directory / 'native/macro-request.json').read_text(encoding='utf-8'))
    projects = [('PGEN0001',1), ('PGEN0002',1)]
    if feedback_followup:
        native_request.update(target_project_count=4,max_active_projects=4,ticks=2)
        projects += [('PGEN0003',2), ('PGEN0004',2)]
        if with_monthly_strategy:
            # The second monthly strategy follows second-tick financing.
            # Only a third real tick can consume that strictly earlier choice.
            native_request.update(target_project_count=6,max_active_projects=6,ticks=3)
            projects += [('PGEN0005',3),('PGEN0006',3)]
    if project_schedule is not None:
        projects = list(project_schedule)
    template_path = Path(__file__).resolve().parents[1] / 'tests/fixtures/roles/bank_credit.v1.json'
    template = json.loads(template_path.read_bytes())
    template_sha = hashlib.sha256(template_path.read_bytes()).hexdigest()
    organizations, plans, grants = {}, [], []
    roles = {a['agent_id']: a['role'] for a in native_request['agents']}
    regions = {'Guangzhou':'GZ','Shenzhen':'SZ','Hong Kong':'HK','Macau':'MO','Zhuhai':'ZH','Foshan':'FS',
               'Dongguan':'DG','Huizhou':'HZ','Zhongshan':'ZS','Jiangmen':'JM','Zhaoqing':'ZQ'}
    for org, role in roles.items():
        organizations[org] = {'organization_id': org, 'actor_id': actors[org], 'source_ids': ['synthetic:' + org],
            'public_description': 'Explicit assumed banking scenario; native scalars are not real cash or credit facts.',
            'public_location': known('Hong Kong'), 'members': [], 'evidence_refs': [ref('Evidence', org + '-basis')],
            'assignments': [{'role': role, 'function_ref': ref('FunctionAssignment', org + '-support'),
                'configuration_version': '1', 'basis_refs': [ref('Evidence', org + '-basis')]}]}
    for bank in ['finance-bank-a', 'finance-bank-b']:
        for owner in ['finance-owner-a', 'finance-owner-b']:
            for project, tick in projects:
                tag = bank + '-' + owner + '-' + project
                def rr(kind, name):
                    return ref(kind, tag + '-' + name)
                # All banks observe the same monthly business clock. A native
                # organization/project version must not change with its reader.
                clock = ref('ClockProfile', run_id + '-monthly-clock')
                point = lambda n: {'clock_ref': clock, 'offset': n}
                window = {'start': point(0), 'end': point(99), 'bounds': 'closed_open'}
                scope = {'kind': 'project', 'ref': ref('Project', project), 'coverage_refs': []}
                basis, native, intake, audit = [rr('Evidence', name) for name in ['synthetic-basis','native-request','intake-result','review-audit']]
                # This scale is an explicit scenario assumption applied only to
                # template money, independent of native financial-capacity scalars.
                def remap(value):
                    if isinstance(value, list): return [remap(v) for v in value]
                    if not isinstance(value, dict):
                        return {'fixture-bank': bank, 'fixture-bank-actor': actors[bank],
                            'fixture-borrower': owner, 'borrower-actor': actors[owner]}.get(value, value) if isinstance(value, str) else value
                    if set(value) == {'kind','id','version'}:
                        if value['kind'] in {'Method'}: return deepcopy(value)
                        if value['kind'] == 'Organization' and value['id'] == 'fixture-borrower': return ref('Organization', owner)
                        if value['kind'] == 'FundingPurpose': return ref('FundingPurpose', owner + '-' + project + '-purpose')
                        if (value['kind'],value['id']) in {('Account','borrower-cash'),('Debt','old-debt'),
                                ('DebtComponent','old-principal'),('Obligation','due-mirror'),('BorrowerPortfolio','borrower-portfolio'),
                                ('Project','old-project')}:
                            identity = ref(value['kind'], owner + '-' + value['id'])
                            if value['kind'] != 'Project': identity['version'] = str(tick)
                            return identity
                        if value['kind'] == 'OwnerCase': return scope['ref']
                        if value['kind'] == 'ClockProfile': return clock
                        return rr(value['kind'], value['id'])
                    if 'clock_ref' in value and 'offset' in value:
                        return point(max(0, value['offset'] - 1))
                    if value.get('kind') == 'assessment_case': return deepcopy(scope)
                    result = {k: remap(v) for k,v in value.items()}
                    if 'as_of' in result: result['as_of'] = point(tick)
                    if {'value','currency','basis_ref'} <= set(value):
                        result['value'] = format(Decimal(value['value']) * 1000000, 'f')
                    return result
                objects = remap(template['objects'])
                bank_initial_cash={key:next(r['value'] for r in objects if r['ref']['kind']=='Account')[key]['value']['value']
                    for key in ('actual_cash','restricted_cash')}
                funding=owner_funding.get(owner)
                if funding is not None:
                    for item in objects:
                        value=item['value']
                        if item['ref']['kind']=='Account' and value['borrower_id']==owner:
                            value['actual_cash']['value']['value']=funding.actual_cash
                            value['restricted_cash']['value']['value']=funding.restricted_cash
                action_input = remap(template['input'])
                def named(kind):
                    return next(r['value'] for r in objects if r['ref']['kind'] == kind)
                parent = named('Project')
                parent['region_id'] = None
                project_evidence = ref('Evidence', project + '-native-financing-source')
                parent['evidence_refs'] = [project_evidence]
                parent['available_at'] = point(tick)
                borrower_evidence = ref('Evidence', owner + '-assumed-financing-disclosure')
                named('Organization')['evidence_refs'] = [borrower_evidence]
                def shared_basis(value):
                    if isinstance(value,list): return [shared_basis(v) for v in value]
                    if not isinstance(value,dict): return value
                    if value == basis: return deepcopy(borrower_evidence)
                    return {k:shared_basis(v) for k,v in value.items()}
                for row in objects:
                    if row['ref']['kind'] in {'Account','Debt','DebtComponent','Obligation','BorrowerPortfolio','FundingPurpose'}:
                        row['value'] = shared_basis(row['value'])
                objects.extend([
                    {'ref': borrower_evidence, 'value': {'ref': borrower_evidence,
                        'source_kind': 'synthetic', 'basis_kind': 'assumed',
                        'locator': 'explicit-shared-borrower-disclosure:' + template_sha,
                        'content_hash': task_digest({'template': template_sha, 'borrower': owner,
                            **({'initial_owner_funding':funding.model_dump(mode='json')}
                                if funding is not None else {})}),
                        'effective_window': window}},
                    {'ref': project_evidence, 'value': {'ref': project_evidence,
                        'source_kind': 'synthetic', 'basis_kind': 'observed',
                        'locator': 'actual-shared-native-project:' + project,
                        'content_hash': None, 'effective_window': window}},
                ])
                app = named('FinanceApplication')
                app['requested'].update(value=None, basis_ref=native)
                app['submitted_at'] = point(tick)
                named('FundingPurpose')['purpose_code'] = known('project_financing')
                named('FundingPurpose')['project_region_id'] = known(None)
                named('FundingPurpose')['stage'] = known('initiation')
                named('FinanceProductProfile')['allowed_purpose_codes'] = known(['project_financing'])
                if bank in intake_decline_banks:
                    # Independent initial product scope, not a forced result:
                    # the original A02 checks the actual received purpose.
                    named('FinanceProductProfile')['allowed_purpose_codes'] = known(['refinancing'])
                named('FinanceProductProfile')['allowed_stages'] = known(['initiation'])
                named('FinanceProductProfile')['allowed_project_region_ids'] = known(list(regions.values()))
                named('Account')['permitted_project_region_ids'] = known(list(regions.values()))
                # Independent borrower disclosure regions, product, purposes,
                # debt, accounts and forecasts retain their template assumptions.
                if bank == 'finance-bank-b' and not feedback_followup:
                    risk = named('RiskObservation')['interval']['value']
                    risk['lower']['value'], risk['upper']['value'] = '8', '9'
                if bank in condition_outcomes:
                    conditions = [r['value'] for r in objects if r['ref']['kind'] == 'Requirement']
                    if len(conditions) != 1 or conditions[0]['verification'] is None:
                        raise ValueError('Initial condition declaration needs one independently verified template condition')
                    conditions[0]['outcome'] = known(condition_outcomes[bank])
                for e in template['evidence']:
                    identity = rr('Evidence', e['id'])
                    objects.append({'ref': identity, 'value': {'ref': identity, 'source_kind': 'synthetic',
                        'basis_kind': 'assumed', 'locator': 'explicit-banking-template:' + template_sha,
                        'content_hash': task_digest({'template': template_sha, 'money_scale': 1000000,
                            'bank': bank, 'owner': owner, 'project': project, 'as_of_tick':tick,
                            'risk_interval': '8..9' if bank.endswith('-b') and not feedback_followup else '2..3',
                            **({'initial_verified_condition': condition_outcomes[bank]} if bank in condition_outcomes else {})}),
                        'effective_window': None}})
                for ev in [native, intake]:
                    objects.append({'ref': ev, 'value': {'ref': ev, 'source_kind': 'synthetic', 'basis_kind': 'observed',
                        'locator': 'actual-bank-micro-source:' + ev['id'], 'content_hash': None, 'effective_window': window}})
                review_fn, quote_fn = rr('FunctionAssignment','bank-review'), rr('FunctionAssignment','bank-quote')
                for fn in [review_fn, quote_fn]:
                    assignment = {'role': 'Bank', 'function_ref': fn, 'configuration_version': '1', 'basis_refs': [basis]}
                    organizations[bank]['assignments'].append(assignment)
                    objects.append({'ref': fn, 'value': deepcopy(assignment)})
                owner_assignment = next(r['value'] for r in objects if r['ref']['kind'] == 'FunctionAssignment'
                                        and r['value']['role'] == 'Owner')
                organizations[owner]['assignments'].append(deepcopy(owner_assignment))
                owner_grant = named('Authorization')
                owner_grant['readable_refs'] = [basis, rr('Evidence','identity-disclosure')]
                review_grant = {'ref': rr('Authorization','bank-review-grant'), 'organization_id': bank, 'actor_id': actors[bank],
                    'function_ref': review_fn, 'action_ids': ['BANK-A02','BANK-A03'], 'scopes': [scope],
                    'readable_refs': [], 'tool_ids': [], 'basis_refs': [basis], 'validity': window}
                quote_grant = {**deepcopy(review_grant), 'ref': rr('Authorization','bank-quote-grant'),
                    'function_ref': quote_fn, 'action_ids': ['BANK-A04'],
                    'basis_refs': [basis, rr('QuoteAuthorityPolicy','quote-limit')]}
                objects.append({'ref': review_grant['ref'], 'value': review_grant})
                base_objects = [r for r in objects if r['ref'] not in [quote_fn, intake]]
                intake_kinds = {'Evidence','FinanceApplication','Organization','Authorization','FunctionAssignment',
                                'FundingPurpose','FinanceProductProfile','Requirement'}
                intake_objects = deepcopy([r for r in base_objects if r['ref']['kind'] in intake_kinds])
                for row in intake_objects:
                    if row['ref']['kind'] == 'Requirement':
                        row['value'] = {k:v for k,v in row['value'].items() if k in {'ref','product_ref','scope_ref','evidence_refs'}}
                        row['value']['description'] = 'Explicit assumed borrower condition'
                    if row['ref']['kind'] == 'Project':
                        row['value'] = {'ref': row['ref'], 'evidence_refs': [basis]}
                credit_objects = deepcopy([r for r in objects if r['ref'] != quote_fn])
                quote_objects = deepcopy(objects)
                def add(object_kind, name, **values):
                    identity = rr(object_kind, name)
                    quote_objects.append({'ref': identity, 'value': {**({} if object_kind == 'TimeWindow' else {'ref': identity}), **values}})
                    return identity
                common = {'application_ref': app['ref'], 'product_ref': action_input['product_ref'], 'borrower_id': owner,
                    'lender_id': bank, 'effective_window': window, 'evidence_refs': [basis]}
                money = lambda v: {'value': v, 'currency':'HKD', 'basis_ref':basis}
                product = next(r['value'] for r in quote_objects if r['ref']['kind'] == 'FinanceProductProfile')
                product['quote_policy_ref'] = rr('QuoteProductPolicy','product-quotes')
                for row in quote_objects:
                    if row['ref']['kind'] == 'Requirement': row['value']['stage'] = 'arrangement_effective'
                add('QuoteProductPolicy','product-quotes', product_ref=product['ref'], lender_id=bank,
                    pricing_refs=[rr('PricingRule','price')], selection_rule='lowest_declared_priority',
                    amount_rule='largest_feasible_authorized_amount', effective_window=window, evidence_refs=[basis])
                add('QuoteAuthorityPolicy','quote-limit', authority_ref=quote_grant['ref'], application_ref=app['ref'],
                    product_ref=product['ref'], lender_id=bank, scope_ref=scope, maximum_principal=known(money('100000000')),
                    permits_terms_reassessment=True, allowed_pricing_refs=[rr('PricingRule','price')],
                    allowed_reservation_refs=[rr('ReservationPolicy','reservation')], effective_window=window, evidence_refs=[basis])
                add('TimeWindow','tenor', start=point(3), end=point(7), bounds='closed_closed')
                # Each declared source must permit quotation at its own time.
                # Extending the scenario does not extend an existing offer:
                # these are independently declared original per-project terms.
                add('TimeWindow','validity', start=point(1), end=point(max(3,tick+1)), bounds='closed_open')
                add('Assumption','quote-factors', method_ref=rr('FinanceFeasibilityMethod','cash-method'),
                    description='Explicit assumed zero fee and simple ten percent interest over four monthly periods',
                    effective_window=window, evidence_refs=[basis])
                add('PricingRule','price', **common, priority=known(1), status='available', currency='HKD',
                    tenor_ref=rr('TimeWindow','tenor'), validity_ref=rr('TimeWindow','validity'), fee_rule_refs=[rr('FeeRule','fee')],
                    repayment_rule_ref=rr('RepaymentRule','repay'), reservation_policy_ref=rr('ReservationPolicy','reservation'),
                    funding_path_ref=rr('FundingPath','path'), condition_refs=[], assumption_ref=rr('Assumption','quote-factors'),
                    interest_payments=known([{'local_key':'interest','time':point(7),'principal_factor':'0.1'}]))
                add('FeeRule','fee', **common, time=point(7), fixed_amount=known(money('0')), principal_factor=known('0'))
                add('RepaymentRule','repay', **common, payments=known([{'local_key':'principal','time':point(7),'principal_factor':'1'}]))
                add('ReservationPolicy','reservation', **common, binding=False, reserves_capacity=False, quantity_rule='none',
                    expiry_ref=rr('TimeWindow','validity'), conversion_rule_ref=None, release_rule_ref=None, acceptance_action_id='OWN-A05')
                add('FundingPath','path', **common, currency='HKD', beneficiary_id=owner,
                    destination_ref=named('Account')['ref'], funding_account_ref=rr('Account','bank-funding'),
                    permitted_region_ids=known(list(regions.values())), kind='borrower_account')
                bank_account = deepcopy(named('Account'))
                bank_account.update(ref=rr('Account','bank-funding'), borrower_id=bank)
                for key,amount in bank_initial_cash.items():
                    bank_account[key]['value']['value']=amount
                quote_objects.append({'ref': bank_account['ref'], 'value': bank_account})
                quote_objects.append({'ref': quote_grant['ref'], 'value': quote_grant})
                for identity in [rr('RecordedDecision','review'), rr('CreditAssessment','assessment')]:
                    quote_objects.append({'ref': identity, 'value': None})
                add('Evidence','review-audit', source_kind='synthetic', basis_kind='observed',
                    locator='actual-private-credit-worker-audit', content_hash=None, effective_window=window)
                quote_input = {'application_ref':app['ref'], 'assessment_ref':rr('CreditAssessment','assessment'),
                    'authority_ref':quote_grant['ref'], 'product_ref':product['ref'], 'pricing_candidates':[rr('PricingRule','price')],
                    'capacity_snapshot_ref':rr('LendingCapacity','bank-capacity'), 'funding_path_refs':[rr('FundingPath','path')]}
                steps = {}
                for action, rows, inp, grant in [('BANK-A02',intake_objects,{'application_ref':app['ref']},review_grant),
                        ('BANK-A03',credit_objects,action_input,review_grant),('BANK-A04',quote_objects,quote_input,quote_grant)]:
                    candidate = rr('CandidateSet', action)
                    rows.append({'ref':candidate,'value':{'operation_id':tag+action,'scope':scope,'as_of':point(tick),
                        'candidates':([{'ref':product['ref'],'permitted_choices':['accept_for_review']}] if action == 'BANK-A02'
                            else [{'ref':rr('PricingRule','price'),'permitted_choices':['offer','conditional_offer']}] if action == 'BANK-A04' else []),
                        'search_profile_ref':rr('Profile','declared-candidates')}})
                    steps[action] = {'context': {'run_id':run_id,'actor_id':actors[bank],'function_ref':grant['function_ref'],
                        'authorization_refs':[grant['ref']],'operation_id':tag+action,'contract_ref':ref('ActionContract',action),
                        'task_ref':rr('DecisionTask',action),'scope':scope,'business_time':point(tick),'read_token':tag+action+'-read',
                        'visible_refs':[r['ref'] for r in rows],'candidate_set_ref':candidate,'execution_mode':'rule'},
                        'action_input':inp,'objects':rows}
                all_refs = list({task_digest(r['ref']):r['ref'] for s in steps.values() for r in s['objects']}.values())
                review_grant['readable_refs'] = quote_grant['readable_refs'] = all_refs
                for step in steps.values():
                    for row in step['objects']:
                        for grant in [review_grant,quote_grant,owner_grant]:
                            if row['ref'] == grant['ref']: row['value'] = deepcopy(grant)
                grants.extend([review_grant,quote_grant,owner_grant])
                plan = {'organization_id':bank,'borrower_id':owner,'project_id':project,'tick':tick,'steps':steps,
                    'native_evidence_ref':native,'native_project_evidence_ref':project_evidence,
                    'intake_evidence_ref':intake,'review_audit_ref':audit,
                    'recorded_review_ref':rr('RecordedDecision','review'),'periods_per_year':12,'native_region_ids':regions,
                    'utility':{'value':'0.7','unit':'score','basis_ref':basis},
                    'probability':{'value':'1','unit':'probability','basis_ref':basis}}
                checked = BankFinancingPlan.model_validate(plan)
                for action, step in checked.steps.items():
                    schemas = COMPONENTS[action][0].SOURCE_SCHEMAS()
                    for row in step.objects:
                        value = deepcopy(row['value'])
                        if value is None:
                            if row['ref'] not in [quote_input['assessment_ref'], rr('RecordedDecision','review')]:
                                raise ValueError('Only actual private review outputs may be deferred source objects')
                            continue
                        if row['ref']['kind'] == 'Evidence' and value['content_hash'] is None: value['content_hash'] = '0'*64
                        if row['ref']['kind'] == 'FinanceApplication': value['requested']['value'] = '1'
                        if row['ref']['kind'] == 'FundingPurpose': value['project_region_id'] = known('HK')
                        if row['ref']['kind'] == 'Project': value['region_id'] = 'HK'
                        schemas.validate_projection(Reference.model_validate(row['ref']), value)
                plans.append(checked.model_dump(mode='json'))
    if with_bank_strategy:
        from integration.bank_financing_strategy_development import extend_plans
        plans=extend_plans(plans,organizations,grants,feedback_basis=(
            'unconfirmed_arrangement_review' if with_unconfirmed_arrangement_feedback else 'selected_financing'))
        plans=[BankFinancingPlan.model_validate(p).model_dump(mode='json') for p in plans]
    monthly=None
    if with_monthly_strategy:
        from integration.bank_monthly_native_development import extend_monthly
        monthly={'version':'1','allow_saved_recovery':allow_monthly_saved_recovery,
            **extend_monthly(directory,run_id=run_id,plans=plans,
            organizations=organizations,grants=grants,ticks=monthly_strategy_ticks or native_request['ticks'],
            max_prior_reviews=monthly_max_prior_reviews)}
    source = _write(directory,'bank-financing-input.json',{'schema_version':'bank-financing-input.v1','run_id':run_id,'plans':plans})
    settings = BankFinancingSettings.model_validate({'version':'1','policy_version':'explicit-bank-source-v1',**source,
        'monthly_strategy':monthly, 'allow_saved_recovery':allow_saved_recovery,
        'continue_unstarted_actions_on_error':continue_unstarted_actions_on_error,
        'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{'schema_version':'organization.v2','run_id':run_id,
            'organizations':list(organizations.values()),'authorizations':grants}}})
    native_host = json.loads((directory/'native/native-host.json').read_text(encoding='utf-8'))
    native_host['settings']['native_financing_proposal_transport'] = False
    native_host['settings']['query_saved_financing_on_error'] = query_saved_financing_on_error
    if with_monthly_strategy:
        native_host['settings']['micro_bank_monthly_strategy_scope']=True
        native_host['settings']['query_saved_bank_monthly_on_error']=query_saved_bank_monthly_on_error
        native_host['settings']['native_proposals']=[r for r in native_host['settings']['native_proposals']
            if (r['role'],r['operation'])!=('Bank','decide_monthly_operation')]
        native_host['settings']['native_decisions']=[r for r in native_host['settings']['native_decisions']
            if (r['role'],r['decision_type'])!=('Bank','monthly_enterprise_operation')]
    native_host['settings']['native_financing_proposal_transport_roles'] = ['Owner']
    native_host['settings']['native_proposals'] = [r for r in native_host['settings']['native_proposals'] if (r['role'],r['operation']) != ('Bank','consider_financing')]
    native_host['settings']['native_decisions'] = [r for r in native_host['settings']['native_decisions'] if (r['role'],r['decision_type']) != ('Bank','bank_project_financing')]
    if feedback_followup:
        # These are original support decisions, explicitly declared before the
        # run; they do not count as micro professional appointment coverage.
        native_host['settings']['native_professional_intake_scope'] = True
        native_host['settings']['native_proposals'] += [
            {'role':r,'operation':'consider_appointment'} for r in ('Architect','Engineer','QS')]
        native_host['settings']['native_proposals'].append({'role':'Owner','operation':'select_appointment'})
        native_host['settings']['native_decisions'] += [
            {'role':r,'decision_type':r.lower()+'_appointment_acceptance'} for r in ('Architect','Engineer','QS')]
        native_host['settings']['native_decisions'] += [
            {'role':'Owner','decision_type':'owner_select_'+r} for r in ('architect','engineer','qs')]
    if with_owner:
        from integration.owner_financing_development import extend_bundle
        expanded,native_host=extend_bundle(directory,run_id=run_id,bank_plans=plans,
            settings=settings.model_dump(mode='json'),native_host=native_host,
            repeat_lender_priority_penalty=2 if feedback_followup else 0, with_arrangement=with_arrangement,
            prior_refusal_priority_penalty=prior_refusal_priority_penalty,
            owner_funding=list(owner_funding.values()),arrangement_principal_limits=formation_limits,
            arrangement_capacity_limits=capacity_limits)
        settings=BankFinancingSettings.model_validate(expanded)
    _write(directory,'native-host.json',native_host)
    _write(directory,'macro-request.json',native_request)
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    readme='''# 合成银行微观处理与原生融资

运行 `& './run.ps1'`。原宏观创建项目后，实际银行请求执行原 BANK-A02/A03/A04，再返回原生融资接口。
账户、完整债务、预测、资格、授权和详细条款来自明确合成模板，金额独立放大一百万倍；不是原生财务能力换算出的现金。
Bank A 的风险区间明确为 2..3，Bank B 为 8..9；原风险方法、现金边界和报价方法实际决定结果，输入不预填微观答案。
申请金额、项目和借款人由当前原生请求绑定；报价年利率仅支持无费用、四个月期末简单利息的显式换算。
A02/A03 的交接读取同一任务库中的真实微观结果和审计，不生成正式受理回执或授信登记。
宏观仍负责正式融资决定和选中银行；微观不建立第二套正式账本，不声称已提款、到账或付款。
业主选择仍为原生行为，不计 OWN-A05 微观完成。其他融资分支、后续微观反馈消费、C3—C4 和模型调用继续接线。
'''
    if with_monthly_strategy:
        readme+='\n--with-monthly-strategy 让真实银行月度请求执行原 BANK-A01，原生最终确认使用同一结果。较早本行实际月度事件及其原始来源用于后续月份和融资报价；--monthly-max-prior-reviews 为独立私有次数阈值，默认 1。Bank A 达到阈值后暂停新的报价金额授权，Bank B 保留原独立上限；只收紧原 A04 私有上限，不改历史条款、现金、贷款或资源占用，不将月度能力随机变化当作资金。该窗口使用明确合成的逐时点组合披露，不调用真实模型。\n'
    if with_owner:
        readme=readme.replace('业主选择仍为原生行为，不计 OWN-A05 微观完成。',
            '业主选择执行原 OWN-A05，读取实际传达报价的原条款和独立资金计划；不生成正式报价登记回执。')
        readme+='\n业主初始账户现金 3000 万、受限 1000 万、较早债务本金 1500 万于时点 2 到期；项目计划支出 5000 万于时点 3。\n独立假设的未来批准非银行资金 1 亿于时点 6 可用，不把银行收入预测或原生融资选择计为实际到账。旧融资安排及独立接受均为明确初始假设，不是运行中生成的正式状态。\n'
    if owner_funding:
        readme+='\n本包显式初始现金声明以 initial-owner-funding.json 为准，覆盖上面的对应业主默认现金说明；同一业主的 Bank 审查与 OWN-A05 使用同源声明，旧欠款保持未付，不从宏观能力换算现金。\n'
    if feedback_followup:
        readme=readme.replace('Bank A 的风险区间明确为 2..3，Bank B 为 8..9；',
            '本反馈窗口两家银行的风险区间均明确为 2..3；')
        readme+='\n本窗口运行两个原生时点，最多四个原生生成项目。业主显式偏好：每条较早实际选行反馈给该银行的比较序号加 2，仍由原 OWN-A05 方法比较。\n各时点的账户、债务和组合采用独立版本与明确假设的读取快照；不把选行反馈转换成融资安排、负债或现金。其他专业委任采用原生行为，不计微观覆盖。\n'
        if with_monthly_strategy:
            readme=readme.replace('本窗口运行两个原生时点，最多四个原生生成项目。',
                '本月度策略窗口运行三个原生时点，最多六个原生生成项目；后续报价只消费严格较早的月度结果。')
    if with_owner and with_monthly_strategy:
        readme+='\n原 OWN-A05 若因独立资金约束返回 no_finance，将保留未决并停止：当前冻结选行接口只支持选择银行或自筹，不能把无融资改成自筹。可用 --initial-owner-funding <JSON路径> 显式声明一名或多名业主的初始 actual_cash / restricted_cash；输入必须包含 organization_id，重复身份拒绝。声明在执行前写入本包，并供银行与业主原动作共同读取，不代表运行中已融资到账。\n'
    if allow_monthly_saved_recovery:
        readme+='\n--allow-monthly-saved-recovery 允许查询当前原银行月度调用的已保存 BANK-A01；--query-saved-bank-monthly-on-error 允许原调用异常后查询并交回同一结果。均默认关闭；恢复前核对原快照、输入、版本、授权、来源及提案摘要，仅完成原技术任务，不重跑处理器或重启宏观。缺保存结果或未解决策略保持原异常及未决，不创建新业务或正式回执。\n'
    if allow_saved_recovery or continue_unstarted_actions_on_error:
        readme+='\n--allow-saved-recovery / --query-saved-financing-on-error 仅查询当前原银行融资调用的完整已保存结果：真实 A02 拒绝，或完整 A01（如启用）/A02/A03/A04 链。核对全部原读取、授权、快照和版本后交回同一原调用，不再执行处理器；接受受理但未形成报价、缺资料、失败及未知结果保持未决。--continue-unstarted-actions-on-error 独立允许原注册任务证明决策准备尚未开始时，在当前调用内执行一次；准备已开始不重试。均默认关闭，不是业务补证、宏观重启、重复申请、正式授信或到账。\n'
    if with_bank_strategy:
        readme+='\n银行请求先执行原 BANK-A01，读取本银行已收到的严格较早选行反馈，按当前借款人排重计数。\n显式合成新业务策略：同一借款人已有一次本行被选中，则暂停其后续新增报价；原 A01 决定保留或调整策略，再由原 A04 在独立授权上限内执行更紧的私有报价限制。\n不将选行计作正式融资承诺、信用风险或已放款，不修改既有债务、条款和现金；策略调查等未解决结果停止接线，不静默放宽报价。\n'
    if arrangement_principal_limits is not None:
        readme+='\n--arrangement-principal-limits <JSON> 显式声明各银行独立初始 A05 形成权限本金上限，例如 {"finance-bank-a":"0"}；原 A05 自行比较真实接受的报价，不改 A04 条款或实际选行，不代表运行中撤回权限。\n'
    if with_unconfirmed_arrangement_feedback:
        readme+='\n--with-unconfirmed-arrangement-feedback 将上述原 A01 的计数策略明确改为同借款人严格较早的本行原 A05 未确认复核次数（decline/requote）；确认不计未确认，缺结果不算拒绝。使用独立 prior_arrangement_reviews 私有证据，不通过原确认安排读取器。原 A01 自行选择策略、原 A04 收紧新报价上限；旧中选项目、条款、未决事项及现金不变，不将新借款处理当作旧安排已解决。\n'
    if intake_decline_banks:
        readme += '\n明确合成的受理拒绝场景：' + ', '.join(intake_decline_banks) + ' 的初始产品仅允许 refinancing，当前实际申请仍为 project_financing。原 BANK-A02 自行核对后 decline，经原生 reject_financing 执行；不运行 A03/A04，不伪造报价。严格较早、本银行、同借款人的实际 A02 拒绝事件及原结果身份进入后续原动作实际读取的私有观察 Evidence；历史不改变产品许可、风险、债务或现金，资料不足和转介不转为拒绝。\n'
    if credit_condition_outcomes is not None:
        readme += '\n--credit-condition-outcomes <JSON> 在最初封装前声明每家银行模板条件的独立核验结果（satisfied/unsatisfied）。机构与核验人、授权、证据和原引用保持对应；这不是运行中补证或真实外部核验。原 A03/A04 自行形成授信意见及报价，业主按原核验结论排除未满足条件的报价并比较其他合法报价。没有核验的条件仍保持缺资料，不伪造满足；报价、选行及 A05 私有确认都不代表条件已补齐、资金安排正式生效或到账。\n'
    if with_arrangement:
        if arrangement_capacity_limits is not None:
            readme += '\n--arrangement-capacity-limits <JSON> supplies independent initial A05 commitment capacity views in HKD. Original A04 capacities and original portfolio/commitments remain unchanged. This is a synthetic source assumption, not a native capacity reduction, reservation, loan or cash execution.\n'
        readme += '\n已显式启用 --with-arrangement：本行实际 project_financing_selected 投递后，原 BANK-A05 核对原报价、业主真实 OWN-A05 接受和原生提案/最终确认，只形成私有协议条件确认。未中选银行不执行 A05。后续融资读取本行严格较早的原 A05；缺失/待补/重报价要求明确诊断，不盲目重跑。\n独立形成权限、初始完整组合及旧承诺来源仍是明确合成输入；保留原 A04 容量和旧负荷，不把中选或私有确认计为新增承诺/资源占用。业主账户、现金、债务和比较偏好不向银行披露。原报价的计划资金释放保留为预测，不冒充实际到账。没有生成详细报价登记、融资安排登记、签署、提款、支付或正式容量预留；其他 A05 分支和后续 A06/A07/C3/C4 仍待接线。\n'
    if write_launch:
        readme+='\n--organization-actor-ids <JSON> 在生成初始来源前声明组织到执行 actor 的映射，银行审查、报价、策略、业主选行及中选确认共用原授权登记器。宏观 agent、借款人、贷款人和任务组织保留组织 ID；不迁移旧输入或已保存结果。\n'
        _write_launch_files(directory,assembly_hook='integration.bank_financing_native:configure_assembly',allow_native_project_generation=True,
            readme_override=readme)
    return {'status':'synthetic_bank_micro_bundle_unverified','directory':str(directory),'plans':len(plans)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True); parser.add_argument('--run-id',required=True)
    parser.add_argument('--with-owner',action='store_true')
    parser.add_argument('--feedback-followup',action='store_true')
    parser.add_argument('--with-bank-strategy',action='store_true')
    parser.add_argument('--with-monthly-strategy',action='store_true')
    parser.add_argument('--monthly-max-prior-reviews',type=int,default=1)
    parser.add_argument('--allow-monthly-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-bank-monthly-on-error',action='store_true')
    parser.add_argument('--initial-owner-funding',type=Path,
        help='JSON object or array of explicit independent initial Owner cash disclosures')
    parser.add_argument('--with-arrangement', action='store_true')
    parser.add_argument('--credit-condition-outcomes', type=Path)
    parser.add_argument('--allow-saved-recovery', action='store_true')
    parser.add_argument('--query-saved-financing-on-error', action='store_true')
    parser.add_argument('--continue-unstarted-actions-on-error', action='store_true')
    parser.add_argument('--arrangement-principal-limits', type=Path)
    parser.add_argument('--arrangement-capacity-limits', type=Path)
    parser.add_argument('--with-unconfirmed-arrangement-feedback', action='store_true')
    parser.add_argument('--organization-actor-ids', type=Path)
    parser.add_argument('--decline-intake-bank', action='append', default=[],
        choices=['finance-bank-a', 'finance-bank-b'])
    args=parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output,run_id=args.run_id,with_owner=args.with_owner,
        feedback_followup=args.feedback_followup,with_bank_strategy=args.with_bank_strategy,
        with_monthly_strategy=args.with_monthly_strategy,monthly_max_prior_reviews=args.monthly_max_prior_reviews,
        allow_monthly_saved_recovery=args.allow_monthly_saved_recovery,
        query_saved_bank_monthly_on_error=args.query_saved_bank_monthly_on_error,
        owner_funding=None if args.initial_owner_funding is None else json.loads(args.initial_owner_funding.read_bytes()),
        with_arrangement=args.with_arrangement, intake_decline_banks=args.decline_intake_bank,
        allow_saved_recovery=args.allow_saved_recovery,query_saved_financing_on_error=args.query_saved_financing_on_error,
        continue_unstarted_actions_on_error=args.continue_unstarted_actions_on_error,
        arrangement_principal_limits=json.loads(args.arrangement_principal_limits.read_text(encoding='utf-8-sig'))
            if args.arrangement_principal_limits is not None else None,
        arrangement_capacity_limits=json.loads(args.arrangement_capacity_limits.read_text(encoding='utf-8-sig'))
            if args.arrangement_capacity_limits is not None else None,
        with_unconfirmed_arrangement_feedback=args.with_unconfirmed_arrangement_feedback,
        organization_actor_ids=json.loads(args.organization_actor_ids.read_text(encoding='utf-8-sig'))
            if args.organization_actor_ids is not None else None,
        credit_condition_outcomes=json.loads(args.credit_condition_outcomes.read_text(encoding='utf-8-sig'))
            if args.credit_condition_outcomes is not None else None)))


if __name__ == '__main__': main()
