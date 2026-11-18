"""Fixed original generation, monthly screening and subsequent original A03 consumption."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from integration.contractor_tender_development import _write,verify_bundle
from integration.owner_monthly_pipeline_development import build_bundle
from integration.owner_monthly_pipeline import BOUNDARY,OwnerPipelineSettings,attach_pipeline_feedback
from integration.owner_pipeline_sources import received_candidates
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.verify_tender_basic import verify_history
from src.actions.roles.owner_monthly_pipeline import decide_pipeline_review
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config=={'schema_version':'owner-monthly-pipeline-chain.v1','run_id':'goal3i-owner-pipeline','ticks':2,
        'scenarios':{'review_after_one':{'maximum_prior_screens_before_portfolio_review':1},
            'review_after_two':{'maximum_prior_screens_before_portfolio_review':2}}},'Unsupported fixed pipeline controls')


def run_case(directory,*,run_id,profile):
    build_bundle(directory/'input',run_id=run_id,**profile);verify_bundle(directory/'input')
    args=[sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),'--output',str(directory/'runtime'),
        '--offline','--input-format','gba_request','--macro-mode','gba_v1_module','--allow-native-project-generation',
        '--agent-client-factory','integration.native_routes:build_agent_client','--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.owner_monthly_pipeline:configure_assembly','--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
        result=subprocess.run(args,cwd=ROOT,stdout=out,stderr=err)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original pipeline process failed; preserve actual journal, never replay it')


def verify_scenario(directory,*,limit):
    from integration.bootstrap import enable_gba_imports
    enable_gba_imports()
    from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
    from integration.owner_opportunity_native import OwnerOpportunityPolicy
    from integration.owner_opportunity_native_sources import prepare_opportunity_sources
    from integration.owner_opportunity_native_feedback import authorize_owner_history
    from integration.owner_investment_actions import OwnerInvestmentActionAssembler
    from integration.verify_owner_investment import _source_oracle
    from src.organization.registry import OrganizationRegistry
    from src.actions.contracts.common import Reference
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original pipeline process did not complete')
    result=read(directory/'runtime/result.json');sim=result['simulation'];host=result['module_host_extension']['host'];events=host['original_global_events']
    require(sim['status']=='completed' and sim['current_tick']==2 and host['boundary']==BOUNDARY,
        'Original two-month pipeline window incomplete')
    require(len({e['event_id'] for e in events})==len(events)
        and not any(e['data'].get('agent_observer_errors') for e in events),'Original event identity or observer failed')
    dbpath=directory/'runtime/tasks.sqlite';before=hashlib.sha256(dbpath.read_bytes()).hexdigest()
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        saved=[json.loads(v) for v, in db.execute('SELECT record FROM owner_investment_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Original task is unresolved or its output changed')
    records=host['requests'];monthly=host['pipeline_requests'];require(len(records)==8 and len(monthly)==2 and len(saved)==8,
        'Expected exactly four received/evaluated candidates and one monthly review per month')
    settings=OwnerPipelineSettings.model_validate(read(directory/'input/assembly-host.json')['settings'])
    require(settings.pipeline.maximum_prior_screens_before_portfolio_review==limit and host['pipeline_policy']==settings.pipeline.model_dump(mode='json'),
        'Independent initial pipeline policy changed')
    sourcepath=Path(settings.opportunity.file_path);require(hashlib.sha256(sourcepath.read_bytes()).hexdigest()==settings.opportunity.file_sha256,
        'Original independent investment input bytes changed')
    document=read(sourcepath);policy=OwnerOpportunityPolicy.model_validate(document['policies'][0]);org=policy.organization_id
    require(policy.max_prior_initiations==999 and policy.max_prior_declines is None and policy.max_prior_final_accounts is None,
        'A different prior-result policy could explain this comparison')
    organizations=OrganizationRegistry(document['run_id'])
    for organization in settings.opportunity.authority.organization_snapshot.organizations:organizations.register(organization)
    for grant in settings.opportunity.authority.organization_snapshot.authorizations:organizations.authorize(grant)
    mock=SimpleNamespace(document=document,organizations=organizations,assembly=SimpleNamespace(client=SimpleNamespace(run_id=document['run_id'])))
    prior=[];proofs=[];micro_proofs=[];all_candidates={}
    schemas=OwnerInvestmentActionAssembler.SOURCE_SCHEMAS()
    for tick in (1,2):
        tick_records=sorted((r for r in records if r['scope']['tick']==tick),key=lambda r:r['scope']['candidate_project_id'])
        require(len(tick_records)==4,'Original candidate round incomplete')
        for record in tick_records:
            digest_valid(record);require(record==metadata[record['key']],'Export differs from original durable candidate record')
            observed=record['observed'];request=AgentProposalRequestV1.model_validate(record['native_request'])
            require(observed['prior_own_pipeline_screens']==prior and observed['prior_own_declines']==[],
                'Original A03 did not consume the same actual earlier screen, or another pause source appeared')
            for origin in observed['prior_own_initiations']:
                event=one(events,lambda e:e['event_id']==origin['event_id'],'Actual earlier own creation missing')
                require(event['event_type']=='project_opportunity_initiated' and event['agent_id']==org and event['tick']<tick
                    and origin['project_id']==event['project_id'] and origin['micro_task_key']==event['data']['decision_factors']['micro_task_key'],
                    'Original initial project history differs from actual own creation')
            source=prepare_opportunity_sources(mock,policy,request,record['scope'],observed['prior_own_initiations'],prior_declines=[])
            source=attach_pipeline_feedback(source,policy=settings.pipeline,history=prior)
            require(source['observed']==observed and task_digest(source['objects'])==record['source_sha256']
                and source['context'].model_dump(mode='json')==record['context'] and source['action_input']==record['action_input']
                and [g.model_dump(mode='json') for g in source['grants']]==record['source_grants'],
                'Actual original source objects, authority or private decision gate differ from declared inputs')
            for grant in source['grants']:organizations.authorize(grant)
            original=one(saved,lambda s:s['identity']==record['identity'],'Original candidate result missing');digest_valid(original)
            identity=TaskIdentity(**original['identity']);snapshot=snapshots[identity.key]
            require(snapshot['snapshot_sha256']==task_digest({k:v for k,v in snapshot.items() if k!='snapshot_sha256'}),
                'Original invocation snapshot changed')
            for reading in original['source_reading']:
                row=one(source['objects'],lambda r:r['ref']==reading['ref'],'Original reading uses undeclared source')
                require(reading['projection']==schemas.validate_projection(Reference.model_validate(row['ref']),row['value']).model_dump(mode='json'),
                    'Original typed reading differs from the actually bound source')
            protected=[r for r in source['objects'] if r['ref']['kind'] in {'FundingSource','Obligation','ResourcePool'}]
            obligation=one(protected,lambda r:r['ref']['kind']=='Obligation','Old obligation absent')['value']
            require(obligation['actual_due']['value']['value']=='5000000' and obligation['actual_paid']['value']['value']=='0',
                'A screen removed the original unpaid old obligation')
            audit=original['audit'];require(audit['input_sha256']==identity.input_sha256
                and audit['result_sha256']==original['result_sha256'] and audit['method_registry_digest']==identity.versions['method']
                and all(c['registry_digest']==identity.versions['method'] for c in audit['method_calls']), 'Original method audit changed')
            canonical=[{'ref':r['ref'],'value':schemas.validate_projection(Reference.model_validate(r['ref']),r['value']).model_dump(mode='json')} for r in source['objects']]
            payload=original['result']['payload']
            oracle=_source_oracle({'objects':canonical,'input':source['action_input'],'business_time':record['context']['business_time'],
                'organization_id':org},SimpleNamespace(kind='completed',payload=SimpleNamespace(choice=payload['choice'],model_dump=lambda **kw:payload)),audit,canonical)
            expected='reject' if tick==2 and limit==1 else 'invest'
            profile=one(source['objects'],lambda r:r['ref']['kind']=='ProjectRegistrationProfile','Original private policy missing')['value']
            require(payload['choice']==expected and profile['policy']['value']==('reject' if expected=='reject' else 'evaluate')
                and observed['pipeline_review_preference_pauses_initiation']==(expected=='reject'),
                'Original A03 did not actually use the declared confirmed-screen gate')
            if expected=='invest':require(len([c for c in audit['method_calls'] if c['method_ref']['id']=='micro.owner.declared_option_intervals'])==2,
                'Original A03 did not actually calculate full and viable comparisons')
            micro_proofs.append({'identity':identity.as_dict(),'tick':tick,'choice':payload['choice'],'micro_result_sha256':original['result_sha256'],
                'source_reading_sha256':original['source_reading_sha256'],'consumed_pipeline_history':prior,
                'source_policy':profile['policy'],'protected_initial_portfolio_sha256':task_digest(protected),'original_source_oracle':oracle})
        candidates=received_candidates(records=records,tasks=tasks,saved_results=saved,snapshots=snapshots,events=events,
            organization_id=org,tick=tick,run_id=document['run_id'],simulation_id=sim['simulation_id'],
            authorize=lambda saved,snapshot,**kw:authorize_owner_history(saved,snapshot,organizations=organizations,tick=tick))
        all_candidates[tick]=candidates
        record=one(monthly,lambda r:r['scope']['tick']==tick,'Original monthly pipeline record missing');digest_valid(record)
        require(record==metadata[record['key']] and record['candidates']==candidates and record['history']==prior,
            'Monthly review lost actual received candidate/result correspondence')
        judgment=decide_pipeline_review(settings.pipeline,organization_id=org,tick=tick,
            market_demand=record['native_request']['inputs']['macro_environment']['market_demand_index'],candidates=candidates,history=prior)
        j=judgment.model_dump(mode='json');require(j==record['judgment'] and task_digest(j)==record['judgment_sha256'] and judgment.participate,
            'Actual monthly gate differs from source micro judgments or actual macro demand')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('pipeline_record_key')==record['key'],'Original pipeline proposal missing')['output']
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('pipeline_record_key')==record['key'],'Original pipeline proposal identity missing')
        pi=TaskIdentity(**proposal_task['identity']);raw=record['native_request']
        require(pi.run_id==document['run_id'] and pi.organization_id==org
            and pi.input_sha256==task_digest({'run_id':pi.run_id,'versions':pi.versions,'request':raw})
            and pi.context_sha256==task_digest({'simulation_id':sim['simulation_id'],'request':raw})
            and all(raw['inputs']['macro_environment']==r['native_request']['inputs']['macro_environment'] for r in tick_records),
            'Monthly source is not the actual original native request/environment at candidate reception time')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('pipeline_record_key')==record['key'],'Original pipeline final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Actual monthly activity missing')
        agent=one(sim['agent_results'],lambda a:a['agent_id']==org,'Actual original Owner missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='screen_investment_pipeline','Actual monthly memory missing')
        require(proposal['accepted'] is final['decision'] is True and proposal['action_type']==final['action_type']=='screen_investment_pipeline'
            and final['data']['pipeline_judgment_sha256']==proposal['factors']['pipeline_judgment_sha256']==record['judgment_sha256']
            and proposal['factors']['micro_candidate_task_keys']==j['candidate_task_keys']
            and record['proposal_response_sha256']==final['data']['proposal_response_sha256']==task_digest(proposal)
            and event['data']['operation']=='screen_investment_pipeline' and event['description']==proposal['data']['description']==judgment.model_dump_json()
            and memory['label']==event['data']['label'] and memory.get('capability_update')==event['data'].get('capability_update'),
            'Original macro did not actually execute that same candidate review judgment')
        for candidate in candidates:
            if candidate['actually_created_project']:
                actual=candidate['actual_native_consequence'];project=one(sim['project_results'],lambda p:p['project_id']==actual['project_id'],'Native-created project missing')
                require(actual in project['event_log'] and project['owner_id']==org and project['initial_budget']==candidate['native_opportunity']['budget'],
                    'Individual candidate acceptance is not the actual original project creation')
        history={'organization_id':org,'tick':tick,'operation':'screen_investment_pipeline','event_id':event['event_id'],
            'event_sha256':task_digest(event),'candidate_source_sha256':task_digest(candidates),'candidate_task_keys':j['candidate_task_keys'],
            'judgment_sha256':record['judgment_sha256'],'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)}
        proofs.append({'tick':tick,'judgment':j,'candidates':candidates,'actual_event':event,'original_native_memory':memory,
            'confirmed_feedback':history,'original_proposal':proposal,'original_final':final})
        prior=[*prior,history]
    created=[e for e in events if e['event_type']=='project_opportunity_initiated' and e['agent_id']==org]
    require(len(created)==(1 if limit==1 else 2),'Actual original project creation differs from confirmed-screen private appetite')
    require(hashlib.sha256(dbpath.read_bytes()).hexdigest()==before,'Read-only verification changed the original task journal')
    return {'status':'original_received_candidates_monthly_native_screen_and_later_original_A03_consumption_verified',
        'proofs':proofs,'investment_proofs':micro_proofs,'actual_project_creation_events':created,'technical_tasks':len(tasks),
        'original_A03_tasks':8,'read_only_journal_sha256':before,'boundary':BOUNDARY}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name,limit=p['maximum_prior_screens_before_portfolio_review']) for name,p in config['scenarios'].items()}
    first=read(directory/'review_after_one/input/macro-request.json');second=read(directory/'review_after_two/input/macro-request.json')
    require(first==second,'Controlled native initial inputs differ')
    a=read(directory/'review_after_one/input/foundation/owner-opportunity-input.json')
    b=read(directory/'review_after_two/input/foundation/owner-opportunity-input.json');a['run_id']=b['run_id']
    require(a==b,'Independent original cash/debt, capacity or forecast inputs differ between controls')
    a=read(directory/'review_after_one/input/assembly-host.json')['settings']['pipeline']
    b=read(directory/'review_after_two/input/assembly-host.json')['settings']['pipeline']
    a['maximum_prior_screens_before_portfolio_review']=b['maximum_prior_screens_before_portfolio_review'];require(a==b,'Independent review policy differs beyond its explicit quota')
    require([r['native_opportunity'] for r in cases['review_after_one']['proofs'][0]['candidates']]
        ==[r['native_opportunity'] for r in cases['review_after_two']['proofs'][0]['candidates']], 'First actual generated candidate controls differ')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro sources changed')
    return {'batch':'3I-Owner-pipeline','status':'actual_original_pipeline_screen_and_later_original_investment_consumer_verified',
        'cases':cases,'macro':macro,'overall_goal3_complete':False,'boundary':BOUNDARY,
        'controlled_difference':'Independent initially declared maximum prior completed screens=1 versus 2. Same native initial request, seed and original private portfolio/forecast template. No saved state or result is patched.'}


PINNED_IMPLEMENTATIONS=[
    'integration/owner_monthly_pipeline.py','integration/owner_pipeline_sources.py','integration/owner_monthly_pipeline_development.py',
    'integration/verify_owner_monthly_pipeline.py','src/actions/contracts/owner_monthly_pipeline.py','src/actions/roles/owner_monthly_pipeline.py',
    'integration/owner_opportunity_native.py','integration/owner_opportunity_native_sources.py','integration/owner_opportunity_native_feedback.py',
    'integration/owner_opportunity_scope.py','integration/owner_investment_actions.py','integration/owner_investment_results.py',
    'src/actions/roles/owner_investment.py','src/methods/owner_investment.py','tests/test_owner_monthly_pipeline.py',
    'tests/fixtures/roles/owner_investment.v1.json','config/owner_monthly_pipeline_chain.json','config/gba_v1_business_wiring.json',
    'config/gba_v1_monthly_business_wiring.json','docs/业主月度项目管线接线与验收.md','docs/宏观动作接线清单.md']


def write_delivery(directory,checks):
    lines=['# GOAL 3I 业主月度项目管线运行记录','',
        '原生成器实际生成并交给本业主的候选，由原 OWN-A03 实际计算和判断；月度入口读取这批同一候选及原结果，形成内部筛选判断。'
        '原宏观实际执行筛选后，后轮原 OWN-A03 才按独立初始限额判断是否暂停新增投资、等待组合复核。','',
        '| 初始私人复核限额 | 每轮真实候选数 | 首轮原 A03 | 首轮实际筛选事件 | 后轮原 A03 | 原宏观实际新增项目数 |',
        '| --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        limit=1 if name=='review_after_one' else 2
        lines.append(f"| {limit} | 4 / 4 | 4 × invest | {case['proofs'][0]['actual_event']['event_id']} | "
            f"4 × {case['investment_proofs'][4]['choice']} | {len(case['actual_project_creation_events'])} |")
    lines.extend(['','两组原始宏观输入和种子相同。私人源资料除独立运行标识外相同，只改变预先声明的已完成筛选次数限额。'
        '候选在原生成器真实请求到达前不存在。没有重新生成候选、预填判断或修改正式状态。','',
        '首轮四个原 A03 的 invest 各自是参与立项的个人决定；原宏观按原规则只实际创建一个项目。'
        '核验逐项区分原最终决定、实际立项事件和未发生的候选后果。月度筛选本身不重复立项，也不授予正式投资权限。','',
        '原始完整私人组合的旧应付 5000000 HKD、已付 0 和原现金、限制及管理容量输入均保留。'
        '限额暂停分支由原 A03 的声明政策门直接拒绝，未声称该分支重新运行现金日历；允许投资分支确实运行原比较、现金日历和容量检查，独立源计算核验通过。','',
        '复现（输出目录必须不存在）：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_pipeline --output output/integration/owner_pipeline_my_run",'```','',
        '只读复核：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_pipeline --check-only --output '{directory.as_posix()}'",'```','',
        '输入、实际候选、原 A03 身份及结果哈希、原月度判断、执行事件和后轮消费的对应关系见 checks.json。'
        '完整源读取和方法审计保留在各组 runtime/tasks.sqlite，原事件和记忆保留在 runtime/result.json。','',
        '两组分别为 78 和 84 个技术任务，各有 8 个原 A03 任务。其余融资、专业委任及其他月度原生背景行为不据此增加微观覆盖。','',
        BOUNDARY,'','本批只补业主月度筛选。原先各业主月度接线仍使用各自验收场景，并非一个全业务统一场景。'
        '月度累计 24/32，仍有 8 项月度动作及 44 项全局来源或接口缺口；GOAL 3 与原 PLAN 均未全部完成。'])
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    _write(directory,'artifact-manifest.json',{'schema_version':'owner-monthly-pipeline-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*')
            if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PINNED_IMPLEMENTATIONS}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/owner_monthly_pipeline_chain.json');parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():run_case(directory/name,run_id=config['run_id']+'-'+name,profile=profile)
    elif (directory/'artifact-manifest.json').is_file():verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_files':checks['macro']['file_count']}))


if __name__=='__main__':main()
