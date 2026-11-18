"""Same-run own A03 selections -> authorized private A12 relationship records."""
from copy import deepcopy
from integration.architect_portfolio_native import PortfolioPlan,PortfolioComposition,selected_portfolio
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.architect_learning_actions import ArchitectLearningActionAssembler
from integration.architect_learning_results import ArchitectLearningResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ref_type
from src.actions.contracts.architect_client_relationship import ClientRelationshipJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY=('Authorized private client/consultant follow-up record and review schedule from actual same-run own selected appointments and original A03 confirmations. '
    'Actual native team events identify the owner and selected consultants; they are not client satisfaction or completed collaboration. '
    'The responsible actor, permitted internal use, allowed counterparties, priority weight/threshold and review interval are independent synthetic initial task inputs. '
    'Only a confirmed original monthly execution permits later adoption of the same private records. '
    'External contact consent, delivered messages and activated detailed service relationships stay unknown. '
    'No outreach, receipt, new commission, spending, resource reservation, reputation or measured capability improvement is inferred.')


class ClientRelationshipPlan(PortfolioPlan):
    observation_ref:ref_type('ClientRelationshipObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='record_feedback':
        raise TaskConflict('Client follow-up requires original completed A12 private recording')
    return ClientRelationshipJudgment.model_validate_json(saved['result']['payload']['interpretation'])


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    row,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(row[k] is not None for k in ('market_demand','native_free_ratio','parties','prior_own_outcomes')):
        raise TaskConflict('Client follow-up observations must remain unbound until actual original requests')
    row.update(market_demand={'value':str(observed['macro_environment']['market_demand_index']),'unit':'index','basis_ref':basis},
        native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        parties=deepcopy(observed['parties']),prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class ArchitectClientRelationshipApplication(ProfessionalMonthlyApplication):
    VERSION='architect-monthly-client-relationship.v1'
    PREFIX='architect_client_relationship_request:'
    COMPONENTS={'Architect':(ArchitectLearningActionAssembler,ArchitectLearningResultWorker)}
    OPERATIONS={'Architect':'maintain_client_relationship'}
    PLAN_TYPE=ClientRelationshipPlan
    INPUT_SCHEMA='architect-client-relationship-input.v1'
    COMPLETED_CHOICES={'record_feedback'}
    SCOPE_KEY='native_architect_client_relationship_scope'
    ACTION_NUMBER='A12'
    LABEL='Original authorized private client and consultant follow-up record'

    def __init__(self,*,professional,settings):
        self.professional=professional
        super().__init__(assembly=professional.assembly,settings=settings,authority=professional.authority,install=False)

    def participates(self,saved):return result_judgment(saved).participate
    def result_note(self,saved):return result_judgment(saved).interpretation

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            saved=checked_result(self.workers['Architect'],TaskIdentity(**h['micro_identity']));j=result_judgment(saved)
            event,=[e for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memories=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if len(memories)!=1 or memories[0]['label']!=event.data['label']:
                raise TaskConflict('Client follow-up lost its exact own original monthly memory')
            h.update(client_judgment=j.model_dump(mode='json'),original_native_memory=deepcopy(memories[0]))
        expected={r['scope']['tick'] for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick}
        if expected!={h['tick'] for h in history}:raise TaskConflict('Earlier client record has no confirmed original monthly execution')
        return sorted(history,key=lambda h:h['tick'])

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');engine=self.assembly.engine;profile=engine.agents[plan.organization_id];parties=[]
        for entry in selected_portfolio(self.professional,organization_id=plan.organization_id,tick=plan.tick):
            if entry['tick']>=plan.tick:continue
            project=engine.projects[entry['project_id']];event,=[e for e in project.event_log if e['event_id']==entry['event_id']]
            for role,pid in [('Owner',project.owner_id),('Engineer',event['data'].get('engineer_id')),('QS',event['data'].get('qs_id'))]:
                if pid is None:continue
                if pid not in engine.agents or engine.agents[pid].role!=role:raise TaskConflict('Actual selected collaboration party changes original identity or role')
                parties.append({'organization_id':pid,'role':role,'selection':deepcopy(entry)})
        parties.sort(key=lambda p:(p['selection']['tick'],p['selection']['event_id'],p['role'],p['organization_id']))
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),
            'native_profile':{'available_resource':profile.available_resource(),'total_resource_capacity':profile.total_resource_capacity,
                'free_ratio':profile.available_resource()/profile.total_resource_capacity},
            'parties':parties,'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick)}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY;return result


class ClientRelationshipComposition(PortfolioComposition):
    VERSION='professional-client-relationship-composition.v1'
    MONTHLY_APPLICATION=ArchitectClientRelationshipApplication
    BOUNDARY=BOUNDARY


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Client follow-up scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ClientRelationshipComposition(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.close,writer_guard=app.read_guard)
