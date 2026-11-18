"""Observe existing runs and seal business-review milestones, without launching work."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json

from review_capstone_all_20261113 import ROOT, MASTER, CP00, CP01, read, save, sha
from capstone_cp_common_20261112 import CP03


def main(number):
    assert len(number)==3 and number.isdigit()
    target=MASTER/f'paid_resume_progress_{number}.json'
    assert not target.exists()
    now=datetime.now(timezone.utc).isoformat()
    grades={c:[read(p) for p in (MASTER/'business_review'/c).glob('*.json')] for c in ['CP00','CP01','CP08','CP07']}
    states={}
    for c,rows in grades.items():
        first=[r for r in rows if r.get('attempt',1)==1]
        repaired=[r for r in rows if r.get('attempt',1)==2]
        for r in rows:
            name=f"{r['window_id']}-{r['arm']}-r{r['repeat']}-a{r.get('attempt',1)}.json"
            gp=MASTER/'business_review'/c/name; cp=MASTER/'business_recheck'/c/name
            if cp.exists():
                check=read(cp)
                assert check['complete'] and check['initial_record_sha256']==sha(gp)
            else:
                # The four retained CP00 calibration revisions embed their recheck.
                check=r.get('evidence_recheck')
                assert check and check['complete'] and c=='CP00'
                assert sha(ROOT/check['initial_record_path'])==check['initial_record_sha256']
                assert sha(MASTER/'calibration/six_block_calibration.json')==check['calibration_sha256']
        states[c]={'first_reviews_rechecked':len(first),'repair_reviews_rechecked':len(repaired)}
    assert states['CP01']=={'first_reviews_rechecked':190,'repair_reviews_rechecked':47}
    macro={}
    for name,d in [('CP03',CP03),('CP03E',MASTER.parent/'2026-11-13_CP03E另三组宏观'),
                   ('CP03X',MASTER.parent/'2026-11-13_CP03X宏观扩样')]:
        files=list((d/'run/provider_attempts').glob('*/*.json'))
        outcomes=read(d/'run/outcomes.json') if (d/'run/outcomes.json').exists() else []
        commands=sorted((d/'chains').glob('*/command.json'),key=lambda p:p.stat().st_mtime)
        macro[name]={'provider_status_counts':dict(Counter(read(p)['status'] for p in files)),
            'saved_provider_attempts':len(files),'completed_verified_chains':[r['chain_id'] for r in outcomes
                if (r.get('verification') or {}).get('technical_integrity_passed')],
            'latest_started_chain':commands[-1].parent.name if commands else None,
            'local_halt':(d/'run/HALT.json').exists(),
            'returned_provider_record_sha256':{str(p.relative_to(ROOT)):sha(p) for p in files if read(p)['status']=='returned'}}
    new_macro=sum(n for d in macro.values() for s,n in d['provider_status_counts'].items() if s!='reserved')
    pins=[MASTER/'analysis/CP01_repair_content_002/manifest.json',
          MASTER/'CP01修复后业务结果_001.md',MASTER/'CP01_repair_analysis_revision_notice_001.json',
          MASTER/'pair_preferences/CP01_001/descriptive_analysis_001.json',
          MASTER/'pair_preferences/CP01_001/retained_reason_label_crosswalk_001.json',
          MASTER/'CP01首轮成对偏好结果_001.md',
          MASTER/'pair_preferences/CP01_001/evidence_audit_001.json',
          MASTER/'analysis/CP01_business_composition_001/summary_001.json',
          MASTER/'CP01行动与业务问题构成_001.md',
          MASTER/'figures/CP01_business_composition_001/manifest.json',
          MASTER/'figures/CP01_business_composition_001/visual_check_001.json',
          MASTER/'CP01业务中间指标与图注_001.md',
          MASTER/'response_index_CP00_first_review_complete_001.json',
          MASTER/'business_readiness_CP00_first_review_complete_001.json',
          MASTER/'response_index_CP08_review_progress_005.json',
          MASTER/'business_readiness_CP08_review_progress_005.json',
          MASTER/'analysis/CP08_review_progress_005/CP08/analysis_manifest.json',
          MASTER/'data_quality/CP08_009_named_design_source_contractor_task_001.json',
          MASTER/'data_quality/CP08_named_design_source_scope_inventory_001.json',
          MASTER/'data_quality/CP08_101_literal_scale_order_diagnostic_001.json',
          MASTER/'data_quality/CP08_013_project_title_type_tension_001.json',
          MASTER/'data_quality/CP08_022_named_design_source_supplier_task_001.json',
          MASTER/'manual_labels/CP08_reviewed_017_024_D1_boundary_candidates_001.json',
          MASTER/'data_quality/CP08_reviewed_017_024_D1_boundary_bindings_001.json',
          MASTER/'manual_labels/CP08_reviewed_025_032_D1_boundary_candidates_001.json',
          MASTER/'data_quality/CP08_reviewed_025_032_D1_boundary_bindings_001.json',
          MASTER/'manual_labels/CP08_reviewed_033_040_D1_boundary_candidates_001.json',
          MASTER/'data_quality/CP08_reviewed_033_040_D1_boundary_bindings_001.json',
          MASTER/'data_quality/CP08_033_project_name_location_tension_001.json',
          MASTER/'data_quality/CP08_040_named_consultancy_source_contractor_task_001.json',
          MASTER/'data_quality/CP08_037_explicit_quotation_total_rows_001.json',
          MASTER/'data_quality/CP08_034_approximate_margin_basis_caveat_001.json',
          MASTER/'data_quality/CP08_first160_quote_traceability_audit_001.json',
          MASTER/'manual_labels/CP08_consultancy_name_source_readings_001.json',
          MASTER/'data_quality/CP08_consultancy_source_scope_inventory_001.json',
          MASTER/'feedback_preparation/source_progress_001/manifest.json',
          MASTER/'feedback_preparation/source_progress_001/selection_validation_001.json',
          MASTER/'CP04反馈来源准备_001.md',
          MASTER/'analysis/CP00_first_review_complete_001/CP00/analysis_manifest.json',
          MASTER/'analysis/CP00_first_review_complete_001/business_report_manifest_001.json',
          MASTER/'CP00首轮业务结果_001.md',
          MASTER/'analysis/CP00_repair_content_002/manifest.json',
          MASTER/'CP00修复后业务结果_002.md',
          MASTER/'CP00评分类别一致性补充_001.md',
          MASTER/'business_revision/CP00/EXPAND-23-full-v2_5-r2-a1/revision-001.json',
          MASTER/'analysis/CP00_review_progress_001/D1_ambiguous_reading_source_bindings.json',
          MASTER/'data_quality/CP00_explicit_quotation_total_rows_001.json',
          MASTER/'data_quality/CP00_EXPAND15_retained_architectural_practice_001.json',
          MASTER/'macro_results/first_fixed_block_001/manifest.json',
          MASTER/'macro_results/first_fixed_block_001/business_interpretation_001.json',
          MASTER/'宏观首块业务结果_001.md',MASTER/'宏观首块图注补充_001.md',
          MASTER/'figures/first_fixed_macro_block_001/manifest.json',
          MASTER/'figures/first_fixed_macro_block_001/visual_check_001.json']
    pins.extend(sorted((MASTER/'manual_labels').glob('CP08_*_compact_first_*_lineage.json')))
    record={'at_UTC':now,'state':'review_progress_with_existing_macro_pipeline',
        'business_review_counts':states,'total_first_reviewed_and_rechecked':sum(d['first_reviews_rechecked'] for d in states.values()),
        'total_repair_reviewed_and_rechecked':sum(d['repair_reviews_rechecked'] for d in states.values()),
        'CP01_effective_repair_analysis':'analysis/CP01_repair_content_002/manifest.json',
        'CP01_initial_repair_review_revisions':3,'CP01_revised_factor_or_detailed_values':5,
        'CP01_first_scores_changed':False,'macro':macro,
        'CP00_first_business_analysis':'analysis/CP00_first_review_complete_001/business_report_manifest_001.json',
        'CP00_repair_business_analysis':'analysis/CP00_repair_content_002/manifest.json',
        'CP00_append_only_first_S6_category_revisions':1,
        'CP00_first_D1_D2_numeric_scores_changed_by_revision':False,
        'CP00_whole_missing_information_D1_stress':'analysis/CP00_first_review_complete_001/business_description_001.json',
        'CP08_content_analysis':'analysis/CP08_review_progress_005/CP08/analysis_manifest.json',
        'CP08_additional_posthoc_reading_candidates':{'count':19,
            'scope':'Selected borderline readings from reviewed groups017–040, not an exhaustive full-cohort audit.',
            'sources':['data_quality/CP08_reviewed_017_024_D1_boundary_bindings_001.json',
                       'data_quality/CP08_reviewed_025_032_D1_boundary_bindings_001.json',
                       'data_quality/CP08_reviewed_033_040_D1_boundary_bindings_001.json'],
            'primary_scores_changed':False,'cohort_estimate_produced':False},
        'CP08_mechanical_quote_traceability_audit':{'reviewed_answers':160,'exact_quotes':1047,
            'all_passed':True,'semantic_regrading':False,
            'source':'data_quality/CP08_first160_quote_traceability_audit_001.json'},
        'CP04_source_preparation':{'fixed_R_repeat1_sources':27,'planned_slots':324,
            'bound_actual_simulated_windows':2,'replays_executed':0,'provider_calls':0,
            'source_selection_tests_passed':4,'other_source_projects_pending':26,
            'manifest':'feedback_preparation/source_progress_001/manifest.json',
            'replay_oracle_and_runner_complete':False},
        'CP08_posthoc_input_scope_readings':{'literal_screened_groups':16,'potential_scope_tension_groups':14,
            'primary_inclusion_or_scores_changed':False,
            'source':'data_quality/CP08_named_design_source_scope_inventory_001.json'},
        'CP08_posthoc_consultancy_scope_supplement':{'all232_names_screened':True,
            'literal_screened_groups':3,'overlap_with_prior_design_scope_groups':1,
            'combined_named_service_scope_tension_groups':15,
            'separate_possible_source_entity_unit_ambiguity_groups':1,
            'primary_inclusion_or_scores_changed':False,
            'source':'data_quality/CP08_consultancy_source_scope_inventory_001.json',
            'exhaustive_real_procurement_scope_validation':False},
        'CP08_cohort_estimates_withheld_until_all_readable_answers_reviewed':True,
        'CP01_pair_preferences':{'planned':48,'processed':48,'readable_pairs':46,
            'counts':read(MASTER/'pair_preferences/CP01_001/summary_001.json')['preferences'],
            'retained_original':12,'newly_authored':36,'newly_authored_rechecked':36,'all48_order_swapped':False},
        'CP01_action_and_primary_D1_issue_composition':'analysis/CP01_business_composition_001/summary_001.json',
        'CP00_D1_ambiguous_reading_flags':'analysis/CP00_review_progress_001/D1_ambiguous_reading_source_bindings.json',
        'CP00_D1_ambiguity_note':'13 post-hoc borderline interpretations retained without score changes; extend coverage before final dual-direction sensitivity, not independent judgments.',
        'first_macro_block':{'verified_chains':4,'source_groups':1,'repeat_blocks':1,
            'actual_canonical_commercial_choices_identical':True,'T2_to_T8_and_state_paths_identical':True,
            'full_macro_cohort_analysis_complete':False,
            'business_interpretation':'macro_results/first_fixed_block_001/business_interpretation_001.json'},
        'master_new_started_calls':2023+new_macro,'master_cap':3488,
        'post_format_stop_new_calls':779+new_macro,'post_format_stop_cap':2240,
        'CP07_unused_3_calls_in_latest_scope_not_transferred':True,
        'serial_session':18707,'serial_session_last_poll':'confirmed live during checkpoint turn',
        'serial_state':read(MASTER/'serial_pipeline_003/state.json'),
        'global_paid_halt':(MASTER/'PAID_HALT.json').exists(),
        'latest_artifact_sha256':{str(p.relative_to(MASTER)):sha(p) for p in pins},
        'unreviewed_readable_first_answers':1590-sum(d['first_reviews_rechecked'] for d in states.values()),
        'unreviewed_CP00_actual_repair_answers':48-states['CP00']['repair_reviews_rechecked'],
        'remaining_work':['CP08 and CP07 first-answer grading and evidence recheck.',
            'Extend CP00 borderline-reading evidence through the full cohort; report symmetric sensitivity with unchanged original scores.',
            'Complete CP08 scope-reading sensitivity for the combined15 named-service scope-tension groups, the separate source-entity ambiguity and other input-quality notes; retain primary inclusion and all versions.',
            'CP07 process-issue tracking, CP08/CP07 preselected order checks, old organization12 exploratory assessment.',
            'Continue existing serial CP03/E/X execution without relaunch, then source-bound macro and deterministic feedback analyses.',
            'Complete scientific tables/figures, claims-to-evidence and total results/discussion deliverables.'],
        'overall_goal':'active_not_complete'}
    assert record['master_new_started_calls']<=3488 and record['post_format_stop_new_calls']<=2240
    save(target,record)
    path=MASTER/'progress.json'; previous=read(path)
    save(MASTER/'progress_snapshots'/f'before_checkpoint_{number}.json',previous)
    previous.update(updated_at_UTC=now,new_attempts=2023+new_macro,
        actual_semantic_repair_reviews=record['total_repair_reviewed_and_rechecked'],
        actual_evidence_rechecked_repair_reviews=record['total_repair_reviewed_and_rechecked'],
        last_progress_record=target.name,CP01_repair_analysis=record['CP01_effective_repair_analysis'])
    previous['work_packages']['CP01']='first190_repair47_order12_pair48_with36_supplemental_rechecks_action_and_issue_composition_complete'
    cp08_first=states['CP08']['first_reviews_rechecked']
    previous['work_packages']['CP08']=f'execution_finished_first{cp08_first}of926_rechecked_remaining{926-cp08_first}_cohort_estimates_withheld'
    previous['work_packages']['CP04']='offline_source_preparation_27_fixed_sources_324_slots_2_windows_bound_0_replays_oracle_and_runner_pending'
    if states['CP00']=={'first_reviews_rechecked':188,'repair_reviews_rechecked':48}:
        previous['work_packages']['CP00']='first188_repair48_rechecked_4_unknown_retained_separate_business_reports_ready_boundary_audit_pending'
    for batch,observed in macro.items():
        if observed['latest_started_chain']:
            previous['work_packages'][batch]=(f"execution_running_verified{len(observed['completed_verified_chains'])}"
                f"_latest_started_{observed['latest_started_chain']}")
    reviewed=record['total_first_reviewed_and_rechecked'];pending=record['unreviewed_readable_first_answers']
    repairs=record['total_repair_reviewed_and_rechecked']
    remaining_repairs=record['unreviewed_CP00_actual_repair_answers']
    previous['work_packages']['review_analysis_figures']=(f'first{reviewed}_and_repair{repairs}_rechecked_CP00_CP01_business_analyses_ready'
        f'_other{pending}_first_and{remaining_repairs}_CP00_repairs_pending')
    previous['actual_semantic_first_reviews']=reviewed
    previous['actual_evidence_rechecked_first_reviews']=reviewed
    previous['first_macro_block_business_results']=record['first_macro_block']['business_interpretation']
    path.write_text(json.dumps(previous,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'checkpoint':target.name,'counts':states,'new_started':2023+new_macro,
        'macro':{k:{x:v[x] for x in ['provider_status_counts','completed_verified_chains','latest_started_chain']} for k,v in macro.items()},
        'global_halt':record['global_paid_halt']},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',required=True);main(p.parse_args().checkpoint)
