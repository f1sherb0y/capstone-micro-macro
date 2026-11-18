"""Original OWN-A16 drafts, native monthly preparation, then actual prior comparison."""
from copy import deepcopy
from typing import Literal
from pydantic import Field

from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from integration.owner_proposal_actions import OwnerProposalActionAssembler
from integration.owner_proposal_results import OwnerProposalResultWorker
from integration.professional_monthly_native import ProfessionalMonthlyApplication
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Bounded private scope research for an actual current own native project. Actual simulation-global demand is an independently authorized research gate, not a regional survey, money or physical scale. Initial case, use/scale bounds, review cash and management budget are independently declared synthetic private inputs. Original A16 drafts do not register a formal scope, acquire rights, spend cash or commit work. Only confirmed earlier own native prepare_project_scope execution makes its actual original A16 brief available to the next original A16 revision comparison. Unchanged content returns no_proposal; no duplicate preparation is forced. Rights uncertainty remains unresolved.'


def current_comparison_brief(brief,*,original_issues,current_objects):
    """Translate case-version links only when the same unresolved issue is unchanged.

    Keep the exact old payload in history. This current comparison view changes
    no scale, purpose, delivery, rights or issue content, and cannot hide a
    changed status/check or a different physical case.
    """
    result=deepcopy(brief)
    for index,reference in enumerate(result['unresolved_refs']):
        old,=[r['projection'] for r in original_issues if r['ref']==reference]
        row,=[r for r in current_objects if r['ref']['kind']==reference['kind'] and r['ref']['id']==reference['id']]
        new=row['value']
        def semantic(value):
            value=deepcopy(value)
            value['ref'].pop('version');value['case_ref'].pop('version')
            return value
        if semantic(old)!=semantic(new):raise TaskConflict('Historical issue changed substantive content or original case')
        result['unresolved_refs'][index]=deepcopy(row['ref'])
    return result


class MonthlyOwnerScopePlan(StrictRecord):
    organization_id:TextId
    role:Literal['Owner']
    project_id:TextId
    tick:int=Field(ge=1,le=2)
    context:ActionContext
    action_input:dict
    objects:list[dict]
    native_evidence_ref:ref_type('Evidence')
    signal_ref:ref_type('DemandObservation')
    prior_brief_ref:ref_type('OwnerBrief')
    prior_template:dict
    continuation_policy:Literal['compare_same_case_only_after_actual_own_preparation']


def bind_sources(plan,observed):
    objects=deepcopy(plan.objects);native=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,native,observed)
    signal,=[r['value'] for r in objects if r['ref']==plan.signal_ref.model_dump(mode='json')]
    if signal['measure'] is not None:raise TaskConflict('Current actual global research signal must be initially unbound')
    signal['measure']={'state':'known','value':{'value':str(observed['macro_environment']['market_demand_index']),'unit':'index','basis_ref':native}}
    case,=[r['value'] for r in objects if r['ref']==plan.action_input['case_ref']]
    space,=[r['value'] for r in objects if r['ref']==plan.action_input['candidate_space_ref']]
    candidate,=[r['value'] for r in objects if r['ref']['kind']=='ProposalCandidate']
    if case['prior_brief_refs'] or candidate['prior_brief_ref'] is not None or space['mode']!='propose':
        raise TaskConflict('Previous brief or revision must not be prefilled')
    prior=[h for h in observed['prior_own_monthly_outcomes'] if h['participated']]
    if len(prior)>1:raise TaskConflict('Fixed private scope chain expects at most one confirmed earlier preparation')
    if prior:
        h=prior[0];identity=h['micro_identity'];briefs=h['original_payload'].get('briefs',[])
        if (h['operation']!='prepare_project_scope' or identity['organization_id']!=plan.organization_id or identity['action_id']!='OWN-A16'
                or not 0<h['tick']<plan.tick or len(briefs)!=1 or h['original_payload']['choice']!='propose'
                or h['case_ref']['kind']!='OwnerCase' or h['case_ref']['id']!=case['ref']['id']):
            raise TaskConflict('Current private case cannot borrow a foreign, unexecuted or different-case brief')
        prior_view=deepcopy(plan.prior_template)
        if prior_view['brief'] is not None:raise TaskConflict('Prior content must come only from the actual original result')
        prior_view['brief']=current_comparison_brief(briefs[0],original_issues=h['original_issues'],current_objects=objects)
        prior_view['evidence_refs']=[native]
        objects.append({'ref':plan.prior_brief_ref.model_dump(mode='json'),'value':prior_view})
        case['prior_brief_refs']=[plan.prior_brief_ref.model_dump(mode='json')]
        candidate['prior_brief_ref']=plan.prior_brief_ref.model_dump(mode='json');space['mode']='revise'
    return objects


class OwnerMonthlyScopeApplication(ProfessionalMonthlyApplication):
    VERSION='owner-monthly-private-scope.v1'
    PREFIX='owner_monthly_scope_request:'
    COMPONENTS={'Owner':(OwnerProposalActionAssembler,OwnerProposalResultWorker)}
    PLAN_TYPE=MonthlyOwnerScopePlan
    INPUT_SCHEMA='owner-monthly-scope-input.v1'
    OPERATIONS={'Owner':'prepare_project_scope'}
    COMPLETED_CHOICES={'propose','revise','no_proposal'}
    SCOPE_KEY='native_owner_monthly_scope'
    LABEL='Original Owner private scope research'

    def action_id(self,role):
        if role!='Owner':raise TaskConflict('Owner scope cannot replace another role')
        return 'OWN-A16'
    def participates(self,saved):return saved['result']['payload']['choice'] in {'propose','revise'}
    def result_note(self,saved):return saved['result']['payload']['note']+' Private research only; formal project scope, rights and expenditure remain unexecuted.'

    def history(self,org,tick):
        history=super().history(org,tick)
        for h in history:
            identity=TaskIdentity(**h['micro_identity']);saved=checked_result(self.workers['Owner'],identity)
            h['original_payload']=deepcopy(saved['result']['payload'])
            h['case_ref']=deepcopy(self.snapshots.get(identity)['action_input']['case_ref'])
            h['original_issues']=[deepcopy(r) for r in saved['source_reading'] if r['ref']['kind']=='Issue']
        return history

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');project=self.assembly.engine.projects.get(plan.project_id)
        case,=[r['value'] for r in plan.objects if r['ref']==plan.action_input['case_ref']]
        if (project is None or project.owner_id!=plan.organization_id or project.region!=case['region_id']
                or project.project_type!='building' or not project.project_id==plan.project_id):
            raise TaskConflict('Private scope mandate lacks its actual current own original project')
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),
            'actual_own_project':{'project_id':project.project_id,'owner_id':project.owner_id,'region':project.region,'project_type':project.project_type},
            'prior_own_monthly_outcomes':self.history(plan.organization_id,plan.tick),'continuation_policy':plan.continuation_policy,'boundary':BOUNDARY}
        return bind_sources(plan,observed),observed

    def evidence(self):return {**super().evidence(),'boundary':BOUNDARY}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Owner scope development requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerMonthlyScopeApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
