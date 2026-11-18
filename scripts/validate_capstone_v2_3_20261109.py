"""Scoped source-bound repair snapshot and offline checks; provider cap is0."""
from pathlib import Path
import argparse
import asyncio
from copy import deepcopy
import importlib.util
import json
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_capstone_v2_2_robustness_20261108 import OUT as OLD, read, save, sha

OUT = OLD.parents[2] / '2026-11-09_V2_3_来源绑定修复'
FILES = ['src/verification.py', 'src/models.py', 'src/agent_runtime.py',
         'src/stages/participation.py', 'src/stages/reconsideration.py', 'src/stages/bid_documents.py']


def initialize():
    if (OUT / 'baseline.json').exists():
        raise RuntimeError('Preserve the captured baseline')
    release = read(OLD / 'release_manifest.json')
    assert all(sha(OLD / name) == digest for name, digest in release['files'].items())
    for name in FILES:
        dest = OUT / 'baseline' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / name).read_bytes())
    save(OUT / 'baseline.json', {'before_source': {n: sha(ROOT / n) for n in FILES},
        'prior_experiment': str(OLD.relative_to(ROOT)), 'prior_release_manifest_sha256': sha(OLD / 'release_manifest.json'),
        'prior_released_files': release['files'], 'provider_call_cap': 0,
        'scope': 'Keep the completed67-call experiment and64 first-response scores unchanged. No macro changes.'})
    print('Captured V2.2 baseline; prior67-call release intact. Provider requests0.')


