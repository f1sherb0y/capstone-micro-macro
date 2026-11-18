"""Original OWN-A01 and original native monthly demand analysis with own feedback."""
from copy import deepcopy
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.owner_observation_actions import OwnerObservationActionAssembler
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.owner_monthly_demand import MonthlyOwnerDemandJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Actual simulation-global demand analysis only. Original propose is an unexecuted private follow-up intent; no A16 brief, case, concrete investment candidate, land/property right, regional survey, project commitment, financing capacity, cash/debt ledger or investment-strategy publication is inferred. Private case and finance history remain unknown. Native random capability changes are not proof of an analysis effect.'


class MonthlyOwnerDemandPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Owner']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyOwnerDemandObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice'] not in {'propose','ignore'}:
        raise TaskConflict('Monthly demand requires the original completed OWN-A01 result')
    judgment=MonthlyOwnerDemandJudgment.model_validate_json(saved['result']['payload']['note'])
    if judgment.original_choice!=saved['result']['payload']['choice']:raise TaskConflict('Monthly interpretation changes original A01 result')
    return judgment


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    signal,=[r['value'] for r in objects if r['ref']['kind']=='DemandObservation']
    capacity,=[r['value'] for r in objects if r['ref']['kind']=='ManagementCapacity']
    if (any(observation[k] is not None for k in ('current_market_index','native_available_resource','prior_own_outcomes'))
            or signal['measure'] is not None or capacity['total'] is not None):
        raise TaskConflict('Monthly demand and native capacity observations must be initially unbound')
    index={'value':str(observed['macro_environment']['market_demand_index']),'unit':'index','basis_ref':basis}
    available={'value':str(observed['native_profile']['available_resource']),'unit':'native_resource','basis_ref':basis}
    observation.update(current_market_index=index,native_available_resource=available,prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    signal['measure']={'state':'known','value':deepcopy(index)}
    capacity['total']={'state':'known','value':deepcopy(available)}
    return objects


class OwnerMonthlyDemandApplication(ProfessionalMonthlyApplication):
    VERSION='owner-monthly-demand.v1'
    PREFIX='owner_monthly_demand_request:'
    COMPONENTS={'Owner':(OwnerObservationActionAssembler,OwnerObservationResultWorker)}
    OPERATIONS={'Owner':'evaluate_market_demand'}
    PLAN_TYPE=MonthlyOwnerDemandPlan
    INPUT_SCHEMA='owner-monthly-demand-input.v1'
    COMPLETED_CHOICES={'propose','ignore'}
    SCOPE_KEY='native_owner_monthly_demand_scope'
    LABEL='Original Owner global demand analysis'

    def action_id(self,role):
        if role!='Owner':raise TaskConflict('Owner demand cannot replace another role')
        return 'OWN-A01'
    def participates(self,saved):result_judgment(saved);return True
    def result_note(self,saved):
        judgment=result_judgment(saved)
        return judgment.interpretation+' Actual index '+judgment.current_market_index.value+'; threshold '+judgment.declared_screening_threshold.value

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            identity=TaskIdentity(**h['micro_identity']);judgment=result_judgment(checked_result(self.workers[identity.role],identity))
            h['analysis']=judgment.model_dump(mode='json');h['analysis_sha256']=task_digest(h['analysis'])
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:
            raise TaskConflict('Earlier demand analysis has no confirmed original native outcome')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');profile=self.assembly.engine.agents[plan.organization_id]
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick),
            'native_profile':{'organization_id':profile.agent_id,'role':profile.role,'available_resource':profile.available_resource(),
                'total_resource_capacity':profile.total_resource_capacity}}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY;return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Owner monthly demand requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerMonthlyDemandApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
