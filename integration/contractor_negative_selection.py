"""Authenticate the bounded A05 no-accepted-supplier wait and its actual outcome."""
from copy import deepcopy
from integration.bank_financing_private import evidence_binding
from src.actions.roles.contractor_negative_selection import WAIT_CODES
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest

SOURCE = 'micro_contractor_no_accepted'


def saved_selection(app, identity):
    saved = app.worker.get_record(identity)
    task = app.worker.store.get(identity)
    if (saved is None or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])):
        raise TaskConflict('Selection lost its exact original worker evidence')
    result = saved['result']
    if result['kind'] == 'completed':
        if task['state'] != 'output_formed' or task['output'] != result:
            raise TaskConflict('Completed selection lost original formed task')
    elif (result['kind'] != 'deferred' or result.get('reason_code') not in WAIT_CODES
            or result['resume_condition']['condition_code'] != result['reason_code']
            or task['state'] != 'waiting_input'):
        raise TaskConflict('Only the exact authenticated no-accepted wait can become negative native selection')
    return saved


def validate_selection_wait(app, task, result, conditions):
    if (result.get('kind') != 'deferred' or result.get('reason_code') not in WAIT_CODES
            or result['resume_condition']['condition_code'] != result['reason_code']):
        return app.supplier.validate_wait(task, result, conditions)
    identity = TaskIdentity(**task['identity'])
    plan, request = app._bound[identity.context_sha256]
    objects, _, observed = app._sources(plan, request)
    if (any(d['accepted'] for p, d in request.inputs['offers'])
            or result['resume_condition']['object_refs'] != [plan.negative_selection_observation_ref.model_dump(mode='json')]
            or result['reason_code'] != ('contractor-plan-repeated-no-accepted-native-supplier' if observed['prior_failures']
                else 'contractor-plan-no-accepted-native-supplier')):
        raise TaskConflict('No-accepted pending condition differs from actual current decisions/history')
    return True


def bind_selection_observation(app, plan, request, objects, *, history):
    row, = [r['value'] for r in objects if r['ref'] == plan.negative_selection_observation_ref.model_dump(mode='json')]
    if row['supplier_decisions'] is not None or row['prior_failures'] is not None:
        raise TaskConflict('Selection observation/history was prefilled')
    project = app.supplier.assembly.engine.projects[plan.project_id]
    events = [deepcopy(e) for e in project.event_log if e['event_type'] == 'supplier_order_decision' and e['tick'] == plan.tick]
    if {e['agent_id'] for e in events} != {p['agent_id'] for p, d in request.inputs['offers']}:
        raise TaskConflict('Negative selection omitted current supplier outcomes')
    row.update(supplier_decisions=events, prior_failures=deepcopy(history))
    return row


def negative_sources(app, plan, request, scope):
    from integration.procurement_failure_followup import authenticate_failure
    objects = deepcopy(plan.objects)
    project = app.supplier.assembly.engine.projects[plan.project_id]
    mandate, = [r['value'] for r in objects if r['ref'] == plan.action_input['work_basis']['contract_ref']]
    if (mandate['organization_id'] != plan.organization_id
            or not any(c.get('contractor_id') == plan.organization_id for c in project.contracts)):
        raise TaskConflict('Negative selection lacks its actual signed buyer mandate')
    profile, = [r['value'] for r in objects if r['ref'] == mandate['planning_profile_ref']]
    if profile['choice'] != 'accept_supply_offer' or profile['selected_offer_ref'] is not None:
        raise TaskConflict('Negative selection cannot replace a preselected offer')
    history = []
    client = app.supplier.assembly.client
    for row in client.inbox.for_organization(run_id=client.run_id, organization_id=plan.organization_id):
        if row['payload']['event_type'] == 'supplier_selection_failed' and row['payload']['tick'] < plan.tick:
            history.append(authenticate_failure(app.supplier, row))
    history.sort(key=lambda h: (h['event']['tick'], h['event']['event_id']))
    observation = bind_selection_observation(app, plan, request, objects, history=history)
    profile.update(negative_selection_observation_ref=plan.negative_selection_observation_ref.model_dump(mode='json'),
        selected_offer_ref=None, procurement_authority_ref=None)
    observed = {'scope': scope, 'native_request_sha256': task_digest(request.model_dump(mode='json')),
        'supplier_decisions': observation['supplier_decisions'], 'prior_failures': history,
        'accepted_supplier_ids': [], 'decision_basis': 'all_actual_supplier_decisions_refused',
        'selected_supplier_id': None}
    evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
    for d in plan.disclosures:
        evidence_binding(objects, d.evidence_ref.model_dump(mode='json'), {
            'source': 'not_an_accepted_quote', 'supplier_id': d.supplier_id, 'scope': scope})
    inputs = deepcopy(plan.action_input); inputs['supplier_offer_refs'] = []
    candidate, = [r['value'] for r in objects if r['ref'] == plan.context.candidate_set_ref.model_dump(mode='json')]
    candidate['candidates'] = []
    return objects, inputs, observed


def authenticate_negative_result(supplier, decision, proposal, final):
    """The native failure must name the actual durable pending A05 result."""
    key = decision.get('micro_task_key')
    tasks = supplier.assembly.client.tasks.for_organization(run_id=supplier.assembly.client.run_id,
        organization_id=decision['native_supply_scope']['contractor_id'])
    task, = [t for t in tasks if TaskIdentity(**t['identity']).key == key]
    saved = saved_selection(supplier.contractor, TaskIdentity(**task['identity']))
    if (task['identity']['action_id'] != 'CONTRACTOR-A05' or saved['result']['kind'] != 'deferred'
            or any(d.get('micro_task_key') != key or d.get('micro_result_sha256') != saved['result_sha256']
                or d.get('decision_source') != SOURCE for d in [decision, proposal['factors'], final['data']])):
        raise TaskConflict('Actual failed selection substituted its original negative A05 judgment')
    return {'identity': task['identity'], 'result': saved['result'], 'result_sha256': saved['result_sha256'],
        'source_reading_sha256': saved['source_reading_sha256']}
