"""Post-hoc conservative dated-history sensitivity; no new parameter search."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.improve_capstone_retrieval_20261106 import OUT,OLD,read,save,sha,now,ROLELIST,SOURCE,read_csv,regions,tokens,normalize,canonical_name,FAMILIES

def month(s):
    # Reject unknown dates, ranges, years-only and dates with ambiguous spelling.
    m=re.fullmatch(r'(19\d{2}|20\d{2})[-/.](0?[1-9]|1[012])(?:[-/.](?:0?[1-9]|[12]\d|3[01]))?',s.strip())
    return int(m[1])*12+int(m[2])-1 if m else None

def main():
    target=OUT/'time_sensitivity';target.mkdir(exist_ok=False)
    source=read(OUT/'protocol.json')
    assert all(sha(SOURCE/n)==h for n,h in source['source_sha256'].items())
    save(target/'protocol.json',{'at':now(),'runner_sha256':sha(Path(__file__)),
        'analysis':'post-hoc date-availability sensitivity, not a prospective test',
        'date_rule':'only strict year-month[-day] dates; reference completion month strictly earlier than earliest known target project start month',
        'training_rule':'same original outer training fold, all target near-duplicate groups excluded, plus reference relation finish date before target start',
        'weights':'fixed predeclared analogy_history formula; no new hyperparameter tuning',
        'families':['old_role_first','dated_role_history','dated_analogy_history'],
        'date_not_ranking_feature':True,'limits':['actual_start is a construction-start proxy, not verified pre-award query time',
            'record completion does not prove historical document publication time','date-missing targets retained as not evaluable, not silently removed from main 433'],
        'new_api_requests':0})
    ps=read_csv(SOURCE/'simulation_input_projects.csv');cs=read_csv(SOURCE/'simulation_input_enterprises.csv')
    links=read_csv(SOURCE/'hidden_benchmark_project_enterprises.csv')
    pid={p['case_id']:i for i,p in enumerate(ps)};cid={p['company_id']:i for i,p in enumerate(cs)}
    splits=read(OUT/'split_before_labels.json')['assignments'];n,c=len(ps),len(cs)
    starts=defaultdict(list);ends=defaultdict(list);truth=defaultdict(set)
    for x in links:
        i=pid[x['case_id']]
        start,end=month(x['actual_start']),month(x['actual_finish'])
        if start is not None:starts[i].append(start)
        if x['company_role_original'] not in ROLELIST or not x['company_id']:continue
        j=ROLELIST.index(x['company_role_original']);k=cid[x['company_id']]
        truth[i,j].add(k)
        if end is not None:ends[i,j,k].append(end)
    # Max completion for duplicated relation rows is the conservative evidence date.
    dated=[(i,j,k,max(v)) for (i,j,k),v in ends.items()]
    rankdata=np.load(OUT/'out_of_fold_rankings_before_evaluation.npz');eligible=rankdata['eligible']
    old=rankdata['old_role_first'];text=np.zeros_like(eligible,dtype=np.float64)
    for i in range(n):
        for j in range(len(ROLELIST)):text[i,j,old[i,j]]=11/(10+np.arange(1,c+1))
    cities=[regions(p['location']) for p in ps];owners=[canonical_name(p['owner_name']) for p in ps]
    titles=[tokens(normalize(p['project_name'])) for p in ps]
    rows=[];audit=[]
    for i,p in enumerate(ps):
        if i not in starts:continue
        cutoff=min(starts[i]);candidates=[x for x in dated if x[3]<cutoff and splits[x[0]]['outer_fold']!=splits[i]['outer_fold']]
        assert all(splits[a]['group']!=splits[i]['group'] for a,_,_,_ in candidates)
        weights={}
        for ref,_,_,_ in candidates:
            cos=len(titles[i]&titles[ref])/max(1,(len(titles[i])*len(titles[ref]))**.5)
            feats=(1,float(bool(cities[i]&cities[ref])),float(bool(owners[i] and owners[i]==owners[ref])),cos,float(p['project_type']==ps[ref]['project_type']))
            weights[ref]=sum(a*b for a,b in zip(FAMILIES['analogy_history'],feats))
        for j in range(len(ROLELIST)):
            gold=truth.get((i,j))
            if not gold:continue
            refs=[(a,k,end) for a,b,k,end in candidates if b==j]
            audit.append({'case_id':p['case_id'],'role':ROLELIST[j],'target_cutoff_month':cutoff,
                'training_relations':[{'case_id':ps[a]['case_id'],'company_id':cs[k]['company_id'],'finish_month':end} for a,k,end in refs]})
            for method in ['old_role_first','dated_role_history','dated_analogy_history']:
                if method=='old_role_first':rank=[int(k) for k in old[i,j] if eligible[i,j,k]]
                else:
                    scores=np.zeros(c,dtype=np.float64)
                    for a,k,_ in refs:scores[k]+=1 if method=='dated_role_history' else weights[a]
                    scores=np.log1p(scores)+1e-9*text[i,j]
                    scores[~eligible[i,j]]=-np.inf
                    rank=[int(k) for k in np.argsort(-scores,kind='stable') if eligible[i,j,k]]
                row={'case_id':p['case_id'],'role':ROLELIST[j],'method':method,'training_relation_n':len(refs),
                    'known_historical_from_available_records':sum(k in {b for a,b,e in refs} for k in gold)}
                for k in [1,3,5]:row[f'hit{k}']=int(bool(gold&set(rank[:k])))
                rows.append(row)
    methods=[]
    for method in ['old_role_first','dated_role_history','dated_analogy_history']:
        rs=[x for x in rows if x['method']==method]
        methods.append({'method':method,'units':len(rs),'projects':len({x['case_id'] for x in rs}),
            **{f'hits{k}':sum(x[f'hit{k}'] for x in rs) for k in [1,3,5]},
            **{f'hit{k}':sum(x[f'hit{k}'] for x in rs)/len(rs) for k in [1,3,5]},
            'units_without_prior_same_role_record':sum(x['training_relation_n']==0 for x in rs)})
    save(target/'role_scores.json',rows);save(target/'training_date_audit.json',audit)
    summary={'status':'completed','finished_at':now(),'strictly_dated_reference_relations':len(dated),
        'total_main_role_units':len(truth),'target_projects_with_parsed_start':len(starts),
        'not_evaluable_role_units_due_to_target_start':len(truth)-methods[0]['units'],'methods':methods,'new_api_requests':0}
    save(target/'summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
