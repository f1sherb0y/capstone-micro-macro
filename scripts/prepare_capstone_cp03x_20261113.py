"""Inspect and freeze the fixed 18 CP03X candidates before any model output."""
import argparse
from copy import deepcopy
import random

from capstone_cp_common_20261112 import ROOT, CP03, no_provider, read, save, sha
from prepare_capstone_cp03_20261112 import ARMS, CALLS, SEEDS
from integration.capstone_extended_catalog import domain_spec, scenario
from integration.capstone_finish_native import DIRECTORIES

BASE = ROOT / 'Capstone报告/验证体系'
OUT = DIRECTORIES['CP03X']
SCOPE = BASE / '指标补充/2026-11-12_完整方案_v4/scope.json'
ANNOTATIONS = BASE / '实验/2026-11-13_总实验收尾/macro_preparation/source_scope_and_families.json'


def candidate_inputs():
    from integration.catalog import SharedCatalog, DEFAULT_SOURCE
    candidates = read(SCOPE)['macro']['CP03X_candidates']
    annotations = {r['case_id']: r for r in read(ANNOTATIONS)}
    with no_provider():
        catalog = SharedCatalog(OUT / 'input_inspection_catalog.sqlite3')
        catalog.import_inputs(DEFAULT_SOURCE)
        projects = {r['case_id']: r for r in catalog.list_projects()}
        records, configs = [], []
        for index, candidate in enumerate(sorted(candidates, key=lambda r: (r['location'] != '澳门', r['case_id']))):
            cid = candidate['case_id']
            project = projects[cid]
            spec = domain_spec(project, annotations[cid])
            profile = [
                {'name': 'tighter_budget_lower_complexity', 'budget': 130000000, 'complexity': .35},
                {'name': 'reference_budget_reference_complexity', 'budget': 150000000, 'complexity': .6},
                {'name': 'larger_budget_higher_complexity', 'budget': 180000000, 'complexity': .85}][index % 3]
            template = read(ROOT / 'config/case0005_model_lifecycle.json')
            for repeat, seed in enumerate(SEEDS, 1):
                for arm in ARMS[repeat - 1:] + ARMS[:repeat - 1]:
                    jid = f'{cid}-r{repeat}-{arm}'
                    config = deepcopy(template)
                    config.update(case_id=cid, run_id='CP03X-' + jid, random_seed=seed,
                        scenario_budget=profile['budget'], technical_complexity=profile['complexity'], research_arm=arm,
                        api_total_attempt_cap=max(1, CALLS[arm]), domain_region=spec,
                        cp03_control={'arm': arm, 'chain_id': jid, 'batch_directory': str(OUT.resolve())})
                    config['model_options'].update(strategy='organization_discussion' if arm == 'D3' else 'single_agent',
                                                  max_calls=max(1, CALLS[arm]))
                    configs.append(config)
            # Check all three seed-specific candidate/region/DBB package
            # assemblies without constructing any simulation or client.
            inspections = []
            for repeat, seed in enumerate(SEEDS, 1):
                config = next(c for c in configs if c['case_id'] == cid and c['random_seed'] == seed and c['research_arm'] == 'S')
                dataset = scenario(catalog, config)
                inspections.append({'repeat': repeat, 'seed': seed, 'input_version': dataset.version,
                    'firm_selection': dataset.payload['assumptions']['candidate_selection'],
                    'firm_ids': [c['company_id'] for c in dataset.payload['companies']]})
            records.append({**annotations[cid], 'domain_region': spec, 'scenario_profile': profile,
                'state': 'input_catalog_and_role_assembly_passed_native_declarations_still_required',
                'inspections': inspections,
                'comparison_boundary': 'Controlled complete chain within the named source scope; package/unclear cases are separated from the whole-project stratum. No historical complete-parent-project claim.'})
        assert len(records) == 18 and len(configs) == 216
    return records, configs


