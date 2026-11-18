"""Run/check original regulatory intake, review, opinion and actual own outcomes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.government_intake_development import build_bundle
from integration.contractor_tender_development import verify_bundle, _write
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory, *, completion):
    """Read saved native results and original worker journals without replay."""
    verify_bundle(directory/'input')
    require(read(directory/'exit.json')['exit_code']==0,'Native regulatory process failed')
    output = read(directory/'runtime/result.json')
    simulation,host = output['simulation'],output['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==(4 if completion else 2),
        'Regulatory window incomplete')
    initial = read(directory/'input/macro-request.json')
    require(all(not p['event_log'] and not p['flags'].get('government_design_approved')
        for p in initial['initial_projects']),'Actual regulatory outcomes prefilled')
    events = [e for p in simulation['project_results'] for e in p['event_log']]
    inbox = read(directory/'runtime/observations.json')['records']
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Regulatory feedback observer failed')
    database = directory/'runtime/tasks.sqlite'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers = [json.loads(v) for table in ('government_intake_results','government_review_results',
            'government_decision_results','government_feedback_results') for v, in db.execute('SELECT record FROM '+table)]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Unresolved or altered original task')
    task_map = {TaskIdentity(**t['identity']).key:t for t in tasks}
    saved = {TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r)
        require(r['result']['kind']=='completed' and r['result_sha256']==task_digest(r['result'])
            and r['source_reading_sha256']==task_digest(r['source_reading'])
            and task_map[TaskIdentity(**r['identity']).key]['output']==r['result'], 'Worker/task/source correlation lost')

    def worker(identity):
        return saved[TaskIdentity(**identity).key]

    def event(event_id):
        return one(events,lambda e:e['event_id']==event_id,'Missing actual project event')

    def bound(record, observed):
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in record['source_reading']), 'Original micro source did not bind this native/history input')

    def transport(row, micro, operation, decision, *, monthly=False):
        field = 'native_monthly_feedback_scope' if monthly else 'native_government_scope'
        org,scope = micro['identity']['organization_id'],row['scope']
        proposal = one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='propose'
            and t['identity']['action_id']==operation and t['output'].get('factors',{}).get(field)==scope,'Missing actual original proposal')['output']
        final = one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='decide'
            and t['identity']['action_id']==decision and t['output'].get('data',{}).get(field)==scope,'Missing actual original final')['output']
        require(task_digest(proposal)==row['proposal_response_sha256']==final['data']['proposal_response_sha256']
            and proposal['accepted']==final['decision'] and proposal['action_type']==final['action_type'],
            'Actual final differs from original micro proposal')
        key = TaskIdentity(**micro['identity']).key
        for data in (proposal['factors'],final['data']):
            require(data['micro_task_key']==key and data['micro_result_sha256']==micro['result_sha256'],
                'Transport substituted original micro result')
        return proposal,final

    def history(prior, *, org, tick):
        e = event(prior['event_id'])
        require(prior['organization_id']==org and e['tick']==prior['tick'] < tick
            and e['project_id']==prior['project_id'], 'History borrowed a peer/future outcome')
        require(saved[prior['micro_task_key']]['result_sha256']==prior['micro_result_sha256'],
            'History lost the exact original micro result')
        identity = saved[prior['micro_task_key']]['identity']
        require(identity['organization_id']==org,'History borrowed another institution micro result')
        records = approvals if identity['action_id']=='GOV-A07' else intakes
        original = one(records,lambda r:r['scope']['project_id']==prior['project_id']
            and r['scope']['tick']==prior['tick']
            and r['native_request']['agent']['agent_id']==org,'History lost its original native request')
        require(original['proposal_response_sha256']==prior['proposal_response_sha256'],
            'History borrowed another original proposal')
        final = one(tasks,lambda t:t['identity']['purpose']=='decide'
            and t['identity']['organization_id']==org
            and t['output'].get('data',{}).get('proposal_response_sha256')==prior['proposal_response_sha256'],
            'History lost original final transport')['output']
        require(task_digest(final)==prior['final_response_sha256']
            and final['data']['micro_task_key']==prior['micro_task_key'],
            'History lost exact final micro authorization')
        if prior.get('native_outcome'):
            require(prior['completed']==(e['event_type']=='project_completed')
                and prior['native_outcome']==('completed' if prior['completed'] else 'rectification_required'),
                'Approval opinion was relabelled as actual completion')
        return {'event_id':e['event_id'],'event_sha256':task_digest(e),
            'micro_task_key':prior['micro_task_key'],'micro_result_sha256':prior['micro_result_sha256'],
            'actual_type':e['event_type']}

    def monthly_history(prior, *, org, tick):
        require(prior['organization_id']==org and prior['tick']<tick,'Monthly history changed recipient/time')
        receipt = one(inbox,lambda r:r['event_id']==prior['event_id'] and r['organization_id']==org,
            'Missing original own monthly reception')
        o = receipt['payload']
        # Rebuild only for a read-only hash comparison with the original source
        # reader's saved native-event digest. Never record or dispatch an event.
        native = dict(event_id=receipt['event_id'],tick=o['tick'],project_id=None,agent_id=o['agent_id'],
            event_type='agent_operation',stage=None,description=o['data']['description'],data=o['data'])
        require(task_digest(native)==prior['source_event_sha256']
            and saved[prior['micro_task_key']]['result_sha256']==prior['micro_result_sha256']
            and o['data']['operation']=='review_policy_feedback', 'Monthly consumer lost exact actual operation/result')
        original = one(monthly,lambda r:r['scope']['tick']==prior['tick']
            and r['identity']['organization_id']==org,'Monthly history lost its original own request')
        require(TaskIdentity(**original['identity']).key==prior['micro_task_key']
            and original['proposal_response_sha256']==prior['proposal_response_sha256'],
            'Monthly history borrowed another micro task/proposal')
        return {'event_id':prior['event_id'],'event_sha256':prior['source_event_sha256'],
            'micro_task_key':prior['micro_task_key'],'micro_result_sha256':prior['micro_result_sha256']}

    intakes = [v for k,v in metadata.items() if k.startswith('government_intake_native_request:')]
    approvals = [v for k,v in metadata.items() if k.startswith('government_approval_native_request:')]
    monthly = [v for k,v in metadata.items() if k.startswith('government_monthly_native_request:')]
    require((len(intakes),len(approvals),len(monthly))==(4,3 if completion else 2,8 if completion else 4),
        'Original regulatory contacts missing')
    for exported,records in ((host['requests'],intakes),(host['approval']['requests'],approvals),
            (host['monthly']['requests'],monthly)):
        require({r['key']:r for r in exported}=={r['key']:r for r in records},
            'Original CLI export and durable workflow disagree')
    intake_proofs,approval_proofs,monthly_proofs = [],[],[]
    for row in intakes:
        digest_valid(row)
        r = worker(row['identity'])
        scope,org = row['scope'],row['identity']['organization_id']
        bound(r,row['observed'])
        require(row['state']=='formed' and row['observed']['native_request_sha256']==task_digest(row['native_request'])
            and row['result_sha256']==r['result_sha256'],'Intake native request/result changed')
        accepted = org=='regulatory-agency-a'
        matter = one(r['source_reading'],lambda s:s['ref']['kind']=='RegulatoryMatter',
            'Original intake lacks its matter')['projection']
        jurisdiction = one(r['source_reading'],lambda s:s['ref']['kind']=='Jurisdiction',
            'Original intake lacks its independent jurisdiction')['projection']
        region = row['native_request']['inputs']['project']['region']
        require(matter['project_region_id']=={'state':'known','value':region}
            and (region in jurisdiction['covered_project_region_ids']['value']) is accepted,
            'Native project region did not enter original micro jurisdiction judgment')
        require(r['result']['payload']['choice']==('accept_for_processing' if accepted else 'decline_processing'),
            'Original jurisdiction check did not determine intake willingness')
        proposal,final = transport(row,r,'consider_review_assignment','government_review_assignment')
        e = one(events,lambda e:e['event_type']=='regulatory_review_decision' and e['project_id']==scope['project_id']
            and e['tick']==scope['tick'] and e['agent_id']==org,'Missing actual intake execution')
        require(e['data']['accepted']==proposal['accepted']==accepted
            and e['data']['micro_result_sha256']==r['result_sha256']
            and e['data']['proposal_response_sha256']==task_digest(proposal),'Native intake differs from original A02')
        received = [v for v in inbox if v['event_id']==e['event_id']]
        require(len(received)==1 and received[0]['organization_id']==org,'Intake history leaked to another institution')
        prior = [history(h,org=org,tick=scope['tick']) for h in row['observed']['prior_review_decisions']]
        intake_proofs.append({'scope':scope,'identity':r['identity'],'result_sha256':r['result_sha256'],
            'choice':r['result']['payload']['choice'],'native_project_region':region,
            'micro_jurisdiction_regions':jurisdiction['covered_project_region_ids']['value'],
            'actual_event':e,'consumed_actual_history':prior})
    for row in approvals:
        digest_valid(row)
        scope = row['scope']
        org = row['native_request']['agent']['agent_id']
        stages = {s:worker(row[s+'_identity']) for s in ('feedback','review','decision')}
        for stage,r in stages.items():
            require(row[stage+'_result_sha256']==r['result_sha256'],'Saved regulatory stage changed')
            bound(r,row[stage+'_observed'])
        feedback,review,decision = [stages[s] for s in ('feedback','review','decision')]
        revision = completion and scope['project_id']=='regulatory-first'
        finding,choice = ('nonconforms','defer_by_procedure') if revision else ('conforms','approve')
        checks = review['result']['payload']['assessment']['checks']
        calls = review['audit']['method_calls']
        require(len(checks)==len(calls)==1 and checks[0]['finding']==finding
            and calls[0]['result']['value']['finding']==finding
            and decision['result']['payload']['choice']==choice,'Original rule method did not reach A07 decision')
        handoff = row['decision_observed']['review_handoff']
        require(handoff['task_key']==TaskIdentity(**review['identity']).key
            and handoff['result_sha256']==review['result_sha256'] and handoff['selected_outcome']==choice,
            'A07 did not consume the exact actual A04 result')
        bound(decision,handoff)
        require(not {s['ref']['kind'] for s in decision['source_reading']} & {'Decision','DecisionNotification','Permit'},
            'Private draft borrowed a formal issuance/permit receipt')
        proposal,final = transport(row,decision,'decide_approval',
            'government_completion_approval' if completion else 'government_design_approval')
        require(proposal['accepted'] is (not revision),'Native approval contradicts original A07')
        assignment = row['review_observed']['assignment']
        assigned_event = event(assignment['event_id'])
        require(assigned_event['data']['accepted'] is True and assigned_event['agent_id']==org
            and saved[assignment['micro_task_key']]['result_sha256']==assignment['micro_result_sha256'],
            'Approval did not follow its own actual A02 assignment')
        e = one(events,lambda e:e['project_id']==scope['project_id'] and e['tick']==scope['tick']
            and e['event_type']==(('quality_issue' if revision else 'project_completed') if completion else 'approval_approved'),
            'Missing original actual regulatory execution outcome')
        if e['event_type']!='project_completed':
            data = e['data']['completion_decision' if completion else 'individual_decision']
            require(data['accepted']==proposal['accepted']
                and data['micro_result_sha256']==decision['result_sha256']
                and data['proposal_response_sha256']==task_digest(proposal),'Actual event substituted the deciding result')
        else:
            require(e['agent_id'] is None,'Native agent-free completion was attributed to an invented actor')
        prior = [history(h,org=org,tick=scope['tick']) for h in row['review_observed']['prior_approval_decisions']]
        months = [monthly_history(h,org=org,tick=scope['tick']) for h in row['review_observed']['prior_monthly_feedback']]
        for stage in ('review','decision'):
            observed = row[stage+'_observed']
            require(observed['prior_approval_decisions']==row['feedback_observed']['prior_approval_decisions']
                and observed['private_feedback']['result_sha256']==feedback['result_sha256']
                and observed['private_feedback']['task_key']==TaskIdentity(**feedback['identity']).key,
                'A04/A07 did not consume this original A12 history reflection')
        require(feedback['result']['payload']['choice']=='record_feedback'
            and len(months)==scope['tick']-1,'Original approval did not read strictly earlier own monthly work')
        approval_proofs.append({'scope':scope,'review_identity':review['identity'],'review_result_sha256':review['result_sha256'],
            'decision_identity':decision['identity'],'decision_result_sha256':decision['result_sha256'],
            'feedback_identity':feedback['identity'],'feedback_result_sha256':feedback['result_sha256'],
            'computed_finding':finding,'micro_choice':choice,'accepted_opinion':proposal['accepted'],
            'actual_event':e,'actual_completed':e['event_type']=='project_completed',
            'consumed_actual_history':prior,'consumed_monthly_history':months})
    for row in monthly:
        digest_valid(row)
        r = worker(row['identity'])
        scope,org = row['scope'],row['identity']['organization_id']
        require(row['state']=='formed' and row['result_sha256']==r['result_sha256']
            and r['result']['payload']['choice']=='record_feedback','Monthly original feedback not formed')
        bound(r,row['observed'])
        proposal,final = transport(row,r,'decide_monthly_operation','monthly_enterprise_operation',monthly=True)
        own = one(inbox,lambda v:v['organization_id']==org and v['payload']['event_type']=='agent_operation'
            and v['payload']['tick']==scope['tick'] and v['payload']['data']['operation']=='review_policy_feedback',
            'Missing actual own native monthly operation')
        data = own['payload']['data']
        require(data['decision_accepted'] is True and data['description']==proposal['data']['description']
            ==r['result']['payload']['interpretation'] and data['label']==proposal['data']['label'],
            'Native scheduler did not execute this original private review')
        prior = [monthly_history(h,org=org,tick=scope['tick']) for h in row['observed']['prior_monthly_feedback']]
        approvals_used = [history(h,org=org,tick=scope['tick']) for h in row['observed']['prior_approval_decisions']]
        require(len(prior)==scope['tick']-1,'Monthly consumer lost its actual own earlier outcomes')
        monthly_proofs.append({'scope':scope,'identity':r['identity'],'result_sha256':r['result_sha256'],
            'actual_received_event_id':own['event_id'],'actual_projection_sha256':task_digest(own['payload']),
            'consumed_monthly_history':prior,'consumed_actual_history':approvals_used,
            'native_capability_update':data.get('capability_update')})
    require(len(workers)==(21 if completion else 14),'Unexpected count of original micro actions')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only verification modified journal')
    return {'status':'passed','native_ticks':simulation['current_tick'],'technical_tasks':len(tasks),
        'original_micro_actions':dict(Counter(r['identity']['action_id'] for r in workers)),
        'intake_requests':intake_proofs,'approval_requests':approval_proofs,'monthly_requests':monthly_proofs,
        'actual_completed_projects':[e['project_id'] for e in events if e['event_type']=='project_completed'],
        'read_only':True,'journal_sha256':before,
        'boundary':'Original review willingness, document-method review, authorized private draft and native aggregate outcome. No formal case/decision/notification/permit, physical inspection, policy issuance or cash receipt.'}


def run_scenario(directory, *, run_id, options):
    build_bundle(directory/'input',run_id=run_id,**options)
    verify_bundle(directory/'input')
    args = [sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.government_intake_native:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        completed = subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':completed.returncode})
    require(completed.returncode==0,'Native run failed; inspect preserved stderr and original journal')


def review_remaining_sources():
    """Pin reviewed boundaries; these source records are not execution receipts."""
    from integration.contractor_construction_source_review import _source
    macro = ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    producers = [
        _source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine.'+name)
        for name in ('_select_government_reviewer','_handle_approval','_handle_completion')]
    producers += [_source(macro,'simulation/simulation_engine.py','SimulationEngine._run_agent_operations'),
        _source(macro,'agents/government_agent.py','GovernmentAgent.decide_monthly_operation')]
    for item in producers:
        item['path'] = (macro/item['path']).relative_to(ROOT).as_posix()
    callbacks = [
        _source(ROOT,'integration/government_submission.py','GovernmentResultSubmission.execute'),
        _source(ROOT,'integration/government_decision_actions.py','GovernmentDecisionActionAssembler.build'),
        _source(ROOT,'integration/government_decision_notification_transport.py','GovernmentDecisionNotificationTransport.execute'),
        _source(ROOT,'integration/government_permit_actions.py','GovernmentPermitActionAssembler.build'),
        _source(ROOT,'integration/government_approval_native_sources.py','decision_sources')]
    return {'batch':'3D','status':'reviewed_boundaries_not_runtime_coverage',
        'native_producers':producers,'existing_formal_components':callbacks,
        'completion_gate':'Original minimum stage duration, detected_defect_rate <= 0.35 and actual positive independent Government decision. project_completed has no agent_id; attribution must retain original assignment/final/engagement authority.',
        'remaining_handoffs':[
            {'business':'Formal filing, signed decision, notification and permit',
             'status':'blocked_missing_verified_equivalent_native_issuer_and_sources',
             'reason':'Existing detailed assemblers/submission/notification/permit callbacks are retained. This native opinion bridge does not bind equivalent filing, signing, notification or permit issuers/query. A02 willingness is not a filed case; A07 command remains not_submitted with no official_decision_ref. Independent synthetic case/mandate/authority inputs are scenario assumptions.',
             'next_step':'Bind authentic detailed submission/procedure/signing sources and equivalent original issuer/query before using existing transports; never synthesize an official receipt from aggregate approval.'},
            {'business':'Conditional approval, refusal, referral, correction and acknowledgment',
             'status':'blocked_outside_original_boolean_operation_contract',
             'reason':'Native final contract supports accept/defer review and approve/request_revision. This scenario verifies accept/decline and unconditional approve/defer_by_procedure only; retain unsupported original outcomes unresolved rather than discard conditions or convert a refusal into approval.'},
            {'business':'publish_guidelines / monitor_compliance / adjust_regulatory_focus',
             'status':'blocked_for_micro_business_judgment',
             'reason':'Native monthly menu has four actual actions. Current original A12 directly selects only review_policy_feedback. Other three need authorized policy/monitoring/focus inputs and matching actual effect consumers; native labels/random capability increments do not prove these micro business actions.'},
            {'business':'Detailed physical inspection and downstream completion/handover',
             'status':'blocked_for_detailed_inspection_sources_and_consumers',
             'reason':'Original A04 document-rule result and aggregate quality/completion gate are real. They are not GOV-A10 physical inspection, independent measurements, defect remedy acceptance or handover/permit. Related construction/closeout work stays in 3G/3I.'}]}


def write_delivery(directory, checks):
    """Save a compact human record and immutable artifact/source hashes."""
    lines = ['# GOAL 3D 监管链运行记录', '',
        '复用既有监管适配器和原微观处理器，原 CLI 实际运行两个固定场景。整体 GOAL 3 未完成。', '',
        '| 场景 | 宏观时点 | 技术任务 | 原微观动作 | 实际完成项目 |',
        '| --- | --- | --- | --- | --- |']
    for name, item in checks['scenarios'].items():
        lines.append(f"| {name} | {item['native_ticks']} | {item['technical_tasks']} | {sum(item['original_micro_actions'].values())} | {', '.join(item['actual_completed_projects']) or '无'} |")
    lines += ['', '原生事件与后轮消费：', '']
    for name, item in checks['scenarios'].items():
        for r in item['approval_requests']:
            e = r['actual_event']
            lines.append(f"- {name} / {r['scope']['project_id']} / tick {r['scope']['tick']}: "
                f"原 A04={r['computed_finding']} → A07={r['micro_choice']} → {e['event_id']} {e['event_type']}; "
                f"本轮已消费 {[v['event_id'] for v in r['consumed_actual_history']]}，以及 {len(r['consumed_monthly_history'])} 项更早的本机构实际月度结果。")
    lines += ['', 'Hong Kong 项目地区由原宏观请求进入 RegulatoryMatter，原 A02 与独立 Jurisdiction 比较；香港机构接受，广州机构拒绝。本轮没有直接修改正式状态或预填微观决定。',
        'A12 将同一实际事件及原微观结果摘要纳入私有经验解释；A04/A07 读取该解释。完工 tick 4 读取 tick 3 实际整改与实际完成，仍按原材料规则要求整改，不把经验反馈当作合规证据。',
        '设计场景从审批阶段开始；完工场景从合法初始施工状态和已声明合同/engagement 开始。这些是场景假设，不是本次已执行采购、施工或签约的证据。', '',
        '新目录完整运行（仓库根目录）：', '```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_regulatory_chain `",
        '  --config config/regulatory_chain.json `',
        '  --output output/integration/goal3d_my_run', '```', '',
        '只读核对本记录：', '```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_regulatory_chain --check-only --output '{directory.as_posix()}'",
        '```', '',
        'source-config.json 和各 input/ 保存执行前输入；command.json、stdout/stderr、runtime/ 保存原进程和任务库。checks.json 保存身份/输入/结果/原实际事件/后轮消费者的对应关系。',
        f"宏观基线 {checks['macro']['file_count']} 个文件及全部宏观 Python 源码哈希不变；宏观执行由原引擎维护。", '',
        '剩余阻塞：正式立案/签署/通知/许可的等价原生来源与接口、超出布尔接口的条件/拒绝等结果、其他三种月度监管判断、详细现场检查及交接。source-boundaries.json 保存定位与下一步；源码审查不计作业务运行成功。', '']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    files = {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}
    names = ['config/regulatory_chain.json','config/gba_v1_business_wiring.json',
        'docs/监管链接线与验收.md','docs/宏观动作接线清单.md','integration/verify_regulatory_chain.py',
        'integration/government_intake_development.py','integration/government_intake_native.py',
        'integration/government_intake_scope.py','integration/government_intake_feedback.py',
        'integration/government_approval_native.py','integration/government_approval_native_sources.py',
        'integration/government_approval_native_learning.py','integration/government_approval_native_feedback.py',
        'integration/government_completion_native_feedback.py','integration/government_monthly_native.py',
        'integration/government_monthly_native_sources.py','integration/native_routes.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'regulatory-chain-artifacts.v1',
        'files':files,'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def validate_config(config):
    require(config['schema_version']=='regulatory-chain-acceptance.v1'
        and config['scenarios']=={
            'design':dict(with_approval=True,with_feedback=True,with_monthly_feedback=True),
            'completion_revision':dict(with_approval=True,with_feedback=True,with_monthly_feedback=True,
                completion=True,revision_first=True)},'Unsupported fixed regulatory scenarios')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/regulatory_chain.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    if not args.check_only:
        config = read(args.config)
        validate_config(config)
        directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'macro-before.json',macro_hashes())
        _write(directory,'source-config.json',config)
        for name,options in config['scenarios'].items():
            run_scenario(directory/name,run_id=config['run_id']+'-'+name,options=options)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    config = read(directory/'source-config.json')
    validate_config(config)
    checks = {'batch':'3D','status':'passed_for_bounded_native_regulatory_chain',
        'scenarios':{name:verify_scenario(directory/name,completion=options.get('completion',False))
            for name,options in config['scenarios'].items()},'macro':macro_hashes(),'overall_goal3_complete':False}
    require(read(directory/'macro-before.json')==macro_hashes(),'Frozen macro sources changed')
    if not args.check_only:
        _write(directory,'checks.json',checks)
        _write(directory,'source-boundaries.json',review_remaining_sources())
        write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),
        'macro_unchanged_files':macro_hashes()['file_count']}))


if __name__ == '__main__':
    main()
