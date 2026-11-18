"""Private original A03 evidence for A04; no native offer registration claim."""
from copy import deepcopy

from pydantic import model_validator

from integration.bank_financing_private import evidence_binding
from integration.supplier_order_native_product import SupplierOrderProductStep
from src.actions.contracts.common import ActionContext, StrictRecord, ref_type
from src.actions.contracts.supplier_order_objects import FormationOfferView, OrderDeliveryLine
from src.actions.contracts.supplier_quote_objects import QuoteInquiryView, QuoteTermsView
from src.coordination.tasks import TaskConflict, task_digest


class SupplierOrderQuoteStep(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    handoff_evidence_ref: ref_type('Evidence')
    product: SupplierOrderProductStep | None=None

    @model_validator(mode='after')
    def original_action(self):
        if (self.context.contract_ref.id!='SUPPLIER-A03' or self.context.execution_mode=='offline_fixture'
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Quote preparation changes original action, execution mode or source identities')
        if self.product is not None:
            p=self.product.context;c=self.context
            if (p.run_id!=c.run_id or p.actor_id!=c.actor_id or p.scope!=c.scope or p.business_time!=c.business_time
                    or p.function_ref!=c.function_ref or p.read_token==c.read_token):
                raise ValueError('Product and quote must preserve the same Supplier, project, clock and separate read points')
        return self


def quote_for_order(record,*,invocation,step,plan,objects):
    """Check an actual same-request quote against independently supplied terms.

    A04 retains its independent offer/proposal and buyer acceptances. This is
    private evidence that the current computation supports those exact terms,
    not a substitute for a formal SupplyOffer publication or native receipt.
    """
    identity=record['identity'];context=step.context
    if (identity['action_id']!='SUPPLIER-A03' or identity['organization_id']!=plan.organization_id
            or identity['run_id']!=context.run_id or invocation['identity']!=identity
            or invocation['context']!=context.model_dump(mode='json') or invocation['action_input']!=step.action_input
            or identity['context_sha256']!=task_digest(invocation['context'])
            or identity['input_sha256']!=task_digest(invocation['action_input'])
            or record['result']['kind']!='completed' or record['result']['payload']['choice']!='quote'
            or record['result_sha256']!=task_digest(record['result'])
            or record['source_reading_sha256']!=task_digest(record['source_reading'])):
        raise TaskConflict('Private supply handoff lost its original same-request completed quote')
    offer,=[r['value'] for r in objects if r['ref']==plan.action_input['offer_ref']]
    offer=FormationOfferView.model_validate(offer);draft=record['result']['payload']['offer']
    if (offer.supplier_organization_id!=plan.organization_id or offer.scope!=context.scope
            or any(draft[k]!=getattr(offer,k) for k in ('buyer_id','payer_id'))
            or draft['terms_ref']!=offer.terms_ref.model_dump(mode='json')
            or draft['validity_ref']!=offer.validity_ref.model_dump(mode='json')
            or draft['condition_refs']!=[r.model_dump(mode='json') for r in offer.condition_refs]
            or len(draft['lines'])!=len(offer.lines)
            or any(OrderDeliveryLine.model_validate(line)!=original.delivery
                for line,original in zip(draft['lines'],offer.lines))):
        raise TaskConflict('Current original quote differs from the independent A04 offer; revise and reconfirm explicitly')
    def original(reference):
        matches=[r['projection'] for r in record['source_reading'] if r['ref']==reference]
        if len(matches)!=1:raise TaskConflict('Private supply quote lacks its complete original source snapshot')
        return matches[0]
    inquiry=QuoteInquiryView.model_validate(original(step.action_input['inquiry_ref']))
    if (inquiry.scope!=offer.scope or inquiry.buyer_id!=offer.buyer_id
            or inquiry.recipient_id!=context.actor_id or inquiry.recipient_organization_id!=plan.organization_id):
        raise TaskConflict('Private quote changes the actual order supplier, buyer or scope')
    terms=QuoteTermsView.model_validate(original(draft['terms_ref']))
    current_terms,=[r['value'] for r in objects if r['ref']==draft['terms_ref']]
    if (terms.supplier_organization_id!=offer.supplier_organization_id or terms.buyer_id!=offer.buyer_id
            or terms.payer_id!=offer.payer_id or terms.currency!=current_terms['currency']
            or terms.effective_window.model_dump(mode='json')!=current_terms['effective_window']
            or [r.model_dump(mode='json') for r in terms.payment_rules]!=current_terms['payment_rules']):
        raise TaskConflict('Private quote substitutes independent A04 payment terms')
    for field in ('inventory_ref','capacity_ref'):
        if step.action_input[field]!=plan.action_input[field]:
            raise TaskConflict('Private quote substitutes its physical stock or capacity source identity')
        current,=[r['value'] for r in objects if r['ref']==plan.action_input[field]]
        if task_digest(current)!=task_digest(original(step.action_input[field])):
            raise TaskConflict('Private quote substitutes its current stock or capacity snapshot')
    evidence=step.handoff_evidence_ref.model_dump(mode='json')
    target,=[r['value'] for r in objects if r['ref']==plan.action_input['offer_ref']]
    if evidence not in target['evidence_refs']:
        raise TaskConflict('A04 offer view does not declare the original quote evidence dependency')
    bound={'source':'private_original_supplier_quote','identity':deepcopy(identity),
        'record_sha256':record['record_sha256'],'result_sha256':record['result_sha256'],
        'source_reading_sha256':record['source_reading_sha256'],'audit_sha256':task_digest(record['audit']),
        'independent_offer_sha256':task_digest(offer.model_dump(mode='json'))}
    evidence_binding(objects,evidence,bound)
    return bound
