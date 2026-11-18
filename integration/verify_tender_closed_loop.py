"""Run the existing native tender path and verify GOAL 1 from saved evidence.

No engine monkeypatches or state writes. Each scenario is authored through the
existing bundle builder and executed by the ordinary integration.run CLI.
"""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import build_feedback_bundle, verify_bundle, _write
from src.coordination.tasks import TaskIdentity, task_digest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'output/integration/implementation_20261016_01/macro_baseline.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def macro_hashes():
    baseline = read(BASELINE)
    root = ROOT / baseline['root']
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in baseline['files']}
    require(actual == baseline['files'], 'Frozen macro differs from the existing 174-file baseline')
    # Include extra Python sources, so an added implementation cannot evade the baseline.
    extra = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob('*.py') if '__pycache__' not in p.parts}
    return {'baseline': str(BASELINE.relative_to(ROOT)), 'baseline_sha256': hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
            'root': baseline['root'], 'files': actual, 'python_sources': extra,
            'file_count': len(actual), 'matches_existing_baseline': True}


def load_config(path):
    config = read(path)
    require(set(config) == {'schema_version', 'source_note', 'run_id', 'varied_organization_id', 'scenarios'},
            'Unexpected acceptance configuration fields')
    require(config['schema_version'] == 'tender-closed-loop-acceptance.v1', 'Unknown acceptance schema')
    require(config['varied_organization_id'] == 'dev-contractor-a', 'This fixed scenario varies Contractor A')
    require(isinstance(config['source_note'], str) and config['source_note'].strip(), 'Source note required')
    require(isinstance(config['run_id'], str) and config['run_id'].strip(), 'Run ID required')
    require(config['scenarios'] == [dict(name='baseline', total_resource_capacity=1.0),
                                  dict(name='lower_capacity', total_resource_capacity=0.8)],
            'This representative acceptance requires the fixed 1.0 / 0.8 controlled pair')
    return config


def database_records(path):
    # Read the completed original journal without opening a TaskStore or migrating it.
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tables = {table: [json.loads(row[0]) for row in db.execute('SELECT record FROM ' + table)]
                  for table in ('tasks', 'invocation_snapshots', 'contractor_screening_results',
                                'contractor_bid_results', 'gba_tender_feedback')}
        tables['metadata'] = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM metadata')
                              if key.startswith(('tender_request_trigger:', 'gba_tender_feedback_consumption:',
                                                 'contractor_screening_feedback_source:',
                                                 'contractor_tender_native_binding:'))}
    return tables


def one(rows, predicate, message):
    selected = [row for row in rows if predicate(row)]
    require(len(selected) == 1, message)
    return selected[0]


def digest_valid(record, field='record_sha256'):
    require(record[field] == task_digest({k: v for k, v in record.items() if k != field}),
            'Saved record digest changed')


