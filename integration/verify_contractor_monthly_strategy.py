"""Run or read-only verify actual private strategy execution and later A02 reuse."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.contractor_monthly_strategy_development import build_bundle
from integration.contractor_monthly_strategy import MonthlyContractorStrategyPlan,bind_sources,bind_bid_sources,policy_of,result_judgment,BOUNDARY
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.actions.contracts.common import EvidenceRecord
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='contractor-monthly-strategy-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'material_price_index':1.2},'low':{'material_price_index':0.8}},'Unsupported fixed private bid-strategy comparison')


def verify_scenario(directory,*,high):
    verify_bundle(directory/'input');require(read(directory/'exit.json')['exit_code']==0,'Actual native strategy run failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];bids=host['bid_requests'];events=host['original_global_events']
    plans=read(directory/'input/contractor-monthly-strategy-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==len(bids)==2,'Two actual original months required')
    require(host['boundary']==BOUNDARY and not any(e['data'].get('agent_observer_errors') for e in events),'Boundary changed or original observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM commercial_action_results')]
        bid_workers=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_bid_results')]
    require(len(tasks)==16 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task changed or unresolved')
    require(sum(t['identity']['purpose']=='action' for t in tasks)==4 and len(workers)==len(bid_workers)==2,'Unexpected business action, submission or transition')
    proofs=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Original own strategy journal changed')
        identity=TaskIdentity(**record['identity']);scope=record['scope'];tick=scope['tick'];org=identity.organization_id;observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original A12 result missing');digest_valid(micro)
        require(identity.action_id=='CONTRACTOR-A12' and identity.role=='Contractor' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result']),'Original A12 identity/result changed')
        require(one(tasks,lambda t:t['identity']==identity.as_dict(),'Original A12 task missing')['output']==micro['result'],'Original A12 task and result disagree')
        plan=MonthlyContractorStrategyPlan.model_validate(one(plans,lambda p:p['organization_id']==org and p['tick']==tick,'Original own plan missing'))
        require(record['context']==plan.context.model_dump(mode='json') and record['action_input']==plan.action_input,'Original declared invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request']) and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and record['native_request']['agent']['agent_id']==org and record['native_request']['agent']['role']=='Contractor','Observed actual native request changed')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Actual strategy source binding changed')
        def source(kind):return one(objects,lambda r:r['ref']['kind']==kind,'Missing bound '+kind)['value']
        state=source('ContinuationState');original_observation=source('Observation');observation=source('MonthlyBidStrategyObservation');policy=policy_of(plan)
        require(state['coverage']=='unknown' and state['as_of']==record['context']['business_time'] and not state['contract_refs'] and not state['commitment_refs']
            and not state['material_refs'] and not state['obligation_refs'],'Monthly private policy fabricated a complete commercial ledger or transition')
        evidence=one(objects,lambda r:r['ref']==original_observation['original_source_ref'],'Actual input evidence missing')['value']
        require(original_observation['verified']=={'state':'known','value':True} and original_observation['event_key']=='actual-native-request:'+observed['native_request_sha256']
            and original_observation['source_sha256']==task_digest(EvidenceRecord.model_validate(evidence).model_dump(mode='json'))
            and evidence['content_hash']==task_digest(observed) and original_observation['outcome_code']=='actual_native_material_index_observation',
            'Original lesson source is not the actual current observed native input')
        require(micro['result']['payload']['source_refs']==state['observation_refs']==[original_observation['ref']]
            and micro['result']['payload']['learning_method_ref']==source('LearningMethod')['ref'],'Original closed lesson result dropped its actual source or selected rule')
        snapshot=snapshots[identity.key];require(snapshot['context']==record['context'] and task_digest(snapshot['action_input'])==identity.input_sha256
            and snapshot['action_input']['observation_refs']==state['observation_refs'],'Original commercial worker changed the exact full invocation')
        j=result_judgment(micro);current=Decimal(str(observed['macro_environment']['material_price_index']));history=observed['prior_own_monthly_outcomes']
        require(len(history)==tick-1,'Strictly earlier actual own strategy outcome missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Actual prior own strategy proof missing')
            require(h['micro_identity']==previous['identity'] and h['micro_identity']['organization_id']==org
                and h['micro_result_sha256']==previous['micro_result_sha256'] and h['source_event_sha256']==task_digest(previous['actual_event'])
                and h['strategy_judgment']==previous['judgment'] and h['operation']=='adjust_bid_strategy' and h['participated'] is True
                and h['tick']<tick,'Later decision did not read the same actually executed own strategy')
        require(policy['base_markup']=='0.20' and policy['risk_markup_increment']=='0.05' and policy['material_index_threshold']['value']=='1.05'
            and j.material_index.model_dump(mode='json')==observation['material_index'] and Decimal(j.material_index.value)==current
            and j.threshold.model_dump(mode='json')==policy['material_index_threshold'] and j.high_material_risk is (current>Decimal('1.05'))
            and j.high_material_risk is high and j.next_private_markup==('0.25' if high else '0.20')
            and j.consumed_event_ids==[h['event_id'] for h in history] and j.consumed_result_sha256==[h['micro_result_sha256'] for h in history],
            'Actual material index or actual own feedback did not affect private strategy judgment')
        bid=one(bids,lambda b:b['scope']==scope,'Current original private A02 missing');digest_valid(bid)
        bm=one(bid_workers,lambda w:w['identity']==bid['identity'],'Original private A02 result missing');digest_valid(bm)
        require(bid==metadata[bid['key']] and bid['state']=='formed' and bid['native_request']==record['native_request']
            and bid['context']==plan.bid.context.model_dump(mode='json') and bid['action_input']==plan.bid.action_input
            and bid['result_sha256']==bm['result_sha256']==task_digest(bm['result']) and bm['identity']['organization_id']==org
            and bm['identity']['action_id']=='CONTRACTOR-A02' and bm['result']['payload']['choice']=='submit_bid'
            and bid['original_private_bid']==bm['result']['payload']['bid'],'Original A02 identity, source invocation or proposal changed')
        bo=bid['observed'];markup=history[-1]['strategy_judgment']['next_private_markup'] if history else policy['base_markup']
        require(bo['prior_own_monthly_outcomes']==history and bo['applied_markup']==markup and bo['native_request_sha256']==observed['native_request_sha256']
            and bo['independent_policy_sha256']==task_digest(policy) and bo['boundary']==BOUNDARY,'A02 did not adopt the confirmed prior executed policy')
        bid_objects=bind_bid_sources(plan,bo);require(task_digest(bid_objects)==bid['source_sha256'],'A02 private policy source binding changed')
        calculations=bm['audit']['method_calls'];price_call=one(calculations,lambda c:c['method_ref']['id']=='micro.contractor.declared_bid_price','Original pricing method not run')
        capacity_call=one(calculations,lambda c:c['method_ref']['id']=='micro.capacity.fixed_location','Original capacity method not run')
        require(price_call['result']['kind']==capacity_call['result']['kind']=='ok' and capacity_call['result']['value']['feasible'] is True
            and price_call['input']['markup_fraction']==markup and price_call['input']['markup_basis_ref']==plan.bid.native_evidence_ref.model_dump(mode='json'),
            'Original A02 pricing/capacity did not actually consume the new private policy')
        line,=price_call['input']['lines'];allowance=price_call['input']['allowance'];offered=bm['result']['payload']['bid']['price']
        require(line['quantity']['value']=='6' and line['quantity']['unit']==line['quantity_unit']=='m2' and line['unit_rate']['value']=='5'
            and allowance['value']=='4' and line['unit_rate']['currency']==allowance['currency']==offered['currency']=='HKD',
            'Macro index replaced an independent quantity, unit cost, allowance or currency')
        expected=Decimal(30)*(Decimal(1)+Decimal(markup))+Decimal(4)
        require(Decimal(offered['value'])==expected and offered==price_call['result']['value']['offered_price'],'Original private price differs from actual pricing calculation')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),'Actual request differs from saved original transport input')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original monthly final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Actual original strategy execution missing')
        require(proposal['accepted'] is final['decision'] is event['data']['decision_accepted'] is True
            and proposal['action_type']==final['action_type']==event['data']['operation']=='adjust_bid_strategy'
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description'] and event['description'].startswith(j.interpretation),'Actual macro execution differs from original micro policy/proposal/final')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Own native agent missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='adjust_bid_strategy','Actual own native memory missing')
        feedback=one(read(directory/'runtime/observations.json')['records'],lambda o:o['event_id']==event['event_id'] and o['organization_id']==org,'Committed own strategy feedback missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors']
            and feedback['payload']['committed'] is True and feedback['payload']['data']['operation']=='adjust_bid_strategy'
            and feedback['payload']['data']['description']==event['description'],'Original memory/committed feedback differs from execution')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'micro_result_sha256':micro['result_sha256'],'actual_observation':observation,
            'original_source_observation':original_observation,'unknown_commercial_state':state,'independent_policy':policy,'judgment':j.model_dump(mode='json'),
            'original_micro_input':snapshot['action_input'],'original_bid_journal':bid,'original_bid_result_sha256':bm['result_sha256'],
            'original_pricing_method_call':price_call,'original_capacity_method_call':capacity_call,'original_proposal':proposal,
            'original_proposal_task_identity':transport,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),
            'actual_native_memory':memory,'original_committed_feedback':feedback,'consumed_own_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed original tasks')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'actual_strategy_operations':2,'original_private_bid_proposals':2,
        'later_own_A12_consumers':1,'later_own_A02_consumers':1,'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,v in inputs.items():require(v['macro_environment'].pop('material_price_index')==config['scenarios'][name]['material_price_index'],'Controlled initial index changed')
    require(normalized(inputs['high'],'high')==normalized(inputs['low'],'low'),'Macro inputs differ beyond original configured material index')
    plans={name:read(directory/name/'input/contractor-monthly-strategy-input.json') for name in cases}
    require(normalized(plans['high'],'high')==normalized(plans['low'],'low'),'Private dossiers or authorized policies differ between controlled cases')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'original initial material_price_index 1.2 versus 0.8 only',
        'boundary':BOUNDARY,'scope':'Bounded original Contractor monthly private markup strategy and actual next A02 calculation; other detailed business remains blocked'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_contractor_monthly_strategy --config config/contractor_monthly_strategy_chain.json --output $OutputDirectory\n",encoding='utf8')
    lines=['# GOAL 3A 月度私有投标加价策略实跑记录','','两组只经原初始场景改变 material_price_index=1.2/0.8。原 A12 使用实际更新后的指数形成规则判断；原宏观实际执行后，下轮原 A02 才采用其加价参数。','',
        '| 场景 | 轮次 | 实际材料指数 | 本轮原 A02 加价 | 原 A02 私有报价 HKD | A12 下轮建议 | 实际执行事件 | 消费前轮事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,c in checks['cases'].items():
        for p in c['proofs']:
            j=p['judgment'];b=p['original_bid_journal'];lines.append(f"| {name} | {p['scope']['tick']} | {j['material_index']['value']} | {b['observed']['applied_markup']} | {b['original_private_bid']['price']['value']} | {j['next_private_markup']} | {p['actual_event']['event_id']} | {', '.join(j['consumed_event_ids']) or '无'} |")
    lines+=['','32 个技术任务全部形成结果：4 次原宏观策略调整，4 次原 A02 私有方案，2 个后轮 A02 消费和 2 个后轮 A12 消费。',
        '独立输入为 6 m2、5 HKD/m2、商业附加 4 HKD、基础加价 0.20；原 A02 实算 30×1.20+4=40。实际材料指数超过授权阈值 1.05，A12 建议附加 0.05；确认原宏观执行后，下轮原 A02 实算 30×1.25+4=41.5。低组维持 40。',
        'A12 保留原闭合 record_lesson 输出、真实 Observation 引用和规则描述引用；新增的是可选的类型化私有风险规则分析，不把它称为原统计学习方法的执行、投标成功率学习或完整商业清账。',
        '完整商业状态 coverage=unknown；独立假设的招标资料、图纸、数量、成本、工期和实物容量仅用于私有方案，不声称正式发布、受邀、提交投标、中选、资源预留或工程执行。原 A02 容量和定价方法的实际调用见 checks.json。','',
        '全新目录运行：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_contractor_monthly_strategy `",'  --config config/contractor_monthly_strategy_chain.json `','  --output output/integration/goal3a_bid_strategy_my_run','```','',
        '只读核验：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_contractor_monthly_strategy --check-only --output '{directory.as_posix()}'",'```','',
        '输入→原 A12 决定→原宏观执行/记忆/反馈→后轮原 A02 方法输入及结果→后轮原 A12 的身份和摘要关系均见 checks.json。',
        '本轮只新增 Contractor.adjust_bid_strategy 的代表性私有加价规则链；月度累计 19/32，13 项仍阻塞，全清单仍有 49 项来源/接口阻塞。GOAL 3 与原 PLAN 未全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    names=['integration/professional_monthly_native.py','integration/contractor_monthly_strategy.py','integration/contractor_monthly_strategy_development.py',
        'integration/verify_contractor_monthly_strategy.py','src/actions/contracts/contractor_monthly_strategy.py','src/actions/contracts/commercial_continuation_objects.py',
        'src/actions/roles/contractor_monthly_strategy.py','src/actions/roles/commercial_continuation.py','config/contractor_monthly_strategy_chain.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/承包商月度投标策略接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'contractor-monthly-strategy-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/contractor_monthly_strategy_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile);run_existing_input(directory/name,assembly_hook='integration.contractor_monthly_strategy:configure_assembly')
    else:
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
