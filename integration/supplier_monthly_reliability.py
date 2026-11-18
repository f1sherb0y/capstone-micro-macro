"""Original A05 backup inquiry candidate -> native review -> later own A05."""
from copy import deepcopy
from typing import Literal
from pydantic import Field
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from integration.supplier_planning_results import SupplierPlanningResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import StrictRecord,TextId,ActionContext,ref_type
from src.actions.contracts.supplier_monthly_reliability import SupplyReliabilityJudgment
from src.coordination.tasks import TaskIdentity,TaskConflict,task_digest

BOUNDARY=('Original monthly backup-sourcing review only, using an independently authorized own-risk forecast and original A05 inquiry candidate. '
    'Native reliability is a normalized readiness indicator, not physical delivery history. Stock, physical capacity and detailed commitments remain unknown. '
    'No sent inquiry, counterparty consent, upstream offer/order, stock adjustment, production, shipment, customer receipt or measured reliability improvement is inferred. '
    'Original random capability updates may also occur on maintain_operations and are not causal improvement evidence.')


class ReliabilityPlan(StrictRecord):
    organization_id:TextId
    role:Literal['Supplier']
    tick:int=Field(ge=1)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    observation_ref:ref_type('SupplyReliabilityObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='request_quote':
        raise TaskConflict('Reliability review requires the original completed A05 private request candidate')
    return SupplyReliabilityJudgment.model_validate_json(saved['result']['payload']['note'])


def backup_request(saved):
    payload=saved['result']['payload']
    return {k:deepcopy(payload[k]) for k in ('supplier_ids','required_lines')}


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(observation[k] is not None for k in ('native_reliability','native_free_ratio','prior_own_outcomes')):
        raise TaskConflict('Reliability observations must remain unbound until actual native request')
    observation.update(native_reliability={'value':str(observed['native_profile']['supply_reliability']),'unit':'native_reliability_index','basis_ref':basis},
        native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class SupplierReliabilityApplication(ProfessionalMonthlyApplication):
    VERSION='supplier-monthly-reliability-review.v1'
    PREFIX='supplier_monthly_reliability_request:'
    COMPONENTS={'Supplier':(SupplierPlanningActionAssembler,SupplierPlanningResultWorker)}
    OPERATIONS={'Supplier':'improve_supply_reliability'}
    PLAN_TYPE=ReliabilityPlan
    INPUT_SCHEMA='supplier-monthly-reliability-input.v1'
    ACTION_NUMBER='A05'
    COMPLETED_CHOICES={'request_quote'}
    SCOPE_KEY='native_supplier_reliability_scope'
    LABEL='Original private backup-sourcing review'

    def participates(self,saved):return result_judgment(saved).participate
    def result_note(self,saved):return result_judgment(saved).interpretation

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            saved=checked_result(self.workers['Supplier'],TaskIdentity(**h['micro_identity']));judgment=result_judgment(saved)
            event,=[e for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memory=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if (len(memory)!=1 or memory[0]['label']!=event.data['label'] or memory[0]['capability_update']!=event.data.get('capability_update')
                    or judgment.current_backup_request!=backup_request(saved)):
                raise TaskConflict('Earlier review lost its exact original request or native memory')
            h.update(review=judgment.model_dump(mode='json'),backup_request=backup_request(saved),original_native_memory=deepcopy(memory[0]))
        expected={r['scope']['tick'] for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick}
        if expected!={h['tick'] for h in history}:raise TaskConflict('Earlier A05 has no confirmed original monthly outcome')
        return sorted(history,key=lambda h:h['tick'])

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');agent=self.assembly.engine.agents[plan.organization_id]
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),
            'native_profile':{'supply_reliability':agent.supply_reliability,'available_resource':agent.available_resource(),
                'total_resource_capacity':agent.total_resource_capacity,'free_ratio':agent.available_resource()/agent.total_resource_capacity},
            'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick)}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY;return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Supplier reliability scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=SupplierReliabilityApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
