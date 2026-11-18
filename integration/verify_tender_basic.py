"""GOAL 2: one fresh run of GOAL 1 inputs, explicit refusal and duplicate checks.

Uses the same builders and bound host runner as integration.run. No recovery,
fault injection, engine patching or resubmission of unknown business is used.
"""
import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import shutil

from integration.verify_tender_closed_loop import (
    ROOT, _write, database_records, macro_hashes, one, read, require, verify_bundle, verify_scenario,
)
from src.coordination.tasks import TaskIdentity, task_digest


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_history(directory):
    manifest = read(directory / 'artifact-manifest.json')
    actual = {name: file_hash(directory / name) for name in manifest['files']}
    require(actual == manifest['files'], 'GOAL 1 historical artifacts changed')
    return {'manifest_sha256': file_hash(directory / 'artifact-manifest.json'), 'files': actual}


def business_snapshot(assembly, runtime):
    client, engine = assembly.client, assembly.engine
    bus = engine.lifecycle_engine.interaction_sessions.message_bus
    messages = [asdict(envelope) for envelope in bus.peek()]
    with client.tasks._lock:
        journal = list(client.tasks._db.iterdump())
        task_count = client.tasks._db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    return {'tick': engine.current_tick, 'task_count': task_count,
        'journal_sha256': task_digest(journal),
        'simulation_sha256': task_digest(engine.response().model_dump(mode='json')),
        'event_count': len(engine.events.events),
        'events_sha256': task_digest([event.model_dump(mode='json') for event in engine.events.events]),
        'observation_sha256': file_hash(runtime / 'observations.json'),
        'message_count': len(messages), 'messages_sha256': task_digest(messages)}


def check_duplicates(assembly, extension, runtime):
    from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
    from integration.contractor_tender_request_trigger import ContractorTenderRequestTrigger

    client = assembly.client
    host = client.proposal_handlers[('Contractor', 'consider_tender')]._recovery_host()
    records = database_records(runtime / 'tasks.sqlite')
    submitted = one(records['gba_tender_feedback'], lambda r:
        r['organization_id'] == 'dev-contractor-a' and r['effect'] == 'native_bid_submitted',
        'Need a known completed native submission before repeating its request')
    trigger = one(list(records['metadata'].values()), lambda r:
        r.get('schema_version') == ContractorTenderRequestTrigger.VERSION and
        r.get('bid_result_sha256') == submitted['micro_result_sha256'], 'Missing original completed request')
    request = AgentProposalRequestV1.model_validate(trigger['native_request'])
    original = client.tasks.get(TaskIdentity(**submitted['proposal_identity']))['output']
    with extension.extension.writer_guard():
        observed = host.query_submission(request)
        require(observed['status'] == 'observed' and observed['effect'] == 'native_bid_submitted',
                'Unknown native submission must never be repeated')
        before = business_snapshot(assembly, runtime)
        call_count = len(client.evidence()['calls'])
        responses = [client.propose(request).model_dump(mode='json') for _ in range(2)]
        require(all(response == original for response in responses), 'Repeated request changed its saved response')
        require(host.query_submission(request) == observed, 'Read-only submission query changed')
        after = business_snapshot(assembly, runtime)
        calls = client.evidence()['calls'][call_count:]
        require(len(calls) == 2 and all(call['status'] == 'cache_hit' for call in calls),
                'Completed duplicate was not handled by the existing cache')
        require(before == after, 'Duplicate request changed tasks, formal state, events, observations or messages')
    return {'status': 'passed', 'original_request': request.model_dump(mode='json'),
        'known_submission_query': observed, 'duplicate_calls': calls, 'same_saved_response': True,
        'response_sha256': task_digest(original), 'before': before, 'after': after,
        'business_or_messages_reexecuted': False}


