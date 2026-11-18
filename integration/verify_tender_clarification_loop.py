"""Fixed 3A business run: native QS reply -> revised micro decision -> later feedback.

Reuses the existing scenario builder, integration.run and original processors.
This is business acceptance, not a new source-discovery/audit workflow.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import build_feedback_bundle, verify_bundle, _write
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from integration.verify_tender_basic import file_hash, verify_history
from src.coordination.tasks import TaskIdentity, task_digest


def verify_run(directory):
    directory = Path(directory)
    verify_bundle(directory / 'input')
    initial = read(directory / 'input/macro-request.json')
    require(all(not p['bids'] and not p['contracts'] and p['selected_contractor_id'] is None
                for p in initial['initial_projects']), 'Prefilled formal business result')
    result = read(directory / 'runtime/result.json')
    simulation = result['simulation']
    require(result['macro_mode'] == 'gba_v1_module' and result['requested_model_mode'] == 'offline'
            and simulation['status'] == 'completed' and simulation['current_tick'] == 3,
            'Expected the completed original three-tick offline window')
    database = directory / 'runtime/tasks.sqlite'
    before = file_hash(database)
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tables = {table: [json.loads(v) for v, in db.execute('SELECT record FROM ' + table)]
                  for table in ('tasks', 'invocation_snapshots', 'contractor_screening_results',
                                'contractor_bid_results', 'qs_procurement_results', 'gba_tender_feedback')}
        metadata = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM metadata')}
    rows = lambda prefix: [v for k, v in metadata.items() if k.startswith(prefix + ':')]
    key = lambda identity: TaskIdentity(**identity).key
    tasks = {key(r['identity']): r for r in tables['tasks']}
    snapshots = {key(r['identity']): r for r in tables['invocation_snapshots']}
    actions = {key(r['identity']): r for table in ('contractor_screening_results',
        'contractor_bid_results', 'qs_procurement_results') for r in tables[table]}
    require(all(t['state'] == 'output_formed' for t in tasks.values()), 'Unfinished technical task')

    def action(identity):
        k = key(identity)
        saved, snapshot = actions[k], snapshots[k]
        digest_valid(saved)
        digest_valid(snapshot, 'snapshot_sha256')
        require(saved['result_sha256'] == task_digest(saved['result']) == tasks[k]['output_sha256']
                and saved['result'] == tasks[k]['output'], 'Action/result/task mismatch')
        # Original A02 records retain their audit and invocation, rather than
        # the typed source_reading fields present on A01 and QS-A05 records.
        if identity['action_id'] != 'CONTRACTOR-A02':
            require(task_digest(saved['source_reading']) == saved['source_reading_sha256'], 'Source reading mismatch')
        require(task_digest(snapshot['action_input']) == identity['input_sha256']
                and task_digest(snapshot['context']) == identity['context_sha256'], 'Source/input mismatch')
        return saved

    triggers = rows('tender_request_trigger')
    require(len(triggers) == 4, 'Expected two enterprises in both native rounds')
    reply_chains = []
    for trigger in triggers:
        digest_valid(trigger)
        require(trigger['state'] == 'selected', 'Unresolved request')
        original = action(trigger['screening_identity'])
        successor = action(trigger['screening_successor_identity'])
        qs = action(trigger['clarification_response_identity'])
        bid = action(trigger['bid_identity'])
        require(original['result']['payload']['choice'] == 'clarify'
                and qs['result']['payload']['choice'] == 'publish_authorized', 'No original question/authority')
        require(original['result_sha256'] == trigger['screening_result_sha256']
                and successor['result_sha256'] == trigger['screening_successor_result_sha256']
                and bid['result_sha256'] == trigger['bid_result_sha256'], 'Trigger/action correlation changed')
        old_package, new_package = [r['result']['payload']['package_ref'] for r in (original, successor)]
        require(old_package['id'] == new_package['id'] and old_package['version'] == '1'
                and new_package['version'] == '2', 'Expected an immutable original and new package version')
        question = one(rows('gba_tender_clarification_request'),
            lambda r: r['binding']['metadata']['micro_identity'] == original['identity'], 'Missing actual question')
        reply = one(rows('gba_tender_clarification_response'),
            lambda r: r['binding']['metadata']['micro_identity'] == qs['identity'], 'Missing actual reply')
        for claim in (question, reply):
            digest_valid(claim)
            require(claim['phase'] == 'published' and claim['message'] is not None, 'Message not published')
            require(all(claim['message'][f] == claim['binding'][f]
                for f in ('session_id', 'sender_id', 'recipient_ids', 'tick', 'topic', 'content', 'metadata')),
                'Published native message differs from its original binding')
        require(reply['binding']['metadata']['question_message_sha256'] == task_digest(question['message'])
                and reply['binding']['metadata']['micro_result_sha256'] == qs['result_sha256']
                and reply['binding']['recipient_ids'] == [trigger['organization_id']], 'Reply recipient/origin changed')
        consumed = one(rows('contractor_clarification_consumption'),
            lambda r: r['record_sha256'] == trigger['clarification_consumption_sha256'], 'Missing reply consumption')
        digest_valid(consumed)
        require(consumed['response_message_sha256'] == task_digest(reply['message'])
                and consumed['qs_record_sha256'] == qs['record_sha256']
                and consumed['original_screening_identity'] == original['identity']
                and consumed['previous_package_ref'] == old_package and consumed['next_package_ref'] == new_package,
                'Successor consumes a different reply or package')
        require(any(r['ref'] == consumed['evidence']['ref'] and r['projection'] == consumed['evidence']
                    for r in successor['source_reading']), 'Revised A01 did not actually read the native reply evidence')
        tick = trigger['native_request']['metadata']['tick']
        require(successor['result']['payload']['choice'] == ('participate' if tick == 2 else 'decline')
                and bid['result']['payload']['choice'] == ('submit_bid' if tick == 2 else 'decline_bid'),
                'Unexpected original successor/bid judgment')
        reply_chains.append({'organization_id': trigger['organization_id'], 'macro_tick': tick,
            'native_request_sha256': trigger['request_sha256'], 'original_identity': original['identity'],
            'question_message': question['message'], 'reply_message': reply['message'], 'qs_identity': qs['identity'],
            'qs_result_sha256': qs['result_sha256'], 'consumption': consumed,
            'successor_identity': successor['identity'], 'successor_result_sha256': successor['result_sha256'],
            'successor_choice': successor['result']['payload']['choice'], 'bid_identity': bid['identity'],
            'bid_result_sha256': bid['result_sha256']})

    events = [e for p in simulation['project_results'] for e in p['event_log']]
    feedback = tables['gba_tender_feedback']
    later_chains = []
    for org in ('dev-contractor-a', 'dev-contractor-b'):
        submitted = one(feedback, lambda r: r['organization_id'] == org and r['effect'] == 'native_bid_submitted',
                        'Missing actual native submission')
        event = one(events, lambda e: e['event_id'] == submitted['event_id'] and e['event_type'] == 'bid_submitted'
                    and e['tick'] == 2 and e['agent_id'] == org, 'No corresponding committed native event')
        first = one(triggers, lambda r: r['organization_id'] == org and r['native_request']['metadata']['tick'] == 2,
                    'Missing first request')
        require(submitted['micro_result_sha256'] == first['bid_result_sha256'], 'Macro executed a different bid')
        later = one(triggers, lambda r: r['organization_id'] == org and r['native_request']['metadata']['tick'] == 3,
                    'Missing later request')
        waiting = action(later['screening_identity'])
        current = action(later['screening_successor_identity'])
        consumer = one(rows('gba_tender_feedback_consumption'), lambda r: r['organization_id'] == org,
                       'Missing later feedback consumer')
        source = one(rows('contractor_screening_feedback_source'),
            lambda r: r['record_sha256'] == consumer['feedback_source_sha256'], 'Missing derived policy')
        for record in (submitted, consumer, source):
            digest_valid(record)
        # The original A01 reads feedback but first asks its pending question.
        # Its receipt belongs to that clarify task, not to the successor task.
        require(consumer['identity'] == waiting['identity']
                and consumer['result_record_sha256'] == waiting['record_sha256']
                and later['feedback_consumption_sha256'] == consumer['record_sha256']
                and consumer['source_events'] == [{'event_id': event['event_id'],
                                                  'record_sha256': submitted['record_sha256']}],
                'Later judgment did not consume the same actual submission')
        profile = one(source['objects'], lambda r: r['ref'] == source['profile_ref'], 'No derived profile')['value']
        require(source['feedback_context']['submitted_count'] == source['decline_after_prior_submissions'] == 1
                and profile['policy'] == 'decline_new_work'
                and any(r['ref'] == profile['ref'] and r['projection'] == profile for r in waiting['source_reading'])
                and any(r['ref'] == profile['ref'] and r['projection'] == profile for r in current['source_reading']),
                'Actual native feedback did not affect the later micro policy')
        declined = one(feedback, lambda r: r['organization_id'] == org and r['effect'] == 'native_bid_declined',
                       'Missing native later refusal')
        require(declined['micro_result_sha256'] == later['bid_result_sha256'], 'Later result not executed')
        one(events, lambda e: e['event_id'] == declined['event_id'] and e['event_type'] == 'bid_declined'
            and e['tick'] == 3 and e['agent_id'] == org, 'Missing committed later refusal')
        later_chains.append({'organization_id': org, 'submission_event': event, 'submission_feedback': submitted,
            'initial_later_screening_identity': waiting['identity'], 'initial_later_choice': 'clarify',
            'later_screening_identity': current['identity'], 'later_choice': 'decline', 'feedback_consumer': consumer,
            'feedback_policy_source': source, 'later_native_feedback': declined})
    require(before == file_hash(database), 'Read-only business verification changed the journal')
    return {'status': 'passed', 'actual_ticks': 3, 'technical_tasks': len(tasks),
        'questions_and_replies': len(reply_chains), 'reply_successor_chains': reply_chains,
        'cross_tick_consumers': later_chains, 'journal_read_only': True,
        'timing_boundary': 'Reply -> new-version A01 is a later micro invocation within the same macro tick; '
                           'tick-2 actual bid -> tick-3 A01 is cross-tick. Different projects do not share replies.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/tender_clarification_loop.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if args.check_only:
        verify_history(output)
        require(macro_hashes() == read(output / 'checks.json')['macro'], 'Frozen macro changed since the run')
        require(verify_run(output) == read(output / 'checks.json')['business'], 'Saved business evidence changed')
    else:
        config = read(args.config)
        require(set(config) == {'schema_version', 'run_id', 'source_note', 'builder_options'}
            and config['schema_version'] == 'tender-clarification-loop.v1'
            and isinstance(config['run_id'], str) and config['run_id'].strip()
            and config['builder_options'] == {'continue_clarification': True,
                                             'clarification_publication_permitted': True}, 'Unsupported fixed scenario')
        before = macro_hashes()
        output.mkdir(parents=True, exist_ok=False)
        _write(output, 'scenario.json', config)
        _write(output, 'macro-before.json', before)
        build_feedback_bundle(output / 'input', run_id=config['run_id'], **config['builder_options'])
        command = [sys.executable, '-m', 'integration.run', '--input', str(output / 'input/macro-request.json'),
            '--output', str(output / 'runtime'), '--offline', '--input-format', 'gba_request',
            '--macro-mode', 'gba_v1_module', '--agent-client-factory', 'integration.native_routes:build_agent_client',
            '--agent-client-config', str(output / 'input/native-host.json'),
            '--module-assembly-hook', 'integration.contractor_tender_development:configure_assembly',
            '--module-assembly-config', str(output / 'input/assembly-host.json')]
        _write(output, 'command.json', command)
        with (output / 'stdout.log').open('xb') as stdout, (output / 'stderr.log').open('xb') as stderr:
            process = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        _write(output, 'exit.json', {'exit_code': process.returncode})
        require(process.returncode == 0, 'Native business run failed; preserve output and inspect stderr.log')
        business = verify_run(output)
        after = macro_hashes()
        require(before == after, 'Frozen macro source changed')
        _write(output, 'checks.json', {'batch': '3A-clarification', 'business': business,
            'macro': after, 'overall_goal3_complete': False, 'winner_override_supported': False})
        _write(output, 'artifact-manifest.json', {'schema_version': 'tender-clarification-loop-artifacts.v1',
            'files': {p.relative_to(output).as_posix(): file_hash(p) for p in output.rglob('*') if p.is_file()}})
    print(json.dumps({'status': 'passed', 'output': str(output), 'winner_override_supported': False}))


if __name__ == '__main__':
    main()
