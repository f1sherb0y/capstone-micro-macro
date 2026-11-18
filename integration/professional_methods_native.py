"""Original Architect/Engineer A12 judgments drive native background method operations."""
from copy import deepcopy
from typing import Literal
from pydantic import Field

from integration.architect_learning_actions import ArchitectLearningActionAssembler
from integration.architect_learning_results import ArchitectLearningResultWorker
from integration.engineer_learning_actions import EngineerLearningActionAssembler
from integration.engineer_learning_results import EngineerLearningResultWorker
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.actions.contracts.professional_monthly_methods import MonthlyMethodJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest


COMPONENTS={'Architect':(ArchitectLearningActionAssembler,ArchitectLearningResultWorker),
    'Engineer':(EngineerLearningActionAssembler,EngineerLearningResultWorker)}
OPERATIONS={'Architect':'improve_design_capability','Engineer':'improve_engineering_capability'}
CAPABILITIES={'Architect':'design_capability','Engineer':'technical_capability'}
BOUNDARY='Native background method-improvement planning and original monthly operations only. Detailed private learning history and capabilities remain unknown; no completed training, formal design/check output, issued qualification, client/reputation record or project cost outcome is inferred. Native normalized capability updates remain the original random mechanism, including on maintain_operations; they are not proof that this activity caused improvement.'


class MonthlyMethodPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Architect','Engineer']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyMethodObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='record_feedback':
        raise TaskConflict('Monthly methods require the original completed A12 observation judgment')
    return MonthlyMethodJudgment.model_validate_json(saved['result']['payload']['interpretation'])


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    fields=('regulatory_pressure','native_capability','native_free_ratio','prior_own_outcomes')
    if any(observation[k] is not None for k in fields):raise TaskConflict('Monthly method observations must be unbound until actual native observation')
    basis=plan.native_evidence_ref.model_dump(mode='json')
    observation.update(regulatory_pressure={'value':str(observed['macro_environment']['regulatory_pressure_index']),'unit':'index','basis_ref':basis},
        native_capability={'value':str(observed['native_profile']['capability']),'unit':'native_capability_index','basis_ref':basis},
        native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class ProfessionalMethodsApplication(ProfessionalMonthlyApplication):
    VERSION='professional-monthly-methods.v1'
    PREFIX='professional_monthly_methods_request:'
    COMPONENTS=COMPONENTS
    OPERATIONS=OPERATIONS
    PLAN_TYPE=MonthlyMethodPlan
    INPUT_SCHEMA='professional-monthly-methods-input.v1'
    ACTION_NUMBER='A12'
    LABEL='Original background method-improvement decision'
    COMPLETED_CHOICES={'record_feedback'}
    SCOPE_KEY='native_professional_methods_scope'

    def participates(self,saved):return result_judgment(saved).participate

    def result_note(self,saved):
        judgment=result_judgment(saved)
        return judgment.interpretation+' '+judgment.method_focus

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            identity=TaskIdentity(**h['micro_identity']);saved=checked_result(self.workers[identity.role],identity)
            judgment=result_judgment(saved)
            event,=[e.model_dump(mode='json') for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memory=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if (len(memory)!=1 or judgment.role!=identity.role or judgment.operation!=self.OPERATIONS[identity.role]
                    or memory[0]['capability_update']!=event['data'].get('capability_update')
                    or memory[0]['label']!=event['data']['label']):
                raise TaskConflict('Monthly methods lost the original native outcome or role-specific judgment')
            h.update(method_focus=judgment.method_focus,prior_observed_capability=judgment.native_capability.model_dump(mode='json'),
                capability_update=event['data'].get('capability_update'),original_native_memory=deepcopy(memory[0]))
        expected=[r for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick]
        if {r['scope']['tick'] for r in expected}!={h['tick'] for h in history}:
            raise TaskConflict('Earlier monthly method judgment lacks a confirmed original native outcome; do not infer execution')
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick)
        profile=self.assembly.engine.agents[plan.organization_id]
        if profile.role!=plan.role:raise TaskConflict('Monthly method profile changes original firm role')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':history,
            'native_profile':{'organization_id':plan.organization_id,'role':plan.role,'capability_field':CAPABILITIES[plan.role],
                'capability':getattr(profile,CAPABILITIES[plan.role]),'available_resource':profile.available_resource(),
                'total_resource_capacity':profile.total_resource_capacity,
                'free_ratio':profile.available_resource()/profile.total_resource_capacity}}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY
        return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Professional monthly methods require explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ProfessionalMethodsApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
