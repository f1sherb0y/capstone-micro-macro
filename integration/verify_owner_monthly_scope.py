"""Run or read-only verify original A16 private scope research and actual reuse."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.owner_monthly_scope import MonthlyOwnerScopePlan,OwnerMonthlyScopeApplication,bind_sources,current_comparison_brief,BOUNDARY
from integration.owner_monthly_scope_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.actions.contracts.common import Reference
from src.actions.roles.owner_proposal import brief_content
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='owner-monthly-private-scope-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.8}},'Unsupported fixed original Owner scope comparison')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original scope process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    records=host['requests'];events=host['original_global_events'];plans=read(directory/'input/owner-monthly-scope-input.json')['plans']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==2,'Two actual own Owner months required')
    require(host['boundary']==BOUNDARY and not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed or boundary changed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM owner_proposal_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(len(tasks)==6 and len(workers)==2 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task count/state/digest changed')
    project,=simulation['project_results'];initial,=read(directory/'input/macro-request.json')['initial_projects']
    require(project['project_id']==initial['project_id'] and project['owner_id']==initial['owner_id'] and project['current_stage']=='design'
        and project['initial_budget']==1000 and not project['contracts'] and not project['engagements'],'Private research unexpectedly made a formal project commitment')
    schemas=OwnerMonthlyScopeApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS();proofs=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Own request journal changed')
        identity=TaskIdentity(**record['identity']);tick=record['scope']['tick'];observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original A16 result missing');digest_valid(micro)
        require(identity.role=='Owner' and identity.action_id=='OWN-A16' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result'])
            and micro['source_reading_sha256']==task_digest(micro['source_reading']),'Original micro result/readings changed')
        require(one(tasks,lambda t:t['identity']==identity.as_dict(),'Original A16 task missing')['output']==micro['result'],'Durable A16 task differs from worker result')
        plan=MonthlyOwnerScopePlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==tick,'Own plan missing'))
        snapshot=snapshots[identity.key]
        require(record['context']==plan.context.model_dump(mode='json')==snapshot['context'] and record['action_input']==plan.action_input==snapshot['action_input']
            and identity.input_sha256==task_digest(plan.action_input)==micro['audit']['input_sha256'],'Originally authorized invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request']) and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and observed['actual_own_project']=={k:project[k] for k in ('project_id','owner_id','region','project_type')}
            and project['owner_id']==identity.organization_id and plan.project_id==project['project_id'],'Actual own project/global request binding changed')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Original source binding changed')
        for reading in micro['source_reading']:
            supplied=one(objects,lambda r:r['ref']==reading['ref'],'Worker read an undeclared source')['value']
            typed=schemas.validate_projection(Reference.model_validate(reading['ref']),supplied).model_dump(mode='json')
            require(reading['projection']==typed,'Worker did not read the exact typed bound source')
        def source(kind):return one(objects,lambda r:r['ref']['kind']==kind,'Private source missing: '+kind)['value']
        signal=source('DemandObservation');objective=source('OwnerObjective');case=source('OwnerCase');candidate=source('ProposalCandidate');space=source('ProposalSpace')
        issue=source('Issue');funding=source('FundingPosition');rule=objective['signal_rules']['value'][0]
        current=Decimal(str(observed['macro_environment']['market_demand_index']))
        require(signal['measure']['value']['value']==str(current) and signal['measure']['value']['unit']=='index'
            and rule['signal_code']==signal['signal_code']=='native_global_market_demand_index' and rule['comparison']=='at_least'
            and rule['threshold']['value']=='1.05' and rule['threshold']['unit']=='index' and (current>=Decimal('1.05')) is high,
            'Actual global macro signal did not enter the original independent research gate')
        require(issue['status']=='unresolved' and issue['check_code']=='rights_path' and candidate['brief']['rights_refs']==[]
            and candidate['brief']['scale']['lower']['value']['value']=='100' and candidate['brief']['scale']['upper']['value']['value']=='200',
            'Private scale or unresolved rights were silently supplied by macro')
        cash=Decimal(funding['actual_cash']['value']['value'])-Decimal(funding['committed_cash']['value']['value'])-Decimal(funding['restricted_cash']['value']['value'])
        require(cash==50 and candidate['review_cost']['value']['value']=='10','Independent private research cash changed')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1,'Earlier own actual history missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Prior actual proof missing')
            event=previous['actual_event']
            require(h['source_event_sha256']==task_digest(event) and h['micro_identity']==previous['identity'] and h['micro_result_sha256']==previous['micro_result_sha256']
                and h['operation']==event['data']['operation'] and h['tick']==event['tick']<tick and event['agent_id']==identity.organization_id
                and h['participated'] is previous['participated'] and h['original_payload']==previous['original_result']['payload']
                and h['case_ref']==previous['case_ref'] and h['original_issues']==previous['original_issues'],'Later input differs from the earlier actual original private output')
        payload=micro['result']['payload'];participates=high and tick==1;expected='propose' if participates else 'no_proposal'
        require(micro['result']['kind']=='completed' and payload['choice']==expected and len(payload.get('briefs',[]))==int(participates),'Unexpected original A16 choice')
        calls=micro['audit']['method_calls'];expected_methods=[] if not high else ['micro.owner.declared_scale_bounds']+(['micro.owner.declared_proposal_priority'] if tick==1 else [])
        require([c['method_ref']['id'] for c in calls]==expected_methods and all(c['result']['kind']=='ok' and c['result']['method_ref']==c['method_ref']
            and c['registry_digest']==identity.versions['method'] for c in calls),'Original scale/ranking execution changed')
        comparison=None
        if high and tick==2:
            prior=source('OwnerBrief');h,=history
            require(h['operation']=='prepare_project_scope' and h['participated'] is True and space['mode']=='revise'
                and case['prior_brief_refs']==[prior['ref']] and candidate['prior_brief_ref']==prior['ref'],'Next original A16 lacks its actually prepared same-case brief')
            old=h['original_payload']['briefs'][0];translated=current_comparison_brief(old,original_issues=h['original_issues'],current_objects=objects)
            require(prior['brief']==translated and translated==candidate['brief'] and old['unresolved_refs']!=translated['unresolved_refs'],
                'Actual earlier brief was not used for the unchanged-content comparison')
            # Typed original brief_content is the original A16 comparison, not a new decision rule.
            prior_read=one(micro['source_reading'],lambda r:r['ref']==prior['ref'],'Original A16 did not read its prior private brief')
            from src.actions.contracts.owner_proposal_objects import ProposalBriefDraft
            require(brief_content(ProposalBriefDraft.model_validate(prior_read['projection']['brief']))==brief_content(ProposalBriefDraft.model_validate(candidate['brief'])),
                'Original comparison would detect changed content')
            comparison={'actual_prior_payload':h['original_payload'],'current_comparison_brief':translated,'substantive_content_unchanged':True,
                'only_reference_translation':'same unresolved Issue and same physical OwnerCase; version fields only; exact original remains in history',
                'effect':'original A16 skips unchanged revision and ranking; no duplicate native preparation'}
        else:
            require(space['mode']=='propose' and not case['prior_brief_refs'] and candidate['prior_brief_ref'] is None and not any(r['ref']['kind']=='OwnerBrief' for r in objects),
                'A prior private brief was prefilled without a positive actual preparation')
        if participates:
            require(payload['briefs']==[candidate['brief']] and calls[-1]['input']['available_cash']['value']=='50'
                and calls[-1]['input']['available_effort']['value']=='1','Original independently funded draft/ranking differs')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Monthly proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),'Actual request differs from durable original transport')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual monthly event missing')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participates
            and proposal['action_type']==final['action_type']=='prepare_project_scope' and event['data']['operation']==('prepare_project_scope' if participates else 'maintain_operations')
            and proposal['factors']['micro_participation'] is final['data']['micro_participation'] is participates
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description'] and event['data']['decision_source']=='llm_agent','Original macro did not actually process the same A16 choice')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Native owner missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Actual own memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native memory differs from actual event')
        feedback=one(read(directory/'runtime/observations.json')['records'],lambda o:o['event_id']==event['event_id'] and o['organization_id']==identity.organization_id,'Committed own feedback missing')
        require(feedback['payload']['committed'] is True and feedback['payload']['data']['operation']==event['data']['operation']
            and feedback['payload']['data']['description']==event['description'],'Actual committed feedback differs')
        proofs.append({'identity':identity.as_dict(),'scope':record['scope'],'actual_macro_signal':signal,'independent_objective':objective,'participated':participates,
            'case_ref':plan.action_input['case_ref'],'original_issues':[r for r in micro['source_reading'] if r['ref']['kind']=='Issue'],
            'private_available_cash_HKD':str(cash),'original_result':micro['result'],'micro_result_sha256':micro['result_sha256'],'original_method_calls':calls,
            'original_proposal':proposal,'original_proposal_task_identity':transport,'original_final':final,'actual_event':event,
            'actual_event_sha256':task_digest(event),'actual_native_memory':memory,'original_committed_feedback':feedback,
            'consumed_own_history':history,'actual_prior_comparison':comparison})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'actual_preparations':int(high),'later_actual_brief_consumers':int(high),'database_sha256':before}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,value in inputs.items():require(value['macro_environment'].pop('market_demand_index')==config['scenarios'][name]['market_demand_index'],'Controlled original setting changed')
    require(normalized(inputs['high'],'high')==normalized(inputs['low'],'low'),'Macro inputs differ beyond original configured demand')
    plans={name:read(directory/name/'input/owner-monthly-scope-input.json') for name in cases}
    require(normalized(plans['high'],'high')==normalized(plans['low'],'low'),'Private case/budget/policy differ between controlled inputs')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'original initial market_demand_index 1.2 versus 0.8 only',
        'boundary':BOUNDARY,'scope':'One bounded Owner.prepare_project_scope private-research action; no formal scope publication, rights or cash execution; other gaps stay blocked'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_scope --config config/owner_monthly_scope_chain.json --output $OutputDirectory\n",encoding='utf-8')
    lines=['# GOAL 3I 业主私有范围准备实跑记录','','原 OWN-A16 → 原月度提案/最终决定 → 原 scheduler 实际执行 → 实际自身结果 → 后轮原 A16。',
        '两组仅通过原场景入口设置初始全局需求指数 1.2 / 0.8；私有案件、预算、阈值和候选相同。下表是原模型更新后真正进入微观的数值。','',
        '| 场景 | 月 | 实际全局指数 | 原 A16 | 实际宏观操作 | 事件 | 读入此前实际准备 | 原方法 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            consumed=[h['event_id'] for h in p['consumed_own_history'] if h['participated']]
            lines.append(f"| {name} | {p['scope']['tick']} | {p['actual_macro_signal']['measure']['value']['value']} | {p['original_result']['payload']['choice']} | {p['actual_event']['data']['operation']} | {p['actual_event']['event_id']} | {', '.join(consumed) or '无'} | {', '.join(c['method_ref']['id'] for c in p['original_method_calls']) or '无'} |")
    lines+=['','共 12 个技术任务全部形成结果；仅 1 次实际范围准备、1 次后轮原 A16 草案消费，另 3 次为维持经营。',
        '宏观指数进入原 A16 的 signal_rules：实际值至少 1.05 index 才进入候选研究。高组先校验 100..200 m² 在 1..1000 m² 边界内，再用独立私有现金 100−30−20=50 HKD、管理余量 1 analyst 对审阅成本 10 HKD / 0.5 analyst 排序。低组未过需求门槛，不调用规模及排序方法。',
        '高组后轮只有在前轮原 prepare_project_scope 已实际执行后，才读入该次原 A16 的真实草案。原输出和旧 Issue 引用完整保留；当前比较视图仅在同一案件、同一未决问题全部实质字段相同时转换版本引用。原 A16 比较内容相同后跳过重复修订及排序，返回 no_proposal；宏观实际维持经营。',
        '该轮是私有范围研究，不发布正式项目范围、不取得权利、不实际花费现金、不承诺工程；rights_path 仍未解决。原宏观预算 1000 不映射为私有现金或规模。全局指数不冒充香港地区需求调查。','',
        '新目录复现：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_scope `",'  --config config/owner_monthly_scope_chain.json `','  --output output/integration/goal3i_owner_scope_my_run','```','',
        '只读核验本次归档：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_scope --check-only --output '{directory.as_posix()}'",'```','',
        '完整请求、独立输入、源读取、原计算审计、决定、实际事件、反馈与后轮对应关系见 checks.json 和 high/low/runtime。',
        ('affected-tests.xml 保存 15 项受影响检查。' if (directory/'affected-tests.xml').is_file() else '受影响代码检查及边界见 docs/业主月度范围准备接线与验收.md 的原验收记录。'),
        '本批只增加 Owner.prepare_project_scope 的有界私有研究接线；月度累计 20/32，12 项月度动作及 48 项全局阻塞仍保留。GOAL 3 和原 PLAN 均未宣称全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/owner_monthly_scope.py','integration/owner_monthly_scope_development.py','integration/verify_owner_monthly_scope.py',
        'tests/test_owner_monthly_scope.py','src/actions/roles/owner_proposal.py','tests/fixtures/roles/owner_proposal.v1.json',
        'config/owner_monthly_scope_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
        'docs/业主月度范围准备接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'owner-monthly-scope-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/owner_monthly_scope_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile);run_existing_input(directory/name,assembly_hook='integration.owner_monthly_scope:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
