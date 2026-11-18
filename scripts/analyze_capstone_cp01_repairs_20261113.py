"""Separate, fully source-bound descriptions of the selected 47 repair answers."""
from collections import Counter, defaultdict
import csv
from pathlib import Path
from statistics import mean
import json
import argparse

from review_capstone_all_20261113 import ROOT, MASTER, CP01, read, save, sha, source
from analyze_capstone_content_20261113 import grade_value
from capstone_project_analysis_20261113 import stratified_bootstrap, influence
from capstone_cp_common_20261112 import no_provider
from revise_capstone_business_evidence_20261113 import effective_review

DEFAULT_TAG='CP01_repair_content_002'


def write_csv(path, rows):
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main(tag=DEFAULT_TAG):
    assert tag and all(c.isalnum() or c in '_-' for c in tag)
    OUT=MASTER/'analysis'/tag
    if OUT.exists(): raise ValueError('Use a new immutable analysis version')
    paths=sorted((CP01/'continuation-001/run/jobs').glob('*/attempt-2.json'))
    assert len(paths)==47 and not list((CP01/'run/jobs').glob('*/attempt-2.json'))
    pairs, pins, factor_transitions=[],{},Counter()
    with no_provider() as counts:
        for raw in paths:
            data=read(raw); job=data['job']
            wid,arm,repeat=job['window_id'],job['arm'],job['repeat']
            records=[]
            for attempt in [1,2]:
                filename=f'{wid}-{arm}-r{repeat}-a{attempt}.json'
                grade_path=MASTER/'business_review/CP01'/filename
                check_path=MASTER/'business_recheck/CP01'/filename
                initial,check=read(grade_path),read(check_path)
                grade,revisions=effective_review(grade_path)
                response,_,payload=source('CP01',wid,arm,repeat,attempt)
                assert isinstance(payload,dict)
                assert check['complete'] and check['initial_record_sha256']==sha(grade_path)
                assert initial['response_sha256']==grade['response_sha256']
                assert sha(response)==grade['response_sha256']==check['response_sha256']
                assert grade['input_card_sha256']==check['task_card_sha256']==sha(ROOT/grade['input_card_path'])
                for p in [grade_path,check_path,response,ROOT/grade['input_card_path']]: pins[str(p.relative_to(ROOT))]=sha(p)
                for p in revisions:
                    revision=read(p)
                    notes=ROOT/revision['authored_notes_path']
                    assert sha(notes)==revision['authored_notes_sha256']
                    pins[str(p.relative_to(ROOT))]=sha(p)
                    pins[str(notes.relative_to(ROOT))]=sha(notes)
                records.append(grade)
            before,after=records
            assert before['project_group']==after['project_group'] and before['role']==after['role']
            assert [f['id'] for f in before['factor_ratings']]==[f['id'] for f in after['factor_ratings']]
            for a,b in zip(before['factor_ratings'],after['factor_ratings']):
                factor_transitions[a['rating']+' -> '+b['rating']]+=1
            row={'window_id':wid,'project_group':after['project_group'],'role':after['role'],
                'company_id':str(job.get('company_id') or ''),'arm':arm,'repeat':repeat,
                'variant':'missing_core' if wid.endswith('-missing_core') else 'full',
                'before_response_path':before['response_path'],'after_response_path':after['response_path'],
                'before_response_sha256':before['response_sha256'],'after_response_sha256':after['response_sha256'],
                'before_grade_path':str((MASTER/'business_review/CP01'/f'{wid}-{arm}-r{repeat}-a1.json').relative_to(ROOT)),
                'after_grade_path':str((MASTER/'business_review/CP01'/f'{wid}-{arm}-r{repeat}-a2.json').relative_to(ROOT))}
            from review_capstone_all_20261113 import cards
            card=cards('CP01')[1][wid]
            row['company_id']=card['company_id']
            for metric in ['D1','D2','D3','D4']:
                initial,repaired=grade_value(before,metric),grade_value(after,metric)
                assert (initial is None)==(repaired is None), 'Do not change detailed scoring sample after repair'
                row[metric+'_before'],row[metric+'_after']=initial,repaired
                row[metric+'_change']=repaired-initial if initial is not None else None
            pairs.append(row)
        reports,project_rows={},[]
        for metric in ['D1','D2','D3','D4']:
            eligible=[r for r in pairs if r[metric+'_change'] is not None]
            groups=defaultdict(list)
            for r in eligible: groups[r['project_group']].append(r)
            projects=[]
            for group,rows in sorted(groups.items()):
                assert len({r['role'] for r in rows})==len({r['company_id'] for r in rows})==1
                item={'metric':metric,'project_group':group,'role':rows[0]['role'],'company_id':rows[0]['company_id'],
                    'selected_repair_answers':len(rows),
                    'before_mean':mean(r[metric+'_before'] for r in rows),
                    'after_mean':mean(r[metric+'_after'] for r in rows),
                    'difference':mean(r[metric+'_change'] for r in rows)}
                projects.append(item);project_rows.append(item)
            reports[metric]={'selected_answer_pairs':len(eligible),'selected_source_projects':len(projects),
                'raw_answer_before_mean':mean(r[metric+'_before'] for r in eligible),
                'raw_answer_after_mean':mean(r[metric+'_after'] for r in eligible),
                'project_equal_before_mean':mean(r['before_mean'] for r in projects),
                'project_equal_after_mean':mean(r['after_mean'] for r in projects),
                'project_equal_change':mean(r['difference'] for r in projects),
                'answer_transitions':dict(Counter(f"{r[metric+'_before']:g} -> {r[metric+'_after']:g}" for r in eligible)),
                'improved_answers':sum(r[metric+'_change']>0 for r in eligible),
                'unchanged_answers':sum(r[metric+'_change']==0 for r in eligible),
                'lower_answers':sum(r[metric+'_change']<0 for r in eligible),
                'selected_project_exploratory_uncertainty':stratified_bootstrap(projects),
                'leave_selected_project_out':influence(projects,'project_group'),
                'leave_reused_firm_out':influence(projects,'company_id')}
        for path,digest in pins.items(): assert sha(ROOT/path)==digest
        save(OUT/'answer_pairs.json',pairs)
        save(OUT/'summary_001.json',{'actual_repair_calls':47,'maximum_allowed':48,
            'unused_capacity_is_not_missing_repair_response':1,'planned_repair_answers_without_semantic_review':0,
            'selected_source_projects':len({r['project_group'] for r in pairs}),
            'selected_variants':dict(Counter(r['variant'] for r in pairs)),
            'selected_arms':dict(Counter(r['arm'] for r in pairs)),
            'factor_state_transitions':dict(factor_transitions),'metrics':reports,
            'initial_first_answer_scores_modified':False})
        write_csv(OUT/'answer_pairs.csv',pairs)
        write_csv(OUT/'selected_project_metric_pairs.csv',project_rows)
        save(OUT/'manifest.json',{'source_sha256':pins,'script_sha256':sha(__file__),
            'revision_reader_sha256':sha(ROOT/'scripts/revise_capstone_business_evidence_20261113.py'),
            'effective_revisions_included':sum('/business_revision/' in p.replace('\\','/') for p in pins),
            'artifact_sha256':{p.name:sha(p) for p in OUT.iterdir()},
            'analysis_scope':['Selected repairs only; not a randomized repair-effect trial or a fresh independent sample.',
                'All 47 actual readable repairs included; no scores invented for one unused maximum-capacity slot.',
                'Average selected answers within each source project, then give each included project equal weight.',
                'These selected-answer means do not replace the full/missing equally weighted first-answer analysis.',
                'D1/D2 cover all47; D3/D4 cover fixed repeat1 only; same assistant evidence review, not independent validation.',
                'Intervals resample selected source projects within role, not individual answers; conditional descriptive uncertainty only.',
                'Version arms are not compared here because trigger-selected repair cases differ by arm.',
                'Same-assistant pre-repair judgments were consulted for consistent application of the frozen rubric; no blinding claimed.'],
            'new_provider_calls':0,'new_semantic_labels_inferred':0,**counts})
    print(json.dumps({m:{k:r[k] for k in ['selected_answer_pairs','selected_source_projects','project_equal_change',
        'improved_answers','unchanged_answers','lower_answers','answer_transitions']} for m,r in reports.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tag',default=DEFAULT_TAG)
    main(parser.parse_args().tag)
