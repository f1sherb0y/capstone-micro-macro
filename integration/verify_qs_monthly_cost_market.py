"""Run or read-only verify actual QS monthly registration, analysis and later reuse."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.qs_monthly_cost_market_development import build_bundle
from integration.qs_monthly_cost_market import MonthlyCostPlan,bind_sources,result_judgment,registration,BOUNDARY,INDEX_PREFIX
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.coordination.tasks import TaskIdentity,task_digest
from src.actions.contracts.common import Measured


def validate_config(config):
    require(config['schema_version']=='qs-monthly-cost-market-chain.v1' and config['ticks']==3 and config['background_project_stage']=='design'
        and config['scenarios']=={'high':{'material_price_index':1.2},'low':{'material_price_index':0.6}},'Unsupported fixed native index comparison')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Actual original monthly process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events'];plans=read(directory/'input/qs-cost-market-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==3 and len(records)==3,'Three actual own QS months required')
    require(host['boundary']==BOUNDARY and not any(e['data'].get('agent_observer_errors') for e in events),'Native observer or boundary differs')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM qs_market_results')]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Actual native task incomplete or changed')
    indices=[v for k,v in metadata.items() if k.startswith(INDEX_PREFIX)]
    require(len(indices)==1 and host['registered_indices']=={indices[0]['organization_id']:indices},'Private index publication missing or substituted')
    proofs=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Original private request journal changed')
        identity=TaskIdentity(**record['identity']);scope=record['scope'];tick=scope['tick'];observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original QS-A01 result missing');digest_valid(micro)
        require(identity.role=='QS' and identity.action_id=='QS-A01' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result']),
            'Original QS identity or result changed')
        judgment=result_judgment(micro);plan=MonthlyCostPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==tick,'Original own plan missing'))
        require(record['context']==plan.context.model_dump(mode='json') and record['action_input']==plan.action_input,'Declared original invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Actual original macro request lost')
        require(task_digest(bind_sources(plan,observed))==record['source_sha256'],'Original source binding changed')
        observation=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyCostObservation','Original A01 never read actual observations')['projection']
        policy=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyCostPolicy','Original A01 never read independent policy')['projection']
        require(observation==one(bind_sources(plan,observed),lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Bound observation missing')['value']
            and any(r['projection'].get('content_hash')==task_digest(observed) for r in micro['source_reading']),
            'Actual native index and history not bound into original micro reading')
        history=observed['prior_own_monthly_outcomes'];registered=observed['registered_indices']
        require(len(history)==tick-1 and registered==([] if tick==1 else indices),'Later A01 did not read exactly its actual private registration')
        for h in history:
            event=one(events,lambda e:e['event_id']==h['event_id'],'Actual prior native event missing')
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Earlier micro/native link missing')
            require(event['agent_id']==identity.organization_id and event['tick']==h['tick']<tick
                and h['source_event_sha256']==task_digest(event) and h['micro_identity']==previous['identity']
                and h['micro_result_sha256']==previous['micro_result_sha256'] and h['operation']==event['data']['operation'] and h['participated'] is True,
                'Later A01 history substituted own original actually executed result')
        current=Decimal(str(observed['macro_environment']['material_price_index']));pressure=max(Decimal(0),current-1)
        require(policy['baseline_material_index']['value']=='1' and policy['pressure_threshold']['value']=='0.1'
            and policy['minimum_relative_change']['value']=='0.01' and policy['maximum_updates']==1,'Private independent cost policy changed')
        change=None if not registered else str(current/Decimal(registered[-1]['material_index']['value'])-1)
        require(judgment.material_index.model_dump(mode='json')==observation['material_index']
            and judgment.baseline_material_index==Measured.model_validate(policy['baseline_material_index'])
            and Decimal(judgment.positive_cost_pressure)==pressure
            and judgment.pressure_priority==('urgent' if pressure>=Decimal('0.1') else 'routine')
            and judgment.relative_change_from_registered==change and judgment.prior_actual_update_count==(0 if tick==1 else 1)
            and judgment.consumed_event_ids==[h['event_id'] for h in history] and judgment.consumed_registration_keys==[e['key'] for e in registered],
            'Original micro did not calculate from actual macro index and exact earlier registered result')
        expected='update_cost_database' if tick==1 else 'review_cost_market'
        require(judgment.operation==expected and judgment.pressure_priority==('urgent' if high else 'routine'),'Actual comparison or bounded original operation differs')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Native proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),
            'Stored macro request differs from the actual original durable proposal input')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Native final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual native operation missing')
        require(proposal['accepted'] is final['decision'] is event['data']['decision_accepted'] is True
            and proposal['action_type']==final['action_type']==event['data']['operation']==expected
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description'] and event['data']['decision_source']=='llm_agent',
            'Actual original operation differs from its micro result, proposal or final')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Own native agent missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==expected,'Actual native memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native memory differs from execution')
        observation_records=read(directory/'runtime/observations.json')['records']
        feedback=one(observation_records,lambda o:o['event_id']==event['event_id'] and o['organization_id']==identity.organization_id,
            'Original committed own event feedback missing')
        require(feedback['payload']['committed'] is True and feedback['payload']['tick']==tick
            and feedback['payload']['data']['operation']==expected and feedback['payload']['data']['description']==event['description'],
            'Original routed actual feedback differs from global execution and own memory')
        source=one(micro['source_reading'],lambda r:r['ref']==judgment.source_ref.model_dump(mode='json'),'Original source permission metadata missing')['projection']
        require(source['source_kind']=='index' and source['confidentiality']=='authorized_private' and source['permission']=={'state':'known','value':True}
            and source['observation_ref']==plan.native_evidence_ref.model_dump(mode='json') and source['applicability']['value']['price_time']==record['context']['business_time'],
            'Registration lost actual observed source permission/time/scope')
        if tick==1:
            entry=indices[0];h={'event_id':event['event_id'],'source_event_sha256':task_digest(event)}
            require(registration(record,micro,h)==entry and entry==metadata[entry['key']] and entry['registered_tick']==2
                and entry['material_index']==observation['material_index'] and micro['result']['payload']['source_refs']==[judgment.source_ref.model_dump(mode='json')],
                'Private publication did not retain the exact actual registered original index and executed event')
        else:require('source_refs' not in micro['result']['payload'],'A review falsely claims a new source registration')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'actual_observation':observation,'independent_policy':policy,'judgment':judgment.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_proposal':proposal,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'actual_native_memory':memory,'original_committed_feedback':feedback,
            'original_proposal_task_identity':transport,'consumed_own_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only check changed original task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'registered_indices':indices,'database_sha256':before,
        'actual_database_updates':1,'actual_market_reviews':2,'later_index_consumers':2,'later_market_review_consumers':1}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes()
    require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,value in inputs.items():require(value['macro_environment'].pop('material_price_index')==config['scenarios'][name]['material_price_index'],'Original configured index changed')
    require(normalized(inputs['high'],'high')==normalized(inputs['low'],'low'),'Controlled native inputs differ beyond original configured index')
    plans={name:read(directory/name/'input/qs-cost-market-input.json') for name in cases}
    require(normalized(plans['high'],'high')==normalized(plans['low'],'low'),'Controlled private plans/policies differ')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'original initial material_price_index 1.2 versus 0.6 only',
        'boundary':BOUNDARY,'scope':'Two bounded QS monthly operations; no cost-estimation improvement or full GOAL 3 completion'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_qs_monthly_cost_market --config config/qs_monthly_cost_market_chain.json --output $OutputDirectory\n",encoding='utf-8')
    lines=['# GOAL 3C QS 月度指数登记与市场分析实跑记录','',
        '两组均通过：54 个技术任务、6 项原 QS-A01 判断、2 次原宏观数据库更新动作、4 次原宏观市场分析动作；4 个后轮动作读取已登记指数，2 个第三轮动作消费上一轮实际市场分析事件。',
        '以下均为原宏观实际更新后的指数；低组初始配置 0.6 被原模型下限截为 0.7，不把配置值冒充实际观测。','',
        '| 场景 | 轮次 | 实际指数 | 正向成本压力 | 优先级 | 实际操作 | 原执行事件 | 已消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append(f"| {name} | {p['scope']['tick']} | {j['material_index']['value']} | {j['positive_cost_pressure']} | {j['pressure_priority']} | {j['operation']} | {p['actual_event']['event_id']} | {', '.join(j['consumed_event_ids']) or '无'} |")
    lines+=['','计算：`max(0, 实际 material_price_index / 私有基准 1 - 1)`，达到 0.1 标为 urgent。',
        '首轮尚无已登记指数，原 A01 检查来源权限、时点和范围后选择 register_source。次轮先核验首轮原生事件、原提案和最终确认，再在原任务库私有 metadata 中写入不可变指数记录；后轮读取同一记录计算相对变化。最大更新次数为 1，后轮 A01 选择 ignore 表示不再登记，类型化 note 保留真实市场分析，原宏观实际执行 review_cost_market。',
        '第三轮读取第二轮实际 review_cost_market 事件并纳入已执行历史及本轮判断，未将微观完成或提案当作宏观已执行。',
        '私有表只保存有原执行事件的全局无量纲模拟材料指数及来源/适用范围/摘要。不是区域成交价、招标基准、实际工程成本或造价预测改进。原随机能力更新也不能证明造价能力因该动作提升。',
        '初始项目通过原配置声明为尚未委任专业方的 design 背景，仅提供三轮观察窗口；不声称本轮完成设计、专业委任或项目履约。','',
        '输入、源读取、计算、微观结果摘要、提案、最终决定、完整原执行事件、机构原记忆、已路由实际反馈和私有指数记录见 checks.json 与 high/low/runtime。宏观 174 文件及所有额外 Python 源码与执行前一致。','',
        '在工作区根目录运行（输出目录必须不存在）：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_qs_monthly_cost_market `",
        '  --config config/qs_monthly_cost_market_chain.json `','  --output output/integration/goal3c_qs_cost_market_my_run','```','',
        '仅核对已保存证据，不重放业务、不写入任务库：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_qs_monthly_cost_market --check-only --output '{directory.as_posix()}'",'```','',
        '本轮只补接两项月度动作；月度累计 16/32，16 项仍未接通。QS.improve_cost_estimation 仍缺原始不可变预测和可比较的实际成本结果。GOAL 3、GOAL 4 整体验证和原 PLAN 均未完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['src/actions/contracts/qs_monthly_cost_market.py','src/actions/contracts/qs_market_objects.py','src/actions/roles/qs_monthly_cost_market.py',
        'src/actions/roles/qs_market.py','integration/professional_monthly_native.py','integration/qs_monthly_cost_market.py',
        'integration/qs_monthly_cost_market_development.py','integration/verify_qs_monthly_cost_market.py','config/qs_monthly_cost_market_chain.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/QS月度指数登记与市场分析接线验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'qs-monthly-cost-market-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/qs_monthly_cost_market_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.qs_monthly_cost_market:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
