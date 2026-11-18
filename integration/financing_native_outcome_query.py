"""Read authenticated original financing outcomes without resubmitting business."""
from copy import deepcopy

from integration.bank_financing_private import checked_result, native_quote_summary
from integration.project_financing_feedback import project_financing_event
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def _caller(bank, identity, organization_id, tick, role, actions):
    identity = TaskIdentity(**(identity.as_dict() if isinstance(identity, TaskIdentity) else identity))
    bank._check()
    client, engine = bank.assembly.client, bank.assembly.engine
    if (identity.run_id != client.run_id or identity.organization_id != organization_id
            or identity.role != role or identity.action_id not in actions or identity.purpose != 'action'
            or client.organization_roles.get(organization_id) != role
            or type(tick) is not int or tick != engine.current_tick):
        raise TaskConflict('Financing query changes its original organization, action or current native clock')
    return identity


def _original_result(bank, identity, worker, context, action_input, *, key, tick):
    snapshot = bank.snapshots.get(identity)
    if (snapshot['identity'] != identity.as_dict() or snapshot['context'] != context.model_dump(mode='json')
            or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or any(snapshot['action_input'].get(k) != v for k, v in action_input.items())
            or identity.request_id != key + ':' + context.contract_ref.id):
        raise TaskConflict('Financing query substitutes its original invocation, input or snapshot')
    current = context.model_copy(update={
        'business_time': context.business_time.model_copy(update={'offset': tick})}, deep=True)
    grants = bank.organizations.grants(current, identity.action_id, identity.role)
    saved = checked_result(worker, identity)
    readable = {r.key() for grant in grants for r in grant.readable_refs} & {r.key() for r in context.visible_refs}
    if (any(g.organization_id != identity.organization_id for g in grants)
            or any(Reference.model_validate(row['ref']).key() not in readable for row in saved['source_reading'])):
        raise TaskConflict('Financing query lost current permission for original private sources')
    return saved


def _matching_events(assembly, record, organization_id, event_type):
    """Read matching original logs, failing closed on ambiguity or divergence."""
    scope = record['scope']
    project = assembly.engine.projects.get(scope['project_id'])
    if project is None or project.owner_id != scope['owner_id']:
        raise TaskConflict('Financing query lost its original native project or owner')

    def matches(e):
        return (e['event_type'] == event_type and e['agent_id'] == organization_id
                and e['project_id'] == scope['project_id'] and e['tick'] == scope['tick'])

    local = [e for e in project.event_log if matches(e)]
    global_ = [e.model_dump(mode='json') for e in assembly.engine.events.events
               if matches(e.model_dump(mode='json'))]
    if (len({e['event_id'] for e in local}) != len(local)
            or len({e['event_id'] for e in global_}) != len(global_)
            or {e['event_id']: task_digest(e) for e in local} != {e['event_id']: task_digest(e) for e in global_}):
        raise TaskConflict('Financing query requires matching original global and project native events')
    if len(local) > 1:
        raise TaskConflict('Financing query has ambiguous original native outcomes')
    if local and local[0]['data'].get('native_financing_scope') != scope:
        raise TaskConflict('Financing query changes its original native event scope')
    return local


def _result(bank, identity, record, saved, tick, outcome):
    result = {'schema_version': 'native-financing-outcome-query.v1',
        'status': 'unknown' if outcome is None else 'observed',
        'run_id': identity.run_id, 'simulation_id': bank.assembly.client.simulation_id,
        'organization_id': identity.organization_id, 'queried_at_tick': tick,
        'original_decision_identity': identity.as_dict(),
        'original_native_request_id': record['native_request']['request_id'],
        'native_scope': deepcopy(record['scope']), 'micro_result_sha256': saved['result_sha256'],
        'native_outcome': deepcopy(outcome),
        'limits': ['Absence is unknown, not nonexecution or permission to resubmit.',
                   'A bank indicative decision or Owner selection is not a registered loan, signed arrangement, drawdown, disbursement, cash receipt or cleared debt.',
                   'Read-only original result query; no processor replay, new tasks, waiting-condition repair or business-time advancement.']}
    result['query_sha256'] = task_digest(result)
    return result


