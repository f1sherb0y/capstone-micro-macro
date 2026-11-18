"""Append explicit evidence-based revisions without replacing initial judgments."""
from copy import deepcopy
import argparse
from pathlib import Path

from review_capstone_all_20261113 import MASTER, ROOT, read, save, sha, source, evidence


def effective_review(path):
    initial=read(path)
    revisions=sorted((MASTER/'business_revision'/initial['cohort']/path.stem).glob('revision-*.json'))
    current=initial
    for index, p in enumerate(revisions,1):
        record=read(p)
        assert p.name==f'revision-{index:03d}.json'
        assert record['initial_record_sha256']==sha(path)
        assert record['response_sha256']==initial['response_sha256']
        assert record['previous_revision_sha256']==(sha(revisions[index-2]) if index>1 else None)
        assert record['evidence_recheck_complete'] and record['revision_reason'].strip()
        current=record['effective_record']
    return current,revisions


def append(path):
    notes=read(path)
    prepared=[]
    for note in notes:
        c,w,a,r,t=[note[k] for k in ['cohort','window_id','arm','repeat','attempt']]
        initial_path=MASTER/'business_review'/c/f'{w}-{a}-r{r}-a{t}.json'
        initial=read(initial_path)
        current,previous=effective_review(initial_path)
        raw,_,payload=source(c,w,a,r,t)
        assert sha(raw)==initial['response_sha256'] and isinstance(payload,dict)
        assert note['reason'].strip() and note['recheck_reason'].strip()
        corrected=deepcopy(current)
        for change in note['changes']:
            kind=change['kind']
            if kind=='factor':
                own=next(f for f in corrected['factor_ratings'] if f['id']==change['id'])
                assert own['rating']==change['previous']
                assert change['rating'] in {'correct','partial','missing','contradicted','not_judgable'}
                own.update(rating=change['rating'],quote=change['quote'],reason=change['reason'])
                own['evidence']=evidence(payload,own,permit_absence=change['rating'] in {'missing','not_judgable'})
            elif kind=='detailed':
                assert change['id'] in {'D3','D4'}
                own=corrected['detailed'][change['id']]
                assert own['score']==change['previous'] and change['score'] in {0,1,2}
                own.update(score=change['score'],quote=change['quote'],reason=change['reason'])
                own['evidence']=evidence(payload,own)
            else: raise ValueError('Unsupported revision type')
        corrected['D2_correct_coverage']=sum(f['rating']=='correct' for f in corrected['factor_ratings'])/len(corrected['factor_ratings'])
        for value in [corrected['D1'],*corrected['factor_ratings'],*corrected['detailed'].values()]:
            assert value['evidence']==evidence(payload,value,permit_absence=value.get('rating') in {'missing','not_judgable'})
        target=MASTER/'business_revision'/c/initial_path.stem/f'revision-{len(previous)+1:03d}.json'
        record={k:note[k] for k in ['cohort','window_id','arm','repeat','attempt']}
        record.update(initial_record_path=str(initial_path.relative_to(ROOT)),initial_record_sha256=sha(initial_path),
            response_sha256=sha(raw),previous_revision_sha256=sha(previous[-1]) if previous else None,
            authored_notes_path=str(path.relative_to(ROOT)),authored_notes_sha256=sha(path),
            revision_reason=note['reason'],changes=note['changes'],evidence_recheck_reason=note['recheck_reason'],
            evidence_recheck_complete=True,effective_record=corrected,
            reviewer='same design-participating assistant; correction of own rating, not independent review',new_model_calls=0)
        prepared.append((target,record))
    for target,record in prepared: save(target,record)
    print(f'Appended {len(prepared)} explicit revisions; all initial judgments retained.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('authored_notes',type=Path);append(p.parse_args().authored_notes)
