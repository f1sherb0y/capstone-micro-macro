"""Relate independently received A05 terms to actual same-request Supplier results."""
from copy import deepcopy

from integration.bank_financing_private import checked_result, evidence_binding
from integration.supplier_order_native_quote import quote_for_order
from integration.contractor_supply_native_substitution import quoted_substitutions
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def supplier_quote_for_contractor(supplier,*,plan,request,disclosure,objects):
    """Disclose exact commercial evidence only; retain independent signing/permission facts."""
    profile,decision=next((p,d) for p,d in request.inputs['offers'] if p['agent_id']==disclosure.supplier_id)
    scope=decision['factors']['native_supply_scope']
    technical,=[r for r in supplier._records() if r['state']=='formed' and r['scope']==scope
        and r['native_request']['agent']['agent_id']==disclosure.supplier_id]
    if not decision['accepted'] or 'quote' not in technical:
        raise TaskConflict('Contractor procurement requires an accepted actual Supplier quote, not a willingness scalar')
    order=checked_result(supplier.worker,TaskIdentity(**technical['identity']))
    quote=checked_result(supplier.quote_worker,TaskIdentity(**technical['quote']['identity']))
    source_plan=supplier.plan_for_scope(disclosure.supplier_id,scope)
    supplier._authorize_step(source_plan,'order',source_reading=order['source_reading'])
    supplier._authorize_step(source_plan,'quote',source_reading=quote['source_reading'])
    bound=quote_for_order(quote,invocation=supplier.snapshots.get(TaskIdentity(**quote['identity'])),
        step=source_plan.quote,plan=source_plan,objects=deepcopy(source_plan.objects))
    if (order['result']['payload']['choice']!='accept' or quote['result']['payload']['choice']!='quote'
            or technical['result_sha256']!=order['result_sha256']
            or technical['quote']['result_sha256']!=quote['result_sha256'] or technical['observed']['quote']!=bound
            or decision['data'].get('micro_task_key')!=TaskIdentity(**order['identity']).key
            or decision['data'].get('micro_result_sha256')!=order['result_sha256']
            or decision['data'].get('proposal_response_sha256')!=technical['proposal_response_sha256']):
        raise TaskConflict('Contractor disclosure changes the actual original Supplier quote or confirmed acceptance')
    get=lambda reference:next(r['value'] for r in objects if r['ref']==reference)
    original=lambda reference:next(r['projection'] for r in quote['source_reading'] if r['ref']==reference)
    offer=get(disclosure.offer_ref.model_dump(mode='json'));terms=get(offer['terms_ref']);draft=quote['result']['payload']['offer']
    independent=next(r['projection'] for r in order['source_reading'] if r['ref']==disclosure.offer_ref.model_dump(mode='json'))
    if (offer['supplier_id']!=disclosure.supplier_id or offer['buyer_id']!=plan.organization_id or offer['payer_id']!=plan.organization_id
            or offer['ref']!=source_plan.action_input['offer_ref'] or offer['terms_ref']!=draft['terms_ref']
            or terms['offer_ref']!=offer['ref'] or terms['supplier_id']!=offer['supplier_id']
            or terms['buyer_id']!=offer['buyer_id'] or terms['payer_id']!=offer['payer_id']
            or draft['buyer_id']!=offer['buyer_id'] or draft['payer_id']!=offer['payer_id']
            or offer['effective_window']!=original(draft['validity_ref'])
            or terms['effective_window']!=original(draft['validity_ref'])
            or offer['lines']!=terms['lines'] or len(offer['lines'])!=len(draft['lines'])
            or terms['gross_price']['currency']!=original(draft['terms_ref'])['currency']
            or disclosure.payment_rules!=original(draft['terms_ref'])['payment_rules']
            or independent['scope']!=plan.context.scope.model_dump(mode='json')):
        raise TaskConflict('Contractor terms substitute communicated Supplier parties, offer identity or payment rules')
    links={task_digest(r.supply_requirement_ref.model_dump(mode='json')):r for r in disclosure.requirement_links}
    if (len(links)!=len(disclosure.requirement_links) or {task_digest(r) for r in offer['requirement_refs']}!=set(links)
            or terms['requirement_refs']!=offer['requirement_refs']):
        raise TaskConflict('Contractor disclosure loses complete independent requirement correspondence')
    for line,quoted in zip(offer['lines'],draft['lines']):
        requirement=get(line['requirement_ref']);link=links[task_digest(line['requirement_ref'])];product=quoted['product']
        if (line['product_ref']!=product['product_ref'] or line['quantity']!=product['quantity'] or line['batch_price']!=quoted['price']
                or requirement['product_ref']!=product['product_ref'] or requirement['quantity']!=product['quantity']
                or requirement['scope']!=product['destination_scope_ref']
                or [r.model_dump(mode='json') for r in link.quote_requirement_refs]!=product['requirement_refs']
                or requirement['delivery_window_ref']!=quoted['delivery_window_ref']
                or requirement['destination_ref']!=quoted['destination_ref']
                or terms['delivery_window_ref']!=quoted['delivery_window_ref'] or terms['destination_ref']!=quoted['destination_ref']):
            raise TaskConflict('Contractor procurement substitutes original quoted product, quantity, price, destination or delivery')
        if [r.model_dump(mode='json') for r in disclosure.included_service_refs]!=quoted['included_service_refs']:
            raise TaskConflict('Contractor procurement substitutes the quoted included services')
    if len(offer['lines'])!=1 or terms['gross_price']!=draft['lines'][0]['price']:
        raise TaskConflict('Current procurement composition requires one exact quoted batch; no invented aggregation')
    # Whitelist evidence records explicitly; never expand an author's readable
    # permissions into the Supplier's cost, stock, cash, capacity or strategy.
    author=get(offer['author_authority_ref']);assignment=get(offer['author_function_ref'])
    required_evidence={task_digest(ref) for ref in [*offer['evidence_refs'],*terms['evidence_refs'],
        *author['basis_refs'],*assignment['basis_refs'],*(line['price']['basis_ref'] for line in draft['lines']),
        *(line['product']['quantity']['basis_ref'] for line in draft['lines'])] if ref['kind']=='Evidence'}
    shared=[task_digest(ref.model_dump(mode='json')) for ref in disclosure.shared_evidence_refs]
    if len(shared)!=len(set(shared)) or set(shared)!=required_evidence:
        raise TaskConflict('Contractor commercial evidence whitelist must preserve every original price, quantity and author basis')
    for ref in disclosure.shared_evidence_refs:
        reference=ref.model_dump(mode='json')
        if get(reference)!=original(reference):raise TaskConflict('Contractor substitutes original shared commercial evidence')
    substitutions=quoted_substitutions(disclosure=disclosure,offer=offer,draft=draft,objects=objects,quote=quote,
        scope=plan.context.scope.model_dump(mode='json'))
    origin={'supplier_id':disclosure.supplier_id,'A03_task_key':TaskIdentity(**quote['identity']).key,
        'A03_result_sha256':quote['result_sha256'],'A03_record_sha256':quote['record_sha256'],
        'A04_task_key':TaskIdentity(**order['identity']).key,'A04_result_sha256':order['result_sha256'],
        'proposal_response_sha256':technical['proposal_response_sha256'],
        'independent_received_offer_sha256':task_digest(offer),'independent_received_terms_sha256':task_digest(terms)}
    if substitutions:origin['substitutions']=substitutions
    evidence_binding(objects,disclosure.evidence_ref.model_dump(mode='json'),origin)
    return origin
