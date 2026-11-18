"""Actual original procurement -> original A05 monthly review -> later own A05."""
from copy import deepcopy
from typing import Literal
from integration.professional_monthly_native import ProfessionalMonthlyApplication,ProfessionalMonthlyPlan,ProfessionalMonthlySettings
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_planning_results import ContractorPlanningResultWorker
from integration.supplier_order_native import SupplierOrderNativeApplication,SupplierOrderNativeSettings
from integration.contractor_supply_native_feedback import prior_contractor_supply_selections
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension,module_client_implementation
from src.actions.contracts.common import StrictRecord,ref_type
from src.actions.contracts.contractor_supplier_review import SupplierRelationshipReviewJudgment
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY=('Original monthly internal selected-supplier reliability/material availability review for future bids. '
    'Same-run original Supplier A01-A04 and Contractor A05 produce actual supplier selections; only own strictly earlier selections are eligible. '
    'Current native supplier reliability and project material availability are normalized/aggregate indicators, not physical stock, commercial terms or remaining obligations. '
    'Future one-panel inquiry requirements, channels, preparation authority and review thresholds are independent synthetic initial sources. '
    'Original A05 validates the inquiry preparation; the monthly judgment chooses actual review targets. '
    'No inquiry is sent, no supplier consent, order, contract amendment, reservation, spending or physical reliability improvement is inferred.')


class SupplierReviewPlan(ProfessionalMonthlyPlan):
    role:Literal['Contractor']
    observation_ref:ref_type('SupplierRelationshipReviewObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice']!='request_quote':
        raise TaskConflict('Supplier review requires original completed A05 inquiry preparation')
    return SupplierRelationshipReviewJudgment.model_validate_json(saved['result']['payload']['note'])


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    row,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(row[k] is not None for k in ('native_free_ratio','selected_relationships','prior_own_outcomes')):
        raise TaskConflict('Supplier review observations must be unbound until the actual native call')
    row.update(native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        selected_relationships=deepcopy(observed['selected_relationships']),prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class ContractorSupplierReviewApplication(ProfessionalMonthlyApplication):
    VERSION='contractor-monthly-supplier-review.v1'
    PREFIX='contractor_supplier_review_request:'
    COMPONENTS={'Contractor':(ContractorPlanningActionAssembler,ContractorPlanningResultWorker)}
    OPERATIONS={'Contractor':'maintain_supplier_relationship'}
    PLAN_TYPE=SupplierReviewPlan
    INPUT_SCHEMA='contractor-supplier-review-input.v1'
    COMPLETED_CHOICES={'request_quote'}
    ACTION_NUMBER='A05'
    SCOPE_KEY='native_contractor_supplier_review_scope'
    LABEL='Original internal selected-supplier review for future bids'

    def __init__(self,*,supplier,settings):
        self.supplier=supplier
        super().__init__(assembly=supplier.assembly,settings=settings,authority=supplier.authority,install=False)

    def participates(self,saved):return result_judgment(saved).participate
    def result_note(self,saved):return result_judgment(saved).interpretation

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            saved=checked_result(self.workers['Contractor'],TaskIdentity(**h['micro_identity']));j=result_judgment(saved)
            event,=[e for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memories=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if len(memories)!=1 or memories[0]['label']!=event.data['label']:
                raise TaskConflict('Supplier review lost its exact original monthly memory')
            h.update(review=j.model_dump(mode='json'),original_native_memory=deepcopy(memories[0]))
        expected={r['scope']['tick'] for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick}
        if expected!={h['tick'] for h in history}:raise TaskConflict('Earlier supplier review lacks actual native execution')
        return sorted(history,key=lambda h:h['tick'])

    def sources(self,plan,request):
        from gba_construction_sim.backend.agents.contracts import identity_from_profile
        scope=self.scope(request,purpose='propose');engine=self.assembly.engine;org=plan.organization_id;profile=engine.agents[org]
        selected=prior_contractor_supply_selections(self.assembly,organization_id=org,tick=plan.tick,
            read_guard=self.read_guard,query_original=self.supplier.contractor.query_native_outcome)
        relationships=[];basis=plan.native_evidence_ref.model_dump(mode='json')
        for selection in selected:
            supplier=engine.agents[selection['supplier_id']];project=engine.projects[selection['project_id']]
            if supplier.role!='Supplier' or project.selected_contractor_id!=org or selection['supplier_id'] not in project.selected_supplier_ids:
                raise TaskConflict('Earlier own selected supplier no longer matches current original project')
            public=identity_from_profile(supplier)
            relationships.append({'selection':selection,
                'native_reliability':{'value':str(public.capabilities['supply_reliability']),'unit':'ratio','basis_ref':basis},
                'native_material_availability':{'value':str(project.performance.material_availability),'unit':'ratio','basis_ref':basis}})
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),
            'native_profile':{'free_ratio':profile.available_resource()/profile.total_resource_capacity},
            'selected_relationships':relationships,'prior_own_monthly_outcomes':self.history(org,plan.tick)}
        return bind_sources(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=BOUNDARY;return result


class SupplierReviewCompositionSettings(StrictRecord):
    supplier:SupplierOrderNativeSettings
    monthly:ProfessionalMonthlySettings


class SupplierReviewComposition:
    VERSION='procurement-contractor-supplier-review-composition.v1'

    def __init__(self,*,assembly,settings):
        self.assembly=assembly;self.settings=SupplierReviewCompositionSettings.model_validate(settings).model_copy(deep=True)
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self.supplier=SupplierOrderNativeApplication(assembly=assembly,settings=self.settings.supplier,install=False)
        try:
            if self.supplier.contractor is None:raise TaskConflict('Supplier review requires actual original micro Contractor procurement')
            self.monthly=ContractorSupplierReviewApplication(supplier=self.supplier,settings=self.settings.monthly)
            self.authority=self.supplier.authority;self.read_guard=self.authority.read_guard;client=assembly.client
            with client._lock:
                for (role,operation),handler in self.bindings().items():
                    client.bind_proposal_handler(role=role,operation=operation,handler=handler,client_version=self.VERSION+':'+role+':'+operation)
                client.decision_handler=self.decide
                self.supplier.seal_client_binding();self.monthly.seal_client_binding();self._implementation=module_client_implementation(client)
            self.check()
        except Exception:
            self.authority.close() if hasattr(self,'authority') else self.supplier.authority.close()
            raise

    def bindings(self):return {**self.supplier.proposal_bindings(),**self.monthly.proposal_bindings()}

    def check(self):
        client=self.assembly.client
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.monthly.supplier is not self.supplier or self.monthly.authority is not self.supplier.authority
                or self.authority is not self.supplier.authority or self.read_guard!=self.authority.read_guard
                or self.monthly._other_decision!=self.supplier._other_decision
                or module_client_implementation(client)!=self._implementation or client.decision_handler!=self.decide
                or any(client.proposal_handlers.get(k)!=v for k,v in self.bindings().items())):
            raise TaskConflict('Supplier review composition lost its sealed shared original runtime')
        self.supplier._check();self.monthly.check()

    def decide(self,request):
        self.check()
        if request.agent.role=='Contractor' and request.decision_type=='monthly_enterprise_operation':return self.monthly.decide(request)
        return self.supplier.decide(request)

    def evidence(self):
        with self.read_guard():
            self.check();return {'version':self.VERSION,'supplier':self.supplier.evidence(),'monthly':self.monthly.evidence(),'boundary':BOUNDARY}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Supplier relationship scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=SupplierReviewComposition(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
