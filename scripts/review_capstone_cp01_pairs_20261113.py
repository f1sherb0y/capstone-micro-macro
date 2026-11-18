"""Frozen CP02 A/B inputs, actual CP01 sources, and explicitly authored preferences."""
import argparse
import json
from pathlib import Path

from review_capstone_all_20261113 import MASTER, ROOT, cards, source, locate, read, save, sha
from capstone_cp_common_20261112 import CP02

OUT=MASTER/'pair_preferences/CP01_001'


def prepare():
    original=read(CP02/'pair_inputs.json')
    mapping=read(CP02/'ab_mapping.json')
    card_path,by_id=cards('CP01')
    index_path=MASTER/'response_index_CP01_first_review_complete_001.json'
    planned=[r for r in read(index_path)['rows'] if r['cohort']=='CP01' and r['repeat']==1]
    pairs=[]
    for item in original:
        pid,wid=item['pair_id'],item['window_id']
        own=sorted([r for r in mapping if r['pair_id']==pid],key=lambda r:r['label'])
        assert [r['label'] for r in own]==['A','B']
        card=by_id[wid]; answers=[]
        for m in own:
            slot=next(r for r in planned if r['window_id']==wid and r['arm']==m['arm'])
            answer={'label':m['label'],'source_arm':m['arm'],'read_state':slot['review_state']}
            if slot['readable_outward_json']:
                raw,_,payload=source('CP01',wid,m['arm'],1,1)
                gp=MASTER/'business_review/CP01'/f"{wid}-{m['arm']}-r1-a1.json"
                check=MASTER/'business_recheck/CP01'/gp.name
                grade=read(gp)
                assert read(check)['complete'] and read(check)['initial_record_sha256']==sha(gp)
                assert sha(raw)==slot['response_sha256']==grade['response_sha256']
                answer.update(outward=payload,response_path=str(raw.relative_to(ROOT)),response_sha256=sha(raw),
                    grade_path=str(gp.relative_to(ROOT)),grade_sha256=sha(gp),recheck_path=str(check.relative_to(ROOT)),
                    recheck_sha256=sha(check))
            else:
                assert not slot['raw_available']
                answer.update(outward=None,missing_source_disposition=slot['status'])
            answers.append(answer)
        binding={'pair_id':pid,'window_id':wid,'project_group':card['project_group'],'role':card['role'],
            'variant':card['variant'],'input_card_path':str(card_path.relative_to(ROOT)),'input_card_sha256':sha(card_path),
            'input':{k:card[k] for k in ['role','project_facts','scope_basis','provided_company_fields','conditions','case_specific_attention']},
            'answers_in_frozen_order':answers}
        save(OUT/'packets'/f'{pid}.json',binding)
        pairs.append({'pair_id':pid,'window_id':wid,'role':card['role'],'packet_sha256':sha(OUT/'packets'/f'{pid}.json')})
    assert len(pairs)==48
    save(OUT/'manifest.json',{'pairs':pairs,'original_input_sha256':sha(CP02/'pair_inputs.json'),
        'original_mapping_sha256':sha(CP02/'ab_mapping.json'),'source_index_sha256':sha(index_path),
        'limitations':['Same design-participating assistant has seen labeled outputs and grades; no true blinding.',
            'Only frozen repeat1 first responses, not repairs or repeat2.',
            'Preferences are separately authored; no automatic vote from dimension scores or program status.',
            'Preselected12 initial preferences may be retained with original source hashes, without pretending a fresh review.'],
        'new_model_calls':0})
    print('Bound48 frozen repeat1 pairs to94 readable originals and2 missing slots.')


def packet(pid):
    doc=read(OUT/'manifest.json')
    selected=next(r for r in doc['pairs'] if r['pair_id']==pid)
    path=OUT/'packets'/f'{pid}.json'
    assert sha(path)==selected['packet_sha256']
    p=read(path)
    assert sha(ROOT/p['input_card_path'])==p['input_card_sha256']
    for a in p['answers_in_frozen_order']:
        if a['outward'] is not None:
            for k in ['response','grade','recheck']:
                assert sha(ROOT/a[k+'_path'])==a[k+'_sha256']
    return p


