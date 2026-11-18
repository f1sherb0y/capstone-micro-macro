"""Prepare/preflight a second bounded continuation; never replay unknown calls."""
import argparse
import asyncio
from pathlib import Path
import shutil
import tempfile

from capstone_cp_common_20261112 import CP00, PARENT, ROOT, engine_binding, no_provider, read, save, sha, verify_parent

LATEST = PARENT / 'continuation-001/run'
RUN_ID = 'capstone-expanded24-20261109'
BUDGET_ID = 'new-explicit-cap240'


def identity(job):
    return f"{job['window_id']}-{job['arm']}-r{job['repeat']}"


def prepare():
    protocol = verify_parent()
    slots = read(LATEST / 'first_results_all_slots.json')
    status = read(LATEST / 'execution_status.json')
    assert status['provider_halt'], 'Continuation only for this frozen stop'
    attempts, pending, unknown = {}, [], []
    for row in slots:
        jid = identity(row['job'])
        if row['status'] == 'not_started_provider_halt':
            pending.append(row['job'])
        else:
            path = LATEST / 'jobs' / jid / 'attempt-1.json'
            stored = read(path)
            assert stored == row and row.get('call_id'), jid
            attempts[jid] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'call_id': row['call_id']}
            if row['status'] == 'provider_unknown_attempt':
                unknown.append(jid)
    assert len(slots) == 192 and len(pending) == 33 and len(attempts) == 159 and len(unknown) == 4
    assert len({a['call_id'] for a in attempts.values()}) == 159
    sources = [LATEST / 'first_results_all_slots.json', LATEST / 'execution_status.json',
               PARENT / 'protocol.json', PARENT / 'run/budget.sqlite',
               PARENT / 'run/llm_calls.jsonl', LATEST / 'llm_calls.jsonl']
    plan = {'status': 'prepared_not_authorized', 'date': '2026-11-12',
            'same_parent_cap': 240, 'charged_before': 159, 'remaining_parent_calls': 81,
            'pending_first_jobs': pending, 'pending_count': 33, 'max_final_retries': 48,
            'unknown_job_ids_never_replayed': sorted(unknown), 'source_attempts': attempts,
            'parent_jobs': protocol['jobs'], 'run_id': RUN_ID, 'budget_id': BUDGET_ID,
            'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sources},
            'runner_sha256': sha(Path(__file__)), 'authorized_provider_calls_now': 0,
            'scope': 'Only33 never-started firsts, then at most48 eligible final repairs. Same240 ledger. No unknown replay, no automatic subsequent resume.'}
    save(CP00 / 'plan.json', plan)
    return plan


def verify_plan():
    protocol = verify_parent()
    plan = read(CP00 / 'plan.json')
    if sha(Path(__file__)) != plan['runner_sha256']:
        raise ValueError('CP00 runner changed after preparation')
    for path, digest in plan['source_sha256'].items():
        if sha(ROOT / path) != digest:
            raise ValueError('CP00 stop snapshot changed: ' + path)
    for jid, info in plan['source_attempts'].items():
        if sha(ROOT / info['path']) != info['sha256']:
            raise ValueError('Prior response changed: ' + jid)
    assert not set(plan['unknown_job_ids_never_replayed']) & {identity(j) for j in plan['pending_first_jobs']}
    return protocol, plan


def preflight():
    protocol, plan = verify_plan()
    from src.coordination.tasks import TaskStore, TaskConflict
    from src.coordination.model_budget import ModelCallBudget
    with no_provider() as counts, tempfile.TemporaryDirectory(prefix='CP00-budget-') as tmp:
        path = Path(tmp) / 'budget.sqlite'
        shutil.copy2(PARENT / 'run/budget.sqlite', path)
        store = TaskStore(run_id=RUN_ID, organization_ids=['experiment-host'], path=path)
        try:
            budget = ModelCallBudget(store=store, budget_id=BUDGET_ID, max_calls=240)
            assert budget.usage()['charged_or_reserved_calls'] == 159
            assert budget.reserve('CP00-synthetic33', 33)
            assert budget.reserve('CP00-synthetic48', 48)
            assert not budget.reserve('CP00-over-cap', 1)
            budget.finish('CP00-synthetic33')
            budget.finish('CP00-synthetic48')
            for jid in plan['unknown_job_ids_never_replayed']:
                try:
                    accepted = budget.reserve(jid + ':1', 1)
                except TaskConflict:
                    pass
                else:
                    assert accepted is False, 'Unknown attempt allowed to replay'
            assert budget.usage()['charged_or_reserved_calls'] == 159
        finally:
            store.close()
        for approved in [None, False]:
            try:
                run(approved)
            except ValueError:
                pass
            else:
                raise AssertionError('Unapproved CP00 execution accepted')
    verify_plan()
    save(CP00 / 'preflight.json', {'passed': True, 'pending_firsts': 33,
         'previous_unique_attempts': 159, 'unknown_attempts_excluded': 4,
         'same_cap': 240, 'max_future_attempts': 81, 'original_ledger_unchanged': True,
         'provider_requests': 0, **counts})
    print('CP00 PASS:159 retained,33 pending,4 unknown excluded, copied-budget cap240, provider requests0')


