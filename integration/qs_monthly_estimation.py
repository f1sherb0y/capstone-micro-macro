"""Actual QS monthly method operation and confirmed private index assumption feedback."""
from copy import deepcopy
from typing import Literal
from pydantic import Field
from integration.qs_learning_actions import QSLearningActionAssembler
from integration.qs_learning_results import QSLearningResultWorker
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.qs_monthly_estimation import MonthlyEstimationJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY=('Bounded QS monthly private index-sensitivity review and original improve_cost_estimation activity only. '
    'The own initial QS mandate and access permission are declared scenario inputs. Original design planned_cost is a reference estimate, '
    'not incurred cost or a frozen independent forecast. The indicative estimate is a private sensitivity calculation in abstract native model units; '
    'it does not overwrite the macro estimate or establish regional prices, improved accuracy, calibrated error, final cost, payment or issued training. '
    'A private index assumption is treated as accepted only after the exact micro proposal, final decision and own native activity are confirmed. '
    'Original random capability updates remain native mechanics, not causal evidence of improvement.')


class MonthlyEstimationPlan(StrictRecord):
    organization_id:TextId
    role:Literal['QS']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyEstimationObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='record_feedback':
        raise TaskConflict('Monthly estimation requires the actual completed QS-A12 result')
    return MonthlyEstimationJudgment.model_validate_json(saved['result']['payload']['interpretation'])


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects)
    evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(observation[k] is not None for k in ('material_index','native_free_ratio','own_project_evidence','prior_own_outcomes')):
        raise TaskConflict('Monthly estimation actual observations must not be prefilled')
    basis=plan.native_evidence_ref.model_dump(mode='json')
    observation.update(material_index={'value':str(observed['macro_environment']['material_price_index']),'unit':'index','basis_ref':basis},
        native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        own_project_evidence=deepcopy(observed['own_project_evidence']),prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class QSMonthlyEstimationApplication(ProfessionalMonthlyApplication):
    VERSION='qs-monthly-estimation.v1'
    PREFIX='qs_monthly_estimation_request:'
    COMPONENTS={'QS':(QSLearningActionAssembler,QSLearningResultWorker)}
    OPERATIONS={'QS':'improve_cost_estimation'}
    PLAN_TYPE=MonthlyEstimationPlan
    INPUT_SCHEMA='qs-monthly-estimation-input.v1'
    ACTION_NUMBER='A12'
    LABEL='QS private future estimation sensitivity review'
    COMPLETED_CHOICES={'record_feedback'}
    SCOPE_KEY='native_qs_monthly_estimation_scope'

    def participates(self,saved):return result_judgment(saved).participate
    def result_note(self,saved):return result_judgment(saved).model_dump_json()

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            identity=TaskIdentity(**h['micro_identity']);saved=checked_result(self.workers['QS'],identity)
            judgment=result_judgment(saved)
            event,=[e.model_dump(mode='json') for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memory=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if len(memory)!=1 or memory[0]['label']!=event['data']['label'] or memory[0]['capability_update']!=event['data'].get('capability_update'):
                raise TaskConflict('QS private assumption lacks original own executed activity and memory')
            h.update(review=judgment.model_dump(mode='json'),review_sha256=task_digest(judgment.model_dump(mode='json')),
                original_native_memory=deepcopy(memory[0]),capability_update=event['data'].get('capability_update'))
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:
            raise TaskConflict('Earlier QS proposal has no confirmed execution; preserve journal without adoption or replay')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');engine=self.assembly.engine
        profile=engine.agents[plan.organization_id];history=self.history(plan.organization_id,plan.tick)
        policy,=[r['value'] for r in plan.objects if r['ref']['kind']=='MonthlyEstimationPolicy']
        projects=[]
        for project_id in policy['authorized_project_ids']:
            project=engine.projects[project_id]
            if project.selected_qs_id!=plan.organization_id or project.current_stage.value!='design':
                raise TaskConflict('Monthly estimate lacks its declared current own design mandate')
            event,=[e.model_dump(mode='json') for e in engine.events.events
                if e.event_type=='project_state_updated' and e.project_id==project_id and e.tick==plan.tick]
            if event['data']['planned_cost']!=project.performance.planned_cost or project.estimated_cost!=project.performance.planned_cost:
                raise TaskConflict('Monthly estimate source differs from original native project event')
            projects.append({'project_id':project_id,'selected_qs_id':project.selected_qs_id,'tick':plan.tick,
                'reference_estimate':str(project.performance.planned_cost),'unit':'native_model_cost_unit',
                'native_event':event,'native_event_sha256':task_digest(event)})
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':history,
            'own_project_evidence':projects,'native_profile':{'organization_id':plan.organization_id,'role':profile.role,
                'available_resource':profile.available_resource(),'total_resource_capacity':profile.total_resource_capacity,
                'free_ratio':profile.available_resource()/profile.total_resource_capacity}}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY
        return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Monthly estimation requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=QSMonthlyEstimationApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
