"""Execute the explicitly authorized phase1 with a stricter additive stop guard.

Never changes frozen prompts, evaluator, request accounting or unknown slots.
The wrapper stops on ALL provider failures, including nonfatal HTTP statuses.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch

from capstone_cp_common_20261112 import ROOT, CP00, CP01, read, save, sha

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-12_第一阶段48组微观结果'
PREP = BASE / '指标补充/2026-11-12_第一阶段微观启动准备'
GOAL = BASE / '2026-11-12_GOAL_第一阶段48组微观实验与业务评价.md'
STOP_STATUSES = {'provider_unknown_attempt', 'provider_failed', 'evaluation_error', 'not_started_budget_exhausted'}


def guarded_request(original, failures):
    async def request(client, budget, logger, job, window, number, halt):
        try:
            result = await original(client, budget, logger, job, window, number, halt)
        except BaseException:
            halt.set()
            raise
        if result.get('status') in STOP_STATUSES:
            halt.set()
            failures.append({'job': result.get('job', job), 'attempt': number,
                'status': result['status'], 'call_id': result.get('call_id'),
                'http_status': result.get('http_status')})
        return result
    return request


def preflight():
    async def check():
        for status in STOP_STATUSES:
            records = []
            async def original(*args):
                return {'status': status, 'job': {'window_id': 'synthetic'}, 'http_status': 429}
            halt = asyncio.Event()
            result = await guarded_request(original, records)(None, None, None, {}, {}, 1, halt)
            assert result['status'] == status and halt.is_set() and len(records) == 1
        records = []
        async def accepted(*args):
            return {'status': 'validation_failed'}
        halt = asyncio.Event()
        await guarded_request(accepted, records)(None, None, None, {}, {}, 1, halt)
        assert not records and not halt.is_set(), 'Content errors follow existing eligible repair policy'
    asyncio.run(check())
    print(json.dumps({'stop_guard_checks': 5, 'provider_calls': 0, 'frozen_sources_edited': False}))


def execute(authorized):
    if authorized is not True:
        raise ValueError('Explicit user instruction to execute the321-scope GOAL required')
    if OUT.exists():
        raise ValueError('Existing phase output; inspect, never automatically restart')
    manifest = read(PREP / 'manifest.json')
    assert sha(GOAL) == manifest['goal_sha256']
    for name, expected in manifest['files'].items():
        assert sha(PREP / name) == expected
    preparation = read(PREP / 'preparation.json')
    for name, expected in preparation['source_sha256'].items():
        assert sha(ROOT / name) == expected
    assert preparation['phase1_future_attempt_max'] == 321
    from continue_capstone_cp00_20261112 import run as run_old, verify_plan
    from run_capstone_cp01_20261112 import run as run_new, verify_frozen
    verify_plan()
    verify_frozen()
    for path in [CP00, CP01]:
        assert not (path / 'run').exists()
        assert not (path / 'authorization.json').exists()
        assert not (path / 'continuation_authorization.json').exists()
    preflight()
    save(OUT / 'goal_execution_authorization.json', {
        'at_UTC': datetime.now(timezone.utc).isoformat(), 'source': 'User explicitly invoked the named GOAL in chat',
        'goal_sha256': sha(GOAL), 'phase_driver_sha256': sha(Path(__file__)),
        'CP00_future_max': 81, 'CP00_parent_cap': 240, 'CP00_already_charged': 159,
        'CP01_independent_cap': 240, 'phase_future_max': 321,
        'unknown_replay_allowed': False, 'other_paid_batches_allowed': False,
        'additive_stop_guard': 'Any provider failure or unknown halts current batch and prevents next batch; frozen scientific inputs and accounting unchanged.'})
    import run_capstone_v2_5_20261109 as engine
    failures = []
    state = {'state': 'running_CP00', 'CP00': 'started', 'CP01': 'not_started', 'stop_records': failures,
             'business_scoring': 'not_started', 'phase_future_max': 321, 'macro_execution': False}
    save(OUT / 'execution_progress_initial.json', dict(state))
    try:
        with patch.object(engine, 'request', guarded_request(engine.request, failures)):
            run_old(True)
            old_status = read(CP00 / 'run/execution_status.json')
            if failures or old_status.get('provider_halt'):
                state.update(state='halted_no_automatic_resume', CP00='halted', CP01='not_started_due_to_CP00_halt')
            else:
                state['CP00'] = 'allowed_execution_finished'
                state['CP01'] = 'started'
                print('CP00 execution finished without a new stop; start independent CP01', flush=True)
                run_new(240)
                new_status = read(CP01 / 'run/execution_status.json')
                if failures or new_status.get('provider_halt'):
                    state.update(state='halted_no_automatic_resume', CP01='halted')
                else:
                    state.update(state='execution_finished_scoring_pending', CP01='allowed_execution_finished')
    except Exception as exc:
        state.update(state='halted_local_or_transport_exception_no_automatic_resume', error_type=type(exc).__name__)
        # Do not print exception messages: provider configuration may contain secrets.
        print('Phase halted:', type(exc).__name__, flush=True)
    finally:
        usage = {}
        for label, path in [('CP00', CP00), ('CP01', CP01)]:
            if (path / 'run/budget_usage.json').exists():
                usage[label] = read(path / 'run/budget_usage.json')
        state['budget_usage_saved'] = usage
        save(OUT / 'execution_driver_result.json', state)
    print(json.dumps({'state': state['state'], 'CP00': state['CP00'], 'CP01': state['CP01'],
                      'stop_records': len(failures), 'scoring': state['business_scoring']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--execute-authorized-goal', action='store_true')
    args = parser.parse_args()
    if args.preflight:
        preflight()
    else:
        execute(args.execute_authorized_goal)
