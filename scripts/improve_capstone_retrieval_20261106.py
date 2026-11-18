"""Retrospective nested project-group cross-fitting of historical recommenders.

Labels of the outer test groups never enter fitting or inner model selection.
No historical partner/project text in corporate profiles, no LLM/API, no core edits.
"""
from __future__ import annotations
import gzip
import argparse
import hashlib
import json
import re
import sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_enriched_retrieval_20261101 import Retrieval,ROLES,SOURCE,read_csv,regions,tokens
from integration.candidate_policy_v3 import canonical_name,normalize

OUT=ROOT/'output/integration/capstone_retrieval_improvement_20261106'
OLD=ROOT/'output/integration/capstone_validation_20261105/offline'
ROLELIST=list(ROLES)
FAMILIES={
    'role_history':(1.,0.,0.,0.,0.),
    'region_history':(1.,8.,0.,0.,0.),
    'owner_history':(1.,4.,12.,0.,0.),
    'analogy_history':(.25,2.,4.,4.,.5),
    'title_analogy_history':(.1,1.,2.,12.,1.),
}
BLENDS=(0.,.15,.35,.60)
CANDIDATES=[(name,b) for name in FAMILIES for b in BLENDS]
METHODS=['old_role_first','role_history','region_history','owner_history','analogy_history','nested_hybrid']
KS=(1,3,5,12)

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))

