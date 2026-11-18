"""Compose real professional selections with original Architect A12 monthly recording."""
from copy import deepcopy
import json
from typing import Literal
from pydantic import Field
from integration.architect_learning_actions import ArchitectLearningActionAssembler
from integration.architect_learning_results import ArchitectLearningResultWorker
from integration.professional_intake_native import ProfessionalIntakeApplication,ProfessionalIntakeSettings
from integration.professional_monthly_native import ProfessionalMonthlyApplication,ProfessionalMonthlySettings
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension,module_client_implementation
from src.actions.contracts.common import StrictRecord,TextId,ActionContext,ref_type
from src.actions.contracts.architect_monthly_portfolio import MonthlyPortfolioJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY=('Private selected-project portfolio from actual same-run native selections and original A03 confirmations. '
    'Selection is not service completion, client satisfaction, publicity permission or measured reputation growth. '
    'No cross-region collaboration is inferred without a corresponding actual selection. Formal learning and qualifications stay unknown; '
    'original random capability updates are not caused-effect evidence.')


class PortfolioPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Architect']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('MonthlyPortfolioObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='record_feedback':
        raise TaskConflict('Portfolio requires the original completed A12 recording')
    return MonthlyPortfolioJudgment.model_validate_json(saved['result']['payload']['interpretation'])


def selected_portfolio(professional,*,organization_id,tick):
    """Reconstruct original A02/OWN-A04/A03 provenance, including same-tick lifecycle completion."""
    professional._check();app=professional.appointment;app.check_components()
    client,engine=professional.assembly.client,professional.assembly.engine
    if tick!=engine.current_tick or client.organization_roles.get(organization_id)!='Architect':
        raise TaskConflict('Portfolio source requires its current own Architect scope')
    inbox={e['event_id']:e for e in client.inbox.for_organization(run_id=client.run_id,organization_id=organization_id)}
    result=[]
    for project in engine.projects.values():
        for event in project.event_log:
            if (event['event_type']!='consultant_team_appointed' or event['tick']>tick
                    or event['data'].get('architect_id')!=organization_id):continue
            entry=inbox.get(event['event_id'])
            if entry is None:raise TaskConflict('Portfolio selection lacks its actual own received observation')
            plans=[p for p in app.plans if (p.organization_id,p.project_id,p.tick)==(organization_id,project.project_id,event['tick'])]
            if len(plans)!=1:raise TaskConflict('Portfolio selection lost its original A03 source plan')
            receipt=app._record(event['event_id'],organization_id)
            if receipt is None or receipt['state']!='formed' or receipt['choice']!='confirm':
                raise TaskConflict('Portfolio selection awaits its original private A03 confirmation')
            saved=app._formed(receipt,plans[0],entry)
            result.append({'organization_id':organization_id,'project_id':project.project_id,'region':project.region,
                'client_organization_id':project.owner_id,'tick':event['tick'],'event_id':event['event_id'],
                'source_event_sha256':task_digest(event),'appointment_identity':deepcopy(receipt['identity']),
                'appointment_result_sha256':saved['result_sha256'],'receipt_record_sha256':receipt['record_sha256'],
                'status':'selected_and_privately_confirmed'})
    return sorted(result,key=lambda e:(e['tick'],e['project_id'],e['event_id']))