def query_bank_financing_outcome(bank, identity, *, organization_id, tick):
    with bank.read_guard():
        identity = _caller(bank, identity, organization_id, tick, 'Bank', {'BANK-A02', 'BANK-A04'})
        rows = [r for r in bank._records() if r.get('terminal_action') == identity.action_id
                and r.get('steps', {}).get(identity.action_id, {}).get('identity') == identity.as_dict()]
        if len(rows) != 1:
            raise TaskConflict('Financing query needs its one original terminal workflow')
        record = rows[0]
        scope, original = record['scope'], record['native_request']
        if (record['state'] != 'formed' or original['agent']['agent_id'] != organization_id
                or original['operation'] != 'consider_financing' or record['source_file_sha256'] != bank.settings.file_sha256
                or record['key'] != bank.PREFIX + task_digest([bank.assembly.client.simulation_id,
                    organization_id, original['request_id'], scope]) or not 1 <= scope['tick'] <= tick):
            raise TaskConflict('Financing query substitutes its original workflow, request or scope')
        plans = [p for p in bank.plans if (p.organization_id, p.project_id, p.borrower_id, p.tick) == (
            organization_id, scope['project_id'], scope['owner_id'], scope['tick'])]
        if len(plans) != 1:
            raise TaskConflict('Financing query lost its original immutable source plan')
        plan, = plans
        actions = [a for a in bank.workers if a in plan.steps]
        actions = actions[:actions.index(identity.action_id) + 1]
        if set(record['steps']) != set(actions):
            raise TaskConflict('Financing query substitutes its original executed prefix')
        previous = {}
        for action in actions:
            step, origin = plan.steps[action], record['steps'][action]
            stage = TaskIdentity(**origin['identity'])
            if (stage.run_id != identity.run_id or stage.organization_id != organization_id
                    or stage.role != 'Bank' or stage.action_id != action or stage.purpose != 'action'):
                raise TaskConflict('Financing query substitutes an original pipeline stage')
            saved = _original_result(bank, stage, bank.workers[action], step.context, step.action_input,
                                     key=record['key'], tick=tick)
            if any(origin.get(k) != saved[k] for k in ('result_sha256', 'record_sha256', 'source_reading_sha256')):
                raise TaskConflict('Financing query conflicts with the original saved result')
            previous[action] = saved
        intake = previous['BANK-A02']['result']['payload']['choice']
        if identity.action_id == 'BANK-A02':
            if intake != 'decline':
                raise TaskConflict('Financing query requires an original terminal intake refusal')
            accepted, data = False, {'approved_amount': 0.0, 'interest_rate': 0.0, 'conditions': []}
        else:
            if intake != 'accept_for_review':
                raise TaskConflict('Financing query cannot quote without original accepted intake')
            objects = [{'ref': row['ref'], 'value': row['projection']} for row in saved['source_reading']]
            accepted, data = native_quote_summary(saved, objects, periods_per_year=plan.periods_per_year)
        data['requested_amount'] = original['inputs']['requested_amount']
        if record['native_summary'] != {'accepted': accepted, 'data': data}:
            raise TaskConflict('Financing query substitutes its original native summary')
        events = _matching_events(bank.assembly, record, organization_id, 'bank_financing_decision')
        outcome = None
        if events:
            event, = events
            tasks = bank.assembly.client.tasks.for_organization(run_id=identity.run_id, organization_id=organization_id)
            proposals = [t['output'] for t in tasks if t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'consider_financing' and t['state'] == 'output_formed'
                and t['output'].get('factors', {}).get('native_financing_scope') == scope]
            finals = [t['output'] for t in tasks if t['identity']['purpose'] == 'decide'
                and t['identity']['action_id'] == 'bank_project_financing' and t['state'] == 'output_formed'
                and t['output'].get('data', {}).get('native_financing_scope') == scope]
            if len(proposals) != 1 or len(finals) != 1:
                raise TaskConflict('Financing query lost its original proposal or final response')
            proposal, final = proposals[0], finals[0]
            action = 'approve_financing' if accepted else 'reject_financing'
            fields = {'micro_action_id': identity.action_id, 'micro_task_key': identity.key,
                      'micro_result_sha256': saved['result_sha256'], 'native_financing_scope': scope}
            if (proposal['accepted'] != accepted or final['decision'] != accepted or event['data'].get('accepted') != accepted
                    or any(v.get('action_type') != action for v in (proposal, final, event['data']))
                    or proposal['data'] != data or task_digest(proposal) != record['proposal_response_sha256']
                    or proposal['factors'].get('micro_pipeline') != record['steps']
                    or any(v.get('proposal_response_sha256') != record['proposal_response_sha256'] for v in (final['data'], event['data']))
                    or any(v.get(k) != expected for v in (proposal['factors'], final['data'], event['data']) for k, expected in fields.items())
                    or any(v.get(k) != expected for v in (final['data'], event['data']) for k, expected in data.items())):
                raise TaskConflict('Financing query substitutes its actual original bank decision')
            from gba_construction_sim.backend.agents.contracts import AgentObservationV1
            projection = project_financing_event(AgentObservationV1.model_validate(event), bank.assembly.client.organization_roles)
            messages = [r for r in bank.assembly.client.inbox.for_organization(run_id=identity.run_id, organization_id=organization_id)
                        if r['event_id'] == event['event_id']]
            if len(messages) != 1 or messages[0]['payload'] != projection.get(organization_id):
                raise TaskConflict('Financing query lost its original private event projection')
            outcome = {'event_id': event['event_id'], 'event_type': event['event_type'], 'event_sha256': task_digest(event),
                       'tick': scope['tick'], 'accepted': accepted, 'action_type': action, **deepcopy(data)}
        return _result(bank, identity, record, saved, tick, outcome)