def verify_scenario(directory):
    """Read-only acceptance; exports the evidence it actually checked."""
    bundle, runtime = directory / 'input', directory / 'runtime'
    verify_bundle(bundle)
    result = read(runtime / 'result.json')
    simulation = result['simulation']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == 3,
            'Native engine did not complete the three-tick window')
    require(result['macro_mode'] == 'gba_v1_module' and result['requested_model_mode'] == 'offline',
            'Expected ordinary native-module deterministic execution')
    records = database_records(runtime / 'tasks.sqlite')
    observations = read(runtime / 'observations.json')['records']
    initial = read(bundle / 'macro-request.json')
    require(all(not p['bids'] and not p['contracts'] and p['selected_contractor_id'] is None
                for p in initial['initial_projects']), 'Initial scenario contains prefilled formal business results')
    metadata = records['metadata']
    triggers = [v for k, v in metadata.items() if k.startswith('tender_request_trigger:')]
    consumers = [v for k, v in metadata.items() if k.startswith('gba_tender_feedback_consumption:')]
    sources = [v for k, v in metadata.items() if k.startswith('contractor_screening_feedback_source:')]
    require(len(triggers) == 4 and len(consumers) == 2, 'Expected four requests and two later consumers')
    require(all(t['state'] == 'output_formed' for t in records['tasks']), 'Unfinished technical task')
    snapshots = {TaskIdentity(**r['identity']).key: r for r in records['invocation_snapshots']}
    screenings = {TaskIdentity(**r['identity']).key: r for r in records['contractor_screening_results']}
    bids = {TaskIdentity(**r['identity']).key: r for r in records['contractor_bid_results']}
    tasks = {TaskIdentity(**r['identity']).key: r for r in records['tasks']}
    require(len(screenings) == len(bids) == 4, 'Expected original A01 and A02 for both enterprises and rounds')
    feedback = records['gba_tender_feedback']
    require(sum(r['effect'] == 'native_bid_submitted' for r in feedback) == 2, 'Two native submissions required')
    require(sum(r['effect'] == 'native_bid_declined' for r in feedback) == 2, 'Two native declines required')
    events = [event for project in simulation['project_results'] for event in project['event_log']]
    chains = []
    for org in ('dev-contractor-a', 'dev-contractor-b'):
        first = one(triggers, lambda r: r['organization_id'] == org and r['native_request']['metadata']['tick'] == 2,
                    'Missing first native tender request')
        later = one(triggers, lambda r: r['organization_id'] == org and r['native_request']['metadata']['tick'] == 3,
                    'Missing later native tender request')
        for trigger in (first, later):
            digest_valid(trigger)
            require(trigger['state'] == 'selected', 'Native request did not select completed micro work')
        first_screen = screenings[TaskIdentity(**first['screening_identity']).key]
        first_bid = bids[TaskIdentity(**first['bid_identity']).key]
        later_screen = screenings[TaskIdentity(**later['screening_identity']).key]
        later_bid = bids[TaskIdentity(**later['bid_identity']).key]
        for record in (first_screen, first_bid, later_screen, later_bid):
            digest_valid(record)
            require(record['result_sha256'] == task_digest(record['result']), 'Micro result hash mismatch')
            require(tasks[TaskIdentity(**record['identity']).key]['output'] == record['result'], 'Task result differs')
            snapshot = snapshots[TaskIdentity(**record['identity']).key]
            digest_valid(snapshot, 'snapshot_sha256')
            require(task_digest(snapshot['action_input']) == record['identity']['input_sha256'] and
                    task_digest(snapshot['context']) == record['identity']['context_sha256'], 'Invocation input/context differs')
        require(first_screen['result']['payload']['choice'] == 'participate', 'First A01 must compute participation')
        require(first_bid['result']['payload']['choice'] == 'submit_bid', 'First A02 must compute a bid')
        require(later_screen['result']['payload']['choice'] == 'decline' and
                later_bid['result']['payload']['choice'] == 'decline_bid', 'Later original actions did not decline')
        capacity = one(first_screen['audit']['method_calls'],
                       lambda c: c['method_ref']['id'] == 'micro.capacity.fixed_location', 'Missing actual capacity call')
        native_total = first['native_request']['agent']['resources']['total_resource_capacity']
        require(Decimal(capacity['input']['resources'][0]['total']['value']) == Decimal(str(native_total)),
                'Native capacity did not enter the actual method input')
        require(capacity['result']['kind'] == 'ok' and capacity['result']['value']['feasible'], 'Capacity comparison failed')
        mapping = one(first_screen['source_reading'], lambda r: r['ref']['kind'] == 'GbaCapacityMapping',
                      'Missing authorized source mapping')['projection']
        native_bindings = [v for k, v in metadata.items() if k.startswith('contractor_tender_native_binding:')]
        require(any(v['native_resource_sha256'] == mapping['source_record_sha256'] and
                    v['request_id'] == first['request_id'] and v['organization_id'] == org for v in native_bindings),
                'Mapping does not bind the actual native resource read')
        submitted = one(feedback, lambda r: r['organization_id'] == org and r['effect'] == 'native_bid_submitted',
                        'Missing actual first submission feedback')
        digest_valid(submitted)
        observation = one(observations, lambda r: r['event_id'] == submitted['event_id'] and
                          r['organization_id'] == org, 'Missing actual committed recipient observation')
        require(observation['payload'] == submitted['projection'] and observation['payload']['committed'] is True,
                'Saved feedback differs from the actual recipient observation')
        require(submitted['micro_result_sha256'] == first_bid['result_sha256'], 'Submission refers to another micro result')
        event = one(events, lambda e: e['event_id'] == submitted['event_id'], 'Missing original native event')
        require(event['event_type'] == 'bid_submitted' and event['tick'] == 2 and event['agent_id'] == org,
                'Wrong original submission event')
        require(event['data']['decision_advisor']['data']['micro_result_sha256'] == first_bid['result_sha256'],
                'Original macro did not execute this micro decision')
        price = Decimal(first_bid['result']['payload']['bid']['price']['value'])
        require(Decimal(str(event['data']['bid_price'])) == price, 'Macro bid price differs from calculated A02 price')
        project = one(simulation['project_results'], lambda p: p['project_id'] == event['project_id'], 'Missing actual project')
        actual_bid = one(project['bids'], lambda b: b['contractor_id'] == org, 'No bid stored by original macro')
        require(Decimal(str(actual_bid['bid_price'])) == price, 'Original macro bid state differs from event/result')
        consumer = one(consumers, lambda r: r['organization_id'] == org, 'Missing later consumption')
        source = one(sources, lambda r: r['record_sha256'] == consumer['feedback_source_sha256'], 'Missing feedback policy source')
        digest_valid(consumer)
        digest_valid(source)
        require(consumer['result_record_sha256'] == later_screen['record_sha256'] and
                later['feedback_consumption_sha256'] == consumer['record_sha256'], 'Later result/consumption link mismatch')
        require(consumer['source_events'] == [{'event_id': event['event_id'], 'record_sha256': submitted['record_sha256']}],
                'Later screening did not consume the same actual submission')
        require(source['feedback_context']['submitted_count'] == source['decline_after_prior_submissions'] == 1,
                'Actual submission count did not meet declared private threshold')
        derived = one(source['objects'], lambda r: r['ref'] == source['profile_ref'], 'Missing derived profile')['value']
        require(derived['policy'] == 'decline_new_work', 'Feedback did not enter the policy decision')
        require(any(r['ref'] == source['profile_ref'] and r['projection'] == derived for r in later_screen['source_reading']),
                'Later A01 did not actually read the derived policy')
        later_snapshot = snapshots[TaskIdentity(**later['screening_identity']).key]
        require(later_snapshot['action_input']['screening_profile_ref'] == source['profile_ref'], 'Later A01 uses another policy')
        declined = one(feedback, lambda r: r['organization_id'] == org and r['effect'] == 'native_bid_declined',
                       'Missing actual later decline')
        require(declined['micro_result_sha256'] == later_bid['result_sha256'], 'Later macro executed another result')
        one(events, lambda e: e['event_id'] == declined['event_id'] and e['event_type'] == 'bid_declined' and e['tick'] == 3,
            'Missing original later decline event')
        chains.append({'organization_id': org, 'native_request': first['native_request'],
            'capacity_source_mapping': mapping, 'actual_capacity_method_call': capacity,
            'action_invocations': [snapshots[TaskIdentity(**r['identity']).key]
                                   for r in (first_screen, first_bid, later_screen, later_bid)],
            'first_screening': first_screen, 'first_bid': first_bid, 'native_submission_event': event,
            'native_recipient_observation': observation,
            'submission_feedback': submitted, 'later_native_request': later['native_request'],
            'feedback_policy_source': source, 'later_consumption': consumer,
            'later_screening': later_screen, 'later_bid': later_bid, 'later_native_feedback': declined})
    return {'status': 'passed', 'actual_ticks': 3, 'original_micro_actions': len(screenings) + len(bids),
            'technical_tasks': len(tasks), 'native_submissions': 2, 'native_declines': 2,
            'actual_later_consumers': len(consumers), 'chains': chains}