def run(approved=None):
    if approved is not True:
        raise ValueError('Explicit CP00 continuation scope required; this is not a new budget')
    protocol, plan = verify_plan()
    assert read(CP00 / 'preflight.json')['passed']
    if (CP00 / 'run').exists() or (CP00 / 'continuation_authorization.json').exists():
        raise ValueError('No automatic CP00 continuation replay')
    with engine_binding(CP00, verify_parent) as engine:
        client = engine.OpenAICompatibleClient.from_env(model=protocol['model'])
        store = None
        try:
            policy = client.request_policy()
            if policy != read(PARENT / 'authorization.json')['transport']:
                raise ValueError('Parent transport changed')
            client._chat_model.max_tokens = protocol['max_output_tokens']
            params = client._chat_model._default_params
            if params.get('max_tokens', params.get('max_completion_tokens')) != 4096:
                raise ValueError('Output limit not bound')
            engine.save(CP00 / 'continuation_authorization.json', {'at': engine.utc_now(),
                'same_parent_cap': 240, 'charged_before': 159, 'pending_firsts': 33,
                'unknown_replay_allowed': False, 'plan_sha256': sha(CP00 / 'plan.json')})
            for jid, info in plan['source_attempts'].items():
                dest = CP00 / 'run/jobs' / jid / 'attempt-1.json'
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / info['path'], dest)
            store = engine.TaskStore(run_id=RUN_ID, organization_ids=['experiment-host'], path=PARENT / 'run/budget.sqlite')
            budget = engine.ModelCallBudget(store=store, budget_id=BUDGET_ID, max_calls=240)
            assert budget.usage()['charged_or_reserved_calls'] == 159
            logger = engine.LLMCallAuditLogger(CP00 / 'run', 'CP00-CONTINUATION', client, attempt=3)

            async def perform():
                halt = asyncio.Event()
                semaphore = asyncio.Semaphore(protocol['concurrency'])
                windows = read(PARENT / 'windows.json')
                async def first(job):
                    async with semaphore:
                        return await engine.request(client, budget, logger, job, windows[job['window_id']], 1, halt)
                try:
                    new = await asyncio.gather(*(first(j) for j in plan['pending_first_jobs']))
                    combined = {identity(r['job']): r for r in new}
                    for jid in plan['source_attempts']:
                        combined[jid] = read(CP00 / 'run/jobs' / jid / 'attempt-1.json')
                    firsts = [combined[identity(j)] for j in protocol['jobs']]
                    engine.save(CP00 / 'run/first_results_all_slots.json', firsts)
                    if not halt.is_set():
                        repairs = [r for r in firsts if r['status'] in {'invalid_json', 'validation_failed'}]
                        for row in repairs[:48]:
                            await engine.request(client, budget, logger, row['job'], windows[row['job']['window_id']], 2, halt)
                            if halt.is_set():
                                break
                    engine.save(CP00 / 'run/execution_status.json', {'provider_halt': halt.is_set(),
                        'calls': budget.usage(), 'all192_slots_retained': len(firsts) == 192,
                        'original_unknown_not_replayed': plan['unknown_job_ids_never_replayed'],
                        'source_first_attempt_copies_not_new_calls': 159, 'macro_execution': False})
                finally:
                    engine.save(CP00 / 'run/budget_usage.json', budget.usage())
                    await client._chat_model.root_async_client.close()
            asyncio.run(perform())
        finally:
            if store is not None:
                store.close()
            client._chat_model.root_client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'preflight', 'run'])
    parser.add_argument('--confirm-run-cp00-scope', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'preflight':
        preflight()
    else:
        run(args.confirm_run_cp00_scope)
