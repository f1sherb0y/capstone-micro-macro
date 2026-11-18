import pytest
from integration.role_match_metrics import score_roles


def test_one_matching_role_is_enough_but_role_and_identity_both_matter():
    labels = [dict(case_id='A', company_role_original='设计', company_id='DESIGNER'),
              dict(case_id='A', company_role_original='施工/总承包', company_id='BUILDER'),
              dict(case_id='B', company_role_original='设计', company_id='OTHER'),
              dict(case_id='C', company_role_original='', company_id='UNKNOWN')]
    predictions = [dict(case_id='A', role='设计', ranked_company_ids=['DESIGNER']),
                   dict(case_id='A', role='施工/总承包', ranked_company_ids=['WRONG']),
                   dict(case_id='B', role='施工/总承包', ranked_company_ids=['OTHER'])]
    result = score_roles(predictions, labels)
    assert result['project_any_role']['1'] == {'hits': 1, 'denominator': 2, 'rate': .5}
    assert result['role_pair_hits']['1'] == {'hits': 1, 'denominator': 3}
    assert result['projects'][0]['matched_roles_at_k']['1'] == ['设计']
    assert not result['projects'][1]['any_role_hit_at_k']['1']
    assert result['eligible_projects'] == 2  # C has no usable role label.


def test_topk_and_multiple_historical_partners_do_not_require_complete_team():
    labels = [dict(case_id='A', company_role_original='设计', company_id=key) for key in ['D1', 'D2']]
    result = score_roles([dict(case_id='A', role='设计', ranked_company_ids=['X', 'D2'])], labels)
    assert result['project_any_role']['1']['hits'] == 0
    assert result['project_any_role']['3']['hits'] == 1
    assert result['eligible_project_role_pairs'] == 1
    assert result['project_roles'][0]['matched_company_ids_at_k']['3'] == ['D2']
    with pytest.raises(ValueError, match='Duplicate'):
        score_roles([dict(case_id='A', role='设计', ranked_company_ids=['D1', 'D1'])], labels)