def write_run_record(output, config, reports):
    lines = ['# GOAL 1 投标闭环实际运行记录', '',
        '本记录来自普通 integration.run 的两个实际三时点运行。输入为明确合成假设；宏观正式执行由冻结源码完成。', '',
        '| 场景 | 企业 | 宏观总容量 | 方法可用量 | 首轮 A01 / A02 | 原收标事件 | 后轮 A01 / A02 | 后轮消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for scenario, report in zip(config['scenarios'], reports):
        for chain in report['chains']:
            available = chain['actual_capacity_method_call']['result']['value']['segments'][0]['available']
            amount = Fraction(available['numerator'], available['denominator'])
            lines.append('| ' + ' | '.join([scenario['name'], chain['organization_id'],
                str(chain['native_request']['agent']['resources']['total_resource_capacity']), str(amount),
                'participate / submit_bid', chain['native_submission_event']['event_id'], 'decline / decline_bid',
                chain['later_consumption']['source_events'][0]['event_id']]) + ' |')
    lines.extend(['', '每组实际完成 8 项原微观动作、44 项技术任务、2 次原宏观收标、2 次后轮消费及原宏观拒投。', '',
        '首轮实际报价为 110 HKD。后轮按预先声明的私有阈值 1 读取本企业实际收标数量；原 A01 读取派生策略并拒绝。', '',
        '完整输入、上下文、结果哈希、原生事件和后轮消费逐企业保存在各组 chain-evidence.json 与 runtime/tasks.sqlite；',
        '完整原 CLI 参数在 command.json，运行输出与诊断在 run.log，宏观项目 bids 和 event_log 在 runtime/result.json。', '',
        '宏观前后逐文件哈希一致，匹配既有 174 文件基线。范围止于投标和后轮反馈，不代表原 PLAN 全部完成。', ''])
    with (output / 'RUN_RECORD.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))


def run_acceptance(config_path, output):
    config = load_config(config_path)
    before = macro_hashes()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    _write(output, 'scenario.json', config)
    _write(output, 'macro-before.json', before)
    reports = []
    try:
        for scenario in config['scenarios']:
            directory = output / scenario['name']
            directory.mkdir()
            bundle = directory / 'input'
            build_feedback_bundle(bundle, run_id=config['run_id'] + '-' + scenario['name'],
                organization_capacity_totals={config['varied_organization_id']: scenario['total_resource_capacity']},
                query_prior_submissions=True, observe_current_occupancy=True)
            verify_bundle(bundle)
            command = [sys.executable, '-m', 'integration.run', '--input', str(bundle / 'macro-request.json'),
                '--output', str(directory / 'runtime'), '--offline', '--input-format', 'gba_request',
                '--macro-mode', 'gba_v1_module', '--agent-client-factory', 'integration.native_routes:build_agent_client',
                '--agent-client-config', str(bundle / 'native-host.json'), '--module-assembly-hook',
                'integration.contractor_tender_development:configure_assembly', '--module-assembly-config', str(bundle / 'assembly-host.json')]
            _write(directory, 'command.json', command)
            print('Running ' + scenario['name'] + ' through original integration.run', flush=True)
            with (directory / 'run.log').open('xb') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            report = verify_scenario(directory)
            _write(directory, 'chain-evidence.json', report)
            reports.append(report)
            print(scenario['name'] + ': native submissions and later consumption verified', flush=True)
        requests = [read(output / s['name'] / 'input/macro-request.json') for s in config['scenarios']]
        normalized = deepcopy(requests)
        for request in normalized:
            agent = one(request['agents'], lambda a: a['agent_id'] == config['varied_organization_id'], 'Missing varied native agent')
            agent['total_resource_capacity'] = 1.0
        require(normalized[0] == normalized[1], 'Controlled native inputs differ beyond declared total capacity')
        calls = [r['chains'][0]['actual_capacity_method_call'] for r in reports]
        require(calls[0]['input']['demands'] == calls[1]['input']['demands'] and
                calls[0]['input']['commitments'] == calls[1]['input']['commitments'], 'Capacity comparison changed other numeric inputs')
        available = [Fraction(c['result']['value']['segments'][0]['available']['numerator'],
                              c['result']['value']['segments'][0]['available']['denominator']) for c in calls]
        require(available == [Fraction(1), Fraction(4, 5)], 'Controlled input did not affect actual capacity output')
        after = macro_hashes()
        require(before == after, 'Macro source changed during the acceptance run')
        _write(output, 'macro-after.json', after)
        summary = {'status': 'passed', 'stage': 'GOAL 1 representative tender loop only',
            'macro_unchanged': True, 'macro_baseline_files': before['file_count'],
            'controlled_parameter': 'SimulationCreateRequest.agents[dev-contractor-a].total_resource_capacity',
            'only_native_input_difference': True,
            'capacity_comparison': [{'scenario': s['name'], 'native_total': s['total_resource_capacity'],
                'actual_available': str(a), 'needed': '1/5', 'feasible': True, 'first_choice': 'participate'}
                for s, a in zip(config['scenarios'], available)],
            'scenarios': [{k: v for k, v in r.items() if k != 'chains'} for r in reports],
            'boundaries': ['Synthetic initial business assumptions; deterministic original micro actions, no model quality claim.',
                'Native tender receipt and later private A01/A02 consumption only; no award, contract, fulfillment or cash acceptance.',
                'Normalized enterprise capacity is not physical labour/equipment; future calendars remain independent assumptions.',
                'Does not complete PLAN: eight roles, 106 actions, 438 branches and broader stability remain outside this stage.']}
        _write(output, 'acceptance.json', summary)
        write_run_record(output, config, reports)
        _write(output, 'artifact-manifest.json', {
            'schema_version': 'tender-closed-loop-artifacts.v1',
            'files': {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(output.rglob('*')) if p.is_file()}})
        return summary
    except Exception as error:
        _write(output, 'failure.json', {'status': 'failed', 'error_type': type(error).__name__, 'message': str(error)})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/tender_closed_loop.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_acceptance(args.config, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
