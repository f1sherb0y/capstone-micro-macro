"""Persist explicit supplemental preference rechecks; never infer a vote."""
from pathlib import Path
from review_capstone_cp01_pairs_20261113 import OUT,packet
from review_capstone_all_20261113 import MASTER,ROOT,read,save,sha,locate


def main():
    authored=MASTER/'manual_labels/CP01_pair_preference_recheck_001.json'
    notes=read(authored);assert len(notes)==36 and len({n['pair_id'] for n in notes})==36
    records=[]
    for note in notes:
        assert note['conclusion']=='no_change' and note['reason'].strip()
        path=OUT/'judgments'/f"{note['pair_id']}.json";r=read(path);p=packet(note['pair_id'])
        assert r['origin']=='explicit_pair_preference_after_individual_grading'
        assert note['expected_preference']==r['preferred_source_arm']
        assert r['packet_sha256']==sha(OUT/'packets'/path.name)
        for e in r['evidence']:
            answer=next(a for a in p['answers_in_frozen_order'] if a['label']==e['label'])
            assert e['source_arm']==answer['source_arm']
            assert locate(answer['outward'],e['quote'])==e['location']
        record={**note,'judgment_sha256':sha(path),'packet_sha256':r['packet_sha256'],
            'authored_recheck_sha256':sha(authored),'complete':True,
            'reviewer':'Same design-participating author-assisting AI; neither independent nor blinded.',
            'new_model_calls':0}
        save(OUT/'rechecks'/path.name,record);records.append({'pair_id':note['pair_id'],
            'recheck_sha256':sha(OUT/'rechecks'/path.name)})
    selected=[]
    for path in sorted((OUT/'judgments').glob('*.json')):
        r=read(path)
        if not r['origin'].startswith('retained_original'):continue
        original=ROOT/r['authored_source_path'];assert sha(original)==r['authored_source_sha256']
        second=original.with_name(original.name.replace('-round1.json','-round2.json'))
        assert second.exists()
        old=read(original);swapped=read(second)
        assert old['preferred_source_arm']==swapped['preferred_source_arm']==r['preferred_source_arm']
        selected.append({'pair_id':r['pair_id'],'original_sha256':sha(original),'original_round2_sha256':sha(second)})
    assert len(selected)==12
    crosswalk=OUT/'retained_reason_label_crosswalk_001.json'
    save(OUT/'evidence_audit_001.json',{'new_supplemental_rechecks':36,'retained_original_order_checks':12,
        'new_preference_changes':0,'initial_dimension_score_changes':0,
        'all48_pairs_order_swapped':False,'supplemental_rechecks':records,
        'retained_original_checks':selected,'retained_reason_label_crosswalk_sha256':sha(crosswalk),
        'limitations':['Same assistant reread of evidence, not additional independent judgments.',
            'Quote/source validation only verifies traceability; semantic conclusions are explicitly authored in notes.'],
        'new_model_calls':0})
    print('36 explicit supplemental rechecks sealed;12 original order checks retained;no vote or initial score changes.')


if __name__=='__main__':main()