def persist(row,origin,authored_path):
    p=packet(row['pair_id']); preference=row['preference']
    assert preference in {'A','B','tie','not_judgable'}
    assert row['reason'].strip() and row['input_basis'].strip()
    missing=[a for a in p['answers_in_frozen_order'] if a['outward'] is None]
    if missing: assert preference=='not_judgable'
    else: assert {e['label'] for e in row['evidence']}=={'A','B'}
    evidence=[]
    for e in row['evidence']:
        a=next(a for a in p['answers_in_frozen_order'] if a['label']==e['label'])
        assert a['outward'] is not None
        pos=locate(a['outward'],e['quote']); assert pos,'Exact public quote required: '+e['quote']
        evidence.append({**e,'location':pos,'source_arm':a['source_arm']})
    selected=next((a['source_arm'] for a in p['answers_in_frozen_order'] if a['label']==preference),preference)
    record={**row,'window_id':p['window_id'],'role':p['role'],'variant':p['variant'],
        'project_group':p['project_group'],'preferred_source_arm':selected,'evidence':evidence,
        'origin':origin,'authored_source_path':str(authored_path.relative_to(ROOT)),
        'authored_source_sha256':sha(authored_path),'packet_sha256':sha(OUT/'packets'/f"{p['pair_id']}.json"),
        'reviewer':'same design-participating assistant; no independent or true blind review',
        'new_model_calls':0}
    save(OUT/'judgments'/f"{p['pair_id']}.json",record)


def retain_selected():
    old=MASTER/'order_check/CP01_001'
    bindings=read(old/'source_binding.json')['pairs']
    new=read(OUT/'manifest.json')['pairs']
    for b in bindings:
        path=old/'judgments'/f"{b['pair_id']}-round1.json"
        r=read(path)
        assert r['source_binding_sha256']==sha(old/'source_binding.json')
        pid=next(n['pair_id'] for n in new if n['window_id']==b['selection']['window_id'])
        p=packet(pid)
        evidence=[]
        for a in p['answers_in_frozen_order']:
            arm=a['source_arm']
            assert a['response_sha256']==b['answers'][arm]['response_sha256']
            old_label=['A','B'][b['selection']['first_presentation_order'].index(arm)]
            evidence.extend({'label':a['label'],'quote':e['quote']} for e in r['evidence'] if e['label']==old_label)
        preferred=r['preferred_source_arm']
        preference=next((a['label'] for a in p['answers_in_frozen_order'] if a['source_arm']==preferred),preferred)
        persist({'pair_id':pid,'preference':preference,'input_basis':r['input_basis'],'reason':r['reason'],
                 'evidence':evidence},'retained_original_preselected_order_check_first_preference',path)
    print('Retained12 original authored preferences with source equality verified; no new judgments inferred.')


def show(pid):
    p=packet(pid)
    print(json.dumps({'pair_id':pid,'window_id':p['window_id'],'input':p['input'],
        'answers_in_frozen_order':[{k:a[k] for k in ['label','outward','read_state']} for a in p['answers_in_frozen_order']]},ensure_ascii=False))


def ingest(path):
    rows=read(path)
    for r in rows: persist(r,'explicit_pair_preference_after_individual_grading',path)
    print(f'Saved {len(rows)} explicit pair preferences.')


def summarize():
    doc=read(OUT/'manifest.json'); rows=[]
    for selected in doc['pairs']:
        path=OUT/'judgments'/f"{selected['pair_id']}.json"
        if path.exists():
            p=packet(selected['pair_id']); r=read(path)
            assert r['packet_sha256']==selected['packet_sha256']
            assert sha(ROOT/r['authored_source_path'])==r['authored_source_sha256']
            rows.append({k:r[k] for k in ['pair_id','window_id','project_group','role','variant','preferred_source_arm','origin']})
    from collections import Counter
    save(OUT/'summary_001.json',{'planned_pairs':48,'completed_pairs':len(rows),
        'paired_readable_answers':sum(r['preferred_source_arm']!='not_judgable' for r in rows),
        'preferences':dict(Counter(r['preferred_source_arm'] for r in rows)),'rows':rows,
        'independent_pairs_claimed':False,'unit':'Two information conditions within each of24 source projects; raw preferences descriptive.',
        'new_model_calls':0})
    print(len(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--retain-selected',action='store_true')
    p.add_argument('--show');p.add_argument('--ingest',type=Path);p.add_argument('--summarize',action='store_true');a=p.parse_args()
    if a.prepare: prepare()
    elif a.retain_selected: retain_selected()
    elif a.show: show(a.show)
    elif a.ingest: ingest(a.ingest)
    elif a.summarize: summarize()
    else: p.error('Select a packet or explicitly authored judgments')
