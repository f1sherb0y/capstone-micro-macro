"""Freeze two input-only retrieval policies on development/validation DBB sets."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from integration.catalog import SharedCatalog
from integration.benchmark_lifecycle_metrics import contractor_truth


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, required=True)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    read = lambda path: json.loads(Path(path).read_text(encoding='utf-8'))
    design = read('config/candidate_retrieval_comparison.json')
    catalog = SharedCatalog(args.directory / 'inputs.sqlite3')
    metadata = catalog.import_inputs()
    source = Path(metadata['source'])
    corpus = list(csv.DictReader((source / 'simulation_input_enterprises.csv').open(encoding='utf-8-sig')))
    manifest = {'design': design, 'source': metadata, 'algorithm_sha256': {
        name: hashlib.sha256(Path('integration', name).read_bytes()).hexdigest()
        for name in ('candidate_policy.py', 'candidate_policy_v3.py', 'catalog.py')}}
    (args.directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    authored = []
    for project in catalog.list_projects():
        if project['delivery_mode'] != 'DBB':
            continue
        for policy in design['policies']:
            dataset = catalog.scenario(project['case_id'], candidate_policy={
                'version': policy, 'contractor_count': design['candidate_count']})
            audit = dataset.payload['assumptions']['candidate_audit']
            authored.append({'case_id': project['case_id'], 'policy': policy,
                'split': 'development' if project['case_id'] in design['development_ids'] else 'validation',
                'ranks': {row['company_id']: row['selection_rank'] for row in audit},
                'candidate_ids': [c['company_id'] for c in dataset.payload['companies'] if c['company_role'] == 'contractor']})
    (args.directory / 'authored_rankings.json').write_text(json.dumps(authored, ensure_ascii=False, indent=2), encoding='utf-8')
    # Only after both policies and every ranking have been saved do we open truth.
    labels = list(csv.DictReader((source / 'hidden_benchmark_project_enterprises.csv').open(encoding='utf-8-sig')))
    for row in authored:
        truth = set(contractor_truth([r for r in labels if r['case_id'] == row['case_id']], role=design['benchmark_role']))
        row['historical_ids'] = sorted(truth)
        row['covered'] = bool(truth & set(row['candidate_ids'])) if truth else None
        row['historical_ranks'] = {key: row['ranks'].get(key) for key in sorted(truth)}
        row['coverage_at_k'] = {str(k): any(0 < row['ranks'].get(key, 10**9) <= k for key in truth)
                                if truth else None for k in design['coverage_curve_k']}
    summary = []
    for split in ('development', 'validation'):
        for policy in design['policies']:
            rows = [r for r in authored if r['split'] == split and r['policy'] == policy and r['historical_ids']]
            summary.append({'split': split, 'policy': policy, 'denominator': len(rows),
                'covered_at_12': sum(r['covered'] for r in rows),
                'coverage_curve': {str(k): sum(r['coverage_at_k'][str(k)] for r in rows) for k in design['coverage_curve_k']}})
    result = {'status': 'retrieval_only_not_award_results', 'model_calls': 0, 'summary': summary, 'cases': authored,
        'limits': 'Current public profiles lack verified pre-award dates; validation is within this dataset, not out-of-time validation or causal proof.'}
    (args.directory / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'summary': summary, 'model_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
