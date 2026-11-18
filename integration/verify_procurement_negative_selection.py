"""Ordinary original CLI acceptance of negative A05 selection and later consumption."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from integration.contractor_tender_development import _write, verify_bundle
from integration.procurement_negative_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest
from src.actions.roles.contractor_negative_selection import WAIT, REPEATED_WAIT


def verify_scenario(directory, *, refused):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original procurement failed; preserve journal and inspect stderr')
    result=read(directory/'runtime/result.json');sim=result['simulation'];host=result['module_host_extension']['host']
    require(sim['status']=='completed' and sim['current_tick']==2,'Original two-tick scenario incomplete')
    projects=sim['project_results'];events=[e for p in projects for e in p['event_log']]
    failures=[e for e in events if e['event_type']=='supplier_selection_failed']
    selections=[e for e in events if e['event_type']=='supplier_selected']
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Actual event consumer failed')
    require((len(failures),len(selections))==((3,0) if refused else (0,2)),'Native outcomes differ from fixed scenario')
    records=host['supplier']['contractor']['requests'];followups=host['failure_followup']['requests']
    require(len(records)==(3 if refused else 2) and len(followups)==len(failures),'Missing micro decision or committed-failure consumer')
    dbpath=directory/'runtime/tasks.sqlite';before=file_hash(dbpath)
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_planning_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
    key=lambda i:TaskIdentity(**i).key
    tm={key(t['identity']):t for t in tasks};wm={key(w['identity']):w for w in workers}
    plans=read(directory/'input/contractor-negative-input.json')['plans'];proofs=[]
    for record in records:
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Decision export differs from durable record')
        identity=record['identity'];worker=wm[key(identity)];digest_valid(worker)
        require(worker['result_sha256']==task_digest(worker['result'])==record['result_sha256']
            and worker['source_reading_sha256']==task_digest(worker['source_reading']),'Original A05 result or reading changed')
        task=tm[key(identity)];snapshot=snapshots[key(identity)];digest_valid(snapshot,'snapshot_sha256')
        require(identity['input_sha256']==task_digest(snapshot['action_input']) and identity['context_sha256']==task_digest(snapshot['context']),
            'Original A05 invocation changed')
        plan=one(plans,lambda p:(p['organization_id'],p['project_id'],p['tick'])==
            (identity['organization_id'],record['scope']['project_id'],record['scope']['tick']),'No exact initial selection plan')
        placeholder=one(plan['objects'],lambda r:r['ref']==plan['negative_selection_observation_ref'],'Missing observation placeholder')['value']
        require(placeholder['supplier_decisions'] is None and placeholder['prior_failures'] is None,
            'Actual supplier outcomes or historical execution were prefilled')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['output'].get('factors',{}).get('micro_task_key')==key(identity),'No original proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['output'].get('data',{}).get('micro_task_key')==key(identity),'No original final')['output']
        require(task_digest(proposal)==record['proposal_response_sha256']==final['data']['proposal_response_sha256']
            and proposal['factors']['micro_result_sha256']==worker['result_sha256']==final['data']['micro_result_sha256']
            and final['decision']==proposal['accepted']==(not refused),'Original macro transport differs from A05')
        if refused:
            require(task['state']=='waiting_input' and worker['result']['kind']=='deferred','A05 wait was falsely promoted to completion')
            observed=record['observed'];source=one(worker['source_reading'],lambda r:r['ref']==plan['negative_selection_observation_ref'],'A05 did not read actual refusals')['projection']
            evidence=one(worker['source_reading'],lambda r:r['ref']==plan['native_evidence_ref'],'A05 did not read bound evidence')['projection']
            require(evidence['content_hash']==task_digest(observed) and observed['native_request_sha256']==task_digest(record['native_request'])
                and source['supplier_decisions']==observed['supplier_decisions'] and source['prior_failures']==observed['prior_failures'],
                'Runtime input/actual source mapping changed')
            current=[e for e in events if e['event_type']=='supplier_order_decision' and e['project_id']==record['scope']['project_id'] and e['tick']==record['scope']['tick']]
            require(current==source['supplier_decisions'] and len(current)==2 and all(e['data']['accepted'] is False for e in current),
                'No-accepted calculation did not use all current actual supplier decisions')
            history=source['prior_failures'];expected=[e for e in failures if e['agent_id']==identity['organization_id'] and e['tick']<record['scope']['tick']]
            require([h['event'] for h in history]==expected and worker['result']['reason_code']==(REPEATED_WAIT if history else WAIT),
                'Same earlier actual result did not affect the later dependency judgment')
            for h in history:
                require(h['event_sha256']==task_digest(h['event']) and h['original_micro_negative']['result_sha256']==h['event']['data']['contractor_decision']['micro_result_sha256'],
                    'Later decision substituted its original earlier negative result')
            event=one(failures,lambda e:e['data']['contractor_decision'].get('micro_task_key')==key(identity),'Original negative not actually executed')
            require(event['data']['delay_days_added']==15 and event['data']['contractor_decision']['decision_source']=='micro_contractor_no_accepted'
                and not event['data']['contractor_decision'].get('selected_supplier_id'),'Negative selection invented a selected supplier')
            followup=one(followups,lambda r:r['observed']['event_id']==event['event_id'],'Same actual failure was not consumed')
            digest_valid(followup);fw=wm[key(followup['identity'])]
            require(followup['proof']['event']==event and followup['proof']['original_micro_negative']['identity']==identity
                and fw['result']['kind']=='completed' and fw['result']['payload']['choice']=='request_quote',
                'Existing private follow-up did not consume same actual negative decision/execution')
            proofs.append({'identity':identity,'result':worker['result'],'result_sha256':worker['result_sha256'],
                'source_reading_sha256':worker['source_reading_sha256'],'observed':observed,'proposal':proposal,'final':final,
                'actual_failure':event,'followup_identity':followup['identity'],'followup_result_sha256':fw['result_sha256']})
        else:
            require(task['state']=='output_formed' and worker['result']['payload']['choice']=='accept_supply_offer',
                'Positive current A05 selection regressed')
    pending=[t for t in tasks if t['state']!='output_formed']
    require(len(pending)==(3 if refused else 0) and all(key(t['identity']) in {key(r['identity']) for r in records} for t in pending),
        'Unrelated task incomplete')
    if refused:
        require(all(not p['selected_supplier_ids'] and p['performance']['delay_days']==15*sum(e['project_id']==p['project_id'] for e in failures) for p in projects),
            'Original delay/selection state was replaced')
    require(file_hash(dbpath)==before,'Read-only verification changed journal')
    return {'technical_tasks':len(tasks),'native_failures':len(failures),'native_successes':len(selections),
        'authenticated_pending_A05':len(pending),'private_followups':len(followups),
        'later_same_failure_consumers':sum(bool(p['observed']['prior_failures']) for p in proofs),
        'proofs':proofs,'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');require(config['schema_version']=='procurement-negative-selection-chain.v1'
        and config['scenarios']=={'all_refused':{'decline_all_quotes':True},'accepted_control':{'decline_all_quotes':False}},'Invalid fixed config')
    require(macro_hashes()==read(directory/'macro-before.json'),'Frozen macro changed')
    cases={name:verify_scenario(directory/name,refused=opts['decline_all_quotes']) for name,opts in config['scenarios'].items()}
    require(cases['all_refused']['later_same_failure_consumers']==2,'Missing next-tick same actual failure consumption')
    originals=[read(directory/name/'input/macro-request.json') for name in cases];require(originals[0]==originals[1],'Native initial states differ')
    # Validate declared Supplier policy is the sole independent input difference.
    docs=[]
    for name in cases:
        settings=read(directory/name/'input/assembly-host.json')['settings']['supply']
        doc=read(settings['file_path'])
        for p in doc['plans']:
            policy=one(p['quote']['objects'],lambda r:r['ref']['kind']=='SupplyPricingProfile','No initial pricing policy')['value']
            require(policy.pop('policy')==('decline_new_quotes' if name=='all_refused' else 'evaluate'),'Wrong controlled quote policy')
        docs.append(json.dumps(doc,sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN'))
    require(docs[0]==docs[1],'Private Supplier inputs differ beyond controlled policy')
    from integration.contractor_planning_actions import ContractorPlanningActionAssembler
    from src.actions.contracts.common import Reference
    from src.actions.roles.qs_change import content_digest
    for filename in ['contractor-negative-input.json','foundation/failure-followup-input.json']:
        compared=[]
        for name in cases:
            doc=read(directory/name/'input'/filename)
            for plan in doc['plans']:
                for row in plan['objects']:
                    if row['ref']['kind']=='ProcurementAuthority':
                        authority=row['value'];terms=one(plan['objects'],lambda r:r['ref']==authority['terms_ref'],'Missing initial terms')
                        typed=ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(terms['ref']),terms['value'])
                        require(authority['terms_sha256']==content_digest(typed),'Initial terms binding changed')
                        authority['terms_sha256']='verified_run_scoped_terms_digest'
            compared.append(json.dumps(doc,sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN'))
        require(compared[0]==compared[1],'Independent Contractor decision/follow-up inputs differ between controls')
    return {'batch':'3E-N05','status':'executed_micro_negative_selection_native_failure_and_later_same_failure_consumption',
        'cases':cases,'macro_unchanged':True,'boundary':config['boundary'],'overall_goal3_complete':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,default=ROOT/'config/procurement_negative_selection.json')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check-only',action='store_true');args=parser.parse_args(argv)
    directory=args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False);config=read(args.config)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,options in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**options)
            run_existing_input(directory/name,assembly_hook='integration.procurement_failure_followup:configure_assembly')
    elif (directory/'artifact-manifest.json').exists():verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:
        _write(directory,'checks.json',checks)
        _write(directory,'artifact-manifest.json',{'schema_version':'procurement-negative-business-artifacts.v1',
            'files':{p.relative_to(directory).as_posix():file_hash(p) for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}})
    print(json.dumps({'status':checks['status'],'cases':{n:{k:v for k,v in c.items() if k!='proofs'} for n,c in checks['cases'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
