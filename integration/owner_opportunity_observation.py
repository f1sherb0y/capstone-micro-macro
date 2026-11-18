"""Original A01 follows a current native opportunity before independent A03 review."""
from copy import deepcopy
from decimal import Decimal

from integration.contractor_tender_development import known,ref
from src.actions.contracts.common import ActionContext,Reference
from src.actions.contracts.owner_objects import OwnerObjectiveView
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest
from src.organization.models import Authorization


def observation_evidence_ref(source):
    return ref('Evidence',source['context'].operation_id+'-actual-observation')


def prepare_observation_sources(source,policy,request):
    """Reuse independent objective/management facts, observe only the native index.

    Native demand is a global index observed with the candidate, never a local
    survey, forecast or formal project/case receipt. Research permission and
    screening effort are explicitly declared private scenario policy.
    """
    if not policy.with_observation:raise TaskConflict('Owner observation needs its explicit original mandate')
    current=source['context'];org=policy.organization_id;now=current.business_time.model_dump(mode='json')
    rr=lambda kind,name:ref(kind,current.operation_id+'-observation-'+name)
    get=lambda reference:next(r['value'] for r in source['objects'] if r['ref']==reference)
    objective=get(source['action_input']['objective_ref'])
    objective=OwnerObjectiveView.model_validate({k:deepcopy(v) for k,v in objective.items()
        if k in OwnerObjectiveView.model_fields}).model_dump(mode='json')
    pools=[r['value'] for r in source['objects'] if r['ref']['kind']=='ResourcePool' and r['value']['organization_id']==org]
    if len(pools)!=1 or pools[0]['coverage']!='complete' or pools[0]['as_of']!=now:
        raise TaskConflict('Owner observation requires its exact independent complete current management pool')
    pool=pools[0];basis=objective['evidence_refs'][0];native=source['native_evidence_ref']
    index=Decimal(str(request.inputs['macro_environment']['market_demand_index']))
    if not index.is_finite():raise TaskConflict('Native market demand has no finite observed index')
    demand=rr('DemandObservation','native-index');observation=rr('Observation','native-index')
    opportunity=rr('Opportunity','current-candidate');capacity=rr('ManagementCapacity','screening')
    scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
    window=objective['effective_window'];op=request.inputs['opportunity']
    objects=[deepcopy(r) for r in source['objects'] if r['ref']['kind']=='Evidence'
             and r['ref']!=observation_evidence_ref(source)
             and r['ref']!=ref('Evidence',current.operation_id+'-actual-proposal')]
    objects.extend([
        {'ref':objective['ref'],'value':objective},
        {'ref':observation,'value':{'ref':observation,'evidence_refs':[native],'demand_ref':demand}},
        {'ref':demand,'value':{'ref':demand,'evidence_refs':[native],'source_ref':observation,
            'region_id':op['region'],'use_code':policy.project_use_codes[op['project_type']],
            'signal_code':'native_global_market_demand_index','measure':known({'value':str(index),'unit':'index','basis_ref':native}),
            'research_permitted':known(True),'observed_at':now,'learned_at':now,'effective_window':window}},
        {'ref':opportunity,'value':{'ref':opportunity,'evidence_refs':[native],'region_id':op['region'],
            'use_code':policy.project_use_codes[op['project_type']],'observation_refs':[demand],
            'effective_window':window,'learned_at':now,'status':known('active'),'research_permitted':known(True)}},
        {'ref':capacity,'value':{'ref':capacity,'evidence_refs':deepcopy(pool['evidence_refs']),
            'organization_id':org,'effective_window':deepcopy(pool['effective_window']),'total':deepcopy(pool['total']),
            'screening_requirement':known({'value':policy.observation_management_requirement,
                'unit':pool['total']['value']['unit'],'basis_ref':basis}),
            'commitments':[{'commitment_ref':r['ref'],'window':deepcopy(r['window']),'quantity':deepcopy(r['quantity'])}
                for r in pool['commitments']]}},
        {'ref':current.function_ref.model_dump(mode='json'),'value':deepcopy(get(current.function_ref.model_dump(mode='json')))},
        {'ref':scope['ref'],'value':{'ref':scope['ref'],'evidence_refs':deepcopy(
            get(current.function_ref.model_dump(mode='json'))['basis_refs'])}},
    ])
    grant=deepcopy(get(current.authorization_refs[0].model_dump(mode='json')))
    grant.update(ref=rr('Authorization','current-screening'),action_ids=['OWN-A01'],scopes=[scope],readable_refs=[])
    objects.append({'ref':grant['ref'],'value':grant})
    candidates=rr('CandidateSet','one-current-opportunity');operation=current.operation_id+'-observation'
    objects.append({'ref':candidates,'value':{'operation_id':operation,'scope':scope,'as_of':now,
        'candidates':[{'ref':opportunity,'permitted_choices':['follow','ignore']}],
        'search_profile_ref':rr('Profile','explicit-current-opportunity')}})
    visible=[r['ref'] for r in objects];grant['readable_refs']=deepcopy(visible)
    context=ActionContext.model_validate({**current.model_dump(mode='json'),'operation_id':operation,
        'contract_ref':ref('ActionContract','OWN-A01'),'task_ref':rr('DecisionTask','screening'),
        'scope':scope,'authorization_refs':[grant['ref']],'read_token':operation+'-read',
        'visible_refs':visible,'candidate_set_ref':candidates})
    return {'context':context,'action_input':{'scope_ref':scope,'objective_ref':objective['ref'],
        'observations':[demand],'opportunity_refs':[opportunity],'existing_case_refs':[],'capacity_ref':capacity},
        'objects':objects,'grants':[Authorization.model_validate(grant)],
        'observed':{'native_observation_sha256':source['observed']['native_request_sha256'],
            'native_context':deepcopy(source['observed']),
            'scope':deepcopy(source['observed']['scope']),'independent_management_pool_sha256':task_digest(pool)}}


