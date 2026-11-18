"""Declare missing eligibility and its actual responsible bidder before sealing."""
from copy import deepcopy

from src.coordination.tasks import task_digest


def prepare_bid_question(plan, *, contractor_id, authorizations):
    binding, = [b for b in plan['bids'] if b['contractor_id']==contractor_id]
    bid, = [r['value'] for r in plan['objects'] if r['ref']==binding['bid_ref']]
    assessment, = [r['value'] for r in plan['objects'] if r['ref']==bid['eligibility_ref']]
    profile, = [r['value'] for r in plan['objects'] if r['ref']==plan['action_input']['evaluation_profile_ref']]
    round_, = [r['value'] for r in plan['objects'] if r['ref']==plan['action_input']['round_ref']]
    gap = {'kind':'EvidenceTarget','id':plan['context']['operation_id']+'-bid-eligibility','version':'1'}
    response = {'kind':'ResponseRequirement','id':gap['id']+'-response','version':'1'}
    common = {key:deepcopy(profile[key]) for key in ('scope','available_at','effective_window','evidence_refs')}
    shared = {**common,'procurement_scope_ref':deepcopy(round_['procurement_scope_ref']),
        'round_ref':deepcopy(round_['ref']),'recipient_ids':[bid['bidder_id']]}
    plan['objects'].extend([
        {'ref':gap,'value':{**deepcopy(shared),'ref':gap,
            'document_ref':deepcopy(plan['action_input']['procurement_document_ref']),
            'bid_ref':deepcopy(binding['bid_ref']),'issue':'eligibility','line_key':None,
            'question':'Provide the original bid qualification evidence; the existing bid price remains unchanged.',
            'blocking_uses':['procurement'],'response_requirement_ref':response}},
        {'ref':response,'value':{**deepcopy(shared),'ref':response}},
    ])
    assessment['qualified'] = {'state':'unknown','reason_code':'original_bid_qualification_not_received','missing_refs':[]}
    profile['question_refs'] = [gap]
    profile['on_unknown'] = 'clarify'
    candidates, = [r['value'] for r in plan['objects'] if r['ref']==plan['context']['candidate_set_ref']]
    candidates['candidates'][0]['permitted_choices'] = ['clarify']
    original = {task_digest(r):r for r in plan['context']['visible_refs']}
    original.update({task_digest(r):r for r in (gap,response)})
    plan['context']['visible_refs'] = list(original.values())
    grant, = [g for g in authorizations if g['ref'] in plan['context']['authorization_refs']]
    reads = {task_digest(r):r for r in grant['readable_refs']}
    reads.update({task_digest(r):r for r in (gap,response)})
    grant['readable_refs'] = list(reads.values())
    for row in plan['objects']:
        if row['ref']==grant['ref']:
            row['value'] = deepcopy(grant)
    return plan
