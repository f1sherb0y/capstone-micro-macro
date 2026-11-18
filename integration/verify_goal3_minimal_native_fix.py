"""Run fixed GOAL 3 interface-closure business cases and correlate real outcomes.

No state changes, processor replay or native function replacements occur in
verification. Full cross-batch integration remains GOAL 4.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.contractor_tender_development import verify_bundle, _write
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid
from integration.verify_tender_award_review import run_scenario as run_selection, verify_scenario as verify_selection
from integration.verify_financing_chain import run_scenario as run_financing
from src.coordination.tasks import TaskIdentity, task_digest


def macro_snapshot():
    baseline=read(ROOT/'output/integration/implementation_20261016_01/macro_baseline.json')
    root=ROOT/baseline['root']
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in baseline['files']}
    python={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*.py') if '__pycache__' not in p.parts}
    return {'root':baseline['root'],'files':files,'python_sources':python}


def save_or_match(directory, name, value):
    path=directory/name
    if path.exists():
        require(read(path)==value,'Saved verification differs; preserve it and use a new output directory: '+str(path))
    else:
        _write(directory,name,value)


def verify_financing_case(directory, *, expected_choice):
    verify_bundle(directory/'input')
    require(read(directory/'exit.json')['exit_code']==0,'Original financing process failed')
    initial=read(directory/'input/macro-request.json')
    require(not initial['initial_projects'],'Financing project outcomes cannot be prefilled')
    simulation=read(directory/'runtime/result.json')['simulation']
    require(simulation['status']=='completed' and simulation['current_tick']==2,'Incomplete actual financing window')
    events={e['event_id']:e for p in simulation['project_results'] for e in p['event_log']}
    require(not any(e['data'].get('agent_observer_errors') for e in events.values()),'Feedback observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM owner_financing_results')]
        parents=[json.loads(v) for k,v in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'owner_financing_native_request:%'")]
    require(len(parents)==4 and len(workers)==4,'Expected four original Owner decisions')
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Changed or incomplete durable task')
    by_key={TaskIdentity(**t['identity']).key:t for t in tasks}
    saved={TaskIdentity(**r['identity']).key:r for r in workers}
    proofs=[];later=[]
    for parent in parents:
        digest_valid(parent);scope=parent['scope'];key=TaskIdentity(**parent['identity']).key
        original=saved[key];digest_valid(original)
        require(original['result']['kind']=='completed' and original['result_sha256']==parent['result_sha256']==task_digest(original['result'])
            and original['source_reading_sha256']==task_digest(original['source_reading'])
            and by_key[key]['output']==original['result'],'Original micro result/source correspondence changed')
        choice=original['result']['payload']['choice']
        require(choice==expected_choice,'Unexpected actual Owner choice: '+choice)
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose'
            and t['identity']['action_id']=='select_financing_offer'
            and t['output'].get('factors',{}).get('native_financing_scope')==scope,'Missing exact original proposal')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide'
            and t['identity']['action_id']=='owner_financing_selection'
            and t['output'].get('data',{}).get('native_financing_scope')==scope,'Missing exact original final decision')
        require(task_digest(proposal['output'])==parent['proposal_response_sha256']==final['output']['data']['proposal_response_sha256'],
            'Final response differs from original micro proposal')
        accepted=choice!='no_finance';mode={'no_finance':'unfinanced','own_funds':'owner_equity','accept_offer':'bank_finance'}[choice]
        kind='project_financing_selected' if accepted else 'project_financing_deferred'
        event=one(list(events.values()),lambda e:e['project_id']==scope['project_id']
            and e['tick']==scope['tick'] and e['event_type']==kind,'Missing actual native financing outcome')
        data=event['data'];project=one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Missing original project')
        require(proposal['output']['accepted'] is accepted and final['output']['decision'] is accepted
            and data['accepted'] is accepted and data['financing_mode']==mode
            and data['micro_task_key']==key and data['micro_result_sha256']==original['result_sha256']
            and data['proposal_response_sha256']==parent['proposal_response_sha256'],'Original macro did not execute the same micro decision')
        require(final['output']['data']['selected_bank_id']==proposal['output']['data']['selected_bank_id']==data['selected_bank_id']==project['selected_bank_id'],
            'Macro bank commitment differs from the actual original choice')
        banks=[e for e in events.values() if e['project_id']==scope['project_id'] and e['tick']==scope['tick']
            and e['event_type']=='bank_financing_decision' and e['data'].get('accepted') is True]
        require(banks,'Cases must exercise real accepted bank candidates, including equity/refusal')
        if not accepted:
            require(project['current_stage']=='initiation' and project['stage_tick']==0
                and not any(e['event_type']=='project_financing_selected' for e in project['event_log'])
                and not project['engagements'] and not project['contracts'],'Refusal created a commitment or advanced lifecycle')
        preference=parent['observed']['feedback_preference']
        history=preference['history'];require(len(history)==int(scope['tick']==2),'Later Owner lost its earlier actual outcome')
        for previous in history:
            prior=events[previous['event_id']]
            require(previous['owner_id']==scope['owner_id']==previous['recipient_organization_id']
                and previous['tick']<scope['tick'] and prior['data']['micro_task_key']==previous['micro_task_key']
                and previous['micro_result_sha256']==saved[previous['micro_task_key']]['result_sha256']==prior['data']['micro_result_sha256']
                and previous['financing_mode']==mode,'Later source changes the original actual outcome or scope')
            later.append({'consumer_task_key':key,'consumer_tick':scope['tick'],'event_id':prior['event_id'],
                'event_sha256':task_digest(prior),'source_micro_task_key':previous['micro_task_key']})
        refusal_count=sum(h['financing_mode']=='unfinanced' for h in history)
        require(preference['prior_refusal_count']==refusal_count,'Refusal count differs from actual earlier feedback')
        priorities=[]
        for row in preference['priorities']:
            expected=row['base_priority']+preference['repeat_lender_priority_penalty']*row['earlier_selection_count']+preference['prior_refusal_priority_penalty']*refusal_count
            require(row['priority']==expected,'Actual feedback did not enter declared preference calculation')
            disclosure=one(parent['native_request']['inputs']['offers'],lambda pair:pair[0]['agent_id']==row['bank_id'],'Lost bank disclosure')
            require(disclosure[1]['accepted'],'Preference includes a refused bank')
            offer=one(original['source_reading'],lambda s:s['ref']['kind']=='FinanceOffer'
                and s['projection']['lender_id']==row['bank_id'],'Priority never entered original micro reading')['projection']
            require(offer['priority']=={'state':'known','value':expected},'Original micro source lost feedback-based priority')
            priorities.append({'bank_id':row['bank_id'],'base_priority':row['base_priority'],'actual_priority':expected})
        proofs.append({'scope':scope,'micro_task_key':key,'micro_result_sha256':original['result_sha256'],
            'micro_choice':choice,'source_reading_sha256':original['source_reading_sha256'],
            'proposal_sha256':parent['proposal_response_sha256'],'final_sha256':task_digest(final['output']),
            'event_id':event['event_id'],'event_sha256':task_digest(event),'financing_mode':mode,
            'accepted_bank_count':len(banks),'prior_refusal_count':refusal_count,'priorities':priorities})
    require(len(later)==2,'Missing both later own consumers')
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Verification wrote the original journal')
    return {'status':'passed','simulation_id':simulation['simulation_id'],'expected_micro_choice':expected_choice,
        'decisions':proofs,'later_consumers':later,'journal_read_only':True,
        'boundary':'Bank selection, equity and refusal are native aggregate outcomes. No formal loan, drawdown or cash settlement is inferred.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/goal3_minimal_native_fix.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve();config=read(args.config)
    require(config['schema_version']=='goal3-minimal-native-fix.v1','Unknown fixed configuration')
    if (directory/'source-config.json').exists():
        require(read(directory/'source-config.json')==config,'Fixed configuration differs from this saved run')
    before=macro_snapshot()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',before)
        run_selection(directory/'selection',**config['selection'])
        for name,case in config['financing'].items():
            case_dir=directory/('financing-'+name);case_dir.mkdir(exist_ok=False)
            _write(case_dir,'scenario.json',case);run_financing(case_dir,case)
        from integration.professional_construction_development import build_bundle as build_construction
        from integration.verify_professional_monthly_chain import run_existing_input
        construction=directory/'construction-guard';construction.mkdir(exist_ok=False)
        construction_config=read(ROOT/config['construction_config'])
        _write(construction,'source-config.json',construction_config);_write(construction,'macro-before.json',before)
        build_construction(construction/'construction/input',run_id=construction_config['run_id'],config=construction_config)
        run_existing_input(construction/'construction',assembly_hook='integration.professional_construction_feedback:configure_assembly')
    selection=verify_selection(directory/'selection',accepted=True)
    require(selection['winner_override_supported'] and selection['proposal_candidate']!=selection['actual_selected_contractor_id'],
        'Fixed scenario did not demonstrate an independently authorized changed selection')
    financing={name:verify_financing_case(directory/('financing-'+name),expected_choice={
        'normal':'accept_offer','equity':'own_funds','limited_cash':'no_finance'}[name]) for name in config['financing']}
    require(all(read(directory/('financing-'+name)/'scenario.json')==case
        for name,case in config['financing'].items()),'Configured financing inputs differ from the saved cases')
    initial=[read(directory/('financing-'+name)/'input/macro-request.json') for name in config['financing']]
    require(all(value==initial[0] for value in initial),'Controlled financing cases changed native inputs')
    require(macro_snapshot()==before,'Macro code changed during business verification')
    from integration.verify_professional_construction_feedback import verify as verify_construction
    construction=verify_construction(directory/'construction-guard',macro_snapshot_reader=macro_snapshot)
    require(not any('engagement_status' in e['data'].get('reason','') for e in construction['native_execute_work_invalid_actions']),
        'Shared diagnostic still rejects its own redundant engagement state field')
    save_or_match(directory/'construction-guard','checks.json',construction)
    checks={'status':'passed_fixed_selection_and_financing_closures','selection':selection,'financing':financing,
        'construction_guard_and_actual_feedback':construction,
        'controlled_native_inputs_equal':True,'macro_unchanged_during_this_check':True,
        'claims_overall_goal3_completion':False,'goal4_started':False,
        'remaining_acceptance':'Shared validation guard coverage, full action inventory, allowed macro differences and preserved historical evidence require final review.'}
    save_or_match(directory,'interface-closure-final-checks.json',checks)
    save_or_match(directory,'source-config.json',config)
    print(json.dumps({'status':checks['status'],'output':str(directory),'claims_overall_goal3_completion':False}))


if __name__=='__main__':
    main()
