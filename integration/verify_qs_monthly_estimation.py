"""Run fixed independent native cases or verify their retained journals read-only."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.qs_monthly_estimation import (
    MonthlyEstimationPlan,QSMonthlyEstimationApplication,bind_sources,result_judgment,BOUNDARY,
)
from integration.qs_monthly_estimation_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.actions.contracts.common import Reference
from src.actions.contracts.qs_monthly_estimation import MonthlyEstimationPolicy,MonthlyEstimationObservation
from src.actions.roles.qs_monthly_estimation import evaluate
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(set(config)=={'schema_version','run_id','ticks','scenarios'}
        and config['schema_version']=='qs-monthly-estimation-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'material_price_index':1.2},'low':{'material_price_index':0.8}},
        'Unsupported fixed QS index sensitivity controls')


def verify_scenario(directory):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Native QS process did not finish')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events'];initial=read(directory/'input/macro-request.json')
    plans=read(directory/'input/qs-estimation-input.json')['plans'];source_policy=read(directory/'input/source-policy.json')
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==2 and host['boundary']==BOUNDARY,
        'Both actual own monthly QS invocations must finish')
    require({e['event_type'] for e in events}<={'project_state_updated','agent_operation'}
        and not any(e['data'].get('agent_observer_errors') for e in events),'Unexpected lifecycle event or native diagnostic')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM qs_learning_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(len(tasks)==18 and len(workers)==2 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Original task counts, completion or output hashes changed')
    require(len([t for t in tasks if t['identity']['role']=='QS'])==6,'Expected exactly six technical QS tasks over two months')
    schemas=QSMonthlyEstimationApplication.COMPONENTS['QS'][0].SOURCE_SCHEMAS();proofs=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Original durable record changed')
        identity=TaskIdentity(**record['identity']);tick=record['scope']['tick'];observed=record['observed']
        saved=one(workers,lambda w:w['identity']==identity.as_dict(),'Original QS-A12 result missing');digest_valid(saved)
        require(identity.action_id=='QS-A12' and identity.role=='QS' and identity.organization_id==source_policy['organization_id']
            and saved['result_sha256']==record['result_sha256']==task_digest(saved['result'])
            and saved['source_reading_sha256']==task_digest(saved['source_reading'])
            and one(tasks,lambda t:t['identity']==identity.as_dict(),'Original QS-A12 task missing')['output']==saved['result'],
            'Actual original action/result or source provenance changed')
        plan=MonthlyEstimationPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==tick,'Own plan missing'))
        snapshot=snapshots[identity.key]
        require(record['context']==plan.context.model_dump(mode='json')==snapshot['context']
            and record['action_input']==plan.action_input==snapshot['action_input']
            and identity.input_sha256==task_digest(plan.action_input)==saved['audit']['input_sha256'],
            'Authorized invocation/snapshot changed')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and record['native_request']['agent']['agent_id']==identity.organization_id,'Actual macro input binding changed')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Actual bound sources changed')
        for reading in saved['source_reading']:
            supplied=one(objects,lambda r:r['ref']==reading['ref'],'Undeclared source')['value']
            require(reading['projection']==schemas.validate_projection(Reference.model_validate(reading['ref']),supplied).model_dump(mode='json'),
                'Retained typed source differs from actual input/feedback')
        def source(kind):return one(objects,lambda r:r['ref']['kind']==kind,'Required source missing: '+kind)['value']
        policy=MonthlyEstimationPolicy.model_validate(source('MonthlyEstimationPolicy'))
        observation=MonthlyEstimationObservation.model_validate(source('MonthlyEstimationObservation'))
        judgment=result_judgment(saved)
        require(policy.authorized_project_ids==source_policy['authorized_project_ids']
            and policy.baseline_material_index.value=='1' and policy.minimum_relative_change.value=='0.05'
            and policy.minimum_free_ratio.value=='0.2' and policy.maximum_updates==1,'Independent policy changed')
        require(source('QSLearningState')['coverage']==source('Capability')['status']=='unknown'
            and not plan.action_input['forecast_refs'] and not plan.action_input['outcome_refs']
            and not saved['audit']['method_calls'],'Monthly analysis asserted complete forecast history or substituted a formal method')
        for p in observed['own_project_evidence']:
            event=one(events,lambda e:e['event_id']==p['native_event']['event_id'],'Original project estimate event missing')
            initial_project=one(initial['initial_projects'],lambda x:x['project_id']==p['project_id'],'Declared initial mandate missing')
            require(event==p['native_event'] and task_digest(event)==p['native_event_sha256']
                and initial_project['selected_qs_id']==p['selected_qs_id']==identity.organization_id
                and initial_project['current_stage']=='design' and p['reference_estimate']==str(event['data']['planned_cost'])
                and p['unit']=='native_model_cost_unit' and event['tick']==tick,'Borrowed or fabricated project estimate source')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1,'Earlier own actual monthly feedback missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Earlier actual origin missing')
            event=previous['actual_event']
            require(h['review']==previous['judgment'] and h['review_sha256']==task_digest(previous['judgment'])
                and h['micro_identity']==previous['identity'] and h['micro_result_sha256']==previous['micro_result_sha256']
                and h['source_event_sha256']==task_digest(event) and h['operation']==event['data']['operation']
                and h['tick']==event['tick']<tick and event['agent_id']==identity.organization_id
                and h['original_native_memory']['operation']==event['data']['operation']
                and h['original_native_memory']['label']==event['data']['label']
                and h['capability_update']==h['original_native_memory']['capability_update']==event['data'].get('capability_update'),
                'Later review adopted a proposal without the exact actual native result/memory')
        calculated=evaluate(policy,observation,organization_id=identity.organization_id,scope=plan.context.scope,now=plan.context.business_time)
        require(calculated==judgment and judgment.participate is (tick==1) and judgment.prior_actual_update_count==tick-1,
            'Retained micro judgment did not use the actual index, policy and prior execution')
        for item in judgment.indicative_estimates:
            require(Decimal(item['indicative_estimate'])==Decimal(item['reference_estimate'])*Decimal(judgment.applied_material_factor),
                'Macro index did not enter actual private arithmetic')
        if tick==2:
            accepted=Decimal(history[0]['review']['proposed_material_factor'])
            require(Decimal(judgment.applied_material_factor)==accepted
                and judgment.accepted_material_index==history[0]['review']['material_index']['value']
                and judgment.consumed_event_ids==[history[0]['event_id']]
                and Decimal(judgment.relative_index_change)==(Decimal(judgment.material_index.value)-Decimal(judgment.accepted_material_index))/Decimal(judgment.accepted_material_index),
                'Next review did not consume the exact actually accepted earlier private assumption')
            without_history=evaluate(policy,observation.model_copy(update={'prior_own_outcomes':[]}),
                organization_id=identity.organization_id,scope=plan.context.scope,now=plan.context.business_time)
            require(without_history.participate is True and without_history.applied_material_factor!=judgment.applied_material_factor,
                'Prior actual feedback made no difference to the later decision/calculation')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output']['factors'].get('micro_task_key')==identity.key,'Exact original proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output']['data'].get('micro_task_key')==identity.key,'Exact original final decision missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual native activity missing')
        require(proposal['accepted'] is True and proposal['factors']['micro_participation']==final['decision']==judgment.participate
            and proposal['action_type']==final['action_type']=='improve_cost_estimation'
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==saved['result_sha256']
            and final['data']['proposal_response_sha256']==record['proposal_response_sha256']==task_digest(proposal)
            and event['data']['operation']==('improve_cost_estimation' if judgment.participate else 'maintain_operations')
            and event['description']==proposal['data']['description']==judgment.model_dump_json(),
            'Native execution did not follow the exact actual micro judgment')
        proofs.append({'identity':identity.as_dict(),'tick':tick,'actual_macro_input':observed['macro_environment'],
            'own_project_evidence':observed['own_project_evidence'],'judgment':judgment.model_dump(mode='json'),'history':history,
            'micro_result_sha256':saved['result_sha256'],'source_reading_sha256':saved['source_reading_sha256'],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event)})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification mutated the retained journal')
    return {'status':'actual_monthly_judgment_execution_and_later_private_assumption_consumption_verified',
        'proofs':proofs,'technical_tasks':len(tasks),'qs_technical_tasks':6,'native_background_tasks_not_counted_as_micro_coverage':12,
        'read_only_journal_sha256':before,'detailed_forecast_error_calibration_or_cost_accuracy_improvement_proven':False}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name) for name in config['scenarios']}
    high=read(directory/'high/input/macro-request.json');low=read(directory/'low/input/macro-request.json')
    high['macro_environment']['material_price_index']=low['macro_environment']['material_price_index']
    require(high==low,'Original supported initial inputs differ beyond the material index')
    a=read(directory/'high/input/qs-estimation-input.json');b=read(directory/'low/input/qs-estimation-input.json')
    a['run_id']=b['run_id']
    for plan in a['plans']:plan['context']['run_id']=b['run_id']
    require(a==b,'Private declared inputs differ between controlled cases')
    first=[case['proofs'][0] for case in cases.values()]
    require(first[0]['own_project_evidence']==first[1]['own_project_evidence']
        and first[0]['judgment']['applied_material_factor']!=first[1]['judgment']['applied_material_factor']
        and first[0]['judgment']['indicative_estimates'][0]['indicative_estimate']!=first[1]['judgment']['indicative_estimates'][0]['indicative_estimate'],
        'Controlled index difference did not affect an actual calculation over the same own estimate')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    return {'batch':'3C-QS-estimation','status':'bounded_qs_monthly_estimation_contact_verified',
        'overall_goal3_complete':False,'cases':cases,'boundary':BOUNDARY,
        'controlled_input_difference':'Original supported macro_environment.material_price_index=1.2 versus 0.8; same seed, initial project, QS mandate, private policy and inputs',
        'macro':macro}


def write_delivery(directory,checks):
    rows=[]
    for name,case in checks['cases'].items():
        a,b=case['proofs'];j=a['judgment'];k=b['judgment']
        rows.append(f"| {name} | {j['material_index']['value']} | {j['indicative_estimates'][0]['reference_estimate']} × {j['applied_material_factor']} = {j['indicative_estimates'][0]['indicative_estimate']} | {a['actual_event']['event_id']} / improve_cost_estimation | {k['indicative_estimates'][0]['reference_estimate']} × {k['applied_material_factor']} = {k['indicative_estimates'][0]['indicative_estimate']} / maintain_operations |")
    lines=['# GOAL 3C QS 月度估算方法复核运行记录','',
        '已打通限定的月度方法复核、原宏观实际活动和后轮私人指数假设消费。未证明实际成本误差校准或估算精度提高。','',
        '| 场景 | tick 1 实际指数 | tick 1 私人敏感性估算 | 实际执行 | tick 2 消费实际接受系数 |',
        '| --- | --- | --- | --- | --- |',*rows,'',
        '输入指数来自原宏观配置，经原随机环境更新后进入微观实际计算。原设计 planned_cost 是估算参考量，不冒充实际成本。'
        '后轮以同一原事件、微观结果哈希、提案、最终决定和本单位记忆确认上轮执行，再把实际接受的系数用于本轮计算及相对变化判断。'
        '只读核验还移除历史做纯计算对照，证明没有历史时会再次建议更新；该对照不注册或重放业务。','',
        '独立运行（须使用不存在的目录）：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_qs_monthly_estimation --output output/integration/qs_estimation_my_run",'```','',
        '核验本次归档：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_qs_monthly_estimation --check-only --output '{directory.as_posix()}'",'```','',
        '对应关系见 checks.json；完整输入、源读取、原决定和实际事件在各组 input、runtime/result.json 和只读 tasks.sqlite。'
        '每组 18 个技术任务，其中本批 QS 6 个，其余 12 个为原宏观背景任务，不计入新增微观覆盖。','',BOUNDARY,'',
        '本批不新增冻结预测/成熟实际成本配对，不发布正式误差校准修订，也不更改宏观项目估算。GOAL 3 和原 PLAN 均未全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/qs_monthly_estimation.py','integration/qs_monthly_estimation_development.py','integration/verify_qs_monthly_estimation.py',
        'src/actions/contracts/qs_monthly_estimation.py','src/actions/roles/qs_monthly_estimation.py','src/actions/contracts/qs_learning_objects.py',
        'src/actions/roles/service_learning.py','src/actions/roles/qs_learning.py','integration/professional_monthly_native.py',
        'tests/test_qs_monthly_estimation.py','config/qs_monthly_estimation_chain.json','config/gba_v1_business_wiring.json',
        'config/gba_v1_monthly_business_wiring.json','docs/QS月度估算方法复核接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'qs-monthly-estimation-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/qs_monthly_estimation_chain.json');parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.qs_monthly_estimation:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
