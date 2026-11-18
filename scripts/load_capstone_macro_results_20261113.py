"""Read verified formal CP03/E/X outputs; retain every planned chain slot.

No provider, simulation, retry, generation change, or automatic business judge.
Historical shape-check runs never enter these fixed formal directories.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from capstone_cp_common_20261112 import ROOT, CP03, read, save, sha, no_provider
from capstone_macro_observations_20261113 import extract_project_observations, RISKS
from capstone_pricing_observations_20261113 import extract_pricing_worker
from integration.capstone_finish_native import DIRECTORIES, MASTER
from integration.capstone_mechanism_results import verify as verify_chain
from integration.verify_goal4_integration import journal
from src.coordination.tasks import TaskIdentity, task_digest

BATCHES = {'CP03': CP03, **DIRECTORIES}
IDENTITY_FIELDS = ('run_id', 'organization_id', 'action_id', 'input_sha256', 'context_sha256')


def locator(path):
    path = Path(path)
    try: return path.relative_to(ROOT).as_posix()
    except ValueError: return str(path.resolve())


def extract_verified_output(job, config, initial, output, verification, metadata, workers, *, database_locator):
    """Pure content binding after native verification; no inferred outcomes."""
    if not verification['technical_integrity_passed'] or verification['arm'] != job['arm']:
        raise ValueError('Verified mechanism arm does not match its formal slot')
    if config['research_arm'] != job['arm'] or config['case_id'] != job['case_id']:
        raise ValueError('Source configuration differs from the planned chain')
    simulation = output['simulation']
    if simulation['status'] != 'completed' or simulation['current_tick'] != initial['ticks']:
        raise ValueError('Fixed planned observation horizon is incomplete')
    projects = [p for p in simulation['project_results'] if p['project_id'] == job['case_id']]
    if len(projects) != 1 or verification['project_id'] != job['case_id']:
        raise ValueError('Formal source project is missing or ambiguous')
    project = projects[0]
    observations = extract_project_observations(project, end_tick=initial['ticks'], complete_horizon=True)
    pricing = []
    for key, worker in workers.items():
        identity = worker['identity']
        if identity['action_id'] != 'CONTRACTOR-A02': continue
        matches = [(k, r) for k, r in metadata.items() if k.startswith('action_option_snapshot:')
            and all(r['selection'].get(f) == identity[f] for f in IDENTITY_FIELDS)]
        if len(matches) != 1:
            raise ValueError('Actual A02 worker lacks one exact saved option snapshot')
        snapshot_key, snapshot = matches[0]
        row = extract_pricing_worker(worker, snapshot,
            snapshot_locator=database_locator + '::metadata/' + snapshot_key)
        links = [r for r in verification['quote_execution_links'] if r['task_key'] == key]
        if row['choice'] == 'submit_bid' and worker['result']['kind'] == 'completed':
            if len(links) != 1 or Decimal(links[0]['price']) != Decimal(row['bid_price']):
                raise ValueError('Selected commercial choice is not linked to the actual native bid')
        elif links:
            raise ValueError('A non-submission worker unexpectedly has an actual bid event')
        pricing.append({'task_key': key, **row, 'actual_bid_event_links': links})
    return {'observations': observations, 'pricing': pricing,
        'pricing_worker_count': len(pricing), 'original_model_calls': verification['actual_model_calls'],
        'fixed_fact_block_sha256': task_digest({k: initial[k] for k in ['initial_projects', 'agents', 'random_seed', 'ticks']}),
        'feedback_source_records': verification['feedback_source_records'],
        'technical_verification': verification}


def extract_chain(directory, job):
    directory = Path(directory)
    config = read(directory / 'input/case-config.json')
    initial = read(directory / 'input/macro-request.json')
    output = read(directory / 'runtime/result.json')
    verification = verify_chain(directory, arm=job['arm'])
    waits = {}
    for action in output['module_host_extension']['host']['lifecycle']['actions']:
        if action['state'] != 'formed': waits[TaskIdentity(**action['identity']).key] = action
    _, metadata, workers, digest = journal(directory, allowed_pending=waits)
    result = extract_verified_output(job, config, initial, output, verification, metadata, workers,
        database_locator=locator(directory / 'runtime/tasks.sqlite'))
    if sha(directory / 'runtime/tasks.sqlite') != digest:
        raise ValueError('Original journal changed during extraction')
    return result


def collect_batch(batch, directory, family_rows):
    """Saved incomplete/failed chains are visible but supply no primary metric."""
    directory = Path(directory)
    protocol = read(directory / 'protocol.json')
    jobs = protocol['jobs']
    if len({j['chain_id'] for j in jobs}) != len(jobs):
        raise ValueError('Duplicate planned chain slots')
    rows, sources = [], {}
    def pin(path):
        path = Path(path)
        if path.is_file(): sources[locator(path)] = sha(path)
    pin(directory / 'protocol.json'); pin(directory / 'sample_manifest.json')
    pin(directory / 'run/outcomes.json'); pin(directory / 'run/HALT.json')
    families = {r['case_id']: r for r in family_rows}
    for job in jobs:
        family = families[job['case_id']]
        config_path = ROOT / job['config_path']
        if sha(config_path) != job['config_sha256']:
            raise ValueError('Frozen formal configuration changed')
        pin(config_path)
        chain = directory / 'chains' / job['chain_id']
        # Only original evidence inputs, durable journal and captured native outputs.
        for path in (chain / 'input').rglob('*'): pin(path)
        for name in ['exit.json', 'command.json', 'runtime/tasks.sqlite', 'runtime/result.json', 'runtime/native-run-state.json']:
            pin(chain / name)
        for path in (directory / 'run/provider_attempts' / job['chain_id']).glob('*.json'): pin(path)
        row = {'batch': batch, **job, 'macro_family_id': family['macro_family_id'],
            'scope_stratum': family['scope_is_full_project_or_package'],
            'source_project_name': family['project_name'], 'source_region': family['location'],
            'family_annotation_identity': family['annotation_evidence']['identity'],
            'formal_chain_directory': locator(chain), 'state': 'no_saved_execution_yet',
            'observations': None, 'pricing': None, 'original_model_calls': None}
        if (chain / 'exit.json').exists():
            exit_code = read(chain / 'exit.json')['exit_code']
            if exit_code != 0:
                row.update(state='saved_nonzero_exit_no_primary_metrics', exit_code=exit_code)
            else:
                try:
                    if read(chain / 'input/case-config.json') != read(config_path):
                        raise ValueError('Compiled source configuration differs from the frozen slot')
                    extracted = extract_chain(chain, job)
                    if extracted['original_model_calls'] > job['expected_max_provider_calls']:
                        raise ValueError('Actual model calls exceed the frozen per-chain limit')
                    row.update(state='verified_complete_horizon_observations', **extracted)
                except Exception as exc:
                    row.update(state='saved_output_failed_reverification_no_primary_metrics',
                        verification_error_type=type(exc).__name__, verification_error=str(exc))
        elif (chain / 'runtime').exists() or (chain / 'command.json').exists():
            row['state'] = 'saved_execution_without_terminal_exit_no_primary_metrics'
        rows.append(row)
    # Four-arm comparisons may only share exactly the frozen external facts.
    blocks = {}
    for row in rows:
        if row['state'] == 'verified_complete_horizon_observations':
            key = (row['case_id'], row['repeat'])
            if key in blocks and blocks[key] != row['fixed_fact_block_sha256']:
                raise ValueError('Four mechanisms in a block do not share the same facts')
            blocks[key] = row['fixed_fact_block_sha256']
    for path, digest in sources.items():
        if sha(ROOT / path) != digest:
            raise ValueError('Evidence changed during this read-only snapshot: ' + path)
    return rows, sources


def chain_table_row(row):
    result = {k: row[k] for k in ['batch', 'chain_id', 'case_id', 'project_group', 'repeat', 'seed', 'arm',
        'macro_family_id', 'scope_stratum', 'source_region', 'state', 'original_model_calls']}
    result.update(T2_contract_to_budget=None, T3_final_cost_vs_budget=None, T3_final_cost_vs_estimate=None,
        T3_final_cost_vs_contract=None, T4_final_progress_gap_pp=None, T4_reported_delay_days=None,
        T5_completion_overall_quality=None, T5_horizon_overall_quality=None,
        T7_contract_awarded=None, T7_project_completed=None, T7_final_account_settled=None,
        T8_inspection_failure_fraction=None, T8_inspection_count=None, T8_supply_delay_count=None, T8_safety_issue_count=None)
    for risk in RISKS:
        result['T6_' + risk + '_construction_peak'] = None
        result['T6_' + risk + '_horizon'] = None
    o = row['observations']
    if o is None: return result
    result['T2_contract_to_budget'] = o['T2']['contract_to_budget']
    costs = o['T3']['fixed_horizon']
    if costs:
        for source, suffix in [('initial_budget', 'budget'), ('reported_estimated_cost', 'estimate'), ('signed_contract', 'contract')]:
            result['T3_final_cost_vs_' + suffix] = costs['deviations'][source]
    result.update(T4_final_progress_gap_pp=o['T4']['fixed_horizon_progress_gap_pp'],
        T4_reported_delay_days=o['T4']['reported_delay_days'],
        T5_completion_overall_quality=(o['T5']['completion'] or {}).get('overall_quality'),
        T5_horizon_overall_quality=(o['T5']['fixed_horizon'] or {}).get('overall_quality'),
        T8_inspection_failure_fraction=o['T8']['inspection_failure_fraction'],
        T8_inspection_count=o['T8']['inspection_count'],
        T8_supply_delay_count=(o['T8']['comparative_counts'] or {}).get('supply_delay'),
        T8_safety_issue_count=(o['T8']['comparative_counts'] or {}).get('safety_issue'))
    for kind, observed in o['T7']['occurred_by_planned_endpoint'].items(): result['T7_' + kind] = observed
    for risk in RISKS:
        result['T6_' + risk + '_construction_peak'] = o['T6'][risk]['construction_peak']
        result['T6_' + risk + '_horizon'] = o['T6'][risk]['fixed_horizon_state']
    return result


def write_csv(path, rows):
    if not rows: return
    with Path(path).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main(tag):
    if not tag or not all(c.isalnum() or c in '_-' for c in tag): raise ValueError('Use a new simple immutable snapshot tag')
    target = MASTER / 'macro_results' / tag
    if target.exists(): raise ValueError('Existing macro result snapshot; do not overwrite')
    started = datetime.now(timezone.utc).isoformat()
    family_path = MASTER / 'macro_preparation/source_scope_and_families.json'
    families = read(family_path)
    rows, sources = [], {locator(family_path): sha(family_path)}
    with no_provider() as counts:
        for batch, directory in BATCHES.items():
            own, pinned = collect_batch(batch, directory, families)
            rows.extend(own); sources.update(pinned)
    if len(rows) != 324 or len({(r['batch'], r['chain_id']) for r in rows}) != 324:
        raise ValueError('Formal 324 planned slots must all have a disposition')
    for path, digest in sources.items():
        if sha(ROOT / path) != digest: raise ValueError('Source changed before snapshot seal: ' + path)
    table = [chain_table_row(row) for row in rows]
    pricing = []
    for row in rows:
        for p in row['pricing'] or []:
            pricing.append({**{k: row[k] for k in ['batch', 'chain_id', 'case_id', 'project_group', 'repeat', 'arm']},
                **{k: p.get(k) for k in ['organization_id', 'task_key', 'state', 'choice', 'currency',
                    'declared_cost_base', 'bid_price', 'markup_fraction', 'semantic_strategy_state']},
                'canonical_commercial_choice': json.dumps(p['canonical_commercial_choice'], ensure_ascii=False, sort_keys=True),
                'snapshot_locator': p['snapshot_locator']})
    save(target / 'chain_observations.json', rows)
    write_csv(target / 'planned_chain_metrics.csv', table)
    write_csv(target / 'pricing_workers.csv', pricing)
    n = sum(r['state'] == 'verified_complete_horizon_observations' for r in rows)
    save(target / 'manifest.json', {'started_at_UTC': started, 'finished_at_UTC': datetime.now(timezone.utc).isoformat(),
        'extractor_sha256': sha(__file__), 'helper_sha256': {name: sha(ROOT / 'scripts' / name) for name in [
            'capstone_macro_observations_20261113.py', 'capstone_pricing_observations_20261113.py']},
        'native_verifier_sha256': sha(ROOT / 'integration/capstone_mechanism_results.py'),
        'planned_chains': 324, 'verified_chains': n, 'state_counts': dict(Counter(r['state'] for r in rows)),
        'formal_source_groups': len({r['case_id'] for r in rows}), 'conservative_name_families': len({r['macro_family_id'] for r in rows}),
        'pricing_worker_rows': len(pricing), 'source_sha256': sources,
        'artifact_sha256': {p.name: sha(p) for p in target.iterdir() if p.is_file()},
        'new_model_calls': 0, 'new_formal_simulations': 0, **counts,
        'result_state': 'no_formal_verified_result_available' if not n else 'chain_observations_available_paired_analysis_separate',
        'boundary': 'Only original formal CP03/E/X directories. Missing/failed chains retain planned denominators and no fabricated values. T1 is declared markup, T2 conditional on contract, T5 completion conditional on observed work/completion. No weighted total or high-price business ranking.'})
    print({'planned': 324, 'verified': n, 'pricing_rows': len(pricing), 'new_model_calls': 0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    main(parser.parse_args().tag)
