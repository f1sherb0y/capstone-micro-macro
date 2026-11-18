"""Fixed original A05 backup review -> native monthly execution -> later own A05."""
from copy import deepcopy
from decimal import Decimal
import argparse
import json
from pathlib import Path
import sqlite3
from integration.supplier_reliability_development import build_bundle
from integration.supplier_monthly_reliability import BOUNDARY,ReliabilityPlan,result_judgment,backup_request,bind_sources
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(set(config)=={'schema_version','run_id','scenarios','source_note'}
        and config['schema_version']=='supplier-reliability-review-chain.v1'
        and config['scenarios']=={'weak':{'supply_reliability':0.4},'strong':{'supply_reliability':0.95}}
        and config['run_id'] and config['source_note'],'Unsupported fixed reliability scenario')


def verify_scenario(directory,*,weak):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original reliability process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host'];monthly=host['requests']
    events=host['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(monthly)==4,'Expected two original Suppliers over two ticks')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Native observer failed')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM supplier_planning_results')]
    require(len(workers)==4 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Unresolved original tasks')
    taskmap={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in workers}
    for micro in workers:
        digest_valid(micro);identity=TaskIdentity(**micro['identity']);snapshot=snapshots[identity.key];digest_valid(snapshot,'snapshot_sha256')
        require(micro['result_sha256']==task_digest(micro['result']) and micro['source_reading_sha256']==task_digest(micro['source_reading'])
            and micro['result']['kind']=='completed' and taskmap[identity.key]['output']==micro['result']
            and identity.context_sha256==task_digest(snapshot['context']) and identity.input_sha256==task_digest(snapshot['action_input']),
            'Original A05 result, reading, task or snapshot changed')
    plans=read(directory/'input/reliability-input.json')['plans'];proofs=[]
    def source(micro,kind):return one(micro['source_reading'],lambda r:r['ref']['kind']==kind,'Missing original '+kind)['projection']
    def event_for(event_id):return one(events,lambda e:e['event_id']==event_id,'Missing actual event')
    for record in sorted(monthly,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];identity=TaskIdentity(**record['identity'])
        micro=saved[identity.key];j=result_judgment(micro);observed=record['observed']
        plan=ReliabilityPlan.model_validate(one(plans,lambda p:(p['organization_id'],p['tick'])==(org,tick),'Missing source plan'))
        require(record==metadata[record['key']] and record['state']=='formed' and record['result_sha256']==micro['result_sha256']
            and identity.action_id=='SUPPLIER-A05' and identity.organization_id==org and identity.role=='Supplier'
            and record['context']==plan.context.model_dump(mode='json')==snapshots[identity.key]['context']
            and record['action_input']==plan.action_input
            and snapshots[identity.key]['action_input']=={'scope_ref':plan.context.scope.model_dump(mode='json'),**plan.action_input},'Original monthly input changed')
        request_agent=record['native_request']['agent'];profile=observed['native_profile']
        require(observed['scope']==scope and observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and request_agent['agent_id']==org and request_agent['role']=='Supplier'
            and profile['supply_reliability']==request_agent['capabilities']['supply_reliability']
            and profile['available_resource']==request_agent['resources']['available_resource']
            and profile['total_resource_capacity']==request_agent['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],'Native profile origin replaced')
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in micro['source_reading']),'A05 did not read observed provenance')
        observation=source(micro,'SupplyReliabilityObservation');policy=source(micro,'SupplyReliabilityPolicy')
        objects=bind_sources(plan,observed)
        require(one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Missing observation')['value']==observation
            and task_digest(objects)==record['source_sha256'],'Original A05 did not read exact current observations')
        require(source(micro,'InventorySnapshot')['coverage']=='unknown' and source(micro,'InventorySnapshot')['lots']==[]
            and source(micro,'SupplierCapacity')['resource_coverage']==source(micro,'SupplierCapacity')['commitment_coverage']=='unknown'
            and not source(micro,'SupplierCapacity')['resources'] and not source(micro,'SupplierCapacity')['commitments']
            and source(micro,'SupplyWorkAuthorization')['order_ref'] is None
            and source(micro,'StockingAuthority')['risk_bearer_id']==org
            and policy['purpose']=='private_own_risk_backup_sourcing_review'
            and policy['target_native_reliability']['value']=='0.8' and policy['minimum_shortfall']['value']=='0.05'
            and policy['minimum_free_ratio']['value']=='0.2' and policy['maximum_prior_reviews']==1,'Private bounded policy or unknown physical state replaced')
        require(j.current_backup_request==backup_request(micro)=={
            'supplier_ids':source(micro,'SupplyPlanningProfile')['supplier_ids'],
            'required_lines':source(micro,'SupplyPlanningProfile')['required_lines']},'Original validated inquiry candidate replaced')
        history=observation['prior_own_outcomes'];previous=[]
        require(history==observed['prior_own_monthly_outcomes'] and len(history)==tick-1,'Earlier own original monthly outcomes missing')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Missing actual Supplier')
        for h in history:
            prior=saved[TaskIdentity(**h['micro_identity']).key];prior_j=result_judgment(prior);earlier=event_for(h['event_id'])
            require(h['tick']<tick and earlier['tick']==h['tick'] and earlier['agent_id']==org
                and h['micro_identity']['organization_id']==org and h['source_event_sha256']==task_digest(earlier)
                and h['micro_result_sha256']==prior['result_sha256'] and h['review']==prior_j.model_dump(mode='json')
                and h['backup_request']==backup_request(prior)==prior_j.current_backup_request
                and h['participated']==prior_j.participate
                and h['operation']==earlier['data']['operation']==(j.operation if prior_j.participate else 'maintain_operations')
                and h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick']
                    and m.get('operation')==h['operation'],'Missing earlier memory'),'Later A05 lost exact original executed review')
            if h['participated']:previous.append(h['backup_request'])
        shortfall=Decimal('0.8')-Decimal(str(profile['supply_reliability']));count=sum(h['participated'] for h in history)
        participate=shortfall>=Decimal('0.05') and Decimal(str(profile['free_ratio']))>=Decimal('0.2') and count<1
        require(j.participate==participate and j.prior_actual_review_count==count and Decimal(j.reliability_shortfall)==shortfall
            and j.native_reliability.model_dump(mode='json')==observation['native_reliability']
            and j.native_free_ratio.model_dump(mode='json')==observation['native_free_ratio']
            and j.consumed_event_ids==[h['event_id'] for h in history]
            and j.consumed_micro_result_sha256==[h['micro_result_sha256'] for h in history]
            and j.prior_backup_requests==previous,'Independent reliability decision oracle failed')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing original proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing original final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing actual monthly execution')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Missing native memory')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['request_id']==record['native_request']['request_id'] and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==j.operation
            and event['data']['operation']==(j.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==j.interpretation
            and memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native execution differs from original A05')
        proofs.append({'scope':scope,'identity':identity.as_dict(),'observed':observed,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_proposal':proposal,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'original_native_memory':memory})
    require(sum(p['judgment']['participate'] for p in proofs)==(2 if weak else 0),'Unexpected actual backup review count')
    require(all(not p['judgment']['participate'] and p['judgment']['prior_actual_review_count']==int(weak)
        for p in proofs if p['scope']['tick']==2),'Later actual review did not limit duplicate review')
    require(file_hash(database)==before,'Read-only verification changed original journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'monthly_actions':len(monthly),
        'actual_backup_reviews':sum(p['judgment']['participate'] for p in proofs),'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes()
    require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    native=[read(directory/n/'input/macro-request.json') for n in config['scenarios']];private=[]
    for name,r in zip(config['scenarios'],native):
        require(all(a['supply_reliability']==config['scenarios'][name]['supply_reliability'] for a in r['agents'] if a['role']=='Supplier'),'Initial supported profile difference missing')
        for a in r['agents']:
            if a['role']=='Supplier':a['supply_reliability']=0.4
        p=read(directory/name/'input/reliability-input.json');p.pop('run_id')
        for plan in p['plans']:plan['context'].pop('run_id')
        private.append(p)
    require(native[0]==native[1] and private[0]==private[1],'Controlled cases differ beyond original initial reliability')
    cases={name:verify_scenario(directory/name,weak=name=='weak') for name in config['scenarios']}
    return {'batch':'3F-Supplier-backup-review','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'Supplier.supply_reliability in original SimulationCreateRequest agents',
        'cases':cases,'contacts':[{'macro_action':'Supplier.improve_supply_reliability','micro_action':'SUPPLIER-A05 request_quote with typed private monthly review',
            'macro_input':'Actual native own supply_reliability and free ratio; independent own-risk six-panel forecast and private review policy',
            'return_to_macro':'Original monthly proposal/final, scheduler agent_operation and retained episodic memory',
            'native_event_correlation':'Unique own organization/tick, exact operation/description and retained memory against original proposal/final; native monthly event has no private micro-result hash.',
            'feedback_consumer':'Later own original A05 reads same executed review and exact request candidate; prior actual review count prevents repeated review',
            'actual_events':[p['actual_event'] for p in cases['weak']['proofs'] if p['judgment']['participate']]}],
        'remaining_blockers':['Supplier.adjust_inventory: no actual stock ledger or native stock mutation interface',
            'Detailed A05-A09: missing independent effective supply order, task/release/batch/dispatch/receipt issuers'], 'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/supplier_monthly_reliability.py','integration/supplier_reliability_development.py',
    'integration/verify_supplier_reliability_chain.py','integration/professional_monthly_native.py',
    'src/actions/contracts/supplier_monthly_reliability.py','src/actions/contracts/supplier_planning_objects.py',
    'src/actions/roles/supplier_monthly_reliability.py','src/actions/roles/supplier_planning.py',
    'integration/supplier_planning_actions.py','integration/supplier_planning_results.py','integration/supplier_order_handoff.py',
    'integration/supplier_monthly_development.py','integration/contractor_tender_authority_runtime.py','integration/bank_financing_private.py',
    'config/supplier_reliability_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
    'docs/供应商月度可靠性复核接线与验收.md','docs/宏观动作接线清单.md','tests/test_supplier_monthly_reliability.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],'boundary':BOUNDARY,'overall_goal3_complete':False})
    lines=['# GOAL 3F 供应商备用采购复核实际运行记录','','| 场景 | 企业 | tick | 实际可靠性 | 与 0.8 差值 | 先前实际复核数 | 原宏观实际动作 | 消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append('| '+' | '.join(map(str,[name,p['scope']['organization_id'],p['scope']['tick'],j['native_reliability']['value'],
                j['reliability_shortfall'],j['prior_actual_review_count'],p['actual_event']['data']['operation'],','.join(j['consumed_event_ids']) or 'none']))+' |')
    lines+=['','仅通过原 SimulationCreateRequest.agents 的期初 supply_reliability 改变 0.4 / 0.95；其他宏观及私有政策、未绑定观测一致。',
        '原 A05 先验证独立自担风险备货授权和六 panel 询价候选，再计算 0.8 - 实际可靠性。差值至少 0.05、空闲比例至少 0.2 且此前实际复核少于一次才开展月度复核。',
        '弱组首次两家执行 improve_supply_reliability；第二轮读取同企业原执行事件和同一原 A05 询价候选，实际复核数成为 1，转 maintain_operations。强组差值不足，均维持运营。',
        'command.json 是普通 integration.run 完整命令；日志、runtime/result.json、tasks.sqlite 和 checks.json 保留输入—微观结果—原执行—后轮消费的对应关系。',
        BOUNDARY,'宏观 174 文件基线和全部 120 个 Python 源码未改。只交付本项月度复核，库存调整和详细供货 A05–A09 仍阻塞；GOAL 3 和原 PLAN 未全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'supplier-reliability-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
        print('Running original supplier backup-review case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.supplier_monthly_reliability:configure_assembly')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/supplier_reliability_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv)
    directory=a.output.resolve()
    if not a.check_only:run_cases(directory,read(a.config))
    elif (directory/'artifact-manifest.json').exists():
        verify_history(directory);require(all(file_hash(ROOT/n)==h for n,h in read(directory/'artifact-manifest.json')['implementations'].items()),'Current code differs from sealed implementation')
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f!='proofs'} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
