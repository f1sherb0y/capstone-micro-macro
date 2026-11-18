"""Freeze72 four-arm chain configurations; compile sources, never simulate."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

from capstone_cp_common_20261112 import CP03, ROOT, no_provider, read, save, sha

ARMS = ['R', 'S', 'D3', 'S4']
CALLS = {'R': 0, 'S': 2, 'D3': 8, 'S4': 8}
SEEDS = [42, 101, 202]


def rank(value):
    return hashlib.sha256(('CP03-input-only/20261112/' + value).encode()).hexdigest()


def prepare(revise_zero_call_draft=False):
    from prepare_capstone_expansion_20261109 import GROUPS, SOURCE, read_csv
    from src.organization.registry import load_role_configurations
    projects = {r['case_id']: r for r in read_csv(SOURCE / 'simulation_input_projects.csv')}
    groups = {r['case_id']: r['group'] for r in read(GROUPS)['assignments']}
    supported = read(ROOT / 'config/benchmark_macro_batch.json')['first_phase_case_ids']
    selected, seen = [], set()
    for cid in sorted(supported, key=rank):
        if groups[cid] in seen:
            continue
        selected.append(cid)
        seen.add(groups[cid])
        if len(selected) == 6:
            break
    assert len(selected) == 6
    role = load_role_configurations(ROOT / 'config/roles')['Contractor']
    assert len(role.members) == 3
    template = read(ROOT / 'config/case0005_model_lifecycle.json')
    profiles = [
        {'name': 'tighter_budget_lower_complexity', 'budget': 130000000, 'complexity': .35},
        {'name': 'reference_budget_reference_complexity', 'budget': 150000000, 'complexity': .6},
        {'name': 'larger_budget_higher_complexity', 'budget': 180000000, 'complexity': .85},
    ]
    rows, jobs = [], []
    for index, cid in enumerate(selected):
        profile = profiles[index % 3]
        rows.append({'case_id': cid, 'project_group': groups[cid], 'project_name': projects[cid]['project_name'],
                     'source_project_type': projects[cid]['project_type'], 'scenario_profile': profile,
                     'initial_parameters_are': 'controlled_scenario_assumptions_not_historical_cost_or_ability',
                     'scope': 'Supported Macau DBB infrastructure entry only; normalized firms and support roles remain simulation assumptions.'})
        for repeat, seed in enumerate(SEEDS, 1):
            arms = ARMS[repeat-1:] + ARMS[:repeat-1]
            for arm in arms:
                jid = f'{cid}-r{repeat}-{arm}'
                config = deepcopy(template)
                config.update(case_id=cid, run_id='CP03-' + jid, random_seed=seed,
                              scenario_budget=profile['budget'], technical_complexity=profile['complexity'],
                              research_arm=arm, api_total_attempt_cap=max(1, CALLS[arm]),
                              cp03_control={'arm': arm, 'chain_id': jid, 'batch_directory': str(CP03.resolve())})
                config['model_options'].update(strategy='organization_discussion' if arm == 'D3' else 'single_agent',
                                               max_calls=max(1, CALLS[arm]))
                save(CP03 / 'configs' / (jid + '.json'), config)
                jobs.append({'chain_id': jid, 'case_id': cid, 'project_group': groups[cid],
                             'repeat': repeat, 'seed': seed, 'arm': arm,
                             'config_path': str((CP03 / 'configs' / (jid + '.json')).relative_to(ROOT)),
                             'config_sha256': sha(CP03 / 'configs' / (jid + '.json')),
                             'expected_max_provider_calls': CALLS[arm]})
    first = jobs[:4]
    rest = jobs[4:]
    random.Random(2026111203).shuffle(rest)
    jobs = first + rest
    files = ['integration/capstone_mechanism_controls.py', 'integration/capstone_mechanism_native.py',
             'integration/capstone_mechanism_results.py',
             'scripts/prepare_capstone_cp03_20261112.py', 'scripts/run_capstone_cp03_20261112.py']
    # Pin all shared native source modules actually reused by the compiler/host.
    files += ['integration/case_library_lifecycle.py', 'integration/origin_lifecycle_case.py',
              'integration/origin_model_lifecycle.py', 'integration/action_model_host.py',
              'integration/contractor_tender_model_options.py', 'integration/model_tender_native.py',
              'src/actions/model_strategy.py', 'src/actions/organization_strategy.py',
              'config/roles/contractor.json']
    role_path = ROOT / 'config/roles/contractor.json'
    if not role_path.exists():
        candidates = [p for p in (ROOT / 'config/roles').glob('*.json') if read(p).get('role') == 'Contractor']
        assert len(candidates) == 1
        files[-1] = str(candidates[0].relative_to(ROOT)).replace('\\', '/')
    protocol = {'schema': 'CP03-four-arm.v1', 'preparation_date': '2026-11-12',
                'project_groups': 6, 'replicate_blocks': 3, 'arms': ARMS, 'chains': 72,
                'jobs': jobs, 'model': template['model_options']['model'], 'temperature': 0,
                'max_output_tokens': 4096, 'concurrency': 1,
                'first_calls': 324, 'max_calls': 324, 'max_final_retries': 0,
                'provider_calls_authorized': 0,
                'budget_revision': 'The native lifecycle has no safe final-only retry entry. Remove48 hypothetical macro retries;324 strict attempts only, no chain replay.',
                'primary_comparison': 'D3-minus-S4', 'secondary_comparisons': ['D3-minus-S', 'S-minus-R'],
                'primary_macro_numeric': 'cost_deviation_vs_initial_budget_at_comparable_endpoint',
                'comment_source': role.model_dump(mode='json'),
                'comment_source_boundary': 'Configured simulation positions from existing role specification, not verified current employees of the real firm.',
                'source_sha256': {str((SOURCE / n).relative_to(ROOT)): sha(SOURCE / n) for n in ['simulation_input_projects.csv', 'simulation_input_enterprises.csv']},
                'code_sha256': {n: sha(ROOT / n) for n in files},
                'stop': 'Any provider unknown/failure, invalid final, source mismatch, extra decision window or unverified chain stops batch. No automatic resume/replay.',
                'cache': 'No reuse of model responses across arms or replicates.',
                'formal_macro_execution_in_preparation': False}
    assert len(jobs) == 72 and sum(j['expected_max_provider_calls'] for j in jobs) == 324
    save(CP03 / 'sample_manifest.json', rows)
    path = CP03 / 'protocol.json'
    if path.exists() and read(path) != protocol:
        assert not (CP03 / 'authorization.json').exists() and not (CP03 / 'run').exists()
        if (CP03 / 'preflight.json').exists():
            assert revise_zero_call_draft and not (CP03.parent / 'package_manifest.json').exists(), 'Published/checked draft requires explicit zero-call revision before publication'
            checked = CP03 / 'preflight.json'
            revisions = CP03 / 'preparation_revisions'
            revisions.mkdir(exist_ok=True)
            dest = revisions / ('preflight-' + sha(checked)[:16] + '.json')
            assert not dest.exists() and checked.resolve().is_relative_to(CP03.resolve()) and dest.resolve().is_relative_to(CP03.resolve())
            checked.rename(dest)
        old = path.read_bytes()
        revisions = CP03 / 'preparation_revisions'
        revisions.mkdir(exist_ok=True)
        previous = revisions / ('protocol-' + hashlib.sha256(old).hexdigest()[:16] + '.json')
        if not previous.exists():
            previous.write_bytes(old)
        path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    else:
        save(path, protocol)
    feedback = [{'case_id': row['case_id'], 'opportunity_slot': t, 'region_condition': region,
                 'feedback_condition': condition, 'source_event_id': None, 'state': 'awaiting_real_chain_snapshot_not_executed'}
                for row in rows for t in [1, 2] for region in ['permitted', 'region_restricted']
                for condition in ['none', 'actual_own_settlement', 'same_count_changed_amount']]
    save(CP03 / 'CP04_feedback_plan.json', feedback)
    print('CP03:6 groups/3 initial profiles/72 configurations/324 strict first attempts; CP04:72 future replay slots.')


def preflight():
    from run_capstone_cp03_20261112 import verify_frozen, run
    from integration.capstone_mechanism_native import build_bundle
    from integration.contractor_tender_development import verify_bundle
    p = verify_frozen()
    jobs = p['jobs']
    # Cover every selected project and every mechanism with compiled sources;
    # repeat/arm-specific remaining bundles are generated before their future run.
    first_case = jobs[0]['case_id']
    references = [j for j in jobs if j['case_id'] == first_case and j['repeat'] == 1]
    references += [next(j for j in jobs if j['case_id'] == cid and j['repeat'] == 1 and j['arm'] == 'S')
                   for cid in dict.fromkeys(j['case_id'] for j in jobs) if cid != first_case]
    results, initial = [], {}
    with no_provider() as counts:
        for j in references:
            directory = CP03 / 'reference_inputs_v2' / j['chain_id'] / 'input'
            config = read(ROOT / j['config_path'])
            if not directory.exists():
                build_bundle(directory, config)
            checked = verify_bundle(directory)
            assert read(directory / 'case-config.json') == config
            request = read(directory / 'macro-request.json')
            project, = request['initial_projects']
            assert project['project_id'] == j['case_id'] and project['initial_budget'] == config['scenario_budget']
            assert project['technical_complexity'] == config['technical_complexity']
            assert request['random_seed'] == j['seed']
            if j['case_id'] == first_case:
                initial[j['arm']] = task_initial = {'initial_projects': request['initial_projects'], 'agents': request['agents']}
            app = read(directory / 'assembly-host.json')['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']
            if j['arm'] in ['R', 'S4']:
                assert app['model_host_factory'] == 'integration.capstone_mechanism_controls:build_model_host'
                assert app['model_host_settings']['research_control_arm'] == j['arm']
            assert app['model_host_settings']['strategy'] == ('organization_discussion' if j['arm'] == 'D3' else 'single_agent')
            results.append({'chain_id': j['chain_id'], 'compiled_input': str(directory.relative_to(ROOT)),
                            'input_manifest_sha256': sha(directory / 'input-manifest.json'),
                            'files_checked': checked['file_count'], 'executed': False})
            print('Compiled source-only reference:', j['chain_id'], flush=True)
        assert all(v == initial['S'] for v in initial.values()), 'Four-arm initial native facts differ'
        for cap in [None, 0, 216, 372, 537, 693]:
            try:
                run(cap)
            except ValueError:
                pass
            else:
                raise AssertionError('Missing/incorrect CP03 authorization accepted')
    verify_frozen()
    save(CP03 / 'preflight.json', {'passed': True, 'project_groups': 6, 'chains_configured': 72,
         'compiled_reference_bundles': results, 'all_four_arms_same_initial_native_facts': True,
         'all_projects_compile': True, 'distinct_initial_profiles': 3, 'planned_first_calls': 324,
         'safe_macro_retries_supported': False, 'max_final_retries': 0,
         'remaining_chain_bundles': 'Generated from pinned configurations before formal execution; not yet claimed compiled or executed.',
         'provider_requests': 0, 'formal_macro_submissions': 0, 'paid_client_constructions': counts['paid_client_constructions'],
         'network_attempts': counts['network_attempts'], 'model_quality_measured': False})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'preflight'])
    parser.add_argument('--revise-zero-call-draft', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.revise_zero_call_draft)
    else:
        preflight()