def observation_origin(*,original,saved,snapshot,organizations):
    """Authenticate the exact original observation, retaining business negatives."""
    identity=TaskIdentity(**saved['identity']);context=original['context']
    grants=organizations.grants(context,'OWN-A01','Owner')
    permitted={r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
    actual=saved['result'];opportunity,=original['action_input']['opportunity_refs']
    if (identity.action_id!='OWN-A01' or identity.run_id!=context.run_id
            or not grants or any(g.organization_id!=identity.organization_id for g in grants)
            or identity.organization_id!=original['observed']['scope']['owner_id']
            or snapshot['identity']!=saved['identity'] or snapshot['context']!=context.model_dump(mode='json')
            or snapshot['action_input']!=original['action_input']
            or identity.context_sha256!=task_digest(snapshot['context']) or identity.input_sha256!=task_digest(snapshot['action_input'])
            or saved['result_sha256']!=task_digest(actual) or actual['kind']!='completed'
            or actual['payload']['choice'] not in {'follow','ignore'}
            or (actual['payload']['choice']=='follow'
                and actual['payload']['target']!={'kind':'opportunity','opportunity_ref':opportunity})
            or saved['source_reading_sha256']!=task_digest(saved['source_reading'])
            or any(Reference.model_validate(r['ref']).key() not in permitted for r in saved['source_reading'])):
        raise TaskConflict('Opportunity needs its exact original same-request follow or ignore; other results need review')
    sources={task_digest(r['ref']):r['projection'] for r in saved['source_reading']}
    if any(sources.get(task_digest(r['ref']))!=r['value'] for r in original['objects']):
        raise TaskConflict('Investment observation substitutes its actual original authorized sources')
    bound={'source':'original_private_owner_opportunity_observation','identity':identity.as_dict(),
        'record_sha256':saved['record_sha256'],'result_sha256':saved['result_sha256'],
        'source_reading_sha256':saved['source_reading_sha256'],'audit_sha256':task_digest(saved['audit']),
        'target_opportunity_ref':opportunity,'native_request_sha256':original['observed']['native_observation_sha256']}
    return actual['payload']['choice'],bound


def attach_observation(source,*,original,saved,snapshot,organizations):
    """Bind actual follow to A03; do not invoke the formal A01->A16 case handoff."""
    choice,bound=observation_origin(original=original,saved=saved,snapshot=snapshot,organizations=organizations)
    if choice!='follow' or bound['native_request_sha256']!=source['observed']['native_request_sha256']:
        raise TaskConflict('Investment requires its actual original same-request followed opportunity')
    result=deepcopy(source);evidence=observation_evidence_ref(source)
    case=next(r['value'] for r in result['objects'] if r['ref']==result['action_input']['case_ref'])
    if evidence not in case['evidence_refs']:raise TaskConflict('Investment case lacks its declared private observation dependency')
    slot,=[r['value'] for r in result['objects'] if r['ref']==evidence]
    if slot['content_hash'] is not None:raise TaskConflict('Investment observation relation must be bound only after actual completion')
    slot['content_hash']=task_digest(bound)
    native,=[r['value'] for r in result['objects'] if r['ref']==result['native_evidence_ref']]
    if native['content_hash']!=task_digest(result['observed']):raise TaskConflict('Investment native observation changed before private handoff')
    result['observed']['observation']=bound;native['content_hash']=task_digest(result['observed'])
    return result
