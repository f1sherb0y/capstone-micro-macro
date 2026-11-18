"""Run the original native financing/monthly window, and verify saved monitoring evidence."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.bank_monthly_risk import bind_monthly_risk, result_judgment, result_operation
from integration.bank_monthly_risk_development import build_bundle
from integration.contractor_tender_development import _write, verify_bundle
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def run_existing_input(directory):
    source=directory/'input';verify_bundle(source)
    args=[sys.executable,'-m','integration.run','--input',str(source/'macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--allow-native-project-generation','--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(source/'native-host.json'),'--module-assembly-hook','integration.bank_financing_native:configure_assembly',
        '--module-assembly-config',str(source/'assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('x',encoding='utf-8') as stdout,(directory/'stderr.log').open('x',encoding='utf-8') as stderr:
        process=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr,check=False)
    _write(directory,'exit.json',{'exit_code':process.returncode})
    require(process.returncode==0,'Original financing/monthly run failed; retain its actual logs and task journal')


def validate_config(config):
    require(config['schema_version']=='bank-monthly-risk-chain.v1' and config['ticks']==3,'Unsupported original risk window')
    require(config['scenarios']=={'supported':{'financing_condition_index':1.2},'stressed':{'financing_condition_index':0.4}},
        'Controlled cases must only vary original initial financing conditions')


def verify_scenario(directory):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original process did not complete')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    monthly=host['monthly_strategy'];records=monthly['requests'];events=monthly['original_own_monthly_events']
    require(simulation['status']=='completed' and simulation['current_tick']==3 and len(records)==6,'Expected two Banks over three actual ticks')
    project_events=[e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in [*events,*project_events]),'Original native observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM bank_strategy_results')]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task unresolved or changed')
    worker_map={TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r);require(r['result_sha256']==task_digest(r['result']) and r['source_reading_sha256']==task_digest(r['source_reading']),
            'Original saved strategy reading/result changed')
    plans=read(directory/'input/bank-monthly-strategy-input.json')['plans']
    proofs=[]
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);require(metadata[record['key']]==record and record['state']=='formed','Monthly durable workflow changed')
        identity=TaskIdentity(**record['identity']);micro=worker_map[identity.key];scope=record['scope'];observed=record['observed']
        require(identity.action_id=='BANK-A01' and identity.organization_id==scope['organization_id']
            and record['result_sha256']==micro['result_sha256'],'Monthly original bank/action/result substituted')
        plan=one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==scope['tick'],'Original monthly plan missing')
        require(plan['context']==record['context'] and plan['action_input']==record['action_input'],'Original monthly invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Actual original current monthly input changed')
        history=observed['prior_own_monthly_strategy'];cases=observed['received_own_financing_cases']
        require(len(history)==scope['tick']-1,'Own prior actual monthly history incomplete')
        for h in history:
            event=one(events,lambda e:e['event_id']==h['event_id'],'Earlier actual monthly event missing')
            origin=one(records,lambda r:r['scope']==h['native_bank_monthly_scope'],'Original deciding workflow missing')
            previous=worker_map[TaskIdentity(**origin['identity']).key]
            require(event['agent_id']==h['organization_id']==identity.organization_id and h['tick']==event['tick']<scope['tick']
                and h['source_event_sha256']==task_digest(event) and h['operation']==event['data']['operation']==result_operation(previous)
                and h['micro_result_sha256']==previous['result_sha256'] and h['proposal_response_sha256']==origin['proposal_response_sha256'],
                'Monthly feedback substitutes another bank, future event or unexecuted decision')
        own_originals=[r for r in host['requests'] if r['native_request']['agent']['agent_id']==identity.organization_id and r['scope']['tick']<scope['tick']]
        require(len(cases)==len(own_originals),'Received risk-case coverage is not the complete earlier own request set')
        for case in cases:
            parent=one(own_originals,lambda r:r['scope']['project_id']==case['project_id']
                and r['scope']['owner_id']==case['borrower_id'] and r['scope']['tick']==case['observed_tick'],'Received case lacks its actual own original request')
            require(case['organization_id']==identity.organization_id and case['original_inputs']==parent['native_request']['inputs']
                and case['original_request_sha256']==task_digest(parent['native_request'])
                and case['proposal_response_sha256']==parent['proposal_response_sha256'],'Received macro risk estimates changed or were prefilled')
            bank_event=one(project_events,lambda e:e['event_type']=='bank_financing_decision' and e['agent_id']==identity.organization_id
                and e['project_id']==case['project_id'] and e['tick']==case['observed_tick'],'Actual original Bank financing execution missing')
            require(bank_event['data']['proposal_response_sha256']==case['proposal_response_sha256'],'Bank financing execution differs from received case')
            for action,origin in case['original_micro_results'].items():
                original_step=parent['steps'][action]
                require(origin['identity']==original_step['identity'] and origin['result_sha256']==original_step['result_sha256'],
                    'Received risk-case micro origin changed')
            selection=case['actual_own_selection']
            if selection is not None:
                event=one(project_events,lambda e:e['event_id']==selection['event_id'],'Actual financing selection missing')
                require(event['event_type']=='project_financing_selected' and event['project_id']==case['project_id']
                    and event['agent_id']==case['borrower_id'] and event['tick']==case['observed_tick']
                    and event['data']['selected_bank_id']==identity.organization_id and event['data']['accepted'] is True,
                    'Another lender, rejection or synthetic selection was called an own financing outcome')
        objects=deepcopy(plan['objects'])
        from integration.bank_financing_private import evidence_binding
        from integration.bank_monthly_native import BankMonthlyPlan
        evidence_binding(objects,plan['native_evidence_ref'],observed)
        signal=one(objects,lambda r:r['ref']==plan['observation_ref'],'Original monthly history signal missing')['value']
        require(signal['interval']=={'state':'known','value':None},'Original monthly signal was prefilled')
        amount={'value':str(len(history)),'unit':'count','basis_ref':plan['native_evidence_ref']}
        signal['interval']['value']={'lower':amount,'upper':deepcopy(amount)}
        bind_monthly_risk(objects,observed=observed,plan=BankMonthlyPlan.model_validate(plan))
        require(task_digest(objects)==record['source_sha256'],'Actual source binding changed')
        observation=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyBorrowerRiskObservation','Original risk observation was never read')['projection']
        policy=one(micro['source_reading'],lambda r:r['ref']['kind']=='MonthlyBorrowerRiskPolicy','Independent original policy was never read')['projection']
        require(observation==one(objects,lambda r:r['ref']==observation['ref'],'Original bound risk source missing')['value']
            and observation['received_cases']==cases and observation['prior_own_operations']==history,'Original A01 did not read exact actual risk inputs and execution history')
        require(any(r['projection'].get('content_hash')==task_digest(observed) for r in micro['source_reading']),
            'Current macro inputs and own feedback lack consumed source evidence')
        judgment=result_judgment(micro);require(judgment is not None,'Original strategy did not perform risk analysis')
        condition=Decimal(str(observed['macro_environment']['financing_condition_index']));stress=max(Decimal(0),1-condition)
        scores=[min(Decimal(1),Decimal(str(c['original_inputs']['project_risk']))+Decimal(policy['market_stress_weight']['value'])*stress
            +Decimal(policy['borrower_weakness_weight']['value'])*(1-Decimal(str(c['original_inputs']['borrower_financial_capacity'])))) for c in cases]
        maximum=max(scores,default=None);count=sum(h['operation']=='monitor_borrower_risk' for h in history)
        require(judgment.financing_condition.model_dump(mode='json')==observation['financing_condition']
            and Decimal(judgment.market_stress)==stress and judgment.prior_actual_monitoring_count==count
            and [Decimal(s['risk_score']) for s in judgment.case_scores]==scores
            and (None if judgment.maximum_risk_score is None else Decimal(judgment.maximum_risk_score))==maximum,
            'Actual macro financing conditions, case estimates or execution history did not enter original risk computation')
        require(policy['market_stress_weight']['value']=='0.5' and policy['borrower_weakness_weight']['value']=='0.25'
            and policy['monitoring_threshold']['value']=='0.5' and policy['maximum_prior_monitoring']==1,'Independent policy unexpectedly changed')
        monitor=maximum is not None and maximum>=Decimal(policy['monitoring_threshold']['value']) and count<policy['maximum_prior_monitoring']
        require((judgment.operation=='monitor_borrower_risk') is monitor and judgment.monitored_case_count==(len(cases) if monitor else 0),
            'Original monitoring choice bypassed computed risk or actual prior monitoring')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original monthly final missing')['output']
        event=one(events,lambda e:e['agent_id']==identity.organization_id and e['tick']==scope['tick'],'Original monthly execution missing')
        require(event['data']['operation']==proposal['action_type']==final['action_type']==judgment.operation
            and event['data']['decision_accepted'] is proposal['accepted'] is final['decision'] is True
            and event['data']['description']==proposal['data']['description']==judgment.interpretation
            and event['data']['decision_source']=='llm_agent'
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256'],
            'Actual original macro operation does not match its original micro judgment')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Original native bank missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==scope['tick'] and m.get('operation')==judgment.operation,'Native bank operation memory missing')
        require(memory['label']==event['data']['label'] and memory['capability_update']==event['data']['capability_update'],
            'Actual retained native operation differs from original event')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'independent_policy':policy,'actual_observation':observation,
            'micro_result_sha256':micro['result_sha256'],'judgment':judgment.model_dump(mode='json'),'original_proposal':proposal,
            'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),'actual_native_memory':memory,
            'consumed_own_monthly_history':history})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed the original task store')
    diagnostics=[{'identity':t['identity'],'output':t['output']} for t in tasks
        if 'invalid_llm_choice_rejected' in json.dumps(t['output'])]
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'retained_native_diagnostics':diagnostics,
        'monthly_operation_counts':{op:sum(p['judgment']['operation']==op for p in proofs)
            for op in ['review_credit_pipeline','adjust_credit_terms','monitor_borrower_risk']},'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed during execution')
    cases={name:verify_scenario(directory/name) for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    originals={name:read(directory/name/'input/macro-request.json') for name in cases}
    require(originals['supported']['macro_environment']['financing_condition_index']==1.2
        and originals['stressed']['macro_environment']['financing_condition_index']==0.4,'Controlled original configuration changed')
    for value in originals.values():value['macro_environment'].pop('financing_condition_index')
    require(normalized(originals['supported'],'supported')==normalized(originals['stressed'],'stressed'),
        'Controlled original inputs differ beyond financing conditions and run identifiers')
    for relative in ['bank-monthly-strategy-input.json','financing-foundation/bank-financing-input.json','financing-foundation/owner-financing-input.json']:
        require(normalized(read(directory/'supported/input'/relative),'supported')
            ==normalized(read(directory/'stressed/input'/relative),'stressed'),
            'Independent private risk/financing inputs differ across controlled cases')
    monitors=[(name,p) for name,c in cases.items() for p in c['proofs'] if p['judgment']['operation']=='monitor_borrower_risk']
    consumers=[(name,p) for name,c in cases.items() for p in c['proofs'] if p['judgment']['prior_actual_monitoring_count']>0]
    require(monitors and consumers,'Actual monitoring and a later own original consumer are both required')
    require(cases['supported']['monthly_operation_counts']=={'review_credit_pipeline':2,'adjust_credit_terms':4,'monitor_borrower_risk':0}
        and cases['stressed']['monthly_operation_counts']=={'review_credit_pipeline':2,'adjust_credit_terms':2,'monitor_borrower_risk':2}
        and len(consumers)==2 and all(p['scope']['tick']==3 and p['judgment']['prior_actual_monitoring_count']==1 for _,p in consumers),
        'The representative controlled monitoring/own later-consumer behavior changed')
    require(any(any(c['actual_own_selection'] is not None for c in p['actual_observation']['received_cases']) for _,p in monitors),
        'Monitoring evidence must include an actually selected own financing case, without calling it a loan')
    contact={'macro_action':'Bank.monitor_borrower_risk','micro_action':'BANK-A01 optional monthly received-case risk analysis',
        'macro_input':'Actual original financing_condition_index and own earlier consider_financing request risk estimates',
        'return_path':'Original decide_monthly_operation proposal → monthly_enterprise_operation final → native agent_operation',
        'feedback_consumer':'Later own original BANK-A01 counts the same authenticated actual monitoring event and uses it in monitoring eligibility',
        'actual_events':[{'scenario':n,'event_id':p['actual_event']['event_id'],'event_sha256':p['actual_event_sha256']} for n,p in monitors],
        'later_consumers':[{'scenario':n,'identity':p['identity'],'prior_actual_monitoring_count':p['judgment']['prior_actual_monitoring_count'],
            'actual_own_history':p['consumed_own_monthly_history']} for n,p in consumers]}
    return {'batch':'3B-monthly','status':'received_borrower_case_risk_monitoring_verified_formal_covenants_still_blocked',
        'cases':cases,'contact':contact,'macro':macro,'overall_goal3_complete':False,
        'boundary':'Original native monthly risk operation consumes historical received applicant/borrower financing-case estimates and actual current financing conditions. Selected financing cases are explicitly identified. This is no current loan/debt/payment/default ledger or independent verified covenant finding. Detailed BANK-A08 and formal cash/loan actions remain blocked.'}


def write_delivery(directory,checks):
    _write(directory,'monthly-contact.json',checks['contact'])
    (directory/'RUN_RECORD.md').write_text('\n'.join(['# GOAL 3B 银行月度风险监测运行记录','',
        '复用原融资场景、BANK-A01、月度提案及最终确认；宏观源码冻结。仅期初 financing_condition_index 不同，其他宏观输入和独立私有输入除运行标识外一致。',
        '原实际已收融资请求提供项目风险和借款人能力。原 BANK-A01 在既有策略筛选后计算当前环境下的风险，并用真实较早监测次数约束重复监测。','',
        '| 原期初融资指数 | 第二轮实际指数 | 最高风险分数 | 两家银行原宏观实际动作 |',
        '| --- | --- | --- | --- |',
        *[f"| {read(directory/'source-config.json')['scenarios'][name]['financing_condition_index']} | {case['proofs'][2]['judgment']['financing_condition']['value']} | {case['proofs'][2]['judgment']['maximum_risk_score']} | {case['proofs'][2]['judgment']['operation']} |" for name,case in checks['cases'].items()],
        '',f"两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个原技术任务形成结果；12 项原 BANK-A01 月度判断；2 项实际风险监测均有下一轮本银行原动作消费证据。",
        '每项原输入、独立策略、已收案例与真实融资选择、原计算结果、提案/最终确认、完整实际月度事件及后轮使用对应关系见 checks.json。较早监测次数达到 1 后，本轮按同一规则回到原信用条件动作。',
        '原窗口末轮结果保存为实际执行，未声称窗口后的消费者已运行。融资选择、月度能力更新不是贷款、支付、真实违约或契约违规证明。正式 BANK-A08 等详细来源阻塞保留。','',
        '可复制入口（新目录）：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_bank_monthly_risk_chain `",
        '  --config config/bank_monthly_risk_chain.json `','  --output output/integration/goal3b_monthly_my_run','```','',
        '只读核对已保存记录：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_bank_monthly_risk_chain --check-only --output '{directory.as_posix()}'",'```','',
        '开发尝试 _01 缺少原项目生成启动开关，未进入业务；_02 叠加另一组按借款人选择次数收紧策略，第三轮两银行停报，触发原 no_finance 接口阻塞。两次失败原始日志与任务保留。',
        '本次 _03 使用既有月度验收场景的融资配置。实际 command.json 含原项目生成开关。归档 input/run.ps1 保留生成时原文；请使用上方已验收入口或本目录 run.ps1 生成新运行。后续生成的场景 run.ps1 已补齐该开关，另作输入清单与启动参数检查，未重放本次完成的业务。',
        '原策略单元检查 20 项通过；既有月度策略到后轮报价关键检查 1 项通过。原宏观弃用提示及原接口拒绝诊断保留，不改宏观。',
        f"宏观 {checks['macro']['file_count']} 文件基线与全部 Python 未改。月度累计 12/32，20 项未接通；GOAL 3 和原 PLAN 未完成。",'']),encoding='utf-8')
    script="""param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath '__WORKSPACE__'
try {
    & '.venv-integration/Scripts/python.exe' -m integration.verify_bank_monthly_risk_chain --config (Join-Path $PSScriptRoot 'source-config.json') --output $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Run failed; retain its actual logs and journals.' }
} finally { Pop-Location }
""".replace('__WORKSPACE__',str(ROOT).replace("'","''"))
    (directory/'run.ps1').write_text(script,encoding='utf-8')
    names=['src/actions/contracts/bank_monthly_risk_objects.py','src/actions/contracts/bank_strategy_objects.py',
        'src/actions/roles/bank_monthly_risk.py','src/actions/roles/bank_strategy.py','integration/bank_monthly_risk.py',
        'integration/bank_monthly_native.py','integration/bank_monthly_native_sources.py','integration/bank_monthly_risk_development.py',
        'integration/verify_bank_monthly_risk_chain.py','config/bank_monthly_risk_chain.json','config/gba_v1_business_wiring.json',
        'config/gba_v1_monthly_business_wiring.json','docs/银行月度风险监测接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'bank-monthly-risk-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/bank_monthly_risk_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_unchanged_files':checks['macro']['file_count']}))


if __name__=='__main__':main()
