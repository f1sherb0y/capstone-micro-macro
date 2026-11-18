"""Explicit optional A02 catalog constraints and evidence; no design approval."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.supplier_product_actions import SupplierProductActionAssembler
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.coordination.tasks import task_digest


def extend_product_plan(plan,*,grants):
    plan=deepcopy(plan);quote=plan['quote'];context=quote['context'];org=plan['organization_id']
    tag=context['operation_id']+'-product';rr=lambda kind,name:ref(kind,tag+'-'+name)
    find=lambda objects,reference:next(r['value'] for r in objects if r['ref']==reference)
    inquiry=find(quote['objects'],quote['action_input']['inquiry_ref'])
    proposal=find(quote['objects'],quote['action_input']['product_proposal_refs'][0])
    product_ref=proposal['lines'][0]['product']['product_ref'];product=find(quote['objects'],product_ref)
    scope=context['scope'];now=context['business_time'];window=product['effective_window']
    basis=rr('Evidence','explicit-catalog-input');proof=rr('ProductEvidence','catalog-properties')
    fact={'ref':basis,'source_kind':'synthetic','basis_kind':'assumed','locator':'explicit-synthetic-product-catalog-and-requirements',
        'content_hash':task_digest({'product_ref':product_ref,'factory_id':org+'-factory','use':'synthetic-envelope',
            'material':'synthetic-panel-material','no_independent_design_checks_declared':True}), 'effective_window':window}
    # The same independently specified product remains unchanged across all
    # action views. These are assumed catalog properties, not measured tests.
    for objects,c in ((plan['objects'],plan['context']),(quote['objects'],context)):
        objects.append({'ref':basis,'value':deepcopy(fact)})
        value=find(objects,product_ref)
        value['properties']=known([{'kind':'category','property_code':'material','value':'synthetic-panel-material','basis_refs':[basis]}])
        value['product_evidence_refs']=[proof];value['evidence_refs'].append(basis)
        c['visible_refs'].append(basis)
        grant=find(objects,c['authorization_refs'][0]);grant['readable_refs'].append(basis)
        next(g for g in grants if g['ref']==grant['ref'])['readable_refs'].append(basis)
    kept={'Evidence','Project','ProductSpecification'}
    objects=[deepcopy(r) for r in quote['objects'] if r['ref']['kind'] in kept
        and r['ref']!=quote['native_evidence_ref']]
    def add(reference,**value):objects.append({'ref':reference,'value':{'ref':reference,'evidence_refs':[basis],**value}})
    objects.append({'ref':inquiry['ref'],'value':{key:deepcopy(inquiry[key]) for key in SupplyInquiryView.model_fields}})
    requirement=inquiry['lines'][0]['requirement_ref'];method=rr('ProductCompatibilityMethod','catalog-comparison')
    add(requirement,inquiry_ref=inquiry['ref'],scope=scope,intended_use_code=known('synthetic-envelope'),
        allowed_factory_ids=known([org+'-factory']),constraints=known([{'kind':'category','property_code':'material',
            'allowed_values':['synthetic-panel-material'],'basis_refs':[basis]}]),
        substitutable_property_codes=[],allow_product_substitution=False,design_dependencies=[])
    add(proof,product_ref=product_ref,factory_id=org+'-factory',intended_use_code='synthetic-envelope',scope=scope,
        property_codes=['material'],effective_window=window,available_at=window['start'])
    add(method,organization_id=org,effective_window=window,algorithm_code='declared_constraints_v1',
        supported_use_codes=['synthetic-envelope'],supported_factory_ids=[org+'-factory'],supported_property_codes=['material'],
        design_action_ids=[],selection_priorities=[])
    native=rr('Evidence','actual-native-request')
    objects.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
        'locator':'actual-native-supplier-product-preparation','content_hash':None,'effective_window':window}})
    objects.append(deepcopy(next(r for r in quote['objects'] if r['ref']==context['function_ref'])))
    own_grant=find(quote['objects'],context['authorization_refs'][0])
    grant=deepcopy(own_grant);grant.update(ref=rr('Authorization','product'),action_ids=['SUPPLIER-A02'],readable_refs=[])
    objects.append({'ref':grant['ref'],'value':grant});candidate=rr('CandidateSet','catalog-products')
    objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':now,
        'candidates':[{'ref':product_ref,'permitted_choices':['propose_original','propose_substitute']}],
        'search_profile_ref':rr('Profile','explicit-catalog-product')}})
    visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
    product_context={**deepcopy(context),'operation_id':tag,'contract_ref':ref('ActionContract','SUPPLIER-A02'),
        'task_ref':rr('DecisionTask','product'),'authorization_refs':[grant['ref']],'read_token':tag+'-read',
        'visible_refs':visible,'candidate_set_ref':candidate}
    relation=rr('SupplierProductHandoffBasis','actual-product-to-quote');evidence=rr('Evidence','actual-product-handoff')
    quote['objects'].extend([{'ref':relation,'value':None},{'ref':evidence,'value':{'ref':evidence,'source_kind':'synthetic',
        'basis_kind':'observed','locator':'actual-private-product-to-independent-quote-check','content_hash':None,'effective_window':window}}])
    proposal['evidence_refs'].append(evidence)
    for target in (own_grant,next(g for g in grants if g['ref']==own_grant['ref'])):target['readable_refs'].extend([relation,evidence])
    context['visible_refs'].extend([relation,evidence])
    for row in objects:
        value=deepcopy(row['value'])
        if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
        SupplierProductActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
    quote['product']={'context':product_context,'action_input':{'inquiry_ref':inquiry['ref'],'requirement_refs':[requirement],
        'design_refs':[],'product_candidates':[product_ref],'compatibility_method_ref':method,'design_authority_refs':[]},
        'objects':objects,'native_evidence_ref':native,'handoff_basis_ref':relation,'handoff_evidence_ref':evidence}
    return plan