class ArchitectPortfolioApplication(ProfessionalMonthlyApplication):
    VERSION='architect-monthly-portfolio.v1'
    PREFIX='architect_monthly_portfolio_request:'
    COMPONENTS={'Architect':(ArchitectLearningActionAssembler,ArchitectLearningResultWorker)}
    OPERATIONS={'Architect':'build_cross_region_reputation'}
    PLAN_TYPE=PortfolioPlan
    INPUT_SCHEMA='architect-monthly-portfolio-input.v1'
    COMPLETED_CHOICES={'record_feedback'}
    SCOPE_KEY='native_architect_portfolio_scope'
    ACTION_NUMBER='A12'
    LABEL='Original private selected-project portfolio recording'

    def __init__(self,*,professional,settings):
        self.professional=professional
        super().__init__(assembly=professional.assembly,settings=settings,authority=professional.authority,install=False)

    def participates(self,saved):return result_judgment(saved).participate

    def result_note(self,saved):return result_judgment(saved).interpretation

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            saved=checked_result(self.workers['Architect'],TaskIdentity(**h['micro_identity']))
            judgment=result_judgment(saved)
            memories=[m for m in self.assembly.engine.agents[org].episodic_memory
                if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            event,=[e for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            if len(memories)!=1 or memories[0]['label']!=event.data['label']:
                raise TaskConflict('Portfolio history lost the actual original enterprise memory')
            h.update(portfolio_judgment=judgment.model_dump(mode='json'),original_native_memory=deepcopy(memories[0]))
        expected={r['scope']['tick'] for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick}
        if expected!={h['tick'] for h in history}:raise TaskConflict('Earlier portfolio judgment lacks a confirmed native outcome')
        return sorted(history,key=lambda h:h['tick'])

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');profile=self.assembly.engine.agents[plan.organization_id]
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),
            'native_profile':{'available_resource':profile.available_resource(),'total_resource_capacity':profile.total_resource_capacity,
                'free_ratio':profile.available_resource()/profile.total_resource_capacity},
            'selected_entries':selected_portfolio(self.professional,organization_id=plan.organization_id,tick=plan.tick),
            'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick)}
        objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
        observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
        fields=('market_demand','native_free_ratio','selected_entries','prior_own_outcomes')
        if any(observation[k] is not None for k in fields):raise TaskConflict('Portfolio observations must be unbound until actual native execution')
        observation.update(market_demand={'value':str(observed['macro_environment']['market_demand_index']),'unit':'index','basis_ref':basis},
            native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
            selected_entries=deepcopy(observed['selected_entries']),prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
        return objects,observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY;return result


class PortfolioCompositionSettings(StrictRecord):
    professional:ProfessionalIntakeSettings
    monthly:ProfessionalMonthlySettings


class PortfolioComposition:
    VERSION='professional-portfolio-composition.v1'
    MONTHLY_APPLICATION=ArchitectPortfolioApplication
    BOUNDARY=BOUNDARY

    def __init__(self,*,assembly,settings):
        self.assembly=assembly;self.settings=PortfolioCompositionSettings.model_validate(settings).model_copy(deep=True)
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self.professional=ProfessionalIntakeApplication(assembly=assembly,settings=self.settings.professional,install=False)
        try:
            if self.professional.appointment is None or self.professional.owner is None or self.professional.feedback is not None:
                raise TaskConflict('Portfolio requires original owner selection and A03 confirmation without duplicate A12 event applications')
            self.monthly=self.MONTHLY_APPLICATION(professional=self.professional,settings=self.settings.monthly)
            self.authority=self.professional.authority;self.read_guard=self.authority.read_guard
            client=assembly.client
            with client._lock:
                for (role,operation),handler in self.bindings().items():
                    client.bind_proposal_handler(role=role,operation=operation,handler=handler,client_version=self.VERSION+':'+role+':'+operation)
                client.decision_handler=self.decide;client.continuation_dispatcher=self.dispatch
                self.professional.seal_client_binding();self.monthly.seal_client_binding()
                self._implementation=module_client_implementation(client)
            self.check()
        except Exception:
            self.professional.close();raise

    def bindings(self):
        return {**self.professional.proposal_bindings(),**self.monthly.proposal_bindings()}

    def check(self):
        client=self.assembly.client
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.monthly.professional is not self.professional or self.monthly.authority is not self.professional.authority
                or self.monthly.authority is not self.authority or self.monthly.registry is not self.professional.registry
                or self.read_guard!=self.authority.read_guard or self.monthly._other_decision!=self.professional._other_decision
                or module_client_implementation(client)!=self._implementation
                or client.decision_handler!=self.decide or client.continuation_dispatcher!=self.dispatch
                or any(client.proposal_handlers.get(k)!=v for k,v in self.bindings().items())):
            raise TaskConflict('Portfolio composition lost its sealed shared authority or original route ownership')
        self.professional._check();self.monthly.check()

    def decide(self,request):
        self.check()
        if request.agent.role=='Architect' and request.decision_type=='monthly_enterprise_operation':return self.monthly.decide(request)
        return self.professional.decide(request)

    def dispatch(self,*,run_id,organization_id):
        self.check();return self.professional.appointment.dispatch(run_id=run_id,organization_id=organization_id)

    def evidence(self):
        with self.read_guard():
            self.check();return {'version':self.VERSION,'professional':self.professional.evidence(),'monthly':self.monthly.evidence(),'boundary':self.BOUNDARY}

    def close(self):self.professional.close()


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Portfolio development scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=PortfolioComposition(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.close,writer_guard=app.read_guard)
