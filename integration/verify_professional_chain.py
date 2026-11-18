"""Run/check original professional intake, appointment and own feedback workers."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.professional_intake_development import build_bundle
from integration.contractor_tender_development import verify_bundle, _write
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory, config, *, macro_snapshot_reader=macro_hashes):
    """Audit completed original records without importing a mutable task store."""
    verify_bundle(directory/'input')
    require(read(directory/'exit.json')['exit_code']==0,'Original process did not succeed')
    initial = read(directory/'input/macro-request.json')
    require(all(not p['engagements'] and not p['contracts'] and not p['event_log']
        and all(p[k] is None for k in ('selected_architect_id','selected_engineer_id','selected_qs_id'))
        for p in initial['initial_projects']), 'Actual professional results were prefilled')
    simulation = read(directory/'runtime/result.json')['simulation']
    expected = config['expected']
    owner_plans = read(Path(read(directory/'input/assembly-host.json')['settings']['owner']['file_path']))['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==expected['ticks']
        and len(simulation['project_results'])==expected['projects'],'Native professional window incomplete')
    events = [e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Actual feedback observer failed')
    database = directory/'runtime/tasks.sqlite'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots = {k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers = [json.loads(v) for table in ('architect_intake_results','engineer_intake_results','qs_intake_results',
            'architect_opportunity_results','engineer_opportunity_results','qs_market_results','owner_commission_results',
            'architect_appointment_results','engineer_appointment_results','qs_appointment_results',
            'architect_learning_results','engineer_learning_results','qs_learning_results')
            for v, in db.execute('SELECT record FROM '+table)]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Unresolved or altered technical task')
    task_map = {TaskIdentity(**t['identity']).key:t for t in tasks}
    saved = {TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r)
        key = TaskIdentity(**r['identity']).key
        require(r['result']['kind']=='completed' and r['result_sha256']==task_digest(r['result'])
            and r['source_reading_sha256']==task_digest(r['source_reading'])
            and task_map[key]['output']==r['result'], 'Original worker/task/sources disagree')

    def worker(identity):
        return saved[TaskIdentity(**identity).key]

    def source(record, kind):
        return one(record['source_reading'],lambda s:s['ref']['kind']==kind,'Missing original '+kind)['projection']

    def original_event(event_id):
        return one(events,lambda e:e['event_id']==event_id,'Missing unique actual native event')

    def source_bound(record, observed):
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in record['source_reading']), 'Original reading did not bind the observed provenance')

    def transport(record, micro, scope, operation, decision):
        org = micro['identity']['organization_id']
        proposal = one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='propose'
            and t['identity']['action_id']==operation
            and t['output'].get('factors',{}).get('native_professional_scope')==scope,'Missing actual scoped proposal')
        final = one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='decide'
            and t['identity']['action_id']==decision
            and t['output'].get('data',{}).get('native_professional_scope')==scope,'Missing actual scoped final')
        key = TaskIdentity(**micro['identity']).key
        for value in (proposal['output']['factors'],final['output']['data']):
            require(value['micro_task_key']==key and value['micro_result_sha256']==micro['result_sha256'],
                'Transport substituted the original micro result')
        require(proposal['output']['accepted']==final['output']['decision'],
            'Final acceptance changed the original proposal')
        if 'proposal_response_sha256' in record:
            require(record['proposal_response_sha256']==task_digest(proposal['output'])
                ==final['output']['data']['proposal_response_sha256'],'Proposal correlation lost')
        return proposal,final

    intake = [v for k,v in metadata.items() if k.startswith('professional_intake_native_request:')]
    owners = [v for k,v in metadata.items() if k.startswith('owner_commission_native_request:')]
    confirms = [v for k,v in metadata.items() if k.startswith('professional_appointment_received:')]
    feedback = [v for k,v in metadata.items() if k.startswith('native_lifecycle_action:')]
    require((len(intake),len(owners),len(confirms),len(feedback))==(expected['intake_requests'],
        expected['owner_decisions'],expected['selected_private_confirmations'],expected['private_feedback_actions']),
        'Expected original professional contacts missing')
    roles = {'Architect':'architect_id','Engineer':'engineer_id','QS':'qs_id'}
    intake_proofs,owner_proofs,confirmation_proofs,feedback_proofs,later = [],[],[],[],[]
    for row in intake:
        digest_valid(row)
        r = worker(row['identity'])
        key = TaskIdentity(**r['identity']).key
        role,org = r['identity']['role'],r['identity']['organization_id']
        context = snapshots[key]['context']
        scope = dict(project_id=context['scope']['ref']['id'],tick=context['business_time']['offset'],role=role)
        project = one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Missing actual project')
        require(row['state']=='formed' and row['request_sha256']==task_digest(row['native_request'])
            and row['result_sha256']==r['result_sha256'],'Intake lost its actual request/result')
        source_bound(r,row['observed'])
        terms = source(r,'ServiceTerms')
        require(terms['region_id']==dict(state='known',value=project['region'])
            and terms['object_type']==dict(state='known',value=project['project_type']),
            'Professional review does not match actual native region/type')
        interest = worker(row['opportunity_identity'])
        handoff = row['observed']['opportunity_handoff']
        require(interest['result']['payload']['choice']==handoff['choice']=='express_interest'
            and interest['identity']==handoff['identity']
            and interest['result_sha256']==handoff['result_sha256']==row['opportunity_result_sha256']
            and handoff['native_request_sha256']==row['request_sha256'], 'Original A01 did not reach original A02')
        source_bound(r,handoff)
        proposal,final = transport(row,r,scope,'consider_appointment',role.lower()+'_appointment_acceptance')
        e = one(events,lambda e:e['event_type']=='appointment_decision' and e['agent_id']==org
            and e['project_id']==scope['project_id'] and e['tick']==scope['tick'],'Missing original intake execution')
        rejected = role=='Engineer' and scope['tick']==2
        require(r['result']['payload']['choice']==('decline' if rejected else 'accept')
            and e['data']['accepted']==proposal['output']['accepted']==(not rejected)
            and e['data']['decision_factors']['micro_task_key']==key
            and e['data']['decision_factors']['micro_result_sha256']==r['result_sha256'], 'Macro did not execute original A02')
        histories = []
        for h in row['observed']['prior_appointments']:
            prior = original_event(h['event_id'])
            require(prior['event_type']=='consultant_team_appointed' and prior['tick']==h['tick'] < scope['tick']
                and prior['data'][roles[role]]==org==h['organization_id'], 'Later intake consumed peer or future appointment')
            a12 = worker(h['private_feedback']['identity'])
            f = one(feedback,lambda f:f['identity']==a12['identity'],'Missing actual prior A12 journal')
            require(h['private_feedback']['event_id']==prior['event_id']==f['observed']['event_id']
                and h['private_feedback']['result_sha256']==a12['result_sha256']==f['result_sha256'],
                'Later A02 did not consume this same original A12 result')
            histories.append({'event_id':prior['event_id'],'event_sha256':task_digest(prior),
                'A12_identity':a12['identity'],'A12_result_sha256':a12['result_sha256']})
        for h in row['observed']['prior_confirmations']:
            a03 = saved[h['micro_task_key']]
            require(a03['identity']['organization_id']==org and a03['result_sha256']==h['result_sha256']
                and a03['result']['payload']['choice']==h['choice']=='confirm','Later A02 lost its own original A03')
        policy = source(r,'FeeBasis')['new_work_policy']
        require(policy==dict(state='known',value='decline' if rejected else 'evaluate'),'Actual history failed to affect A02 policy')
        proof = {'identity':r['identity'],'result_sha256':r['result_sha256'],'scope':scope,
            'native_request_sha256':row['request_sha256'],'micro_choice':r['result']['payload']['choice'],
            'original_A01_result_sha256':interest['result_sha256'],'region':project['region'],'object_type':project['project_type'],
            'actual_event':e,'consumed_actual_history':histories,'new_work_policy':policy}
        intake_proofs.append(proof)
        if rejected:
            require(len(histories)==1 and row['observed']['max_prior_appointments']==1,'Expected actual rejection feedback absent')
            later.append(proof)
    teams = [e for e in events if e['event_type']=='consultant_team_appointed']
    require(len(teams)==2,'Actual teams missing')
    for row in owners:
        digest_valid(row)
        r = worker(row['identity'])
        scope = row['scope']
        proposal,final = transport(row,r,scope,'select_appointment','owner_select_'+scope['role'].lower())
        require(row['state']=='formed' and row['result_sha256']==r['result_sha256'],'Owner result not formed')
        source_bound(r,row['observed'])
        owner_plan = one(owner_plans,lambda p:p['context']['operation_id']==
            snapshots[TaskIdentity(**r['identity']).key]['context']['operation_id'],'Missing initial Owner plan')
        for h in row['observed']['prior_own_commissions']:
            prior = original_event(h['event_id'])
            require(prior['event_type']=='consultant_team_appointed' and prior['tick']==h['tick'] < scope['tick']
                and prior['agent_id']==h['organization_id']==r['identity']['organization_id']
                and prior['data'][roles[scope['role']]]==h['provider_id']
                and saved[h['micro_task_key']]['result_sha256']==h['micro_result_sha256'],
                'Owner comparison changed its own actual previous commission')
        for origin in row['observed']['providers']:
            a02 = worker(origin['identity'])
            e = original_event(origin['acceptance_event_id'])
            require(a02['result_sha256']==origin['result_sha256']
                and e['data']['accepted']==origin['accepted']
                and e['data']['decision_factors']['micro_result_sha256']==a02['result_sha256'],
                'Owner compared an unexecuted provider acceptance')
            disclosure = one(owner_plan['disclosures'],lambda d:d['provider_id']==origin['provider_id'],
                'Missing original provider disclosure')
            initial_offer = one(owner_plan['objects'],lambda o:o['ref']==disclosure['offer_ref'],'Missing initial offer')['value']
            actual_offer = one(r['source_reading'],lambda s:s['ref']==disclosure['offer_ref'],'Missing compared offer')['projection']
            count = sum(h['provider_id']==origin['provider_id'] for h in row['observed']['prior_own_commissions'])
            require(actual_offer['priority']['value']==initial_offer['priority']['value']+
                (row['observed']['repeat_provider_priority_penalty']*count if origin['accepted'] else 0),
                'Actual Owner history did not reach the comparison priority')
        team = one(teams,lambda e:e['project_id']==scope['project_id'],'Missing selected team')
        selected = team['data'][roles[scope['role']]]
        require(final['output']['data'].get('selected_agent_id')==selected
            and r['result']['payload']['choice']==('reject_all' if selected is None else 'accept')
            and team['data']['owner_selections'][scope['role'].lower()]['micro_result_sha256']==r['result_sha256'],
            'Native team differs from independent Owner decision')
        owner_proofs.append({'scope':scope,'identity':r['identity'],'result_sha256':r['result_sha256'],
            'micro_choice':r['result']['payload']['choice'],'selected_provider_id':selected,
            'team_event_id':team['event_id'],'team_event_sha256':task_digest(team)})
    for row in confirms:
        digest_valid(row)
        r = worker(row['identity'])
        observed = row['observed']
        team = original_event(row['event_id'])
        require(row['state']=='formed' and row['choice']==r['result']['payload']['choice']=='confirm'
            and row['result_sha256']==r['result_sha256'] and observed['event_sha256']==task_digest(team)
            and team['data'][roles[row['role']]]==row['organization_id']
            and saved[observed['provider_task_key']]['result_sha256']==observed['provider_result_sha256']
            and saved[observed['owner_task_key']]['result_sha256']==observed['owner_result_sha256'],
            'A03 lost exact actual selection and independent original acceptances')
        appointment = source(r,'Appointment')
        require(appointment['status']=='selected' and appointment['service_relationship_ref'] is None
            and appointment['reservation_ref'] is None,'Private A03 fabricated a formal relationship/reservation')
        source_bound(r,observed)
        confirmation_proofs.append({'identity':r['identity'],'result_sha256':r['result_sha256'],
            'team_event_id':team['event_id'],'team_event_sha256':task_digest(team),'choice':row['choice']})
    statuses = Counter()
    for row in feedback:
        digest_valid(row)
        r = worker(row['identity'])
        o = row['observed']
        e = original_event(o['event_id'])
        require(row['state']=='formed' and r['result']['payload']['choice']=='record_feedback'
            and r['result_sha256']==row['result_sha256'] and o['source_event_sha256']==task_digest(e),
            'A12 did not read the exact actual event')
        source_bound(r,o)
        actual = source(r,'Feedback')
        require(actual['event_sha256']==task_digest(actual['event']) and actual['event']['outcomes']==[]
            and actual['recipient_organization_id']==r['identity']['organization_id']
            and o['data']['status'] in r['result']['payload']['interpretation'], 'A12 fabricated performance or changed recipient')
        if o['event_type']=='consultant_team_appointed':
            require(o['data']['status']=='appointed' and 'owner_selections' not in o['data']
                and e['data'][roles[r['identity']['role']]]==r['identity']['organization_id'], 'Unselected firm received selection feedback')
        statuses[o['data']['status']]+=1
        feedback_proofs.append({'identity':r['identity'],'result_sha256':r['result_sha256'],
            'actual_event_id':e['event_id'],'actual_event_sha256':task_digest(e),'status':o['data']['status']})
    require(statuses=={'accepted_pending_owner_selection':7,'declined':1,'appointed':5}
        and len(later)==1 and len(workers)==40,'Unexpected professional action outcomes')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only audit modified journal')
    return {'batch':'3C','status':'passed_for_professional_intake_appointment_and_private_feedback',
        'native_ticks':simulation['current_tick'],'projects':len(simulation['project_results']),'technical_tasks':len(tasks),
        'original_micro_actions':dict(Counter(r['identity']['action_id'] for r in workers)),
        'intake_requests':intake_proofs,'owner_decisions':owner_proofs,'private_confirmations':confirmation_proofs,
        'private_feedback':feedback_proofs,'feedback_status_counts':dict(statuses),
        'later_intake_consumers':len([r for r in intake_proofs if r['consumed_actual_history']]),
        'later_engineer_decline':later,'journal_sha256':before,'read_only':True,
        'macro':macro_snapshot_reader(),'overall_goal3_complete':False,
        'boundary':'Native team/normalized engagement and private A03/A12 only. Detailed relationship/task/design/cost issuers and role-specific monthly decisions remain explicit open items.'}


def run_scenario(directory, config):
    require(config['schema_version']=='professional-chain-acceptance.v1'
        and config['bundle_options']==dict(with_owner=True,with_confirmation=True,
            with_opportunity=True,with_feedback=True), 'Unsupported fixed professional scenario')
    build_bundle(directory/'input',run_id=config['run_id'],**config['bundle_options'])
    verify_bundle(directory/'input')
    args = [sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.professional_intake_native:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        completed = subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':completed.returncode})
    require(completed.returncode==0,'Native run failed; inspect preserved stderr and original journal')


def review_remaining_sources():
    """Pin reviewed producers and missing handoffs; this is not business evidence."""
    from integration.contractor_construction_source_review import _source
    from integration.professional_work_source_review import professional_work_reviews
    macro = ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    original = [
        _source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine.'+name)
        for name in ('_handle_initiation','_collect_appointment_decisions','_handle_design','_record_lifecycle_task')]
    original += [_source(macro,'simulation/project_state_update_engine.py','ProjectStateUpdateEngine.'+name)
        for name in ('update_design_state','update_cost')]
    original += [_source(macro,'simulation/engagement_manager.py','EngagementManager.create_engagement'),
        _source(macro,'simulation/simulation_engine.py','SimulationEngine._run_agent_operations')]
    for role in ('Architect','Engineer','QS'):
        original.append(_source(macro,'agents/'+role.lower()+'_agent.py',role+'Agent.decide_monthly_operation'))
    for item in original:
        item['path'] = (macro/item['path']).relative_to(ROOT).as_posix()
    designs = [_source(ROOT,'src/actions/roles/architect_design.py','compile_design'),
        _source(ROOT,'src/actions/roles/engineer_design.py','compile_professional_design')]
    return {'batch':'3C','status':'reviewed_sources_and_explicit_open_handoffs_not_runtime_coverage',
        'native_producers':original,'existing_work_reviews':professional_work_reviews(ROOT,macro),
        'existing_design_processors':designs,
        'native_team_boundary':'Real selected team and ACTIVE normalized engagements exist; original own-resource readers can read them. They do not bind a detailed service relationship, released professional task, per-person commitments or independent quantities/prices.',
        'design_state_boundary':'update_design_state computes aggregate design/information quality, cost and duration. _handle_design checks thresholds; archived owner design_coordination_task is not an independently released design task or received deliverable.',
        'remaining_handoffs':[
            {'business':'Professional detailed planning and design / downstream QS costing',
             'status':'blocked_missing_verified_detailed_sources_and_native_consumer',
             'missing':'Detailed relationship/task/authority and quantity/price provenance; equivalent native submission/reception/approval of exact original design/cost outputs.',
             'next_step':'Reuse original A04/A05 and QSCost preparation/publication after independently verified producers and downstream consumers are available. Keep aggregate macro state unchanged.'},
            {'business':'Architect/Engineer/QS role-specific monthly operations',
             'status':'blocked_for_micro_business_judgment',
             'existing':'Native stable_pick operations run; original A01/A12 and optional QSEvaluationLearning exist. QS monthly recording then calls the native business proposal and explicitly does not choose the formal monthly operation.',
             'missing':'Authorized action-specific market/qualification/training/cost facts and a micro business result selecting each applicable monthly operation; actual result reception for any claimed capability/database/qualification effects.',
             'next_step':'Keep these operations uncompleted in GOAL 3. Reuse private recording only for what it proves; do not call native proposal plus optional A12 a micro monthly decision.'}],
        'overall_goal3_complete':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/professional_chain.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'macro-before.json',macro_hashes())
        config = read(args.config)
        _write(directory,'source-config.json',config)
        run_scenario(directory,config)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks = verify_scenario(directory,read(directory/'source-config.json'))
    require(read(directory/'macro-before.json')==macro_hashes(),'Frozen macro sources changed')
    if not args.check_only:
        _write(directory,'checks.json',checks)
        _write(directory,'source-boundaries.json',review_remaining_sources())
        write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),
        'macro_unchanged_files':macro_hashes()['file_count']}))


def write_delivery(directory, checks):
    lines = ['# GOAL 3C 专业委任运行记录', '',
        '状态：专业受理、原宏观委任及私有反馈主链通过；后续专业工作与月度动作仍有阻塞，GOAL 3 整体未完成。', '',
        f"原宏观运行 {checks['native_ticks']} 个时点、{checks['projects']} 个项目；40 个原微观动作、{checks['technical_tasks']} 个技术任务均形成结果。",
        '宏观 174 文件基线及额外 Python 源文件在运行前后相同。', '',
        '| 项目/时点 | 角色 | 原 OWN-A04 结果 | 宏观实际中选 | 实际团队事件 |',
        '| --- | --- | --- | --- | --- |']
    for row in sorted(checks['owner_decisions'],key=lambda r:(r['scope']['tick'],r['scope']['role'])):
        scope = row['scope']
        lines.append(f"| {scope['project_id']} / {scope['tick']} | {scope['role']} | {row['micro_choice']} | {row['selected_provider_id'] or '无中选'} | {row['team_event_id']} |")
    later = checks['later_engineer_decline'][0]
    history = later['consumed_actual_history'][0]
    lines += ['', '后轮消费：',
        f"- 首轮实际委任 {history['event_id']}，完整事件 SHA256 `{history['event_sha256']}`。",
        f"- 原 ENGINEER-A12 完成私有反馈，结果 SHA256 `{history['A12_result_sha256']}`。",
        '- 次轮 ENGINEER-A02 读取同一实际委任、同一 A12 及原 A03 确认；实际次数达到初始策略门槛 1，FeeBasis.new_work_policy 从 evaluate 变为 decline。',
        f"- 原 A02 返回 decline，原宏观实际拒绝事件 {later['actual_event']['event_id']}，微观结果 SHA256 `{later['result_sha256']}`。",
        '- 次轮业主也读取自己的历史委任；同建筑师的比较序号按初始惩罚 2 增加，原 OWN-A04 从建筑师 A 改选 B。', '',
        '独立重跑（新目录）：', '```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_chain --config config/professional_chain.json --output output/integration/goal3c_new_run",
        '```', '', '只读复核：', '```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_chain --check-only --output {directory.as_posix()}",
        '```', '',
        'source-config.json / input/ 是执行前输入；command.json 是原 CLI 命令；runtime/ 保存原结果、观察和任务库。',
        'checks.json 保存微观身份→原宏观实际事件→后轮消费者对应关系。source-boundaries.json 是来源审查，不能当作业务成功证据。',
        '原宏观确实建立项目团队及规范化 ACTIVE engagement。私有 A03 不建立详细 ServiceRelationship 或人员预留，A12 不虚构专业绩效、培训或资格。',
        '详细专业任务、设计/造价成果的原生产者及等价提交接收接口，以及月度微观业务判断继续列为阻塞。', '']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    files = {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}
    names = ['config/professional_chain.json','config/gba_v1_business_wiring.json',
        'docs/专业委任接线与验收.md','docs/宏观动作接线清单.md',
        'integration/verify_professional_chain.py','integration/professional_intake_development.py',
        'integration/professional_intake_native.py','integration/professional_intake_scope.py',
        'integration/professional_intake_feedback.py','integration/professional_opportunity_native.py',
        'integration/professional_appointment_native.py','integration/professional_appointment_native_sources.py',
        'integration/owner_commission_native.py','integration/owner_commission_native_sources.py',
        'integration/owner_commission_native_feedback.py','integration/native_lifecycle_actions.py',
        'integration/professional_work_source_review.py','integration/qs_evaluation_learning.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'professional-chain-artifacts.v1','files':files,
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


if __name__ == '__main__':
    main()
