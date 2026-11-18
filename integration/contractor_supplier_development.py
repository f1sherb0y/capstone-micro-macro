"""Fixed original procurement with independent future inquiry-preparation inputs."""
from copy import deepcopy
from pathlib import Path
from integration.supplier_order_native_development import build_bundle as foundation
from integration.contractor_supplier_review import SupplierReviewPlan,SupplierReviewCompositionSettings
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_tender_development import _write,_write_launch_files,known,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,supply_reliability):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'procurement-foundation'
    foundation(base,run_id=run_id,with_quote=True,with_product=True,with_screening=True,with_contractor=True,
        clock_id='supplier-review-monthly-clock')
    supplier=read(base/'assembly-host.json')['settings'];authority=supplier['authority'];snapshot=authority['organization_snapshot']
    seed=read(base/'contractor-supply-input.json')['plans'][0];org=seed['organization_id'];plans=[]
    owner=next(o for o in snapshot['organizations'] if o['organization_id']==org);assignment=deepcopy(owner['assignments'][0])
    common=owner['evidence_refs'][0];common_value=next(r['value'] for r in seed['objects'] if r['ref']==common)
    window=common_value['effective_window'];point=lambda n:{**window['start'],'offset':n}
    supplier_ids=[o['organization_id'] for o in snapshot['organizations'] if o['assignments'][0]['role']=='Supplier']
    for tick in (1,2,3):
        tag=org+'-supplier-review-'+str(tick);rr=lambda kind:ref(kind,tag);now=point(tick)
        scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
        work,profile,capacity,requirement,product,location,inspection,payment,delivery,receiving,basis,native,policy,observation,auth=map(rr,[
            'WorkAuthorization','WorkPlanningProfile','ContractorCapacity','SupplyRequirement','ProductSpecification','Location',
            'InspectionRule','PaymentRule','TimeWindow','TimeWindow','Evidence','Evidence','SupplierRelationshipReviewPolicy',
            'SupplierRelationshipReviewObservation','Authorization'])
        # Distinct references for same-kind independent source objects.
        receiving=ref('TimeWindow',tag+'-receiving');native=ref('Evidence',tag+'-actual-native')
        objects=[{'ref':common,'value':deepcopy(common_value)},{'ref':scope['ref'],'value':{'ref':scope['ref'],'evidence_refs':[common]}},
            {'ref':assignment['function_ref'],'value':deepcopy(assignment)}]
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
        assumed={'organization_id':org,'purpose':'private_future_bid_supplier_availability_review','forecast_panels':1,
            'candidate_channels':supplier_ids,'minimum_reliability':'0.7','minimum_availability':'0.3','minimum_free_ratio':'0.2',
            'interpretation':'Independent future inquiry preparation and own internal review; no sent contact or existing remaining obligation.'}
        add(basis,{'source_kind':'synthetic','basis_kind':'assumed','locator':'independent-initial-contractor-future-inquiry-authority-requirement-channels-and-review-policy',
            'content_hash':task_digest(assumed),'effective_window':window})
        add(native,{'source_kind':'synthetic','basis_kind':'observed','locator':'actual-own-native-selection-events-current-public-reliability-project-availability-and-confirmed-reviews',
            'content_hash':None,'effective_window':window})
        meta={'scope':scope,'available_at':point(0),'effective_window':window,'evidence_refs':[basis]}
        add(work,{**meta,'organization_id':org,'mandate_kind':'preparation','effective':known(True),'planning_profile_ref':profile,
            'allowed_task_purposes':['preparation'],'allow_quote':known(True),'allow_supply_acceptance':known(False),
            'procurement_limit':{'state':'unknown','reason_code':'no_purchase_authority','missing_refs':[]},
            'procurement_used':{'state':'unknown','reason_code':'no_contract_ledger','missing_refs':[]},'procurement_history_refs':[],
            'procurement_history_complete':False,'region_id':'Hong Kong','object_type':'building','work_type':'factory_supply',
            'special_condition_codes':[],'required_qualification_codes':[],'dependency_refs':[],'design_refs':[],'method_refs':[]})
        channels=[ref('SupplySupplier',tag+'-'+sid) for sid in supplier_ids]
        add(profile,{**meta,'mandate_ref':work,'organization_id':org,'authority_ref':auth,'choice':'request_quote','plan_ref':None,
            'prior_plan_ref':None,'requirement_refs':[requirement],'supplier_refs':channels,'selected_offer_ref':None,
            'receiving_window_ref':receiving,'procurement_authority_ref':None,'note':'Independently authorized future inquiry preparation only.',
            'monthly_supplier_policy_ref':policy,'monthly_supplier_observation_ref':observation})
        add(capacity,{**meta,'organization_id':org,'as_of':now,'coverage':'unknown','resources':[],'commitments':[],
            'qualification_refs':[],'qualification_coverage':'unknown'})
        for identity in (delivery,receiving):objects.append({'ref':identity,'value':{'start':point(10),'end':point(11),'bounds':'closed_open'}})
        add(requirement,{**meta,'mandate_ref':work,'product_ref':product,'quantity':{'value':'1','unit':'panel','basis_ref':basis},
            'delivery_window_ref':delivery,'receiving_window_ref':receiving,'destination_ref':location,'inspection_rule_ref':inspection,
            'payment_rule_ref':payment,'allowed_supplier_ids':supplier_ids,'substitution_authority_ref':None})
        for identity in (product,location,inspection,payment):
            add(identity,{**meta,'requirement_refs':[requirement],'offer_ref':None,'terms_ref':None,'permitted':known(True)})
        for sid,identity in zip(supplier_ids,channels):
            add(identity,{**meta,'organization_id':sid,'accepts_inquiries':known(True),'requirement_refs':[requirement]})
        measure=lambda v:{'value':v,'unit':'ratio','basis_ref':basis}
        add(policy,{'organization_id':org,'scope':scope,'authority_ref':auth,'effective_window':window,
            'minimum_reliability':measure('0.7'),'minimum_availability':measure('0.3'),'minimum_free_ratio':measure('0.2'),
            'purpose':assumed['purpose'],'evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':scope,'as_of':now,'native_free_ratio':None,
            'selected_relationships':None,'prior_own_outcomes':None,'evidence_refs':[native]})
        candidate=rr('CandidateSet');objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':now,
            'candidates':[{'ref':work,'permitted_choices':['request_quote']}],'search_profile_ref':rr('Profile')}})
        grant={'ref':auth,'organization_id':org,'actor_id':owner['actor_id'],'function_ref':assignment['function_ref'],
            'action_ids':['CONTRACTOR-A05'],'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[common],'validity':window}
        objects.append({'ref':auth,'value':grant});grant['readable_refs']=[r['ref'] for r in objects];snapshot['authorizations'].append(deepcopy(grant))
        context={'run_id':run_id,'actor_id':owner['actor_id'],'function_ref':assignment['function_ref'],'authorization_refs':[auth],
            'operation_id':tag,'contract_ref':ref('ActionContract','CONTRACTOR-A05'),'task_ref':rr('DecisionTask'),'scope':scope,
            'business_time':now,'read_token':tag+'-read','visible_refs':deepcopy(grant['readable_refs']),'candidate_set_ref':candidate,'execution_mode':'rule'}
        inputs={'work_basis':{'kind':'preparation','authorization_ref':work},'authorized_scope_ref':scope,'dependency_refs':[],
            'design_refs':[],'capacity_ref':capacity,'supplier_offer_refs':[],'work_method_refs':[]}
        for r in objects:
            value=deepcopy(r['value'])
            if r['ref']==native:value['content_hash']='0'*64
            if r['ref']==observation:value.update(native_free_ratio=measure('1'),selected_relationships=[],prior_own_outcomes=[])
            ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(r['ref']),value)
        plans.append(SupplierReviewPlan.model_validate({'organization_id':org,'role':'Contractor','tick':tick,'context':context,
            'action_input':inputs,'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    sources=_write(directory,'supplier-review-input.json',{'schema_version':'contractor-supplier-review-input.v1','run_id':run_id,'plans':plans})
    settings=SupplierReviewCompositionSettings.model_validate({'supplier':supplier,'monthly':{'authority':authority,**sources}})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    native=read(base/'native-host.json')
    native['settings']['native_proposals']=[r for r in native['settings']['native_proposals'] if r['role']!='Contractor']
    native['settings']['native_decisions']=[r for r in native['settings']['native_decisions'] if r['role']!='Contractor']
    _write(directory,'native-host.json',native)
    request=read(base/'macro-request.json');request['ticks']=3
    for agent in request['agents']:
        if agent['role']=='Supplier':agent['supply_reliability']=supply_reliability
    _write(directory,'macro-request.json',request)
    _write_launch_files(directory,assembly_hook='integration.contractor_supplier_review:configure_assembly',readme_override=__doc__)
