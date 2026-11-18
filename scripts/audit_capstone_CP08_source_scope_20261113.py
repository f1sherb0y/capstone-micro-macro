"""Bind authored input-scope readings and literal scale diagnostics, no judging."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
from review_capstone_all_20261113 import MASTER,ROOT,cards,read,save,sha


def main():
    cp,byid=cards('CP08')
    notes=MASTER/'manual_labels/CP08_named_design_source_scope_readings_001.json'
    authored=read(notes)
    screened={c['window_id'] for c in byid.values() if c['variant']=='full' and c['role']!='designer'
              and '\u8bbe\u8ba1' in c['project_facts']['project_name']}
    assert screened=={r['window_id'] for r in authored['rows']}
    rows=[]
    for r in authored['rows']:
        c=byid[r['window_id']]
        assert type(r['potential_source_task_scope_tension']) is bool and r['reason']
        rows.append({**r,'project_group':c['project_group'],'assigned_role':c['role'],
                     'project_facts':c['project_facts'],'company_id':c['company_id'],
                     'counterpart_missing_window':c['window_id'].replace('-full','-missing_core')})
    assert len(rows)==16 and sum(r['potential_source_task_scope_tension'] for r in rows)==14
    evidence={'identity':'Post-hoc input-text description, not verified tender scope, new eligibility rule or semantic grading.',
        'task_cards_path':str(cp.relative_to(ROOT)),'task_cards_sha256':sha(cp),
        'authored_readings_path':str(notes.relative_to(ROOT)),'authored_readings_sha256':sha(notes),
        'all_CP08_project_groups':len({c['project_group'] for c in byid.values()}),
        'literal_name_screened_non_designer_groups':16,'authored_potential_scope_tension_groups':14,
        'authored_reading_counts':dict(Counter(r['classification'] for r in rows)),
        'rows':rows,'posthoc_scope_stratum_project_ids':[r['project_group'] for r in rows if r['potential_source_task_scope_tension']],
        'timing':'After all CP08 provider outputs existed and after first40 business grades; future ungraded responses were not inspected for this input-text screen.',
        'not_exhaustive_for_other_scope_problems_or_names_without_design_word':True,
        'primary_inclusion_inputs_and_scores_changed':False,'new_provider_calls':0}
    save(MASTER/'data_quality/CP08_named_design_source_scope_inventory_001.json',evidence)
    c=byid['CP08-101-full'];literal=c['project_facts']['scale']
    assert '148207357\u4e07\u5e73\u65b9\u7c73' in literal
    assert '\u7ea626\u516c\u9877' in literal and '\u7ea618.8\u516c\u9877' in literal and '\u7ea67.2\u516c\u9877' in literal
    building=Decimal('148207357')*10000
    land=Decimal('26')*10000
    save(MASTER/'data_quality/CP08_101_literal_scale_order_diagnostic_001.json',{
        'window_id':'CP08-101-full','project_group':c['project_group'],'project_facts':c['project_facts'],
        'task_cards_sha256':sha(cp),'given_literal_scale_field':literal,
        'literal_building_area_square_metres':str(building),'literal_site_area_square_metres':str(land),
        'literal_implied_building_area_divided_by_site_area':str(building/land),
        'identity':'Arithmetic diagnostic on provided text only; apparent order mismatch requires disclosure, not a verified correction of the real project.',
        'real_project_area_verified':False,'replacement_value_inferred':False,'source_or_prompt_changed':False,
        'primary_sample_exclusion':False,'first_answer_scores_for_this_group_exist_at_note_time':False,
        'treatment':'Retain the literal field and unknown real value; do not penalize merely quoting provided data, do not treat the derived ratio as an actual real-project indicator. Report leave-project-out sensitivity and corpus-validity limitation.',
        'new_provider_calls':0})
    print({'literal_screen':16,'authored_scope_tension':14,'initial_scores_changed':False,
           'literal_implied_area_ratio':str(building/land)})


if __name__=='__main__':
    main()
