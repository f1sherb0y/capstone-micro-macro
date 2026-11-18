"""Run and verify bounded N03 monthly upkeep through the ordinary native CLI."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from integration.contractor_tender_development import _write, verify_bundle
from integration.engineer_qualification_maintenance import OPERATION, BOUNDARY
from integration.engineer_qualification_maintenance_development import build_bundle
from integration.professional_methods_native import bind_sources, MonthlyMethodPlan, result_judgment
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory, *, high):
    for manifest in (directory/'input').rglob('input-manifest.json'): verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0, 'Original upkeep process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==2,
        'Expected own Engineer judgments across two original monthly ticks')
    require(not any(e['data'].get('agent_observer_errors') for e in events), 'Original event observer failed')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM engineer_learning_results')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks), 'Unformed/changed original task')
    key=lambda i:TaskIdentity(**i).key
    micros={key(r['identity']):r for r in workers};task_map={key(t['identity']):t for t in tasks}
    plans=read(directory/'input/qualification-maintenance-input.json')['plans'];proofs=[]
    agent=one(simulation['agent_results'],lambda a:a['agent_id']=='professional-engineer','Missing own native profile')
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);identity=TaskIdentity(**record['identity']);micro=micros[identity.key];digest_valid(micro)
        require(record==metadata[record['key']] and record['state']=='formed'
            and identity.organization_id=='professional-engineer' and identity.action_id=='ENGINEER-A12'
            and micro['result']==task_map[identity.key]['output']
            and record['result_sha256']==micro['result_sha256']==task_digest(micro['result'])
            and micro['source_reading_sha256']==task_digest(micro['source_reading']), 'Original result/task/source reading changed')
        snapshot=snapshots[identity.key];digest_valid(snapshot,'snapshot_sha256')
        require(task_digest(snapshot['context'])==identity.context_sha256 and task_digest(snapshot['action_input'])==identity.input_sha256,
            'Original invocation changed')
        plan=MonthlyMethodPlan.model_validate(one(plans,lambda p:p['tick']==record['scope']['tick'],'Missing initial plan'))
        observed=record['observed'];objects=bind_sources(plan,observed)
        require(task_digest(objects)==record['source_sha256'] and observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'], 'Runtime observation binding changed')
        def source(kind):return one(micro['source_reading'],lambda s:s['ref']['kind']==kind,'Missing original '+kind)['projection']
        observation=source('MonthlyMethodObservation');policy=source('MonthlyMethodPolicy');judgment=result_judgment(micro)
        require(observation==one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Missing bound observation')['value']
            and any(s['projection'].get('content_hash')==task_digest(observed) for s in micro['source_reading']), 'A12 never consumed exact actual sources')
        require(source('EngineerLearningState')['coverage']=='unknown' and source('Capability')['status']=='unknown'
            and plan.action_input['qualification_refs']==[] and plan.action_input['learning_profile_ref'] is None,
            'Background upkeep became complete credential/training facts')
        placeholder=one(plan.objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Missing placeholder')['value']
        require(all(placeholder[k] is None for k in ('regulatory_pressure','native_capability','native_free_ratio','prior_own_outcomes')),
            'Native inputs or prior executions were prefilled')
        profile=observed['native_profile'];request_profile=record['native_request']['agent']
        require(profile['organization_id']==identity.organization_id==request_profile['agent_id']
            and profile['capability']==request_profile['capabilities']['technical_capability']
            and profile['available_resource']==request_profile['resources']['available_resource']
            and profile['total_resource_capacity']==request_profile['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'], 'Not the actual own native profile')
        pressure=Decimal(str(observed['macro_environment']['regulatory_pressure_index']))
        free=Decimal(str(profile['free_ratio']));threshold=Decimal(policy['qualification_maintenance_pressure']['value'])
        history=observed['prior_own_monthly_outcomes'];count=sum(h['participated'] for h in history)
        require(history==observation['prior_own_outcomes'] and len(history)==record['scope']['tick']-1, 'Incomplete own actual history')
        for h in history:
            prior=micros[key(h['micro_identity'])];event=one(events,lambda e:e['event_id']==h['event_id'],'Missing actual earlier event')
            previous=result_judgment(prior)
            memory=one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick'] and m.get('operation')==h['operation'],'Missing actual prior memory')
            require(event['agent_id']==identity.organization_id and event['tick']==h['tick']<record['scope']['tick']
                and task_digest(event)==h['source_event_sha256'] and prior['result_sha256']==h['micro_result_sha256']
                and previous.participate==h['participated'] and previous.method_focus==h['method_focus']
                and event['data']['operation']==h['operation']==(OPERATION if previous.participate else 'maintain_operations')
                and memory==h['original_native_memory'], 'Later A12 substituted its earlier actual execution or micro focus')
        expected=pressure>=threshold and free>=Decimal(policy['minimum_free_ratio']['value']) and count<policy['maximum_prior_improvements']
        q=judgment.qualification_maintenance
        require(threshold==Decimal('0.6') and policy['maximum_prior_improvements']==1 and policy['minimum_free_ratio']['value']=='0.2'
            and judgment.operation==OPERATION and judgment.participate==expected==(high and record['scope']['tick']==1)
            and q['pressure_gap']==str(pressure-threshold) and q['credential_status']=='unknown'
            and q['credential_effect_applied'] is False and q['technical_capability_used_as_credential'] is False
            and judgment.prior_actual_improvement_count==count and judgment.consumed_event_ids==[h['event_id'] for h in history]
            and judgment.prior_method_focus==[h['method_focus'] for h in history if h['participated']], 'Actual upkeep decision or no-credential boundary changed')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id
            and e['tick']==record['scope']['tick'],'Missing actual upkeep execution')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==record['scope']['tick'] and m.get('operation')==event['data']['operation'],'Missing actual retained memory')
        require(proposal['accepted'] is True and final['decision']==judgment.participate==event['data']['decision_accepted']
            and proposal['action_type']==final['action_type']==OPERATION
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and task_digest(proposal)==record['proposal_response_sha256']==final['data']['proposal_response_sha256']
            and event['data']['operation']==(OPERATION if expected else 'maintain_operations')
            and event['description']==proposal['data']['description']==judgment.interpretation+' '+judgment.method_focus
            and memory['capability_update']==event['data'].get('capability_update') and memory['label']==event['data']['label'],
            'Actual native operation differs from its original A12/proposal/final')
        proofs.append({'identity':identity.as_dict(),'result_sha256':micro['result_sha256'],'observation':observed,
            'policy':policy,'judgment':judgment.model_dump(mode='json'),'proposal':proposal,'final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'retained_memory':memory})
    require(file_hash(database)==before, 'Read-only verification changed original journal')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'database_sha256':before,
        'actual_upkeep_operations':sum(p['judgment']['participate'] for p in proofs),
        'later_upkeep_consumers':sum(p['judgment']['prior_actual_improvement_count']>0 for p in proofs)}


def collect_checks(directory):
    config=read(directory/'source-config.json')
    require(config['schema_version']=='engineer-qualification-maintenance-chain.v1' and config['ticks']==2
        and config['minimum_pressure']=='0.6' and config['scenarios']=={'higher_pressure':0.9,'lower_pressure':0.2}, 'Unsupported fixed scenario')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'), 'Frozen macro source changed')
    cases={name:verify_scenario(directory/name,high=name=='higher_pressure') for name in config['scenarios']}
    originals=[];plans=[]
    for name,value in config['scenarios'].items():
        initial=read(directory/name/'input/macro-request.json')
        require(initial['macro_environment'].pop('regulatory_pressure_index')==value, 'Initial controlled pressure changed')
        originals.append(initial)
        document=read(directory/name/'input/qualification-maintenance-input.json')
        plans.append(json.dumps(document,sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN'))
    require(originals[0]==originals[1] and plans[0]==plans[1], 'Controlled inputs differ beyond pressure and run identifiers')
    require(cases['higher_pressure']['actual_upkeep_operations']==cases['higher_pressure']['later_upkeep_consumers']==1
        and cases['lower_pressure']['actual_upkeep_operations']==cases['lower_pressure']['later_upkeep_consumers']==0, 'Missing controlled outcome/later consumption')
    return {'batch':'3C-N03','status':'executed_original_engineer_upkeep_and_later_same_result_consumption',
        'cases':cases,'macro':macro,'boundary':BOUNDARY,'overall_goal3_complete':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/engineer_qualification_maintenance.json')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False);config=read(args.config)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,pressure in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,regulatory_pressure_index=pressure,minimum_pressure=config['minimum_pressure'])
            run_existing_input(directory/name,assembly_hook='integration.engineer_qualification_maintenance:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file(): verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:
        _write(directory,'checks.json',checks)
        _write(directory,'artifact-manifest.json',{'schema_version':'engineer-upkeep-business-artifacts.v1',
            'files':{p.relative_to(directory).as_posix():file_hash(p) for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}})
    print(json.dumps({'status':checks['status'],'technical_tasks':sum(c['technical_tasks'] for c in checks['cases'].values()),'output':str(directory)}))


if __name__=='__main__':main()
