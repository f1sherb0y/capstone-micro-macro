"""OWN-A15 private strategy -> actual native activity -> later original OWN-A03 comparison."""
from copy import deepcopy
import json
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.owner_operating_actions import OwnerOperatingActionAssembler
from integration.owner_operating_results import OwnerOperatingResultWorker
from integration.owner_investment_actions import OwnerInvestmentActionAssembler
from integration.owner_investment_results import OwnerInvestmentResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.owner_monthly_strategy import MonthlyInvestmentJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

INVESTMENT_PREFIX='owner_monthly_strategy_comparison:'
BOUNDARY=('Actual bounded private future investment-preference revision and original adjust_investment_strategy activity. '
    'An independently declared initial whole private portfolio retains its old unpaid obligation; it is not inferred from normalized native financial capacity. '
    'The financing index is an environment signal, not cash, return or a verified investment outcome. '
    'Finite authorized preference alternatives are selected inside OWN-A15; no learned score or improved return is asserted. '
    'Only the exact confirmed own native execution permits later adoption. The next original OWN-A03 actually compares an independently declared private planning dossier '
    'with the accepted criteria; its authorization proposal does not execute an investment, create a project, spend cash or reserve resources. '
    'Actual native candidate generation and monthly pipeline screening remain separate unresolved contacts.')


class PrivateInvestmentPlan(StrictRecord):
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')


class MonthlyOwnerStrategyPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Owner']
    project_id:TextId
    tick:int=Field(ge=1,le=2)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyInvestmentObservation')
    initial_preference_ref:ref_type('OwnerPreferenceProfile')
    investment:PrivateInvestmentPlan


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice'] not in {'revise_preferences','retain_policy'}:
        raise TaskConflict('Monthly strategy requires the original completed OWN-A15 choice')
    result=MonthlyInvestmentJudgment.model_validate_json(saved['result']['payload']['note'])
    if result.original_choice!=saved['result']['payload']['choice']:raise TaskConflict('Strategy interpretation changes original choice')
    if result.participate and saved['result']['payload']['preference_profile_ref']!=result.effective_preference_ref.model_dump(mode='json'):
        raise TaskConflict('Original strategy result differs from its selected preference reference')
    return result


def merge_retained(objects,history):
    rows={task_digest(r['ref']):r for r in objects}
    for h in history:
        if h['source_reading_sha256']!=task_digest(h['source_reading']):
            raise TaskConflict('Retained original strategy source reading changed')
        for source in h['source_reading']:
            row={'ref':deepcopy(source['ref']),'value':deepcopy(source['projection'])};key=task_digest(row['ref'])
            if key in rows and rows[key]!=row:raise TaskConflict('Current strategy rewrites an immutable retained original source')
            rows[key]=row
    return list(rows.values())


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);history=observed['prior_own_monthly_outcomes']
    evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if observation['financing_index'] is not None or observation['prior_own_outcomes'] is not None:
        raise TaskConflict('Monthly financing observation/history must be initially unbound')
    observation.update(financing_index={'value':str(observed['macro_environment']['financing_condition_index']),'unit':'index',
        'basis_ref':plan.native_evidence_ref.model_dump(mode='json')},prior_own_outcomes=deepcopy(history))
    portfolio,=[r['value'] for r in objects if r['ref']==plan.action_input['portfolio_ref']]
    if portfolio['current_preference_ref']!=plan.initial_preference_ref.model_dump(mode='json'):
        raise TaskConflict('An accepted private preference must not be prefilled')
    market,=[r['value'] for r in objects if r['ref'] in plan.action_input['observation_refs']]
    if market['event_id'] is not None:raise TaskConflict('Actual current market observation must not be prefilled')
    market['event_id']='actual-native-request:'+observed['native_request_sha256']
    active=[h for h in history if h['participated']]
    if active:
        latest=active[-1];accepted=latest['accepted_preference']
        if (latest['accepted_preference_sha256']!=task_digest(accepted)
                or accepted['ref']!=latest['strategy']['effective_preference_ref']
                or accepted['scores']!=latest['strategy']['effective_scores']):
            raise TaskConflict('Adopted preference differs from the confirmed original strategy')
        portfolio['current_preference_ref']=deepcopy(accepted['ref'])
        for r in objects:
            if r['ref']['kind']=='OwnerPreferenceProfile' and r['ref']!=plan.initial_preference_ref.model_dump(mode='json'):
                if r['value']['prior_profile_ref']!=plan.initial_preference_ref.model_dump(mode='json'):
                    raise TaskConflict('Current candidate prior must be unbound from an unexecuted strategy')
                r['value']['prior_profile_ref']=deepcopy(accepted['ref'])
    return merge_retained(objects,history)


