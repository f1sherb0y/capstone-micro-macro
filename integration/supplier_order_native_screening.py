"""Actual A01 screening evidence for a same-request received A02 inquiry."""
from copy import deepcopy

from pydantic import model_validator

from integration.bank_financing_private import evidence_binding
from integration.supplier_screening_handoff import SupplierScreeningHandoffBasisView
from src.actions.contracts.common import ActionContext, StrictRecord, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class SupplierOrderScreeningStep(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    handoff_basis_ref: ref_type('SupplierScreeningHandoffBasis')
    handoff_evidence_ref: ref_type('Evidence')
    received_evidence_ref: ref_type('Evidence')

    @model_validator(mode='after')
    def original_action(self):
        if (self.context.contract_ref.id!='SUPPLIER-A01' or self.context.execution_mode=='offline_fixture'
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Screening preparation changes original action, execution mode or source identities')
        return self


def screening_for_product(record,*,invocation,step,product,objects):
    """Relate an actual full response to independently received demand, never create demand."""
    identity=record['identity'];context=step.context;current=product.context;result=record['result']
    if (identity['action_id']!='SUPPLIER-A01' or identity['run_id']!=context.run_id
            or invocation['identity']!=identity
            or invocation['context']!=context.model_dump(mode='json') or invocation['action_input']!=step.action_input
            or identity['context_sha256']!=task_digest(invocation['context'])
            or identity['input_sha256']!=task_digest(invocation['action_input']) or result['kind']!='completed'
            or result['payload']['choice']!='respond' or record['result_sha256']!=task_digest(result)
            or record['source_reading_sha256']!=task_digest(record['source_reading'])
            or context.run_id!=current.run_id or context.actor_id!=current.actor_id
            or context.scope!=current.scope or context.business_time!=current.business_time):
        raise TaskConflict('Product preparation requires its actual original same-request full screening response')
    def target(reference):
        rows=[r for r in objects if r['ref']==reference]
        if len(rows)!=1:raise TaskConflict('Screening handoff lacks its exact pre-authorized product source')
        return rows[0]
    inquiry_ref=product.action_input['inquiry_ref'];inquiry=target(inquiry_ref)['value']
    original,=[r['projection'] for r in record['source_reading'] if r['ref']==inquiry_ref]
    if (result['payload']['inquiry_ref']!=inquiry_ref or inquiry_ref not in step.action_input['inquiry_refs']
            or inquiry!=original or inquiry['buyer_id']!=original['buyer_id']
            or inquiry['recipient_organization_id']!=identity['organization_id']
            or inquiry['recipient_id']!=current.actor_id
            or {task_digest(s) for s in result['payload']['offered_scope_refs']}
                !={task_digest(line['scope']) for line in original['lines']}
            or {task_digest(ref) for ref in product.action_input['requirement_refs']}
                !={task_digest(line['requirement_ref']) for line in inquiry['lines']}):
        raise TaskConflict('Product preparation substitutes the actual screened inquiry, complete scope or requirements')
    evidence=step.handoff_evidence_ref.model_dump(mode='json');received_ref=step.received_evidence_ref.model_dump(mode='json')
    requirements=[target(ref)['value'] for ref in product.action_input['requirement_refs']]
    if any(evidence not in r['evidence_refs'] or received_ref not in r['evidence_refs'] for r in requirements):
        raise TaskConflict('Product requirements do not declare actual screening and received-source evidence')
    links=[]
    for line in inquiry['lines']:
        requirement=target(line['requirement_ref'])['value']
        if requirement['inquiry_ref']!=inquiry_ref or requirement['scope']!=line['scope']:
            raise TaskConflict('Product requirement changes its independently received inquiry scope')
        links.append({'original_requirement_ref':line['requirement_ref'],'current_requirement_ref':line['requirement_ref'],
            'current_requirement_sha256':task_digest(requirement)})
    bound={'source':'private_original_supplier_screening','identity':deepcopy(identity),
        'record_sha256':record['record_sha256'],'result_sha256':record['result_sha256'],
        'source_reading_sha256':record['source_reading_sha256'],'audit_sha256':task_digest(record['audit']),
        'inquiry_sha256':task_digest(inquiry),'requirement_links':links}
    # This observes an actually read input, not a macro-created inquiry receipt.
    received={'source':'observed_read_of_independently_supplied_inquiry','inquiry':deepcopy(inquiry),
        'requirements':deepcopy(requirements),'original_screening_task_key':TaskIdentity(**identity).key,
        'original_screening_source_reading_sha256':record['source_reading_sha256']}
    evidence_binding(objects,received_ref,received);evidence_binding(objects,evidence,bound)
    placeholder=target(step.handoff_basis_ref.model_dump(mode='json'))
    if placeholder['value'] is not None:raise TaskConflict('Screening handoff must bind an unused private relation')
    basis=SupplierScreeningHandoffBasisView.model_validate({'ref':placeholder['ref'],'run_id':current.run_id,
        'organization_id':identity['organization_id'],'scope':current.scope,'available_at':current.business_time,
        'effective_window':inquiry['response_window'],'author_actor_id':current.actor_id,
        'author_organization_id':identity['organization_id'],'author_function_ref':current.function_ref,
        'author_authority_ref':current.authorization_refs[0],'author_action_id':'SUPPLIER-A02','authored_at':current.business_time,
        'screening_task_sha256':TaskIdentity(**identity).key,'screening_record_sha256':record['record_sha256'],
        'screening_result_sha256':record['result_sha256'],'screening_audit_sha256':task_digest(record['audit']),
        'screening_source_reading_sha256':record['source_reading_sha256'],'inquiry_ref':inquiry_ref,
        'inquiry_sha256':task_digest(inquiry),'requirement_links':links,'received_source_sha256':task_digest(received),
        'received_evidence_ref':received_ref,'relation_evidence_refs':[evidence],'evidence_refs':[evidence]})
    placeholder['value']=basis.model_dump(mode='json')
    return {**bound,'received_source_sha256':task_digest(received),'basis_sha256':task_digest(placeholder['value'])}