def run_checks(source, output):
    from integration.bootstrap import enable_gba_imports
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    from integration.bindings.gba_v1 import build_module_engine
    from integration.contractor_tender_development import configure_assembly
    from integration.module_host import build_module_host_client, configure_module_host_extension, load_module_host_configuration
    from integration.native_routes import build_agent_client

    source, output = Path(source).resolve(), Path(output).resolve()
    history_before, macro_before = verify_history(source), macro_hashes()
    verify_bundle(source / 'baseline/input')
    require(read(ROOT / 'config/tender_closed_loop.json') == read(source / 'scenario.json'),
            'Current normal configuration differs from the accepted GOAL 1 configuration')
    output.mkdir(parents=True, exist_ok=False)
    _write(output, 'source.json', {'goal1_directory': str(source), 'history_before': history_before,
        'normal_input': 'Exact bytes copied from GOAL 1 baseline/input; existing absolute source references retained.',
        'recovery_used': False})
    _write(output, 'macro-before.json', macro_before)
    shutil.copytree(source / 'baseline/input', output / 'input')
    require(all(file_hash(output / 'input' / p.relative_to(source / 'baseline/input')) == file_hash(p)
                for p in (source / 'baseline/input').rglob('*') if p.is_file()), 'Fresh run inputs changed')
    verify_bundle(output / 'input')
    request = SimulationCreateRequest.model_validate(read(output / 'input/macro-request.json'))
    runtime = output / 'runtime'
    runtime.mkdir()
    configuration = load_module_host_configuration(output / 'input/native-host.json')
    extension_config = load_module_host_configuration(output / 'input/assembly-host.json')
    client = extension = None
    try:
        client, host_evidence = build_module_host_client(factory=build_agent_client,
            specification='integration.native_routes:build_agent_client', request=request,
            output_directory=runtime, offline=True, configuration=configuration)
        assembly = build_module_engine(request, client)
        extension = configure_module_host_extension(assembly=assembly, hook=configure_assembly,
            specification='integration.contractor_tender_development:configure_assembly', request=request,
            output_directory=runtime, offline=True, host_evidence=host_evidence,
            configuration=configuration, extension_configuration=extension_config)
        print('Running unchanged GOAL 1 baseline inputs in a fresh engine and directory', flush=True)
        try:
            extension.run_engine()
        finally:
            _write(runtime, 'result.json', {'macro_mode': 'gba_v1_module', 'requested_model_mode': 'offline',
                'module_host': host_evidence, 'module_host_extension': extension.evidence(),
                'macro_assembly': assembly.evidence(), 'simulation': assembly.engine.response().model_dump(mode='json')})
        normal = verify_scenario(output)
        _write(output, 'normal-chain-evidence.json', normal)
        # Reuse the same chain's explicit later refusal, already proved in GOAL 1.
        followup = one(assembly.engine.response().model_dump(mode='json')['project_results'],
            lambda p: p['project_id'] == 'dev-followup-project', 'Missing refusal project')
        require(not followup['bids'] and not followup['contracts'] and followup['selected_contractor_id'] is None,
                'Refusal created a false successful bid, contract or selection')
        events = [e for e in followup['event_log'] if e['event_type'] in {'bid_submitted', 'bid_declined'}]
        require(len(events) == 2 and all(e['event_type'] == 'bid_declined' for e in events),
                'Refused tender was reported as a successful submission')
        _write(output, 'refusal.json', {'status': 'passed', 'reused_scenario': 'GOAL 1 tick-3 explicit refusal',
            'stopped_operation': 'Both current tender attempts; the simulation itself may finish normally.',
            'micro_choices': [{'organization_id': c['organization_id'],
                'A01': c['later_screening']['result']['payload']['choice'],
                'A02': c['later_bid']['result']['payload']['choice']} for c in normal['chains']],
            'actual_events': events, 'actual_bids': followup['bids'], 'false_success': False})
        print('Fresh normal run and explicit refusal verified; checking completed duplicates', flush=True)
        _write(output, 'duplicates.json', check_duplicates(assembly, extension, runtime))
        macro_after, history_after = macro_hashes(), verify_history(source)
        require(macro_before == macro_after and history_before == history_after,
                'Macro or original historical output changed')
        _write(output, 'macro-after.json', macro_after)
        summary = {'status': 'passed', 'stage': 'GOAL 2 basic checks only',
            'normal_run': {k: v for k, v in normal.items() if k != 'chains'},
            'same_configuration_and_input_bytes': True, 'historical_files_preserved': len(history_after['files']),
            'representative_refusal': 'passed: later bids stopped, no bid/contract/selection success',
            'duplicate_request': 'passed: two cache hits; journal, state, events, observations and message log unchanged',
            'macro_unchanged': True, 'recovery_used': False,
            'scope': 'No cross-process recovery, automatic continuation, fault injection or broader stability acceptance.'}
        _write(output, 'checks.json', summary)
        return summary
    except Exception as error:
        _write(output, 'failure.json', {'status': 'failed', 'error_type': type(error).__name__, 'message': str(error)})
        raise
    finally:
        if extension is not None:
            extension.close()
        if client is not None:
            client.close()


def main(argv=None):
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'output/integration/goal1_tender_closed_loop_20261018_01')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_checks(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
