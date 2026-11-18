"""Fixed GOAL 3H actual payment requests, private responses and honest waits."""
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


def validate_config(config):
    require(config['schema_version']=='payment-chain.v1' and config['ticks']==3 and config['random_seed']==1
        and config['progress_payment_ticks']==[1,2] and config['max_prior_payment_requests']==1
        and config['scenarios']=={'low_reliability':{'owner_payment_reliability':0.0},
            'high_reliability':{'owner_payment_reliability':1.0}},'Unsupported fixed payment configuration')


def run_scenario(directory,*,run_id,config,profile):
    from integration.financing_professional_development import build_bundle
    directory.mkdir(parents=True,exist_ok=False)
    build_bundle(directory/'input',run_id=run_id,with_government_and_supply=True,
        with_owner_opportunity=True,max_prior_initiations=999,max_prior_payment_requests=config['max_prior_payment_requests'],
        with_payment_project=True,with_payment_positions=True,with_contractor_formation=True,
        progress_payment_ticks=tuple(config['progress_payment_ticks']),max_prior_accept_terms=999,
        max_prior_owner_payment_delays=1,random_seed=config['random_seed'],**profile)
    verify_bundle(directory/'input')
    args=[sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--allow-native-project-generation','--allow-native-initial-projects-with-generation',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.financing_professional_native:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original payment run failed; preserve logs and original tasks')


GATES={
    'draw':{'actions':['BANK-A06'],'handlers':['integration.bank_draw_actions:BankDrawActionAssembler'],
        'missing':['effective_registered_facility_and_current_draw_conditions','actual_owner_draw_request_and_capacity_reservations','native_draw_batch_issuer_and_original_query']},
    'bank_execution':{'actions':['BANK-A07'],'handlers':['integration.bank_execution_actions:BankExecutionActionAssembler','integration.bank_execution_reader:BankExecutionReader'],
        'missing':['authentic_approved_instruction_and_original_command_business_keys','current_accounts_principal_allocations_and_actual_execution_query','independent_execution_and_cash_receipts_complete_for_all_commands']},
    'owner_pay_repay_and_reconcile':{'actions':['OWN-A06'],
        'handlers':['integration.owner_payment_actions:OwnerPaymentActionAssembler','integration.owner_payment_reconciliation_reader:OwnerPaymentReconciliationReader'],
        'missing':['actual_certificates_due_components_obligations_and_account_funding','independent_pay_repay_authorization_and_original_issued_commands','complete_debit_credit_receipts_and_settlement_query'],
        'private_branch':'negotiate runs; pay/repay/financial reconciliation do not'},
    'contractor_receipt_reconciliation':{'actions':['CONTRACTOR-A10'],
        'handlers':['integration.contractor_payment_actions:ContractorPaymentActionAssembler'],
        'missing':['complete_current_original_payment_history','authentic_entitlement_components_account_and_execution_receipts','independent_actual_measurement_payment_query_and_authorized_disposition'],
        'private_branch':'actual delay triggers original needs_information; no completed dispute or receipt'},
    'supplier_receipt_reconciliation':{'actions':['SUPPLIER-A10'],
        'handlers':['integration.supplier_payment_actions:SupplierPaymentActionAssembler'],
        'missing':['effective_order_delivery_acceptance_and_settlement_rights','complete_current_payment_obligation_account_and_execution_history','actual_recipient_credit_receipts_and_current_authorized_query']},
    'qs_payment_reconciliation':{'actions':['QS-A08'],
        'handlers':['integration.qs_payment_actions:QSPaymentActionAssembler','integration.qs_payment_reader:QSPaymentReader'],
        'missing':['actual_signed_certificate_and_complete_lineage','authentic_complete_command_payment_and_offset_history','independent_current_execution_and_receipt_mapping'],
        'cross_reference':'3G independent certification sources remain blocked'},
}


