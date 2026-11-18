"""Actual private A02 product evidence for the same native-request A03 quote."""
from copy import deepcopy

from pydantic import model_validator

from integration.bank_financing_private import evidence_binding
from integration.supplier_product_handoff import SupplierProductHandoffBasisView
from integration.supplier_order_native_screening import SupplierOrderScreeningStep
from src.actions.contracts.common import ActionContext, StrictRecord, ref_type
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.actions.contracts.supplier_quote_objects import QuoteProductLine
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class SupplierOrderProductStep(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    handoff_basis_ref: ref_type('SupplierProductHandoffBasis')
    handoff_evidence_ref: ref_type('Evidence')
    screening: SupplierOrderScreeningStep | None=None

    @model_validator(mode='after')
    def original_action(self):
        if (self.context.contract_ref.id!='SUPPLIER-A02' or self.context.execution_mode=='offline_fixture'
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Product preparation changes original action, execution mode or source identities')
        if self.screening is not None:
            s=self.screening.context;c=self.context
            if (s.run_id!=c.run_id or s.actor_id!=c.actor_id or s.scope!=c.scope or s.business_time!=c.business_time
                    or s.function_ref!=c.function_ref or s.read_token==c.read_token):
                raise ValueError('Screening and product must preserve the same Supplier, project, clock and separate read points')
        return self


def product_for_quote(record,*,invocation,step,quote,objects):
    """Bind evidence and a pre-authorized relation, preserving independent proposal facts.

    This does not confirm a product, resolve a design issue or register a formal
    proposal. The original handoff validator subsequently checks this relation
    against the original saved worker result and the current authorized reading.
    """
    identity=record['identity'];context=step.context;current=quote.context
    if (identity['action_id']!='SUPPLIER-A02' or identity['run_id']!=context.run_id
            or invocation['identity']!=identity
            or invocation['context']!=context.model_dump(mode='json') or invocation['action_input']!=step.action_input
            or identity['context_sha256']!=task_digest(invocation['context'])
            or identity['input_sha256']!=task_digest(invocation['action_input'])
            or record['result']['kind']!='completed'
            or record['result']['payload']['choice'] not in {'propose_original','propose_substitute'}
            or record['result_sha256']!=task_digest(record['result'])
            or record['source_reading_sha256']!=task_digest(record['source_reading'])
            or context.run_id!=current.run_id or context.actor_id!=current.actor_id
            or context.scope!=current.scope or context.business_time!=current.business_time):
        raise TaskConflict('Private product handoff lost its original same-request completed A02')
    def source(reference):
        rows=[r['projection'] for r in record['source_reading'] if r['ref']==reference]
        if len(rows)!=1:raise TaskConflict('Product handoff lacks its exact original source snapshot')
        return rows[0]
    def target(reference):
        rows=[r for r in objects if r['ref']==reference]
        if len(rows)!=1:raise TaskConflict('Product handoff lacks its exact pre-authorized quote source')
        return rows[0]
    inquiry=target(quote.action_input['inquiry_ref'])['value']
    if (inquiry['recipient_organization_id']!=identity['organization_id']
            or inquiry['recipient_id']!=current.actor_id
            or step.action_input['inquiry_ref']!=quote.action_input['inquiry_ref']
            or {key:inquiry[key] for key in SupplyInquiryView.model_fields}!=source(step.action_input['inquiry_ref'])):
        raise TaskConflict('Quote substitutes the original product inquiry')
    proposals=[target(ref)['value'] for ref in quote.action_input['product_proposal_refs']]
    actual=record['result']['payload'];unmatched=set(range(len(actual['lines'])));links=[]
    # This composition supports fully resolved catalog proposals only. It must
    # not turn an unresolved independent design check into a confirmed quote.
    if actual['unresolved_refs']:
        raise TaskConflict('Original product design issues require explicit resolution before this quote composition')
    for proposal in proposals:
        if (proposal['inquiry_ref']!=step.action_input['inquiry_ref']
                or proposal['supplier_organization_id']!=identity['organization_id']):
            raise TaskConflict('Quote product proposal changes the original inquiry or Supplier')
        for line in proposal['lines']:
            matches=[i for i in sorted(unmatched) if QuoteProductLine.model_validate(actual['lines'][i])
                ==QuoteProductLine.model_validate(line['product'])]
            if not matches:raise TaskConflict('Quote proposal differs from the original A02 product, quantity or requirements')
            index=matches[0];unmatched.remove(index)
            links.append({'product_line_index':index,'proposal_ref':proposal['ref'],'proposal_line_key':line['local_key']})
            product_ref=line['product']['product_ref']
            if target(product_ref)['value']!=source(product_ref):
                raise TaskConflict('Quote substitutes original product specification facts')
    if unmatched or not links:raise TaskConflict('Quote omits original product proposal lines')
    evidence=step.handoff_evidence_ref.model_dump(mode='json')
    if any(evidence not in p['evidence_refs'] for p in proposals):
        raise TaskConflict('Quote product proposals do not declare their actual A02 evidence dependency')
    bound={'source':'private_original_supplier_product','identity':deepcopy(identity),
        'record_sha256':record['record_sha256'],'result_sha256':record['result_sha256'],
        'source_reading_sha256':record['source_reading_sha256'],'audit_sha256':task_digest(record['audit']),
        'independent_proposal_sha256s':{p['ref']['id']:task_digest(p) for p in proposals}}
    evidence_binding(objects,evidence,bound)
    placeholder=target(step.handoff_basis_ref.model_dump(mode='json'))
    if placeholder['value'] is not None:raise TaskConflict('Product handoff requires an unbound private relation, not an existing formal record')
    basis=SupplierProductHandoffBasisView.model_validate({'ref':placeholder['ref'],'run_id':current.run_id,
        'organization_id':identity['organization_id'],'scope':current.scope,'available_at':current.business_time,
        'effective_window':proposals[0]['effective_window'],'author_actor_id':current.actor_id,
        'author_organization_id':identity['organization_id'],'author_function_ref':current.function_ref,
        'author_authority_ref':current.authorization_refs[0],'author_action_id':'SUPPLIER-A03','authored_at':current.business_time,
        'product_task_sha256':TaskIdentity(**identity).key,'product_record_sha256':record['record_sha256'],
        'product_result_sha256':record['result_sha256'],'product_audit_sha256':task_digest(record['audit']),
        'product_source_reading_sha256':record['source_reading_sha256'],
        'proposal_refs':[p['ref'] for p in proposals],'proposal_sha256s':bound['independent_proposal_sha256s'],
        'line_links':links,'issue_links':[],'relation_evidence_refs':[evidence],'evidence_refs':[evidence]})
    placeholder['value']=basis.model_dump(mode='json')
    return {**bound,'basis_sha256':task_digest(placeholder['value'])}
