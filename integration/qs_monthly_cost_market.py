"""Original QS-A01 and native monthly execution backed by a private index journal."""
from copy import deepcopy
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.qs_market_actions import QSMarketActionAssembler
from integration.qs_market_results import QSMarketResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.qs_monthly_cost_market import MonthlyCostJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest,canonical

BOUNDARY='Private original dimensionless simulation-global material index knowledge only. No currency conversion, supplier quote, delivered material price, regional/tender benchmark, actual project quantity/cost, forecast validation or cost-estimation improvement is inferred. Native capability changes remain original random mechanics. Publication requires a confirmed original update_cost_database event and occurs at the next actual own observation.'
INDEX_PREFIX='qs_monthly_registered_index:'


class MonthlyCostPlan(StrictRecord):
    organization_id:TextId
    role:Literal['QS']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyCostObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice'] not in {'register_source','ignore'}:
        raise TaskConflict('Monthly cost market requires an original completed QS-A01 result')
    result=MonthlyCostJudgment.model_validate_json(saved['result']['payload']['note'])
    if (saved['result']['payload']['choice']=='register_source')!=(result.operation=='update_cost_database'):
        raise TaskConflict('Cost-market operation changes original registration choice')
    return result


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(observation[k] is not None for k in ('material_index','prior_own_outcomes','registered_indices')):
        raise TaskConflict('Cost-market observations must be unbound until actual native observation')
    observation.update(material_index={'value':str(observed['macro_environment']['material_price_index']),'unit':'index','basis_ref':plan.native_evidence_ref.model_dump(mode='json')},
        prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']),registered_indices=deepcopy(observed['registered_indices']))
    return objects


def registration(record,saved,history_item):
    """Pure reconstruction from a verified native event, original result and request."""
    judgment=result_judgment(saved)
    if judgment.operation!='update_cost_database' or saved['result']['payload']['choice']!='register_source':
        raise TaskConflict('A market review is not a source registration')
    entry={'key':INDEX_PREFIX+history_item['event_id'],'schema_version':'qs-private-simulation-index.v1',
        'organization_id':record['scope']['organization_id'],'observed_tick':record['scope']['tick'],'registered_tick':record['scope']['tick']+1,
        'source_ref':judgment.source_ref.model_dump(mode='json'),'material_index':judgment.material_index.model_dump(mode='json'),
        'applicability':deepcopy(saved['result']['payload']['applicability']),
        'native_event_id':history_item['event_id'],'native_event_sha256':history_item['source_event_sha256'],
        'micro_identity':deepcopy(record['identity']),'micro_result_sha256':saved['result_sha256'],
        'proposal_response_sha256':record['proposal_response_sha256'],'observed_source_sha256':task_digest(record['observed']),
        'boundary':BOUNDARY}
    entry['record_sha256']=task_digest(entry);return entry


class QSCostMarketApplication(ProfessionalMonthlyApplication):
    VERSION='qs-monthly-cost-market.v1'
    PREFIX='qs_monthly_cost_market_request:'
    COMPONENTS={'QS':(QSMarketActionAssembler,QSMarketResultWorker)}
    PLAN_TYPE=MonthlyCostPlan
    INPUT_SCHEMA='qs-monthly-cost-market-input.v1'
    COMPLETED_CHOICES={'register_source','ignore'}
    SCOPE_KEY='native_qs_cost_market_scope'
    LABEL='Original QS simulation-index registration or review'

    def participates(self,saved):result_judgment(saved);return True
    def operation(self,saved,role):return result_judgment(saved).operation
    def result_note(self,saved):
        j=result_judgment(saved)
        return j.interpretation+' Positive pressure '+j.positive_cost_pressure+'; priority '+j.pressure_priority+'; original index '+j.material_index.value

    def history(self,org,tick):
        history=super().history(org,tick)
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:
            raise TaskConflict('Earlier cost-market judgment lacks an actual native outcome')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def indices(self,org):
        with self.assembly.client.tasks._lock:
            entries=[__import__('json').loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(INDEX_PREFIX+'%',))]
        if any(e['record_sha256']!=task_digest({k:v for k,v in e.items() if k!='record_sha256'}) for e in entries):
            raise TaskConflict('Private simulation-index journal changed')
        return sorted((e for e in entries if e['organization_id']==org),key=lambda e:e['observed_tick'])

    def reconcile(self,org,tick):
        # This is the only publication site. It runs at a later actual proposal,
        # after base history checks native event + original proposal + final.
        for h in self.history(org,tick):
            if h['operation']!='update_cost_database':continue
            record,=[r for r in self.records() if r['identity']==h['micro_identity']]
            i=TaskIdentity(**record['identity']);entry=registration(record,checked_result(self.workers[i.role],i),h)
            if entry['registered_tick']>tick:raise TaskConflict('Cannot publish an unexecuted or future index')
            with self.assembly.client.tasks._transaction():
                existing=self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',(entry['key'],)).fetchone()
                if existing is None:self.assembly.client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)',(entry['key'],canonical(entry)))
                elif __import__('json').loads(existing[0])!=entry:raise TaskConflict('Registered index is immutable')

    def propose(self,request):
        with self.read_guard():
            scope=self.scope(request,purpose='propose');self.reconcile(scope['organization_id'],scope['tick'])
            return super().propose(request)

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick);entries=self.indices(plan.organization_id)
        if {e['native_event_id'] for e in entries}!={h['event_id'] for h in history if h['operation']=='update_cost_database'}:
            raise TaskConflict('Actual native updates and private index registrations differ')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':history,'registered_indices':entries}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY
        result['registered_indices']={org:self.indices(org) for org in sorted({p.organization_id for p in self.plans})}
        return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('QS monthly cost market requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=QSCostMarketApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
