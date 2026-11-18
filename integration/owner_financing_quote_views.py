"""Project communicated original A04 terms into Owner's declared finance view."""
from copy import deepcopy

from integration.bank_financing_private import checked_result, native_quote_summary
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.pricing import decimal_fraction, exact_decimal


def disclosure_refs(objects, action_input):
    """Explicit dependency list known before future quotation values exist."""
    by_ref = {task_digest(r['ref']):r['value'] for r in objects}
    app = by_ref[task_digest(action_input['application_ref'])]
    product = by_ref[task_digest(action_input['product_ref'])]
    authority = by_ref[task_digest(action_input['authority_ref'])]
    selected = [app['ref'],app['borrower_ref'],app['purpose_ref'],app['applicant_authority_ref'],app['applicant_function_ref'],
        product['ref'],authority['ref'],authority['function_ref'],*authority['basis_refs']]
    for price_ref in action_input['pricing_candidates']:
        price = by_ref[task_digest(price_ref)]
        selected.extend([price_ref,price['tenor_ref'],price['validity_ref'],price['repayment_rule_ref'],*price['fee_rule_refs'],
                         *price['condition_refs'],*product['required_condition_refs']])
    # Evidence and independent author bases, but never recursive readable_refs:
    # those describe the Bank's authority, not a disclosure of its private data.
    pending = list(selected)
    seen = {}
    while pending:
        ref = pending.pop()
        if task_digest(ref) in seen:
            continue
        seen[task_digest(ref)] = ref
        value = by_ref[task_digest(ref)]
        if ref['kind'] in {'Authorization','FunctionAssignment'}:
            pending.extend(value['basis_refs'])
            continue
        for evidence in walk_references(value):
            if evidence.kind == 'Evidence': pending.append(evidence.model_dump(mode='json'))
    return list(seen.values())


def _condition_permission(value, sources):
    """Preserve the original verified dependency conclusion, including uncertainty."""
    if value['verification'] is None:
        raise TaskConflict('Owner requires actual supplied condition verification; no fabricated satisfaction')
    conclusions = [row for source in sources if source['ref']['kind'] == 'CreditAssessment'
        for row in source['value']['review_payload']['conditions'] if row['requirement_ref'] == value['ref']]
    if len(conclusions) != 1:
        raise TaskConflict('Owner condition lacks its exact original credit dependency conclusion')
    outcome = conclusions[0]['outcome']
    if outcome in {'satisfied', 'unsatisfied'}:
        return {'state': 'known', 'value': outcome == 'satisfied'}
    if outcome == 'unknown':
        return {'state': 'unknown', 'reason_code': 'original_credit_condition_unresolved', 'missing_refs': [value['ref']]}
    raise TaskConflict('Owner condition has an unsupported original credit conclusion')


