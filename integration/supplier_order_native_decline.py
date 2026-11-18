"""Bind an original upstream commercial decline to the complete current demand."""
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.actions.contracts.supplier_order_objects import FormationOfferView, OrderProposalView
from src.actions.contracts.supplier_quote_objects import QuoteInquiryView, QuoteProductLine
from src.coordination.tasks import TaskConflict, task_digest


DECLINES = {'screening': ('SUPPLIER-A01', 'decline'),
            'product': ('SUPPLIER-A02', 'decline'), 'quote': ('SUPPLIER-A03', 'decline_quote')}


def decline_for_supply(record, *, invocation, plan, stage):
    """No quote, agreement, A04 result or formal order is manufactured here.

    A decline is usable only for one independently received complete inquiry
    whose parties, quantities, requirements and delivery windows match the
    existing project-order proposal. A smaller or unrelated inquiry cannot
    reject the whole native request.
    """
    action, choice = DECLINES[stage]
    quote = plan.quote
    step = {'quote': quote, 'product': quote.product,
            'screening': quote.product.screening if quote.product else None}[stage]
    context = step.context.model_dump(mode='json');identity = record['identity']
    result = record['result']
    if (identity['action_id'] != action or identity['run_id'] != plan.context.run_id
            or identity['organization_id'] != plan.organization_id or invocation['identity'] != identity
            or invocation['context'] != context or invocation['action_input'] != step.action_input
            or identity['context_sha256'] != task_digest(context)
            or identity['input_sha256'] != task_digest(step.action_input)
            or result['kind'] != 'completed' or result['payload']['choice'] != choice
            or record['result_sha256'] != task_digest(result)
            or record['source_reading_sha256'] != task_digest(record['source_reading'])):
        raise TaskConflict('Supply decline lost its original completed upstream decision')

    def source(objects, reference):
        rows = [r['value'] for r in objects if r['ref'] == reference]
        if len(rows) != 1:raise TaskConflict('Supply decline lacks its exact independent demand source')
        return rows[0]

    inquiry = QuoteInquiryView.model_validate(source(quote.objects, quote.action_input['inquiry_ref']))
    base = {k: v for k, v in inquiry.model_dump(mode='json').items() if k in SupplyInquiryView.model_fields}
    references = step.action_input['inquiry_refs'] if stage == 'screening' else [step.action_input['inquiry_ref']]
    read = [r['projection'] for r in record['source_reading'] if r['ref'] == inquiry.ref.model_dump(mode='json')]
    if (references != [inquiry.ref.model_dump(mode='json')] or len(read) != 1
            or read[0] != (inquiry.model_dump(mode='json') if stage == 'quote' else base)
            or inquiry.status != 'active' or inquiry.scope != plan.context.scope
            or inquiry.recipient_id != plan.context.actor_id or inquiry.recipient_organization_id != plan.organization_id
            or not inquiry.response_window.contains(plan.context.business_time)):
        raise TaskConflict('Supply decline changes its actual complete received inquiry')
    offer = FormationOfferView.model_validate(source(plan.objects, plan.action_input['offer_ref']))
    proposal = OrderProposalView.model_validate(source(plan.objects, plan.action_input['order_proposal_ref']))
    payer = inquiry.payer_id.model_dump(mode='json');currency = inquiry.currency.model_dump(mode='json')
    terms = source(plan.objects, offer.terms_ref.model_dump(mode='json'))
    if (offer.ref != proposal.offer_ref or offer.status != 'active' or proposal.status != 'active'
            or any(r.scope != inquiry.scope or r.supplier_organization_id != plan.organization_id
                   or r.buyer_id != inquiry.buyer_id or payer != {'state': 'known', 'value': r.payer_id}
                   for r in (offer, proposal))
            or proposal.recipient_actor_id != plan.context.actor_id or proposal.terms_ref != offer.terms_ref
            or proposal.condition_refs != offer.condition_refs
            or not proposal.response_window.contains(plan.context.business_time)
            or currency != {'state': 'known', 'value': terms['currency']}
            or len(offer.lines) != len(proposal.lines) or len(offer.lines) != len(inquiry.lines)):
        raise TaskConflict('Supply decline substitutes its native-project parties or complete agreement')
    offered = {r.local_key: r.delivery for r in offer.lines};requirements = []
    for row in proposal.lines:
        delivery = row.delivery;product = delivery.product
        if offered.get(row.offer_line_key) != delivery or len(product.requirement_refs) != 1:
            raise TaskConflict('Supply decline changes its complete proposed deliveries')
        reference = product.requirement_refs[0].model_dump(mode='json')
        lines = [r for r in inquiry.lines if r.requirement_ref.model_dump(mode='json') == reference]
        if len(lines) != 1:raise TaskConflict('Supply decline loses complete inquiry requirement correspondence')
        line = lines[0];spec = source(quote.objects, product.product_ref.model_dump(mode='json'))
        window = source(plan.objects, delivery.delivery_window_ref.model_dump(mode='json'))
        if (line.scope != product.destination_scope_ref
                or line.quantity.model_dump(mode='json') != {'state': 'known', 'value': product.quantity.model_dump(mode='json')}
                or line.product_code.model_dump(mode='json') != spec['product_code']
                or line.work_window.model_dump(mode='json') != {'state': 'known', 'value': window}):
            raise TaskConflict('Supply decline substitutes inquiry product, quantity, scope or delivery window')
        products = [p['product'] for ref in quote.action_input['product_proposal_refs']
                    for p in source(quote.objects, ref)['lines']]
        if sum(QuoteProductLine.model_validate(p) == product for p in products) != 1:
            raise TaskConflict('Supply decline changes the independent proposed product demand')
        requirements.append(reference)
    if len({task_digest(r) for r in requirements}) != len(inquiry.lines):
        raise TaskConflict('Supply decline repeats or omits part of the received demand')
    return {'source': 'original_supplier_complete_demand_decline', 'stage': stage,
            'micro_action_id': action, 'result_sha256': record['result_sha256'],
            'source_reading_sha256': record['source_reading_sha256'],
            'inquiry_sha256': task_digest(base), 'order_proposal_sha256': task_digest(proposal.model_dump(mode='json'))}
