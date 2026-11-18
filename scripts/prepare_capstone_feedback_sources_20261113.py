"""Seal fixed R/r1 CP04 source slots without executing a feedback intervention.

Only completed, verified chains are read. No provider/client, processor, native
engine or writable task store is instantiated. Unavailable sources stay pending.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from review_capstone_all_20261113 import ROOT, BASE, MASTER, read, save, sha
from src.coordination.tasks import TaskIdentity

CATALOGUE=MASTER/'macro_results/first_fixed_block_001/all324_planned_catalogue.json'
CONDITIONS=('none','actual_own_settlement','changed_content_same_count')
REGIONS=('permitted','restricted')


def select_events(events, owner, case):
    settlements=[e for e in events if e.get('event_type')=='final_account_settled'
        and e.get('project_id')==case and e.get('data',{}).get('owner_id')==owner]
    if not settlements:
        return [], []
    first=min(e['tick'] for e in settlements)
    decisions=[(i,e) for i,e in enumerate(events) if e.get('tick',0)>first
        and e.get('agent_id')==owner
        and e.get('data',{}).get('decision_factors',{}).get('micro_action_id')=='OWN-A03'
        and e.get('data',{}).get('decision_factors',{}).get('micro_task_key')]
    # Original event sequence resolves ties; no selection by outcome or region.
    decisions.sort(key=lambda x:(x[1]['tick'],x[0]))
    return settlements,[e for _,e in decisions[:2]]


def bind_source(entry, target):
    chain=ROOT/entry['formal_chain_directory']
    batch=chain.parent.parent
    outcomes_path=batch/'run/outcomes.json'
    outcomes=read(outcomes_path) if outcomes_path.exists() else []
    matching=[r for r in outcomes if r['chain_id']==entry['chain_id']]
    if not matching:
        return {'state':'pending_fixed_R_r1_terminal_source','windows':[]}
    assert len(matching)==1
    outcome=matching[0]
    if not (outcome.get('verification') or {}).get('technical_integrity_passed'):
        return {'state':'terminal_source_not_verified_not_replayed','windows':[]}
    assert outcome['exit_code']==0
    document_path=chain/'input/bound-declarations/11-owner-opportunity-input.json'
    native_path=chain/'runtime/native-run-state.json'
    db_path=chain/'runtime/tasks.sqlite'
    document=read(document_path)
    assert len(document['policies'])==1
    policy=document['policies'][0];owner=policy['organization_id']
    events=read(native_path)['original_global_events']
    settlements,selected=select_events(events,owner,entry['case_id'])
    source_dir=target/'sources'/entry['case_id']
    save(source_dir/'verified_outcome_snapshot.json',outcome)
    pins={str(p.relative_to(ROOT)):sha(p) for p in [document_path,native_path,db_path]}
    result={'state':'source_windows_bound_replay_oracle_and_runner_pending',
        'source_file_sha256':pins,'owner_id':owner,'windows':[],
        'actual_own_settlement_event_ids':[e['event_id'] for e in settlements],
        'verified_outcome_snapshot_sha256':sha(source_dir/'verified_outcome_snapshot.json')}
    if not settlements:
        result['state']='fixed_R_r1_has_no_actual_own_settlement_no_substitution'
        return result
    con=sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        rows=[(key,json.loads(raw)) for key,raw in con.execute(
            "select key,value from metadata where key like 'owner_opportunity_native_request:%'")]
    finally:
        con.close()
    event_by_id={e['event_id']:e for e in events if e.get('event_id')}
    for ordinal,event in enumerate(selected,1):
        key=event['data']['decision_factors']['micro_task_key']
        matches=[(k,r) for k,r in rows if r.get('investment',{}).get('identity')
            and TaskIdentity(**r['investment']['identity']).key==key]
        assert len(matches)==1,(entry['chain_id'],key,len(matches))
        metadata_key,row=matches[0]
        assert row['scope']['owner_id']==owner and row['scope']['tick']==event['tick']
        accounts=row['observed']['own_final_accounts']
        assert accounts['organization_id']==owner and accounts['role']=='Owner'
        assert accounts['as_of_tick']==event['tick']
        observed=accounts['settlements']
        assert any(s['project_id']==entry['case_id'] for s in observed)
        for s in observed:
            actual=event_by_id[s['event_id']]
            assert actual['event_type']=='final_account_settled'
            assert actual['data']['owner_id']==owner and actual['tick']<event['tick']
            assert actual['project_id']==s['project_id'] and actual['tick']==s['tick']
            assert actual['data']['final_account_amount']==s['final_account_amount']
        packet={'identity':'actual_source_only_not_feedback_replay_result',
            'case_id':entry['case_id'],'source_chain':entry['chain_id'],
            'ordinal':ordinal,'native_event':event,'metadata_key':metadata_key,
            'metadata_record':row,'source_policy':policy,
            'original_template':document['template'],'source_file_sha256':pins}
        packet_path=source_dir/f'window-{ordinal}.json';save(packet_path,packet)
        result['windows'].append({'ordinal':ordinal,'consumer_tick':event['tick'],
            'decision_event_id':event['event_id'],'micro_task_key':key,
            'packet_path':str(packet_path.relative_to(ROOT)),'packet_sha256':sha(packet_path),
            'actual_settlement_count':len(observed),
            'source_region':row['native_request']['inputs']['opportunity']['region'],
            'source_initiation_regions':policy.get('initiation_region_ids'),
            'source_count_threshold':policy.get('max_prior_final_accounts')})
    if len(selected)<2:
        result['state']='fixed_R_r1_insufficient_later_windows_no_substitution'
    return result


def main(tag):
    target=MASTER/'feedback_preparation'/tag
    assert not target.exists(),'Use a new immutable preparation snapshot tag'
    catalogue=read(CATALOGUE)
    entries=[r for r in catalogue if r['arm']=='R' and r['repeat']==1]
    assert len(entries)==27 and len({r['case_id'] for r in entries})==27
    projects=[];slots=[]
    for entry in entries:
        config_path=ROOT/entry['config_path']
        assert sha(config_path)==entry['config_sha256']
        binding=bind_source(entry,target)
        projects.append({**{k:entry[k] for k in ['batch','case_id','project_group','macro_family_id',
            'scope_stratum','source_region','source_project_name','chain_id','config_path','config_sha256']},
            **binding})
        by_ordinal={w['ordinal']:w for w in binding['windows']}
        for ordinal in (1,2):
            for region in REGIONS:
                for condition in CONDITIONS:
                    window=by_ordinal.get(ordinal)
                    slots.append({'case_id':entry['case_id'],'source_chain':entry['chain_id'],
                        'opportunity_ordinal':ordinal,'region_condition':region,
                        'feedback_condition':condition,
                        'state':'source_bound_not_replayed' if window else binding['state'],
                        'source_packet_sha256':window['packet_sha256'] if window else None,
                        'replay_executed':False})
    assert len(slots)==324
    save(target/'projects.json',projects);save(target/'planned_slots.json',slots)
    summary={'at_UTC':datetime.now(timezone.utc).isoformat(),'phase':'source_preparation_only',
        'fixed_source_chain':'R repeat=1; no alternate arm/repeat substitution',
        'selection_rule':'First two actual OWN-A03 native decision events strictly after the source project own final-account settlement, ordered by tick and original global-event sequence; bind their exact task keys, not another candidate opportunity from the same tick.',
        'source_project_count':27,'planned_replay_slots':324,
        'bound_source_windows':sum(len(p['windows']) for p in projects),
        'project_state_counts':dict(Counter(p['state'] for p in projects)),
        'replays_executed':0,'model_calls':0,'macro_submissions':0,
        'counterfactual_rule':'Future declared copies only: none removes own settlements; actual preserves actual count/content; amount control changes only monetary amount holding count and other facts fixed. Region controls are configured permitted/restricted values. No original record will be edited.',
        'remaining_before_replay':['Wait for all fixed source chains to be disposed under macro execution order.',
            'Bind later sources and preserve scientific missing windows without substitution.',
            'Seal exact region/amount interventions, applicability and expected action oracles before any CP04 replay output.',
            'Implement and verify isolated zero-provider replay runner using existing production processor.'],
        'identity':'Native simulated source evidence and planned deterministic feedback interventions; not real settlements, learned LLM adaptation, or completed F1/F2 validation.',
        'sha256':{'catalogue':sha(CATALOGUE),'runner':sha(__file__),
            'v4':sha(BASE/'2026-11-12_Capstone完整实验与论文方案_v4.md'),
            'projects':sha(target/'projects.json'),'planned_slots':sha(target/'planned_slots.json')}}
    save(target/'manifest.json',summary)
    print(json.dumps({k:summary[k] for k in ['source_project_count','planned_replay_slots',
        'bound_source_windows','project_state_counts','replays_executed','model_calls']},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tag',required=True)
    main(parser.parse_args().tag)
