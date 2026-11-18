"""Fixed GOAL 3G native suspension feedback and detailed-source boundaries.

Reuses the original construction query and Contractor A04. It creates no
detailed task release, physical work, measurement or independent certificate.
"""
import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import _write,verify_bundle
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest


GATES={
    'readiness':{'actions':['CONTRACTOR-A06'],'handlers':['integration.contractor_readiness_actions:ContractorReadinessActionAssembler'],
        'missing':['original_own_task_mandate_gates_predecessors','actual_exclusive_inputs_and_independent_verification','native_task_release_issuer_and_query']},
    'physical_execution':{'actions':['CONTRACTOR-A07'],'handlers':['integration.contractor_execution_actions:ContractorExecutionActionAssembler'],
        'missing':['authentic_released_task_and_execution_gates','physical_crew_equipment_stock_rules_and_conditions','atomic_actual_work_consumption_cost_quality_issuer_and_query']},
    'work_inspection':{'actions':['CONTRACTOR-A08','ENGINEER-A08'],'handlers':['integration.contractor_quality_actions:ContractorQualityActionAssembler','integration.engineer_inspection_actions:EngineerInspectionActionAssembler'],
        'missing':['original_physical_work_requirements_and_observation_evidence','authorized_supported_self_or_independent_inspection_method','actual_inspection_disposition_recheck_issuer_and_query']},
    'measurement':{'actions':['CONTRACTOR-A10'],'handlers':['integration.contractor_payment_actions:ContractorPaymentActionAssembler'],
        'missing':['authentic_original_work_and_measurement_history','effective_contract_valuation_and_settlement_rules','actual_measurement_application_and_result_issuer_query']},
    'certification':{'actions':['QS-A08'],'handlers':['integration.qs_payment_actions:QSPaymentActionAssembler'],
        'missing':['actual_eligible_work_measurement_rates_and_complete_certificate_history','independently_received_certification_authority_and_basis','atomic_signed_certificate_issuer_original_query_and_owner_receipt']},
    'construction_variation':{'actions':['CONTRACTOR-A09','ARCHITECT-A09','ENGINEER-A09'],
        'handlers':['integration.contractor_claim_actions:ContractorClaimActionAssembler','integration.architect_change_actions:ArchitectChangeActionAssembler','integration.engineer_change_actions:EngineerChangeActionAssembler'],
        'missing':['original_issue_used_deliverable_obligation_and_change_authority','authentic_work_impacts_and_independent_professional_calculations','actual_change_notice_revision_registration_recipient_and_outcome']},
}


def validate_config(config):
    require(config['schema_version']=='construction-chain.v1' and config['ticks']==3
        and config['max_prior_accept_terms']==999 and config['max_prior_construction_suspensions']==1
        and config['scenarios']=={'suspended':{'suspension_project_design_quality':0.0},
            'healthy':{'suspension_project_design_quality':1.0}},'Unsupported fixed construction configuration')


