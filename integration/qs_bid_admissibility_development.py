"""Declare synthetic initial buyer delegation independently of future native results."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref


def prepare_admissibility_sources(parent_plan, *, contractor_id, authorizations):
    """Retain the original round and add separately declared exclusion sources."""
    binding, = [b for b in parent_plan['bids'] if b['contractor_id']==contractor_id]
    by_ref = lambda rows,reference:next(r['value'] for r in rows if r['ref']==reference)
    bid = by_ref(parent_plan['objects'],binding['bid_ref'])
    eligibility = by_ref(parent_plan['objects'],bid['eligibility_ref'])
    eligibility['qualified'] = known(False)
    # This is independent professional score evidence, not an exclusion encoding.
    binding['evaluation_score']['value'] = '0.2'
    context = deepcopy(parent_plan['context'])
    context['operation_id'] += ':delegated-exclusion:'+contractor_id
    context['read_token'] = context['operation_id']+':read'
    context['task_ref'] = ref('DecisionTask',context['operation_id'])
    candidates = ref('CandidateSet',context['operation_id']+':candidates')
    context['candidate_set_ref'] = candidates
    objects = deepcopy(parent_plan['objects'])
    original_profile = by_ref(objects,parent_plan['action_input']['evaluation_profile_ref'])
    profile = deepcopy(original_profile)
    profile['ref'] = ref('EvaluationProfile',context['operation_id']+':profile')
    authority = ref('Authority',context['operation_id']+':buyer-delegation')
    evidence = ref('Evidence',context['operation_id']+':original-round')
    round_ = by_ref(objects,parent_plan['action_input']['round_ref'])
    buyer_grant, = [g for g in authorizations if g['organization_id']==round_['buyer_organization_id']]
    qs_grant, = [g for g in authorizations if g['organization_id']==parent_plan['organization_id']]
    if 'OWN-A09' not in buyer_grant['action_ids']:
        raise ValueError('Initial exclusion delegation requires the original buyer OWN-A09 function authority')
    rule, = [r['ref'] for r in objects if r['ref']['kind']=='EvaluationRule'
        and r['value']['predicate']=='qualification' and r['value']['consequence']=='recommend_exclusion']
    profile.update(exclusion_bid_ref=binding['bid_ref'],exclusion_rule_ref=rule,exclusion_authority_ref=authority)
    profile['evidence_refs'].append(evidence)
    common = {k:deepcopy(original_profile[k]) for k in ('scope','available_at','effective_window','evidence_refs')}
    objects.extend([
        {'ref':profile['ref'],'value':profile},
        {'ref':authority,'value':{'ref':authority,**common,'round_ref':round_['ref'],
            'document_ref':parent_plan['action_input']['procurement_document_ref'],
            'bid_ref':binding['bid_ref'],'rule_ref':rule,'delegate_actor_id':context['actor_id'],
            'delegate_organization_id':parent_plan['organization_id'],
            'delegate_function_ref':context['function_ref'],'buyer_authority_ref':buyer_grant['ref'],
            'buyer_function_ref':buyer_grant['function_ref'],'granted_at':context['business_time'],
            'permission':known(True)}},
        {'ref':evidence,'value':{'ref':evidence,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-original-same-round-qs-result','content_hash':None,
            'effective_window':common['effective_window']}},
        {'ref':candidates,'value':{'operation_id':context['operation_id'],'scope':context['scope'],
            'as_of':context['business_time'],'candidates':[
                {'ref':round_['ref'],'permitted_choices':['exclude_authorized']},
                {'ref':binding['bid_ref'],'permitted_choices':['exclude_authorized']}],
            'search_profile_ref':ref('Profile',context['operation_id']+':exposure')}},
    ])
    context['visible_refs'] = [r['ref'] for r in objects]
    for reference in context['visible_refs']:
        if reference not in qs_grant['readable_refs']:qs_grant['readable_refs'].append(reference)
    grants = {g['organization_id']:g for g in authorizations}
    for row in [*parent_plan['objects'],*objects]:
        if row['ref']['kind']=='Authorization':row['value']=deepcopy(grants[row['value']['organization_id']])
    action_input = deepcopy(parent_plan['action_input'])
    action_input['evaluation_profile_ref'] = profile['ref']
    return {'organization_id':parent_plan['organization_id'],'project_id':parent_plan['project_id'],
        'tick':parent_plan['tick'],'contractor_id':contractor_id,'context':context,
        'action_input':action_input,'objects':objects,'original_round_evidence_ref':evidence}
