"""Original A01 monitoring, native execution, and a later original A03 quote consumer."""
from copy import deepcopy
from decimal import Decimal
import json
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_screening_results import SupplierScreeningResultWorker
from integration.supplier_quote_actions import SupplierQuoteActionAssembler
from integration.supplier_quote_results import SupplierQuoteResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.supplier_monthly_prices import SupplierPriceMonitorJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Private quote-risk monitoring only. The native material index is dimensionless; it may select an independently authorized future markup, never create a monetary unit cost or market transaction price. Original A03 computes private quotes from separately declared synthetic product/cost/stock/capacity/logistics inputs. No native SupplyOffer publication, buyer receipt, accepted order, stock adjustment, reservation, payment or physical reliability improvement is inferred. Unknown A01 physical capacity stays unknown; original A03 validates its separately declared physical dossier.'
QUOTE_PREFIX='supplier_monthly_price_quote:'


class PrivatePriceQuotePlan(StrictRecord):
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')


class MonthlySupplierPricePlan(StrictRecord):
    organization_id:TextId
    role:Literal['Supplier']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('SupplierPriceMonitorObservation')
    quote:PrivatePriceQuotePlan


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='track_market':raise TaskConflict('Original completed A01 market tracking required')
    return SupplierPriceMonitorJudgment.model_validate_json(saved['result']['payload']['note'])


def policy_of(plan):
    return next(r['value'] for r in plan.objects if r['ref']['kind']=='SupplierPriceMonitorPolicy')


def bind_quote_sources(plan,observed):
    objects=deepcopy(plan.quote.objects);evidence_binding(objects,plan.quote.native_evidence_ref.model_dump(mode='json'),observed)
    profile,=[r['value'] for r in objects if r['ref']==plan.quote.action_input['pricing_profile_ref']]
    if profile['markup_rate'] is not None:raise TaskConflict('Private quote markup must be bound from declared policy and confirmed earlier monitoring')
    profile['markup_rate']={'state':'known','value':observed['applied_markup_rate']}
    return objects


