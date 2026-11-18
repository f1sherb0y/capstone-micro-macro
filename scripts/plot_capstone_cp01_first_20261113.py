"""Versioned CP01 first-answer working figure, from completed content labels."""
import csv
from pathlib import Path
from statistics import mean

from capstone_cp_common_20261112 import ROOT, read, save, sha
from review_capstone_all_20261113 import MASTER

SOURCE = MASTER / 'analysis/CP01_first_review_complete_001/CP01'
OUT = MASTER / 'figures/CP01_first_review_001'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    assert read(SOURCE / 'analysis_manifest.json')['cohort_estimates_withheld'] is False
    if OUT.exists(): raise ValueError('Existing working figure version; do not overwrite')
    with (SOURCE / 'rechecked_case_descriptions.csv').open(encoding='utf-8-sig') as stream:
        descriptions = list(csv.DictReader(stream))
    rows, sources = [], {}
    for metric in ['D1', 'D2', 'D3', 'D4']:
        path = SOURCE / (metric + '_v2_5_minus_v2_4.json')
        report = read(path); e = report['cohort_estimate']
        assert report['pending_readable_content_reviews_or_rechecks'] == 0 and e is not None
        own = [r for r in descriptions if r['metric'] == metric and r['difference'] != '']
        assert len(own) == e['paired']['paired_observed_projects']
        values = {'metric': metric, 'unit': 'percentage points' if metric in {'D1','D2'} else 'ordinal score points (0-2)',
            'paired_projects': len(own), 'planned_projects': 24,
            'v2_4_mean': mean(float(r['right_mean']) for r in own),
            'v2_5_mean': mean(float(r['left_mean']) for r in own),
            'difference': e['paired']['project_equal_difference'],
            'exploratory_percentile95': e['uncertainty']['exploratory_percentile95'],
            'all24_planned_slot_missing_bounds': e['paired']['all_planned_slot_bounds'],
            'leave_one_project_out_range': [min(r['remaining_mean_difference'] for r in e['leave_project_out']),
                max(r['remaining_mean_difference'] for r in e['leave_project_out'])],
            'leave_one_firm_out_range': [min(r['remaining_mean_difference'] for r in e['leave_reused_firm_out']),
                max(r['remaining_mean_difference'] for r in e['leave_reused_firm_out'])],
            'complete_repeat_slot_difference': e['complete_repeat_slots_sensitivity']['project_equal_difference']}
        assert abs(values['v2_5_mean']-values['v2_4_mean']-values['difference']) < 1e-12
        if metric in {'D1','D2'}:
            for key in ['v2_4_mean','v2_5_mean','difference','complete_repeat_slot_difference']:
                values[key] *= 100
            for key in ['exploratory_percentile95','all24_planned_slot_missing_bounds','leave_one_project_out_range','leave_one_firm_out_range']:
                values[key] = [v*100 for v in values[key]]
        rows.append(values); sources[str(path.relative_to(ROOT)).replace('\\','/')] = sha(path)
    OUT.mkdir(parents=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,
        'axes.spines.right':False,'axes.spines.left':False,'svg.fonttype':'none'})
    fig, axes = plt.subplots(1,2,figsize=(14,5.4))
    fig.subplots_adjust(left=.16,right=.96,bottom=.26,top=.69,wspace=.76)
    labels = [['D1  Appropriate\naction','D2  Correct issue\ncoverage'],['D3  Feasibility','D4  Trade-off\nreasoning']]
    for panel, (ax, subset) in enumerate(zip(axes,[rows[:2],rows[2:]])):
        ax.axvline(0,color='#788592',linewidth=1.1,zorder=0)
        ax.grid(axis='x',color='#e7ebef',linewidth=.8,zorder=0)
        for y, row in zip([1,0],subset):
            lo,hi=row['exploratory_percentile95']; point=row['difference']
            ax.errorbar(point,y,xerr=[[point-lo],[hi-point]],fmt='o',color='#236b96',
                ecolor='#236b96',elinewidth=2.3,capsize=5,markersize=8,zorder=3)
            text = f"{point:+.1f} [{lo:.1f}, {hi:.1f}]" if panel==0 else f"{point:+.3f} [{lo:.3f}, {hi:.3f}]"
            ax.text(.05,y+.25,text,transform=ax.get_yaxis_transform(),fontsize=11,color='#253747')
        ax.set_yticks([1,0],labels[panel]); ax.tick_params(axis='y',length=0,pad=15)
        ax.set_ylim(-.5,1.55); ax.set_xlim((-5,40) if panel==0 else (-.06,.8))
        ax.set_xlabel('Difference, percentage points' if panel==0 else 'Difference, ordinal score points',labelpad=12)
        ax.set_title('24 paired projects' if panel==0 else '22 paired projects | 0–2 scores',loc='left',fontsize=12,pad=22)
    fig.suptitle('CP01 | First-answer content evaluation',x=.16,y=.96,ha='left',fontsize=20,fontweight='bold',color='#19384f')
    fig.text(.16,.865,'V2.5 minus V2.4 · 24 source groups · 190 readable answers / 192 planned',fontsize=12,color='#425466')
    fig.text(.16,.81,'Working result · AI review with author involvement · order-swap and repair analyses pending',fontsize=10,color='#815d25')
    fig.text(.16,.10,'Points: equal-weight project differences. Lines: exploratory 95% intervals, role-stratified project resampling (20,000 draws).',fontsize=9,color='#536170')
    fig.text(.16,.055,'Same-assistant evidence recheck; no independent expert validation. The two unknown responses remain missing. Higher scores are not measured business utility.',fontsize=9,color='#536170')
    for ext in ['png','svg']: fig.savefig(OUT/('CP01_first_answer_effects.'+ext),dpi=240,facecolor='white')
    plt.close(fig)
    save(OUT/'metric_summary.json',rows)
    with (OUT/'figure_data.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        fields=['metric','unit','paired_projects','planned_projects','v2_4_mean','v2_5_mean','difference','ci_low','ci_high','planned_missing_low','planned_missing_high']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({**{k:row[k] for k in fields[:7]},'ci_low':row['exploratory_percentile95'][0],
                'ci_high':row['exploratory_percentile95'][1],'planned_missing_low':row['all24_planned_slot_missing_bounds'][0],
                'planned_missing_high':row['all24_planned_slot_missing_bounds'][1]})
    save(OUT/'manifest.json',{'figure_status':'working_first_answer_results_order_swap_and_repair_analysis_pending',
        'source_sha256':sources,'source_case_csv_sha256':sha(SOURCE/'rechecked_case_descriptions.csv'),
        'script_sha256':sha(__file__),'artifact_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
        'new_model_calls':0,'new_semantic_scores':0,'missing_bounds_population':'all24 planned projects; not the same population as observed22 D3/D4 intervals',
        'no_weighted_total':True,'independent_human_validation':False})
    print('CP01 working figure and exact source data saved; no new calls or grades')


if __name__=='__main__': main()
