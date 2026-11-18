"""Prepare CP08's 780 never-started firsts; resume only on new explicit scope.

Original 148 attempted jobs, including both unknowns, are excluded. The same
928 ledger, model, messages, evaluation and zero-repair policy remain in force.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from capstone_cp_common_20261112 import ROOT, CP01, no_provider, read, save, sha, engine_binding
from continue_capstone_cp01_20261112 import identity, process_ancestors, assert_transport_open, open_checked_request
from run_capstone_cp08_20261113 import OUT, MASTER, verify_frozen

CONT = OUT / 'continuation-001'
SNAPSHOT = MASTER / 'CP08_stop_snapshot.json'
NEW_AUTH = MASTER / 'resume_after_CP08_stop_authorization.json'


def prepare():
    p = verify_frozen()
    stopped = read(SNAPSHOT)
    status = read(OUT / 'run/execution_status.json')
    first = read(OUT / 'run/first_results_all_slots.json')
    assert status['provider_halt'] and status['calls']['charged_or_reserved_calls'] == 148
    assert stopped['actual_attempts'] == 148 and stopped['never_started_count'] == 780
    assert not (CONT / 'run').exists() and not (CONT / 'launch_authorization.json').exists()
    pending = [r['job'] for r in first if r['status'] == 'not_started_provider_halt']
    attempted = {}
    for row in first:
        if row['job'] in pending:
            continue
        path = OUT / 'run/jobs' / identity(row['job']) / 'attempt-1.json'
        assert read(path) == row
        attempted[identity(row['job'])] = {'path': str(path.relative_to(ROOT)).replace('\\', '/'),
            'sha256': sha(path), 'status': row['status']}
    assert len(pending) == 780 and len(attempted) == 148
    assert not set(attempted) & {identity(j) for j in pending}
    assert pending == stopped['never_started_first_jobs']
    sources = [SNAPSHOT, OUT / 'protocol.json', OUT / 'windows.json', OUT / 'targets.json',
        OUT / 'run/execution_status.json', OUT / 'run/first_results_all_slots.json', OUT / 'run/budget_usage.json',
        OUT / 'run/budget.sqlite', OUT / 'run/llm_calls.jsonl', MASTER / 'PAID_HALT.json',
        ROOT / 'scripts/continue_capstone_cp01_20261112.py', ROOT / 'scripts/run_capstone_phase1_goal_20261112.py']
    plan = {'state': 'offline_prepared_new_stop_scope_required', 'runner_sha256': sha(__file__),
        'parent_protocol_sha256': sha(OUT / 'protocol.json'), 'same_parent_cap': 928,
        'charged_before': 148, 'new_first_max': 780, 'new_repairs': 0, 'pending_first_jobs': pending,
        'attempted_jobs_excluded': attempted, 'historical_unknowns_excluded': [key for key, row in attempted.items() if row['status'] == 'provider_unknown_attempt'],
        'source_sha256': {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path) for path in sources},
        'future_scope_max_after_this_stop': 3102, 'master_already_used': 385,
        'budget_arithmetic': '385 + (780+864+324+162+972) = 3487 <= original3488; CP01 unused1 is not transferred.',
        'new_scope_authorized': False, 'new_paid_calls': 0,
        'root_cause': 'Connection error cause remains unproven; fresh process is isolation, not proof of repaired provider/network availability.'}
    assert len(plan['historical_unknowns_excluded']) == 2
    save(CONT / 'plan.json', plan)
    print('CP08 continuation prepared:780 unstarted firsts,148 excluded,2 unknowns never replayed; new authorization required')


def verify_plan():
    p = verify_frozen()
    plan = read(CONT / 'plan.json')
    assert sha(__file__) == plan['runner_sha256']
    for path, expected in plan['source_sha256'].items():
        assert sha(ROOT / path) == expected, 'Original CP08 stop evidence changed: ' + path
    assert len(plan['pending_first_jobs']) == 780
    assert not {identity(j) for j in plan['pending_first_jobs']} & set(plan['attempted_jobs_excluded'])
    for row in plan['attempted_jobs_excluded'].values():
        assert sha(ROOT / row['path']) == row['sha256']
    return p, plan


def require_new_scope(plan):
    """A future real user instruction must be recorded here by the supervisor."""
    if not NEW_AUTH.exists():
        raise ValueError('New explicit after-CP08-stop scope is missing; keep paid stop active')
    auth = read(NEW_AUTH)
    assert auth['source'] == 'Explicit user instruction after CP08 stop'
    assert auth['stop_snapshot_sha256'] == sha(SNAPSHOT)
    assert auth['stop_marker_sha256'] == plan['source_sha256'][str((MASTER / 'PAID_HALT.json').relative_to(ROOT)).replace('\\', '/')]
    assert auth['master_already_used'] == 385 and auth['future_max'] == 3102
    assert auth['batch_limits'] == {'CP08_continuation': 780, 'CP07': 864, 'CP03': 324, 'CP03E': 162, 'CP03X': 972}
    assert auth['unknown_replay_allowed'] is False and auth['max_active_paid_batches'] == 1
    assert auth['explicit_instruction'].strip()
    assert auth['continuation_plan_sha256'] == sha(CONT / 'plan.json')
    return auth


def preflight():
    from src.coordination.tasks import TaskStore, TaskConflict
    from src.coordination.model_budget import ModelCallBudget
    p, plan = verify_plan()
    with no_provider() as counts, tempfile.TemporaryDirectory(prefix='CP08-unstarted-only-') as temporary:
        copied = Path(temporary) / 'budget.sqlite'
        shutil.copy2(OUT / 'run/budget.sqlite', copied)
        store = TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'], path=copied)
        try:
            budget = ModelCallBudget(store=store, budget_id=p['budget_id'], max_calls=928)
            assert budget.usage()['charged_or_reserved_calls'] == 148
            assert budget.reserve('offline-never-started780', 780)
            assert not budget.reserve('offline-overflow', 1)
            budget.finish('offline-never-started780')
            assert budget.usage()['charged_or_reserved_calls'] == 148
            for jid in plan['historical_unknowns_excluded']:
                try:
                    budget.reserve(jid + ':1', 1)
                except TaskConflict:
                    pass
                else:
                    raise AssertionError('Original unknown reservation could be replayed')
        finally:
            store.close()
        if not NEW_AUTH.exists():
            try:
                require_new_scope(plan)
            except ValueError:
                pass
            else:
                raise AssertionError('Missing new authorization accepted')
    verify_plan()
    save(CONT / 'preflight.json', {'passed': True, 'copied_budget_only': True,
        'old_attempts_excluded': 148, 'unknown_replay_reservations_rejected': 2,
        'pending_first_jobs': 780, 'parent_cap': 928, 'new_repairs': 0,
        'master_total_if_all_future_used': 3487, 'provider_calls': 0, **counts})
    print('CP08 continuation preflight PASS:148+780=928, unknown replay and overflow rejected;0 calls')


def launch(confirmed):
    if confirmed is not True:
        raise ValueError('Explicit after-stop continuation confirmation required')
    p, plan = verify_plan()
    require_new_scope(plan)
    assert read(CONT / 'preflight.json')['passed']
    if (CONT / 'run').exists() or (CONT / 'launch_authorization.json').exists():
        raise ValueError('Existing CP08 continuation; never automatically replay')
    token = uuid.uuid4().hex
    save(CONT / 'launch_authorization.json', {'at_UTC': datetime.now(timezone.utc).isoformat(),
        'launcher_pid': os.getpid(), 'launch_token': token, 'runner_sha256': sha(__file__),
        'plan_sha256': sha(CONT / 'plan.json'), 'new_scope_authorization_sha256': sha(NEW_AUTH),
        'same_parent_cap': 928, 'charged_before': 148, 'new_first_max': 780, 'new_repairs': 0})
    done = subprocess.run([sys.executable, str(Path(__file__)), 'worker', '--token', token], cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if done.returncode:
        raise RuntimeError('CP08 continuation child stopped; inspect, do not replay')


def worker(token):
    receipt = read(CONT / 'launch_authorization.json')
    assert token and token == receipt['launch_token']
    assert os.getpid() != receipt['launcher_pid'] and receipt['launcher_pid'] in process_ancestors()
    assert sha(__file__) == receipt['runner_sha256'] and sha(CONT / 'plan.json') == receipt['plan_sha256']
    assert sha(NEW_AUTH) == receipt['new_scope_authorization_sha256']
    p, plan = verify_plan()
    require_new_scope(plan)
    assert not (CONT / 'run').exists()
    from src.coordination.tasks import TaskStore
    from src.coordination.model_budget import ModelCallBudget
    store, client = None, None
    failures = []
    with engine_binding(CONT, verify_frozen) as engine:
        try:
            client = engine.OpenAICompatibleClient.from_env(model=p['model'])
            assert_transport_open(client)
            assert client.request_policy() == read(CP01 / 'authorization.json')['transport']
            client._chat_model.max_tokens = p['max_output_tokens']
            params = client._chat_model._default_params
            assert params.get('max_tokens', params.get('max_completion_tokens')) == 4096
            for jid, original in plan['attempted_jobs_excluded'].items():
                path = CONT / 'run/jobs' / jid / 'attempt-1.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / original['path'], path)
            store = TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'], path=OUT / 'run/budget.sqlite')
            budget = ModelCallBudget(store=store, budget_id=p['budget_id'], max_calls=928)
            assert budget.usage()['charged_or_reserved_calls'] == 148
            archived = MASTER / 'paid_stops' / ('CP08-stop-' + sha(MASTER / 'PAID_HALT.json')[:16] + '.json')
            archived.parent.mkdir(exist_ok=True)
            if archived.exists():
                assert sha(archived) == sha(MASTER / 'PAID_HALT.json')
            else:
                shutil.copy2(MASTER / 'PAID_HALT.json', archived)
            # This single marker transition is allowed only by the new
            # explicitly recorded post-stop user scope above. Evidence stays.
            save(CONT / 'run/stop_transition.json', {'archived_stop_path': str(archived.relative_to(ROOT)).replace('\\', '/'),
                'archived_stop_sha256': sha(archived), 'new_scope_sha256': sha(NEW_AUTH),
                'baseline_calls': 148, 'future_CP08_max': 780})
            (MASTER / 'PAID_HALT.json').unlink()
            logger = engine.LLMCallAuditLogger(CONT / 'run', 'CP08-CONTINUATION', client, attempt=2)
            request = open_checked_request(engine.request, failures)
            async def perform():
                halt = asyncio.Event()
                semaphore = asyncio.Semaphore(p['concurrency'])
                windows = read(OUT / 'windows.json')
                async def first(job):
                    async with semaphore:
                        return await request(client, budget, logger, job, windows[job['window_id']], 1, halt)
                try:
                    fresh = await asyncio.gather(*(first(j) for j in plan['pending_first_jobs']))
                    by_id = {identity(r['job']): r for r in fresh}
                    for jid, old in plan['attempted_jobs_excluded'].items():
                        by_id[jid] = read(ROOT / old['path'])
                    combined = [by_id[identity(j)] for j in p['jobs']]
                    save(CONT / 'run/first_results_all_slots.json', combined)
                    save(CONT / 'run/execution_status.json', {'provider_halt': halt.is_set(), 'stop_records': failures,
                        'calls': budget.usage(), 'all_first_slots_accounted': len(combined) == 928,
                        'historical_attempt_copies_not_new_calls': 148, 'original_unknowns_never_replayed': 2,
                        'new_attempts': budget.usage()['charged_or_reserved_calls'] - 148, 'scoring': 'pending'})
                    if halt.is_set():
                        save(MASTER / 'PAID_HALT.json', {'batch': 'CP08-continuation-001', 'reason': 'new_provider_or_local_stop', 'stop_records': failures})
                finally:
                    save(CONT / 'run/budget_usage.json', budget.usage())
                    await client._chat_model.root_async_client.close()
            asyncio.run(perform())
        except Exception as exc:
            if not (MASTER / 'PAID_HALT.json').exists():
                save(MASTER / 'PAID_HALT.json', {'batch': 'CP08-continuation-001', 'reason': 'local_or_transport_exception', 'error_type': type(exc).__name__})
            raise
        finally:
            if store:
                store.close()
            if client:
                client._chat_model.root_client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'preflight', 'run', 'worker'])
    parser.add_argument('--confirm-after-CP08-stop', action='store_true')
    parser.add_argument('--token')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'preflight':
        preflight()
    elif args.command == 'run':
        launch(args.confirm_after_CP08_stop)
    else:
        worker(args.token)
