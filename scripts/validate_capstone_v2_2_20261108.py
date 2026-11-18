"""Targeted V2.2 repair snapshot, output replay and offline behavior checks.

No provider client is constructed. Saved experiment artifacts are never rewritten.
This is a scoped repair experiment, not a repository-wide source audit.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_capstone_followup_20261108 import OUT as OLD, read, save, sha

OUT = OLD.parent.parent / '2026-11-08_V2_2_最小修复与稳健性'
CHANGED = ['src/verification.py', 'src/stages/participation.py',
           'src/stages/reconsideration.py', 'src/stages/bid_documents.py']


def initialize():
    if (OUT / 'baseline.json').exists():
        raise RuntimeError('Baseline already captured; do not overwrite it')
    protocol = read(OLD / 'protocol.json')
    files = sorted(set(CHANGED + list(protocol['code_sha256'])))
    for name in files:
        source = ROOT / name
        target = OUT / 'baseline' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    artifacts = sorted(set([OLD / p for p in ['protocol.json', 'windows.json',
        'measurement_targets.json', 'sample_manifest.json', 'ai_review_annotations.json',
        'content_review_summary.json', 'execution_accounting.json']]
        + list(OLD.glob('*/jobs/*/*-attempt-*.json'))
        + [OLD / batch / 'llm_calls.jsonl' for batch in ('confirmation', 'organization')]))
    save(OUT / 'baseline.json', {
        'before_source': {p: sha(ROOT / p) for p in files},
        'preserved_prior_artifacts': {str(p.relative_to(ROOT)): sha(p) for p in artifacts},
        'old_experiment': str(OLD.relative_to(ROOT)),
        'scope': 'New repair baseline. Prior 194 calls and scores remain unchanged.',
        'provider_call_cap': 0, 'macro_changes': False})
    print('Captured V2.1 source baseline and prior experiment hashes. Provider calls: 0.')


def run(attempt='offline-attempt-002'):
    from src.agent_runtime import AgentRuntime
    from src.models import ParticipationDecision, dump
    from src.stages.bid_documents import generate_bid_documents
    from src.verification import require_condition_disposition, conditions
    from run_capstone_core_validation_20261108 import NoProviderNetwork, v0
    from tests.test_verification_conditions import solo_state
    from tests.test_capstone_v2_2_repairs import FinalConditionsClient

    result_dir = OUT / attempt
    if (result_dir / 'offline_result.json').exists():
        raise RuntimeError('Preserve the completed offline run; do not overwrite it')
    baseline = read(OUT / 'baseline.json')
    spec = importlib.util.spec_from_file_location('v22_frozen_v21_verification', OUT / 'baseline/src/verification.py')
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    windows = read(OLD / 'windows.json')
    guard = NoProviderNetwork()
    rows = []
    stage_rows = []
    with asyncio.Runner() as runner:
        runner.get_loop()
        with patch.object(socket.socket, 'connect', guard.block), patch.object(socket.socket, 'connect_ex', guard.block), \
             patch('src.llm_client.OpenAICompatibleClient.from_env', side_effect=RuntimeError('Offline V2.2 provider cap is zero')):
            for batch in ('confirmation', 'organization'):
                for path in sorted((OLD / batch / 'jobs').glob('*/final-attempt-*.json')):
                    original_hash = sha(path)
                    old = read(path)
                    data = deepcopy(old['parsed'])
                    records = windows[path.parent.name[:11]]['conditions']
                    errors = {}
                    for arm, validator in [('v2_1', before.require_condition_disposition),
                                           ('v2_2', require_condition_disposition)]:
                        try:
                            validator(data, records)
                            errors[arm] = None
                        except (ValueError, TypeError, KeyError) as exc:
                            errors[arm] = f'{type(exc).__name__}: {exc}'
                    rows.append({'batch': batch, 'job_id': path.parent.name, 'attempt_file': path.name,
                                 'original_status': old['status'], 'guard_errors': errors,
                                 'parsed_unchanged': data == old['parsed'],
                                 'source_sha256': original_hash, 'source_unchanged': original_hash == sha(path)})
            for hard in (True, False):
                state = solo_state()
                state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid', 'fixture intent')]
                client = FinalConditionsClient(hard=hard)
                runtime = AgentRuntime(client, profile='smoke')
                runner.run(generate_bid_documents(state, runtime))
                records = conditions(state, 'designer_001', 'design_package')
                case = 'final-only-hard-waits' if hard else 'final-only-optional-retained-and-continues'
                save(result_dir / 'stage_cases' / case / 'state.json', dump(state))
                save(result_dir / 'stage_cases' / case / 'trace.json', {
                    'synthetic_fixture': True, 'provider_calls': 0, 'fixture_final_responses': client.final_calls,
                    'condition_register': records, 'recovery_events': runtime.recovery_events})
                stage_rows.append({'case': case, 'passed': bool(records) and bool(state.bid_documents) == (not hard)
                                   and client.final_calls == 1 and not runtime.recovery_events,
                                   'bid_count': len(state.bid_documents), 'provider_calls': 0})
            closures = v0(result_dir / 'closure_regression', runner)
    unchanged = {p: sha(ROOT / p) == h for p, h in baseline['preserved_prior_artifacts'].items()}
    known_false_positives = [r for r in rows if (r['batch'], r['job_id']) in {
        ('confirmation', 'FOLLOWUP-12-v2_baseline-r2'), ('organization', 'FOLLOWUP-02-role_discussion-r1')}]
    result = {'provider_requests': 0, 'blocked_network_attempts': guard.attempts,
              'replayed_final_outputs': len(rows),
              'guard_rejections_before': sum(r['guard_errors']['v2_1'] is not None for r in rows),
              'guard_rejections_after': sum(r['guard_errors']['v2_2'] is not None for r in rows),
              'after_error_counts': dict(Counter(r['guard_errors']['v2_2'] for r in rows if r['guard_errors']['v2_2'])),
              'known_false_positive_attempts': len(known_false_positives),
              'known_false_positives_now_accepted': all(r['guard_errors']['v2_2'] is None for r in known_false_positives),
              'all_raw_and_parsed_outputs_preserved': all(r['parsed_unchanged'] and r['source_unchanged'] for r in rows),
              'preserved_prior_artifacts': unchanged, 'stage_cases': stage_rows, 'closure_regressions': closures,
              'changed_source': {p: {'before': baseline['before_source'][p], 'after': sha(ROOT / p)} for p in CHANGED},
              'scope': 'Guard replay and synthetic stage/closure verification; not new LLM responses, quality scores or external validation.'}
    save(result_dir / 'saved_response_guard_replay.json', rows)
    save(result_dir / 'offline_result.json', result)
    assert len(rows) == 122 and len(known_false_positives) == 4
    assert result['known_false_positives_now_accepted'] and result['all_raw_and_parsed_outputs_preserved']
    assert all(unchanged.values()) and all(r['passed'] for r in stage_rows + closures) and guard.attempts == 0
    print(json.dumps({k: v for k, v in result.items() if k not in {
        'after_error_counts', 'preserved_prior_artifacts', 'changed_source', 'closure_regressions'}}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['init', 'run'])
    parser.add_argument('--attempt', default='offline-attempt-002')
    args = parser.parse_args()
    if args.phase == 'init':
        initialize()
    else:
        if not args.attempt.startswith('offline-attempt-') or Path(args.attempt).name != args.attempt:
            raise ValueError('Use a new local offline-attempt name')
        run(args.attempt)


if __name__ == '__main__':
    main()
