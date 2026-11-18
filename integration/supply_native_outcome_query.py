"""Read original supply decisions and selections without repeating business."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from integration.financing_native_outcome_query import _original_result
from integration.supplier_order_native_decline import DECLINES, decline_for_supply
from integration.supplier_order_native_feedback import project_supply_event
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def matching_supply_events(assembly, record, organization_id, *, contractor):
    """Require matching original project/global logs; absence remains unknown."""
    scope = record['scope']
    project = assembly.engine.projects.get(scope['project_id'])
    if project is None:
        raise TaskConflict('Supply query lost its original native project')
    event_type = 'supplier_selected' if contractor else 'supplier_order_decision'

    def matches(event):
        return (event['event_type'] == event_type and event['tick'] == scope['tick']
                and event['project_id'] == scope['project_id']
                and (event['data'].get('contractor_id') == organization_id if contractor
                     else event['agent_id'] == organization_id))

    local = [e for e in project.event_log if matches(e)]
    global_events = [e.model_dump(mode='json') for e in assembly.engine.events.events
                     if matches(e.model_dump(mode='json'))]
    if (len({e['event_id'] for e in local}) != len(local)
            or len({e['event_id'] for e in global_events}) != len(global_events)
            or {e['event_id']: task_digest(e) for e in local}
               != {e['event_id']: task_digest(e) for e in global_events} or len(local) > 1):
        raise TaskConflict('Supply query requires consistent unique original project and global events')
    return local


def reconcile_supply_history(query_original, origins, tasks, tick):
    """Gate later private consumption on a currently readable original outcome.

    The original history projection and strictly-earlier policy stay unchanged.
    Queries neither redeliver feedback nor replay a completed native request.
    """
    if not callable(query_original):
        raise TaskConflict('Supply history requires its original read-only outcome query')
    for origin in origins:
        rows = [t for t in tasks if t['state'] == 'output_formed' and t['identity']['purpose'] == 'action'
                and TaskIdentity(**t['identity']).key == origin['micro_task_key']]
        if len(rows) != 1 or origin['tick'] >= tick:
            raise TaskConflict('Supply history lost its unique strictly earlier original action')
        identity = TaskIdentity(**rows[0]['identity'])
        result = query_original(identity, organization_id=identity.organization_id, tick=tick)
        outcome = result.get('native_outcome')
        if (result.get('status') != 'observed' or not isinstance(outcome, dict)
                or result.get('queried_at_tick') != tick
                or result.get('original_decision_identity') != identity.as_dict()
                or result.get('micro_result_sha256') != origin['micro_result_sha256']
                or outcome.get('event_id') != origin.get('acceptance_event_id', origin['event_id'])
                or outcome.get('accepted') is not origin.get('accepted', True)):
            raise TaskConflict('Supply history lacks its currently authorized exact original native outcome')


def _workflow(app, supplier, identity, organization_id, tick, *, contractor):
    supplier._check()
    identity = TaskIdentity(**(identity.as_dict() if isinstance(identity, TaskIdentity) else identity))
    role = 'Contractor' if contractor else 'Supplier'
    actions = {'CONTRACTOR-A05'} if contractor else {'SUPPLIER-A01', 'SUPPLIER-A02', 'SUPPLIER-A03', 'SUPPLIER-A04'}
    client, engine = supplier.assembly.client, supplier.assembly.engine
    if (type(tick) is not int or tick != engine.current_tick or identity.run_id != client.run_id
            or identity.organization_id != organization_id or identity.role != role
            or identity.action_id not in actions or identity.purpose != 'action'
            or client.organization_roles.get(organization_id) != role):
        raise TaskConflict('Supply query changes its original organization, action or current business clock')
    rows = [r for r in app._records() if r.get('identity') == identity.as_dict()]
    if len(rows) != 1:
        raise TaskConflict('Supply query needs its one original terminal workflow')
    record, = rows
    scope, request = record['scope'], record['native_request']
    key_data = [client.simulation_id, scope, request['request_id']] if contractor else [
        client.simulation_id, organization_id, scope, request['request_id']]
    operation = 'select_supplier' if contractor else 'consider_supply_order'
    if (record['state'] != 'formed' or request['agent']['agent_id'] != organization_id
            or request['agent']['role'] != role or request['operation'] != operation
            or record['key'] != app.PREFIX + task_digest(key_data) or not 1 <= scope['tick'] <= tick
            or contractor and scope['contractor_id'] != organization_id):
        raise TaskConflict('Supply query substitutes its original workflow, scope or request')
    plans = [p for p in app.plans if (p.organization_id, p.project_id, p.tick) == (
        organization_id, scope['project_id'], scope['tick']) and (
            contractor or p.contractor_id in {None, scope['contractor_id']})]
    if len(plans) != 1:
        raise TaskConflict('Supply query lost its immutable original source plan')
    return identity, record, plans[0]


def _bound_observation(supplier, saved, technical, evidence_ref, record):
    observed = technical['observed']
    evidence = [r['projection'] for r in saved['source_reading'] if r['ref'] == evidence_ref.model_dump(mode='json')]
    if (saved['result_sha256'] != technical['result_sha256'] or len(evidence) != 1
            or evidence[0]['content_hash'] != task_digest(observed) or observed['scope'] != record['scope']
            or observed['native_request_sha256'] != task_digest(record['native_request'])):
        raise TaskConflict('Supply query changes its original executed stage or bound native observation')


def _transport(supplier, identity, record, saved, accepted, action, data, *, contractor):
    events = matching_supply_events(supplier.assembly, record, identity.organization_id, contractor=contractor)
    if not events:
        return None
    event, = events
    tasks = supplier.assembly.client.tasks.for_organization(run_id=identity.run_id, organization_id=identity.organization_id)
    operation = 'select_supplier' if contractor else 'consider_supply_order'
    decision = 'contractor_supplier_selection' if contractor else 'supplier_order_acceptance'
    scope = record['scope']
    proposals = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == operation
        and t['output'].get('factors', {}).get('native_supply_scope') == scope]
    finals = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'decide' and t['identity']['action_id'] == decision
        and t['output'].get('data', {}).get('native_supply_scope') == scope]
    if len(proposals) != 1 or len(finals) != 1:
        raise TaskConflict('Supply query lost its original proposal or final response')
    proposal, final = proposals[0], finals[0]
    actual = event['data'].get('contractor_decision', {}) if contractor else event['data']
    fields = {'micro_action_id': identity.action_id, 'micro_task_key': identity.key,
              'micro_result_sha256': saved['result_sha256'], 'native_supply_scope': scope}
    if (proposal['request_id'] != record['native_request']['request_id'] or final['agent_id'] != identity.organization_id
            or proposal['accepted'] is not accepted or final['decision'] is not accepted
            or proposal['action_type'] != action or final['action_type'] != action
            or proposal['data'] != data or task_digest(proposal) != record['proposal_response_sha256']
            or any(row.get(k) != v for row in (proposal['factors'], final['data'], actual) for k, v in fields.items())
            or any(row.get('proposal_response_sha256') != record['proposal_response_sha256']
                   for row in (final['data'], actual))
            or any(row.get(k) != v for row in (final['data'], actual) for k, v in data.items())
            or not contractor and (actual.get('accepted') is not accepted or actual.get('action_type') != action)
            or contractor and event['agent_id'] != data['selected_supplier_id']):
        raise TaskConflict('Supply query substitutes its actual original decision, selection or correlation')
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    projection = project_supply_event(AgentObservationV1.model_validate(event), supplier.assembly.client.organization_roles)
    messages = [r for r in supplier.assembly.client.inbox.for_organization(
        run_id=identity.run_id, organization_id=identity.organization_id) if r['event_id'] == event['event_id']]
    if len(messages) != 1 or messages[0]['payload'] != projection.get(identity.organization_id):
        raise TaskConflict('Supply query lost its original recipient-scoped event projection')
    return {'event_id': event['event_id'], 'event_type': event['event_type'], 'tick': event['tick'],
            'event_sha256': task_digest(event), 'action_type': action, 'accepted': accepted, **deepcopy(data)}


def _result(supplier, identity, record, saved, tick, outcome):
    result = {'schema_version': 'native-supply-outcome-query.v1', 'status': 'unknown' if outcome is None else 'observed',
        'run_id': identity.run_id, 'simulation_id': supplier.assembly.client.simulation_id,
        'organization_id': identity.organization_id, 'queried_at_tick': tick,
        'original_decision_identity': identity.as_dict(), 'native_scope': deepcopy(record['scope']),
        'micro_result_sha256': saved['result_sha256'], 'native_outcome': deepcopy(outcome), 'resubmitted': False,
        'limits': ['Missing outcome remains unknown; no processor replay or new formal submission.',
                   'Original supply willingness or supplier selection only; no detailed order, stock reservation, shipment, receipt or payment is inferred.']}
    result['query_sha256'] = task_digest(result)
    return result


def query_supplier_outcome(supplier, identity, *, organization_id, tick):
    with supplier.read_guard():
        identity, record, plan = _workflow(supplier, supplier, identity, organization_id, tick, contractor=False)
        stage = record.get('terminal_stage', 'order')
        workers = {'screening': supplier.screening_worker, 'product': supplier.product_worker,
                   'quote': supplier.quote_worker, 'order': supplier.worker}
        stages = [s for s in ('screening', 'product', 'quote', 'order')
                  if s == 'order' or (s == 'quote' and plan.quote is not None)
                  or (s == 'product' and plan.quote is not None and plan.quote.product is not None)
                  or (s == 'screening' and plan.quote is not None and plan.quote.product is not None
                      and plan.quote.product.screening is not None)]
        if stage not in stages:
            raise TaskConflict('Supply query substitutes its original terminal stage')
        stages = stages[:stages.index(stage) + 1]
        if {s for s in workers if s != 'order' and s in record} != set(stages) - {'order'}:
            raise TaskConflict('Supply query changes its original executed prefix')
        previous = {}
        for name in stages:
            technical = record if name == stage else record[name]
            stage_identity = TaskIdentity(**technical['identity'])
            step = supplier._step(plan, name)
            if (stage_identity.organization_id != identity.organization_id or stage_identity.run_id != identity.run_id
                    or stage_identity.role != 'Supplier' or stage_identity.purpose != 'action'
                    or stage_identity.action_id != step.context.contract_ref.id):
                raise TaskConflict('Supply query changes an original predecessor identity')
            saved = _original_result(supplier, stage_identity, workers[name], step.context,
                                     step.action_input, key=record['key'], tick=tick)
            _bound_observation(supplier, saved, technical, step.native_evidence_ref, record)
            previous[name] = saved
        saved = previous[stage]
        if saved['identity'] != identity.as_dict():
            raise TaskConflict('Supply query changes its deciding action')
        if stage in DECLINES:
            if decline_for_supply(saved, invocation=supplier.snapshots.get(identity), plan=plan, stage=stage) != record.get('decline_binding'):
                raise TaskConflict('Supply query changes its original complete-demand decline')
        accepted, action = supplier._summary(saved['result'], stage)
        data = {'offer_score': float(plan.utility.value)}
        outcome = _transport(supplier, identity, record, saved, accepted, action, data, contractor=False)
        return _result(supplier, identity, record, saved, tick, outcome)


def query_contractor_supply_outcome(app, identity, *, organization_id, tick):
    supplier = app.supplier
    with supplier.read_guard():
        identity, record, plan = _workflow(app, supplier, identity, organization_id, tick, contractor=True)
        inputs = {k: v for k, v in plan.action_input.items() if k != 'supplier_offer_refs'}
        saved = _original_result(supplier, identity, app.worker, plan.context, inputs, key=record['key'], tick=tick)
        _bound_observation(supplier, saved, record, plan.native_evidence_ref, record)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
        selected = app._summary(saved, plan, AgentProposalRequestV1.model_validate(record['native_request']))
        if record['observed']['selected_supplier_id'] != selected:
            raise TaskConflict('Supply query changes its original Contractor preference')
        data = {'selected_supplier_id': selected, 'accepted_supplier_ids': [p['agent_id']
            for p, d in record['native_request']['inputs']['offers'] if d['accepted']]}
        outcome = _transport(supplier, identity, record, saved, True, 'select_supplier', data, contractor=True)
        return _result(supplier, identity, record, saved, tick, outcome)
