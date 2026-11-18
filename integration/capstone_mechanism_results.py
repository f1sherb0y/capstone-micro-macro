"""Read-only checks for R/S/D3/S4 results, preserving original multi-call audits.

The old report assumes one call per A02 and is therefore not reused as a
universal verifier. This checks the declared experiment's execution/feedback
links and reports business completion separately from technical integrity.
"""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from integration.contractor_tender_development import verify_bundle
from integration.verify_goal4_integration import journal
from src.coordination.tasks import TaskIdentity, task_digest


def read(path):
    return json.loads(Path(path).read_bytes())


def verify(directory, *, arm=None, source_directory=None):
    directory = Path(directory)
    source = Path(source_directory) if source_directory is not None else directory / 'input'
    verify_bundle(source)
    config = read(source / 'case-config.json')
    arm = arm or config['research_arm']
    if arm not in {'R', 'S', 'D3', 'S4'}:
        raise ValueError('Explicit mechanism arm required')
    assert read(directory / 'exit.json')['exit_code'] == 0
    initial = read(source / 'macro-request.json')
    output = read(directory / 'runtime/result.json')
    simulation = output['simulation']
    host = output['module_host_extension']['host']
    captured = read(directory / 'runtime/native-run-state.json')
    events = host['original_global_events']
    assert captured['original_global_events'] == events
    for field in ['simulation_id', 'status', 'current_tick', 'project_results']:
        assert captured['simulation'][field] == simulation[field]
    assert simulation['status'] == 'completed' and simulation['current_tick'] == initial['ticks']
    event_map = {e['event_id']: e for e in events}
    assert len(event_map) == len(events)
    assert not any(e['data'].get('agent_observer_errors') for e in events)
    project = next(p for p in simulation['project_results'] if p['project_id'] == config['case_id'])
    assert initial['initial_projects'][0]['project_id'] == project['project_id']
    allowed_pending = {}
    for record in host['lifecycle']['actions']:
        if record['state'] == 'formed':
            continue
        identity = TaskIdentity(**record['identity'])
        observed = event_map[record['observed']['event_id']]
        assert identity.action_id == 'CONTRACTOR-A10' and observed['event_type'] == 'payment_delayed'
        assert record['result_kind'] == 'needs_information' and record['formal_effect'] == 'not_submitted'
        allowed_pending[identity.key] = record
    tasks, metadata, workers, journal_sha = journal(directory, allowed_pending=allowed_pending)
    matches, calls, response_digests = [], 0, []
    per_task = {'R': 0, 'S': 1, 'D3': 4, 'S4': 4}[arm]
    for task_key, worker in workers.items():
        execution = worker['audit'].get('decision', {}).get('execution', {})
        count = execution.get('model_calls', 0)
        calls += count
        if count:
            assert worker['identity']['action_id'] == 'CONTRACTOR-A02'
            assert execution['status'] == 'selected' and count == per_task
            if execution.get('calls'):
                response_digests += [r['response_sha256'] for r in execution['calls']]
            else:
                response_digests.append(execution['response_sha256'])
        if worker['identity']['action_id'] != 'CONTRACTOR-A02':
            continue
        if worker['result']['kind'] != 'completed' or worker['result']['payload']['choice'] != 'submit_bid':
            continue
        org = worker['identity']['organization_id']
        bid_events = [e for e in events if e['event_type'] == 'bid_submitted' and e['agent_id'] == org
                      and e.get('project_id') == project['project_id']]
        assert len(bid_events) == 1
        event = bid_events[0]
        assert event['data']['decision_factors']['micro_result_sha256'] == worker['result_sha256']
        assert Decimal(str(event['data']['bid_price'])) == Decimal(worker['result']['payload']['bid']['price']['value'])
        matches.append({'organization_id': org, 'task_key': task_key, 'event_id': event['event_id'],
                        'event_tick': event['tick'], 'price': str(event['data']['bid_price']),
                        'model_calls': count})
    budget = host['tender']['model_host']['call_budget']
    assert budget['charged_or_reserved_calls'] == calls
    assert calls <= {'R': 0, 'S': 2, 'D3': 8, 'S4': 8}[arm]
    if config.get('cp03_control'):
        control = config['cp03_control']
        attempts = [read(p) for p in (Path(control['batch_directory']) / 'run/provider_attempts' / control['chain_id']).glob('*.json')]
        assert len(attempts) == calls and all(r['status'] == 'returned' for r in attempts)
        assert Counter(task_digest(r['raw_content']) for r in attempts) == Counter(response_digests)
    signed = [e for e in events if e['event_type'] == 'contract_awarded' and e.get('project_id') == project['project_id']]
    handoffs = []
    if signed:
        assert len(signed) == 1 and len(host['supplier']['requests']) == 2
        event = signed[0]
        for supplier in host['supplier']['requests']:
            for stage in [supplier, *[supplier[k] for k in ['screening', 'product', 'quote']]]:
                key = TaskIdentity(**stage['identity']).key
                worker = workers[key]
                received = stage['observed']['native_signed_contract']
                assert stage['result_sha256'] == worker['result_sha256']
                assert received['event_id'] == event['event_id']
                assert received['source_event_sha256'] == task_digest(event)
                assert received['signed_tick'] < received['read_tick'] == supplier['scope']['tick']
                assert received['receiving_organization_id'] == stage['identity']['organization_id']
                assert received['contractor_id'] == project['selected_contractor_id']
                assert any(r['projection'].get('content_hash') == task_digest(stage['observed']) for r in worker['source_reading'])
                handoffs.append({'source_event_id': event['event_id'], 'consumer_task_key': key,
                                 'read_tick': received['read_tick']})
    settlements = [e for e in events if e['event_type'] == 'final_account_settled' and e.get('project_id') == project['project_id']]
    feedback = []
    for record in host['opportunity']['requests']:
        observed = record['observed']
        for settlement in observed.get('own_final_accounts', {}).get('settlements', []):
            eid = settlement.get('event_id') or settlement.get('settlement_event_id')
            # Keep unrecognized shapes visible instead of inventing a link.
            if eid is None:
                feedback.append({'state': 'source_shape_requires_review', 'record_key': record.get('key')})
                continue
            event = event_map[eid]
            assert event['event_type'] == 'final_account_settled'
            assert event['project_id'] == project['project_id']
            assert settlement['source_event_sha256'] == task_digest(event)
            assert record['identity']['organization_id'] == project['owner_id']
            assert record['scope']['tick'] > event['tick']
            task_key = TaskIdentity(**record['identity']).key
            worker = workers[task_key]
            assert record['result_sha256'] == worker['result_sha256']
            assert any(s['projection'].get('content_hash') == task_digest(observed) for s in worker['source_reading'])
            feedback.append({'state': 'source_event_present', 'source_event_id': eid,
                             'source_tick': event['tick'], 'consumer_tick': record['scope']['tick'],
                             'lag_ticks': record['scope']['tick'] - event['tick'],
                             'consumer_task_key': task_key, 'consumer_record_key': record.get('key'),
                             'choice': worker['result']['payload']['choice']})
    if settlements:
        assert feedback and all(r['state'] == 'source_event_present' for r in feedback)
    return {'scope': 'CP03 native journal, bid identity/price/hash, saved global events and feedback source checks; not external project validation',
            'simulation_id': simulation['simulation_id'], 'project_id': project['project_id'], 'arm': arm,
            'technical_integrity_passed': True, 'project_stage': project['current_stage'],
            'closed': project['current_stage'] == 'closed', 'settled': bool(settlements),
            'quote_execution_links': matches, 'actual_model_calls': calls,
            'contract_handoffs': handoffs, 'expected_handoffs_if_contract_formed': 8,
            'feedback_source_records': feedback, 'feedback_complete': all(r['state'] == 'source_event_present' for r in feedback),
            'declared_payment_waits': len(allowed_pending), 'journal_sha256': journal_sha,
            'macro_performance': project['performance']}
