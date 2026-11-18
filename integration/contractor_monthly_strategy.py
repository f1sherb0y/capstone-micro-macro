"""Original commercial worker, native monthly execution, then original A02 reuse."""
from copy import deepcopy
import json
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.commercial_actions import CommercialActionAssembler
from integration.commercial_worker import CommercialTaskWorker
from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.contractor_monthly_strategy import MonthlyBidStrategyJudgment
from src.coordination.continuations import ContinuationJournal,ConditionRegistry
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Bounded private future material-risk markup only. The actual dimensionless macro index is not a currency cost, learned win rate or past bid outcome. A12 retains a typed private rule judgment, not a published tender strategy for all work. Only after confirmed actual native adjust_bid_strategy execution can the next original A02 read that judgment through a new scoped private pricing profile. Its benchmark package, quantity/cost/design/programme/capacity sources are independently declared synthetic inputs. No actual invitation/publication/receipt, submitted bid, award, reservation, money or physical work is inferred; full commercial ledger coverage remains unknown.'
BID_PREFIX='contractor_monthly_strategy_bid:'


class PrivateStrategyBidPlan(StrictRecord):
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')


class MonthlyContractorStrategyPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Contractor']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyBidStrategyObservation')
    bid:PrivateStrategyBidPlan


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='record_lesson':raise TaskConflict('Original completed private A12 judgment required')
    return MonthlyBidStrategyJudgment.model_validate_json(saved['result']['payload']['note'])


