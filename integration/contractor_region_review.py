"""Original A01 regional eligibility -> native monthly review -> own later A01."""
from copy import deepcopy
from typing import Literal
from integration.professional_monthly_native import ProfessionalMonthlyApplication,ProfessionalMonthlyPlan
from integration.contractor_screening_actions import ContractorScreeningActionAssembler
from integration.contractor_screening_results import ContractorScreeningResultWorker
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ref_type
from src.actions.contracts.contractor_region_review import RegionEntryReviewJudgment
from src.coordination.tasks import TaskIdentity,TaskConflict,task_digest

BOUNDARY=('Original monthly preliminary regional qualification and public local-partner review only. '
    'Target-region package, qualifications, physical crew, existing commitment and public partner disclosures are independently declared synthetic initial inputs. '
    'Native regional friction and free ratio are actual request observations, never inferred physical capacity. '
    'Public candidate listing is not available committed capacity or counterparty consent. Formal entry clearance and consent remain unknown; '
    'no market entry, JV, contact delivery, bid submission, resource reservation, spending or capability improvement is inferred.')


class RegionReviewPlan(ProfessionalMonthlyPlan):
    role:Literal['Contractor']
    observation_ref:ref_type('RegionEntryReviewObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice'] not in {'participate','decline'}:
        raise TaskConflict('Regional review requires original completed A01 eligibility judgment')
    j=RegionEntryReviewJudgment.model_validate_json(saved['result']['payload']['note'])
    if j.screening_choice!=saved['result']['payload']['choice']:raise TaskConflict('Regional review replaces original A01 eligibility')
    return j


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
    observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
    if any(observation[k] is not None for k in ('native_home_region','native_friction','native_free_ratio','prior_own_outcomes')):
        raise TaskConflict('Regional observation must remain unbound until actual native request')
    observation.update(native_home_region=observed['native_profile']['home_region'],
        native_friction={'value':str(observed['native_friction']),'unit':'ratio','basis_ref':basis},
        native_free_ratio={'value':str(observed['native_profile']['free_ratio']),'unit':'ratio','basis_ref':basis},
        prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']))
    return objects


class ContractorRegionReviewApplication(ProfessionalMonthlyApplication):
    VERSION='contractor-monthly-region-review.v1'
    PREFIX='contractor_region_review_request:'
    COMPONENTS={'Contractor':(ContractorScreeningActionAssembler,ContractorScreeningResultWorker)}
    OPERATIONS={'Contractor':'evaluate_region_entry'}
    PLAN_TYPE=RegionReviewPlan
    INPUT_SCHEMA='contractor-region-review-input.v1'
    COMPLETED_CHOICES={'participate','decline'}
    SCOPE_KEY='native_contractor_region_review_scope'
    LABEL='Original preliminary regional qualification and public partner review'
    POLICY_KIND='RegionEntryReviewPolicy'
    RESULT_JUDGMENT=staticmethod(result_judgment)
    BIND_SOURCES=staticmethod(bind_sources)
    BOUNDARY=BOUNDARY

    def participates(self,saved):return self.RESULT_JUDGMENT(saved).participate
    def result_note(self,saved):return self.RESULT_JUDGMENT(saved).interpretation

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            saved=checked_result(self.workers['Contractor'],TaskIdentity(**h['micro_identity']));j=self.RESULT_JUDGMENT(saved)
            event,=[e for e in self.assembly.engine.events.events if e.event_id==h['event_id']]
            memory=[m for m in self.assembly.engine.agents[org].episodic_memory if m.get('tick')==h['tick'] and m.get('operation')==h['operation']]
            if len(memory)!=1 or memory[0]['label']!=event.data['label'] or memory[0]['capability_update']!=event.data.get('capability_update'):
                raise TaskConflict('Earlier region assessment lost its exact native memory')
            h.update(review=j.model_dump(mode='json'),assessment=deepcopy(j.assessment),original_native_memory=deepcopy(memory[0]))
        expected={r['scope']['tick'] for r in self.records() if r['scope']['organization_id']==org and r['scope']['tick']<tick}
        if expected!={h['tick'] for h in history}:raise TaskConflict('Earlier region review has no confirmed original monthly execution')
        return sorted(history,key=lambda h:h['tick'])

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');agent=self.assembly.engine.agents[plan.organization_id]
        policy,=[r['value'] for r in plan.objects if r['ref']['kind']==self.POLICY_KIND]
        environment=deepcopy(request.inputs['macro_environment']);matrix=environment['regional_friction_matrix']
        if agent.region!=policy['home_region'] or policy['target_region'] not in matrix.get(agent.region,{}):
            raise TaskConflict('Native current region/friction source missing; no default zero or invented target')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),'macro_environment':environment,
            'native_friction':matrix[agent.region][policy['target_region']],
            'native_profile':{'home_region':agent.region,'available_resource':agent.available_resource(),
                'total_resource_capacity':agent.total_resource_capacity,'free_ratio':agent.available_resource()/agent.total_resource_capacity},
            'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick)}
        return self.BIND_SOURCES(plan,observed),observed

    def evidence(self):
        result=super().evidence();result['boundary']=self.BOUNDARY;return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Regional review scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ContractorRegionReviewApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
