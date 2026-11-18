"""Join explicit, rechecked labels to planned slots; withhold incomplete claims."""
import argparse
from collections import Counter
import csv
from pathlib import Path

from capstone_cp_common_20261112 import ROOT, read, save, sha
from review_capstone_all_20261113 import MASTER, PACKS, cards
from capstone_project_analysis_20261113 import project_pairs, summary, stratified_bootstrap, influence


def grade_value(record, metric):
    if metric == 'D1':
        label = record['D1']['label'] if 'D1' in record else record['D1_appropriateness']
        assert label in {'appropriate', 'inappropriate', 'not_judgable'}
        return {'appropriate': 1., 'inappropriate': 0., 'not_judgable': None}[label]
    if metric == 'D2':
        factors = record['factor_ratings']
        assert factors
        assert all(f['rating'] in {'correct', 'partial', 'missing', 'contradicted', 'not_judgable'} for f in factors)
        value = sum(f['rating'] == 'correct' for f in factors) / len(factors)
        assert abs(value - record['D2_correct_coverage']) < 1e-12
        return value
    if 'detailed' in record:
        value = record['detailed'].get(metric, {}).get('score')
    else:
        value = record['D3_feasibility' if metric == 'D3' else 'D4_tradeoff']
    assert value in {None, 'not_judgable', 0, 1, 2}
    return None if value in {None, 'not_judgable'} else float(value)


def joined_slots(index, cohort, metric):
    _, by_id = cards(cohort)
    detailed_groups = set(read(PACKS['CP08'] / 'detailed_score_groups.json')) if cohort == 'CP08' else None
    slots = []
    for planned in index['rows']:
        if planned['cohort'] != cohort:
            continue
        if metric in {'D3', 'D4'}:
            if cohort == 'CP00' or (cohort == 'CP01' and planned['repeat'] != 1):
                continue
            if cohort == 'CP08' and planned['project_group'] not in detailed_groups:
                continue
        card = by_id[planned['window_id']]
        row = {**planned, 'company_id': card['company_id'], 'value': None,
               'metric': metric, 'analysis_state': 'no_returned_business_answer'}
        if planned['readable_outward_json']:
            name = f"{planned['window_id']}-{planned['arm']}-r{planned['repeat']}-a1.json"
            path = MASTER / 'business_review' / cohort / name
            if path.exists():
                grade = read(path)
                assert grade['response_sha256'] == planned['response_sha256']
                rechecked = bool(grade.get('evidence_recheck'))
                recheck_path = MASTER / 'business_recheck' / cohort / name
                if recheck_path.exists():
                    recheck = read(recheck_path)
                    assert recheck['initial_record_sha256'] == sha(path)
                    assert recheck['response_sha256'] == planned['response_sha256']
                    rechecked = recheck['complete']
                if rechecked:
                    value = grade_value(grade, metric)
                    row.update(value=value, analysis_state='rechecked_observed' if value is not None else 'rechecked_not_judgable',
                        grade_path=str(path.relative_to(ROOT)).replace('\\', '/'), grade_sha256=sha(path))
                else:
                    row['analysis_state'] = 'content_recheck_pending'
            else:
                row['analysis_state'] = 'explicit_content_review_pending'
        slots.append(row)
    return slots