def quote_summary(saved,*,tick):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='quote':raise TaskConflict('Original A03 did not form a quote; no fallback price')
    lines=saved['result']['payload']['offer']['lines'];currencies={line['price']['currency'] for line in lines}
    if len(currencies)!=1:raise TaskConflict('Cannot aggregate private quotes in different currencies')
    def source(reference):return next(r['projection'] for r in saved['source_reading'] if r['ref']==reference)
    products=[source(line['product']['product_ref']) for line in lines]
    physical=[{'product_ref':line['product']['product_ref'],'product_sha256':task_digest(product),
        'quantity':line['product']['quantity']['value'],'quantity_unit':line['product']['quantity']['unit'],
        'destination_ref':line['destination_ref'],
        'scope':line['product']['destination_scope_ref'],
        'included_service_refs':line['included_service_refs']}
        for line,product in zip(lines,products)]
    return {'identity':deepcopy(saved['identity']),'record_sha256':saved['record_sha256'],'result_sha256':saved['result_sha256'],
        'source_reading_sha256':saved['source_reading_sha256'],'tick':tick,'currency':next(iter(currencies)),
        'total_price':str(sum((Decimal(line['price']['value']) for line in lines),Decimal(0))),'priced_product_scope':physical}


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(observation[k] is not None for k in ('material_index','current_original_quote','prior_own_outcomes')):raise TaskConflict('Monitor observations must remain initially unbound')
    observation.update(material_index={'value':str(observed['macro_environment']['material_price_index']),'unit':'index','basis_ref':basis},
        current_original_quote=deepcopy(observed['current_original_quote']),prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class SupplierMonthlyPriceApplication(ProfessionalMonthlyApplication):
    VERSION='supplier-monthly-price-monitor.v1'
    PREFIX='supplier_monthly_price_monitor:'
    COMPONENTS={'Supplier':(SupplierScreeningActionAssembler,SupplierScreeningResultWorker)}
    OPERATIONS={'Supplier':'monitor_material_prices'}
    PLAN_TYPE=MonthlySupplierPricePlan
    INPUT_SCHEMA='supplier-monthly-prices-input.v1'
    COMPLETED_CHOICES={'track_market'}
    SCOPE_KEY='native_supplier_price_monitor_scope'
    LABEL='Original Supplier price-risk monitoring'

    def __init__(self,**kwargs):
        super().__init__(**kwargs);self._quote_bound={}
        for plan in self.plans:
            q=plan.quote.context
            if q.run_id!=plan.context.run_id or q.actor_id!=plan.context.actor_id or q.business_time!=plan.context.business_time or q.contract_ref.id!='SUPPLIER-A03' or q.scope.kind!='project':
                raise TaskConflict('Private quote changes original Supplier, run, current time or scoped A03')
        self.quote_assembler=SupplierQuoteActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
            macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.VERSION,model_version=self.assembly.client.versions['model'])
        self.quote_worker=SupplierQuoteResultWorker(store=self.assembly.client.tasks,snapshots=self.snapshots,registry=self.registry,
            client_version=self.VERSION,model_version=self.assembly.client.versions['model'],validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)
        self._quote_components=(self.quote_assembler,self.quote_worker)

    def check(self):
        super().check()
        if hasattr(self,'_quote_components') and ((self.quote_assembler,self.quote_worker)!=self._quote_components
                or self.quote_worker.store is not self.assembly.client.tasks or self.quote_worker.snapshots is not self.snapshots
                or self.quote_assembler._views.provider is not self or self.quote_worker.registry is not self.registry):
            raise TaskConflict('Original private quote components changed')

    def participates(self,saved):result_judgment(saved);return True
    def result_note(self,saved):
        j=result_judgment(saved)
        return j.interpretation+' Actual index '+j.material_index.value+'; next private markup '+j.next_markup_rate+'; current private quote '+j.current_original_quote['total_price']+' '+j.current_original_quote['currency']

    def quote_records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(QUOTE_PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):raise TaskConflict('Original private quote journal changed')
        return rows

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            i=TaskIdentity(**h['micro_identity']);j=result_judgment(checked_result(self.workers[i.role],i))
            h['price_analysis']=j.model_dump(mode='json')
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:raise TaskConflict('Previous price monitoring lacks confirmed original native execution')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def quote_sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick);policy=policy_of(plan)
        markup=history[-1]['price_analysis']['next_markup_rate'] if history else policy['base_markup_rate']
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'prior_own_monthly_outcomes':history,'applied_markup_rate':markup,'independent_policy_sha256':task_digest(policy),
            'boundary':BOUNDARY}
        return bind_quote_sources(plan,observed),observed

    def _form_quote(self,plan,request):
        scope=self.scope(request,purpose='propose');key=QUOTE_PREFIX+task_digest([self.assembly.client.run_id,scope,request.request_id])
        if any(r['key']==key for r in self.quote_records()):raise TaskConflict('Original private quote already claimed; no repeated submission')
        if plan.quote.context.scope.ref.id not in self.assembly.engine.projects:raise TaskConflict('Private quote scope lacks its declared original project')
        objects,observed=self.quote_sources(plan,request)
        record=self._save({'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json'),
            'context':plan.quote.context.model_dump(mode='json'),'action_input':plan.quote.action_input,'observed':observed,'source_sha256':task_digest(objects)})
        self._quote_bound[task_digest(record['context'])]=(plan,request.model_copy(deep=True))
        prepared=self.quote_assembler.build(plan.quote.context,**deepcopy(plan.quote.action_input));identity=self.quote_worker.register(prepared,request_id=key+':SUPPLIER-A03')
        record['identity']=identity.as_dict();self._save(record);self.quote_worker.execute(identity,prepared)
        saved=checked_result(self.quote_worker,identity);summary=quote_summary(saved,tick=plan.tick)
        record.update(state='formed',result_sha256=saved['result_sha256'],quote_summary=summary);self._save(record)

    def propose(self,request):
        with self.read_guard():
            scope=self.scope(request,purpose='propose');plan,=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
            self._form_quote(plan,request)
            return super().propose(request)

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');record,=[r for r in self.quote_records() if r['scope']==scope and r['state']=='formed']
        identity=TaskIdentity(**record['identity']);saved=checked_result(self.quote_worker,identity);summary=quote_summary(saved,tick=plan.tick)
        if summary!=record['quote_summary']:raise TaskConflict('Current original quote changed before price monitoring')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick),
            'current_original_quote':summary,'quote_request_record_sha256':record['record_sha256']}
        return bind_sources(plan,observed),observed

    def project(self,*,context,organization_id,grants):
        if context.contract_ref.id!='SUPPLIER-A03':return super().project(context=context,organization_id=organization_id,grants=grants)
        plan,request=self._quote_bound[task_digest(context.model_dump(mode='json'))]
        if context!=plan.quote.context or organization_id!=plan.organization_id:raise TaskConflict('Quote source substitutes another Supplier or read point')
        objects,_=self.quote_sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'private-price-quote:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        if row['identity']['action_id']!='SUPPLIER-A03':return super().validate_invocation(row,prepared)
        plan,request=self._quote_bound[prepared.context_sha256];self.scope(request,purpose='propose')
        if prepared.context!=plan.quote.context or row['identity']['organization_id']!=plan.organization_id:raise TaskConflict('Quote invocation changes its original source request')
        prepared.reading.recheck();return True

    def evidence(self):
        result=super().evidence();result['quote_requests']=self.quote_records();result['boundary']=BOUNDARY;return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Supplier monthly prices require explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=SupplierMonthlyPriceApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