def run():
    from src.verification import require_condition_disposition
    from run_capstone_core_validation_20261108 import NoProviderNetwork, v0
    from src.agent_runtime import AgentRuntime
    from src.models import ParticipationDecision, dump
    from src.stages.bid_documents import generate_bid_documents
    from src.company_grounding import company_evidence, require_company_assessment
    from tests.test_verification_conditions import solo_state
    from tests.test_capstone_v2_3_repairs import SourceFixtureClient, unknown_assessment
    if (OUT / 'offline_result.json').exists():
        raise RuntimeError('Preserve this completed offline attempt')
    spec = importlib.util.spec_from_file_location('v23_frozen_v22_guard', OUT / 'baseline/src/verification.py')
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    windows = read(OLD / 'windows.json')
    baseline = read(OUT / 'baseline.json')
    guard = NoProviderNetwork()
    replay = []
    stages = []
    source_rows = []
    source_plan = [
        {'id': 'name-and-address-not-scope', 'raw': {'company_id': 'synthetic-c', 'company_name': '顶级设计建造集团', 'office_location': '澳门', 'staff_scale': '9999'},
         'topic': 'scope', 'expect': 'unknown'},
        {'id': 'broad-scope-not-catalogue', 'raw': {'company_id': 'synthetic-c', 'business_scope': '建筑材料生产销售'},
         'topic': 'product_range', 'expect': 'unknown'},
        {'id': 'provided-scope-quotable', 'raw': {'company_id': 'synthetic-c', 'business_scope': '公共建筑施工'},
         'topic': 'scope', 'expect': 'provided'},
        {'id': 'synthetic-catalogue-quotable', 'raw': {'company_id': 'synthetic-c', 'product_catalogue': 'SYNTHETIC: aggregate materials for this fictional task only.'},
         'topic': 'product_range', 'expect': 'provided'},
        {'id': 'synthetic-cost-worksheet-quotable', 'raw': {'company_id': 'synthetic-c', 'historical_cost_records': 'SYNTHETIC prior worksheet: unitA=100MOP; not actual company cost.'},
         'topic': 'historical_cost_basis', 'expect': 'provided'},
    ]
    save(OUT / 'source_fixture_plan.json', {'origin': 'Author-declared synthetic fixtures; no real company records', 'cases': source_plan})
    with asyncio.Runner() as runner:
        runner.get_loop()
        with patch.object(socket.socket, 'connect', guard.block), patch.object(socket.socket, 'connect_ex', guard.block), \
             patch('src.llm_client.OpenAICompatibleClient.from_env', side_effect=RuntimeError('V2.3 offline provider cap0')):
            for path in sorted((OLD / 'run/jobs').glob('*/attempt-*.json')):
                before_hash = sha(path)
                result = read(path)
                data = deepcopy(result['parsed'])
                records = windows[result['job']['window_id']]['conditions']
                errors = {}
                for name, validate in [('v2_2', old.require_condition_disposition), ('v2_3', require_condition_disposition)]:
                    try:
                        validate(data, records)
                        errors[name] = None
                    except (ValueError, TypeError, KeyError) as exc:
                        errors[name] = str(exc)
                replay.append({'job': path.parent.name, 'attempt': result['attempt'], 'source_sha256': before_hash,
                               'guard_errors': errors, 'raw_and_parsed_unchanged': before_hash == sha(path) and data == result['parsed']})
            for case in source_plan:
                evidence = company_evidence(case['raw'])
                assessment = unknown_assessment(evidence)
                for topic, row in evidence['topics'].items():
                    if row['status'] == 'provided':
                        ref = row['allowed_source_refs'][0]
                        assessment['topics'][topic] = {'status': 'provided', 'source_ref': ref, 'quote': evidence['sources'][ref]['text']}
                require_company_assessment({'company_assessment': assessment}, evidence)
                passed = evidence['topics'][case['topic']]['status'] == case['expect']
                source_rows.append({'fixture_id': case['id'], 'passed': passed, 'evidence': evidence, 'assessment': assessment})
            state = solo_state()
            state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid', 'synthetic proposal')]
            runtime = AgentRuntime(SourceFixtureClient(), profile='smoke', company_grounding=True)
            runner.run(generate_bid_documents(state, runtime))
            save(OUT / 'stage_source_binding/state.json', dump(state))
            stages.append({'case': 'source-assessment-persists-without-creating-package-review',
                           'passed': len(state.bid_documents) == 1 and bool(state.bid_documents[0].company_assessment)
                                     and not state.verification_reviews and not runtime.recovery_events})
            closures = v0(OUT / 'condition_closure', runner)
    preserved = {name: sha(OLD / name) == digest for name, digest in baseline['prior_released_files'].items()}
    old_fps = read(OLD / 'observed_guard_edge_cases.json')
    known = [r for r in replay if any(r['job'] == f['job_id'] and r['attempt'] == f['attempt'] for f in old_fps)]
    result = {'provider_requests': 0, 'network_attempts': guard.attempts, 'saved_responses_replayed': len(replay),
              'old_guard_rejections': sum(r['guard_errors']['v2_2'] is not None for r in replay),
              'new_guard_rejections': sum(r['guard_errors']['v2_3'] is not None for r in replay),
              'known_false_positive_attempts': len(known), 'known_false_positives_released': all(r['guard_errors']['v2_3'] is None for r in known),
              'source_fixtures': source_rows, 'stages': stages, 'condition_closure': closures,
              'prior_release_unchanged': preserved, 'old_raw_and_parsed_unchanged': all(r['raw_and_parsed_unchanged'] for r in replay),
              'source_changes': {p: {'before': h, 'after': sha(ROOT / p)} for p, h in baseline['before_source'].items()},
              'added_source': {'src/company_grounding.py': sha(ROOT / 'src/company_grounding.py')},
              'limits': 'Replay checks negation/condition guards only. Old outputs lack the new source contract and are not marked worse for that. Reference validity does not prove narrative faithfulness; old grounding errors and scores are not rewritten or claimed fixed.'}
    save(OUT / 'old_response_guard_replay.json', replay)
    save(OUT / 'offline_result.json', result)
    assert len(replay) == 67 and len(known) == 4 and result['known_false_positives_released']
    assert all(preserved.values()) and result['old_raw_and_parsed_unchanged'] and guard.attempts == 0
    assert all(r['passed'] for r in source_rows + stages + closures)
    print(json.dumps({k: v for k, v in result.items() if k not in {'source_fixtures', 'source_changes', 'prior_release_unchanged', 'condition_closure'}}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['init', 'run'])
    args = parser.parse_args()
    initialize() if args.phase == 'init' else run()
