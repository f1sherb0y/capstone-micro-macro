"""Expose actual native initial values vs catalog views; no parameter edits."""
from collections import Counter

from capstone_cp_common_20261112 import ROOT, CP03, read, save, sha, no_provider
from integration.capstone_finish_native import DIRECTORIES

MASTER = ROOT / 'Capstone报告/验证体系/实验/2026-11-13_总实验收尾'
FIELDS = ['total_resource_capacity', 'qualification_level', 'financial_capacity', 'technical_capability',
          'management_capability', 'design_capability', 'cost_estimation_capability', 'construction_capability',
          'safety_management_capability', 'quality_management_capability', 'supply_reliability', 'material_quality']


def main(snapshot_name='actual_initials_compiled_snapshot_001.json'):
    assert snapshot_name.endswith('.json') and all(c.isalnum() or c in '_-.' for c in snapshot_name)
    rows, protocols = [], {}
    for batch, directory in [('CP03', CP03), ('CP03E', DIRECTORIES['CP03E']), ('CP03X', DIRECTORIES['CP03X'])]:
        protocol = read(directory / 'protocol.json')
        protocols[batch] = {'protocol_sha256': sha(directory / 'protocol.json'),
            'planned_chain_inputs': len(protocol['jobs']),
            'compilation_evidence_sha256': sha(directory / ('all_chain_compilation_20261113.json' if batch == 'CP03' else 'preflight.json'))}
        for job in protocol['jobs']:
            source = directory / 'chains' / job['chain_id'] / 'input'
            request_path = source / 'macro-request.json'
            if not request_path.exists():
                continue
            catalog_path = source / 'case-library-input.json'
            request, catalog = read(request_path), read(catalog_path)
            actual = []
            for agent in request['agents']:
                key = agent['agent_id']
                view = catalog['assumptions']['enterprise_parameters'].get(key)
                if view is None:
                    continue
                differences = {field: {'native_initial': agent[field], 'catalog_view': view[field]} for field in FIELDS
                               if field in agent and field in view and agent[field] != view[field]}
                actual.append({'organization_id': key, 'role': agent['role'],
                    'native_initial_values': {field: agent[field] for field in FIELDS if field in agent},
                    'catalog_differences': differences})
            rows.append({'batch': batch, 'chain_id': job['chain_id'], 'case_id': job['case_id'],
                'repeat': job['repeat'], 'arm': job['arm'], 'actual_native_initial_projects': request['initial_projects'],
                'actual_native_enterprise_profiles': actual, 'request_sha256': sha(request_path),
                'catalog_view_sha256': sha(catalog_path),
                'interpretation': 'Native request and private methods define the actual simulation controls; catalog view parameters are not assumed consumed.'})
    output = MASTER / 'macro_preparation' / snapshot_name
    save(output, {'compiled_chain_inputs_observed': dict(Counter(r['batch'] for r in rows)), 'rows': rows,
        'protocols': protocols, 'auditor_sha256': sha(__file__),
        'boundary': 'Source compilation only; no simulation execution, outcome or demonstrated runtime text consumption.',
        'actual_provider_calls': 0})
    print({'compiled_inputs_audited': dict(Counter(r['batch'] for r in rows)), 'model_calls': 0})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot-name', default='actual_initials_compiled_snapshot_001.json')
    args = parser.parse_args()
    with no_provider():
        main(args.snapshot_name)