def analyze(cohort, tag, output_tag):
    index_path = MASTER / f'response_index_{tag}.json'
    index = read(index_path)
    out = MASTER / 'analysis' / output_tag / cohort
    contrasts = [('D3', 'S4'), ('D3', 'S'), ('S4', 'S')] if cohort == 'CP07' else [('v2_5', 'v2_4')]
    manifests, case_rows = [], []
    for metric in ['D1', 'D2', 'D3', 'D4']:
        slots = joined_slots(index, cohort, metric)
        if not slots:
            continue
        coverage = Counter(r['analysis_state'] for r in slots)
        pending = sum(coverage[state] for state in ['explicit_content_review_pending', 'content_recheck_pending'])
        save(out / (metric + '_slot_values.json'), slots)
        for left, right in contrasts:
            paired = project_pairs(slots, left=left, right=right, low=0, high=1 if metric in {'D1', 'D2'} else 2)
            observed_cases = []
            for case in paired:
                own = [s for s in slots if s['project_group'] == case['project_group'] and s['arm'] in {left, right}]
                if any(s['analysis_state'] in {'explicit_content_review_pending', 'content_recheck_pending'} for s in own):
                    continue
                if case['observed_slots'] == 0:
                    continue
                observed_cases.append(case)
                case_rows.append({'cohort': cohort, 'metric': metric, 'project_group': case['project_group'],
                    'role': case['role'], 'company_id': case['company_id'], 'left_arm': left, 'right_arm': right,
                    'left_mean': case['left_mean'], 'right_mean': case['right_mean'], 'difference': case['difference'],
                    'all_repeat_slots_observed': case['all_planned_repeat_slots_observed'],
                    'interpretation': 'Rechecked individual-case descriptive result; cohort inference withheld until all readable content is reviewed.'})
            report = {'cohort': cohort, 'metric': metric, 'contrast': [left, right],
                'coverage': dict(coverage), 'pending_readable_content_reviews_or_rechecks': pending,
                'fully_reviewed_case_descriptions': len(observed_cases),
                'source_index_path': str(index_path.relative_to(ROOT)).replace('\\', '/'), 'source_index_sha256': sha(index_path),
                'cohort_analysis_state': 'withheld_scoring_incomplete' if pending else 'reviewed_observed_cases_and_missing_bounds',
                'cohort_estimate': None, 'reason': 'Unreviewed content must not masquerade as absent model output or selectively scored evidence.' if pending else None}
            if not pending:
                report['cohort_estimate'] = {'paired': summary(paired), 'uncertainty': stratified_bootstrap(paired),
                    'leave_project_out': influence(paired, 'project_group'),
                    'leave_reused_firm_out': influence(paired, 'company_id'),
                    'complete_repeat_slots_sensitivity': summary([r for r in paired if r['all_planned_repeat_slots_observed']])}
            save(out / f'{metric}_{left}_minus_{right}.json', report)
            manifests.append(report)
    # A standalone CSV supports later figures without hand-transcribed scores.
    csv_path = out / 'rechecked_case_descriptions.csv'
    fields = ['cohort', 'metric', 'project_group', 'role', 'company_id', 'left_arm', 'right_arm', 'left_mean', 'right_mean',
              'difference', 'all_repeat_slots_observed', 'interpretation']
    import io
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(case_rows)
    text = buffer.getvalue()
    if csv_path.exists():
        assert csv_path.read_text(encoding='utf-8-sig') == text.replace('\r\n', '\n')
    else:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(text, encoding='utf-8-sig', newline='')
    save(out / 'analysis_manifest.json', {'source_index_sha256': sha(index_path),
        'analysis_code_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in [Path(__file__), ROOT / 'scripts/capstone_project_analysis_20261113.py']},
        'case_csv_sha256': sha(csv_path), 'cohort_estimates_withheld': any(r['cohort_estimate'] is None for r in manifests),
        'bootstrap_rule': 'v4: paired project groups, role-stratified 20000 draws, seed20261112, exploratory95 percentile interval',
        'new_model_calls': 0, 'new_semantic_labels_inferred': 0})
    print({'cohort': cohort, 'rechecked_case_metric_rows': len(case_rows),
           'cohort_estimate_state': 'withheld_scoring_incomplete' if any(r['cohort_estimate'] is None for r in manifests)
               else 'reviewed_observed_cases_and_missing_bounds'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cohort', choices=['CP00', 'CP01', 'CP08', 'CP07'], required=True)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output-tag', required=True)
    args = parser.parse_args()
    analyze(args.cohort, args.snapshot, args.output_tag)
