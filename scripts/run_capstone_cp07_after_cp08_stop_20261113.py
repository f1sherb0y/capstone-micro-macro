"""Versioned CP07 entry recognizing a successfully completed CP08 continuation.

The frozen CP07 generation, messages, stage caps and 864 ledger are reused
unchanged. Only the explicitly superseded predecessor stop is resolved here.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import uuid

from capstone_cp_common_20261112 import ROOT, read, save, sha, no_provider
from continue_capstone_cp01_20261112 import process_ancestors
import run_capstone_cp07_20261113 as original
from continue_capstone_cp08_20261113 import CONT as CP08_CONT, NEW_AUTH, require_new_scope

MASTER, OUT = original.MASTER, original.OUT
ENTRY_SEAL = OUT / 'resume_entry_preflight.json'


def check_resumed_predecessor():
    plan = read(CP08_CONT / 'plan.json')
    auth = require_new_scope(plan)
    assert not (MASTER / 'PAID_HALT.json').exists(), 'A new global paid stop is active'
    receipt = read(CP08_CONT / 'launch_authorization.json')
    assert receipt['new_scope_authorization_sha256'] == sha(NEW_AUTH)
    status = read(CP08_CONT / 'run/execution_status.json')
    assert not status['provider_halt'] and not status['stop_records']
    assert status['all_first_slots_accounted'] and status['calls']['charged_or_reserved_calls'] == 928
    assert status['historical_attempt_copies_not_new_calls'] == 148
    assert status['original_unknowns_never_replayed'] == 2 and status['new_attempts'] == 780
    assert auth['batch_limits']['CP07'] == 864
    for row in plan['attempted_jobs_excluded'].values():
        assert sha(ROOT / row['path']) == row['sha256']


def verify_entry():
    p = original.verify_frozen()
    seal = read(ENTRY_SEAL)
    assert seal['passed'] and seal['wrapper_sha256'] == sha(__file__)
    assert seal['original_runner_sha256'] == sha(Path(original.__file__))
    assert seal['protocol_sha256'] == sha(OUT / 'protocol.json')
    return p


def preflight():
    with no_provider() as counts:
        p = original.verify_frozen()
        assert p['max_calls'] == 864 and p['max_repairs'] == 0
        assert read(OUT / 'preflight.json')['passed']
        assert not (OUT / 'run').exists() and not (OUT / 'authorization.json').exists()
        assert len(read(CP08_CONT / 'plan.json')['pending_first_jobs']) == 780
        if not NEW_AUTH.exists():
            try:
                check_resumed_predecessor()
            except ValueError:
                pass
            else:
                raise AssertionError('Missing new stop scope unexpectedly passed')
        save(ENTRY_SEAL, {'passed': True, 'wrapper_sha256': sha(__file__),
            'original_runner_sha256': sha(Path(original.__file__)), 'protocol_sha256': sha(OUT / 'protocol.json'),
            'generation_or_scientific_input_changes': 0,
            'only_changed_gate': 'Recognize sealed CP08 continuation completion under new post-stop scope; historical two unknowns stay excluded.',
            'new_provider_calls': 0, **counts})
    print('CP07 resumed-predecessor entry preflight PASS; original864 generation unchanged;0 calls')


def launch(cap):
    if type(cap) is not int or cap != 864:
        raise ValueError('Exact original CP07 cap864 required')
    verify_entry()
    check_resumed_predecessor()
    if (OUT / 'run').exists() or (OUT / 'authorization.json').exists():
        raise ValueError('Existing CP07 run; never replay')
    token = uuid.uuid4().hex
    save(OUT / 'authorization.json', {'at_UTC': datetime.now(timezone.utc).isoformat(), 'max_calls': cap,
        'master_authorization_sha256': sha(MASTER / 'authorization.json'),
        'source': 'Explicit user post-CP08-stop scope, within unchanged original master cap',
        'new_scope_authorization_sha256': sha(NEW_AUTH),
        'launcher_pid': os.getpid(), 'token': token,
        'runner_sha256': sha(Path(original.__file__)), 'wrapper_sha256': sha(__file__),
        'protocol_sha256': sha(OUT / 'protocol.json'), 'entry_seal_sha256': sha(ENTRY_SEAL)})
    done = subprocess.run([sys.executable, str(Path(__file__)), 'worker', '--token', token], cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if done.returncode:
        original.paid_stop('CP07_resumed_entry_worker_exit', exit_code=done.returncode)
        raise RuntimeError('CP07 worker stopped; inspect without restarting')


def worker(token):
    receipt = read(OUT / 'authorization.json')
    assert token and token == receipt['token'] and receipt['launcher_pid'] in process_ancestors()
    assert receipt['wrapper_sha256'] == sha(__file__)
    assert receipt['entry_seal_sha256'] == sha(ENTRY_SEAL)
    assert receipt['new_scope_authorization_sha256'] == sha(NEW_AUTH)
    verify_entry()
    check_resumed_predecessor()
    try:
        with patch.object(original, 'check_master', check_resumed_predecessor):
            original.worker(token)
    except Exception as exc:
        original.paid_stop('CP07_resumed_entry_local_exception', error_type=type(exc).__name__)
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['preflight', 'run', 'worker'])
    p.add_argument('--authorize-max-calls', type=int)
    p.add_argument('--token')
    a = p.parse_args()
    if a.command == 'preflight':
        preflight()
    elif a.command == 'run':
        launch(a.authorize_max_calls)
    else:
        worker(a.token)
