"""Verify actual selections, authorized original A12 records and later same-result use."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
from integration.architect_client_development import build_bundle
from integration.architect_client_relationship import BOUNDARY,ClientRelationshipPlan,bind_sources,result_judgment
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(c):
    require(set(c)=={'schema_version','run_id','scenarios','source_note'} and c['schema_version']=='architect-client-relationship-chain.v1'
        and c['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}}
        and c['run_id'] and c['source_note'],'Unsupported fixed client relationship scenario')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original client relationship process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    monthly=host['monthly'];records=monthly['requests'];events=monthly['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==3 and len(records)==6,'Expected both original Architects over three ticks')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed')
    initial=read(directory/'input/macro-request.json')
    require(all(not p['event_log'] and not p['selected_architect_id'] and not p['selected_engineer_id'] and not p['selected_qs_id']
        for p in initial['initial_projects']),'Actual client collaboration was prefilled')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        tables=[n for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if n.endswith('_results')]
        require(all(re.fullmatch('[a-z_]+',n) for n in tables),'Invalid original journal table name')
        workers=[json.loads(v) for n in tables for v, in db.execute('SELECT record FROM '+n)]
    require(len(workers)==33 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original tasks unresolved or missing')
    taskmap={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r);i=TaskIdentity(**r['identity']);snapshot=snapshots[i.key];digest_valid(snapshot,'snapshot_sha256')
        require(r['result_sha256']==task_digest(r['result']) and r['source_reading_sha256']==task_digest(r['source_reading'])
            and r['result']['kind']=='completed' and taskmap[i.key]['output']==r['result']
            and i.context_sha256==task_digest(snapshot['context']) and i.input_sha256==task_digest(snapshot['action_input']),
            'Original action/result/reading/snapshot identity changed')
    def source(r,kind):return one(r['source_reading'],lambda s:s['ref']['kind']==kind,'Missing original '+kind)['projection']
    def event_for(eid):return one(events,lambda e:e['event_id']==eid,'Missing actual original event')
    receipts=host['professional']['appointment']['receipts'];require(len(receipts)==5,'Original selected professional confirmation missing')
    for receipt in receipts:
        digest_valid(receipt);event=event_for(receipt['event_id']);r=saved[TaskIdentity(**receipt['identity']).key];o=receipt['observed']
        require(receipt==metadata['professional_appointment_received:'+task_digest({'event_id':receipt['event_id'],'organization_id':receipt['organization_id']})]
            and receipt['state']=='formed' and receipt['choice']==r['result']['payload']['choice']=='confirm'
            and receipt['result_sha256']==r['result_sha256'] and o['event_sha256']==task_digest(event)
            and event['data'][receipt['role'].lower()+'_id']==receipt['organization_id'],'Actual own A03 selection confirmation changed')
        appointment=source(r,'Appointment')
        require(appointment['status']=='selected' and appointment['service_relationship_ref'] is None and appointment['reservation_ref'] is None,
            'Selected collaboration was promoted to a detailed service relationship')
        for prefix,action,operation,finalop in [('provider',receipt['role'].upper()+'-A02','consider_appointment',receipt['role'].lower()+'_appointment_acceptance'),
                ('owner','OWN-A04','select_appointment','owner_select_'+receipt['role'].lower())]:
            predecessor=saved[o[prefix+'_task_key']];identity=TaskIdentity(**predecessor['identity'])
            proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']==operation
                and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing original independent acceptance')['output']
            final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']==finalop
                and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing independent acceptance final')['output']
            require(identity.action_id==action and predecessor['result']['payload']['choice']=='accept'
                and proposal['accepted'] is final['decision'] is True
                and o[prefix+'_result_sha256']==predecessor['result_sha256']==proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']
                and task_digest(proposal)==o[prefix+'_proposal_sha256'] and task_digest(final)==o[prefix+'_final_sha256'],
                'A03 replaced the original exact provider/owner acceptance')
    plans=read(directory/'input/client-relationship-input.json')['plans'];proofs=[]
    for record in sorted(records,key=lambda row:(row['scope']['tick'],row['scope']['organization_id'])):
        digest_valid(record);scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];i=TaskIdentity(**record['identity']);r=saved[i.key];j=result_judgment(r)
        require(record==metadata[record['key']] and record['state']=='formed' and record['result_sha256']==r['result_sha256'],'Monthly original record changed')
        observed=record['observed'];plan=ClientRelationshipPlan.model_validate(one(plans,lambda p:p['organization_id']==org and p['tick']==tick,'Missing declared own plan'))
        require(i.action_id=='ARCHITECT-A12' and i.organization_id==org and observed['scope']==scope
            and record['context']==plan.context.model_dump(mode='json')==snapshots[i.key]['context']
            and record['action_input']==plan.action_input==snapshots[i.key]['action_input']
            and observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Original monthly request changed')
        profile=observed['native_profile'];request_agent=record['native_request']['agent']
        require(request_agent['agent_id']==org and profile['available_resource']==request_agent['resources']['available_resource']
            and profile['total_resource_capacity']==request_agent['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],'Native resource ratio changed')
        objects=bind_sources(plan,observed);observation=source(r,'ClientRelationshipObservation');task=source(r,'ClientRelationshipTask')
        require(task_digest(objects)==record['source_sha256'] and observation==one(objects,lambda row:row['ref']==plan.observation_ref.model_dump(mode='json'),'Missing current observation')['value'],
            'A12 did not read exact actual collaboration and monthly history')
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed) for s in r['source_reading']),
            'Original A12 input evidence is unbound')
        require(task['permitted']=={'state':'known','value':True} and task['responsible_actor_id']==plan.context.actor_id
            and task['authority_ref'] in record['context']['authorization_refs'] and task['external_contact_consent']['state']=='unknown'
            and task['purpose']=='internal_selected_client_and_consultant_followup_record'
            and source(r,'ArchitectLearningState')['coverage']=='unknown' and source(r,'Capability')['status']=='unknown',
            'Client task lacks own internal permission or fabricates formal/external authority')
        parties=[]
        for event in events:
            if event['event_type']!='consultant_team_appointed' or event['tick']>=tick or event['data'].get('architect_id')!=org:continue
            receipt=one(receipts,lambda row:row['organization_id']==org and row['event_id']==event['event_id'],'Missing actual own selection receipt')
            project=one(simulation['project_results'],lambda p:p['project_id']==event['project_id'],'Missing actual selected project')
            selected={'organization_id':org,'project_id':project['project_id'],'region':project['region'],'client_organization_id':event['agent_id'],
                'tick':event['tick'],'event_id':event['event_id'],'source_event_sha256':task_digest(event),'appointment_identity':receipt['identity'],
                'appointment_result_sha256':receipt['result_sha256'],'receipt_record_sha256':receipt['record_sha256'],'status':'selected_and_privately_confirmed'}
            for role,pid in [('Owner',project['owner_id']),('Engineer',event['data'].get('engineer_id')),('QS',event['data'].get('qs_id'))]:
                if pid is not None:parties.append({'organization_id':pid,'role':role,'selection':deepcopy(selected)})
        parties.sort(key=lambda p:(p['selection']['tick'],p['selection']['event_id'],p['role'],p['organization_id']))
        require(parties==observed['parties']==observation['parties'],'Client identities borrowed a foreign/future/unconfirmed collaboration')
        history=observed['prior_own_monthly_outcomes'];previous=[]
        require(history==observation['prior_own_outcomes'] and len(history)==tick-1,'Earlier actual own monthly result missing')
        for h in history:
            earlier=event_for(h['event_id']);prior=saved[TaskIdentity(**h['micro_identity']).key];pj=result_judgment(prior)
            require(earlier['agent_id']==org and h['tick']==earlier['tick']<tick and h['source_event_sha256']==task_digest(earlier)
                and h['micro_identity']['organization_id']==org and h['micro_result_sha256']==prior['result_sha256']
                and h['client_judgment']==pj.model_dump(mode='json') and h['participated']==pj.participate
                and h['operation']==earlier['data']['operation']==(pj.operation if pj.participate else 'maintain_operations'),
                'Later original A12 substituted its same actually executed private client update')
            previous=deepcopy(pj.adopted_records)
        old={row['party_organization_id']:row for row in previous};grouped={}
        for party in parties:
            row=grouped.setdefault(party['organization_id'],{'role':party['role'],'selections':[]});row['selections'].append(party['selection'])
        priority=Decimal(str(observed['macro_environment']['market_demand_index']))*Decimal(task['private_review_weight']['value'])
        priority_gate=priority>=Decimal(task['minimum_priority']['value']);capacity_gate=Decimal(str(profile['free_ratio']))>=Decimal(task['minimum_free_ratio']['value'])
        proposals=[];due=[];not_due=[]
        for pid,row in sorted(grouped.items()):
            selected=sorted(row['selections'],key=lambda s:(s['tick'],s['event_id']));event_ids=[s['event_id'] for s in selected];previous_row=old.get(pid)
            changed=previous_row is None or previous_row['selection_event_ids']!=event_ids
            review_due=previous_row is None or tick>=previous_row['next_review_tick']
            proposals.append({'party_organization_id':pid,'party_role':row['role'],'responsible_actor_id':plan.context.actor_id,
                'selection_event_ids':event_ids,'project_ids':sorted({s['project_id'] for s in selected}),'confirmed_selection_sources':selected,
                'last_updated_tick':tick,'next_review_tick':tick+task['review_interval_ticks'],'private_review_priority':str(priority),
                'followup_agenda':['retain_confirmed_collaboration_context','review_future_work_scope_before_any_contact'],
                'external_contact_consent':'unknown','external_message_delivered':False,'detailed_service_relationship':'unknown'})
            if changed or review_due:due.append(pid)
            else:not_due.append(pid)
        participate=priority_gate and capacity_gate and bool(due);adopted=deepcopy(old)
        if participate:
            for row in proposals:
                if row['party_organization_id'] in due:adopted[row['party_organization_id']]=deepcopy(row)
        require(j.participate==participate and j.private_priority.value==str(priority) and j.priority_gate==priority_gate and j.capacity_gate==capacity_gate
            and j.proposed_records==proposals and j.updated_party_ids==(due if participate else []) and j.not_due_party_ids==not_due
            and j.adopted_records==[adopted[k] for k in sorted(adopted)] and j.market_demand.model_dump(mode='json')==observation['market_demand']
            and j.consumed_monthly_event_ids==[h['event_id'] for h in history] and j.consumed_micro_result_sha256==[h['micro_result_sha256'] for h in history],
            'Original A12 failed independent private relationship record and review-due oracle')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==i.key,'Missing original monthly proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==i.key,'Missing original monthly final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing actual monthly operation')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Missing actual Architect')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Missing original monthly memory')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['request_id']==record['native_request']['request_id'] and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==j.operation and event['data']['operation']==(j.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==r['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==j.interpretation
            and memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],
            'Original native monthly execution differs from the same A12 relationship judgment')
        for h in history:
            require(h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick'] and m.get('operation')==h['operation'],'Missing original previous memory'),
                'Later original A12 borrowed a different native memory')
        proofs.append({'scope':scope,'identity':i.as_dict(),'observed':observed,'judgment':j.model_dump(mode='json'),'micro_result_sha256':r['result_sha256'],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),'original_native_memory':memory})
    require(sum(p['judgment']['participate'] for p in proofs)==(2 if high else 0),'Unexpected actual private client update count')
    first=one(proofs,lambda p:p['scope']['organization_id']=='professional-architect' and p['scope']['tick']==2,'Missing first actual client update')
    later=one(proofs,lambda p:p['scope']['organization_id']=='professional-architect' and p['scope']['tick']==3,'Missing later actual consumer')
    require(first['actual_event']['event_id'] in later['judgment']['consumed_monthly_event_ids'] and first['judgment']['adopted_records']==later['judgment']['adopted_records']
        and not later['judgment']['participate'] and len(later['judgment']['not_due_party_ids'])==(3 if high else 0),'Same actual prior client record did not govern later update')
    require(file_hash(database)==before,'Read-only verification changed original journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'monthly_actions':6,
        'actual_client_record_updates':sum(p['judgment']['participate'] for p in proofs),'proofs':proofs}


def collect_checks(directory):
    c=read(directory/'source-config.json');validate_config(c);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    native=[];private=[]
    for name in c['scenarios']:
        r=read(directory/name/'input/macro-request.json');require(r['macro_environment']['market_demand_index']==c['scenarios'][name]['market_demand_index'],'Initial supported demand difference missing')
        r['macro_environment']['market_demand_index']=1.2;native.append(r)
        private.append(read(directory/name/'input/client-relationship-input.json'))
    require(native[0]==native[1] and private[0]==private[1],'Controlled cases differ beyond supported initial macro demand')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in c['scenarios']};regression=None
    if (directory/'portfolio-regression').exists():
        from integration.verify_architect_portfolio_chain import verify_scenario as verify_portfolio
        original=verify_portfolio(directory/'portfolio-regression',high=True)
        require(original==read(directory/'portfolio-regression/regression-checks.json'),'Original portfolio regression changed')
        regression={k:v for k,v in original.items() if k!='proofs'}
    return {'batch':'3C-Architect-client-relationship','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'SimulationCreateRequest.macro_environment.market_demand_index','cases':cases,
        'original_portfolio_regression':regression,'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/architect_client_relationship.py','integration/architect_client_development.py','integration/verify_architect_client_relationship.py',
    'src/actions/contracts/architect_client_relationship.py','src/actions/roles/architect_client_relationship.py','src/actions/contracts/architect_learning_objects.py',
    'src/actions/roles/service_learning.py','integration/architect_portfolio_native.py','integration/architect_portfolio_development.py',
    'integration/verify_architect_portfolio_chain.py','integration/professional_monthly_native.py','integration/professional_intake_native.py',
    'integration/professional_appointment_native.py','integration/architect_learning_actions.py','integration/architect_learning_results.py',
    'config/architect_client_relationship_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
    'docs/建筑师月度客户关系记录接线与验收.md','docs/宏观动作接线清单.md','tests/test_architect_client_relationship.py','tests/test_architect_monthly_portfolio.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'overall_goal3_complete':False,'boundary':BOUNDARY,
        'contacts':[{'macro_action':'Architect.maintain_client_relationship','micro_action':'ARCHITECT-A12 original own authorization and private record judgment',
            'macro_input':'Actual own earlier A03-confirmed team selection, owner/consultant identities, market demand and own free ratio',
            'return_to_macro':'Same original A12 result -> original monthly proposal/final -> actual scheduler event and own memory',
            'feedback_consumer':'Next own A12 reads exact confirmed private record, responsible actor and next-review tick; unchanged not-due records suppress duplicate update',
            'actual_events':[p['actual_event'] for p in checks['cases']['high']['proofs'] if p['judgment']['participate']]}]})
    lines=['# GOAL 3C 建筑师月度客户与合作方私有记录实际运行','','| 场景 | 企业 | tick | 私有优先级 | 更新对象 | 未到复核期 | 原宏观动作 | 消费月度事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,c in checks['cases'].items():
        for p in c['proofs']:
            j=p['judgment'];lines.append('| '+' | '.join(map(str,[name,p['scope']['organization_id'],p['scope']['tick'],j['private_priority']['value'],
                ','.join(j['updated_party_ids']) or 'none',','.join(j['not_due_party_ids']) or 'none',p['actual_event']['data']['operation'],
                ','.join(j['consumed_monthly_event_ids']) or 'none']))+' |')
    lines+=['','仅通过原 SimulationCreateRequest.macro_environment 改变期初市场需求 1.2 / 0.6；独立内部任务、责任人、允许对象、私人权重 0.8、优先级门槛 0.8、复核间隔 2 完全相同。观测和先前记录未预填。',
        '两组在独立进程和任务库中使用相同逻辑 run_id，彼此不读取、不重放任务。原 A01/A02、业主 OWN-A04 与实际选聘、原 A03 确认形成当前真实合作身份；同 tick 选聘不能支持本轮客户记录。',
        '高组主建筑师 tick 2 实际更新业主、工程师、QS 三条私有记录，next_review_tick=4；tick 3 原 A12 读取同一执行与完全相同记录，三者未到复核期，维持运营。另一建筑师 tick 3 更新自己较早选聘的业主和 QS；没有借用主建筑师的关系。',
        '私有优先级=实际需求指数×独立任务权重；高组 0.96、低组 0.48。低组未达门槛，不采用新记录。',
        'checks.json 保留原请求、结果哈希、真实选聘/月度事件、原提议/最终决定、自身记忆和后轮消费；command.json 为普通 integration.run 完整命令。runtime/ 保留原任务库和结果。',
        '原月度事件不包含私有微观哈希；使用本机构/时点唯一事件、精确动作/描述、原提议/决定与自身记忆关联。',BOUNDARY,
        '宏观 174 个基线文件及全部 120 个 Python 源码未改。正式来源和其余月度接线继续保留；GOAL 3 与原 PLAN 未全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'architect-client-relationship-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id'],**profile)
        print('Running original professional/client record case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.architect_client_relationship:configure_assembly')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/architect_client_relationship_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:run_cases(directory,read(a.config))
    elif (directory/'artifact-manifest.json').exists():
        verify_history(directory);require(all(file_hash(ROOT/n)==h for n,h in read(directory/'artifact-manifest.json')['implementations'].items()),'Current client relationship implementation differs from sealed version')
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f!='proofs'} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
