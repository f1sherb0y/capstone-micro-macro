"""Run/check the fixed 3A acceptance and budget-refusal scenarios."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import verify_bundle, _write
from integration.tender_award_review_development import build_bundle
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory, *, accepted):
    directory = Path(directory)
    verify_bundle(directory/'input')
    runtime = directory/'runtime'
    result = read(runtime/'result.json')
    simulation = result['simulation']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == (8 if accepted else 4),
            'Scenario did not finish its independently configured native window')
    initial = read(directory/'input/macro-request.json')
    require(all(not p['bids'] and not p['contracts'] and p['selected_contractor_id'] is None
                for p in initial['initial_projects']), 'Actual formal results were prefilled')
    database = runtime/'tasks.sqlite'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        owner = [json.loads(v) for v, in db.execute('SELECT record FROM owner_tender_results')]
        awards = [json.loads(v) for v, in db.execute('SELECT record FROM owner_award_results')]
    require(all(t['state'] == 'output_formed' for t in tasks), 'Unresolved technical task in purported normal business')
    review = one([v for k,v in metadata.items() if k.startswith('owner_selection_review:')],
        lambda r:True,'Expected one actual Owner selection review')
    digest_valid(review)
    require(review['state'] == 'formed' and review['accepted'] is accepted,
            'Owner review final decision differs from its saved original work')
    native = review['native_request']
    require(task_digest(native) == review['request_sha256'], 'Native decision request changed')
    original = one(owner,lambda r:r['identity'] == review['identity'],'Missing original OWN-A09 result')
    digest_valid(original)
    require(original['result']['kind'] == 'completed' and original['result']['payload']['choice'] == 'evaluate'
        and original['result_sha256'] == review['result_sha256'] == task_digest(original['result'])
        and original['source_reading_sha256'] == task_digest(original['source_reading']),
        'Original Owner action/result/source reading lost its correlation')
    key = TaskIdentity(**review['identity']).key
    selecting=review.get('selection_mode','review_native')=='lowest_eligible_price'
    action = one(tasks,lambda t:TaskIdentity(**t['identity']).key == key,'Missing durable original action')
    final = one(tasks,lambda t:t['identity']['purpose'] == 'decide'
        and t['identity']['action_id'] == 'owner_preferred_bidder_selection','Missing actual final decision')
    require(action['output'] == original['result'] and action['output_sha256'] == review['result_sha256']
        and final['output']['decision'] is accepted
        and final['output']['data']['micro_task_key'] == key
        and final['output']['data']['micro_result_sha256'] == review['result_sha256']
        and (final['output']['data'].get('selected_contractor_id')==review['native_candidate'] if selecting
             else 'selected_contractor_id' not in final['output']['data']), 'Final transport substituted result or candidate')
    funding = one(original['source_reading'],lambda r:r['ref']['kind'] == 'FundingPosition','Missing funding calculation source')
    budget = funding['projection']['authorized_limit']['value']['value']
    require(budget == ('1000' if accepted else '80'), 'Wrong independent authorized budget source')
    bids = [r for r in original['source_reading'] if r['ref']['kind'] == 'Bid']
    require(len(bids) == 2 and {r['projection']['total_price']['value']['value'] for r in bids} == {'110.0'},
            'Review did not use both actual submitted prices')
    evidence = one(original['source_reading'],lambda r:r['projection'].get('locator') ==
        'actual-native-owner-selection-review','Missing current native input provenance')
    require(evidence['projection']['content_hash'] == review['request_sha256'], 'Review sources lost actual request provenance')
    payload = original['result']['payload']
    require(len(payload['ranked_bid_refs']) == (2 if accepted else 0)
        and len(payload['rejected_bid_refs']) == (0 if accepted else 2), 'Original budget filter did not affect admissibility')
    require(len(original['audit']['method_calls']) == int(accepted),
            'Expected original comparison only when bids pass original funding constraint')
    project, = simulation['project_results']
    events = project['event_log']
    submissions = [e for e in events if e['event_type'] == 'bid_submitted']
    require(len(submissions) == 2 and all(e['tick'] < native['tick'] for e in submissions),
            'Review sources must follow two actual native submissions')
    event = one(events,lambda e:e['event_type'] == ('bid_evaluation_completed' if accepted else 'bid_evaluation_deferred'),
        'Missing actual native evaluation outcome')
    decision = event['data']['owner_decision']
    require(decision['accepted'] is accepted and decision['micro_task_key'] == key
        and decision['micro_result_sha256'] == review['result_sha256']
        and decision['choice_source'] == ('llm_agent' if selecting else 'bounded_evidence_default'),
        'Macro did not process the actual review or bounded micro choice')
    consumers = []
    if accepted:
        require(project['selected_contractor_id'] == review['native_candidate']
            and project['flags'].get('contract_signed') and len(project['contracts']) == 1,
            'Native candidate did not reach actual signature')
        formation = one([v for k,v in metadata.items() if k.startswith('contractor_formation_native_request:')],
            lambda r:True,'Missing downstream actual Contractor A04 consumer')
        selection = formation['observed']['actual_original_tender']['own_selection']
        require(selection['event_id'] == event['event_id'] and selection['source_event_sha256'] == task_digest(event),
                'Later A04 did not authenticate this exact actual selection event')
        owner_accept = one(awards,lambda r:True,'Missing original Owner A10')
        require(owner_accept['result']['payload']['choice'] == 'accept', 'Original Owner did not independently accept')
        consumers.append({'action_id':'CONTRACTOR-A04','identity':formation['identity'],
            'selection_event_id':selection['event_id'],'selection_event_sha256':selection['source_event_sha256']})
    else:
        require(project['selected_contractor_id'] is None and not project['contracts']
            and not project['flags'].get('contract_signed') and not awards,
            'Budget refusal created a selection, award or contract')
    require(before == hashlib.sha256(database.read_bytes()).hexdigest(), 'Read-only verification changed the journal')
    return {'status':'passed','simulation_id':simulation['simulation_id'],'actual_ticks':simulation['current_tick'],
        'budget_HKD':budget,'actual_bid_prices':['110.0','110.0'],'accepted':accepted,
        'micro_identity':review['identity'],'micro_task_key':key,'micro_result_sha256':review['result_sha256'],
        'source_reading_sha256':original['source_reading_sha256'],'native_request_sha256':review['request_sha256'],
        'original_comparison_calls':len(original['audit']['method_calls']),
        'macro_outcome':event,'actual_later_consumers':consumers,'contracts':project['contracts'],
        'journal_read_only':True,'all_tasks_formed':True,'winner_override_supported':selecting,
        'proposal_candidate':review.get('proposal_candidate',review['native_candidate']),
        'actual_selected_contractor_id':project['selected_contractor_id']}


def run_scenario(directory, *, run_id, authorized_budget, ticks,
        selection_mode='review_native',selection_tie_break='wait'):
    directory = Path(directory)
    build_bundle(directory/'input',run_id=run_id,authorized_budget=authorized_budget,ticks=ticks,
        selection_mode=selection_mode,selection_tie_break=selection_tie_break)
    args = [sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.contractor_tender_formation_development:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        completed = subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':completed.returncode})
    require(completed.returncode == 0,'Native run failed; inspect preserved stderr.log and original journal')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/tender_award_review.json')
    parser.add_argument('--check-only',action='store_true')
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'macro-before.json',macro_hashes())
        config = read(args.config)
        for name,scenario in config['scenarios'].items():
            run_scenario(directory/name,run_id=config['run_id']+'-'+name,**scenario)
    normal = verify_scenario(directory/'normal',accepted=True)
    refusal = verify_scenario(directory/'budget_refusal',accepted=False)
    a,b = [read(directory/name/'input/macro-request.json') for name in ('normal','budget_refusal')]
    require(a['agents'] == b['agents'] and a['initial_projects'] == b['initial_projects'],
        'Budget comparison changed initial native enterprise or project inputs')
    frozen = macro_hashes()
    checks = {'batch':'3A','status':'passed_for_bounded_review',
        'normal':normal,'budget_refusal':refusal,'controlled_native_inputs_equal':True,
        'macro':frozen,'overall_goal3_complete':False,
        'remaining_blocker':'External preferred-bidder proposal requires and forbids selected_contractor_id; Boolean review cannot override native winner.'}
    if not args.check_only:
        _write(directory,'checks.json',checks)
    print(json.dumps({'status':'passed_for_bounded_review','output':str(directory),'macro_unchanged_files':frozen['file_count']}))


if __name__ == '__main__':
    main()
