"""Export condition diagnostics from source JSON, with no hand-entered results."""
import csv
from pathlib import Path

from analyze_capstone_cp01_conditions_20261113 import MASTER, ROOT, OUT as SOURCE, read, save, sha

OUT = MASTER/'figures/CP01_condition_diagnostics_001'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if OUT.exists():
        raise ValueError('Create a new figure version instead of replacing artifacts')
    data, sources = [], {}
    for metric in ['D1', 'D2', 'D3', 'D4']:
        scale = 100 if metric in {'D1', 'D2'} else 1
        for contrast in ['version_full', 'version_missing', 'interaction']:
            path = SOURCE/f'{metric}_{contrast}.json'
            r = read(path)
            data.append({'metric': metric, 'contrast': contrast, 'projects': r['observed_projects'],
                'effect': r['project_equal_difference']*scale,
                'ci_low': r['uncertainty']['exploratory_percentile95'][0]*scale,
                'ci_high': r['uncertainty']['exploratory_percentile95'][1]*scale,
                'unit': 'percentage points' if scale == 100 else 'ordinal score points (0-2)'})
            sources[str(path.relative_to(ROOT))] = sha(path)
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
        'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False,'svg.fonttype':'none'})
    fig, axes = plt.subplots(2,2,figsize=(13.5,8.4))
    fig.subplots_adjust(left=.17,right=.97,top=.78,bottom=.21,wspace=.60,hspace=.70)
    titles = ['D1 | Appropriate action','D2 | Correct issue coverage','D3 | Feasibility','D4 | Trade-off reasoning']
    colors = ['#236b96','#208979','#9a672e']
    for ax, metric, title in zip(axes.flat,['D1','D2','D3','D4'],titles):
        own = [r for r in data if r['metric'] == metric]
        ax.axvline(0,color='#73828e',lw=1,zorder=0)
        ax.grid(axis='x',color='#e7ebef',lw=.8,zorder=0)
        for y,r,color in zip([2,1,0],own,colors):
            ax.errorbar(r['effect'],y,xerr=[[r['effect']-r['ci_low']],[r['ci_high']-r['effect']]],
                fmt='o',color=color,elinewidth=2,capsize=4,markersize=7,zorder=3)
            digits = 1 if metric in {'D1','D2'} else 3
            value = f"{r['effect']:+.{digits}f} [{r['ci_low']:.{digits}f}, {r['ci_high']:.{digits}f}]"
            ax.text(.02,y+.26,value,transform=ax.get_yaxis_transform(),fontsize=9,color='#253747')
        ax.set_yticks([2,1,0],[f"Full input (n={own[0]['projects']})",
            f"Reduced input (n={own[1]['projects']})",f"Interaction (n={own[2]['projects']})"])
        ax.tick_params(axis='y',length=0,pad=12)
        ax.set_ylim(-.45,2.55)
        ax.set_xlim((-.30,.85) if metric in {'D3','D4'} else (-8,45))
        ax.set_title(title,loc='left',fontsize=12,fontweight='bold',pad=12,color='#19384f')
        ax.set_xlabel('Difference, percentage points' if metric in {'D1','D2'} else 'Difference, ordinal score points',labelpad=8)
    fig.suptitle('CP01 | Information-condition diagnostics',x=.17,y=.96,ha='left',fontsize=20,fontweight='bold',color='#19384f')
    fig.text(.17,.895,'Full / reduced rows: V2.5 minus V2.4. Interaction: reduced-input contrast minus full-input contrast.',fontsize=10,color='#425466')
    fig.text(.17,.85,'24 fixed project groups | first answers only | same-assistant content review and evidence recheck',fontsize=10,color='#815d25')
    fig.text(.17,.125,'Points: project-equal effects; lines: exploratory 95% role-stratified project-bootstrap intervals (20,000 draws).',fontsize=9,color='#536170')
    fig.text(.17,.085,'Two unknown answers remain missing. Each row uses its available project pairs; interaction uses shared four-cell pairs.',fontsize=9,color='#536170')
    fig.text(.17,.045,'All interaction intervals include zero. These diagnostics do not establish stronger robustness, independent expert validity, or business utility.',fontsize=9,color='#536170')
    OUT.mkdir(parents=True)
    for ext in ['png','svg']:
        fig.savefig(OUT/f'CP01_information_conditions.{ext}',dpi=240,facecolor='white')
    plt.close(fig)
    with (OUT/'figure_data.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    save(OUT/'manifest.json',{'source_sha256':sources,'script_sha256':sha(__file__),
        'artifact_sha256':{p.name:sha(p) for p in OUT.iterdir()},'new_model_calls':0,'new_semantic_labels_inferred':0,
        'status':'exploratory_CP01_condition_diagnostics_other_cohorts_and_repairs_pending'})
    print('Saved source-bound condition PNG/SVG and exact plotting data.')


if __name__ == '__main__': main()