def query_owner_financing_outcome(owner, identity, *, organization_id, tick):
    bank = owner.bank
    with bank.read_guard():
        identity = _caller(bank, identity, organization_id, tick, 'Owner', {'OWN-A05'})
        rows = [r for r in bank._records(prefix=owner.PREFIX) if r.get('identity') == identity.as_dict()]
        if len(rows) != 1:
            raise TaskConflict('Financing query needs its one original Owner workflow')
        record, = rows
        scope, original = record['scope'], record['native_request']
        if (record['state'] != 'formed' or scope['owner_id'] != organization_id
                or original['agent']['agent_id'] != organization_id or original['operation'] != 'select_financing_offer'
                or record['key'] != owner.PREFIX + task_digest([bank.assembly.client.simulation_id, scope, original['request_id']])
                or not 1 <= scope['tick'] <= tick):
            raise TaskConflict('Financing query substitutes its original Owner workflow or request')
        plans = [p for p in owner.plans if (p.organization_id, p.project_id, p.tick) == (
            organization_id, scope['project_id'], scope['tick'])]
        if len(plans) != 1:
            raise TaskConflict('Financing query lost its original immutable Owner plan')
        plan, = plans
        # Offers are dynamically disclosed in the original snapshot; static
        # action fields must match, while original snapshot hashes pin all offers.
        inputs = {k: v for k, v in plan.action_input.items() if k not in {'offers', 'funding_lines'}}
        saved = _original_result(bank, identity, owner.worker, plan.context, inputs, key=record['key'], tick=tick)
        if record['result_sha256'] != saved['result_sha256']:
            raise TaskConflict('Financing query conflicts with its original Owner result')
        kind='project_financing_deferred' if saved['result']['payload']['choice']=='no_finance' else 'project_financing_selected'
        events = _matching_events(bank.assembly, record, organization_id, kind)
        outcome = None
        if events:
            current = plan.model_copy(update={'tick': tick,
                'context': plan.context.model_copy(update={
                    'business_time': plan.context.business_time.model_copy(update={'offset': tick})}, deep=True)}, deep=True)
            outcomes = owner._history(current, include_current=True, decision_task_key=identity.key)
            if len(outcomes) != 1 or outcomes[0]['event_id'] != events[0]['event_id']:
                raise TaskConflict('Financing query lacks one authenticated original Owner selection')
            outcome = {**outcomes[0], 'event_type': events[0]['event_type'], 'event_sha256': task_digest(events[0])}
        return _result(bank, identity, record, saved, tick, outcome)