def policy_of(plan):return next(r['value'] for r in plan.objects if r['ref']['kind']=='MonthlyBidStrategyPolicy')


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    row,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if row['material_index'] is not None or row['prior_own_outcomes'] is not None:raise TaskConflict('Monthly strategy observations must be originally unbound')
    row.update(material_index={'value':str(observed['macro_environment']['material_price_index']),'unit':'index','basis_ref':basis},prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    original,=[r['value'] for r in objects if r['ref']['kind']=='Observation']
    if original['source_sha256'] is not None or original['event_key'] is not None or original['verified'] is not None:
        raise TaskConflict('Original current macro observation must remain unbound initially')
    from src.actions.contracts.common import EvidenceRecord
    source,=[r['value'] for r in objects if r['ref']==basis]
    original.update(source_sha256=task_digest(EvidenceRecord.model_validate(source).model_dump(mode='json')),
        event_key='actual-native-request:'+observed['native_request_sha256'],verified={'state':'known','value':True})
    return objects


def bind_bid_sources(plan,observed):
    objects=deepcopy(plan.bid.objects);evidence_binding(objects,plan.bid.native_evidence_ref.model_dump(mode='json'),observed)
    row,=[r['value'] for r in objects if r['ref']==plan.bid.action_input['pricing_profile_ref']]
    if row['markup_fraction'] is not None:raise TaskConflict('Private markup must be bound from policy or confirmed prior execution')
    row['markup_fraction']=observed['applied_markup'];row['markup_basis_ref']=plan.bid.native_evidence_ref.model_dump(mode='json')
    return objects


class MonthlyCommercialWorker:
    """Signature bridge only: the existing commercial worker owns execution/results."""
    def __init__(self,*,assembler,store,snapshots,registry,client_version,model_version,validate_invocation,validate_wait):
        self.store,self.snapshots,self.registry=store,snapshots,registry
        self.original=CommercialTaskWorker(assembler=assembler,journal=ContinuationJournal(store,ConditionRegistry(())),snapshots=snapshots,
            client_version=client_version,model_version=model_version,validate_invocation=validate_invocation,validate_wait=validate_wait)
    def register(self,prepared,*,request_id):return self.original.register(prepared,request_id=request_id,purpose='action')
    def execute(self,identity,prepared):
        if self.snapshots.get(identity)['context']!=prepared.context.model_dump(mode='json'):raise TaskConflict('Commercial bridge changed original prepared invocation')
        return self.original.run(identity)
    def get_record(self,identity):return self.original._saved(identity)


class ContractorMonthlyStrategyApplication(ProfessionalMonthlyApplication):
    VERSION='contractor-monthly-bid-strategy.v1'
    PREFIX='contractor_monthly_strategy:'
    COMPONENTS={'Contractor':(CommercialActionAssembler,MonthlyCommercialWorker)}
    PLAN_TYPE=MonthlyContractorStrategyPlan
    INPUT_SCHEMA='contractor-monthly-strategy-input.v1'
    ACTION_NUMBER='A12'
    OPERATIONS={'Contractor':'adjust_bid_strategy'}
    COMPLETED_CHOICES={'record_lesson'}
    SCOPE_KEY='native_contractor_monthly_strategy_scope'
    LABEL='Original bounded private bid-strategy decision'

    def build_worker(self,role,worker):
        return worker(assembler=self.assemblers[role],store=self.assembly.client.tasks,snapshots=self.snapshots,registry=self.registry,
            client_version=self.VERSION,model_version=self.assembly.client.versions['model'],validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)

    def __init__(self,**kwargs):
        super().__init__(**kwargs);self._bid_bound={}
        self.bid_assembler=ContractorBidActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
            macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.VERSION,model_version=self.assembly.client.versions['model'])
        self.bid_worker=ContractorBidResultWorker(store=self.assembly.client.tasks,snapshots=self.snapshots,registry=self.registry,
            client_version=self.VERSION,model_version=self.assembly.client.versions['model'],validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)
        self._original_components=(self.assemblers['Contractor'],self.workers['Contractor'],self.workers['Contractor'].original,self.bid_assembler,self.bid_worker)
        for p in self.plans:
            q=p.bid.context
            if q.run_id!=p.context.run_id or q.actor_id!=p.context.actor_id or q.business_time!=p.context.business_time or q.contract_ref.id!='CONTRACTOR-A02' or q.scope.kind!='project':raise TaskConflict('Private A02 changes own run/time/actor or project scope')

    def check(self):
        super().check()
        if hasattr(self,'_original_components'):
            a,w,ow,ba,bw=self._original_components
            if ((self.assemblers['Contractor'],self.workers['Contractor'],self.workers['Contractor'].original,self.bid_assembler,self.bid_worker)!=(a,w,ow,ba,bw)
                    or ow.assembler is not a or ow.store is not self.assembly.client.tasks or ow.snapshots is not self.snapshots
                    or bw.store is not self.assembly.client.tasks or bw.snapshots is not self.snapshots or ba.provider is not self):raise TaskConflict('Original commercial/bid component binding changed')

    def participates(self,saved):result_judgment(saved);return True
    def result_note(self,saved):
        j=result_judgment(saved);return j.interpretation+' Actual material index '+j.material_index.value+'; next private markup '+j.next_private_markup

    def history(self,org,tick):
        rows=super().history(org,tick)
        for h in rows:h['strategy_judgment']=result_judgment(checked_result(self.workers['Contractor'],TaskIdentity(**h['micro_identity']))).model_dump(mode='json')
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in rows}:raise TaskConflict('Earlier strategy lacks confirmed native execution')
        return sorted(rows,key=lambda h:(h['tick'],h['event_id']))

    def bid_records(self):
        with self.assembly.client.tasks._lock:rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(BID_PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):raise TaskConflict('Private bid source journal changed')
        return rows

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),'macro_environment':deepcopy(request.inputs['macro_environment']),
            'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick)}
        return bind_sources(plan,observed),observed

    def bid_sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick);policy=policy_of(plan)
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),'prior_own_monthly_outcomes':history,
            'applied_markup':history[-1]['strategy_judgment']['next_private_markup'] if history else policy['base_markup'],
            'independent_policy_sha256':task_digest(policy),'boundary':BOUNDARY}
        return bind_bid_sources(plan,observed),observed

    def propose(self,request):
        with self.read_guard():
            scope=self.scope(request,purpose='propose');plan,=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
            key=BID_PREFIX+task_digest([self.assembly.client.run_id,scope,request.request_id])
            if any(r['key']==key for r in self.bid_records()):raise TaskConflict('Private bid already claimed; no replay')
            if plan.bid.context.scope.ref.id not in self.assembly.engine.projects:raise TaskConflict('Private bid lacks its declared native project')
            objects,observed=self.bid_sources(plan,request)
            record=self._save({'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json'),
                'context':plan.bid.context.model_dump(mode='json'),'action_input':plan.bid.action_input,'observed':observed,'source_sha256':task_digest(objects)})
            self._bid_bound[task_digest(record['context'])]=(plan,request.model_copy(deep=True))
            prepared=self.bid_assembler.build(plan.bid.context,**deepcopy(plan.bid.action_input));identity=self.bid_worker.register(prepared,request_id=key+':CONTRACTOR-A02')
            record['identity']=identity.as_dict();self._save(record);self.bid_worker.execute(identity,prepared);saved=checked_result(self.bid_worker,identity)
            if saved['result']['payload']['choice']!='submit_bid':raise TaskConflict('No fallback price for unresolved or declined private bid')
            record.update(state='formed',result_sha256=saved['result_sha256'],original_private_bid=deepcopy(saved['result']['payload']['bid']))
            self._save(record);return super().propose(request)

    def project(self,*,context,organization_id,grants):
        if context.contract_ref.id!='CONTRACTOR-A02':return super().project(context=context,organization_id=organization_id,grants=grants)
        plan,request=self._bid_bound[task_digest(context.model_dump(mode='json'))]
        if context!=plan.bid.context or organization_id!=plan.organization_id:raise TaskConflict('Private A02 substitutes another firm or read point')
        objects,_=self.bid_sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'private-monthly-strategy-bid:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        if row['identity']['action_id']!='CONTRACTOR-A02':return super().validate_invocation(row,prepared)
        plan,request=self._bid_bound[prepared.context_sha256];self.scope(request,purpose='propose')
        if prepared.context!=plan.bid.context or row['identity']['organization_id']!=plan.organization_id:raise TaskConflict('Private bid changes its original source request')
        prepared.reading.recheck();return True

    def evidence(self):
        result=super().evidence();result.update(bid_requests=self.bid_records(),boundary=BOUNDARY);return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Monthly private strategy requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ContractorMonthlyStrategyApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
