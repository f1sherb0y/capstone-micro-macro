"""Freeze the three remaining supported macro cases, without execution."""
from copy import deepcopy
import random

from capstone_cp_common_20261112 import ROOT, CP03, no_provider, read, save, sha
from prepare_capstone_cp03_20261112 import ARMS, CALLS, SEEDS

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_CP03E另三组宏观'
SCOPE = BASE / '指标补充/2026-11-12_完整方案_v4/scope.json'


def prepare():
    if (OUT / 'protocol.json').exists():
        raise ValueError('Existing CP03E protocol; do not reselect')
    with no_provider() as counts:
        scope = read(SCOPE)['macro']
        selected = scope['extension_case_ids']
        assert selected == ['CASE-0005', 'CASE-0007', 'CASE-0014']
        source_rows = {r['case_id']: r for r in scope['all_DBB_candidates']}
        template = read(ROOT / 'config/case0005_model_lifecycle.json')
        profiles = [
            {'name': 'tighter_budget_lower_complexity', 'budget': 130000000, 'complexity': .35},
            {'name': 'reference_budget_reference_complexity', 'budget': 150000000, 'complexity': .6},
            {'name': 'larger_budget_higher_complexity', 'budget': 180000000, 'complexity': .85}]
        jobs, manifest = [], []
        for index, cid in enumerate(selected):
            profile = profiles[index]
            row = source_rows[cid]
            manifest.append({**row, 'scenario_profile': profile,
                'scope': 'Original supported Macau DBB infrastructure entry; named work scope, not a historical procurement reconstruction.',
                'initial_parameters_are': 'Explicit controlled assumptions, not observed budget, duration or enterprise ability.'})
            for repeat, seed in enumerate(SEEDS, 1):
                for arm in ARMS[repeat - 1:] + ARMS[:repeat - 1]:
                    jid = f'{cid}-r{repeat}-{arm}'
                    config = deepcopy(template)
                    config.update(case_id=cid, run_id='CP03E-' + jid, random_seed=seed,
                        scenario_budget=profile['budget'], technical_complexity=profile['complexity'],
                        research_arm=arm, api_total_attempt_cap=max(1, CALLS[arm]),
                        cp03_control={'arm': arm, 'chain_id': jid, 'batch_directory': str(OUT.resolve())})
                    config['model_options'].update(strategy='organization_discussion' if arm == 'D3' else 'single_agent',
                                                   max_calls=max(1, CALLS[arm]))
                    path = OUT / 'configs' / (jid + '.json')
                    save(path, config)
                    jobs.append({'chain_id': jid, 'case_id': cid, 'project_group': row['project_group'],
                        'repeat': repeat, 'seed': seed, 'arm': arm,
                        'config_path': str(path.relative_to(ROOT)).replace('\\', '/'),
                        'config_sha256': sha(path), 'expected_max_provider_calls': CALLS[arm]})
        first, rest = jobs[:4], jobs[4:]
        random.Random(2026111303).shuffle(rest)
        jobs = first + rest
        assert len(jobs) == 36 and sum(j['expected_max_provider_calls'] for j in jobs) == 162
        save(OUT / 'sample_manifest.json', manifest)
        parent = read(CP03 / 'protocol.json')
        code = dict(parent['code_sha256'])
        for name in ['integration/capstone_finish_native.py', 'scripts/prepare_capstone_cp03e_20261113.py',
                     'scripts/run_capstone_macro_finish_20261113.py', 'integration/catalog.py',
                     'integration/shared_data.py', 'src/llm_client.py']:
            code[name] = sha(ROOT / name)
        protocol = {**deepcopy(parent), 'schema': 'CP03E-four-arm.v1', 'batch': 'CP03E',
            'run_id': 'capstone-CP03E-20261113', 'budget_id': 'CP03E-independent-firsts-cap162',
            'project_groups': 3, 'chains': 36, 'jobs': jobs, 'first_calls': 162, 'max_calls': 162,
            'preparation_date': '2026-11-13', 'code_sha256': code,
            'manifest_sha256': sha(OUT / 'sample_manifest.json'),
            'source_sha256': {**parent['source_sha256'], str(SCOPE.relative_to(ROOT)).replace('\\', '/'): sha(SCOPE)},
            'primary_macro_numeric': 'T2 contract_sum/initial_budget among common signed pairs, with joint planned-block states',
            'provider_calls_authorized': 0, 'max_final_retries': 0,
            'stop': 'Global stop, any provider failure/unknown, source drift, extra window or unverified native chain stops all new paid work. No replay.'}
        save(OUT / 'protocol.json', protocol)
        save(OUT / 'preparation.json', {'groups': 3, 'repeats': 3, 'chains': 36,
            'first_requests': 162, 'repairs': 0, 'actual_model_calls': 0, 'formal_macro_simulations': 0, **counts})
    print('CP03E frozen:3 groups/36 chains/162 independent calls; no execution')


if __name__ == '__main__':
    prepare()
