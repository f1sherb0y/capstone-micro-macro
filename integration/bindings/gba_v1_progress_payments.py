"""Read own actual aggregate progress-payment events, without a cash ledger."""
from copy import deepcopy
import hashlib
import math

from src.coordination.tasks import TaskConflict, task_digest


def with_own_progress_payment_history(assembly, *, request, memory, read_guard):
    """Bind actual own aggregate payment observations to this later tender.

    This private preference source supplies no detailed payment ledger,
    certification, cash or proof that an outstanding obligation is cleared.
    """
    if not callable(read_guard):
        raise TaskConflict('Payment tender feedback requires the original writer guard')
    with read_guard():
        assembly._validate_components()
        client, engine = assembly.client, assembly.engine
        org, tick = request.agent.agent_id, request.metadata.get('tick')
        if (request.agent.role != 'Contractor' or request.operation != 'consider_tender'
                or client.organization_roles.get(org) != 'Contractor' or type(tick) is not int
                or tick != engine.current_tick or client.simulation_id != engine.simulation_id
                or memory.get('schema_version') != 'gba-v1-own-tender-context.v1'
                or memory.get('organization_id') != org or memory.get('run_id') != client.run_id
                or memory.get('simulation_id') != client.simulation_id
                or memory.get('as_of_tick') != tick or type(memory.get('project_only')) is not bool
                or memory.get('project_id') != request.inputs['project']['project_id']
                or memory.get('request_sha256') != task_digest(request.model_dump(mode='json'))
                or memory.get('context_sha256') != task_digest(
                    {k: v for k, v in memory.items() if k != 'context_sha256'})):
            raise TaskConflict('Payment tender feedback changes its actual own request or context')
        query = read_own_progress_payments(assembly, organization_id=org, tick=tick, read_guard=read_guard)
        records = [deepcopy(row) for row in query['delay_events']
            if not memory['project_only'] or row['project_id'] == memory['project_id']]
        result = deepcopy(memory)
        result['own_progress_payments'] = {'schema_version': 'gba-v1-own-tender-progress-payments.v1',
            'query': query, 'delays': records,
            'limits': 'Actual own aggregate delayed requests only; not a complete payment ledger, due debt or cash.'}
        result['context_sha256'] = task_digest({k: v for k, v in result.items() if k != 'context_sha256'})
        return result


def read_own_progress_payments(assembly, *, organization_id, tick, read_guard):
    """Only strictly earlier live native events for this Owner or Contractor.

    This is an authorized query, not evidence of an externally delivered receipt.
    Native `approved` is a request status: the source executes no bank transfer,
    cash reconciliation, independent QS certificate or debt clearance here.
    """
    if not callable(read_guard):
        raise TaskConflict('Progress-payment reading requires the original engine writer guard')
    with read_guard():
        assembly._validate_components()
        engine, client = assembly.engine, assembly.client
        role = client.organization_roles.get(organization_id)
        agent = engine.agents.get(organization_id)
        if (role not in {'Owner', 'Contractor'} or agent is None or agent.role != role
                or agent.agent_id != organization_id or client.simulation_id != engine.simulation_id
                or client.tasks.run_id != client.run_id or type(tick) is not int or tick != engine.current_tick):
            raise TaskConflict('Progress-payment query changes its original own party, run or current clock')
        requests, delays, seen = [], [], set()
        for event in engine.events.events:
            if event.event_type not in {'payment_requested', 'payment_delayed'} or event.tick >= tick:
                continue
            data = event.data
            party_field = 'owner_id' if role == 'Owner' else 'contractor_id'
            if data.get(party_field) != organization_id:
                continue
            project = engine.projects.get(event.project_id)
            original = event.model_dump(mode='json')
            logged = [] if project is None else [r for r in project.event_log if r['event_id'] == event.event_id]
            if (len(logged) != 1 or task_digest(logged[0]) != task_digest(original)
                    or event.event_id in seen or project.owner_id != data.get('owner_id')
                    or client.organization_roles.get(data.get('owner_id')) != 'Owner'
                    or client.organization_roles.get(data.get('contractor_id')) != 'Contractor'
                    or event.agent_id != data.get('contractor_id' if event.event_type == 'payment_requested' else 'owner_id')):
                raise TaskConflict('Progress-payment history lost its exact native event or original parties')
            seen.add(event.event_id)
            amount = data.get('payment_amount')
            if type(amount) not in {int, float} or not math.isfinite(amount) or amount < 0:
                raise TaskConflict('Native progress-payment amount has no supported finite source value')
            row = {'event_id':event.event_id, 'project_id':event.project_id, 'tick':event.tick,
                'owner_id':data['owner_id'], 'contractor_id':data['contractor_id'],
                'payment_amount':amount, 'source_event_sha256':task_digest(original)}
            if event.event_type == 'payment_requested':
                if data.get('payment_status') not in {'approved', 'delayed'}:
                    raise TaskConflict('Unknown native payment-request status needs diagnosis')
                row.update(payment_status=data['payment_status'], certified_progress=data.get('certified_progress'))
                requests.append(row)
            else:
                delays.append(row)
        # A delay event is a second observation of the same request, never an
        # additional payment, debit, debt or repeated unit of requested work.
        for delay in delays:
            matches = [r for r in requests if all(r[k] == delay[k] for k in
                ('project_id', 'tick', 'owner_id', 'contractor_id', 'payment_amount'))
                and r['payment_status'] == 'delayed']
            if len(matches) != 1:
                raise TaskConflict('Native payment delay lacks its exact original delayed request')
            delay['request_event_id'] = matches[0]['event_id']
        for request in requests:
            matches = [d for d in delays if d['request_event_id'] == request['event_id']]
            if len(matches) != (1 if request['payment_status'] == 'delayed' else 0):
                raise TaskConflict('Native payment request has inconsistent actual delay observations')
        order = lambda row:(row['tick'], row['project_id'], row['event_id'])
        record = {'schema_version':'gba-v1-own-progress-payments.v1',
            'run_id':client.run_id, 'simulation_id':engine.simulation_id, 'organization_id':organization_id,
            'role':role, 'as_of_tick':tick, 'source':'authorized_own_native_progress_payment_query',
            'payment_requests':sorted(requests,key=order), 'delay_events':sorted(delays,key=order),
            'amount_unit':'native_contract_sum_unit', 'currency':None,
            'limits':['Aggregate native request observations only, not independent QS certification.',
                'Approved request is not cash execution, bank transfer, received payment or cleared debt.',
                'No cash, debt or interest balance is inferred; no currency conversion is performed.',
                'Empty history means no authenticated earlier native event, not absence of obligations.',
                'Query result is private to the original party; no external delivery is claimed.']}
        from integration.bootstrap import enable_gba_imports
        root = enable_gba_imports() / 'gba_construction_sim/backend'
        record['source_hashes'] = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
            ('simulation/project_state_update_engine.py', 'simulation/event_system.py', 'models/event.py')}
        record['record_sha256'] = task_digest(record)
        return deepcopy(record)
