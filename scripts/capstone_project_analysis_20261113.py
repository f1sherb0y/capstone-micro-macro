"""Project-level paired analysis implementing the frozen v4 micro rules.

Pure numerical functions only. A caller must independently establish complete
content grading/recheck and distinguish unknown responses from unreviewed ones.
Repeated answers or two information conditions are never independent projects.
"""
from collections import defaultdict
import math
import random
from statistics import mean

VARIANTS = ('full', 'missing_core')


def finite_score(value, low, high):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid metric value or range')
    return float(value)


def project_pairs(slots, *, left, right, low=0., high=1.):
    """Average observed repeats, then two conditions equally, then pair arms.

    slots includes all planned slots, with value=None for missing/unreviewed.
    Missing one whole condition does not transfer its half-weight to the other.
    Bounds use every planned slot/project, filling left/right missing values in
    opposite directions. They are mathematical limits, never assigned grades.
    """
    if left == right or low >= high:
        raise ValueError('Distinct arms and a nonempty score range are required')
    groups, seen = defaultdict(list), set()
    for source in slots:
        if source['arm'] not in {left, right}:
            continue
        row = dict(source)
        if row['variant'] not in VARIANTS:
            raise ValueError('Unexpected information condition')
        key = (row['project_group'], row['variant'], row['arm'], row['repeat'])
        if key in seen:
            raise ValueError('Duplicate planned first slot; cohorts must be analyzed separately')
        seen.add(key)
        row['value'] = finite_score(row['value'], low, high)
        groups[row['project_group']].append(row)
    result = []
    for group, rows in sorted(groups.items()):
        roles = {r['role'] for r in rows}
        firms = {r['company_id'] for r in rows}
        if len(roles) != 1 or len(firms) != 1:
            raise ValueError('One fixed role/enterprise pairing is required per micro project group')
        cells, observations = {}, {}
        for arm in [left, right]:
            for variant in VARIANTS:
                planned = [r for r in rows if r['arm'] == arm and r['variant'] == variant]
                if not planned:
                    raise ValueError('Missing planned condition/arm cells; do not silently change design')
                values = [r['value'] for r in planned]
                available = [v for v in values if v is not None]
                cells[arm, variant] = {'planned': len(values), 'observed': len(available),
                    'observed_mean': mean(available) if available else None,
                    'lower': mean(low if v is None else v for v in values),
                    'upper': mean(high if v is None else v for v in values)}
            arm_means = [cells[arm, variant]['observed_mean'] for variant in VARIANTS]
            observations[arm] = mean(arm_means) if all(v is not None for v in arm_means) else None
        delta = observations[left] - observations[right] if all(v is not None for v in observations.values()) else None
        worst = mean(cells[left, v]['lower'] - cells[right, v]['upper'] for v in VARIANTS)
        best = mean(cells[left, v]['upper'] - cells[right, v]['lower'] for v in VARIANTS)
        result.append({'project_group': group, 'role': next(iter(roles)), 'company_id': next(iter(firms)),
            'left_mean': observations[left], 'right_mean': observations[right], 'difference': delta,
            'all_planned_repeat_slots_observed': all(c['planned'] == c['observed'] for c in cells.values()),
            'planned_slots': len(rows), 'observed_slots': sum(c['observed'] for c in cells.values()),
            'worst_missing_bound': worst, 'best_missing_bound': best,
            'conditions': {arm: {variant: cells[arm, variant] for variant in VARIANTS} for arm in [left, right]}})
    return result


def percentile(sorted_values, p):
    if not sorted_values or not 0 <= p <= 1:
        raise ValueError('Nonempty sorted distribution and valid percentile required')
    point = p * (len(sorted_values) - 1)
    lower = int(point)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (point - lower) * (sorted_values[upper] - sorted_values[lower])


def stratified_bootstrap(projects, *, draws=20000, seed=20261112):
    """Resample paired project differences within fixed role strata."""
    if type(draws) is not int or draws <= 0:
        raise ValueError('Positive explicit bootstrap draw count required')
    available = [r for r in projects if r['difference'] is not None]
    if len({r['project_group'] for r in available}) != len(available):
        raise ValueError('Bootstrap input duplicates an independent project group')
    strata = defaultdict(list)
    for row in available:
        strata[row['role']].append(row['difference'])
    estimate = mean(r['difference'] for r in available) if available else None
    result = {'paired_projects': len(available), 'role_counts': {k: len(v) for k, v in sorted(strata.items())},
        'difference': estimate, 'exploratory_percentile95': None, 'seed': seed, 'resamples': draws,
        'unit': 'paired project group, not a model call/repeat/information condition',
        'singleton_strata': [k for k, values in sorted(strata.items()) if len(values) == 1]}
    if len(available) < 2 or all(len(v) == 1 for v in strata.values()):
        result['interval_state'] = 'insufficient_within_role_project_variation_for_interval'
        return result
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        sample = []
        for role in sorted(strata):
            values = strata[role]
            sample.extend(rng.choices(values, k=len(values)))
        samples.append(mean(sample))
    samples.sort()
    result.update(exploratory_percentile95=[percentile(samples, .025), percentile(samples, .975)],
        interval_state='exploratory_not_population_representativeness_or_independent_expert_validation')
    return result


def influence(projects, by):
    if by not in {'project_group', 'company_id', 'macro_family_id'}:
        raise ValueError('Unsupported leave-out unit')
    available = [r for r in projects if r['difference'] is not None]
    if any(not r.get(by) for r in available):
        raise ValueError('Missing source grouping for sensitivity analysis')
    rows = []
    for excluded in sorted({r[by] for r in available}):
        remaining = [r for r in available if r[by] != excluded]
        rows.append({'excluded_unit': excluded, 'removed_projects': len(available) - len(remaining),
            'remaining_projects': len(remaining),
            'remaining_mean_difference': mean(r['difference'] for r in remaining) if remaining else None})
    return rows


def summary(projects):
    observed = [r for r in projects if r['difference'] is not None]
    return {'planned_projects': len(projects), 'paired_observed_projects': len(observed),
        'project_equal_difference': mean(r['difference'] for r in observed) if observed else None,
        'all_planned_slot_bounds': [mean(r['worst_missing_bound'] for r in projects), mean(r['best_missing_bound'] for r in projects)] if projects else None,
        'complete_repeat_slot_projects': sum(r['all_planned_repeat_slots_observed'] for r in projects),
        'missing_bound_identity': 'Opposite favorable/unfavorable fillings across the full fixed design; not observed scores.'}
