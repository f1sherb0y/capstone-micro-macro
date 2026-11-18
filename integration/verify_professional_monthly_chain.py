"""Run and inspect original professional monthly judgment, execution and own feedback."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from integration.contractor_tender_development import _write,verify_bundle
from integration.professional_monthly_development import build_bundle
from integration.professional_monthly_native import OPERATIONS
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest


def run_existing_input(directory,*,assembly_hook='integration.professional_monthly_native:configure_assembly'):
    input_directory=directory/'input';verify_bundle(input_directory)
    args=[sys.executable,'-m','integration.run','--input',str(input_directory/'macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client','--agent-client-config',str(input_directory/'native-host.json'),
        '--module-assembly-hook',assembly_hook,'--module-assembly-config',str(input_directory/'assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original monthly run failed; preserve actual logs and journal')


def validate_config(config):
    require(config['schema_version']=='professional-monthly-chain.v1' and config['ticks']==2
        and config['minimum_market_demand']=='1' and config['maximum_prior_outreach']==1
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}},'Unsupported fixed professional monthly cases')


def verify_scenario(directory,*,participates,role_operations=None,worker_tables=None,expected_records=6,participation_choice='express_interest',nonparticipation_choice=None):
    role_operations=OPERATIONS if role_operations is None else role_operations
    worker_tables={'Architect':'architect_opportunity_results','Engineer':'engineer_opportunity_results','QS':'qs_market_results'} if worker_tables is None else worker_tables
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Monthly process failed')
    initial=read(directory/'input/macro-request.json');output=read(directory/'runtime/result.json')
    simulation=output['simulation'];host=output['module_host_extension']['host'];events=host['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==2,'Original monthly window incomplete')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers={role:[json.loads(v) for v, in db.execute('SELECT record FROM '+table)] for role,table in worker_tables.items()}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original monthly task incomplete or changed')
    proofs=[]
    require(len(host['requests'])==expected_records,'Expected own monthly actions over two actual ticks')
    for record in host['requests']:
        digest_valid(record);require(record==metadata[record['key']],'Original durable record differs')
        i=TaskIdentity(**record['identity']);saved=one(workers[i.role],lambda r:r['identity']==i.as_dict(),'Original A01 result missing');digest_valid(saved)
        require(saved['result_sha256']==record['result_sha256']==task_digest(saved['result']),'Original professional result changed')
        observation=one(saved['source_reading'],lambda s:s['ref']['kind']=='OutreachObservation','Original monthly constraints never read')['projection']
        policy=one(saved['source_reading'],lambda s:s['projection'].get('outreach_limits') is not None,'Authorized original outreach policy missing')['projection']['outreach_limits']
        require(policy['minimum_market_demand']['value']=='1' and policy['maximum_prior_outreach']==1,
            'Original micro did not receive the fixed authorized outreach thresholds')
        observed=record['observed'];tick=record['scope']['tick'];history=observed['prior_own_monthly_outcomes']
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and record['state']=='formed','Original macro observation or workflow changed')
        require(any(s['projection'].get('content_hash')==task_digest(observed) for s in saved['source_reading']),
            'Original native input and feedback not bound into micro reading')
        require(len(history)==tick-1 and observation['prior_outreach_count']==sum(h['participated'] for h in history)
            and observation['market_demand']['value']==str(observed['macro_environment']['market_demand_index']),
            'Original macro index/history did not enter original micro constraint')
        for h in history:
            e=one(events,lambda e:e['event_id']==h['event_id'],'Own monthly actual result missing')
            require(e['agent_id']==i.organization_id and e['tick']<tick and h['source_event_sha256']==task_digest(e),
                'Micro history borrowed another organization or same/future result')
        active=participates and tick==1
        inactive_choice=nonparticipation_choice or ('decline' if i.role in {'Engineer','Contractor'} else 'ignore')
        expected_choice=participation_choice if active else inactive_choice
        require(saved['result']['kind']=='completed' and saved['result']['payload']['choice']==expected_choice,'Original monthly A01 did not apply demand/outreach limit')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output']['factors'].get('micro_task_key')==i.key,'Original monthly proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output']['data'].get('micro_task_key')==i.key,'Original monthly final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==i.organization_id and e['tick']==tick,'Original monthly execution missing')
        require(proposal['accepted'] is True and proposal['factors']['micro_participation']==final['decision']==active
            and proposal['action_type']==final['action_type']==role_operations[i.role]
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==saved['result_sha256']
            and final['data']['proposal_response_sha256']==record['proposal_response_sha256']==task_digest(proposal)
            and event['data']['operation']==(role_operations[i.role] if active else 'maintain_operations')
            and event['description']==proposal['data']['description'],'Original macro execution changed micro judgment')
        proofs.append({'identity':i.as_dict(),'scope':record['scope'],'observation':observation,'applied_original_policy':policy,'history':history,
            'choice':expected_choice,'micro_result_sha256':saved['result_sha256'],'source_reading_sha256':saved['source_reading_sha256'],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event)})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only check changed original journal')
    return {'status':'actual_original_professional_monthly_decisions_execution_and_later_consumption_verified','proofs':proofs,
        'initial_market_demand_index':initial['macro_environment']['market_demand_index'],'technical_tasks':len(tasks),'read_only_journal_sha256':before,
        'native_diagnostics':[e for e in events if e['event_type']=='invalid_action'],'remaining_professional_monthly_subactions':8,
        'formal_invitation_appointment_training_qualification_or_cost_database_effects_proven':False}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name,participates=name=='high') for name in config['scenarios']}
    high=read(directory/'high/input/macro-request.json');low=read(directory/'low/input/macro-request.json')
    high['macro_environment']['market_demand_index']=low['macro_environment']['market_demand_index']
    require(high==low,'Controlled original macro inputs differ beyond initial market demand')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    contacts=[]
    for role,operation in OPERATIONS.items():
        proofs=[{'scenario':name,**p} for name,case in cases.items() for p in case['proofs'] if p['identity']['role']==role]
        contacts.append({'role':role,'operation':operation,'status':'executed_micro_judgment_native_execution_and_later_own_feedback',
            'macro_input':'Original current monthly macro_environment plus authorized strictly earlier own micro-origin monthly outcomes',
            'micro_handler':'integration.professional_monthly_native:ProfessionalMonthlyApplication',
            'original_micro_action':role.upper()+'-A01','micro_processing':'Original professional A01 optional sourced outreach constraints, original assembler/worker',
            'return_to_macro':'Legal original positive candidate proposal then original final response carries exact micro participation; refusals execute native maintain_operations',
            'feedback_consumer':'Next original own A01 constraint counts actual own outreach, not maintenance or another enterprise',
            'actual_business_events':[{'scenario':p['scenario'],'event_id':p['actual_event']['event_id'],'event_sha256':p['actual_event_sha256']} for p in proofs if p['actual_event']['data']['operation']==operation],
            'later_consumers':[{'scenario':p['scenario'],'identity':p['identity'],'history':p['history']} for p in proofs if p['scope']['tick']==2]})
    return {'batch':'3C-monthly','status':'three_professional_monthly_outreach_contacts_verified_eight_remaining_blocked',
        'overall_goal3_complete':False,'cases':cases,'contacts':contacts,'controlled_input_difference':'original initial macro_environment.market_demand_index=1.2 versus 0.6; same random seed, private policy and supported scenario entry',
        'macro':macro}


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],
        'remaining_professional_monthly_subactions':8,'overall_goal3_complete':False})
    lines=['# GOAL 3C 月度专业业务补接运行记录','',
        '复用原 ARCHITECT-A01、ENGINEER-A01、QS-A01 及其任务、授权、只读来源和结果处理器。三项月度入口的决定、原宏观实际执行及后轮消费已核验；其余八项专业月度子动作仍阻塞，GOAL 3 未完成。','',
        '| 原配置 | tick 1 原微观 / 实际执行 | tick 2 原微观 / 实际执行 |',
        '| --- | --- | --- |',
        '| market_demand_index=1.2 | 三角色 express_interest / 各自原月度业务 | 原 A01 读取本机构实际业务事件，达到本入口次数上限 1，ignore 或 decline / maintain_operations |',
        '| market_demand_index=0.6 | 需求低于独立私有阈值 1，ignore 或 decline / maintain_operations | 读取同一机构较早原维护事件，已开展拓客次数仍为 0；需求仍不足 / maintain_operations |','',
        '两组通过原 SimulationCreateRequest.macro_environment 构造差异，原宏观输入除期初需求指数外逐字段一致；同种子 42、同私有阈值、授权和档案。实际首轮指数先由原宏观更新，再进入原 A01 的可选约束；计算位置为 src/actions/roles/professional_outreach.py。没有在适配器中预填微观选择，没有改变机会访问权限。',
        '原提案契约仅允许正向候选对，因此先提交三角色各自合法候选，factors 显示真实 micro_participation；真正的参与/拒绝由同一原 A01 结果经最终决定接口交回。候选 accepted=True 不算已开展；计数只接受原事件与原最终响应一致的实际结果。',
        '新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_monthly_chain `",
        '  --config config/professional_monthly_chain.json `','  --output output/integration/goal3c_monthly_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_professional_monthly_chain --check-only --output '{directory.as_posix()}'",'```','',
        '输入为原场景编制器期初声明的合成市场档案、授权及独立私有来源；不是实际收件邀请或已执行委任。期初待汇总结算项目只为原引擎自然维持两时点，不作为从零履约或清偿证据。原微观判断只控制本入口的月度拓客候选及最终参与，不控制全部其他月度子动作。',
        '后轮只计同一运行、本机构、本入口严格较早的实际 monthly agent_operation，并校验原 A01、提案、最终响应及事件哈希。原事件不携带微观哈希，靠机构/时点、操作及描述对应。维护事件进入历史，但不增加已开展拓客次数；不声称完整企业业务历史或占用/现金变化。',
        '原宏观随机能力标量更新和资源机制保持原样；不推断真实培训、资格续期、客户接触、委任、服务收费或成本库写入。源码冻结、全局事件只读导出，未增加第二套执行账本。',
        f"两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个技术任务，12 个原 A01 决定，3 个实际专业月度业务及 9 个实际维护结果；各组 tick 2 共六项微观消费较早本机构结果。宏观 {checks['macro']['file_count']} 文件基线及全部 Python 源码未改。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/professional_monthly_native.py','integration/professional_monthly_development.py','integration/verify_professional_monthly_chain.py',
        'src/actions/contracts/professional_outreach.py','src/actions/roles/professional_outreach.py',
        'config/professional_monthly_chain.json','config/gba_v1_monthly_business_wiring.json','config/gba_v1_business_wiring.json',
        'docs/专业月度业务接线与验收.md','docs/宏观动作接线清单.md']
    names += ['src/actions/contracts/'+n+'_objects.py' for n in ('architect_opportunity','engineer_opportunity','qs_market')]
    names += ['src/actions/roles/'+n+'.py' for n in ('architect_opportunity','engineer_opportunity','qs_market')]
    _write(directory,'artifact-manifest.json',{'schema_version':'professional-monthly-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'config/professional_monthly_chain.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile,minimum_market_demand=config['minimum_market_demand'],maximum_prior_outreach=config['maximum_prior_outreach'],ticks=config['ticks'])
            run_existing_input(directory/name)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:
        _write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
