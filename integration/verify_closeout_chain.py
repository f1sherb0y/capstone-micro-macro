"""Fixed GOAL 3I actual closeout communication, feedback and monthly coverage."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import _write,_write_launch_files,verify_bundle
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='closeout-chain.v1' and config['ticks']==3
        and config['max_prior_final_accounts']==1 and config['bank_monthly_max_prior_reviews']==1,
        'Unsupported fixed closeout configuration')


def run_scenario(directory,*,config):
    from integration.financing_professional_development import build_bundle
    directory.mkdir(parents=True,exist_ok=False);input_directory=directory/'input';input_directory.mkdir()
    foundation=input_directory/'foundation'
    build_bundle(foundation,run_id=config['run_id'],with_government_and_supply=True,
        with_owner_opportunity=True,max_prior_initiations=999,max_prior_final_accounts=config['max_prior_final_accounts'],
        with_final_account_discussion=True,with_final_account_response=True,with_contractor_final_account_response=True,
        with_final_account_learning=True,professional_project_object_types={'PGEN0001':'industrial','PGEN0002':'industrial'},
        with_bank_monthly_strategy=True,bank_monthly_max_prior_reviews=config['bank_monthly_max_prior_reviews'],
        with_government_monthly_feedback=True)
    for name in ('macro-request.json','native-host.json','assembly-host.json'):
        _write(input_directory,name,read(foundation/name))
    _write_launch_files(input_directory,assembly_hook='integration.closeout_native_evidence:configure_assembly',
        allow_native_project_generation=True,allow_native_initial_projects_with_generation=True,readme_override=__doc__)
    verify_bundle(input_directory)
    args=[sys.executable,'-m','integration.run','--input',str(input_directory/'macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--allow-native-project-generation','--allow-native-initial-projects-with-generation',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(input_directory/'native-host.json'),
        '--module-assembly-hook','integration.closeout_native_evidence:configure_assembly',
        '--module-assembly-config',str(input_directory/'assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original closeout run failed; preserve logs and actual journal')


def verify_scenario(directory):
    from integration.closeout_source_review import monthly_inventory
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original closeout process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];export=output['module_host_extension']['host']
    host=export['chain'];events=export['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==3,'Original closeout window incomplete')
    initial=read(directory/'input/macro-request.json');roles={a['agent_id']:a['role'] for a in initial['agents']}
    require(len({e['event_id'] for e in events})==len(events)
        and not any(e['data'].get('agent_observer_errors') for e in events),'Global events duplicated or observer failed')
    for p in simulation['project_results']:
        for event in p['event_log']:
            actual=one(events,lambda e:e['event_id']==event['event_id'],'Original project/global event missing')
            require(actual==event,'Original global/project logs differ')
    project=one(simulation['project_results'],lambda p:p['project_id']=='shared-final-account-review','Final account project missing')
    original=one(initial['initial_projects'],lambda p:p['project_id']==project['project_id'],'Initial closeout case missing')
    require(not original['event_log'] and not original['flags'].get('final_account_review_started'),
        'Current actual review or settlement was prefilled')
    review=one(events,lambda e:e['project_id']==project['project_id'] and e['event_type']=='final_account_review_started','Actual review missing')
    settlement=one(events,lambda e:e['project_id']==project['project_id'] and e['event_type']=='final_account_settled','Actual settlement missing')
    require(review['tick']==1 and settlement['tick']==2 and project['current_stage']=='closed','Original aggregate settlement did not close')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    tables={'OWN-A06':'owner_payment_results','CONTRACTOR-A11':'contractor_closeout_results',
        'QS-A09':'qs_final_account_results','QS-A12':'qs_learning_results','OWN-A03':'owner_investment_results',
        'BANK-A01':'bank_strategy_results','GOV-A12':'government_feedback_results'}
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        originals={a:[json.loads(v) for v, in db.execute('SELECT record FROM '+table)] for a,table in tables.items()}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Original closeout or monthly task unresolved or output changed')
    def saved(record):
        digest_valid(record);require(record==metadata[record['key']],'Export differs from durable original record')
        identity=TaskIdentity(**record['identity'])
        result=one(originals[identity.action_id],lambda s:s['identity']==identity.as_dict(),'Original micro result missing')
        digest_valid(result);require(task_digest(result['result'])==result['result_sha256']==record['result_sha256'],
            'Original micro result digest changed')
        require(any(s['projection'].get('content_hash')==task_digest(record['observed']) for s in result['source_reading']),
            'Actual feedback was not bound into saved original micro input')
        return identity,result
    lifecycle=host['lifecycle'];require(lifecycle['all_private_actions_formed'] and not lifecycle['formal_commands_submitted'],
        'Private communication became formal closeout or stayed unresolved')
    require(len(lifecycle['actions'])==7,'Expected original communication successors and QS feedback missing')
    actions=[]
    for record in lifecycle['actions']:
        identity,result=saved(record)
        event=one(events,lambda e:e['event_id']==record['observed']['event_id'],'Original lifecycle trigger missing')
        require(record['state']=='formed' and event['project_id']==project['project_id']
            and result['result']['kind']=='completed','Private original closeout action not formed')
        for dependency in record['dependencies']:
            require(any(r['identity']==dependency['identity'] and r['result_sha256']==dependency['result_sha256']
                for r in lifecycle['actions']),'Original private dependency identity changed')
            receipt=dependency.get('native_communication')
            if receipt is not None:require(receipt['status']=='observed','Successor lacks actual native communication')
        if identity.action_id=='QS-A12':
            require(event==settlement and result['result']['payload']['choice']=='record_feedback'
                and record['observed']['data']['observed_review_event_id']==review['event_id']
                and len(record['dependencies'])==1 and record['dependencies'][0]['identity']['action_id']=='QS-A09',
                'QS feedback did not consume exact original settlement and review result')
            require('no cash payment, debt clearance' in result['result']['payload']['interpretation'],
                'QS feedback inferred financial clearance')
        actions.append({'plan_id':record['plan_id'],'identity':identity.as_dict(),'trigger_event_id':event['event_id'],
            'trigger_sha256':task_digest(event),'result_sha256':result['result_sha256'],
            'source_reading_sha256':result['source_reading_sha256'],'choice':result['result']['payload']['choice'],
            'dependencies':record['dependencies']})
    receipts={**lifecycle['final_account_communications'],**lifecycle['final_account_questions']}
    require(len(receipts)>=4 and all(r['status']=='observed' for r in receipts.values()),'Actual closeout room publications missing')
    consumers=[];cash_views=[]
    for record in host['opportunity']['requests']:
        identity,result=saved(record);query=record['observed']['own_final_accounts'];digest_valid(query)
        cash_views.append({s['ref']['id']:{f:{k:v for k,v in s['projection'][f]['value'].items() if k!='basis_ref'}
            for f in ('actual_cash','restricted_cash')} for s in result['source_reading'] if s['ref']['kind']=='FundingSource'})
        require(cash_views[-1] and cash_views[-1]==cash_views[0],'Aggregate settlement increased independent private cash')
        if record['scope']['tick']<3:
            require(not query['settlements'] and not record['observed']['final_account_review_preference_pauses_initiation'],
                'Same/future settlement leaked to earlier Owner judgment')
            continue
        item=one(query['settlements'],lambda s:s['event_id']==settlement['event_id'],'Later actual settlement missing')
        require(item['source_event_sha256']==task_digest(settlement) and item['observed_review_event_id']==review['event_id']
            and item['tick']<record['scope']['tick'] and query['organization_id']==identity.organization_id==project['owner_id']
            and item['payment_execution_status']==item['obligation_clearance_status']=='not_proven' and query['currency'] is None,
            'Later Owner borrowed another party, same-tick result, cash or cleared duties')
        policies=[s['projection']['policy'] for s in result['source_reading'] if s['ref']['kind']=='ProjectRegistrationProfile']
        require(record['observed']['final_account_review_preference_pauses_initiation'] and policies
            and all(p=={'state':'known','value':'reject'} for p in policies)
            and result['result']['payload']['choice']=='reject','Actual settlement history was only printed')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='owner_project_opportunity'
            and t['output']['data'].get('native_owner_opportunity_scope')==record['scope'],'Later Owner final missing')['output']
        require(final['decision'] is False and final['data']['micro_result_sha256']==result['result_sha256'],
            'Later micro result not returned to original macro interface')
        consumers.append({'identity':identity.as_dict(),'settlement':item,'result_sha256':result['result_sha256'],
            'source_reading_sha256':result['source_reading_sha256'],'applied_registration_policy':policies,'native_final_response':final})
    require(len(consumers)==4 and any(e['event_type']=='project_opportunity_declined' and e['tick']==3
        and e['agent_id']==project['owner_id'] for e in events),'Later actual Owner refusal/execution missing')
    monthly=[]
    for role,rows,history_field in (('Bank',host['bank']['monthly_strategy']['requests'],'prior_own_monthly_strategy'),
            ('Government',host['government']['monthly']['requests'],'prior_monthly_feedback')):
        require(len(rows)==6,'Original monthly composition did not execute both organizations for three ticks')
        for record in rows:
            identity,result=saved(record);scope=record['scope']
            event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id
                and e['tick']==scope['tick'],'Actual monthly execution missing')
            final=one(tasks,lambda t:t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='monthly_enterprise_operation'
                and t['output']['data'].get('micro_task_key')==identity.key,'Monthly original final response missing')['output']
            proposal=one(tasks,lambda t:t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_monthly_operation'
                and t['output']['factors'].get('micro_task_key')==identity.key,'Monthly original proposal missing')['output']
            require(final['data']['micro_result_sha256']==proposal['factors']['micro_result_sha256']==result['result_sha256']
                and final['data']['proposal_response_sha256']==record['proposal_response_sha256']==task_digest(proposal)
                and final['decision'] is True and proposal['accepted'] is True
                and event['data']['operation']==final['action_type']==proposal['action_type']
                and final['reason']==proposal['reason'] and event['description']==proposal['data']['description']
                and all(event['data'][k]==v for k,v in proposal['data'].items()),
                'Monthly original proposal/final result and actual event differ')
            history=record['observed'][history_field]
            require(len(history)==scope['tick']-1,'Original monthly did not consume its earlier outcomes')
            for h in history:
                prior=one(events,lambda e:e['event_id']==h['event_id'],'Earlier own monthly event missing')
                require(prior['agent_id']==identity.organization_id and prior['tick']<scope['tick']
                    and h['source_event_sha256']==task_digest(prior),'Monthly history lost own exact earlier event')
            monthly.append({'role':role,'operation':event['data']['operation'],'identity':identity.as_dict(),
                'event_id':event['event_id'],'event_sha256':task_digest(event),'choice':result['result']['payload']['choice'],
                'result_sha256':result['result_sha256'],'original_proposal':proposal,'original_final_response':final,
                'event_hash_provenance':'Original event drops micro factors; own org/tick, operation and proposal description match actual event; saved proposal/final responses retain exact micro hash',
                'prior_own_outcomes':history})
    inventory=monthly_inventory(events,monthly,agent_roles=roles)
    require(inventory['executed_subactions']==3 and inventory['blocked_subactions']==29,
        'Original monthly subaction coverage differs; review actual evidence')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only check modified original task journal')
    return {'status':'actual_communication_settlement_feedback_and_bounded_monthly_verified_detailed_closure_blocked',
        'native_ticks':3,'actual_review':review,'actual_settlement':settlement,'lifecycle_actions':actions,
        'communication_receipts':receipts,'later_owner_consumers':consumers,'independent_cash_unchanged':True,
        'monthly_proofs':monthly,'monthly_inventory':inventory,'technical_tasks':len(tasks),
        'formed_micro_actions':dict(Counter(t['identity']['action_id'] for t in tasks if t['identity']['purpose']=='action')),
        'native_validation_diagnostics':[e for e in events if e['event_type']=='invalid_action'],
        'formal_handover_clearance_or_released_continuing_duties_proven':False,'journal_sha256':before,'read_only':True}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    case=verify_scenario(directory/'case')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro sources changed')
    from integration.closeout_source_review import source_boundaries
    boundaries=source_boundaries()
    return {'batch':'3I','status':'bounded_closeout_and_monthly_feedback_verified_required_wiring_incomplete',
        'overall_goal_complete':False,'scenario':case,'macro':macro,'source_boundaries':boundaries,
        'monthly_executed_subactions':case['monthly_inventory']['executed_subactions'],
        'monthly_unwired_subactions':case['monthly_inventory']['blocked_subactions']}


def write_delivery(directory,checks):
    case=checks['scenario']
    lines=['# GOAL 3I 本批运行记录','',
        '结算沟通、原宏观汇总结算、QS 后轮记录、业主后轮投资判断和银行/监管月度反馈已核验；GOAL 3 仍未完成。','',
        f"原审查：{case['actual_review']['event_id']} / tick 1；原结算：{case['actual_settlement']['event_id']} / tick 2；项目由原引擎关闭。",
        f"{len(case['lifecycle_actions'])} 个私有微观动作，{len(case['communication_receipts'])} 项原通信回执，{len(case['later_owner_consumers'])} 项 tick 3 业主后轮消费；{len(case['monthly_proofs'])} 项原月度执行及严格较早结果消费。",
        f"原八角色月度函数共 32 个业务子动作，实际执行并接微观的子动作 3 个，未接微观 29 个。技术任务 {case['technical_tasks']} 个。",'',
        '新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_closeout_chain `",
        '  --config config/closeout_chain.json `','  --output output/integration/goal3i_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_closeout_chain --check-only --output '{directory.as_posix()}'",'```','',
        '本场景复用原共享场景编制器，期初为独立声明的待结算项目，并非本次从零投标建成。期初没有本轮结算事件或审查标记；原引擎在 tick 1/2 实际生成审查和结算。',
        '业主、承包商与 QS 的私有立场、问答及回执来自原消息接口，不代表正式组件清偿或双方最终同意。QS-A12 绑定同一实际结算事件与原 QS-A09 依赖；没有现金误差或清债推断。',
        'tick 3 原 OWN-A03 查询同一业主严格较早的结算事件，按场景期初阈值 max_prior_final_accounts=1 暂缓新增立项；reject 经原宏观最终接口处理，并产生 project_opportunity_declined。独立现金/受限现金来源保持原值。',
        '两家银行每家三轮 BANK-A01，经原月度接口执行 review_credit_pipeline/adjust_credit_terms；两个监管机构每家三轮 GOV-A12，经原接口执行 review_policy_feedback。微观哈希保存在原提案及最终响应；实际事件按本机构/时点、操作与描述对应，事件自身不携带微观哈希。后轮输入绑定本机构较早的 agent_operation 事件及哈希。',
        '全局事件仅由新只读证据封装导出，没有替换宏观方法、注入反馈事件或新增业务执行器。monthly-business-wiring.json 是逐子动作清单，不是调度器；角色参与和原生独自执行均不充当微观覆盖。',
        '六类详细来源阻塞见 source-boundaries.json：明细结算、真实移交、业主经营、商业持续义务、专业费用/转交、银行债务监控及清收结清。其余 29 项月度判断仍未接通；不将阶段 closed 推定为到账、清债、移交或解除持续义务。',
        'runtime/ 与 checks.json 保存实际输入、原微观结果、依赖、执行回执及后轮消费对应关系；原本地 invalid_action 诊断保留且不计成功。',
        f"宏观 {checks['macro']['file_count']} 个文件基线及全部宏观 Python 源码未改。所有旧批证据独立保留，本批交付不等于宏观业务动作全覆盖，也不等于原 PLAN 完成。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/verify_closeout_chain.py','integration/closeout_source_review.py','integration/closeout_native_evidence.py',
        'config/closeout_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
        'docs/结算移交及后续经营接线与验收.md','docs/宏观动作接线清单.md',
        'integration/financing_professional_native.py','integration/financing_professional_development.py',
        'integration/native_lifecycle_actions.py','integration/bindings/gba_v1_final_accounts.py',
        'integration/owner_opportunity_native_sources.py','integration/bank_monthly_native.py','integration/government_monthly_native.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'closeout-chain-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'config/closeout_chain.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--check-only',action='store_true');args=p.parse_args(argv)
    directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        run_scenario(directory/'case',config=config)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:
        _write(directory,'checks.json',checks);_write(directory,'source-boundaries.json',checks['source_boundaries'])
        _write(directory,'monthly-business-wiring.json',checks['scenario']['monthly_inventory']);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_unchanged_files':checks['macro']['file_count'],
        'monthly_executed':checks['monthly_executed_subactions'],'monthly_unwired':checks['monthly_unwired_subactions']}))


if __name__=='__main__':main()
