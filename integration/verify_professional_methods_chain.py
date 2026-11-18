"""Verify original A12 method choices, native monthly execution and later own consumption."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.professional_methods_development import build_bundle
from integration.professional_methods_native import MonthlyMethodPlan,bind_sources,result_judgment,OPERATIONS,CAPABILITIES,BOUNDARY
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='professional-methods-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'regulatory_pressure_index':0.9},'low':{'regulatory_pressure_index':0.2}},
        'Only the fixed original regulatory-pressure difference is supported by this representative proof')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original monthly methods process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events'];plans=read(directory/'input/professional-methods-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==4,'Two roles over two actual monthly ticks required')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Native observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers={role:[json.loads(v) for v, in db.execute('SELECT record FROM '+table)] for role,table in
            [('Architect','architect_learning_results'),('Engineer','engineer_learning_results')]}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'A native/micro task is unresolved or changed')
    micros={TaskIdentity(**r['identity']).key:r for rows in workers.values() for r in rows}
    for micro in micros.values():
        digest_valid(micro);require(micro['result_sha256']==task_digest(micro['result'])
            and micro['source_reading_sha256']==task_digest(micro['source_reading']),'Original A12 result or reading changed')
    proofs=[]
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['role'])):
        digest_valid(record);require(metadata[record['key']]==record and record['state']=='formed','Original durable monthly record changed')
        identity=TaskIdentity(**record['identity']);micro=micros[identity.key];scope=record['scope'];observed=record['observed']
        require(identity.organization_id==scope['organization_id'] and identity.role==scope['role'] and identity.action_id==identity.role.upper()+'-A12'
            and identity.purpose=='action' and record['result_sha256']==micro['result_sha256'],'Original monthly role/action/result substituted')
        plan=MonthlyMethodPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==scope['tick'],'Original plan missing'))
        require(record['context']==plan.context.model_dump(mode='json') and record['action_input']==plan.action_input,'Original invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Actual original macro input binding changed')
        profile=observed['native_profile'];request_profile=record['native_request']['agent'];field=CAPABILITIES[identity.role]
        require(profile['organization_id']==identity.organization_id==request_profile['agent_id']
            and profile['role']==identity.role==request_profile['role'] and profile['capability_field']==field
            and profile['capability']==request_profile['capabilities'][field]
            and profile['available_resource']==request_profile['resources']['available_resource']
            and profile['total_resource_capacity']==request_profile['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],
            'Observed native capability/free resource is not the actual own request profile')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Original dynamic source binding changed')
        observation=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyMethodObservation','A12 never read its actual monthly observations')['projection']
        policy=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyMethodPolicy','A12 never read its independent policy')['projection']
        require(observation==one(objects,lambda r:r['ref']==observation['ref'],'Bound observation missing')['value']
            and any(r['projection'].get('content_hash')==task_digest(observed) for r in micro['source_reading']),
            'A12 did not consume exact actual inputs and own outcome evidence')
        state=one(micro['source_reading'],lambda r:r['ref']['kind']==identity.role+'LearningState','Original private learning state missing')['projection']
        capability=one(micro['source_reading'],lambda r:r['ref']['kind']=='Capability','Original private capability projection missing')['projection']
        require(state['coverage']=='unknown' and capability['status']=='unknown' and not capability['verified_capability_codes']
            and not capability['qualification_refs'] and not state['execution_refs'] and plan.action_input['learning_profile_ref'] is None,
            'Unknown detailed history, training or credentials were asserted complete')
        initial=one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==scope['tick'],'Initial plan missing')
        placeholder=one(initial['objects'],lambda r:r['ref']==observation['ref'],'Original observation placeholder missing')['value']
        require(all(placeholder[k] is None for k in ['regulatory_pressure','native_capability','native_free_ratio','prior_own_outcomes']),
            'Actual inputs or outcome history were prefilled before execution')
        history=observed['prior_own_monthly_outcomes'];require(history==observation['prior_own_outcomes'] and len(history)==scope['tick']-1,
            'Actual own monthly history is incomplete or was not consumed')
        for h in history:
            event=one(events,lambda e:e['event_id']==h['event_id'],'Earlier original native monthly event missing')
            prior=micros[TaskIdentity(**h['micro_identity']).key];previous=result_judgment(prior)
            require(event['agent_id']==identity.organization_id and event['tick']==h['tick']<scope['tick']
                and h['source_event_sha256']==task_digest(event) and h['micro_result_sha256']==prior['result_sha256']
                and h['participated']==previous.participate and h['method_focus']==previous.method_focus
                and h['prior_observed_capability']==previous.native_capability.model_dump(mode='json')
                and h['operation']==event['data']['operation']==(OPERATIONS[identity.role] if previous.participate else 'maintain_operations')
                and h['capability_update']==event['data'].get('capability_update'),
                'Later A12 used another organization, future event, fabricated completion or different micro artifact')
        judgment=result_judgment(micro)
        require(policy['baseline_requirement']['value']=='0.4' and policy['regulatory_pressure_weight']['value']=='0.5'
            and policy['minimum_shortfall']['value']=='0.05' and policy['minimum_free_ratio']['value']=='0.2'
            and policy['maximum_prior_improvements']==1,'Independent private policy changed')
        pressure=Decimal(str(observed['macro_environment']['regulatory_pressure_index']))
        current=Decimal(str(profile['capability']));free=Decimal(str(profile['free_ratio']))
        target=min(Decimal(1),Decimal('0.4')+Decimal('0.5')*pressure);shortfall=target-current
        count=sum(h['participated'] for h in history)
        require(judgment.regulatory_pressure.model_dump(mode='json')==observation['regulatory_pressure']
            and judgment.native_capability.model_dump(mode='json')==observation['native_capability']
            and judgment.native_free_ratio.model_dump(mode='json')==observation['native_free_ratio']
            and Decimal(judgment.required_capability_index)==target and Decimal(judgment.capability_shortfall)==shortfall
            and judgment.prior_actual_improvement_count==count and judgment.consumed_event_ids==[h['event_id'] for h in history]
            and judgment.prior_method_focus==[h['method_focus'] for h in history if h['participated']],
            'Original A12 did not calculate from current macro pressure, native profile and exact earlier executed work')
        participate=shortfall>=Decimal('0.05') and free>=Decimal('0.2') and count<1
        require(judgment.participate is participate and participate is (high and scope['tick']==1)
            and judgment.operation==OPERATIONS[identity.role] and policy['method_focus'] in judgment.method_focus,
            'Original business choice lacks its macro/capability/actual-prior-work basis')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original monthly final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==scope['tick'],
            'Actual original monthly execution missing')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['action_type']==final['action_type']==judgment.operation
            and event['data']['operation']==(judgment.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==judgment.interpretation+' '+judgment.method_focus
            and event['data']['decision_source']=='llm_agent','Actual native operation differs from its deciding original micro result')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Original professional profile missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==scope['tick'] and m.get('operation')==event['data']['operation'],'Actual native operation memory missing')
        require(memory['label']==event['data']['label'] and memory['capability_update']==event['data'].get('capability_update')
            and memory['decision_factors']==event['data']['decision_factors'],'Actual retained memory differs from native execution')
        if history:
            require(all(h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick']
                and m.get('operation')==h['operation'],'Earlier own retained monthly memory missing') for h in history),
                'Later A12 feedback substitutes original native memory')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'actual_observation':observation,'independent_policy':policy,
            'original_unknown_private_history':state,'original_unknown_private_capability':capability,
            'judgment':judgment.model_dump(mode='json'),'micro_result_sha256':micro['result_sha256'],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),
            'actual_retained_memory':memory,'consumed_own_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed the original task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,
        'actual_improvement_operations':sum(p['judgment']['participate'] for p in proofs),
        'later_own_improvement_consumers':sum(p['judgment']['prior_actual_improvement_count']>0 for p in proofs),
        'database_sha256':before,'native_random_capability_updates_unattributed':[
            {'organization_id':p['scope']['organization_id'],'tick':p['scope']['tick'],'actual_operation':p['actual_event']['data']['operation'],
             'capability_update':p['actual_event']['data'].get('capability_update')}
            for p in proofs if p['actual_event']['data'].get('capability_update') is not None]}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Macro sources changed during execution')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(v,name):return json.dumps(v,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    originals={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,value in originals.items():
        require(value['macro_environment'].pop('regulatory_pressure_index')==config['scenarios'][name]['regulatory_pressure_index'],
            'Original controlled initial regulatory pressure changed')
    require(normalized(originals['high'],'high')==normalized(originals['low'],'low'),
        'Controlled original macro inputs differ beyond regulatory pressure and run identifiers')
    require(normalized(read(directory/'high/input/professional-methods-input.json'),'high')
        ==normalized(read(directory/'low/input/professional-methods-input.json'),'low'),'Private policies/predeclared sources differ across controlled cases')
    require(cases['high']['actual_improvement_operations']==cases['high']['later_own_improvement_consumers']==2
        and cases['low']['actual_improvement_operations']==cases['low']['later_own_improvement_consumers']==0,
        'Expected two actual original method improvements and two later own consumers')
    contacts=[]
    for role,operation in OPERATIONS.items():
        actual=[p for p in cases['high']['proofs'] if p['scope']['role']==role and p['judgment']['participate']]
        consumers=[p for p in cases['high']['proofs'] if p['scope']['role']==role and p['judgment']['prior_actual_improvement_count']>0]
        contacts.append({'macro_action':role+'.'+operation,'micro_action':role.upper()+'-A12 optional monthly observation analysis',
            'macro_input':'Actual original regulatory_pressure_index and current own native capability/free resource profile',
            'return_path':'Original monthly proposal → final decision → original scheduler operation and retained memory',
            'feedback_consumer':'Later own original A12 reads the same executed event and prior method-focus artifact, and uses the count to constrain new improvement',
            'actual_events':[{'scenario':'high','event_id':p['actual_event']['event_id'],'event_sha256':p['actual_event_sha256']} for p in actual],
            'later_consumers':[{'scenario':'high','identity':p['identity'],'prior_actual_improvement_count':p['judgment']['prior_actual_improvement_count'],
                'consumed_own_history':p['consumed_own_history']} for p in consumers]})
    return {'batch':'3C-methods','status':'two_native_monthly_method_improvements_verified_detailed_training_and_credentials_still_blocked',
        'cases':cases,'contacts':contacts,'macro':macro,'overall_goal3_complete':False,'boundary':BOUNDARY}


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],'boundary':checks['boundary'],'overall_goal3_complete':False})
    (directory/'RUN_RECORD.md').write_text('\n'.join(['# GOAL 3C 建筑师与工程师月度方法改进','',
        '原宏观请求 → 原 A12 月度观察分析 → 原提案/最终确认 → 原月度实际执行 → 后轮同机构原 A12。','',
        '| 期初监管压力 | 首轮要求指数 | 首轮实际能力指数 | 首轮缺口 | 原实际动作 | 第二轮 |',
        '| --- | --- | --- | --- | --- | --- |',
        '| 0.9 | 0.85 | 0.6 | 0.25 | 两角色分别执行 improve_design_capability / improve_engineering_capability | 读取同一次实际执行，已开展次数为 1，暂缓新活动 |',
        '| 0.2 | 0.50 | 0.6 | -0.10 | 两角色均拒绝新改进，原宏观执行 maintain_operations | 仍按真实能力和已开展次数判断 |','',
        '两组只改变原配置 regulatory_pressure_index；种子 42，私有阈值、能力初始配置与其他输入除运行标识外一致。观测与后轮回执在执行时绑定，未预填。',
        '两个角色的原 A12 以 record_feedback 分支承载类型化方法改进判断；正式私有学习历史 coverage 和能力 status 均保持 unknown。仅新设的月度分析分支使用真实月度观测，不把空列表视作完整学习或资质历史；原正式学习、训练和资质检查继续保留。',
        '实际原事件与机构记忆核验，不将 proposal 或微观完成当作宏观执行。两项改进行为均有第二轮本机构原 A12 消费同一实际事件、先前方法重点及结果摘要。窗口末轮未声称有下一轮。',
        '原 scheduler 的随机能力更新也会发生在 maintain_operations。两组第二轮观察到的能力指数同为 0.61；不能由此声称本轮活动导致能力提升、训练完成或资质续期。','',
        f"本次两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个技术任务全部形成结果，8 项 A12 月度判断，2 项实际改进活动和 2 项后轮原动作消费。",
        '完整输入、规则、计算、原微观结果、提案/最终确认、完整原事件、原机构记忆与后轮使用见 checks.json。宏观源码和既有交付哈希未改。','',
        '新目录启动：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_methods_chain `",
        '  --config config/professional_methods_chain.json `','  --output output/integration/goal3c_methods_my_run','```','',
        '只读核对：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_methods_chain --check-only --output '{directory.as_posix()}'",'```','',
        '本轮新增两项月度业务，累计 14/32，18 项月度业务及其他详细接口/来源仍阻塞。GOAL 3 与原 PLAN 未完成。','']),encoding='utf-8')
    names=['src/actions/contracts/professional_monthly_methods.py','src/actions/contracts/architect_learning_objects.py',
        'src/actions/roles/professional_monthly_methods.py','src/actions/roles/service_learning.py','integration/professional_monthly_native.py',
        'integration/professional_methods_native.py','integration/professional_methods_development.py','integration/verify_professional_methods_chain.py',
        'config/professional_methods_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
        'docs/专业月度方法改进接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'professional-methods-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/professional_methods_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.professional_methods_native:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
