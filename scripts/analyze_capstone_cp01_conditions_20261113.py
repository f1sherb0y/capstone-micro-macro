"""Fixed full/missing information contrasts from completed, rechecked first grades."""
from collections import defaultdict
from pathlib import Path
from statistics import mean
import json

from analyze_capstone_content_20261113 import MASTER, ROOT, read, save, sha
from capstone_project_analysis_20261113 import finite_score, stratified_bootstrap, influence

SOURCE = MASTER/'analysis/CP01_first_review_complete_001/CP01'
OUT = MASTER/'analysis/CP01_condition_diagnostics_001'
CONTRASTS = {
    'version_full': {('v2_5', 'full'): 1, ('v2_4', 'full'): -1},
    'version_missing': {('v2_5', 'missing_core'): 1, ('v2_4', 'missing_core'): -1},
    'information_v2_4': {('v2_4', 'missing_core'): 1, ('v2_4', 'full'): -1},
    'information_v2_5': {('v2_5', 'missing_core'): 1, ('v2_5', 'full'): -1},
    'interaction': {('v2_5', 'missing_core'): 1, ('v2_4', 'missing_core'): -1,
                    ('v2_5', 'full'): -1, ('v2_4', 'full'): 1},
}


def contrast_projects(slots, coefficients, high):
    groups, seen = defaultdict(list), set()
    for r in slots:
        if r['analysis_state'] not in {'rechecked_observed', 'no_returned_business_answer', 'rechecked_not_judgable'}:
            raise ValueError('Complete review/recheck required before any condition estimate')
        key = (r['project_group'], r['arm'], r['variant'], r['repeat'])
        if key in seen:
            raise ValueError('Duplicate planned slot')
        seen.add(key)
        finite_score(r['value'], 0, high)
        groups[r['project_group']].append(r)
    result = []
    for group, rows in sorted(groups.items()):
        assert len({r['role'] for r in rows}) == len({r['company_id'] for r in rows}) == 1
        cells = {}
        for (arm, variant), coefficient in coefficients.items():
            planned = [r['value'] for r in rows if (r['arm'], r['variant']) == (arm, variant)]
            if not planned:
                raise ValueError('Planned cell absent')
            observed = [v for v in planned if v is not None]
            cells[(arm, variant)] = {'mean': mean(observed) if observed else None,
                'low': mean(0 if v is None else v for v in planned),
                'high': mean(high if v is None else v for v in planned),
                'n': len(observed), 'planned': len(planned), 'coefficient': coefficient}
        available = all(c['mean'] is not None for c in cells.values())
        result.append({'project_group': group, 'role': rows[0]['role'], 'company_id': rows[0]['company_id'],
            'difference': sum(c['coefficient']*c['mean'] for c in cells.values()) if available else None,
            'worst_missing_bound': sum(c['coefficient']*c['low' if c['coefficient'] > 0 else 'high'] for c in cells.values()),
            'best_missing_bound': sum(c['coefficient']*c['high' if c['coefficient'] > 0 else 'low'] for c in cells.values()),
            'all_planned_repeat_slots_observed': all(c['n'] == c['planned'] for c in cells.values()),
            'cells': [{'arm': arm, 'variant': variant, **c} for (arm, variant), c in cells.items()]})
    return result


def main():
    from capstone_cp_common_20261112 import no_provider
    reports, pins = {}, {}
    with no_provider() as counts:
        for metric in ['D1', 'D2', 'D3', 'D4']:
            path = SOURCE/f'{metric}_slot_values.json'
            pins[str(path.relative_to(ROOT))] = sha(path)
            slots = read(path)
            for r in slots:
                if r.get('grade_path'):
                    assert sha(ROOT/r['grade_path']) == r['grade_sha256']
            reports[metric] = {}
            for name, coefficients in CONTRASTS.items():
                projects = contrast_projects(slots, coefficients, 1 if metric in {'D1', 'D2'} else 2)
                observed = [p for p in projects if p['difference'] is not None]
                full = [p for p in observed if p['all_planned_repeat_slots_observed']]
                report = {'metric': metric, 'contrast': name, 'planned_projects': len(projects),
                    'observed_projects': len(observed),
                    'project_equal_difference': mean(p['difference'] for p in observed) if observed else None,
                    'all_planned_missing_bounds': [mean(p[k] for p in projects) for k in ['worst_missing_bound', 'best_missing_bound']],
                    'complete_repeat_projects': len(full),
                    'complete_repeat_difference': mean(p['difference'] for p in full) if full else None,
                    'uncertainty': stratified_bootstrap(projects),
                    'leave_project_out': influence(projects, 'project_group'),
                    'leave_firm_out': influence(projects, 'company_id'),
                    'projects': projects}
                save(OUT/f'{metric}_{name}.json', report)
                reports[metric][name] = {k: report[k] for k in ['observed_projects', 'project_equal_difference',
                    'all_planned_missing_bounds', 'complete_repeat_projects', 'complete_repeat_difference', 'uncertainty']}
        for path, digest in pins.items():
            assert sha(ROOT/path) == digest
        save(OUT/'summary_001.json', reports)
        save(OUT/'manifest.json', {'source_files_sha256': pins,
            'analysis_code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT/'scripts/capstone_project_analysis_20261113.py']},
            'contrast_definitions': {k: [{'arm': a, 'variant': v, 'coefficient': c} for (a,v),c in cs.items()] for k,cs in CONTRASTS.items()},
            'interpretation': ['Exploratory, fixed same-project information contrasts; no new grading or output-based selection.',
                'Within-arm information contrast is missing_core minus full; negative means lower graded content under reduced information.',
                'Interaction is (v2_5-v2_4) under missing_core minus the same contrast under full.',
                'All planned missing bounds and observed-pair intervals can refer to different project sets.',
                'D3/D4 are ordinal 0-2 rubric scores, not utility or financial benefit.',
                'Same design-participating assistant grades; not independent expert evidence. Multiple exploratory comparisons, no confirmatory claim.'],
            'new_model_calls': 0, 'new_semantic_labels_inferred': 0, **counts})
    print(json.dumps({m:{c:{'n':x['observed_projects'],'difference':x['project_equal_difference'],
        'interval':x['uncertainty']['exploratory_percentile95']} for c,x in cs.items()} for m,cs in reports.items()}))


if __name__ == '__main__': main()
