"""Independent own-risk speculative requirement; no physical or counterparty state is fabricated."""
from copy import deepcopy
from pathlib import Path
from integration.supplier_monthly_development import build_bundle as foundation
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.supplier_monthly_reliability import ReliabilityPlan
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from integration.contractor_tender_development import _write,_write_launch_files,ref,known
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import ActionContext,Reference
from src.actions.contracts.domain import CandidateSet
from src.actions.registry import ActionRegistry
from src.actions.processors import register_representative_processors


def build_bundle(directory,*,run_id,supply_reliability,ticks=2):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'screening-foundation';foundation(base,run_id=run_id,ticks=ticks)
    authority=read(base/'assembly-host.json')['settings']['authority'];seeds=read(base/'supplier-monthly-input.json')['plans'];plans=[];grants=[]
    contract=register_representative_processors(ActionRegistry()).get('SUPPLIER-A05').contract
    for seed in seeds:
        org,tick=seed['organization_id'],seed['tick'];tag=org+'-backup-review-'+str(tick);rr=lambda kind:ref(kind,tag)
        context=deepcopy(seed['context']);context.update(contract_ref=ref('ActionContract','SUPPLIER-A05'),operation_id=tag,
            task_ref=rr('DecisionTask'),candidate_set_ref=rr('CandidateSet'),read_token=tag+'-read')
        scope=deepcopy(context['scope']);now=context['business_time']
        objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] in {'Evidence','ClockProfile','FunctionAssignment','Organization','Authorization'}]
        grant=deepcopy(next(r for r in authority['organization_snapshot']['authorizations'] if r['ref']==context['authorization_refs'][0]))
        owner=next(o for o in authority['organization_snapshot']['organizations'] if o['organization_id']==org)
        assignment=deepcopy(next(a for a in owner['assignments'] if a['function_ref']==context['function_ref']))
        objects.extend([{'ref':grant['ref'],'value':grant},{'ref':context['function_ref'],'value':assignment}])
        window=grant['validity']
        basis=next(r['value']['basis_refs'][0] for r in objects if r['ref']==context['function_ref'])
        native=seed['native_evidence_ref'];auth=context['authorization_refs'][0]
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
        work,profile,stocking,requirement,product,product_requirement,inventory,capacity,policy,observation=map(rr,[
            'SupplyWorkAuthorization','SupplyPlanningProfile','StockingAuthority','SupplyRequirement','ProductSpecification','Requirement',
            'InventorySnapshot','SupplierCapacity','SupplyReliabilityPolicy','SupplyReliabilityObservation'])
        meta={'scope':scope,'available_at':now,'effective_window':window,'evidence_refs':[basis]}
        forecast_line={'product_ref':product,'destination_scope_ref':scope,'quantity':{'value':'6','unit':'panel','basis_ref':basis},
            'requirement_refs':[product_requirement],'deviation_refs':[]}
        add(product,{**meta,'quantity_unit':'panel'})
        add(product_requirement,{**meta,'product_refs':[product],'offer_ref':None,'satisfied':known(True)})
        add(requirement,{**meta,'work_authority_ref':work,'purpose':'order_output','target':forecast_line,'permitted':known(True),'order_line_ref':None})
        add(stocking,{**meta,'organization_id':org,'authority_ref':auth,'permitted':known(True),'risk_bearer_id':org,'requirement_refs':[requirement]})
        add(work,{**meta,'organization_id':org,'permitted':known(True),'order_ref':None,'speculative_authority_ref':stocking,
            'profile_ref':profile,'permitted_modes':['purchase'],'requirement_refs':[requirement],'design_refs':[],'method_refs':[],'order_line_refs':[]})
        add(profile,{**meta,'work_authority_ref':work,'organization_id':org,'actor_id':context['actor_id'],'function_ref':context['function_ref'],
            'authority_ref':auth,'choice':'request_quote','plan_ref':None,'prior_plan_ref':None,'supplier_ids':['declared-upstream-backup-a','declared-upstream-backup-b'],
            'required_lines':[forecast_line],'offer_ref':None,'offer_line_keys':[],'procurement_authority_ref':None,'affected_line_refs':[],'proposed_window_ref':None,
            'note':'Independently authorized own-risk speculative inquiry candidate only; no sent request or actual upstream agreement.',
            'monthly_reliability_policy_ref':policy,'monthly_reliability_observation_ref':observation})
        add(inventory,{'organization_id':org,'as_of':now,'coverage':'unknown','lots':[],'evidence_refs':[basis]})
        add(capacity,{'organization_id':org,'as_of':now,'resource_coverage':'unknown','commitment_coverage':'unknown','resources':[],'commitments':[],'evidence_refs':[basis]})
        measure=lambda value,unit:{'value':value,'unit':unit,'basis_ref':basis}
        add(policy,{'organization_id':org,'scope':scope,'authority_ref':auth,'effective_window':window,
            'target_native_reliability':measure('0.8','native_reliability_index'),'minimum_shortfall':measure('0.05','native_reliability_index'),
            'minimum_free_ratio':measure('0.2','ratio'),'maximum_prior_reviews':1,'purpose':'private_own_risk_backup_sourcing_review','evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':scope,'as_of':now,'native_reliability':None,'native_free_ratio':None,
            'prior_own_outcomes':None,'evidence_refs':[native]})
        for r in objects:
            if r['ref']==native:r['value'].update(locator='actual-current-own-native-reliability-and-earlier-confirmed-backup-reviews',content_hash=None)
        candidate={'operation_id':tag,'scope':scope,'as_of':now,'candidates':[{'ref':work,'permitted_choices':['request_quote']}],'search_profile_ref':rr('Profile')}
        objects.append({'ref':context['candidate_set_ref'],'value':candidate})
        grant.update(action_ids=['SUPPLIER-A05'],readable_refs=[r['ref'] for r in objects]);context['visible_refs']=deepcopy(grant['readable_refs']);grants.append(deepcopy(grant))
        CandidateSet.model_validate(candidate).check_context(ActionContext.model_validate(context),contract.choices)
        action_input={'scope_ref':scope,'work_authority_ref':work,'requirement_refs':[requirement],'design_refs':[],
            'inventory_ref':inventory,'upstream_offer_refs':[],'capacity_ref':capacity,'method_refs':[]}
        contract.validate_input(action_input)
        action_input.pop('scope_ref')  # Original assembler supplies context.scope itself.
        for r in objects:
            value=deepcopy(r['value'])
            if r['ref']==native:value['content_hash']='0'*64
            if r['ref']==observation:value.update(native_reliability=measure('0','native_reliability_index'),native_free_ratio=measure('1','ratio'),prior_own_outcomes=[])
            SupplierPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),value)
        plans.append(ReliabilityPlan.model_validate({'organization_id':org,'role':'Supplier','tick':tick,'context':context,
            'action_input':action_input,'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    authority['organization_snapshot']['authorizations']=grants
    sources=_write(directory,'reliability-input.json',{'schema_version':'supplier-monthly-reliability-input.v1','run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',read(base/'native-host.json'))
    macro=read(base/'macro-request.json')
    for a in macro['agents']:
        if a['role']=='Supplier':a['supply_reliability']=supply_reliability
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.supplier_monthly_reliability:configure_assembly',readme_override=__doc__)
