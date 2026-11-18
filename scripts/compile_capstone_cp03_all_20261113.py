"""Compile all pinned CP03 sources offline; do not run simulations or clients."""
from collections import defaultdict

from capstone_cp_common_20261112 import ROOT, CP03, no_provider, read, save, sha


def main():
    from run_capstone_cp03_20261112 import verify_frozen
    from integration.capstone_mechanism_native import build_bundle
    from integration.contractor_tender_development import verify_bundle
    p = verify_frozen()
    comparison, compiled = defaultdict(dict), []
    with no_provider() as counts:
        for i, job in enumerate(p['jobs'], 1):
            directory = CP03 / 'chains' / job['chain_id'] / 'input'
            config = read(ROOT / job['config_path'])
            if not directory.exists():
                build_bundle(directory, config)
            checked = verify_bundle(directory)
            assert read(directory / 'case-config.json') == config
            request = read(directory / 'macro-request.json')
            initial, = request['initial_projects']
            assert initial['project_id'] == job['case_id'] and request['random_seed'] == job['seed']
            assert initial['initial_budget'] == config['scenario_budget']
            assert initial['technical_complexity'] == config['technical_complexity']
            assert initial['region'] == 'Macau' and initial['project_type'] == 'infrastructure'
            comparison[job['case_id'], job['repeat']][job['arm']] = {
                'initial_projects': request['initial_projects'], 'agents': request['agents'],
                'ticks': request['ticks'], 'random_seed': request['random_seed']}
            compiled.append({'chain_id': job['chain_id'], 'input_manifest_sha256': sha(directory / 'input-manifest.json'),
                'files_checked': checked['file_count'], 'actual_provider_calls': 0, 'macro_execution': False})
            if i % 12 == 0:
                print(f'CP03 source bundles checked: {i}/72', flush=True)
        assert len(compiled) == 72 and len(comparison) == 18
        for key, arms in comparison.items():
            assert set(arms) == {'R', 'S', 'D3', 'S4'}
            assert all(facts == arms['S'] for facts in arms.values()), key
    verify_frozen()
    out = CP03 / 'all_chain_compilation_20261113.json'
    save(out, {'passed': True, 'compiled_chains': compiled, 'same_facts_comparison_blocks': len(comparison),
        'source_groups': 6, 'actual_model_calls': 0, 'formal_macro_simulations': 0,
        'protocol_sha256': sha(CP03 / 'protocol.json'), 'compiler_script_sha256': sha(__file__), **counts})
    print('CP03 all72 source bundles compiled and checked; 18 four-arm same-fact blocks; no models or simulations')


if __name__ == '__main__':
    main()
