"""Explicit optional A03 sources for the existing independent A04 agreement."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.supplier_quote_actions import SupplierQuoteActionAssembler
from src.actions.contracts.common import Reference


def extend_quote_plan(plan,*,grants,factory_unit_cost='80'):
    plan=deepcopy(plan);objects=plan['objects'];context=plan['context'];org=plan['organization_id']
    tag=context['operation_id']+'-quote';rr=lambda kind,name:ref(kind,tag+'-'+name)
    find=lambda reference:next(r['value'] for r in objects if r['ref']==reference)
    offer=find(plan['action_input']['offer_ref']);proposal=find(plan['action_input']['order_proposal_ref'])
    profile=find(plan['action_input']['formation_profile_ref']);full=find(profile['full_plan_ref'])
    basis=profile['evidence_refs'][0];now=context['business_time'];window=profile['effective_window'];scope=context['scope']
    # Preserve the independent existing offer, proposal and exact buyer terms.
    # The original pricing method must compute and match the supplied price.
    retained={'Evidence','Project','ProductSpecification','InventorySnapshot','SupplierCapacity',
        'Location','DeliveryService','ResourcePool','TimeWindow'}
    quote_objects=[deepcopy(r) for r in objects if r['ref']['kind'] in retained and r['ref']!=plan['native_evidence_ref']]
    native=rr('Evidence','actual-native-request');handoff=rr('Evidence','actual-quote-handoff')
    for target,locator in [(native,'actual-native-supplier-quote-preparation'),(handoff,'actual-private-quote-to-independent-order-check')]:
        row={'ref':target,'value':{'ref':target,'source_kind':'synthetic','basis_kind':'observed','locator':locator,
            'content_hash':None,'effective_window':window}}
        (quote_objects if target==native else objects).append(row)
    offer['evidence_refs'].append(handoff)
    own_grant=find(context['authorization_refs'][0]);own_grant['readable_refs'].append(handoff)
    context['visible_refs'].append(handoff)
    next(g for g in grants if g['ref']==own_grant['ref'])['readable_refs'].append(handoff)
    def add(reference,**value):quote_objects.append({'ref':reference,'value':{'ref':reference,'evidence_refs':[basis],**value}})
    inquiry=rr('SupplyInquiry','received');product_proposal=rr('ProductProposal','confirmed');cost=rr('CostBasis','factory')
    logistics=rr('LogisticsAssessment','stock-delivery');pricing=rr('SupplyPricingProfile','price')
    delivery=deepcopy(offer['lines'][0]['delivery']);product=delivery['product'];requirement=product['requirement_refs'][0]
    production_region=known('Hong Kong');measured=lambda n,unit:{'value':str(n),'unit':unit,'basis_ref':basis}
    money=lambda n:{'value':str(n),'currency':'HKD','basis_ref':basis}
    actual_window=find(delivery['delivery_window_ref'])
    add(inquiry,scope=scope,buyer_id=offer['buyer_id'],recipient_id=org,recipient_organization_id=org,received_at=window['start'],
        response_window=window,status='active',allow_partial_scope=False,clarification_requirement_refs=[],
        payer_id=known(offer['payer_id']),currency=known('HKD'),required_service_codes=known(['factory_supply']),
        lines=[{'requirement_ref':requirement,'scope':scope,'product_code':known('synthetic-panel'),
            'quantity':known(product['quantity']),'production_region_id':production_region,'delivery_region_id':production_region,
            'work_window':known(actual_window),'required_function_codes':known(['factory_supply']),
            'allowed_fulfillment_modes':known(['manufacture','purchase'])}])
    add(requirement,inquiry_ref=inquiry,scope=scope,condition_code='explicit-panel-requirement',product_proposal_ref=product_proposal)
    add(product_proposal,inquiry_ref=inquiry,supplier_organization_id=org,status='confirmed',confirmation_requirement_ref=None,
        prerequisite_refs=[],effective_window=window,available_at=window['start'],lines=[{'local_key':'product-1','product':product}])
    add(cost,supplier_organization_id=org,product_ref=product['product_ref'],destination_scope_ref=scope,quantity_unit='panel',
        service_code='factory_supply',unit_cost=known(money(factory_unit_cost)),per_batch_cost=known(money(0)),effective_window=window,
        available_at=window['start'],purpose='binding_quote')
    add(logistics,supplier_organization_id=org,product_proposal_ref=product_proposal,inquiry_ref=inquiry,
        available_at=window['start'],effective_window=window,feasible=known(True),prerequisite_refs=[],deliveries=[{
            'local_key':'delivery-1','proposal_line_key':'product-1','quantity':product['quantity'],
            'inventory_quantity':product['quantity'],'source_location_ref':full['lines'][0]['source_location_ref'],
            'destination_ref':delivery['destination_ref'],'delivery_window_ref':delivery['delivery_window_ref'],
            'included_service_refs':delivery['included_service_refs'],'cost_basis_refs':[cost],
            'resource_uses':full['lines'][0]['resource_uses']}])
    terms=find(offer['terms_ref'])
    add(offer['terms_ref'],inquiry_ref=inquiry,supplier_organization_id=org,buyer_id=offer['buyer_id'],payer_id=offer['payer_id'],
        currency=terms['currency'],effective_window=terms['effective_window'],payment_rules=terms['payment_rules'],prerequisite_refs=[])
    add(pricing,organization_id=org,effective_window=window,policy='evaluate',algorithm_code='declared_cost_markup_v1',
        price_basis='batch_total_included_services',markup_rate=known('0.25'),minor_places=2,currency=known('HKD'),
        required_service_codes=known(['factory_supply']),terms_ref=offer['terms_ref'],validity_ref=offer['validity_ref'],
        proposal_priorities=[],evidence_refs=[basis,native])
    function=context['function_ref'];quote_objects.append(deepcopy(next(r for r in objects if r['ref']==function)))
    grant=deepcopy(own_grant);grant.update(ref=rr('Authorization','quote'),action_ids=['SUPPLIER-A03'],readable_refs=[])
    quote_objects.append({'ref':grant['ref'],'value':grant});candidate=rr('CandidateSet','products')
    quote_objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':now,
        'candidates':[{'ref':product['product_ref'],'permitted_choices':['quote']}],'search_profile_ref':rr('Profile','explicit-product')}})
    visible=[r['ref'] for r in quote_objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
    quote_context={**deepcopy(context),'operation_id':tag,'contract_ref':ref('ActionContract','SUPPLIER-A03'),
        'task_ref':rr('DecisionTask','quote'),'authorization_refs':[grant['ref']],'read_token':tag+'-read',
        'visible_refs':visible,'candidate_set_ref':candidate}
    inputs={'inquiry_ref':inquiry,'product_proposal_refs':[product_proposal],'cost_basis_refs':[cost],
        'inventory_ref':plan['action_input']['inventory_ref'],'capacity_ref':plan['action_input']['capacity_ref'],
        'logistics_refs':[logistics],'pricing_profile_ref':pricing}
    for row in quote_objects:
        value=deepcopy(row['value'])
        if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
        SupplierQuoteActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
    plan['quote']={'context':quote_context,'action_input':inputs,'objects':quote_objects,
        'native_evidence_ref':native,'handoff_evidence_ref':handoff}
    return plan
