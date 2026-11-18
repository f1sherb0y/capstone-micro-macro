"""Run or read-only verify native monitoring and its later original A03 consumer."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.supplier_monthly_prices_development import build_bundle
from integration.supplier_monthly_prices import MonthlySupplierPricePlan,bind_sources,bind_quote_sources,quote_summary,policy_of,result_judgment,BOUNDARY
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='supplier-monthly-prices-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'material_price_index':1.2},'low':{'material_price_index':0.8}},'Unsupported fixed price-monitoring comparison')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original native run failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];quotes=host['quote_requests'];events=host['original_global_events']
    plans=read(directory/'input/supplier-monthly-prices-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==len(quotes)==4,'Two Suppliers and two original months required')
    require(host['boundary']==BOUNDARY and not any(e['data'].get('agent_observer_errors') for e in events),'Boundary changed or original observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM supplier_screening_results')]
        quote_workers=[json.loads(v) for v, in db.execute('SELECT record FROM supplier_quote_results')]
    require(len(tasks)==24 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Task missing, incomplete or changed')
    require(sum(t['identity']['purpose']=='action' for t in tasks)==8 and len(workers)==len(quote_workers)==4,'Unexpected publication, order or physical action')
    proofs=[]
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Own monthly journal changed')
        identity=TaskIdentity(**record['identity']);scope=record['scope'];tick=scope['tick'];org=identity.organization_id;observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original own A01 result missing');digest_valid(micro)
        require(identity.role=='Supplier' and identity.action_id=='SUPPLIER-A01' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result']),'Original A01 identity/result changed')
        require(micro['source_reading_sha256']==task_digest(micro['source_reading']),'Original assembly reading changed')
        j=result_judgment(micro)
        plan=MonthlySupplierPricePlan.model_validate(one(plans,lambda p:p['organization_id']==org and p['tick']==tick,'Original own plan missing'))
        require(record['context']==plan.context.model_dump(mode='json') and record['action_input']==plan.action_input,'Original invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request']) and observed['macro_environment']==record['native_request']['inputs']['macro_environment'], 'Actual macro request changed')
        require(record['native_request']['agent']['agent_id']==org and record['native_request']['agent']['role']=='Supplier','Observed another native organization')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Bound monitoring source changed')
        observation=one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Bound observation missing')['value']
        policy=policy_of(plan);require(policy['base_markup_rate']=='0.25' and policy['risk_surcharge_rate']=='0.05' and policy['material_index_threshold']['value']=='1.05','Independent risk policy changed')
        for kind in ('SupplierCapacity','MarketObservation'):
            src=one(micro['source_reading'],lambda r:r['ref']['kind']==kind,'Original market/capacity reading missing')['projection']
            if kind=='SupplierCapacity':require(src['resource_coverage']==src['commitment_coverage']=='unknown' and src['resources']==src['commitments']==[],'A01 fabricated complete physical capacity')
            else:require(src['region_id']['value']=='simulation_global' and src['forecast_quantity']['state']==src['forecast_window']['state']=='unknown','Global monitoring became a local forecast or order')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1,'Strictly earlier own actual monitoring missing')
        for h in history:
            prev=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'] and p['identity']['organization_id']==org,'Actual own prior event missing')
            require(h['source_event_sha256']==task_digest(prev['actual_event']) and h['micro_identity']==prev['identity']
                and h['micro_result_sha256']==prev['micro_result_sha256'] and h['price_analysis']==prev['judgment']
                and h['operation']=='monitor_material_prices' and h['participated'] is True and h['tick']<tick,'Prior price analysis is not the same actually executed own result')
        quote=one(quotes,lambda r:r['scope']==scope,'Original current private quote missing');digest_valid(quote)
        require(quote==metadata[quote['key']] and quote['state']=='formed' and quote['native_request']==record['native_request']
            and quote['context']==plan.quote.context.model_dump(mode='json') and quote['action_input']==plan.quote.action_input,'Original quote invocation changed')
        qm=one(quote_workers,lambda r:r['identity']==quote['identity'],'Original A03 result missing');digest_valid(qm)
        require(qm['identity']['action_id']=='SUPPLIER-A03' and qm['identity']['organization_id']==org
            and qm['result_sha256']==quote['result_sha256']==task_digest(qm['result'])
            and qm['source_reading_sha256']==task_digest(qm['source_reading']),'Original A03 result/reading changed')
        summary=quote_summary(qm,tick=tick)
        require(summary==quote['quote_summary']==observed['current_original_quote'] and observed['quote_request_record_sha256']==quote['record_sha256'],'A01 did not consume this actual original A03 price')
        qo=quote['observed'];markup=history[-1]['price_analysis']['next_markup_rate'] if history else policy['base_markup_rate']
        require(qo['prior_own_monthly_outcomes']==history and qo['applied_markup_rate']==markup
            and qo['independent_policy_sha256']==task_digest(policy) and qo['native_request_sha256']==observed['native_request_sha256']
            and qo['scope']==scope and qo['boundary']==BOUNDARY,'A03 did not consume the authorized confirmed prior own monitoring')
        qobjects=bind_quote_sources(plan,qo);require(task_digest(qobjects)==quote['source_sha256'],'Private pricing source binding changed')
        pricing=one(qm['source_reading'],lambda r:r['ref']['kind']=='SupplyPricingProfile','Original pricing profile unread')['projection']
        costs=one(qm['source_reading'],lambda r:r['ref']['kind']=='CostBasis','Independent original cost unread')['projection']
        require(pricing['markup_rate']=={'state':'known','value':markup},'Original A03 did not read the applied future markup')
        require(costs['unit_cost']['state']==costs['per_batch_cost']['state']=='known' and costs['quantity_unit']=='panel'
            and costs['unit_cost']['value']['currency']==costs['per_batch_cost']['value']['currency']=='HKD'
            and Decimal(costs['unit_cost']['value']['value'])==80 and Decimal(costs['per_batch_cost']['value']['value'])==0,
            'Dimensionless macro index replaced the independently declared monetary cost')
        expected=Decimal(208) if high and tick==2 else Decimal(200)
        require(summary['currency']=='HKD' and Decimal(summary['total_price'])==expected,'Original quote calculation did not reflect the controlled markup')
        immutable=[r for r in qobjects if r['ref']['kind'] in {'ProductSpecification','Location','DeliveryService'}]
        if history:
            prev=one(proofs,lambda p:p['identity']['organization_id']==org and p['scope']['tick']==tick-1,'Prior own quote proof missing')
            require(summary['priced_product_scope']==prev['current_original_quote']['priced_product_scope'] and immutable==prev['immutable_product_location_services']
                and {k:v for k,v in costs.items() if k!='ref'}=={k:v for k,v in prev['independent_cost_basis'].items() if k!='ref'},'Cross-month quote changed physical terms or independent cost')
        current=Decimal(str(observed['macro_environment']['material_price_index']));risk=current>Decimal('1.05')
        delta=None if not history else str(Decimal(summary['total_price'])-Decimal(history[-1]['price_analysis']['current_original_quote']['total_price']))
        require(j.material_index.model_dump(mode='json')==observation['material_index'] and Decimal(j.material_index.value)==current
            and j.threshold.model_dump(mode='json')==policy['material_index_threshold'] and j.price_risk_above_threshold is risk and risk is high
            and j.next_markup_rate==('0.30' if high else '0.25') and j.current_original_quote==summary
            and j.change_from_previous_quote==delta and j.consumed_event_ids==[h['event_id'] for h in history]
            and j.consumed_monitor_result_sha256==[h['micro_result_sha256'] for h in history], 'Actual index or own actual feedback did not enter the A01 computation')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),'Saved actual request differs from original transport input')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Actual original monitoring execution missing')
        require(proposal['accepted'] is final['decision'] is event['data']['decision_accepted'] is True
            and proposal['action_type']==final['action_type']==event['data']['operation']=='monitor_material_prices'
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description'] and event['description'].startswith(j.interpretation)
            and event['data']['decision_source']=='llm_agent','Original native execution differs from micro proposal/final/result')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Own native agent missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='monitor_material_prices','Actual native memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Original native memory changed')
        feedback=one(read(directory/'runtime/observations.json')['records'],lambda o:o['event_id']==event['event_id'] and o['organization_id']==org,'Committed own feedback missing')
        require(feedback['payload']['committed'] is True and feedback['payload']['data']['operation']=='monitor_material_prices'
            and feedback['payload']['data']['description']==event['description'],'Committed feedback differs from actual execution')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'actual_observation':observation,'independent_policy':policy,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'current_original_quote':summary,'original_quote_journal':quote,'independent_cost_basis':costs,
            'immutable_product_location_services':immutable,'original_proposal':proposal,'original_proposal_task_identity':transport,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'actual_native_memory':memory,'original_committed_feedback':feedback,'consumed_own_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification modified the task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'actual_monitor_operations':4,'original_private_quotes':4,
        'later_own_A01_consumers':2,'later_own_A03_quote_consumers':2,'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,v in inputs.items():require(v['macro_environment'].pop('material_price_index')==config['scenarios'][name]['material_price_index'],'Controlled original index input changed')
    require(normalized(inputs['high'],'high')==normalized(inputs['low'],'low'),'Macro inputs differ beyond configured material index')
    plans={name:read(directory/name/'input/supplier-monthly-prices-input.json') for name in cases}
    require(normalized(plans['high'],'high')==normalized(plans['low'],'low'),'Independent private inputs or policy differ between controlled cases')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'original initial material_price_index 1.2 versus 0.8 only','boundary':BOUNDARY,
        'scope':'One original monthly Supplier price-risk monitoring action and later private original A03 quote consumer; other blocked business stays blocked'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_supplier_monthly_prices --config config/supplier_monthly_prices_chain.json --output $OutputDirectory\n",encoding='utf-8')
    lines=['# GOAL 3F 供应商材料指数风险监测与后轮报价实跑记录','','两供应商、两轮、两组；仅通过原初始 material_price_index=1.2/0.8 构造差异。',
        '原 A03 形成当期私有报价 → 原 A01 监测 → 原宏观实际执行并反馈 → 下轮原 A03 使用已执行监测的加价建议，原 A01 比较同口径前后报价。','',
        '| 场景 | 机构 | 轮次 | 实际材料指数 | 风险阈值 | 本轮加价 | 原 A03 报价 HKD | 下轮建议 | 同口径报价差 | 实际事件 | 消费前轮事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,c in checks['cases'].items():
        for p in c['proofs']:
            j=p['judgment'];lines.append(f"| {name} | {p['identity']['organization_id']} | {p['scope']['tick']} | {j['material_index']['value']} | 1.05 | {p['original_quote_journal']['observed']['applied_markup_rate']} | {p['current_original_quote']['total_price']} | {j['next_markup_rate']} | {j['change_from_previous_quote'] if j['change_from_previous_quote'] is not None else '无'} | {p['actual_event']['event_id']} | {', '.join(j['consumed_event_ids']) or '无'} |")
    lines+=['','48 个技术任务全部形成结果，8 次原宏观监测执行、8 次原 A03 私有报价，4 个后轮原 A03 消费及 4 个后轮原 A01 消费。',
        '独立假设：2 panel、工厂单位成本 80 HKD/panel、基础加价 0.25；原 A03 算得 200 HKD。实际指数超过独立授权阈值 1.05，原 A01 建议附加 0.05；确认原宏观已执行后，下轮原 A03 用 0.30 算得 208 HKD。低组保持 200 HKD。原单位成本、产品、目的地和服务口径不变。',
        '无量纲指数不能折算货币成本或市场成交价；原 A03 的产品、库存、产能和物流是单独声明的合成私有资料。A01 的实物容量和预测保持 unknown。',
        '未发布正式 SupplyOffer、未向买方交付报价、未接单、未调库存或改进实物可靠性。原 scheduler 的归一化能力更新保留，但不能据此宣称实物改善。',
        '原 worker 保存的 source_reading 是组装读取子集；动态监测政策/观测对应输入计划、绑定 source_sha256 和原 A01 类型化结果，不伪称全部动态读取都在该快照中。','',
        '全新目录运行：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_supplier_monthly_prices `",'  --config config/supplier_monthly_prices_chain.json `','  --output output/integration/goal3f_supplier_prices_my_run','```','',
        '只读核验：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_supplier_monthly_prices --check-only --output '{directory.as_posix()}'",'```','',
        '输入、决定、原执行事件、反馈及后轮消费者的身份和摘要对应关系见 checks.json；原请求、持久任务与日志见 high/low/runtime。',
        '月度累计 18/32，14 项仍阻塞；本轮只新增 Supplier.monitor_material_prices，库存调整和供应可靠性仍阻塞。GOAL 3 及原 PLAN 未全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/professional_monthly_native.py','integration/supplier_monthly_prices.py','integration/supplier_monthly_prices_development.py',
        'integration/verify_supplier_monthly_prices.py','src/actions/contracts/supplier_monthly_prices.py','src/actions/contracts/supplier_objects.py',
        'src/actions/roles/supplier_monthly_prices.py','src/actions/roles/supplier.py','config/supplier_monthly_prices_chain.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/供应商月度价格监测接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'supplier-monthly-prices-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/supplier_monthly_prices_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile);run_existing_input(directory/name,assembly_hook='integration.supplier_monthly_prices:configure_assembly')
    else:
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
