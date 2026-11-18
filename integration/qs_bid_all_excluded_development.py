"""Declare two independently authorized exclusion rounds before native execution."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.qs_bid_admissibility_development import prepare_admissibility_sources


def prepare_all_excluded_rounds(parent, *, authorizations):
    """A deferred native selection can request a new review in the following tick.

    Each review has a distinct original context, candidate set and read token.
    Initial qualifications and buyer delegations are explicit synthetic facts;
    no future native decision or successful execution is embedded here.
    """
    by_ref = lambda rows, reference:next(r['value'] for r in rows if r['ref']==reference)
    for binding in parent['bids']:
        bid = by_ref(parent['objects'],binding['bid_ref'])
        by_ref(parent['objects'],bid['eligibility_ref'])['qualified'] = known(False)
        binding['evaluation_score']['value'] = '0.2'
    candidate = by_ref(parent['objects'],parent['context']['candidate_set_ref'])
    for item in candidate['candidates']:
        item['permitted_choices'] = ['no_valid_bid']
    later = deepcopy(parent)
    later['tick'] += 1
    context = later['context']
    context['business_time'] = {**context['business_time'],'offset':later['tick']}
    context['operation_id'] += ':new-review:'+str(later['tick'])
    context['read_token'] = context['operation_id']+':read'
    context['task_ref'] = ref('DecisionTask',context['operation_id'])
    old = context['candidate_set_ref']
    context['candidate_set_ref'] = ref('CandidateSet',context['operation_id']+':candidates')
    row, = [r for r in later['objects'] if r['ref']==old]
    row['ref'] = deepcopy(context['candidate_set_ref'])
    row['value'].update(operation_id=context['operation_id'],as_of=deepcopy(context['business_time']))
    context['visible_refs'] = [r['ref'] for r in later['objects']]
    parents, exclusions = [parent,later], []
    for plan in parents:
        for binding in plan['bids']:
            exclusion = prepare_admissibility_sources(plan,
                contractor_id=binding['contractor_id'],authorizations=authorizations)
            for row in exclusion['objects']:
                if row['ref']['kind']=='Authority':
                    row['value']['available_at'] = deepcopy(row['value']['granted_at'])
            exclusions.append(exclusion)
    grants = {g['ref']['id']:g for g in authorizations}
    grant, = [g for g in authorizations if g['organization_id']==parent['organization_id']]
    for plan in parents:
        for reference in plan['context']['visible_refs']:
            if reference not in grant['readable_refs']:grant['readable_refs'].append(deepcopy(reference))
    # Reconcile the independently declared union before the first file is sealed.
    # Runtime projection never alters these authorizations or an earlier result.
    for plan in [*parents,*exclusions]:
        for row in plan['objects']:
            if row['ref']['kind']=='Authorization':row['value']=deepcopy(grants[row['ref']['id']])
    return parents, exclusions
