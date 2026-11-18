"""Expand explicitly authored repair-delta decisions, retaining first grades.

Only inheritance and supplied overrides are performed; no content judging or
score/default inference. Every retained quote is checked against attempt 2.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from review_capstone_all_20261113 import MASTER,ROOT,read,save,sha,source,locate,ingest
from recheck_capstone_authored_evidence_20261113 import main as recheck


def main(path):
    instructions=read(path)
    labels=[];notes=[];bindings=[]
    for instruction in instructions:
        cohort=instruction['cohort'];wid=instruction['window_id'];arm=instruction['arm'];repeat=instruction['repeat']
        assert instruction['all_changed_outward_fields_manually_reviewed'] is True
        assert instruction['unchanged_business_content_inherits_first_review'] is True
        parent=MASTER/'business_review'/cohort/f'{wid}-{arm}-r{repeat}-a1.json'
        grade=read(parent)
        p1,_,first=source(cohort,wid,arm,repeat,1)
        p2,_,repair=source(cohort,wid,arm,repeat,2)
        assert grade['response_sha256']==sha(p1) and repair is not None and first is not None
        changed=sorted(k for k in set(first)|set(repair) if first.get(k)!=repair.get(k))
        assert changed==sorted(instruction['changed_public_fields']), (wid,arm,repeat,changed)
        row={'cohort':cohort,'window_id':wid,'arm':arm,'repeat':repeat,'attempt':2,
             'action':instruction.get('action',grade['annotated_action']),
             'D1':{k:deepcopy(grade['D1'][k]) for k in ['label','quote','reason']},
             'factors':[{k:deepcopy(f[k]) for k in ['id','rating','quote','reason']} for f in grade['factor_ratings']]}
        row['D1'].update(instruction.get('D1_override',{}))
        changes=instruction.get('factor_overrides',{})
        assert set(changes)<=set(f['id'] for f in row['factors'])
        for f in row['factors']:f.update(changes.get(f['id'],{}))
        for value in [row['D1'],*row['factors']]:
            assert not value.get('quote') or locate(repair,value['quote']), (wid,arm,repeat,value)
        labels.append(row)
        notes.append({'cohort':cohort,'window_id':wid,'arm':arm,'repeat':repeat,'attempt':2,
                      'conclusion':'no_change','reason':instruction['recheck_reason']})
        bindings.append({'cohort':cohort,'window_id':wid,'arm':arm,'repeat':repeat,
            'first_grade_path':str(parent.relative_to(ROOT)).replace('\\','/'),'first_grade_sha256':sha(parent),
            'first_response_sha256':sha(p1),'repair_response_sha256':sha(p2),'changed_public_fields':changed,
            'outward_equal_except_repair_explanation':{k:v for k,v in first.items() if k!='repair_explanation'}==
                                                     {k:v for k,v in repair.items() if k!='repair_explanation'}})
    labelpath=path.with_name(path.stem+'_expanded_labels.json')
    notepath=path.with_name(path.stem+'_expanded_rechecks.json')
    save(labelpath,labels);save(notepath,notes)
    ingest(labelpath);recheck(notepath)
    save(path.with_name(path.stem+'_source_bindings.json'),{'authored_instructions_sha256':sha(path),
        'expanded_labels_sha256':sha(labelpath),'expanded_rechecks_sha256':sha(notepath),'rows':bindings,
        'identity':'Explicit same-author repair-delta review plus inherited judgments on unchanged outward content; not an independent review or automated semantic score.',
        'new_provider_calls':0,'first_scores_changed':False})
    print({'saved_authored_repair_delta_reviews':len(labels)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('instructions',type=Path);main(p.parse_args().instructions)