def prototype(case_id):
    from integration.capstone_extended_lifecycle import build_bundle
    from integration.contractor_tender_development import verify_bundle
    records, configs = candidate_inputs()
    config = next(c for c in configs if c['case_id'] == case_id and c['research_arm'] == 'S' and c['random_seed'] == 42)
    compiler = ROOT / 'integration/capstone_extended_lifecycle.py'
    path = OUT / 'preparation_drafts' / (case_id + '-' + sha(compiler)[:12]) / 'input'
    with no_provider() as counts:
        if not path.exists():
            build_bundle(path, config)
        verified = verify_bundle(path)
        assert read(path / 'case-config.json') == config
        request = read(path / 'macro-request.json')
        project, = request['initial_projects']
        assert project['region'] == config['domain_region']['region']
        assert project['project_type'] == config['domain_region']['native_project_type']
        host = read(path / 'assembly-host.json')
        source_settings = host['settings']['tender']['settings']['source_settings']
        code = config['domain_region']['work_type_code']
        evidence_checks = []
        for key in ['snapshots', 'quantity_snapshots']:
            pin = source_settings[key]
            doc = read(pin['snapshot_path'])
            assert sha(pin['snapshot_path']) == pin['snapshot_sha256']
            text = __import__('json').dumps(doc, ensure_ascii=False)
            assert config['domain_region']['construction_scope'] in text
            assert 'CP03X_CONTROLLED_DOMAIN' in text and 'synthetic-work' not in text
            objects = [o for snapshot in doc['snapshots'] for o in snapshot['projection']['objects']]
            projects = [o for o in objects if o['ref']['kind'] == 'Project']
            assert projects and all(o['ref']['id'] == case_id for o in projects)
            if key == 'snapshots':
                terms = [o['value'] for o in objects if o['ref']['kind'] == 'GbaTenderPackageTerms']
                from pydantic import TypeAdapter
                from src.actions.contracts.common import ValueState, TextId
                declared_types = [TypeAdapter(ValueState[list[TextId]]).validate_python(term['work_types']) for term in terms]
                assert declared_types and all(v.state == 'known' and code in v.value for v in declared_types)
                assert code in text
            else:
                # The actual quantity schema carries schedules/coverage/ref
                # relations, not a work_types field. Bind its real Project
                # identity and domain evidence; do not invent a code field.
                schedules = [o['value'] for o in objects if o['ref']['kind'] == 'QuantitySchedule']
                assert schedules and all(schedule['lines'] for schedule in schedules)
            evidence_checks.append({'source_kind': key, 'source_sha256': pin['snapshot_sha256'],
                'domain_business_scope_present': True, 'project_identity_checked': True,
                'typed_work_code_required_and_checked': key == 'snapshots',
                'quantity_schedules_checked': key == 'quantity_snapshots',
                'original_synthetic_work_code_absent': True})
        result = {'case_id': case_id, 'state': 'native_sources_compiled_not_executed',
            'region': project['region'], 'native_project_type': project['project_type'],
            'domain': config['domain_region']['domain'], 'scope_class': config['domain_region']['scope_class'],
            'input_manifest_sha256': sha(path / 'input-manifest.json'), 'files_checked': verified['file_count'],
            'code_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in [compiler,
                ROOT / 'integration/capstone_extended_catalog.py', ROOT / 'scripts/prepare_capstone_cp03x_20261113.py']},
            'tender_source_checks': evidence_checks, 'actual_model_calls': 0, 'macro_simulations': 0, **counts}
        save(path.parent / 'inspection.json', result)
    print(result)


