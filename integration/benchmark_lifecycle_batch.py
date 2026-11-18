"""Resumable, case-level integrated macro benchmark batch (no offline fallback)."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from integration.benchmark_lifecycle_metrics import aggregate, contractor_truth, score_case
from integration.case_library_lifecycle import build_bundle
from integration.contractor_tender_development import verify_bundle
from integration.sessions import atomic_json
from integration.verify_goal3_minimal_native_fix import macro_snapshot

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def utc():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def batch_lock(directory):
    """OS lock releases on a crash; retain the lock file for later resumes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.batch.lock').open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def pins(config):
    source = ROOT / config['source_directory']
    files = [source / name for name in ['simulation_input_projects.csv',
        'simulation_input_enterprises.csv', 'hidden_benchmark_project_enterprises.csv']]
    files += [ROOT / config['template'], ROOT / 'config/origin_model_lifecycle_case.json']
    files += sorted((ROOT / 'integration').rglob('*.py')) + sorted((ROOT / 'src').rglob('*.py'))
    return {'files': {str(p.relative_to(ROOT)): sha(p) for p in files}, 'macro': macro_snapshot()}


def supported(project):
    return project['delivery_mode'] == 'DBB' and project['location'] in {'澳门', '澳門'} and project['project_type'] in {
        '市政与公共基础设施', '交通基础设施'}


def prepare(directory, config_path):
    directory = Path(directory).resolve()
    if (directory / 'state.json').exists():
        raise ValueError('Batch exists; use --resume instead of overwriting retained evidence')
    config = read(config_path)
    source = ROOT / config['source_directory']
    projects = rows(source / 'simulation_input_projects.csv')
    benchmarks = rows(source / 'hidden_benchmark_project_enterprises.csv')
    if len({p['case_id'] for p in projects}) != len(projects):
        raise ValueError('Duplicate project IDs')
    truth = {}
    for row in benchmarks:
        truth.setdefault(row['case_id'], []).append(row)
    if set(truth) - {p['case_id'] for p in projects}:
        raise ValueError('Benchmark references unknown project')
    selected = set(config['first_phase_case_ids'])
    actual = {p['case_id'] for p in projects if p['case_id'] in truth and supported(p)}
    if selected != actual:
        raise ValueError('First-phase IDs must exactly match currently supported raw project modes and domains')
    execution_ids = config.get('execution_case_ids', sorted(selected))
    if not execution_ids or len(execution_ids) != len(set(execution_ids)) or not set(execution_ids) <= selected:
        raise ValueError('Execution shard must contain distinct supported case IDs')
    items = []
    for p in projects:
        if p['case_id'] not in truth:
            continue
        eligible = p['case_id'] in selected
        mode = p['delivery_mode']
        reason = '' if eligible else ('delivery_mode_missing' if not mode else
            'DBB_region_or_project_type_adapter_required' if mode == 'DBB' else
            'EPC_adapter_required' if mode == 'EPC' else 'original_mode_adapter_required')
        items.append({'case_id': p['case_id'], 'project_name': p['project_name'],
            'delivery_mode': mode, 'location': p['location'], 'project_type': p['project_type'],
            'benchmark_rows': len(truth[p['case_id']]),
            'has_contractor_benchmark': bool(contractor_truth(truth[p['case_id']])),
            'supported': eligible, 'status': ('pending' if p['case_id'] in execution_ids else 'not_scheduled') if eligible else 'blocked',
            'blocking_reason': reason, 'attempts': []})
    state = {'schema_version': config['schema_version'], 'batch_id': config['batch_id'],
        'config': config, 'pins': pins(config), 'created_at': utc(), 'status': 'prepared',
        'cases': items, 'scores': {}}
    atomic_json(directory / 'state.json', state)
    report(directory, state)
    return state


