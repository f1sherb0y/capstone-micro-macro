"""Declare an alternate catalog product and exact deviation before any execution."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from src.actions.contracts.supplier_order_objects import order_agreement_digest
from src.coordination.tasks import task_digest


def extend_substitution_plan(plan, *, grants):
    plan=deepcopy(plan);quote=plan['quote'];step=quote['product']
    find=lambda objects,reference:next(r['value'] for r in objects if r['ref']==reference)
    product_ref,=step['action_input']['product_candidates']
    requirement_ref,=step['action_input']['requirement_refs']
    product=find(step['objects'],product_ref);inquiry=find(step['objects'],step['action_input']['inquiry_ref'])
    requested=inquiry['lines'][0]['product_code']['value'];alternate=requested+'-alternate-catalog'
    tag=step['context']['operation_id'];deviation=ref('SpecificationDeviation',tag+'-product-code-departure')
    basis=ref('Evidence',tag+'-independent-substitution-source')
    window=product['effective_window'];scope=step['context']['scope']
    fact={'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
        'locator':'independent-initial-alternate-catalog-and-deviation-not-a-product-approval',
        'content_hash':task_digest({'product_ref':product_ref,'requested_code':requested,'alternate_code':alternate,
            'requirement_ref':requirement_ref,'deviation_ref':deviation,'explicitly_allow_product_substitution':True}),
        'effective_window':window}
    departure={'ref':deviation,'inquiry_ref':inquiry['ref'],'requirement_ref':requirement_ref,'product_ref':product_ref,
        'factory_id':product['factory_id']['value'],'intended_use_code':'synthetic-envelope','scope':scope,
        'property_code':'product_code','description':'Independent alternate catalog code '+alternate+' differs from requested '+requested,
        'effective_window':window,'evidence_refs':[basis]}

    def update_lines(value):
        if isinstance(value,dict):
            if value.get('product_ref')==product_ref and 'deviation_refs' in value:
                value['deviation_refs']=[deepcopy(deviation)]
            for child in value.values():update_lines(child)
        elif isinstance(value,list):
            for child in value:update_lines(child)

    for selected in (plan,quote,step):
        objects=selected['objects'];context=selected['context']
        value=find(objects,product_ref)
        value['product_code']=known(alternate);value['deviation_refs']=[deviation]
        value['evidence_refs'].append(basis)
        update_lines(objects)
        objects.extend([{'ref':basis,'value':deepcopy(fact)},{'ref':deviation,'value':deepcopy(departure)}])
        context['visible_refs'].extend([basis,deviation])
        own=find(objects,context['authorization_refs'][0]);own['readable_refs'].extend([basis,deviation])
        next(g for g in grants if g['ref']==own['ref'])['readable_refs'].extend([basis,deviation])
    find(step['objects'],requirement_ref)['allow_product_substitution']=True
    # This is initial independently declared commercial assent to the exact
    # alternate terms, not a signature attributed to a future A02/A03/A04.
    proposal=find(plan['objects'],plan['action_input']['order_proposal_ref'])
    for reference in plan['action_input']['counterpart_acceptance_refs']:
        find(plan['objects'],reference)['agreement_sha256']=order_agreement_digest(proposal)
    return plan