def prepare():
    if (OUT / 'protocol.json').exists():
        raise ValueError('CP03X already frozen; do not reselect')
    records, configs = candidate_inputs()
    # Representative building, specialist work-package and previously
    # unsupported Dongguan geography must compile before protocol publication.
    for cid in ['CASE-0004', 'CASE-0051', 'CASE-0261']:
        compiler = ROOT / 'integration/capstone_extended_lifecycle.py'
        check = OUT / 'preparation_drafts' / (cid + '-' + sha(compiler)[:12]) / 'inspection.json'
        inspected = read(check)
        assert inspected['state'] == 'native_sources_compiled_not_executed'
        assert all(sha(ROOT / path) == digest for path, digest in inspected['code_sha256'].items())
    jobs = []
    for config in configs:
        jid = config['cp03_control']['chain_id']
        path = OUT / 'configs' / (jid + '.json')
        save(path, config)
        row = next(r for r in records if r['case_id'] == config['case_id'])
        jobs.append({'chain_id': jid, 'case_id': config['case_id'], 'project_group': row['project_group'],
            'repeat': SEEDS.index(config['random_seed']) + 1, 'seed': config['random_seed'], 'arm': config['research_arm'],
            'config_path': str(path.relative_to(ROOT)).replace('\\', '/'), 'config_sha256': sha(path),
            'expected_max_provider_calls': CALLS[config['research_arm']],
            'scope_stratum': row['scope_is_full_project_or_package'], 'macro_family_id': row['macro_family_id']})
    # Keep each layer's first block intact; remaining blocks have a fixed
    # shuffle within Macau / cross-region layers, never interchanging them.
    ordered = []
    for is_macau in [True, False]:
        layer = [j for j in jobs if (next(r for r in records if r['case_id'] == j['case_id'])['location'] == '澳门') == is_macau]
        first, rest = layer[:4], layer[4:]
        random.Random(2026111304 + int(is_macau)).shuffle(rest)
        ordered += first + rest
    save(OUT / 'sample_manifest.json', records)
    parent = read(CP03 / 'protocol.json')
    code = dict(parent['code_sha256'])
    for path in ['integration/capstone_finish_native.py', 'integration/capstone_extended_catalog.py',
                 'integration/capstone_extended_lifecycle.py', 'scripts/prepare_capstone_cp03x_20261113.py',
                 'scripts/run_capstone_macro_finish_20261113.py', 'integration/catalog.py', 'integration/shared_data.py', 'src/llm_client.py']:
        code[path] = sha(ROOT / path)
    protocol = {**deepcopy(parent), 'schema': 'CP03X-domain-region-four-arm.v1', 'batch': 'CP03X',
        'run_id': 'capstone-CP03X-20261113', 'budget_id': 'CP03X-independent-firsts-cap972',
        'project_groups': len(records), 'chains': len(ordered), 'jobs': ordered,
        'first_calls': len(records) * 54, 'max_calls': len(records) * 54, 'max_final_retries': 0,
        'preparation_date': '2026-11-13', 'code_sha256': code,
        'manifest_sha256': sha(OUT / 'sample_manifest.json'),
        'source_sha256': {**parent['source_sha256'], **{str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in [SCOPE, ANNOTATIONS]}},
        'primary_macro_numeric': 'T2 contract_sum/initial_budget among common signed pairs, joint planned-block states; scope/region strata separate',
        'provider_calls_authorized': 0,
        'technical_scope': 'Source-specific domain scope, typed methods/qualification/work declarations, region and candidate roles. Native physical dynamics and cost methods remain generic normalized controls; no claim of calibrated domain generalization.',
        'full_chain_scope': 'Complete simulated chain within each named scope, exactly two A02 subjects. Packages/unclear scopes never pooled as full real projects. A package requiring different stages or extra decisions must remain ineligible and cannot consume this budget.',
        'stop': 'Any new provider failure/unknown, source mismatch, extra decision window or unverified native chain stops all paid work; no replay.'}
    save(OUT / 'protocol.json', protocol)
    save(OUT / 'preparation.json', {'source_groups': len(records), 'configured_chains': len(ordered),
        'first_requests': protocol['first_calls'], 'new_model_calls': 0, 'native_execution': False,
        'scope_strata': dict(__import__('collections').Counter(r['scope_is_full_project_or_package'] for r in records)),
        'final_native_readiness': 'All216 bundle compilation and source/permission/stage checks still required; publication does not authorize calls or prove actual runtime consumption.'})
    print('CP03X frozen:18 source groups/216 planned chains/972 independent strict attempts; no execution')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['inspect', 'prototype', 'prepare'])
    p.add_argument('--case')
    a = p.parse_args()
    if a.command == 'prototype':
        prototype(a.case)
    elif a.command == 'prepare':
        prepare()
    else:
        records, configs = candidate_inputs()
        print('18 candidates, all source-role/domain/region assemblies inspected, 216 configurations derivable; zero calls')
