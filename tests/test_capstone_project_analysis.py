"""Scientific-unit/missing-condition checks against hand-computed examples."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from capstone_project_analysis_20261113 import project_pairs, stratified_bootstrap, influence


def slots(group, left, right, repeats=2, role='designer', firm='firm'):
    return [{'project_group': group, 'role': role, 'company_id': firm,
             'variant': variant, 'arm': arm, 'repeat': repeat, 'value': value}
            for variant in ['full', 'missing_core'] for arm, value in [('new', left), ('old', right)]
            for repeat in range(1, repeats + 1)]


def test_more_repeated_answers_do_not_create_more_projects_or_weights():
    # A contributes +1 with 5 repeats, B contributes -1 with 1 repeat.
    # Equal-project contrast is zero; per-answer pooling would be +2/3.
    result = project_pairs(slots('A', 1, 0, repeats=5) + slots('B', 0, 1, repeats=1), left='new', right='old')
    report = stratified_bootstrap(result, draws=20000)
    assert len(result) == report['paired_projects'] == 2 and report['difference'] == 0
    assert report['resamples'] == 20000 and report['seed'] == 20261112


def test_missing_whole_condition_never_promotes_other_condition_to_full_weight():
    data = slots('A', 1, 0, repeats=1)
    for row in data:
        if row['arm'] == 'new' and row['variant'] == 'missing_core':
            row['value'] = None
    result, = project_pairs(data, left='new', right='old')
    assert result['difference'] is None and result['left_mean'] is None
    assert result['worst_missing_bound'] == .5 and result['best_missing_bound'] == 1


def test_partial_repeat_aggregation_retains_condition_weights_and_exposes_complete_slot_sensitivity():
    data = slots('A', 1, 0)
    for row in data:
        if row['arm'] == 'new' and row['variant'] == 'full' and row['repeat'] == 2:
            row['value'] = None
        if row['arm'] == 'new' and row['variant'] == 'missing_core':
            row['value'] = 0
    result, = project_pairs(data, left='new', right='old')
    assert result['difference'] == .5
    assert not result['all_planned_repeat_slots_observed']
    assert result['worst_missing_bound'] == .25 and result['best_missing_bound'] == .5


def test_durable_unknown_is_not_assigned_zero_and_ordinal_bounds_remain_zero_to_two():
    data = slots('A', None, None, repeats=1)
    result, = project_pairs(data, left='new', right='old', low=0, high=2)
    assert result['difference'] is None
    assert (result['worst_missing_bound'], result['best_missing_bound']) == (-2, 2)


def test_firm_leave_out_removes_every_reused_project_not_just_one_answer():
    pairs = project_pairs(slots('A', 1, 0, firm='reused') + slots('B', 1, 0, firm='reused') + slots('C', 0, 1, firm='other'), left='new', right='old')
    row = next(r for r in influence(pairs, 'company_id') if r['excluded_unit'] == 'reused')
    assert row['removed_projects'] == 2 and row['remaining_projects'] == 1 and row['remaining_mean_difference'] == -1


def test_duplicate_repeats_or_mixed_cohort_keys_are_rejected():
    data = slots('A', 1, 0)
    with pytest.raises(ValueError, match='Duplicate planned'):
        project_pairs(data + [data[0]], left='new', right='old')


def test_one_project_does_not_get_a_misleading_zero_width_confidence_interval():
    pair = project_pairs(slots('A', 1, 0), left='new', right='old')
    report = stratified_bootstrap(pair)
    assert report['difference'] == 1 and report['exploratory_percentile95'] is None