def report(directory, state):
    directory = Path(directory)
    atomic_json(directory / 'summary.json', {**aggregate(list(state['scores'].values()),
        len(state['cases']), sum(c['supported'] for c in state['cases'])),
        'batch_status': state['status'], 'statuses': dict(Counter(c['status'] for c in state['cases']))})
    fields = ['case_id', 'project_name', 'delivery_mode', 'location', 'project_type',
        'benchmark_rows', 'has_contractor_benchmark', 'supported', 'status', 'blocking_reason']
    with (directory / 'inventory.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({f: c[f] for f in fields} for c in state['cases'])
    scores = list(state['scores'].values())
    atomic_json(directory / 'scores.json', scores)
    if scores:
        with (directory / 'scores.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(scores[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v
                for k, v in score.items()} for score in scores)


def save(directory, state):
    state['updated_at'] = utc()
    atomic_json(Path(directory) / 'state.json', state)
    report(directory, state)


def ledger_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def execute_case(case_directory, attempt, source):
    """Reuse immutable case inputs. Each runtime/journal belongs to one attempt."""
    verify_bundle(source)
    attempt.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'integration.run', '--input', str(source / 'macro-request.json'),
        '--output', str(attempt / 'runtime'), '--llm', '--input-format', 'gba_request',
        '--macro-mode', 'gba_v1_module', '--allow-native-project-generation',
        '--allow-native-initial-projects-with-generation',
        '--agent-client-factory', 'integration.model_tender_native:build_agent_client',
        '--agent-client-config', str(source / 'native-host.json'),
        '--module-assembly-hook', 'integration.origin_model_lifecycle:configure_assembly',
        '--module-assembly-config', str(source / 'assembly-host.json')]
    atomic_json(attempt / 'command.json', command)
    with (attempt / 'stdout.log').open('xb') as out, (attempt / 'stderr.log').open('xb') as err:
        child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        atomic_json(attempt / 'process.json', {'pid': child.pid, 'started_at': utc()})
        try:
            code = child.wait()
        except BaseException:
            child.terminate()
            child.wait()
            raise
    atomic_json(attempt / 'exit.json', {'exit_code': code, 'finished_at': utc()})
    return code


def verify_completed(attempt, source):
    from integration.origin_lifecycle_report import verify
    return verify(attempt, source_directory=source)