def quote_views(bank, *, plan, request, disclosure, decision):
    scope = decision['factors']['native_financing_scope']
    technical, = [r for r in bank._records() if r['state']=='formed' and r['scope']==scope
                  and r['native_request']['agent']['agent_id']==disclosure.bank_id]
    identity = TaskIdentity(**technical['steps']['BANK-A04']['identity'])
    snapshot = bank.snapshots.get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    grants = bank.organizations.grants(context, 'BANK-A04', 'Bank')
    if not grants or any(grant.organization_id != disclosure.bank_id for grant in grants):
        raise TaskConflict('Owner quote disclosure lost its original Bank quotation authority')
    record = checked_result(bank.workers['BANK-A04'],identity)
    readable = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
    if any(Reference.model_validate(row['ref']).key() not in readable for row in record['source_reading']):
        raise TaskConflict('Owner quote disclosure lost current permission for its original Bank sources')
    sources = [{'ref':r['ref'],'value':r['projection']} for r in record['source_reading']]
    lookup = {task_digest(r['ref']):r['value'] for r in sources}
    get = lambda ref: lookup[task_digest(ref)]
    if record['result']['payload']['choice'] not in {'offer','conditional_offer'}:
        raise TaskConflict('Owner cannot receive a declined or unresolved Bank quotation as an offer')
    terms = record['result']['payload']['terms']
    app = get(next(r['ref'] for r in sources if r['ref']['kind']=='FinanceApplication'))
    project = bank.assembly.engine.projects[plan.project_id]
    event, = [e for e in project.event_log if e['event_type']=='bank_financing_decision' and e['agent_id']==disclosure.bank_id]
    accepted,summary = native_quote_summary(record,sources,periods_per_year=next(p.periods_per_year for p in bank.plans
        if (p.organization_id,p.borrower_id,p.project_id,p.tick)==(disclosure.bank_id,plan.organization_id,plan.project_id,plan.tick)))
    if (not accepted or app['borrower_id']!=plan.organization_id or terms['borrower_id']!=plan.organization_id
            or event['data'].get('micro_task_key')!=identity.key or event['data'].get('micro_result_sha256')!=record['result_sha256']
            or event['data'].get('proposal_response_sha256')!=technical['proposal_response_sha256']
            or any(task_digest(decision['data'].get(k))!=task_digest(v) for k,v in summary.items())):
        raise TaskConflict('Owner offer changes its actual native Bank event, original A04 or disclosed summary')
    allowed = {task_digest(r) for r in disclosure.readable_refs}
    required = disclosure_refs(sources,snapshot['action_input'])
    if {task_digest(r) for r in required} != allowed:
        raise TaskConflict('Owner financing quote disclosure differs from its explicit dependency whitelist')
    origin = {'bank_id':disclosure.bank_id,'event_id':event['event_id'],'native_event_sha256':task_digest(event),
        'task_key':identity.key,'record_sha256':record['record_sha256'],'result_sha256':record['result_sha256'],
        'source_reading_sha256':record['source_reading_sha256'],'offer_ref':disclosure.offer_ref.model_dump(mode='json')}
    evidence_ref = disclosure.evidence_ref.model_dump(mode='json')
    rows = []
    price = get(terms['pricing_ref'])
    path = get(price['funding_path_ref'])
    account, = [r['value'] for r in plan.objects if r['ref']==path['destination_ref']]
    original_account=get(path['destination_ref'])
    if (account['organization_id']!=plan.organization_id or account['currency']!=original_account['currency']
            or account['region_id']!=original_account['region_id'] or account['as_of']!=original_account['as_of']
            or any(account[k]['state']!=original_account[k]['state']
                or account[k]['value']['value']!=original_account[k]['value']['value']
                or account[k]['value']['currency']!=original_account[k]['value']['currency']
                for k in ['actual_cash','restricted_cash'])):
        raise TaskConflict('Owner quote reception changes its actual disclosed borrower account')
    source_ref = account['source_ref']
    principal = decimal_fraction(terms['principal_limit']['value'])
    point = plan.context.business_time.model_dump(mode='json')
    def payments(values, name):
        result=[]
        for index,row in enumerate(values):
            factor = decimal_fraction(row.get('principal_factor','0'))
            fixed = row.get('fixed_amount',{}).get('value','0')
            value = principal*factor+decimal_fraction(fixed)
            if value:
                result.append({'local_key':name+str(index),'source_ref':source_ref,'time':row['time'],
                    'amount':{**terms['principal_limit'],'value':exact_decimal(value)}})
        return result
    for ref in required:
        value=deepcopy(get(ref))
        kind=ref['kind']
        if kind=='FinanceProductProfile': value.pop('quote_policy_ref',None)
        elif kind in {'PricingRule','FeeRule','RepaymentRule'}:
            schedule = payments(price['interest_payments']['value'],'interest') if kind=='PricingRule' else (
                payments(get(ref)['payments']['value'],'principal') if kind=='RepaymentRule' else
                payments([{'time':value['time'],'fixed_amount':value['fixed_amount']['value'],
                           'principal_factor':value['principal_factor']['value']}],'fee'))
            value={'ref':ref,'offer_ref':disclosure.offer_ref.model_dump(mode='json'),'borrower_id':plan.organization_id,
                'lender_id':disclosure.bank_id,'scope_ref':plan.context.scope.model_dump(mode='json'),
                'schedule':{'state':'known','value':schedule},'coverage':'complete','available_at':point,
                'effective_window':value['effective_window'],'evidence_refs':[evidence_ref]}
        elif kind=='Requirement':
            verification=value['verification']
            permitted = _condition_permission(value, sources)
            value={'ref':ref,'scope_ref':value['scope_ref'],'borrower_id':plan.organization_id,'lender_id':disclosure.bank_id,
                'offer_ref':disclosure.offer_ref.model_dump(mode='json'),'arrangement_ref':None,
                'permitted':permitted,'verifier_actor_id':verification['actor_id'],
                'verifier_function_ref':verification['function_ref'],'verifier_authority_ref':verification['authority_ref'],
                'verifier_action_id':verification['action_id'],'verified_at':verification['verified_at'],
                'effective_window':value['effective_window'],'evidence_refs':value['evidence_refs']}
        rows.append({'ref':ref,'value':value})
    offer=disclosure.offer_ref.model_dump(mode='json')
    rows.append({'ref':offer,'value':{'ref':offer,'lender_id':disclosure.bank_id,'application_ref':app['ref'],
        'scope_ref':app['scope_ref'],'author_actor_id':snapshot['context']['actor_id'],
        'author_function_ref':snapshot['context']['function_ref'],'authority_ref':snapshot['action_input']['authority_ref'],
        'originating_action_id':'BANK-A04','terms':deepcopy(terms),'priority':{'state':'known','value':disclosure.priority},
        'status':'offered','issued_at':point,'available_at':point,'effective_window':get(terms['validity_ref']),
        'proposed_releases':[{'local_key':'draw','source_ref':source_ref,'time':get(terms['tenor_ref'])['start'],
                              'amount':deepcopy(terms['principal_limit'])}],'evidence_refs':[evidence_ref]}})
    rows.append({'ref':evidence_ref,'value':{'ref':evidence_ref,'source_kind':'synthetic','basis_kind':'observed',
        'locator':'actual-communicated-bank-proposal:'+identity.key,'content_hash':task_digest(origin),'effective_window':None}})
    return rows,origin
