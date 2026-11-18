"""Original A05 portfolio calculation, native monthly review, actual later baseline."""
from copy import deepcopy
from pydantic import Field
from typing import Literal
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from integration.owner_financing_actions import OwnerFinancingActionAssembler
from integration.owner_financing_results import OwnerFinancingResultWorker
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.owner_monthly_capacity import MonthlyOwnerCapacityJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Original OWN-A05 reviews one independently declared complete synthetic initial private treasury portfolio: actual/restricted cash, existing original debt and unpaid obligations, approved future nonbank release and proposed funding use. Actual native financing index is a separate environment-risk signal, not money or credit. Original cash calendar decides private own_funds/no_finance; both completed analyses can execute original monthly review_financing_capacity. Only confirmed earlier own actual monthly review supplies the later comparison baseline and watch transition. No new financing selection, application, arrangement, draw, reservation, payment, debt discharge or ledger mutation is inferred.'


class MonthlyOwnerCapacityPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Owner']
    tick:int=Field(ge=1,le=2)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyOwnerCapacityObservation')


def result_judgment(saved):
    payload=saved['result'].get('payload',{})
    if saved['result']['kind']!='completed' or payload.get('choice') not in {'own_funds','no_finance'}:raise TaskConflict('Capacity review requires an original completed A05 cash decision')
    judgment=MonthlyOwnerCapacityJudgment.model_validate_json(payload['note'])
    if judgment.original_choice!=payload['choice']:raise TaskConflict('Review interpretation changes original A05 choice')
    return judgment


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);native=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,native,observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if observation['actual_financing_index'] is not None or observation['prior_own_reviews'] is not None:raise TaskConflict('Actual index and earlier executed reviews must not be prefilled')
    observation['actual_financing_index']={'value':str(observed['macro_environment']['financing_condition_index']),'unit':'index','basis_ref':native}
    observation['prior_own_reviews']=deepcopy(observed['prior_own_monthly_outcomes'])
    return objects


class OwnerMonthlyCapacityApplication(ProfessionalMonthlyApplication):
    VERSION='owner-monthly-capacity.v1'
    PREFIX='owner_monthly_capacity_request:'
    COMPONENTS={'Owner':(OwnerFinancingActionAssembler,OwnerFinancingResultWorker)}
    OPERATIONS={'Owner':'review_financing_capacity'}
    PLAN_TYPE=MonthlyOwnerCapacityPlan
    INPUT_SCHEMA='owner-monthly-capacity-input.v1'
    COMPLETED_CHOICES={'own_funds','no_finance'}
    SCOPE_KEY='native_owner_monthly_capacity'
    LABEL='Original Owner private financing capacity review'

    def action_id(self,role):
        if role!='Owner':raise TaskConflict('Owner review cannot substitute another role')
        return 'OWN-A05'
    def participates(self,saved):result_judgment(saved);return True
    def result_note(self,saved):return result_judgment(saved).interpretation
    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            identity=TaskIdentity(**h['micro_identity']);judgment=result_judgment(checked_result(self.workers['Owner'],identity))
            h['review']=judgment.model_dump(mode='json');h['review_sha256']=task_digest(h['review'])
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:raise TaskConflict('Earlier review lacks a confirmed actual native outcome')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))
    def sources(self,plan,request):
        observed={'scope':self.scope(request,purpose='propose'),'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick),'boundary':BOUNDARY}
        return bind_sources(plan,observed),observed
    def evidence(self):return {**super().evidence(),'boundary':BOUNDARY}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Owner capacity development requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerMonthlyCapacityApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
