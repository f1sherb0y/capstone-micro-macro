"""Explicit synthetic source templates bound only when an original opportunity arrives."""
from copy import deepcopy
from decimal import Decimal

from integration.contractor_tender_development import ref,known
from src.actions.contracts.common import ActionContext
from src.organization.models import Authorization
from src.coordination.tasks import TaskConflict,task_digest


def prepare_opportunity_sources(app,policy,request,scope,history,*,progress_payments=None,prior_declines=None,final_accounts=None):
    """Produce a private assessment; preserve independent money and forecasts.

    Supplied grant templates explicitly authorize these scoped source views.
    Their concrete grant versions are persisted before action execution, never
    interpreted as public rights, formal project registration or expenditure.
    """
    template=app.document['template'];owner=policy.organization_id
    op=request.inputs['opportunity'];tick=scope['tick'];tag=owner+'-'+task_digest(scope)
    rr=lambda kind,name:ref(kind,tag+'-'+name)
    clock=ref('ClockProfile',app.assembly.client.run_id+'-monthly-clock')
    point=lambda n:{'clock_ref':clock,'offset':n}
    roles={'owner':owner,'cost-consultant':policy.cost_organization_id,'schedule-consultant':policy.schedule_organization_id}
    actors={'owner-actor':app.organizations.get(owner).actor_id,
        'cost-author':app.organizations.get(policy.cost_organization_id).actor_id,
        'schedule-author':app.organizations.get(policy.schedule_organization_id).actor_id}
    functions={'owner-investment':app.organizations.get(owner).assignments[0].function_ref.model_dump(mode='json'),
        'cost-function':app.organizations.get(policy.cost_organization_id).assignments[0].function_ref.model_dump(mode='json'),
        'schedule-function':app.organizations.get(policy.schedule_organization_id).assignments[0].function_ref.model_dump(mode='json')}
    def remap(value):
        if isinstance(value,list):return [remap(v) for v in value]
        if not isinstance(value,dict):
            return {**roles,**actors}.get(value,value) if isinstance(value,str) else value
        if set(value)=={'kind','id','version'}:
            if value['kind']=='Method':return deepcopy(value)
            if value['kind']=='ClockProfile':return clock
            if value['kind']=='FunctionAssignment':return deepcopy(functions[value['id']])
            if value['kind']=='OwnerCase' and value['id']=='other-case':
                # The prior debt keeps its original other-business origin;
                # evaluating another candidate never creates a new old debt.
                return ref('OwnerCase',owner+'-other-case')
            if value['kind'] in {'FundingSource','Obligation'}:
                return ref(value['kind'],owner+'-'+value['id'],str(tick))
            if value['kind'] in {'ResourcePool','OwnerPortfolio'}:
                # One physical pool/account identity; an exact assessment view
                # version also binds its case-specific permission references.
                return ref(value['kind'],owner+'-'+value['id'],task_digest(scope))
            if value['kind']=='ResourceCommitment':return ref(value['kind'],owner+'-'+value['id'])
            if value['kind']=='TimeWindow' and value['id'] in {'planned-period','long-period'}:
                return ref(value['kind'],owner+'-'+value['id'],str(tick))
            return rr(value['kind'],value['id'])
        if set(value)=={'clock_ref','offset'}:return point(max(0,value['offset']-template['business_time']['offset']+tick))
        result={k:remap(v) for k,v in value.items()}
        if {'value','basis_ref'}<=set(value) and (value.get('currency')=='HKD' or value.get('unit')=='HKD'):
            result['value']=format(Decimal(value['value'])*Decimal(policy.money_scale),'f')
        return result
    objects=remap(template['objects']);inputs=remap(template['input'])
    current_scope=next(r['value']['permitted_scope'] for r in objects if r['ref']['kind']=='ProjectRegistrationProfile')
    native=rr('Evidence','actual-native-opportunity')
    basis=rr('Evidence','fixture-basis')
    disclosure=ref('Evidence',owner+'-independent-investment-disclosure',str(tick))
    observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
        'opportunity':deepcopy(op),'prior_own_initiations':history,
        'max_prior_initiations':policy.max_prior_initiations,'source_policy_sha256':task_digest(policy.model_dump(mode='json'))}
    if policy.initial_investment_policy is not None:
        observed['initial_investment_policy']=policy.initial_investment_policy
    decline_pause=policy.max_prior_declines is not None and len(prior_declines or [])>=policy.max_prior_declines
    if prior_declines is not None:
        observed.update(prior_own_declines=deepcopy(prior_declines),max_prior_declines=policy.max_prior_declines,
            decline_preference_pauses_initiation=decline_pause)
    region_pause=policy.initiation_region_ids is not None and op['region'] not in policy.initiation_region_ids
    if policy.initiation_region_ids is not None:
        observed['initiation_region_ids']=list(policy.initiation_region_ids)
        observed['region_preference_pauses_initiation']=region_pause
    payment_pause=False
    if policy.max_prior_payment_requests is not None:
        if (progress_payments is None or progress_payments['organization_id']!=owner
                or progress_payments['run_id']!=app.assembly.client.run_id
                or progress_payments['simulation_id']!=app.assembly.engine.simulation_id
                or progress_payments['as_of_tick']!=tick or progress_payments['role']!='Owner'
                or progress_payments['record_sha256']!=task_digest({k:v for k,v in progress_payments.items() if k!='record_sha256'})):
            raise TaskConflict('Owner investment requires its actual own current native payment-request query')
        observed['own_progress_payments']=deepcopy(progress_payments)
        observed['max_prior_payment_requests']=policy.max_prior_payment_requests
        payment_pause=len(progress_payments['payment_requests'])>=policy.max_prior_payment_requests
        observed['payment_request_preference_pauses_initiation']=payment_pause
    final_account_pause=False
    if policy.max_prior_final_accounts is not None:
        if (final_accounts is None or final_accounts['organization_id']!=owner
                or final_accounts['run_id']!=app.assembly.client.run_id
                or final_accounts['simulation_id']!=app.assembly.engine.simulation_id
                or final_accounts['as_of_tick']!=tick or final_accounts['role']!='Owner'
                or final_accounts['record_sha256']!=task_digest({k:v for k,v in final_accounts.items() if k!='record_sha256'})):
            raise TaskConflict('Owner investment requires its exact own actual final-account query')
        final_account_pause=len(final_accounts['settlements'])>=policy.max_prior_final_accounts
        observed.update(own_final_accounts=deepcopy(final_accounts),
            max_prior_final_accounts=policy.max_prior_final_accounts,
            final_account_review_preference_pauses_initiation=final_account_pause)
    objects.extend([
        {'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
            'locator':'explicit-independent-investment-template:'+task_digest(template),
            'content_hash':task_digest({'template':task_digest(template),'policy':policy.model_dump(mode='json')}),
            'effective_window':None}},
        {'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-original-owner-opportunity-and-own-history','content_hash':task_digest(observed),'effective_window':None}},
        {'ref':disclosure,'value':{'ref':disclosure,'source_kind':'synthetic','basis_kind':'assumed',
            'locator':'explicit-shared-owner-investment-cash-debt-and-management-disclosure',
            'content_hash':task_digest({'template':task_digest(template),'policy':policy.model_dump(mode='json'),'as_of_tick':tick}),
            'effective_window':None}}])
    def shared_basis(value):
        if isinstance(value,list):return [shared_basis(v) for v in value]
        if not isinstance(value,dict):return value
        if value==basis:return deepcopy(disclosure)
        return {k:shared_basis(v) for k,v in value.items()}
    inputs['funding_lines']=shared_basis(inputs['funding_lines'])
    for org in (owner,policy.cost_organization_id,policy.schedule_organization_id):
        organization=app.organizations.get(org);basis_ref=organization.evidence_refs[0].model_dump(mode='json')
        objects.append({'ref':basis_ref,'value':{'ref':basis_ref,'source_kind':'synthetic','basis_kind':'assumed',
            'locator':'explicit-original-opportunity-organization-mandate','content_hash':task_digest(organization.model_dump(mode='json')),
            'effective_window':None}})
    for row in objects:
        kind=row['ref']['kind'];value=row['value']
        if kind=='FunctionAssignment':
            org={'Owner':owner,'QS':policy.cost_organization_id,'Architect':policy.schedule_organization_id}[value['role']]
            value['basis_refs']=[app.organizations.get(org).evidence_refs[0].model_dump(mode='json')]
        if kind in {'FundingSource','Obligation','ResourcePool','OwnerPortfolio'}:
            value=shared_basis(value);row['value']=value
        if kind=='Obligation':value['due_at']=point(2)
        if kind=='ResourcePool':
            for load in value['commitments']:
                load['window']={'start':point(0),'end':point(16),'bounds':'closed_open'}
        if kind=='OwnerCase':value.update(region_id=op['region'],use_code=policy.project_use_codes[op['project_type']])
        if kind=='OwnerBrief':value['brief']['region_ids']=[op['region']]
        if kind=='OwnerObjective':
            value['allowed_region_ids']=known(policy.allowed_regions)
            value['allowed_use_codes']=known(sorted(set(policy.project_use_codes.values())))
            if policy.with_observation:
                value['signal_rules']=known([{'signal_code':'native_global_market_demand_index','comparison':'at_least',
                    'threshold':{'value':policy.observation_minimum_demand,'unit':'index','basis_ref':basis}}])
        if kind=='ProjectRegistrationProfile':
            value['evidence_refs'].append(native)
            if policy.initial_investment_policy is not None:
                if value['policy']!=known('evaluate'):
                    raise TaskConflict('Explicit initial investment policy cannot overwrite an independently restricted template')
                value['policy']=known(policy.initial_investment_policy)
            if region_pause or payment_pause or decline_pause or final_account_pause or (policy.max_prior_initiations is not None and len(history)>=policy.max_prior_initiations):
                value['policy']=known('reject')
    candidates=rr('CandidateSet','investment');operation_id=tag+'-OWN-A03'
    if policy.with_observation:
        relation=ref('Evidence',operation_id+'-actual-observation')
        objects.append({'ref':relation,'value':{'ref':relation,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-original-OWN-A01-private-opportunity-following','content_hash':None,'effective_window':None}})
        case,=[r['value'] for r in objects if r['ref']==inputs['case_ref']]
        case['evidence_refs'].append(relation)
    if policy.with_proposal:
        relation=ref('Evidence',operation_id+'-actual-proposal')
        objects.append({'ref':relation,'value':{'ref':relation,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-original-OWN-A16-private-briefs','content_hash':None,'effective_window':None}})
        case,=[r['value'] for r in objects if r['ref']==inputs['case_ref']]
        case['evidence_refs']=[*case['evidence_refs'],relation]
    options=[r['ref'] for r in objects if r['ref']['kind']=='ProjectOption']
    from integration.owner_opportunity_study import declare_study_followup
    study_targets=declare_study_followup(objects,policy,point(tick))
    objects.append({'ref':candidates,'value':{'operation_id':operation_id,'scope':current_scope,'as_of':point(tick),
        'candidates':[{'ref':r,'permitted_choices':['invest','authorize_preparation','reject']
            +(['study_more'] if r in study_targets else [])} for r in options],
        'search_profile_ref':rr('Profile','comparison')}})
    visible=[r['ref'] for r in objects];grants=[]
    for row in objects:
        if row['ref']['kind']=='Authorization':
            row['value']['readable_refs']=deepcopy(visible);grant=Authorization.model_validate(row['value'])
            if (not policy.allow_scoped_template_authorizations
                    or grant.organization_id not in (owner,policy.cost_organization_id,policy.schedule_organization_id)
                    or any(s.kind!='assessment_case' or s.ref!=current_scope_ref(current_scope) for s in grant.scopes)):
                raise TaskConflict('Opportunity sources leave their explicitly authorized private assessment mandate')
            grants.append(grant)
    owner_grant,=[g for g in grants if g.organization_id==owner and g.action_ids==['OWN-A03']]
    context=ActionContext.model_validate({'run_id':app.assembly.client.run_id,'actor_id':actors['owner-actor'],
        'function_ref':owner_grant.function_ref,'authorization_refs':[owner_grant.ref],
        'operation_id':operation_id,'contract_ref':ref('ActionContract','OWN-A03'),'task_ref':rr('DecisionTask','investment'),
        'scope':current_scope,'business_time':point(tick),'read_token':tag+'-read','visible_refs':visible,
        'candidate_set_ref':candidates,'execution_mode':'rule'})
    return {'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,
        'grants':grants,'observed':observed}


def current_scope_ref(scope):
    from src.actions.contracts.common import Reference
    return Reference.model_validate(scope['ref'])