def run(directory, *, retry_failed=False, limit=None):
    directory = Path(directory).resolve()
    state = read(directory / 'state.json')
    if state['pins'] != pins(state['config']):
        raise ValueError('Pinned input or implementation changed; retain this batch and prepare a new one')
    for score in state['scores'].values():
        if sha(Path(score['attempt_directory']) / 'runtime/result.json') != score['result_sha256']:
            raise ValueError('Completed result changed; do not silently skip corrupted evidence')
    config = state['config']
    source_csv = ROOT / config['source_directory']
    benchmarks = rows(source_csv / 'hidden_benchmark_project_enterprises.csv')
    state['status'] = 'running'
    save(directory, state)
    processed = 0
    try:
        for item in state['cases']:
            if not item['supported'] or item['status'] in {'completed', 'not_scheduled'}:
                continue
            if item['status'] == 'failed' and not retry_failed:
                continue
            if limit is not None and processed >= limit:
                break
            case_id = item['case_id']
            case_dir = directory / 'cases' / case_id
            source = case_dir / 'input'
            if not source.exists():
                case_config = read(ROOT / config['template'])
                case_config.update(case_id=case_id, run_id=config['batch_id'] + '-' + case_id,
                    response_cache_directory=str(case_dir / 'model-cache'),
                    api_total_attempt_cap=config['max_paid_attempts_per_case'])
                case_config['model_options']['max_calls'] = config['max_paid_attempts_per_case']
                case_config['scope'] = config['scope'] + ' ' + config['model_scope']
                build_bundle(source, case_config)
            # A killed builder leaves an incomplete bundle. Fail visibly, never silently replace it.
            verify_bundle(source)
            before = ledger_rows(case_dir / 'model-cache' / 'attempts.jsonl')
            attempt = case_dir / ('attempt-%03d' % (len(item['attempts']) + 1))
            record = {'directory': str(attempt), 'started_at': utc(), 'status': 'running'}
            item['attempts'].append(record)
            item['status'] = 'running'
            save(directory, state)
            print(json.dumps({'case_id': case_id, 'status': 'running', 'attempt': len(item['attempts'])}), flush=True)
            code = execute_case(case_dir, attempt, source)
            all_calls = ledger_rows(case_dir / 'model-cache' / 'attempts.jsonl')
            calls = all_calls[len(before):]
            record.update(finished_at=utc(), exit_code=code,
                new_paid_attempts=sum(r['event'] == 'started' for r in calls),
                reused_responses=sum(r['event'] == 'cache_hit' for r in calls))
            failures = [r for r in calls if r['event'] in {'failed', 'attempt_cap_exhausted'}]
            if failures or code:
                quota = any(r.get('http_status') == 402 for r in failures)
                item['status'] = record['status'] = 'paused_quota' if quota else 'failed'
                record['errors'] = failures
                state['status'] = 'paused_quota' if quota else 'paused_error'
                save(directory, state)
                # Fail-stop: no automatic retries, fallback, or continuing to later cases.
                return state
            result = read(attempt / 'runtime/result.json')
            chain = verify_completed(attempt, source)
            declared = read(ROOT / config['template'])
            stages = None
            if declared.get('candidate_policy'):
                dataset = read(source / 'case-library-input.json')
                initial = read(source / 'macro-request.json')
                stages = {'source': [r['company_id'] for r in rows(source_csv / 'simulation_input_enterprises.csv')],
                    'retrieved': [c['company_id'] for c in dataset['companies'] if c['company_role'] == 'contractor'],
                    'active': [a['agent_id'] for a in initial['agents'] if a['role'] == 'Contractor']}
            score = score_case(result, case_id, contractor_truth([r for r in benchmarks if r['case_id'] == case_id],
                role=config.get('benchmark_role')), candidate_stages=stages)
            if not score['completed'] or not score['closed'] or not score['award_event_ids'] or not score['settlement_event_ids']:
                raise ValueError('Lifecycle did not complete actual contract and settlement')
            score.update(attempt_directory=str(attempt), result_sha256=sha(attempt / 'runtime/result.json'))
            score.update(chain_check_status=chain['status'],
                later_owner_feedback_consumers=len(chain['later_owner_consumers']),
                open_payment_feedback_count=len(chain.get('open_payment_feedback', [])))
            score['integration_checks'] = {'contract_executed': bool(score['award_event_ids']),
                'aggregate_settlement_executed': bool(score['settlement_event_ids']),
                'later_feedback_consumed': bool(chain['later_owner_consumers']),
                'payment_clearing_complete': not bool(chain.get('open_payment_feedback', []))}
            state['scores'][case_id] = score
            item['status'] = record['status'] = 'completed'
            processed += 1
            save(directory, state)
            print(json.dumps({'case_id': case_id, 'status': 'completed',
                'top1': score['top1'], 'valid_bidders': score['valid_bid_count']}), flush=True)
        remaining = [c for c in state['cases'] if c['supported'] and c['status'] not in {'completed', 'not_scheduled'}]
        state['status'] = 'phase_complete_other_modes_blocked' if not remaining else 'phase_incomplete'
    except KeyboardInterrupt:
        state['status'] = 'interrupted'
        for item in state['cases']:
            if item['status'] == 'running':
                item['status'] = 'interrupted'
                item['attempts'][-1]['status'] = 'interrupted'
        raise
    except Exception:
        state['status'] = 'paused_error'
        for item in state['cases']:
            if item['status'] == 'running':
                item['status'] = item['attempts'][-1]['status'] = 'failed'
        raise
    finally:
        save(directory, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path)
    group.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    with batch_lock(args.directory):
        state = prepare(args.directory, args.prepare) if args.prepare else run(
            args.directory, retry_failed=args.retry_failed, limit=args.limit)
    print(json.dumps({'status': state['status'], 'directory': str(args.directory)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