def verify_scenario(directory,*,reliability,expect_delay):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original payment process failed')
    initial=read(directory/'input/macro-request.json');result=read(directory/'runtime/result.json')
    simulation=result['simulation'];host=result['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==3,'Payment window incomplete')
    owner=one(initial['agents'],lambda a:a['agent_id']=='finance-owner-a','Initial Owner missing')
    require(owner['payment_reliability']==reliability and initial['random_seed']==1,'Controlled original initial profile changed')
    project=one(simulation['project_results'],lambda p:p['project_id']=='owner-existing-construction','Actual construction missing')
    original=one(initial['initial_projects'],lambda p:p['project_id']==project['project_id'],'Initial construction missing')
    require(not original['event_log'] and original['current_stage']=='construction','Actual payment results prefilled')
    events=[e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original payment observer failed')
    requests=[e for e in project['event_log'] if e['event_type']=='payment_requested' and e['tick'] in (1,2)]
    require({e['tick'] for e in requests}=={1,2} and len(requests)==2,'Both original payment request windows required')
    selected=one(requests,lambda e:e['tick']==2,'Second actual request missing')
    delays=[e for e in project['event_log'] if e['event_type']=='payment_delayed' and e['tick']==2]
    require(len(delays)==int(expect_delay) and selected['data']['payment_status']==('delayed' if expect_delay else 'approved'),
        'Controlled reliability did not produce the expected original request status')
    require(all(e['data']['payment_amount']==200000 for e in requests),'Original threshold amount changed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        saved={table:[json.loads(v) for v, in db.execute('SELECT record FROM '+table)]
            for table in ('owner_payment_results','contractor_payment_results','owner_investment_results')}
    by_key={TaskIdentity(**t['identity']).key:t for t in tasks}
    lifecycle=host['lifecycle'];require(lifecycle['formal_commands_submitted'] is False,'Private response submitted formal payment')
    lifecycle_source=read(read(directory/'input/assembly-host.json')['settings']['lifecycle']['file_path'])
    plans={p['plan_id']:p for p in lifecycle_source['plans']}
    proofs=[];waiting=set()
    for record in lifecycle['actions']:
        if not record['plan_id'].startswith('shared-progress-payment-'):continue
        digest_valid(record);require(record==metadata[record['key']],'Private export differs from original durable journal')
        identity=TaskIdentity(**record['identity']);task=by_key[identity.key]
        table='owner_payment_results' if identity.action_id=='OWN-A06' else 'contractor_payment_results'
        worker=one(saved[table],lambda s:s['identity']==identity.as_dict(),'Original private result missing');digest_valid(worker)
        require(task_digest(worker['result'])==worker['result_sha256'],'Original private result hash changed')
        plan=plans[record['plan_id']]
        require(task_digest(plan['context'])==identity.context_sha256,
            'Private response changed the original sealed invocation')
        event=one(events,lambda e:e['event_id']==record['observed']['event_id'],'Actual trigger missing')
        origin=record['observed']['payment_origin'];request=one(requests,lambda e:e['event_id']==origin['request_event_id'],'Original request lineage missing')
        require(origin['request_source_event_sha256']==task_digest(request)
            and origin['trigger_source_event_sha256']==task_digest(event)
            and event['project_id']==project['project_id'] and event['tick']==plan['context']['business_time']['offset']
            and origin['native_request_status']==request['data']['payment_status'],
            'Private action lost exact original request/delay linkage')
        require(any(s['projection'].get('content_hash')==task_digest(record['observed']) for s in worker['source_reading']),
            'Actual payment feedback did not enter original saved micro input')
        if identity.action_id=='OWN-A06':
            require(event['event_type']=='payment_requested' and identity.organization_id==project['owner_id']
                and record['state']=='formed' and worker['result']['payload']['choice']=='negotiate'
                and task['state']=='output_formed','Original Owner did not privately review the actual request')
        else:
            require(identity.action_id=='CONTRACTOR-A10' and event['event_type']=='payment_delayed'
                and identity.organization_id==project['selected_contractor_id'] and record['state']=='unresolved'
                and worker['result']['kind']=='needs_information' and task['state']=='waiting_input'
                and 'complete_current_original_payment_history' in json.dumps(worker['result']),
                'Incomplete real payment history was promoted to completed dispute or received cash')
            require(origin['delay_event_id']==event['event_id'],'Delay was detached from its original request')
            waiting.add(identity.key)
        proofs.append({'plan_id':record['plan_id'],'identity':identity.as_dict(),'state':record['state'],
            'event_id':event['event_id'],'payment_origin':origin,'result':worker['result'],
            'result_sha256':worker['result_sha256'],'source_reading_sha256':worker['source_reading_sha256']})
    require(sum(p['identity']['action_id']=='OWN-A06' for p in proofs)==2,'Both actual Owner responses missing')
    require(any(p['identity']['action_id']=='CONTRACTOR-A10' and p['payment_origin']['request_event_id']==selected['event_id']
        for p in proofs)==expect_delay,'Actual second delay did not reach the original private review/wait')
    consumers=[]
    for record in host['opportunity']['requests']:
        if record['scope']['tick']!=3:continue
        digest_valid(record);require(record==metadata[record['key']],'Later Owner export changed')
        query=record['observed']['own_progress_payments'];digest_valid(query)
        require(query['organization_id']=='finance-owner-a' and query['as_of_tick']==3 and query['currency'] is None
            and record['observed']['payment_request_preference_pauses_initiation'] is True
            and record['observed']['max_prior_payment_requests']==1,'Actual request exposure did not enter later Owner judgment')
        for q in query['payment_requests']+query['delay_events']:
            event=one(events,lambda e:e['event_id']==q['event_id'],'Later source event missing')
            require(q['source_event_sha256']==task_digest(event) and event['tick']<3
                and event['data']['owner_id']==query['organization_id'],'Later query borrowed another party or future event')
        require(any(q['event_id']==selected['event_id'] for q in query['payment_requests']),
            'Later micro action did not consume this same actual request')
        if expect_delay:
            require(any(d['event_id']==delays[0]['event_id'] and d['request_event_id']==selected['event_id']
                for d in query['delay_events']),'Later query double-counted or lost the exact delay/request relation')
        identity=TaskIdentity(**record['identity'])
        worker=one(saved['owner_investment_results'],lambda s:s['identity']==identity.as_dict(),'Original later A03 missing')
        digest_valid(worker)
        require(task_digest(worker['result'])==worker['result_sha256'],'Later original investment result hash changed')
        applied_policies=[{'ref':s['ref'],'policy':s['projection']['policy']} for s in worker['source_reading']
            if s['ref']['kind']=='ProjectRegistrationProfile']
        require(identity.action_id=='OWN-A03' and worker['result']['payload']['choice']=='reject'
            and applied_policies and all(p['policy']=={'state':'known','value':'reject'} for p in applied_policies)
            and any(s['projection'].get('content_hash')==task_digest(record['observed']) for s in worker['source_reading']),
            'Actual request history was merely printed or original investment result changed')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='owner_project_opportunity'
            and t['output']['data'].get('native_owner_opportunity_scope')==record['scope'],'Original later Owner final response missing')['output']
        require(final['decision'] is False and final['data']['micro_result_sha256']==worker['result_sha256'],
            'Later micro refusal was not returned through the original macro final decision interface')
        consumers.append({'identity':identity.as_dict(),'query':query,'micro_result_sha256':worker['result_sha256'],
            'source_reading_sha256':worker['source_reading_sha256'],'applied_registration_policies':applied_policies,
            'choice':'reject','native_final_response':final})
    require(len(consumers)==4,'All original later opportunity consumers missing')
    require(all(t['state']=='output_formed' or (t['state']=='waiting_input' and TaskIdentity(**t['identity']).key in waiting)
        for t in tasks),'An unrelated task is incomplete')
    require(all(t['output_sha256']==task_digest(t['output']) for t in tasks if t['state']=='output_formed'),
        'Original formed task output digest changed')
    require(not any(k.startswith(('bank_execution_submission:','bank_draw_submission:','owner_payment_submission:')) for k in metadata),
        'Unverified formal payment command was submitted')
    require(not any(t['identity']['purpose']=='action' and t['identity']['action_id'] in
        {'BANK-A06','BANK-A07','SUPPLIER-A10','QS-A08'} for t in tasks),
        'Formal-money stage invoked without its independently verified original sources')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only check modified payment journal')
    return {'status':'actual_requests_private_responses_waits_and_later_owner_consumption_verified_formal_money_blocked',
        'owner_payment_reliability':reliability,'native_ticks':3,'actual_requests':requests,'second_actual_delay':delays,
        'second_delay_probability':selected['data']['payment_delay_probability'],'private_responses':proofs,'later_owner_consumers':consumers,
        'technical_tasks':len(tasks),'waiting_input_tasks':len(waiting),'executed_private_micro_actions':dict(Counter(t['identity']['action_id']
            for t in tasks if t['identity']['purpose']=='action' and t['state']=='output_formed')),
        'native_validation_diagnostics':[e for e in events if e['event_type']=='invalid_action'],
        'formal_money_execution_or_cash_receipt_proven':False,'journal_sha256':before,'read_only':True}


def source_boundaries():
    from integration.contractor_construction_source_review import _source
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    producer=_source(macro,'simulation/project_state_update_engine.py','ProjectStateUpdateEngine._record_payment_event')
    producer['path']=(macro/producer['path']).relative_to(ROOT).as_posix()
    stages={}
    for name,gate in GATES.items():
        sources=[]
        for handler in gate['handlers']:
            module,symbol=handler.split(':');getattr(importlib.import_module(module),symbol)
            sources.append(_source(ROOT,module.replace('.','/')+'.py',symbol))
        stages[name]={**gate,'status':'blocked_missing_verified_native_sources','existing_handlers':sources,
            'formal_money_effects_verified':False}
    return {'batch':'3H','native_producer':producer,'actual_feedback_components':[
        _source(ROOT,'integration/native_progress_payment_trigger.py','payment_trigger_origin'),
        _source(ROOT,'integration/bindings/gba_v1_progress_payments.py','read_own_progress_payments'),
        _source(ROOT,'integration/native_lifecycle_actions.py','NativeLifecycleApplication._dispatch_event'),
        _source(ROOT,'integration/owner_opportunity_native_sources.py','prepare_opportunity_sources')],
        'stages':stages,'boundary':'Actual native request status, private negotiation and unresolved original review are not formal pay/repay/draw commands or independent cash/credit receipts. The original approved status is chosen before the post-event private response. Later own exposure preference counts original requests once, never debt or cash.',
        'next_step':'Bind independently equivalent original issuer/query and exact authorized detailed sources to existing typed submission/read/reconciliation components. Never synthesize receipts or infer complete payment history from aggregate events. Bank debt monitoring/resolution/closeout remains 3I; certificate issuance remains blocked in 3G.'}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    scenarios={name:verify_scenario(directory/name,reliability=profile['owner_payment_reliability'],
        expect_delay=name=='low_reliability') for name,profile in config['scenarios'].items()}
    low=scenarios['low_reliability']['second_delay_probability'];high=scenarios['high_reliability']['second_delay_probability']
    require(low>high,'Initial reliability difference did not affect original delay probability')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro sources changed')
    return {'batch':'3H','status':'actual_payment_requests_private_responses_waits_and_later_consumption_verified_formal_money_blocked',
        'scenarios':scenarios,'profile_effect':{'original_delay_probability_low':low,'original_delay_probability_high':high,
            'source_formula_component':'0.30 * (1.0 - owner.payment_reliability)',
            'boundary':'Only the original initial profile is varied. Full probabilities also include market/claim terms and the resulting native trajectory; no fixed random draw or 0.30 total difference is assumed.',
            'actual_second_statuses':['delayed','approved'],'native_request_status_is_cash':False},
        'formal_money_gates':{n:'blocked_missing_verified_native_sources' for n in GATES},
        'macro':macro,'overall_goal3_complete':False}


def write_delivery(directory,checks):
    lines=['# GOAL 3H 资金执行、付款及对账接线记录','',
        '已实跑：原付款请求 → 原 OWN-A06 私有协商；实际延付 → 原 Contractor A10 缺资料等待；后轮 OWN-A03 消费同一请求/延付后拒绝新立项，交原最终决定接口。',
        '**正式提款、资金执行、到账及财务对账未接通。** 等待和汇总状态不算成功财务效果。','',
        '| 原初始可靠度 | 时点 2 原概率/状态 | 原 Owner 私有协商 | 缺资料等待 | 时点 3 原 OWN-A03 消费 |',
        '| --- | --- | --- | --- | --- |']
    for name,s in checks['scenarios'].items():
        request=next(r for r in s['actual_requests'] if r['tick']==2)
        lines.append(f"| {name} / {s['owner_payment_reliability']} | {s['second_delay_probability']} / {request['data']['payment_status']} | 2 次 negotiate | {s['waiting_input_tasks']} | {len(s['later_owner_consumers'])} 次 reject |")
    lines += ['','新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_payment_chain `",
        '  --config config/payment_chain.json `','  --output output/integration/goal3h_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_payment_chain --check-only --output '{directory.as_posix()}'",'```','',
        '初始既有施工/合同/进度、私有争议、独立现金/义务等来源由原共享编制器在引擎构造前明确声明；不是本轮从零工程或签发成果。两组只经原 owner_payment_reliability 配置差异、原随机种子 1 和原付款时窗 1/2 构造，不改运行中状态或预填决定。',
        '原宏观实算延付概率并先选择请求状态；随后原观察接口触发私有处理，其 negotiate 不修改已记录的宏观 approved/delayed。缺完整真实付款历史的 A10 仍 waiting_input，未形成完成争议或收款。',
        '后轮原 OWN-A03 查询严格较早、属于本业主的请求/延付，按初始请求数阈值 1 暂停新立项。两条延付观察只对应一次请求，不形成欠债/现金、独立核证或币种换算；双方初始独立义务不是从原请求金额推导。',
        'checks.json 保存原请求/延付摘要、原私有输入和结果、补资料等待、后轮查询及原最终响应。runtime/ 保留原进程输出/任务库；source-boundaries.json 定位生产者、实际反馈组件、六类正式资金阻塞及下一步。',
        '原生本地 invalid_action 诊断完整保留，不算成功动作；原观察器错误为零。基础组合中的融资/采购/专业等仅作为既有入口前缀，不据此扩张本批覆盖。',
        f"宏观 {checks['macro']['file_count']} 文件基线及全部宏观 Python 源码未改；GOAL 3 与原 PLAN 均未完成。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/verify_payment_chain.py','config/payment_chain.json','config/gba_v1_business_wiring.json',
        'docs/资金付款对账接线与验收.md','docs/宏观动作接线清单.md','integration/native_progress_payment_trigger.py',
        'integration/native_lifecycle_actions.py','integration/bindings/gba_v1_progress_payments.py',
        'integration/owner_opportunity_native_sources.py','integration/progress_payment_development.py',
        'integration/financing_professional_native.py','integration/financing_professional_development.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'payment-chain-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'config/payment_chain.json')
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
