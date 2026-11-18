"""Audit retrieval before simulation; hidden truth is read only after authoring.

This command makes no model/API calls and cannot report native award results.
"""
import argparse
import csv
import json
from pathlib import Path

from integration.catalog import SharedCatalog
from integration.benchmark_lifecycle_metrics import contractor_truth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('config/benchmark_macro_batch_v2.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    template = json.loads(Path(config['template']).read_text(encoding='utf-8'))
    args.directory.mkdir(parents=True, exist_ok=False)
    catalog = SharedCatalog(args.directory / 'inputs.sqlite3')
    source = Path(config['source_directory'])
    imported = catalog.import_inputs(source)
    datasets = {}
    for case_id in config['first_phase_case_ids']:
        dataset = catalog.scenario(case_id, budget=template['scenario_budget'],
            duration=template['contract_duration'], seed=template['random_seed'],
            candidate_policy=template['candidate_policy'])
        datasets[case_id] = dataset
        (args.directory / (case_id + '-input.json')).write_text(
            json.dumps(dataset.payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Evaluation cannot affect retrieval: all inputs above have been frozen.
    with (source / 'hidden_benchmark_project_enterprises.csv').open(encoding='utf-8-sig', newline='') as stream:
        labels = list(csv.DictReader(stream))
    scores = []
    for case_id, dataset in datasets.items():
        truth = set(contractor_truth([r for r in labels if r['case_id'] == case_id], role=config.get('benchmark_role')))
        candidates = {c['company_id'] for c in dataset.payload['companies'] if c['company_role'] == 'contractor'}
        audit = dataset.payload['assumptions']['candidate_audit']
        scores.append({'case_id': case_id, 'candidate_count': len(candidates),
            'candidate_ids': sorted(candidates), 'historical_contractor_ids': sorted(truth),
            'retrieval_covered': bool(truth & candidates) if truth else None,
            'historical_relation_recall': len(truth & candidates) / len(truth) if truth else None,
            'score_values': sorted({r['score'] for r in audit if r['selected']})})
    eligible = [s for s in scores if s['historical_contractor_ids']]
    report = {'status': 'retrieval_preflight_only_not_simulation', 'model_calls': 0,
        'source': imported, 'candidate_policy': template['candidate_policy'],
        'covered': sum(s['retrieval_covered'] for s in eligible), 'denominator': len(eligible),
        'scores': scores, 'boundary': 'No actual bids, TopK, awards or integration success measured.'}
    (args.directory / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['status', 'model_calls', 'covered', 'denominator']}))


if __name__ == '__main__':
    main()
