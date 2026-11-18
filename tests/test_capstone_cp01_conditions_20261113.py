import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_capstone_cp01_conditions_20261113 import contrast_projects, CONTRASTS


def slots():
    values = {('v2_4','full'): [1., 1.], ('v2_5','full'): [1., 0.],
              ('v2_4','missing_core'): [0., 0.], ('v2_5','missing_core'): [1., 1.]}
    return [{'project_group':'g','role':'supplier','company_id':'c','arm':a,'variant':v,
             'repeat':i+1,'value':x,'analysis_state':'rechecked_observed'}
            for (a,v),xs in values.items() for i,x in enumerate(xs)]


def test_interaction_preserves_project_and_repeat_weight():
    rows = slots()
    contrasts = {k:contrast_projects(rows,c,1)[0]['difference'] for k,c in CONTRASTS.items()}
    assert contrasts['version_full'] == -.5
    assert contrasts['version_missing'] == 1
    assert contrasts['interaction'] == 1.5
    assert contrasts['interaction'] == contrasts['information_v2_5']-contrasts['information_v2_4']


def test_missing_repeat_mean_is_observed_and_bounds_keep_planned_weight():
    rows = slots()
    rows[0].update(value=None, analysis_state='no_returned_business_answer')
    result = contrast_projects(rows, CONTRASTS['version_full'], 1)[0]
    assert result['difference'] == -.5
    assert result['worst_missing_bound'] == -.5
    assert result['best_missing_bound'] == 0
    for r in rows:
        if (r['arm'],r['variant']) == ('v2_4','full'):
            r.update(value=None, analysis_state='no_returned_business_answer')
    result = contrast_projects(rows, CONTRASTS['interaction'], 1)[0]
    assert result['difference'] is None
    assert (result['worst_missing_bound'],result['best_missing_bound']) == (.5,1.5)


def test_pending_or_duplicate_not_treated_as_missing_output():
    rows=slots()
    with pytest.raises(ValueError, match='Duplicate'):
        contrast_projects(rows+[rows[0]], CONTRASTS['interaction'], 1)
    rows[0]['analysis_state']='explicit_content_review_pending'
    with pytest.raises(ValueError, match='Complete review'):
        contrast_projects(rows, CONTRASTS['interaction'], 1)
