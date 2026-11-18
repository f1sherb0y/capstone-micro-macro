"""Prepare and launch a fresh-process continuation of stopped CP01.

Shares the original240 ledger; preserves two unknowns; never reruns CP00.
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
from unittest.mock import patch
import uuid

from capstone_cp_common_20261112 import ROOT, CP01, engine_binding, no_provider, read, save, sha
from run_capstone_cp01_20261112 import verify_frozen
from run_capstone_phase1_goal_20261112 import guarded_request

CONT = CP01 / 'continuation-001'


def identity(job):
    return f"{job['window_id']}-{job['arm']}-r{job['repeat']}"


def process_ancestors():
    """Account for Windows venv python.exe redirectors without weakening isolation."""
    if os.name != 'nt':
        return [os.getppid()]
    import ctypes
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('Cannot verify fresh-worker process ancestry')
    parents = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    result, current = [], os.getpid()
    for _ in range(8):
        current = parents.get(current, 0)
        if not current or current in result:
            break
        result.append(current)
    return result


def assert_transport_open(client):
    for root in [client._chat_model.root_client, client._chat_model.root_async_client]:
        closed = getattr(root, 'is_closed', None)
        closed = closed() if callable(closed) else closed
        if closed is not False:
            raise RuntimeError('Local transport is closed or cannot prove open; do not reserve a call')


def open_checked_request(original, failures):
    guarded = guarded_request(original, failures)
    async def request(client, budget, logger, job, window, number, halt):
        if halt.is_set():
            return {'job': job, 'status': 'not_started_provider_halt'}
        try:
            assert_transport_open(client)
        except Exception:
            halt.set()
            raise
        return await guarded(client, budget, logger, job, window, number, halt)
    return request


def prepare():
    protocol = verify_frozen()
    status = read(CP01 / 'run/execution_status.json')
    firsts = read(CP01 / 'run/first_results.json')
    assert status['provider_halt'] and status['calls']['charged_or_reserved_calls'] == 2
    assert not (CONT / 'run').exists() and not (CONT / 'launch_authorization.json').exists()
    unknown, pending = {}, []
    for row in firsts:
        if row['status'] == 'not_started_provider_halt':
            pending.append(row['job'])
        else:
            assert row['status'] == 'provider_unknown_attempt'
            path = CP01 / 'run/jobs' / identity(row['job']) / 'attempt-1.json'
            assert read(path) == row
            unknown[identity(row['job'])] = {'path': str(path.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(path)}
    assert len(pending) == 190 and len(unknown) == 2 and len(firsts) == 192
    sources = [CP01 / 'protocol.json', CP01 / 'windows.json', CP01 / 'targets.json',
               CP01 / 'run/first_results.json', CP01 / 'run/execution_status.json',
               CP01 / 'run/budget_usage.json', CP01 / 'run/budget.sqlite', CP01 / 'run/llm_calls.jsonl',
               ROOT / 'scripts/run_capstone_phase1_goal_20261112.py']
    plan = {'state': 'prepared_not_run_authorized', 'runner_sha256': sha(Path(__file__)),
        'parent_protocol_sha256': sha(CP01 / 'protocol.json'), 'parent_run_id': protocol['run_id'],
        'parent_budget_id': protocol['budget_id'], 'same_parent_cap': 240, 'charged_before': 2,
        'future_max': 238, 'max_repairs': 48, 'pending_first_jobs': pending,
        'unknown_attempts_never_replayed': unknown,
        'source_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sources},
        'runtime_policy': 'Fresh child process, open transport check before reservation, no internal retries, any provider failure halts.',
        'new_paid_calls': 0}
    save(CONT / 'plan.json', plan)
    return plan


def verify_plan():
    protocol = verify_frozen()
    plan = read(CONT / 'plan.json')
    assert sha(Path(__file__)) == plan['runner_sha256']
    for path, expected in plan['source_sha256'].items():
        assert sha(ROOT / path) == expected, 'Stop snapshot changed: ' + path
    for item in plan['unknown_attempts_never_replayed'].values():
        assert sha(ROOT / item['path']) == item['sha256']
    assert not {identity(j) for j in plan['pending_first_jobs']} & set(plan['unknown_attempts_never_replayed'])
    assert len(plan['pending_first_jobs']) == 190
    return protocol, plan


async def isolation_probe():
    # Start the event loop BEFORE blocking sockets (Windows needs a local self-pipe).
    import socket
    from langchain_openai.chat_models._client_utils import _get_default_async_httpx_client
    network = []
    def deny(*args, **kwargs):
        network.append(True)
        raise AssertionError('No network in local isolation probe')
    with patch.object(socket.socket, 'connect', deny), patch.object(socket.socket, 'connect_ex', deny):
        first = _get_default_async_httpx_client('https://phase1-isolation.invalid', 60)
        initially_open = not first.is_closed
        await first.aclose()
        second = _get_default_async_httpx_client('https://phase1-isolation.invalid', 60)
        assert first is second and second.is_closed
        assert initially_open and not network
    return {'pid': os.getpid(), 'parent_pid': os.getppid(), 'ancestor_pids': process_ancestors(), 'initially_open': initially_open,
            'closed_cache_hazard_reproduced': True, 'network_attempts': 0, 'paid_calls': 0}


def preflight():
    protocol, plan = verify_plan()
    from src.coordination.tasks import TaskStore, TaskConflict
    from src.coordination.model_budget import ModelCallBudget
    with no_provider() as counts, tempfile.TemporaryDirectory(prefix='CP01-cont-budget-') as tmp:
        path = Path(tmp) / 'budget.sqlite'
        shutil.copy2(CP01 / 'run/budget.sqlite', path)
        store = TaskStore(run_id=protocol['run_id'], organization_ids=['experiment-host'], path=path)
        try:
            budget = ModelCallBudget(store=store, budget_id=protocol['budget_id'], max_calls=240)
            assert budget.usage()['charged_or_reserved_calls'] == 2
            assert budget.reserve('offline-pending190', 190)
            assert budget.reserve('offline-repairs48', 48)
            assert not budget.reserve('offline-overflow', 1)
            budget.finish('offline-pending190')
            budget.finish('offline-repairs48')
            assert budget.usage()['charged_or_reserved_calls'] == 2
            for jid in plan['unknown_attempts_never_replayed']:
                try:
                    budget.reserve(jid + ':1', 1)
                except TaskConflict:
                    pass
                else:
                    raise AssertionError('Unknown attempt replay was not rejected')
        finally:
            store.close()
        from types import SimpleNamespace
        calls = []
        async def fake(*args):
            calls.append(True)
            return {'status': 'accepted'}
        async def gate_check():
            roots = [SimpleNamespace(is_closed=lambda: True), SimpleNamespace(is_closed=lambda: False)]
            client = SimpleNamespace(_chat_model=SimpleNamespace(root_client=roots[0], root_async_client=roots[1]))
            halt = asyncio.Event()
            try:
                await open_checked_request(fake, [])(client, None, None, {}, {}, 1, halt)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Closed local client was accepted')
            assert halt.is_set() and not calls
        try:
            launch(False)
        except ValueError:
            pass
        else:
            raise AssertionError('Unauthorised launch accepted')
    # The fake-client coroutine opens no transport. Create its event loop after
    # the global socket guard, so Windows can create its local self-pipe.
    asyncio.run(gate_check())
    # Genuine child interpreter: no model client, no API key, no external connection.
    probes = []
    for _ in range(2):
        done = subprocess.run([sys.executable, str(Path(__file__)), 'isolation-probe'],
            cwd=ROOT, capture_output=True, text=True, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        probes.append(json.loads(done.stdout.strip()))
    assert all(p['pid'] != os.getpid() and os.getpid() in p['ancestor_pids'] and p['initially_open'] for p in probes)
    verify_plan()
    save(CONT / 'preflight.json', {'passed': True, 'checks': [
        'parent_snapshot_and_unknown_hashes', '190_pending_only', '2_unknown_reservations_rejected',
        'same_cap_2_plus190_plus48', 'overflow_rejected', 'closed_client_stops_before_engine_or_reservation',
        'explicit_scope_required_before_launch', 'two_fresh_child_processes_open_transport'],
        'copied_budget_only': True, 'fresh_process_probe': {'count': 2, 'all_fresh_initially_open': True, 'external_network_attempts': 0},
        'provider_calls': 0, **counts})
    print(json.dumps({'preflight': 'PASS', 'checks': 8, 'pending_firsts': 190,
        'unknown_excluded': 2, 'same_parent_cap': 240, 'future_max': 238, 'new_calls': 0}))


def launch(confirmed):
    if confirmed is not True:
        raise ValueError('Explicit stopped-CP01 continuation scope confirmation required')
    verify_plan()
    assert read(CONT / 'preflight.json')['passed']
    if (CONT / 'run').exists() or (CONT / 'launch_authorization.json').exists():
        raise ValueError('Existing continuation; no automatic replay')
    token = uuid.uuid4().hex
    receipt_path = CONT / 'launch_authorization.json'
    save(receipt_path, {'at_UTC': datetime.now(timezone.utc).isoformat(), 'launcher_pid': os.getpid(),
        'launch_token': token, 'runner_sha256': sha(Path(__file__)), 'plan_sha256': sha(CONT / 'plan.json'),
        'same_parent_cap': 240, 'charged_before': 2, 'future_max': 238,
        'unknown_replay_allowed': False, 'other_paid_batches_allowed': False})
    done = subprocess.run([sys.executable, str(Path(__file__)), 'worker', '--launch-token', token], cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if done.returncode:
        raise RuntimeError('Continuation child exited nonzero; do not restart')


def worker(token):
    receipt = read(CONT / 'launch_authorization.json')
    assert token and token == receipt['launch_token']
    assert os.getpid() != receipt['launcher_pid'] and receipt['launcher_pid'] in process_ancestors()
    assert sha(Path(__file__)) == receipt['runner_sha256']
    assert sha(CONT / 'plan.json') == receipt['plan_sha256']
    protocol, plan = verify_plan()
    assert not (CONT / 'run').exists()
    from src.coordination.tasks import TaskStore
    from src.coordination.model_budget import ModelCallBudget
    with engine_binding(CONT, verify_frozen) as engine:
        client = engine.OpenAICompatibleClient.from_env(model=protocol['model'])
        store = None
        failures = []
        try:
            assert_transport_open(client)
            assert client.request_policy() == read(CP01 / 'authorization.json')['transport']
            client._chat_model.max_tokens = protocol['max_output_tokens']
            params = client._chat_model._default_params
            assert params.get('max_tokens', params.get('max_completion_tokens')) == 4096
            save(CONT / 'run/process_identity.json', {'worker_pid': os.getpid(), 'launcher_pid': os.getppid(),
                'isolated_process': True, 'transport_open_before_budget': True})
            for jid, item in plan['unknown_attempts_never_replayed'].items():
                dest = CONT / 'run/jobs' / jid / 'attempt-1.json'
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / item['path'], dest)
            store = TaskStore(run_id=protocol['run_id'], organization_ids=['experiment-host'], path=CP01 / 'run/budget.sqlite')
            budget = ModelCallBudget(store=store, budget_id=protocol['budget_id'], max_calls=240)
            assert budget.usage()['charged_or_reserved_calls'] == 2
            logger = engine.LLMCallAuditLogger(CONT / 'run', 'CP01-CONTINUATION', client, attempt=2)
            request = open_checked_request(engine.request, failures)
            async def perform():
                halt = asyncio.Event()
                semaphore = asyncio.Semaphore(protocol['concurrency'])
                windows = read(CP01 / 'windows.json')
                async def first(job):
                    async with semaphore:
                        return await request(client, budget, logger, job, windows[job['window_id']], 1, halt)
                try:
                    fresh = await asyncio.gather(*(first(j) for j in plan['pending_first_jobs']))
                    all_rows = {identity(r['job']): r for r in fresh}
                    for jid, item in plan['unknown_attempts_never_replayed'].items():
                        all_rows[jid] = read(ROOT / item['path'])
                    firsts = [all_rows[identity(j)] for j in protocol['jobs']]
                    save(CONT / 'run/first_results_all_slots.json', firsts)
                    if not halt.is_set():
                        repairs = [r for r in firsts if r['status'] in {'invalid_json', 'validation_failed'}]
                        for row in repairs[:48]:
                            await request(client, budget, logger, row['job'], windows[row['job']['window_id']], 2, halt)
                            if halt.is_set():
                                break
                    save(CONT / 'run/execution_status.json', {'provider_halt': halt.is_set(), 'calls': budget.usage(),
                        'stop_records': failures, 'all192_slots_retained': len(firsts) == 192,
                        'original_unknown_copies_not_new_calls': 2, 'scoring': 'pending', 'other_paid_batches': False})
                finally:
                    save(CONT / 'run/budget_usage.json', budget.usage())
                    await client._chat_model.root_async_client.close()
            asyncio.run(perform())
        finally:
            if store is not None:
                store.close()
            client._chat_model.root_client.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare', 'preflight', 'run', 'worker', 'isolation-probe'])
    p.add_argument('--confirm-stopped-cp01-scope', action='store_true')
    p.add_argument('--launch-token')
    args = p.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'preflight':
        preflight()
    elif args.command == 'run':
        launch(args.confirm_stopped_cp01_scope)
    elif args.command == 'worker':
        worker(args.launch_token)
    else:
        print(json.dumps(asyncio.run(isolation_probe())))