def bind_investment_sources(plan,observed):
    objects=deepcopy(plan.investment.objects)
    evidence_binding(objects,plan.investment.native_evidence_ref.model_dump(mode='json'),observed)
    objective,=[r['value'] for r in objects if r['ref']==plan.investment.action_input['objective_ref']]
    for criterion in objective['criteria']['value']:
        if criterion['weight'] is not None:raise TaskConflict('Investment criteria must come from initial policy or actually adopted preferences')
        criterion['weight']=observed['applied_scores'][criterion['code']]
    return objects


class OwnerMonthlyStrategyApplication(ProfessionalMonthlyApplication):
    VERSION='owner-monthly-investment-strategy.v1'
    PREFIX='owner_monthly_strategy_request:'
    COMPONENTS={'Owner':(OwnerOperatingActionAssembler,OwnerOperatingResultWorker)}
    PLAN_TYPE=MonthlyOwnerStrategyPlan
    INPUT_SCHEMA='owner-monthly-strategy-input.v1'
    OPERATIONS={'Owner':'adjust_investment_strategy'}
    COMPLETED_CHOICES={'revise_preferences','retain_policy'}
    SCOPE_KEY='native_owner_monthly_strategy_scope'
    LABEL='Original Owner future private investment-preference revision'

    def action_id(self,role):
        if role!='Owner':raise TaskConflict('Owner strategy cannot replace another role')
        return 'OWN-A15'

    def __init__(self,**kwargs):
        super().__init__(**kwargs);self._investment_bound={}
        self.investment_assembler=OwnerInvestmentActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
            macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.VERSION,model_version=self.assembly.client.versions['model'])
        self.investment_worker=OwnerInvestmentResultWorker(store=self.assembly.client.tasks,snapshots=self.snapshots,registry=self.registry,
            client_version=self.VERSION,model_version=self.assembly.client.versions['model'],validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)
        self._original_investment_components=(self.investment_assembler,self.investment_worker)
        for p in self.plans:
            q=p.investment.context
            if (q.run_id!=p.context.run_id or q.actor_id!=p.context.actor_id or q.business_time!=p.context.business_time
                    or q.contract_ref.id!='OWN-A03' or q.scope.kind!='assessment_case'):
                raise TaskConflict('Private comparison changes original own run, clock, actor or action')

    def check(self):
        super().check()
        if hasattr(self,'_original_investment_components') and (
                self._original_investment_components!=(self.investment_assembler,self.investment_worker)
                or self.investment_assembler.provider is not self or self.investment_worker.store is not self.assembly.client.tasks
                or self.investment_worker.snapshots is not self.snapshots or self.investment_worker.registry is not self.registry):
            raise TaskConflict('Original private investment component binding changed')

    def participates(self,saved):return result_judgment(saved).participate
    def result_note(self,saved):return result_judgment(saved).model_dump_json()

    def history(self,org,tick):
        rows=super().history(org,tick)
        for h in rows:
            identity=TaskIdentity(**h['micro_identity']);saved=checked_result(self.workers['Owner'],identity);j=result_judgment(saved)
            event,=[e.model_dump(mode='json') for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memory=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if len(memory)!=1 or memory[0]['label']!=event['data']['label'] or memory[0]['capability_update']!=event['data'].get('capability_update'):
                raise TaskConflict('Private strategy lacks exact actual own native activity/memory')
            preference,=[r['projection'] for r in saved['source_reading'] if r['ref']==j.effective_preference_ref.model_dump(mode='json')]
            if preference['scores']!=j.effective_scores:raise TaskConflict('Accepted strategy changed its actual selected original profile')
            h.update(strategy=j.model_dump(mode='json'),strategy_sha256=task_digest(j.model_dump(mode='json')),
                accepted_preference=deepcopy(preference),accepted_preference_sha256=task_digest(preference),
                source_reading=deepcopy(saved['source_reading']),source_reading_sha256=saved['source_reading_sha256'],original_native_memory=deepcopy(memory[0]))
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in rows}:
            raise TaskConflict('Earlier strategy has no confirmed native execution; do not adopt, fallback or replay')
        return sorted(rows,key=lambda h:(h['tick'],h['event_id']))

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');project=self.assembly.engine.projects.get(plan.project_id)
        if project is None or project.owner_id!=plan.organization_id:raise TaskConflict('Strategy dossier lacks its current own initial project')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick),
            'actual_own_project':{'project_id':project.project_id,'owner_id':project.owner_id}}
        return bind_sources(plan,observed),observed

    def investment_records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(INVESTMENT_PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):raise TaskConflict('Private comparison journal changed')
        return rows

    def investment_sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick)
        active=[h for h in history if h['participated']]
        initial,=[r['value'] for r in plan.objects if r['ref']==plan.initial_preference_ref.model_dump(mode='json')]
        preference=active[-1]['accepted_preference'] if active else initial
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'prior_own_monthly_outcomes':history,'applied_preference':deepcopy(preference),'applied_scores':deepcopy(preference['scores']),
            'applied_preference_sha256':task_digest(preference),'boundary':BOUNDARY}
        return bind_investment_sources(plan,observed),observed

    def propose(self,request):
        with self.read_guard():
            scope=self.scope(request,purpose='propose');plan,=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
            key=INVESTMENT_PREFIX+task_digest([self.assembly.client.run_id,scope,request.request_id])
            if any(r['key']==key for r in self.investment_records()):raise TaskConflict('Private comparison already claimed; preserve journal without replay')
            objects,observed=self.investment_sources(plan,request)
            record=self._save({'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json'),
                'context':plan.investment.context.model_dump(mode='json'),'action_input':plan.investment.action_input,
                'observed':observed,'source_sha256':task_digest(objects)})
            self._investment_bound[task_digest(record['context'])]=(plan,request.model_copy(deep=True))
            prepared=self.investment_assembler.build(plan.investment.context,**deepcopy(plan.investment.action_input))
            identity=self.investment_worker.register(prepared,request_id=key+':OWN-A03');record['identity']=identity.as_dict();self._save(record)
            self.investment_worker.execute(identity,prepared);saved=checked_result(self.investment_worker,identity)
            if saved['result']['payload']['choice'] not in {'invest','authorize_preparation','reject'}:
                raise TaskConflict('Private planning comparison unresolved; no native investment is inferred')
            record.update(state='formed',result_sha256=saved['result_sha256']);self._save(record)
            return super().propose(request)

    def project(self,*,context,organization_id,grants):
        if context.contract_ref.id!='OWN-A03':return super().project(context=context,organization_id=organization_id,grants=grants)
        plan,request=self._investment_bound[task_digest(context.model_dump(mode='json'))]
        if context!=plan.investment.context or organization_id!=plan.organization_id:raise TaskConflict('Private comparison changes own invocation')
        objects,_=self.investment_sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'private-strategy-comparison:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        if row['identity']['action_id']!='OWN-A03':return super().validate_invocation(row,prepared)
        plan,request=self._investment_bound[prepared.context_sha256];self.scope(request,purpose='propose')
        if prepared.context!=plan.investment.context or row['identity']['organization_id']!=plan.organization_id:
            raise TaskConflict('Private comparison changes original source request')
        prepared.reading.recheck();return True

    def evidence(self):return {**super().evidence(),'investment_requests':self.investment_records(),'boundary':BOUNDARY}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Owner private strategy requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerMonthlyStrategyApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
