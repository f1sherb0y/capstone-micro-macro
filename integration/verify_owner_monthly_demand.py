"""Run or read-only verify original Owner demand judgments and actual later reuse."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.owner_monthly_demand_development import build_bundle
from integration.owner_monthly_demand import MonthlyOwnerDemandPlan,bind_sources,result_judgment,BOUNDARY
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='owner-monthly-demand-chain.v1' and config['ticks']==2 and config['background_project_stage']=='design'
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}},'Unsupported fixed original Owner demand comparison')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Actual original demand analysis process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events'];plans=read(directory/'input/owner-monthly-demand-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==2,'Two actual own Owner months required')
    require(host['boundary']==BOUNDARY and not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed or boundary changed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM owner_observation_results')]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task incomplete or changed')
    require(sum(t['identity']['purpose']=='action' for t in tasks)==2,'Monthly demand unexpectedly executed a brief, investment or other formal action')
    proofs=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Original own request journal changed')
        identity=TaskIdentity(**record['identity']);scope=record['scope'];tick=scope['tick'];observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original OWN-A01 result missing');digest_valid(micro)
        require(identity.role=='Owner' and identity.action_id=='OWN-A01' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result']),
            'Original Owner identity or micro result changed')
        judgment=result_judgment(micro);plan=MonthlyOwnerDemandPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==tick,'Own original plan missing'))
        require(record['context']==plan.context.model_dump(mode='json') and record['action_input']==plan.action_input,'Originally declared invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Original actual macro request binding changed')
        request_profile=record['native_request']['agent'];profile=observed['native_profile']
        require(profile['organization_id']==request_profile['agent_id']==identity.organization_id and profile['role']==request_profile['role']=='Owner'
            and profile['available_resource']==request_profile['resources']['available_resource']
            and profile['total_resource_capacity']==request_profile['resources']['total_resource_capacity'],'Observed native own capacity is not the actual request profile')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Original source binding changed')
        observation=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyOwnerDemandObservation','Original A01 never read actual monthly outcomes')['projection']
        objective=one(micro['source_reading'],lambda r:r['ref']['kind']=='OwnerObjective','Independent original objective missing')['projection']
        signal=one(micro['source_reading'],lambda r:r['ref']['kind']=='DemandObservation','Original A01 never read its actual global index')['projection']
        capacity=one(micro['source_reading'],lambda r:r['ref']['kind']=='ManagementCapacity','Original own capacity missing')['projection']
        require(observation==one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Bound monthly observation missing')['value']
            and any(r['projection'].get('content_hash')==task_digest(observed) for r in micro['source_reading'])
            and observation['private_case_and_finance_history_coverage']=='unknown','Actual current input/history was replaced with declared or supposedly complete private facts')
        require(not record['action_input']['opportunity_refs'] and not record['action_input']['existing_case_refs']
            and signal['region_id']=='simulation_global' and signal['use_code']=='background_portfolio_demand'
            and signal['research_permitted']=={'state':'known','value':True} and signal['measure']['value']==observation['current_market_index']
            and capacity['total']['value']==observation['native_available_resource'] and capacity['commitments']==[]
            and capacity['total']['value']['unit']=='native_resource' and Decimal(capacity['total']['value']['value'])==Decimal(str(profile['available_resource'])),
            'Global demand/native remaining capacity was replaced with a project, private complete commitments or a financial ledger')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1,'Original earlier own actual history missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Actual prior analysis proof missing')
            event=previous['actual_event']
            require(h['source_event_sha256']==task_digest(event) and h['micro_identity']==previous['identity']
                and h['micro_result_sha256']==previous['micro_result_sha256'] and h['operation']==event['data']['operation']=='evaluate_market_demand'
                and h['tick']==event['tick']<tick and event['agent_id']==identity.organization_id and h['participated'] is True
                and h['analysis']==previous['judgment'] and h['analysis_sha256']==task_digest(previous['judgment']),
                'Later original A01 did not receive the same earlier actually executed own analysis artifact')
        rule=objective['signal_rules']['value'][0];threshold=rule['threshold'];current=Decimal(str(observed['macro_environment']['market_demand_index']))
        require(rule['signal_code']=='native_global_market_demand_index' and rule['comparison']=='at_least' and threshold['value']=='1'
            and threshold['unit']=='index' and objective['new_signal_choice']=={'state':'known','value':'propose'},'Original independent screening policy changed')
        previous=None if not history else history[-1]['analysis']['current_market_index']['value']
        delta=None if previous is None else current-Decimal(previous)
        trend='initial' if delta is None else 'rising' if delta>0 else 'falling' if delta<0 else 'flat'
        require(judgment.current_market_index.model_dump(mode='json')==observation['current_market_index']
            and judgment.declared_screening_threshold.model_dump(mode='json')==threshold
            and judgment.meets_screening_threshold is (current>=Decimal(1)) and judgment.meets_screening_threshold is high
            and judgment.original_choice==('propose' if high else 'ignore') and judgment.prior_actual_analysis_count==len(history)
            and judgment.previous_actual_index==previous and judgment.change_from_previous_actual_analysis==(None if delta is None else str(delta))
            and judgment.trend==trend and judgment.consumed_event_ids==[h['event_id'] for h in history]
            and judgment.consumed_analysis_sha256==[h['analysis_sha256'] for h in history],
            'Original A01 did not apply actual macro demand and the prior executed analysis to its threshold/trend judgment')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),
            'Observed macro request differs from the actual durable transport input')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual original operation missing')
        require(proposal['accepted'] is final['decision'] is event['data']['decision_accepted'] is True
            and proposal['action_type']==final['action_type']==event['data']['operation']=='evaluate_market_demand'
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description'] and event['data']['decision_source']=='llm_agent',
            'Actual native execution differs from original micro analysis, proposal or final')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Own native profile missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='evaluate_market_demand','Original native own memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native memory differs from actual execution')
        feedback=one(read(directory/'runtime/observations.json')['records'],lambda o:o['event_id']==event['event_id'] and o['organization_id']==identity.organization_id,'Committed original own feedback missing')
        require(feedback['payload']['committed'] is True and feedback['payload']['data']['operation']=='evaluate_market_demand'
            and feedback['payload']['data']['description']==event['description'],'Original routed feedback differs from execution')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'actual_observation':observation,'independent_objective':objective,'judgment':judgment.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_proposal':proposal,'original_proposal_task_identity':transport,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'actual_native_memory':memory,'original_committed_feedback':feedback,'consumed_own_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed the original task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'actual_demand_analyses':2,'later_own_analysis_consumers':1,'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,value in inputs.items():require(value['macro_environment'].pop('market_demand_index')==config['scenarios'][name]['market_demand_index'],'Original controlled demand setting changed')
    require(normalized(inputs['high'],'high')==normalized(inputs['low'],'low'),'Original macro inputs differ beyond configured demand')
    plans={name:read(directory/name/'input/owner-monthly-demand-input.json') for name in cases}
    require(normalized(plans['high'],'high')==normalized(plans['low'],'low'),'Private input/policy differs between controlled cases')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'original initial market_demand_index 1.2 versus 0.6 only','boundary':BOUNDARY,
        'scope':'One original Owner monthly demand-analysis action; remaining monthly/business gaps stay blocked'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_demand --config config/owner_monthly_demand_chain.json --output $OutputDirectory\n",encoding='utf-8')
    lines=['# GOAL 3I 业主月度需求分析实跑记录','',
        '两组均通过原 OWN-A01、原月度提案/最终决定、原 scheduler 实际执行及后轮原 A01 消费。',
        '两组只改变原初始 market_demand_index=1.2/0.6；下表为原模型更新后的实际指数，不把配置当作观测。','',
        '| 场景 | 轮次 | 实际需求指数 | 原 A01 选择 | 阈值 | 趋势 | 与前轮实际分析的差 | 实际事件 | 消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append(f"| {name} | {p['scope']['tick']} | {j['current_market_index']['value']} | {j['original_choice']} | {j['declared_screening_threshold']['value']} | {j['trend']} | {j['change_from_previous_actual_analysis'] or '无'} | {p['actual_event']['event_id']} | {', '.join(j['consumed_event_ids']) or '无'} |")
    lines+=['',f"共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个技术任务全部形成结果，4 项实际需求分析，2 个后轮原 A01 消费。",'私有阈值为 1 index。原 A01 保留原阈值比较、观察时点、权限和容量检查；可选月度分析读取实际上一轮分析结果，计算当前指数减前轮实际指数，并形成 rising/falling/flat 判断。',
        'propose 仅保留未执行的私有后续意向，没有创建私有简报、案件或项目；两组的需求分析本身均已完成，故原宏观均实际执行 evaluate_market_demand。',
        '容量取原 request 的可用原生资源，作为当期剩余可用量，未重建完整企业承诺。私有案件和融资历史保持 unknown；全局指数不是区域调查或具体投资候选。','',
        '新目录运行：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_demand `",'  --config config/owner_monthly_demand_chain.json `','  --output output/integration/goal3i_owner_demand_my_run','```','',
        '只读核验：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_demand --check-only --output '{directory.as_posix()}'",'```','',
        '完整原请求、输入源、类型化判断、原提案、最终决定、原执行事件、原记忆、提交反馈及后轮对应关系见 checks.json 和 high/low/runtime。',
        '本轮只接通 Owner.evaluate_market_demand；月度累计 17/32，15 项仍阻塞，GOAL 3 未完成。具体项目管线筛选、融资容量、范围编制与投资策略调整不计入本轮。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/professional_monthly_native.py','integration/owner_monthly_demand.py','integration/owner_monthly_demand_development.py',
        'integration/verify_owner_monthly_demand.py','src/actions/contracts/owner_monthly_demand.py','src/actions/contracts/owner_objects.py',
        'src/actions/roles/owner_monthly_demand.py','src/actions/roles/owner.py','config/owner_monthly_demand_chain.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/业主月度需求分析接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'owner-monthly-demand-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/owner_monthly_demand_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile);run_existing_input(directory/name,assembly_hook='integration.owner_monthly_demand:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
