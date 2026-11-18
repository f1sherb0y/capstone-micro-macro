"""Explicit A01 production capability/capacity sources, separate from delivery pools."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def extend_screening_plan(plan,*,grants):
    plan=deepcopy(plan);product=plan['quote']['product'];context=product['context'];org=plan['organization_id']
    tag=context['operation_id']+'-screening';rr=lambda kind,name:ref(kind,tag+'-'+name)
    find=lambda objects,reference:next(r['value'] for r in objects if r['ref']==reference)
    inquiry=find(product['objects'],product['action_input']['inquiry_ref'])
    scope=context['scope'];now=context['business_time'];window=inquiry['response_window']
    basis=rr('Evidence','explicit-production-input');native=rr('Evidence','actual-native-request')
    # A01 screens independently sourced production capability. It is neither
    # the native normalized allocation nor the A03/A04 delivery pool capacity.
    objects=[deepcopy(r) for r in product['objects'] if r['ref']['kind'] in {'Evidence','Project','SupplyInquiry'}
        and r['ref']!=product['native_evidence_ref']]
    objects.append({'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
        'locator':'explicit-independent-production-capability-and-capacity','content_hash':task_digest({
            'organization_id':org,'production_capacity':'10 production-unit','units_per_capacity_tick':'1 panel',
            'function_authority':'factory_supply','commitments':[],'distinct_from_delivery_pool':True}),'effective_window':window}})
    objects.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
        'locator':'actual-native-supplier-screening','content_hash':None,'effective_window':window}})
    def add(reference,**value):objects.append({'ref':reference,'value':{'ref':reference,'evidence_refs':[basis],**value}})
    capability=rr('SupplierCapability','factory-supply');capacity=rr('SupplierCapacity','production')
    method=rr('WorkMethod','production');profile=rr('SupplyScreeningProfile','respond');authority=rr('Authority','factory-supply')
    add(authority,organization_id=org,actor_id=org,scope=scope,function_codes=['factory_supply'],effective_window=window)
    add(capability,organization_id=org,registration_region_id=known('Hong Kong'),operating_region_ids=known(['Hong Kong']),
        effective_window=window,product_coverage='complete',products=[{'product_code':'synthetic-panel',
            'function_codes':known(['factory_supply']),'production_region_ids':known(['Hong Kong']),
            'delivery_region_ids':known(['Hong Kong']),'method_ref':method}],function_authority_refs=[authority])
    add(capacity,organization_id=org,as_of=now,resource_coverage='complete',commitment_coverage='complete',resources=[{
        'resource_ref':rr('Resource','production-line'),'resource_kind':'production_line','region_id':known('Hong Kong'),
        'total':known({'value':'10','unit':'production-unit','basis_ref':basis}),'effective_window':window}],commitments=[])
    add(method,organization_id=org,product_code='synthetic-panel',fulfillment_mode='manufacture',production_region_id='Hong Kong',
        delivery_region_ids=['Hong Kong'],function_codes=['factory_supply'],effective_window=window,quantity_unit='panel',
        resource_kind='production_line',capacity_unit='production-unit',units_per_capacity_tick='1',
        method='constant_capacity_over_half_open_window_v1')
    add(profile,organization_id=org,effective_window=window,policy='evaluate',allow_limited_scope=False,
        inquiry_priorities=[],evidence_refs=[basis,native])
    for line in inquiry['lines']:
        add(line['requirement_ref'],inquiry_ref=inquiry['ref'],scope=line['scope'],description='Explicit synthetic received panel requirement')
    objects.append(deepcopy(next(r for r in product['objects'] if r['ref']==context['function_ref'])))
    own_grant=find(product['objects'],context['authorization_refs'][0])
    grant=deepcopy(own_grant);grant.update(ref=rr('Authorization','screening'),action_ids=['SUPPLIER-A01'],readable_refs=[])
    objects.append({'ref':grant['ref'],'value':grant});candidate=rr('CandidateSet','received-inquiry')
    objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':now,
        'candidates':[{'ref':inquiry['ref'],'permitted_choices':['respond']}],
        'search_profile_ref':rr('Profile','explicit-received-inquiry')}})
    visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
    screening_context={**deepcopy(context),'operation_id':tag,'contract_ref':ref('ActionContract','SUPPLIER-A01'),
        'task_ref':rr('DecisionTask','screening'),'authorization_refs':[grant['ref']],'read_token':tag+'-read',
        'visible_refs':visible,'candidate_set_ref':candidate}
    relation=rr('SupplierScreeningHandoffBasis','actual-screening-to-product')
    evidence=rr('Evidence','actual-screening-handoff');received=rr('Evidence','actual-received-input-reading')
    additions=[{'ref':relation,'value':None}]
    for target,locator in ((evidence,'actual-private-screening-to-product-check'),
            (received,'observed-read-of-independent-received-inquiry-not-a-macro-receipt')):
        additions.append({'ref':target,'value':{'ref':target,'source_kind':'synthetic','basis_kind':'observed',
            'locator':locator,'content_hash':None,'effective_window':window}})
    product['objects'].extend(additions)
    for reference in product['action_input']['requirement_refs']:
        find(product['objects'],reference)['evidence_refs'].extend([evidence,received])
    for target in (own_grant,next(g for g in grants if g['ref']==own_grant['ref'])):
        target['readable_refs'].extend([relation,evidence,received])
    context['visible_refs'].extend([relation,evidence,received])
    for row in objects:
        value=deepcopy(row['value'])
        if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
        SupplierScreeningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
    product['screening']={'context':screening_context,'action_input':{'inquiry_refs':[inquiry['ref']],'market_refs':[],
        'capability_ref':capability,'capacity_ref':capacity,'screening_profile_ref':profile},'objects':objects,
        'native_evidence_ref':native,'handoff_basis_ref':relation,'handoff_evidence_ref':evidence,'received_evidence_ref':received}
    return plan