def project_groups(projects):
    """Connected components of an input-only conservative near-duplicate rule."""
    parent=list(range(len(projects)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    names=[canonical_name(p['project_name']) for p in projects]
    # Digit/phase removal allows adjacent phases of a named project to stay together.
    stems=[re.sub(r'第?[一二三四五六七八九十百\d]+[期标段区座栋楼层号]?', '',n) for n in names]
    ts=[tokens(s) for s in stems]
    edges=[]
    for i in range(len(projects)):
        for j in range(i):
            if not (regions(projects[i]['location'])&regions(projects[j]['location'])):continue
            sim=len(ts[i]&ts[j])/max(1,len(ts[i]|ts[j]))
            if names[i]==names[j] or (len(stems[i])>=6 and stems[i]==stems[j]) or sim>=.80:
                a,b=find(i),find(j)
                if a!=b:parent[a]=b
                edges.append({'left':projects[j]['case_id'],'right':projects[i]['case_id'],'title_jaccard':sim})
    members=defaultdict(list)
    for i,p in enumerate(projects):members[find(i)].append(p['case_id'])
    ids={k:hashlib.sha256('|'.join(sorted(v)).encode()).hexdigest()[:16] for k,v in members.items()}
    return [ids[find(i)] for i in range(len(projects))],edges

def folds(indices,groups,k,salt):
    by=defaultdict(list)
    for i in indices:by[groups[i]].append(i)
    # Group sizes and input-only hash, never stratification by labels.
    ordered=sorted(by,key=lambda g:(-len(by[g]),hashlib.sha256((salt+g).encode()).hexdigest()))
    loads=[0]*k;assigned=[[] for _ in range(k)]
    for g in ordered:
        f=min(range(k),key=lambda x:(loads[x],x));assigned[f].extend(by[g]);loads[f]+=len(by[g])
    return [np.array(sorted(a),dtype=int) for a in assigned]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--precision-correction',action='store_true');args=parser.parse_args()
    if args.precision_correction:
        archive=OUT/'float32_first_pass'
        archived=read(archive/'archive_manifest.json')
        assert all(sha(archive/n)==h for n,h in archived.items())
        assert sha(archive/'runner.py')==read(archive/'protocol.json')['runner_sha256']
        save(OUT/'precision_correction.json',{'at':now(),'previous_protocol_sha256':sha(archive/'protocol.json'),
            'reason':'Independent float64 reconstruction exposed float32 near-tie accumulation changing candidate order at Top5 boundary.',
            'change':'Float64 public similarity matrices, history accumulation and score arithmetic; fixed input-only tie break retained.',
            'unchanged':['folds','grouping','candidate families','fusion grid','Hit@K definition','all 433 role units','source data'],
            'first_pass_retained':'float32_first_pass/','selection_based_on_test_metric':False,'new_api_requests':0})
    else:OUT.mkdir(exist_ok=False,parents=True)
    ps=read_csv(SOURCE/'simulation_input_projects.csv');cs=read_csv(SOURCE/'simulation_input_enterprises.csv')
    n,c,r=len(ps),len(cs),len(ROLELIST)
    cid={x['company_id']:i for i,x in enumerate(cs)};pid={x['case_id']:i for i,x in enumerate(ps)}
    groups,edges=project_groups(ps);outer=folds(range(n),groups,5,'outer-20261106/')
    protocol={'created_at':now(),'runner_sha256':sha(Path(__file__)),'study':'retrospective method development with nested project-group cross-fitting',
        'prior_labels_inspected':True,'new_api_requests':0,'source_sha256':{p.name:sha(p) for p in SOURCE.glob('*.csv')},
        'outer_folds':5,'inner_folds':3,'fold_seed':'20261106','near_duplicate_title_jaccard':.80,'numeric_precision':'float64',
        'grouping':'connected components; same recognized city; exact normalized title, phase/digit-stripped stem, or title-bigram Jaccard >= .80',
        'families':FAMILIES,'text_blends':BLENDS,'hyperparameters':len(CANDIDATES),
        'selection_metric':'inner validation pooled project-role Hit@5; ties prefer candidate declaration order',
        'score':'(1-b)*log1p(weighted other-project role history)/row_max + b*(11/(10+old_public_rank))',
        'history_features':['other training-project role-company links','project city','normalized owner exact match','project-title binary cosine','project type'],
        'excluded_profile_fields':['past_project_experience','partners_or_clients','notes','historical results'],
        'same_candidate_pool_as_old':True,'identity_merging':False,'formal_live_policy_changed':False,
        'boundaries':['different task from input-only retrieval: historical role links are now explicitly training data',
            'no temporal pre-award availability verified; retrospective interpolation, not prospective deployment accuracy',
            'no independent external dataset; all outer results retained even if negative']}
    save(OUT/'protocol.json',protocol)
    assignment=[{'case_id':p['case_id'],'project_name':p['project_name'],'group':groups[i],
        'outer_fold':next(f for f,a in enumerate(outer) if i in a)} for i,p in enumerate(ps)]
    save(OUT/'split_before_labels.json',{'assignments':assignment,'near_duplicate_edges':edges})
    # Construct public feature matrices before opening labels.
    dest=[regions(p['location']) for p in ps];owner=[canonical_name(p['owner_name']) for p in ps]
    title=[tokens(normalize(p['project_name'])) for p in ps]
    base=np.ones((n,n),dtype=np.float64)
    region=np.array([[bool(a&b) for b in dest] for a in dest],dtype=np.float64)
    owner_sim=np.array([[bool(a and a==b) for b in owner] for a in owner],dtype=np.float64)
    title_sim=np.array([[len(a&b)/max(1,(len(a)*len(b))**.5) for b in title] for a in title],dtype=np.float64)
    type_sim=np.array([[a['project_type']==b['project_type'] for b in ps] for a in ps],dtype=np.float64)
    channels=[base,region,owner_sim,title_sim,type_sim]
    weights={name:sum(w*x for w,x in zip(ws,channels)) for name,ws in FAMILIES.items()}
    eligible=np.zeros((n,r,c),dtype=bool);public_rank=np.full((n,r,c),c+1,dtype=np.int16)
    frozen=OLD/'E01_predictions_before_evaluation.jsonl.gz'
    assert sha(frozen)==read(OLD/'E01_prediction_freeze.json')['sha256']
    with gzip.open(frozen,'rt',encoding='utf-8') as f:
        for line in f:
            q=json.loads(line);i=pid[q['case_id']];j=ROLELIST.index(q['role'])
            for rank,company in enumerate(q['ranks']['role_first'],1):
                public_rank[i,j,cid[company]]=rank;eligible[i,j,cid[company]]=True
    text_score=11/(10+public_rank.astype(np.float64))
    save(OUT/'public_features_manifest.json',{'frozen_old_predictions_sha256':sha(frozen),
        'split_sha256':sha(OUT/'split_before_labels.json'),'features_built_before_this_execution_label_read':True})
    # Labels become supervised training data ONLY after public grouping is frozen.
    labels=defaultdict(set)
    for x in read_csv(SOURCE/'hidden_benchmark_project_enterprises.csv'):
        if x['company_role_original'] in ROLES and x['company_id']:
            labels[pid[x['case_id']],ROLELIST.index(x['company_role_original'])].add(cid[x['company_id']])
    assert len(labels)==433
    relations=[(i,j,k) for (i,j),gold in labels.items() for k in sorted(gold)]
    # Root-cause audit of original public-only method.
    index=Retrieval(cs);diag=Counter();misses=[]
    seen=defaultdict(set)
    for i,j,k in relations:seen[j,k].add(i)
    for (i,j),gold in labels.items():
        best=min(int(public_rank[i,j,k]) for k in gold)
        if best<=5:continue
        detail=[];diag['missed_role_units']+=1
        for k in sorted(gold):
            h=index.role_hits[ROLELIST[j]][k]
            tier='profile' if h['profile'] else 'name_only' if h['name_only'] else 'unknown'
            local=bool(dest[i]&index.locations[k]);repeat=len(seen[j,k])>1
            diag['missed_positive_role_'+tier]+=1;diag['missed_positive_local' if local else 'missed_positive_nonlocal_or_unknown']+=1
            diag['missed_positive_repeated_role_firm' if repeat else 'missed_positive_unique_role_firm']+=1
            detail.append({'company_id':cs[k]['company_id'],'old_rank':int(public_rank[i,j,k]),
                'text_role_evidence':tier,'local_profile':local,'other_projects_with_same_role':len(seen[j,k]-{i})})
        misses.append({'case_id':ps[i]['case_id'],'role':ROLELIST[j],'historical_details':detail})
    save(OUT/'error_diagnosis.json',{'counts':diag,'missed_units':misses})

    def fit(train,name):
        mask=np.zeros(n,dtype=bool);mask[train]=True
        hist=np.zeros((n,r,c),dtype=np.float64);w=weights[name]
        for i,j,k in relations:
            if mask[i]:hist[:,j,k]+=w[:,i]
        hist=np.log1p(hist);peak=hist.max(axis=2,keepdims=True)
        return hist/np.maximum(peak,1e-8)

    def score(hist,b):
        z=(1-b)*hist+b*text_score
        # Exactly tied history scores use the old public order; no label tie-break.
        z=z+1e-9*text_score.astype(np.float64)
        return np.where(eligible,z,-np.inf)

    def metrics(z,indices):
        total=hits=0
        for i in indices:
            for j in range(r):
                gold=labels.get((int(i),j))
                if not gold:continue
                top=np.argpartition(z[i,j],-5)[-5:]
                hits+=bool(gold&set(map(int,top)));total+=1
        return hits,total

    # Outer test-label access is reserved for the final evaluation below.
    predictions={m:np.empty((n,r,c),dtype=np.int16) for m in METHODS}
    for i in range(n):
        for j in range(r):predictions['old_role_first'][i,j]=np.argsort(public_rank[i,j],kind='stable')
    selection=[];training_seen={};isolation=[]
    for f,test in enumerate(outer):
        train=np.array(sorted(set(range(n))-set(map(int,test))),dtype=int)
        assert not set(groups[i] for i in train)&set(groups[i] for i in test)
        inner=folds(train,groups,3,f'inner-20261106/{f}/');totals=Counter();denoms=Counter()
        for g,val in enumerate(inner):
            inner_train=np.array(sorted(set(map(int,train))-set(map(int,val))),dtype=int)
            assert not set(inner_train)&set(test) and not set(inner_train)&set(val)
            assert not set(groups[i] for i in inner_train)&set(groups[i] for i in val)
            for name in FAMILIES:
                hist=fit(inner_train,name)
                for b in BLENDS:
                    h,d=metrics(score(hist,b),val);totals[name,b]+=h;denoms[name,b]+=d
            isolation.append({'outer_fold':f,'inner_fold':g,'training_projects':len(inner_train),
                'inner_validation_projects':len(val),'test_projects':len(test),'project_group_overlap':0})
        best=max(CANDIDATES,key=lambda key:totals[key]/max(1,denoms[key]))
        selection.append({'outer_fold':f,'selected_family':best[0],'text_blend':best[1],
            'inner_hit5':totals[best]/denoms[best],
            'candidates':[{'family':k[0],'text_blend':k[1],'hits':totals[k],'units':denoms[k]} for k in CANDIDATES],
            'training_case_ids':[ps[i]['case_id'] for i in train],
            'test_case_ids':[ps[i]['case_id'] for i in test]})
        for name in FAMILIES:
            hist=fit(train,name)
            if name in METHODS:
                predictions[name][test]=np.argsort(-score(hist,0)[test],axis=2,kind='stable').astype(np.int16)
            if name==best[0]:
                predictions['nested_hybrid'][test]=np.argsort(-score(hist,best[1])[test],axis=2,kind='stable').astype(np.int16)
        mask=set(map(int,train))
        for i in test:
            for j in range(r):
                gold=labels.get((int(i),j),set())
                training_seen[int(i),j]=sum(bool(seen[j,k]&mask) for k in gold)
        print(f'Finished outer fold {f+1}/5; selected {best}; training={len(train)}, test={len(test)}',flush=True)
    save(OUT/'inner_selection.json',selection);save(OUT/'split_isolation_checks.json',isolation)
    np.savez_compressed(OUT/'out_of_fold_rankings_before_evaluation.npz',**predictions,eligible=eligible)
    save(OUT/'ranking_index.json',{'case_ids':[p['case_id'] for p in ps],'company_ids':[x['company_id'] for x in cs],
        'roles':ROLELIST,'methods':METHODS,'interpretation':'each rank vector contains indices into company_ids; owner-excluded padding has eligible=false'})
    save(OUT/'prediction_freeze.json',{'at':now(),'sha256':sha(OUT/'out_of_fold_rankings_before_evaluation.npz'),
        'outer_test_scores_not_yet_calculated':True,'labels_previously_inspected_by_researcher':True})
    rows=[]
    for (i,j),gold in sorted(labels.items()):
        for method in METHODS:
            rank=predictions[method][i,j];rank=[int(k) for k in rank if eligible[i,j,k]]
            rankpos={k:a+1 for a,k in enumerate(rank)}
            row={'case_id':ps[i]['case_id'],'role':ROLELIST[j],'method':method,'group':groups[i],
                'fold':assignment[i]['outer_fold'],'historical_n':len(gold),'training_seen_historical_n':training_seen[i,j],
                'candidate_n':len(rank),'reciprocal_rank':1/min((rankpos[k] for k in gold if k in rankpos),default=float('inf')),
                'historical_ranks':{cs[k]['company_id']:rankpos.get(k) for k in sorted(gold)},
                'top5_company_ids':[cs[k]['company_id'] for k in rank[:5]]}
            for k in KS:
                hit=len(set(rank[:k])&gold);row[f'hit{k}']=int(hit>0);row[f'recall{k}']=hit/len(gold)
            rows.append(row)
    save(OUT/'role_scores.json',rows)
    summaries=[]
    for method in METHODS:
        subset=[x for x in rows if x['method']==method]
        z={'method':method,'units':len(subset),'projects':n}
        for k in KS:
            z[f'hits{k}']=sum(x[f'hit{k}'] for x in subset);z[f'hit{k}']=z[f'hits{k}']/len(subset)
            z[f'recall{k}']=sum(x[f'recall{k}'] for x in subset)/len(subset)
            z[f'project_any{k}']=sum(any(x[f'hit{k}'] for x in subset if x['case_id']==p['case_id']) for p in ps)
        summaries.append(z)
    assert next(s for s in summaries if s['method']=='old_role_first')['hits5']==24
    # Resample input-only project groups so related projects remain clustered.
    gids=sorted(set(groups));gp={g:i for i,g in enumerate(gids)}
    den=np.zeros(len(gids));nums={m:np.zeros(len(gids)) for m in METHODS}
    for x in rows:
        k=gp[x['group']]
        if x['method']=='old_role_first':den[k]+=1
        nums[x['method']][k]+=x['hit5']
    draws=np.random.default_rng(20261106).integers(0,len(gids),size=(4000,len(gids)))
    contrasts=[]
    for a,b in [('nested_hybrid','old_role_first'),('nested_hybrid','role_history'),('nested_hybrid','region_history')]:
        d=nums[a]-nums[b];v=d[draws].sum(axis=1)/den[draws].sum(axis=1)
        contrasts.append({'contrast':a+' minus '+b,'estimate':float(d.sum()/den.sum()),
            'group_cluster_percentile_95':[float(t) for t in np.quantile(v,[.025,.975])],'draws':4000})
    breakdown=[]
    for dimension in ['role','location','project_type','training_seen']:
        buckets=defaultdict(list)
        for x in rows:
            i=pid[x['case_id']]
            value=x['role'] if dimension=='role' else ('seen_positive' if x['training_seen_historical_n'] else 'no_seen_positive') if dimension=='training_seen' else ps[i][dimension]
            buckets[x['method'],value or '(missing)'].append(x)
        for (method,value),rs in sorted(buckets.items()):
            breakdown.append({'dimension':dimension,'group':value,'method':method,'units':len(rs),
                'projects':len({x['case_id'] for x in rs}),'hits5':sum(x['hit5'] for x in rs),'hit5':sum(x['hit5'] for x in rs)/len(rs)})
    save(OUT/'grouped_scores.json',breakdown)
    result={'status':'completed','finished_at':now(),'projects':n,'companies':c,'role_units':len(labels),
        'project_groups':len(gids),'multi_project_groups':sum(Counter(groups)[g]>1 for g in gids),
        'methods':summaries,'contrasts':contrasts,'diagnosis_counts':diag,
        'outer_fold_selections':[{k:x[k] for k in ['outer_fold','selected_family','text_blend','inner_hit5']} for x in selection],
        'candidate_pool_unchanged':True,'new_api_requests':0,
        'inputs_unchanged':all(sha(SOURCE/k)==v for k,v in protocol['source_sha256'].items())}
    assert result['inputs_unchanged'];save(OUT/'summary.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
