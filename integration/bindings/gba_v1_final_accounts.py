"""Authorized native final-account observations, without settlement accounting."""
from copy import deepcopy
import hashlib
import math

from src.coordination.tasks import TaskConflict, task_digest


def with_own_final_account_history(assembly, *, request, memory, read_guard):
    """Bind the existing named-party query to this actual Contractor request.

    A later tender can consume observed aggregate closeout as a private
    preference. No settlement amount becomes cash or released capacity.
    """
    if not callable(read_guard):
        raise TaskConflict('Final-account tender feedback requires the original writer guard')
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
                or memory.get('request_sha256') != task_digest(request.model_dump(mode='json'))
                or memory.get('context_sha256') != task_digest(
                    {k: v for k, v in memory.items() if k != 'context_sha256'})):
            raise TaskConflict('Final-account tender feedback changes its actual own request or context')
        query = read_own_final_accounts(assembly, organization_id=org, tick=tick, read_guard=read_guard)
        records = [deepcopy(row) for row in query['settlements']
            if not memory['project_only'] or row['project_id'] == memory['project_id']]
        result = deepcopy(memory)
        result['own_final_accounts'] = {
            'schema_version': 'gba-v1-own-tender-final-accounts.v1',
            'query': query, 'records': records,
            'limits': 'Actual own aggregate settlements only; no cash, debt clearance, profit or resource release.'}
        result['context_sha256'] = task_digest({k: v for k, v in result.items() if k != 'context_sha256'})
        return result


def read_own_final_accounts(assembly, *, organization_id, tick, read_guard):
    """Read strictly earlier aggregate events for their original named party.

    The frozen lifecycle emits these events and releases roles itself. This
    query does not produce a QS certificate, cash movement, handover, release
    of liability or a new formal closeout. In particular, event wording is not
    evidence that detailed payment obligations were actually extinguished.
    """
    if not callable(read_guard):
        raise TaskConflict('Final-account history requires the original engine writer guard')
    with read_guard():
        assembly._validate_components()
        engine, client = assembly.engine, assembly.client
        agent = engine.agents.get(organization_id)
        role = client.organization_roles.get(organization_id)
        if (role not in {'Owner', 'Contractor', 'QS'} or agent is None
                or agent.agent_id != organization_id or agent.role != role
                or client.simulation_id != engine.simulation_id or client.tasks.run_id != client.run_id
                or type(tick) is not int or tick != engine.current_tick):
            raise TaskConflict('Final-account query changes its current own party, run or clock')
        party_field = {'Owner': 'owner_id', 'Contractor': 'contractor_id', 'QS': 'qs_id'}[role]
        reviews, settlements, seen = [], [], set()
        for event in engine.events.events:
            if (event.event_type not in {'final_account_review_started', 'final_account_settled'}
                    or event.tick >= tick or event.data.get(party_field) != organization_id):
                continue
            project = engine.projects.get(event.project_id)
            data = event.data
            logged = [] if project is None else [e for e in project.event_log if e['event_id'] == event.event_id]
            original = event.model_dump(mode='json')
            if (len(logged) != 1 or task_digest(logged[0]) != task_digest(original)
                    or event.event_id in seen or data.get('owner_id') != project.owner_id
                    or data.get('contractor_id') != project.selected_contractor_id
                    or data.get('qs_id') != project.selected_qs_id
                    or event.agent_id != (data.get('qs_id') or data.get('owner_id'))):
                raise TaskConflict('Final-account history lost its original event or exact named parties')
            for field, expected_role in (('owner_id', 'Owner'), ('contractor_id', 'Contractor'), ('qs_id', 'QS')):
                party = data.get(field)
                if (field == 'owner_id' or party is not None) and client.organization_roles.get(party) != expected_role:
                    raise TaskConflict('Final-account history changes an original party role')
            seen.add(event.event_id)
            amount_fields = ('contract_sum', 'actual_cost') if event.event_type == 'final_account_review_started' else (
                'contract_sum', 'final_account_amount')
            for field in amount_fields:
                value = data.get(field)
                if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                    raise TaskConflict('Final-account history has an unsupported original amount')
            row = {'event_id': event.event_id, 'project_id': event.project_id, 'tick': event.tick,
                'owner_id': data['owner_id'], 'contractor_id': data.get('contractor_id'), 'qs_id': data.get('qs_id'),
                'source_event_sha256': task_digest(original),
                **{field: data[field] for field in amount_fields}}
            if event.event_type == 'final_account_review_started':
                reviews.append(row)
            else:
                if data['final_account_amount'] < data['contract_sum']:
                    raise TaskConflict('Final-account amount contradicts its frozen native aggregate rule')
                # Retain the exact observed risk, without treating it as a
                # defect register, current debt, guarantee or clearance.
                for field in ('claim_risk', 'dispute_risk', 'delay_days', 'cost_overrun_ratio'):
                    value = data.get(field)
                    if type(value) not in {int, float} or not math.isfinite(value):
                        raise TaskConflict('Final-account history lacks its original aggregate metrics')
                    row[field] = value
                row.update(outcome='native_aggregate_final_account_settled',
                    payment_execution_status='not_proven', obligation_clearance_status='not_proven')
                settlements.append(row)
        if len({r['project_id'] for r in settlements}) != len(settlements):
            raise TaskConflict('Final-account history repeats settlement for the same original project')
        for settlement in settlements:
            matches = [r for r in reviews if r['project_id'] == settlement['project_id']
                and r['tick'] < settlement['tick'] and all(r[k] == settlement[k] for k in
                    ('owner_id', 'contractor_id', 'qs_id'))]
            if len(matches) > 1:
                raise TaskConflict('Final-account history has ambiguous actual review origins')
            # An initial project may explicitly start with an existing review.
            # Its absence from this run is retained, never synthesized.
            settlement['observed_review_event_id'] = matches[0]['event_id'] if matches else None
        order = lambda r: (r['tick'], r['project_id'], r['event_id'])
        from integration.bootstrap import enable_gba_imports
        root = enable_gba_imports() / 'gba_construction_sim/backend'
        record = {'schema_version': 'gba-v1-own-final-accounts.v1',
            'run_id': client.run_id, 'simulation_id': engine.simulation_id,
            'organization_id': organization_id, 'role': role, 'as_of_tick': tick,
            'source': 'authorized_own_native_final_account_query',
            'reviews': sorted(reviews, key=order), 'settlements': sorted(settlements, key=order),
            'amount_unit': 'native_contract_sum_unit', 'currency': None,
            'source_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
                'simulation/project_lifecycle_engine.py', 'simulation/event_system.py', 'models/event.py')},
            'limits': ['Original aggregate events only, not a micro QS certificate or detailed final-account acceptance.',
                'No cash execution, received payment, cleared debt, defects, handover or liability release is inferred.',
                'A missing review event may predate this run; no original review or micro action is manufactured.',
                'Query is private to an actual named party; no delivery receipt or competitor/private account data is added.',
                'No amount is converted or used as available reinvestment cash; empty history does not clear obligations.']}
        record['record_sha256'] = task_digest(record)
        return deepcopy(record)
