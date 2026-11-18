"""Declare isolated private portfolios and finite rules; leave actual selection/adoption unbound."""
from copy import deepcopy
import hashlib
from pathlib import Path
from integration.professional_monthly_development import build_bundle as monthly_foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.owner_monthly_strategy import MonthlyOwnerStrategyPlan,OwnerMonthlyStrategyApplication
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.verify_tender_closed_loop import ROOT,read
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_operating_objects import owner_operating_schemas
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,financing_condition_index):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'monthly-foundation';monthly_foundation(foundation,run_id=run_id,ticks=2)
    authority=read(foundation/'assembly-host.json')['settings']['authority']
    organizations={o['organization_id']:o for o in authority['organization_snapshot']['organizations']}
    owner=organizations['professional-owner'];org=owner['organization_id'];actor=owner['actor_id']
    seed=read(foundation/'professional-monthly-input.json')['plans'][0]
    clock=seed['context']['business_time']['clock_ref'];point=lambda tick:{'clock_ref':deepcopy(clock),'offset':tick}
    window={'start':point(0),'end':point(40),'bounds':'closed_open'}
    basis=ref('Evidence','owner-strategy-initial-private-declaration');scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
    initial_ref=ref('OwnerPreferenceProfile','owner-initial-private-preferences')
    initial_scores={'expected_return':'0.5','risk':'0.5','lifecycle_cost':'0.1','delivery_delay':'0.1'}
    normal_scores={**initial_scores,'expected_return':'0.8','risk':'0.2'}
    watch_scores={**initial_scores,'expected_return':'0.2','risk':'0.8'}
    declaration={'source':'explicit-synthetic-complete-initial-private-portfolio','old_fee_due':'5','old_fee_paid':'0','currency':'HKD',
        'initial_preference':initial_scores,'normal':normal_scores,'watch':watch_scores,'financing_watch_threshold':'0.95',
        'minimum_weight_change':'0.1','maximum_updates':1,'whole_old_obligation_is_retained':True,
        'private_comparison_dossier_sha256':hashlib.sha256((ROOT/'tests/fixtures/roles/owner_investment.v1.json').read_bytes()).hexdigest(),
        'limits':'Native financing index is not cash or return. Private core initial declarations are not observations of formal macro ledgers. No candidate, decision, execution or adoption is prefilled.'}
    shared=[{'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
        'locator':'complete-initial-private-portfolio-and-authorized-finite-investment-policy','content_hash':task_digest(declaration),'effective_window':window}},
        {'ref':scope['ref'],'value':{'ref':scope['ref'],'evidence_refs':[basis]}}]
    clock_rows=[deepcopy(r) for r in seed['objects'] if r['ref']==clock]
    for r in clock_rows:
        shared.append(r)
        shared.extend(deepcopy(v) for v in seed['objects'] if v['ref'] in r['value']['evidence_refs'])
    grants=[];plans=[];previous_visible=[]
    for tick in (1,2):
        tag=org+'-strategy-'+str(tick);fn=ref('FunctionAssignment',tag);grant_ref=ref('Authorization',tag)
        assignment={'role':'Owner','function_ref':fn,'configuration_version':'1','basis_refs':[basis]};owner['assignments'].append(deepcopy(assignment))
        native=ref('Evidence',tag+'-actual');policy_ref=ref('MonthlyInvestmentPolicy',tag);observation=ref('MonthlyInvestmentObservation',tag)
        portfolio_ref=ref('OwnerPortfolio',tag);profile_ref=ref('OwnerOperatingProfile',tag);market=ref('Observation',tag+'-actual-market')
        candidates=ref('CandidateSet',tag);normal=ref('OwnerPreferenceProfile',tag+'-normal');watch=ref('OwnerPreferenceProfile',tag+'-watch')
        project_ref=ref('Project','owner-strategy-background',str(tick));obligation=ref('Obligation','existing-other-project-fee',str(tick))
        common={'scope':scope,'available_at':point(tick),'effective_window':window,'evidence_refs':[basis]}
        authored={**common,'author_actor_id':actor,'author_organization_id':org,'author_function_ref':fn,
            'author_authority_ref':grant_ref,'author_action_id':'OWN-A15','authored_at':point(tick)}
        rows=deepcopy(shared)
        def put(reference,**fields):rows.append({'ref':reference,'value':{'ref':reference,**deepcopy(fields)}})
        put(native,source_kind='synthetic',basis_kind='observed',locator='actual-native-monthly-request-and-confirmed-own-private-strategy',content_hash=None,effective_window=window)
        rows.append({'ref':fn,'value':assignment})
        if tick==1:
            initial={**authored,'ref':initial_ref,'available_at':point(0),'authored_at':point(0),'organization_id':org,
                'prior_profile_ref':None,'purpose':'investment_return','scores':initial_scores,'basis_refs':[],
                'requires_learning':False,'learning_assessment_ref':None,'effect':'future_preferences_only'}
        rows.append({'ref':initial_ref,'value':deepcopy(initial)})
        put(project_ref,**common,organization_id=org,obligation_refs=[],status='preparing')
        put(obligation,evidence_refs=[basis],debtor_id=org,payee_id='declared-fee-creditor',
            source_ref=ref('FundingSource','actual-account',str(tick)),origin_scope={'kind':'assessment_case','ref':ref('OwnerCase','other-case',str(tick)),'coverage_refs':[]},
            debt_ref=None,component_refs=[ref('SettlementComponent','declared-fee-component')],actual_due=known({'value':'5','currency':'HKD','basis_ref':basis}),
            actual_paid=known({'value':'0','currency':'HKD','basis_ref':basis}),due_at=point(0),as_of=point(tick),status='effective',kind='works',
            actual_offset=known({'value':'0','currency':'HKD','basis_ref':basis}),payable=known(True),verification_evidence_refs=[basis])
        put(portfolio_ref,**common,organization_id=org,project_refs=[project_ref],obligation_refs=[obligation],observation_refs=[market],
            resource_refs=[],task_refs=[],required_task_refs=[],current_preference_ref=initial_ref,execution_refs=[],coverage='complete',as_of=point(tick),producer='core')
        put(market,**{**authored,'evidence_refs':[native]},recipient_organization_id=org,event_id=None,
            observed_at=point(tick),kind='market',outcome_code=None,dimension_codes=[],verified=known(True))
        for target,scores in [(normal,normal_scores),(watch,watch_scores)]:
            put(target,**authored,organization_id=org,prior_profile_ref=initial_ref,purpose='investment_return',scores=scores,
                basis_refs=[market],requires_learning=False,learning_assessment_ref=None,effect='future_preferences_only')
        put(profile_ref,**common,organization_id=org,portfolio_ref=portfolio_ref,actor_id=actor,function_ref=fn,authority_ref=grant_ref,
            choice='retain_policy',business_key=tag,basis_refs=[market],preference_profile_ref=None,budget_authority_ref=None,proposed_limit=None,
            allocations=[],allocation_task_refs=[],replaced_commitment_refs=[],allocation_revision_ref=None,
            note='Selection remains inside original OWN-A15; no actual revision or adoption is prefilled.',
            monthly_strategy_policy_ref=policy_ref,monthly_strategy_observation_ref=observation)
        put(policy_ref,organization_id=org,scope=scope,authority_ref=grant_ref,effective_window=window,
            financing_watch_threshold={'value':'0.95','unit':'index','basis_ref':basis},normal_preference_ref=normal,watch_preference_ref=watch,
            minimum_weight_change='0.1',maximum_updates=1,effect='future_private_investment_criteria_only',evidence_refs=[basis])
        put(observation,organization_id=org,scope=scope,as_of=point(tick),financing_index=None,prior_own_outcomes=None,evidence_refs=[native])
        put(candidates,operation_id=tag,scope=scope,as_of=point(tick),candidates=[{'ref':normal,'permitted_choices':['revise_preferences']},
            {'ref':watch,'permitted_choices':['revise_preferences']}],search_profile_ref=ref('Profile',tag))
        rows[-1]['value'].pop('ref')
        visible=[r['ref'] for r in rows]+[grant_ref]
        visible=list({task_digest(r):r for r in [*visible,*previous_visible]}.values())
        grant={'ref':grant_ref,'organization_id':org,'actor_id':actor,'function_ref':fn,'action_ids':['OWN-A15'],'scopes':[scope],
            'readable_refs':deepcopy(visible),'tool_ids':[],'validity':window,'basis_refs':[basis]}
        rows.append({'ref':grant_ref,'value':grant});grants.append(deepcopy(grant))
        # Canonical static projections also make later retained-source equality exact.
        for row in rows:
            if row['ref'] not in [observation,market,native]:
                row['value']=owner_operating_schemas().validate_projection(Reference.model_validate(row['ref']),row['value']).model_dump(mode='json')
        context={'run_id':run_id,'actor_id':actor,'function_ref':fn,'authorization_refs':[grant_ref],'operation_id':tag,
            'contract_ref':ref('ActionContract','OWN-A15'),'task_ref':ref('DecisionTask',tag),'scope':scope,'business_time':point(tick),
            'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidates,'execution_mode':'rule'}
        investment=investment_plan(tick=tick,run_id=run_id,org=org,actor=actor,point=point,clock=clock,basis=basis,
            shared=shared,organizations=organizations,grants=grants)
        inputs={'organization_ref':scope['ref'],'portfolio_ref':portfolio_ref,'obligation_refs':[obligation],
            'observation_refs':[market],'operating_profile_ref':profile_ref,'learning_method_ref':None}
        plans.append(MonthlyOwnerStrategyPlan.model_validate({'organization_id':org,'role':'Owner','project_id':'owner-strategy-background','tick':tick,
            'context':context,'action_input':inputs,'objects':rows,'native_evidence_ref':native,'observation_ref':observation,
            'initial_preference_ref':initial_ref,'investment':investment}).model_dump(mode='json'))
        previous_visible=deepcopy(visible)
    authority['organization_snapshot'].update(organizations=list(organizations.values()),authorizations=grants)
    sources=_write(directory,'owner-strategy-input.json',{'schema_version':OwnerMonthlyStrategyApplication.INPUT_SCHEMA,'run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(foundation/'native-host.json')
    for field,operation in [('native_proposals','decide_monthly_operation'),('native_decisions','monthly_enterprise_operation')]:
        native['settings'][field]=[r for r in native['settings'][field] if r['role']!='Owner']
        for role in ('Architect','Engineer','QS'):native['settings'][field].append({'role':role,'operation' if field=='native_proposals' else 'decision_type':operation})
    _write(directory,'native-host.json',native)
    macro=read(foundation/'macro-request.json');macro['macro_environment']['financing_condition_index']=financing_condition_index
    macro['initial_projects']=[{'project_id':'owner-strategy-background','name':'Initial undeveloped own project; private scenario declaration only',
        'project_type':'building','region':'Hong Kong','owner_id':org,'initial_budget':1000,'current_stage':'design'}]
    _write(directory,'macro-request.json',macro);_write(directory,'source-policy.json',declaration)
    _write_launch_files(directory,assembly_hook='integration.owner_monthly_strategy:configure_assembly',readme_override=__doc__)


def investment_plan(*,tick,run_id,org,actor,point,clock,basis,shared,organizations,grants):
    data=read(ROOT/'tests/fixtures/roles/owner_investment.v1.json')
    names={'owner':org,'owner-actor':actor,'cost-consultant':'professional-qs','cost-author':organizations['professional-qs']['actor_id'],
        'schedule-consultant':'professional-architect','schedule-author':organizations['professional-architect']['actor_id']}
    def remap(value):
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,dict):
            if set(value)=={'clock_ref','offset'}:
                n=value['offset'];return point(0 if n<10 else tick if n==10 else 40 if n==100 else tick+n-10)
            if set(value)=={'kind','id','version'}:
                if value['kind']=='ClockProfile':return deepcopy(clock)
                if value['kind']=='Evidence' and value['id']=='fixture-basis':return deepcopy(basis)
                return {**value,'id':names.get(value['id'],value['id']),'version':str(tick)}
            return {k:remap(v) for k,v in value.items()}
        return names.get(value,value) if isinstance(value,str) else value
    rows=remap(data['objects']);inputs=remap(data['input']);tag=org+'-strategy-comparison-'+str(tick)
    native=ref('Evidence',tag+'-actual-adoption');candidate=ref('CandidateSet',tag)
    scope=next(r['value']['permitted_scope'] for r in rows if r['ref']['kind']=='ProjectRegistrationProfile')
    rows.extend(deepcopy(r) for r in shared if r['ref']['kind']!='ClockProfile')
    rows.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
        'locator':'initial-private-policy-or-exact-confirmed-earlier-own-native-strategy-and-preference','content_hash':None,'effective_window':None}})
    rows.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),
        'candidates':[{'ref':r['ref'],'permitted_choices':['invest','authorize_preparation','revise','study_more']} for r in rows if r['ref']['kind']=='ProjectOption'],
        'search_profile_ref':ref('Profile',tag)}})
    for row in rows:
        kind=row['ref']['kind'];value=row['value']
        if kind=='OwnerObjective':
            for criterion in value['criteria']['value']:criterion['weight']=None
            value['evidence_refs'].append(native)
        if kind=='FunctionAssignment':
            organization={'Owner':org,'QS':'professional-qs','Architect':'professional-architect'}[value['role']]
            organizations[organization]['assignments'].append(deepcopy(value))
    visible=[r['ref'] for r in rows]
    for row in rows:
        if row['ref']['kind']=='Authorization':
            row['value']['readable_refs']=deepcopy(visible);grants.append(deepcopy(row['value']))
    fn=next(r['ref'] for r in rows if r['ref']['kind']=='FunctionAssignment' and r['value']['role']=='Owner')
    grant=next(r['ref'] for r in rows if r['ref']['kind']=='Authorization' and r['value']['organization_id']==org)
    context={'run_id':run_id,'actor_id':actor,'function_ref':fn,'authorization_refs':[grant],'operation_id':tag,
        'contract_ref':ref('ActionContract','OWN-A03'),'task_ref':ref('DecisionTask',tag),'scope':scope,'business_time':point(tick),
        'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidate,'execution_mode':'rule'}
    from src.actions.contracts.owner_investment_objects import owner_investment_schemas
    for row in rows:
        value=deepcopy(row['value'])
        if row['ref']==native:value['content_hash']='0'*64
        if row['ref']['kind']=='OwnerObjective':
            for criterion in value['criteria']['value']:criterion['weight']='1'
        owner_investment_schemas().validate_projection(Reference.model_validate(row['ref']),value)
    return {'context':context,'action_input':inputs,'objects':rows,'native_evidence_ref':native}