def run_scenario(directory,*,run_id,config,profile):
    from integration.contractor_formation_native_development import build_bundle
    directory.mkdir(parents=True,exist_ok=False)
    build_bundle(directory/'input',run_id=run_id,max_prior_accept_terms=config['max_prior_accept_terms'],
        max_prior_construction_suspensions=config['max_prior_construction_suspensions'],
        with_suspension_project=True,**profile)
    verify_bundle(directory/'input')
    args=[sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.contractor_formation_native:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original construction run failed; retain logs and inspect original task journal')


def verify_scenario(directory,*,suspended,quality):
    verify_bundle(directory/'input');require(read(directory/'exit.json')['exit_code']==0,'Native process failed')
    initial=read(directory/'input/macro-request.json');result=read(directory/'runtime/result.json')
    simulation=result['simulation'];host=result['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==3,'Construction window incomplete')
    original=one(initial['initial_projects'],lambda p:p['project_id']=='terms-existing-suspension','Initial construction missing')
    require(original['current_stage']=='construction' and not original['event_log']
        and original['performance']['design_quality']==quality
        and original['performance']['defect_rate']==1-quality,'Initial condition changed or result was prefilled')
    events=[e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Native observer error')
    project=one(simulation['project_results'],lambda p:p['project_id']==original['project_id'],'Construction project missing')
    suspensions=[e for e in project['event_log'] if e['event_type']=='project_suspended']
    require(len(suspensions)==int(suspended),'Original construction gate did not produce the expected actual outcome')
    if suspended:
        require(project['current_stage']=='suspended' and suspensions[0]['tick']==1
            and suspensions[0]['agent_id'] is None and suspensions[0]['data']=={}
            and suspensions[0]['description']=='Serious safety or quality issue','Suspension was relabeled or attributed to a party')
    else:
        require(any(e['event_type']=='construction_progress_updated' for e in project['event_log']),
            'Healthy original project never executed its aggregate construction update')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        saved=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_formation_results')]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'An actual native or A04 task remains unresolved')
    records=host['requests'];require(len(records)==2,'Expected first/later A04 requests missing')
    for r in records:
        digest_valid(r);require(r==metadata[r['key']],'Export differs from durable original A04 request')
    first=one(records,lambda r:r['scope']['project_id']=='terms-first','First A04 missing')
    later=one(records,lambda r:r['scope']['project_id']=='terms-followup','Later A04 missing')
    require(first['observed']['own_construction_suspensions']['suspensions']==[],'Same-tick event leaked into first A04')
    history=later['observed']['own_construction_suspensions'];digest_valid(history)
    require(len(history['suspensions'])==int(suspended) and history['organization_id']=='terms-contractor'
        and history['as_of_tick']==2,'Later A04 changed its own earlier event scope')
    for h in history['suspensions']:
        e=one(events,lambda e:e['event_id']==h['event_id'],'Consumed actual event missing')
        contract=one(project['contracts'],lambda c:c['contractor_id']=='terms-contractor','Actual dated main contract missing')
        engagement=one(project['engagements'],lambda g:g['engagement_id']==h['engagement_id'],'Original own engagement missing')
        require(h['source_event_sha256']==task_digest(e) and h['contract_sha256']==task_digest(contract)
            and h['project_id']==project['project_id'] and h['contractor_id']==project['selected_contractor_id']
            and h['signed_tick']==contract['signed_tick']<=e['tick']<later['scope']['tick']
            and engagement['agent_id']==h['contractor_id'] and engagement['contractual_obligation'],
            'Later A04 lost exact original event/party/contract/engagement correspondence')
    require(later['observed']['private_revision_preference'] is suspended
        and later['observed']['suspension_preference_requests_price_review'] is suspended,
        'Actual history was merely printed and did not enter the original private preference')
    identity=TaskIdentity(**later['identity'])
    worker=one(saved,lambda r:r['identity']==identity.as_dict(),'Later original result missing')
    digest_valid(worker)
    require(worker['result']['payload']['choice']==('revise' if suspended else 'accept')
        and task_digest(worker['result'])==worker['result_sha256']==later['result_sha256'],
        'Original A04 did not form expected bounded result')
    require(any(s['projection'].get('content_hash')==task_digest(later['observed']) for s in worker['source_reading']),
        'Saved original micro input did not bind actual observed history')
    match=lambda t,purpose,action:t['identity']['purpose']==purpose and t['identity']['action_id']==action
    proposal=one(tasks,lambda t:match(t,'propose','decide_contract_terms') and t['output']['factors']['native_formation_scope']==later['scope'],
        'Later actual proposal missing')['output']
    final=one(tasks,lambda t:match(t,'decide','contract_negotiation') and t['output']['data']['native_formation_scope']==later['scope'],
        'Later actual final decision missing')['output']
    executed=one(events,lambda e:e['project_id']=='terms-followup' and e['tick']==2
        and e['event_type']=='contract_negotiation_recommendation','Actual later macro execution missing')
    action='request_revision' if suspended else 'accept_terms'
    require(proposal['action_type']==final['action_type']==executed['data']['selected_action']==action
        and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==later['result_sha256']
        and executed['data']['individual_decision']['decision_factors']['micro_result_sha256']==later['result_sha256']
        and executed['data']['individual_decision']['decision_factors']['micro_task_key']==identity.key
        and executed['agent_id']==identity.organization_id and executed['data']['error'] is None,
        'Original macro did not process the exact later micro result')
    blocked_actions={a for g in GATES.values() for a in g['actions']}
    require(not any(t['identity']['purpose']=='action' and t['identity']['action_id'] in blocked_actions for t in tasks),
        'A detailed stage was invoked without verified authentic sources')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only check modified actual task journal')
    return {'status':'actual_suspension_to_later_A04_verified_detailed_execution_measurement_certification_blocked',
        'initial_design_quality':quality,'native_ticks':3,'actual_suspension_events':suspensions,
        'first_micro_identity':first['identity'],'later_micro_identity':later['identity'],
        'later_micro_result_sha256':later['result_sha256'],'later_input_sha256':worker['source_reading_sha256'],
        'consumed_own_suspensions':history,'private_revision_preference':suspended,'micro_choice':worker['result']['payload']['choice'],
        'actual_later_execution':executed,'technical_tasks':len(tasks),
        'executed_micro_actions':dict(Counter(t['identity']['action_id'] for t in tasks if t['identity']['purpose']=='action')),
        'native_event_counts':dict(Counter(e['event_type'] for e in events)),
        'native_validation_diagnostics':[e for e in events if e['event_type']=='invalid_action'],
        'native_construction_final_stage':project['current_stage'],
        'native_aggregate_progress':project['performance']['actual_progress'],
        'detailed_actions_invoked':0,'journal_sha256':before,'read_only':True}


def source_boundaries():
    from integration.contractor_construction_source_review import _source
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    producers=[_source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine._handle_construction')]
    producers += [_source(macro,'simulation/project_state_update_engine.py','ProjectStateUpdateEngine.'+n)
        for n in ('update_construction_state','update_construction_progress','update_construction_quality',
            'record_construction_process_events','_record_inspection_event','_record_payment_event')]
    for p in producers:p['path']=(macro/p['path']).relative_to(ROOT).as_posix()
    stages={}
    for name,gate in GATES.items():
        sources=[]
        for handler in gate['handlers']:
            module,symbol=handler.split(':');getattr(importlib.import_module(module),symbol)
            sources.append(_source(ROOT,module.replace('.','/')+'.py',symbol))
        stages[name]={**gate,'status':'blocked_missing_verified_native_sources','existing_handlers':sources,'micro_invocations':0}
    return {'batch':'3G','native_producers':producers,'executed_feedback_consumer':[
        _source(ROOT,'integration/bindings/gba_v1_construction_suspensions.py','read_own_construction_suspensions'),
        _source(ROOT,'integration/contractor_formation_native_sources.py','formation_sources')],
        'stages':stages,'boundary':'Native construction remains the original aggregate mechanism. Actual own suspension informs later A04 only; no detailed task release, work, measurement, independent inspection or certificate is inferred. Variation/clarification requests and resolution remain detailed-source blocked; completion regulation remains batch 3D.',
        'next_step':'Bind independently equivalent original detailed producer/issuer/query and exact authorized original source versions to the existing typed components; preserve unknown outcomes. Do not synthesize core_event_id or measurements from progress.'}


def write_delivery(directory,checks):
    lines=['# GOAL 3G 施工反馈、计量与核证接线记录','',
        '已实跑：原施工暂停 → 自身较早事件查询 → 原 Contractor A04 后续价格复核 → 原宏观实际谈判建议。',
        '未接通：详细施工准备/放行、物理执行、工程检验、计量、独立核证及施工变更；不得将本记录算作上述动作完成。','',
        '| 初始质量场景 | 实际暂停 | 后轮原 A04 | 原宏观实际执行 |', '| --- | --- | --- | --- |']
    for name,s in checks['scenarios'].items():
        lines.append(f"| {name} / {s['initial_design_quality']} | {len(s['actual_suspension_events'])} | {s['micro_choice']} | {s['actual_later_execution']['event_id']} / {s['actual_later_execution']['data']['selected_action']} |")
    lines += ['','新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_construction_chain `",
        '  --config config/construction_chain.json `','  --output output/integration/goal3g_my_run','```','',
        '只读复核：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_construction_chain --check-only --output '{directory.as_posix()}'",'```','',
        '原编制器在引擎构造前声明既有主合同、承包商委任及原生初始质量；暂停不预填。两组差异只走既有 suspension_project_design_quality 配置入口。',
        '原宏观施工门槛实际产生事件。事件不含责任方/详细原因，查询核对原项目、较早时点、合同和委任；仅作为本承包商后续价格复核偏好。原 A04 仍使用独立授权的允许变更；没有用汇总事件补造工作或财务事实。',
        'checks.json 保存输入质量、实际事件摘要、后轮微观身份/来源摘要/结果、原宏观谈判建议的对应关系；runtime/ 保留原进程输出和任务库。source-boundaries.json 定位实际原生生产者、已复用接线及六类阻塞。',
        '原生 execute_work 的本地 validation_only 动作因 engagement_status 字段触发冻结宏观校验，invalid_action 诊断完整保留，不能计作成功动作。原宏观仍执行其独立的汇总状态更新或暂停门槛，不等于细粒度 WorkExecution；原观察器错误为零。详细动作执行数为零，变更、独立核证及实体验收仍未覆盖。',
        f"宏观 {checks['macro']['file_count']} 文件基线及全部 Python 源码未改；GOAL 3 及原 PLAN 未完成。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/verify_construction_chain.py','config/construction_chain.json','config/gba_v1_business_wiring.json',
        'docs/施工计量核证接线与验收.md','docs/宏观动作接线清单.md','integration/contractor_formation_native.py',
        'integration/contractor_formation_native_sources.py','integration/bindings/gba_v1_construction_suspensions.py',
        'integration/contractor_formation_native_development.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'construction-chain-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    scenarios={name:verify_scenario(directory/name,suspended=name=='suspended',
        quality=profile['suspension_project_design_quality']) for name,profile in config['scenarios'].items()}
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro sources changed')
    return {'batch':'3G','status':'actual_own_construction_suspension_feedback_verified_detailed_stages_blocked',
        'scenarios':scenarios,'detailed_gates':{k:'blocked_missing_verified_native_sources' for k in GATES},
        'macro':macro,'overall_goal3_complete':False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'config/construction_chain.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--check-only',action='store_true');args=p.parse_args(argv)
    directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            run_scenario(directory/name,run_id=config['run_id']+'-'+name,config=config,profile=profile)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:
        _write(directory,'checks.json',checks);_write(directory,'source-boundaries.json',source_boundaries());write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_unchanged_files':checks['macro']['file_count']}))


if __name__=='__main__':main()
