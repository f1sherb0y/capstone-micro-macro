"""Compile CP03E/X offline, or execute a separately authorized serial batch."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from capstone_cp_common_20261112 import ROOT, CP03, no_provider, read, save, sha
from integration.capstone_finish_native import DIRECTORIES, MASTER, check_master, paid_stop


def verify_frozen(batch):
    directory = DIRECTORIES[batch]
    p = read(directory / 'protocol.json')
    assert p['batch'] == batch and p['max_final_retries'] == 0
    assert sha(directory / 'sample_manifest.json') == p['manifest_sha256']
    assert sum(j['expected_max_provider_calls'] for j in p['jobs']) == p['max_calls']
    assert len(p['jobs']) == p['chains'] == p['project_groups'] * 12
    for key in ['code_sha256', 'source_sha256']:
        for path, digest in p[key].items():
            assert sha(ROOT / path) == digest, 'Frozen macro implementation/source changed: ' + path
    for job in p['jobs']:
        assert sha(ROOT / job['config_path']) == job['config_sha256']
    return directory, p


def compile_all(batch):
    directory, p = verify_frozen(batch)
    from integration.contractor_tender_development import verify_bundle
    if batch == 'CP03E':
        from integration.capstone_finish_native import build_bundle
    else:
        from integration.capstone_extended_lifecycle import build_bundle
    comparisons, rows = defaultdict(dict), []
    with no_provider() as counts:
        for i, job in enumerate(p['jobs'], 1):
            source = directory / 'chains' / job['chain_id'] / 'input'
            config = read(ROOT / job['config_path'])
            if not source.exists():
                build_bundle(source, config)
            verified = verify_bundle(source)
            assert read(source / 'case-config.json') == config
            request = read(source / 'macro-request.json')
            project, = request['initial_projects']
            assert project['project_id'] == job['case_id'] and project['initial_budget'] == config['scenario_budget']
            assert request['random_seed'] == job['seed'] and project['technical_complexity'] == config['technical_complexity']
            if batch == 'CP03X':
                assert project['region'] == config['domain_region']['region']
                assert project['project_type'] == config['domain_region']['native_project_type']
            comparisons[job['case_id'], job['repeat']][job['arm']] = {
                'initial_projects': request['initial_projects'], 'agents': request['agents'],
                'random_seed': request['random_seed'], 'ticks': request['ticks']}
            rows.append({'chain_id': job['chain_id'], 'input_manifest_sha256': sha(source / 'input-manifest.json'),
                         'files_checked': verified['file_count']})
            if i % 12 == 0:
                print(f'{batch}: compiled source bundles {i}/{len(p["jobs"])}', flush=True)
        for key, arms in comparisons.items():
            assert set(arms) == {'R', 'S', 'D3', 'S4'} and all(v == arms['S'] for v in arms.values()), key
    verify_frozen(batch)
    save(directory / 'preflight.json', {'passed': True, 'all_requested_chain_inputs_compiled': rows,
        'same_fact_four_arm_blocks': len(comparisons), 'planned_calls': p['max_calls'],
        'formal_macro_simulations': 0, 'provider_calls': 0, **counts})
    print(f'{batch} all-source preflight PASS; zero model calls and simulations')


def check_predecessor(batch):
    if batch == 'CP03E':
        previous = CP03
    else:
        previous = DIRECTORIES['CP03E']
    assert not (previous / 'run/HALT.json').exists()
    prior = read(previous / 'protocol.json')
    outcomes = read(previous / 'run/outcomes.json')
    assert len(outcomes) == len(prior['jobs'])
    assert {r['chain_id'] for r in outcomes} == {j['chain_id'] for j in prior['jobs']}
    assert all(r['exit_code'] == 0 and r['verification']['technical_integrity_passed'] for r in outcomes)


def run(batch, cap):
    directory, p = verify_frozen(batch)
    if type(cap) is not int or cap != p['max_calls']:
        raise ValueError('Exact independent input-eligible macro batch cap required')
    check_master(directory)
    check_predecessor(batch)
    preflight = read(directory / 'preflight.json')
    assert preflight['passed'] and len(preflight['all_requested_chain_inputs_compiled']) == len(p['jobs'])
    if (directory / 'run').exists() or (directory / 'authorization.json').exists():
        raise ValueError('Existing macro attempt; no automatic replay')
    from integration.contractor_tender_development import verify_bundle
    from integration.capstone_mechanism_results import verify as verify_chain
    for job, compiled in zip(p['jobs'], preflight['all_requested_chain_inputs_compiled']):
        source = directory / 'chains' / job['chain_id'] / 'input'
        assert job['chain_id'] == compiled['chain_id']
        assert sha(source / 'input-manifest.json') == compiled['input_manifest_sha256']
        verify_bundle(source)
    save(directory / 'authorization.json', {'batch': batch, 'max_calls': cap,
        'at_UTC': datetime.now(timezone.utc).isoformat(), 'protocol_sha256': sha(directory / 'protocol.json'),
        'master_authorization_sha256': sha(MASTER / 'authorization.json'),
        'source': 'Explicitly activated master scope; cannot override a subsequent paid halt',
        'macro_final_retries': 0, 'automatic_resume': False})
    (directory / 'run').mkdir()
    outcomes = []
    try:
        for job in p['jobs']:
            check_master(directory)
            chain = directory / 'chains' / job['chain_id']
            source = chain / 'input'
            command = [sys.executable, '-m', 'integration.run', '--input', str(source / 'macro-request.json'),
                '--output', str(chain / 'runtime'), '--llm', '--input-format', 'gba_request',
                '--macro-mode', 'gba_v1_module', '--allow-native-project-generation',
                '--allow-native-initial-projects-with-generation',
                '--agent-client-factory', 'integration.capstone_finish_native:build_agent_client',
                '--agent-client-config', str(source / 'native-host.json'),
                '--module-assembly-hook', 'integration.origin_model_lifecycle:configure_assembly',
                '--module-assembly-config', str(source / 'assembly-host.json')]
            assert not (chain / 'runtime').exists() and not (chain / 'command.json').exists()
            save(chain / 'command.json', command)
            with (chain / 'stdout.log').open('xb') as stdout, (chain / 'stderr.log').open('xb') as stderr:
                done = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            save(chain / 'exit.json', {'exit_code': done.returncode})
            outcome = {'chain_id': job['chain_id'], 'exit_code': done.returncode, 'verification': None}
            try:
                assert done.returncode == 0 and not (directory / 'run/HALT.json').exists()
                check_master(directory)
                outcome['verification'] = verify_chain(chain)
                assert outcome['verification']['actual_model_calls'] <= job['expected_max_provider_calls']
            except Exception as exc:
                outcome['verification_error_type'] = type(exc).__name__
                outcomes.append(outcome)
                (directory / 'run/outcomes.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                raise
            outcomes.append(outcome)
            (directory / 'run/outcomes.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except Exception as exc:
        if not (directory / 'run/HALT.json').exists():
            save(directory / 'run/HALT.json', {'reason': 'native_chain_or_verification_stop', 'error_type': type(exc).__name__, 'automatic_resume': False})
        paid_stop(directory, 'native_chain_or_verification_stop:' + type(exc).__name__)
        raise
    save(directory / 'run/execution_status.json', {'state': 'execution_finished_scoring_pending',
        'all_chains_verified': len(outcomes) == len(p['jobs']), 'provider_halt': False,
        'actual_provider_calls': sum(r['verification']['actual_model_calls'] for r in outcomes),
        'planned_max': p['max_calls'], 'macro_business_analysis': 'pending'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'run'])
    parser.add_argument('--batch', choices=['CP03E', 'CP03X'], required=True)
    parser.add_argument('--authorize-max-calls', type=int)
    args = parser.parse_args()
    if args.command == 'preflight':
        compile_all(args.batch)
    else:
        run(args.batch, args.authorize_max_calls)
