"""Author independent original QS-A05 sources, never a future response/result."""
from copy import deepcopy

from src.actions.contracts.qs_procurement_objects import procurement_document_digest, qs_procurement_schemas
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_response_plan(*, run_id, qs_id, owner_id, scope, now, prefix, shared_sources,
        authorizations, function_refs, grant_refs, basis_refs, design, rule, quantity, document,
        requirement_refs, publication_permitted):
    def ref(kind, name):
        return {'kind': kind, 'id': prefix + name, 'version': '1'}

    common = {k: deepcopy(document[k]) for k in ('scope', 'available_at', 'effective_window', 'evidence_refs')}
    procurement, round_ref = document['draft']['procurement_scope_ref'], document['round_ref']
    task, template, pricing = ref('Task', 'qs-publication'), ref('ProcurementTemplate', 'qs-template'), document['draft']['pricing_rule_ref']
    publication, publication_basis = ref('Authority', 'qs-release'), ref('PublicationBasis', 'qs-purpose-check')
    evidence_ref, candidate = ref('Evidence', 'native-question'), ref('CandidateSet', 'qs-response')
    operation_id = prefix + 'qs-clarification-publication'
    objects = deepcopy([r for r in shared_sources if r['ref']['kind'] in
        {'Evidence', 'FunctionAssignment', 'Authorization', 'ClockProfile', 'Project', 'WorkScope'}])
    basis, = [r['value'] for r in objects if r['ref'] == basis_refs[qs_id]]
    question_evidence = deepcopy(basis)
    question_evidence.update(ref=evidence_ref, basis_kind='observed', content_hash=None,
        locator='development:actual-native-question:' + prefix)
    objects.append({'ref': evidence_ref, 'value': question_evidence})

    def put(reference, **fields):
        value = {**deepcopy(common), 'ref': reference, **fields}
        objects.append({'ref': reference, 'value': value})

    for value in (design, rule, quantity, document):
        objects.append({'ref': value['ref'], 'value': deepcopy(value)})
    # The actual question is a runtime input to the original publication task.
    # It is not an initial answer, approval or edited procurement draft.
    put(procurement, task_ref=task, round_ref=round_ref, template_ref=template,
        buyer_id=owner_id, buyer_organization_id=owner_id, design_refs=[design['ref']],
        measurement_rule_ref=rule['ref'], quantity_schedule_ref=quantity['ref'], pricing_rule_ref=pricing,
        exclusions=[], saved_document_ref=document['ref'], prior_document_ref=None,
        revision_impact_ref=None, question_refs=[], evidence_refs=[basis_refs[qs_id], evidence_ref])
    put(task, organization_id=qs_id, function_ref=function_refs[qs_id], authority_ref=grant_refs[qs_id],
        procurement_scope_ref=procurement, round_ref=round_ref, operation='publication', status='authorized')
    put(round_ref, procurement_scope_ref=procurement, buyer_id=owner_id, buyer_organization_id=owner_id,
        template_ref=template, status='open')
    put(template, procurement_mode='fixed_quantity', measurement_rule_refs=[rule['ref']],
        pricing_rule_refs=[pricing], allowed_uses=['procurement'])
    put(pricing, round_ref=round_ref, design_refs=[design['ref']], quantity_schedule_ref=quantity['ref'],
        measurement_rule_ref=rule['ref'], currency='HKD', included_coverage_keys=design['coverage_keys'],
        excluded_scope_refs=[], assumptions=['Explicit synthetic source quantities and publication grants'],
        provisional_quantities_supported=False, allowed_uses=['procurement'])
    put(publication_basis, procurement_scope_ref=procurement, round_ref=round_ref, document_ref=document['ref'],
        document_digest=procurement_document_digest(document['draft']), permitted={'state':'known','value':True},
        checker_actor_id=qs_id, checker_function_ref=function_refs[qs_id], checker_authority_ref=grant_refs[qs_id],
        checked_at=now)
    put(publication, procurement_scope_ref=procurement, round_ref=round_ref, document_ref=document['ref'],
        publication_basis_ref=publication_basis, delegate_actor_id=qs_id, delegate_organization_id=qs_id,
        delegate_function_ref=function_refs[qs_id], buyer_actor_id=owner_id, buyer_organization_id=owner_id,
        buyer_function_ref=function_refs[owner_id], buyer_authority_ref=grant_refs[owner_id],
        granted_at=common['effective_window']['start'], permission={'state':'known','value':publication_permitted})
    objects.append({'ref': candidate, 'value': {'operation_id': operation_id, 'scope': scope, 'as_of': now,
        'candidates': [{'ref': procurement, 'permitted_choices': ['prepare','identify_gaps','request_publication','publish_authorized']}],
        'search_profile_ref': ref('Profile', 'explicit-qs-publication')}})
    refs = {task_digest(r['ref']): r['ref'] for r in objects}
    allowed = {task_digest(r): r for r in authorizations[qs_id]['readable_refs']}
    allowed.update(refs)
    authorizations[qs_id]['readable_refs'] = list(allowed.values())
    context = {'run_id':run_id, 'actor_id':qs_id, 'function_ref':function_refs[qs_id],
        'authorization_refs':[grant_refs[qs_id]], 'operation_id':operation_id,
        'contract_ref':{'kind':'ActionContract','id':'QS-A05','version':'1'},
        'task_ref':ref('DecisionTask','qs-response'), 'scope':scope, 'business_time':now,
        'read_token':prefix+'qs-response', 'visible_refs':list(refs.values()),
        'candidate_set_ref':candidate, 'execution_mode':'rule'}
    schemas = qs_procurement_schemas()
    for row in objects:
        if row['ref'] == evidence_ref:
            continue  # The actual native message binds this evidence before any original typed read.
        row['value'] = schemas.validate_projection(Reference.model_validate(row['ref']), row['value']).model_dump(mode='json')
    return {'answer_kind':'quantity_and_measurement', 'requirement_refs':requirement_refs,
        'context':context, 'action_input':{'scope':scope, 'procurement_scope_ref':procurement,
            'design_refs':[design['ref']], 'measurement_rule_ref':rule['ref'],
            'quantity_schedule_ref':quantity['ref'], 'prior_document_ref':None, 'publication_authority_ref':publication},
        'objects':objects, 'question_evidence_ref':evidence_ref}
