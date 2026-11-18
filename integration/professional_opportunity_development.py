"""Declare independent A01 policy and source views before any professional result exists."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.professional_opportunity_native import COMPONENTS, ProfessionalOpportunityPlan
from src.actions.contracts.common import Reference


def add_opportunity(plan, grant, *, interest_permitted=True, decline_after_no_interest=False):
    role = plan['role']
    current = plan['context']
    tag = current['operation_id']+'-opportunity'
    rr = lambda kind, name:ref(kind,tag+'-'+name)
    opportunity, strategy = rr('Opportunity','invitation'), rr('Capability' if role=='Engineer' else 'Strategy','policy')
    native, handoff = rr('Evidence','native'), rr('Evidence','interest')
    candidates = rr('CandidateSet','interest')
    get = lambda reference:next(row['value'] for row in plan['objects'] if row['ref']==reference)
    basis = get(plan['native_evidence_ref'])['effective_window']
    terms = get(plan['action_input']['terms_ref'])
    service = get(plan['action_input']['request_ref'])
    objects = [deepcopy(row) for row in plan['objects'] if (
        row['ref']['kind'] in {'ClockProfile','Project','WorkScope'}
        or row['ref']==current['function_ref'] or row['ref']==grant['ref']
        or row['ref']['kind']=='Evidence' and row['value']['content_hash'] is not None
        or role!='QS' and row['ref']==plan['action_input']['capacity_ref'])]

    def put(reference, **fields):
        objects.append({'ref':reference,'value':{'ref':reference,**fields}})

    put(native, source_kind='synthetic', basis_kind='observed', locator='actual-professional-invitation:'+tag,
        content_hash=None, effective_window=deepcopy(basis))
    common = {'scope':deepcopy(current['scope']), 'available_at':deepcopy(current['business_time']),
        'effective_window':deepcopy(basis), 'evidence_refs':[native]}
    policy = {**common, 'organization_id':plan['organization_id'], 'author_actor_id':current['actor_id'],
        'author_function_ref':current['function_ref'], 'author_authority_ref':grant['ref'], 'preparation_ref':None}
    invite = {**common,'permission':known(True),'status':'open','inviting_actor_id':service['client_id'],
        'interest_permission':known(interest_permitted)}
    if role=='QS':
        put(opportunity, **invite, recipient_ids=[current['actor_id']],strategy_refs=[strategy],trigger_ref=None)
        put(strategy, **policy, choice_order=['express_interest','ignore'],opportunity_order=[opportunity],
            source_order=[],ignore_reason='Independent policy does not authorize interest')
        inputs = {'scope':current['scope'],'opportunity_refs':[opportunity],'price_source_refs':[],
            'strategy_ref':strategy,'research_authority_ref':None}
    else:
        invite.update(recipient_organization_ids=[plan['organization_id']],recipient_actor_ids=[current['actor_id']],
            source_verified=known(True), region_id=terms['region_id'],service_code=terms['service_code'],
            object_type=terms['object_type'], clarification_recipient_ids=[service['client_id']],questions=[])
        policy.update(opportunity_ref=opportunity,capacity_ref=plan['action_input']['capacity_ref'])
        if role=='Architect':
            put(opportunity,**invite,strategy_refs=[strategy],watch_condition_ref=None)
            put(strategy,**policy,choice_order=['express_interest','ignore'],
                ignore_reason='Independent policy does not authorize interest')
            inputs = {'scope':current['scope'],'opportunity_ref':opportunity,'strategy_ref':strategy,
                'capacity_ref':plan['action_input']['capacity_ref'],'preparation_authority_ref':None}
        else:
            discipline = rr('Discipline','original-service')
            code, = terms['discipline_codes']['value']
            put(discipline,**common,code=code)
            put(opportunity,**invite,capability_refs=[strategy],discipline_ref=known(discipline),
                function_code=terms['function_code'],trigger_ref=None)
            put(strategy,**policy,discipline_codes=terms['discipline_codes'],function_codes=known([terms['function_code']['value']]),
                choice_order=['express_interest','decline'],decline_reason='Independent policy does not authorize interest')
            inputs = {'scope':current['scope'],'opportunity_ref':opportunity,'capability_ref':strategy,
                'capacity_ref':plan['action_input']['capacity_ref'],'preparation_authority_ref':None}
    objects.append({'ref':candidates,'value':{'operation_id':tag,'scope':current['scope'],
        'as_of':current['business_time'], 'candidates':[{'ref':opportunity,
            'permitted_choices':['express_interest', 'decline' if role=='Engineer' else 'ignore']}],
        'search_profile_ref':rr('Profile','explicit-current-invitation')}})
    context = {**deepcopy(current),'contract_ref':ref('ActionContract',role.upper()+'-A01'),
        'operation_id':tag,'task_ref':rr('DecisionTask','interest'),'read_token':tag+'-read',
        'candidate_set_ref':candidates,'visible_refs':[row['ref'] for row in objects]}
    plan['opportunity'] = {'context':context,'action_input':inputs,'objects':objects,'opportunity_ref':opportunity,
        'native_evidence_ref':native,'handoff_evidence_ref':handoff,
        'non_interest_policy':'decline_new_work' if decline_after_no_interest else 'require_resolution'}
    plan['objects'].append({'ref':handoff,'value':{'ref':handoff,'source_kind':'synthetic','basis_kind':'observed',
        'locator':'actual-original-professional-interest:'+tag,'content_hash':None,'effective_window':deepcopy(basis)}})
    # Initial service objects reuse a basis list. Give only the private request
    # this new dependency; disclosed capabilities keep their original evidence.
    service['evidence_refs'] = [*service['evidence_refs'],handoff]
    current['visible_refs'].append(handoff)
    grant['readable_refs'].extend([*[row['ref'] for row in objects],handoff])
    if role.upper()+'-A01' not in grant['action_ids']:
        grant['action_ids'].append(role.upper()+'-A01')
    ProfessionalOpportunityPlan.model_validate(plan['opportunity'])


def validate_opportunity(plan):
    source = plan['opportunity']
    schemas = COMPONENTS[plan['role']][0].SOURCE_SCHEMAS()
    for row in source['objects']:
        value = deepcopy(row['value'])
        if row['ref']==source['native_evidence_ref']:
            value['content_hash']='0'*64
        schemas.validate_projection(Reference.model_validate(row['ref']), value)
