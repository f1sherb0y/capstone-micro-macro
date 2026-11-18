"""Business-content figure: equal-project issue composition and declared actions."""
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean
from review_capstone_all_20261113 import MASTER,ROOT,read,save,sha

SOURCE=MASTER/'analysis/CP01_business_composition_001'
OUT=MASTER/'figures/CP01_business_composition_001'
RATINGS=['correct','partial','missing','contradicted']


def issue_composition(records):
    cells=defaultdict(list)
    for r in records:
        counts=r['factor_counts'];total=sum(counts.values())
        assert total>0 and set(counts)<=set(RATINGS)
        cells[(r['project_group'],r['arm'],r['variant'])].append({k:counts.get(k,0)/total for k in RATINGS})
    projects=[]
    for group,arm in sorted({(g,a) for g,a,v in cells}):
        own=[cells.get((group,arm,v)) for v in ['full','missing_core']]
        if not all(own):raise ValueError('A missing entire information cell cannot inherit the other cell weight')
        values={k:mean(mean(r[k] for r in cell) for cell in own) for k in RATINGS}
        assert abs(sum(values.values())-1)<1e-12
        projects.append({'project_group':group,'arm':arm,**values})
    return projects,{a:{k:mean(r[k] for r in projects if r['arm']==a) for k in RATINGS} for a in ['v2_4','v2_5']}


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if OUT.exists():raise ValueError('Do not overwrite a sealed figure version')
    ledger=SOURCE/'answer_ledger_001.json';rows=read(ledger)
    summary=read(SOURCE/'summary_001.json')
    for name,digest in summary['source_files_sha256'].items():assert sha(ROOT/name)==digest
    projects,composition=issue_composition(rows)
    assert len(projects)==48
    main_d2=MASTER/'analysis/CP01_first_review_complete_001/CP01/D2_v2_5_minus_v2_4.json'
    difference=read(main_d2)['cohort_estimate']['paired']['project_equal_difference']
    assert abs(composition['v2_5']['correct']-composition['v2_4']['correct']-difference)<1e-12
    actions=['bid','bid_with_consortium','no_bid']
    management=[r for r in rows if r['role']!='supplier'];supplier=[r for r in rows if r['role']=='supplier']
    action_counts={a:{k:sum(r['declared_action']==k for r in management if r['arm']==a) for k in actions}
        for a in ['v2_4','v2_5']}
    OUT.mkdir(parents=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'svg.fonttype':'none',
        'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False})
    fig,axes=plt.subplots(2,1,figsize=(12,7.4))
    fig.subplots_adjust(left=.15,right=.96,top=.78,bottom=.20,hspace=1.15)
    colors=['#267e87','#e3bd70','#d5dce3','#bc6071']
    for i,arm in enumerate(['v2_4','v2_5']):
        left=0
        for key,color in zip(RATINGS,colors):
            value=100*composition[arm][key]
            axes[0].barh(1-i,value,left=left,height=.47,color=color)
            if value>=4:axes[0].text(left+value/2,1-i,f'{value:.1f}%',ha='center',va='center',fontsize=10,
                color='white' if key in {'correct','contradicted'} else '#243b4d')
            left+=value
    action_colors=['#397baf','#a08cb8','#929ca6']
    for i,arm in enumerate(['v2_4','v2_5']):
        left=0;total=sum(action_counts[arm].values())
        for key,color in zip(actions,action_colors):
            n=action_counts[arm][key];value=100*n/total
            axes[1].barh(1-i,value,left=left,height=.47,color=color)
            if n:axes[1].text(left+value/2,1-i,str(n),ha='center',va='center',fontsize=10,color='white')
            left+=value
        axes[1].text(101,1-i,f'n={total}',va='center',fontsize=10,color='#4b5965')
    for ax in axes:
        ax.set_yticks([1,0],['V2.4','V2.5']);ax.set_xlim(0,107);ax.set_xticks([0,25,50,75,100])
        ax.set_xticklabels(['0','25','50','75','100%']);ax.set_ylim(-.55,1.55)
        ax.tick_params(axis='y',length=0,pad=13)
    axes[0].set_title('A   Issue handling | repeat means → equal conditions → equal projects (24)',loc='left',fontsize=12,pad=31)
    axes[1].set_title('B   Declared management actions | descriptive answer counts',loc='left',fontsize=12,pad=31)
    from matplotlib.patches import Patch
    axes[0].legend(handles=[Patch(color=c,label=k.capitalize()) for k,c in zip(RATINGS,colors)],
        loc='lower left',bbox_to_anchor=(0,1.04),ncol=4,frameon=False,fontsize=9,borderaxespad=0)
    axes[1].legend(handles=[Patch(color=c,label=k) for k,c in zip(actions,action_colors)],
        loc='lower left',bbox_to_anchor=(0,1.04),ncol=3,frameon=False,fontsize=9,borderaxespad=0)
    fig.suptitle('CP01 | What changed in business judgments?',x=.15,y=.96,ha='left',fontsize=20,fontweight='bold',color='#19384f')
    fig.text(.15,.895,'190 readable first answers / 192 planned · author-assisted AI evaluation · exploratory',fontsize=11,color='#526170')
    fig.text(.15,.115,'Panel A preserves the primary D2 weighting; correct coverage improves by '+f'{100*difference:.2f} percentage points.',fontsize=10,color='#41556a')
    fig.text(.15,.074,'Panel B excludes 47 supplier proposals with no comparable action field. A bid label can still describe a conditional draft.',fontsize=9,color='#526170')
    fig.text(.15,.037,'Two historical missing answers remain missing. No independent expert review; action frequency is not business utility.',fontsize=9,color='#526170')
    for ext in ['png','svg']:fig.savefig(OUT/f'CP01_business_composition.{ext}',dpi=240,facecolor='white')
    plt.close(fig)
    data={'project_equal_issue_composition':composition,'project_values':projects,
        'management_action_counts':action_counts,'excluded_supplier_proposals':len(supplier),
        'primary_D2_difference_reproduced':difference,'new_model_calls':0}
    save(OUT/'figure_data.json',data)
    with (OUT/'project_issue_composition.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['project_group','arm',*RATINGS]);writer.writeheader();writer.writerows(projects)
    save(OUT/'manifest.json',{'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [ledger,SOURCE/'summary_001.json',main_d2]},
        'script_sha256':sha(Path(__file__)),'artifact_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
        'new_model_calls':0,'new_semantic_scores':0,'independent_expert_review':False})
    print(data['project_equal_issue_composition']);print(action_counts)


if __name__=='__main__':main()
