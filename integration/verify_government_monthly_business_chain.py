"""Run/check original regulatory monthly judgments, native work and own consumers."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.government_monthly_business_development import build_bundle
from integration.government_monthly_native import GovernmentMonthlyPlan
from integration.government_monthly_business import result_judgment
from integration.government_approval_native_learning import feedback_sources
from integration.verify_professional_monthly_chain import run_existing_input
from integration.contractor_tender_development import _write,verify_bundle
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest
from src.actions.contracts.government_monthly_objects import OPERATIONS

NEW_OPERATIONS=OPERATIONS-{'review_policy_feedback'}


def validate_config(config):
    require(config['schema_version']=='government-monthly-business-chain.v1' and config['ticks']==4
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}},'Unsupported fixed government monthly cases')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original regulatory process failed')
    result=read(directory/'runtime/result.json');simulation=result['simulation'];host=result['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==4,'Original four-tick window incomplete')
    inbox=read(directory/'runtime/observations.json')['records']
    events=[e for project in simulation['project_results'] for e in project['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original event observer failed')
    initial=read(directory/'input/macro-request.json')
    require(all(not p['event_log'] for p in initial['initial_projects']),'Actual initial outcomes prefilled')
    plans=read(directory/'input/government-monthly-input.json')['plans']
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        saved=[json.loads(v) for table in ('government_feedback_results','government_intake_results','government_review_results','government_decision_results')
            for v, in db.execute('SELECT record FROM '+table)]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task unresolved or altered')
    worker_map={TaskIdentity(**r['identity']).key:r for r in saved}
    for r in saved:
        digest_valid(r)
        task=one(tasks,lambda t:t['identity']==r['identity'],'Original micro task missing')
        require(task['output']==r['result'] and r['result_sha256']==task_digest(r['result'])
            and r['source_reading_sha256']==task_digest(r['source_reading']),'Original micro evidence correlation lost')
    records=host['monthly']['requests'];require(len(records)==8,'Expected two agencies over four native ticks')
    proofs=[]
    for record in records:
        digest_valid(record);require(metadata[record['key']]==record and record['state']=='formed','Durable original monthly record changed')
        identity=TaskIdentity(**record['identity']);micro=worker_map[identity.key];observed=record['observed'];scope=record['scope']
        require(identity.role=='Government' and identity.action_id=='GOV-A12' and identity.organization_id==scope['organization_id']
            and record['result_sha256']==micro['result_sha256'],'Original monthly actor/action/result changed')
        plan=GovernmentMonthlyPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==scope['tick'],'Original monthly plan missing'))
        objects=feedback_sources(plan,observed=observed)
        require(task_digest(objects)==record['source_sha256'] and plan.feedback.context.model_dump(mode='json')==record['context']
            and plan.feedback.action_input==record['action_input'],'Original current sources or invocation substituted')
        require(observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Actual macro input binding changed')
        observation=one(micro['source_reading'],lambda s:s['ref']['kind']=='MonthlyRegulatoryObservation','Monthly observation was not read')['projection']
        policy=one(micro['source_reading'],lambda s:s['ref']['kind']=='MonthlyRegulatoryPolicy','Independent monthly mandate was not read')['projection']
        expected_observation=one(objects,lambda s:s['ref']==observation['ref'],'Original bound observation missing')['value']
        require(observation==expected_observation and observation['prior_own_operations']==observed['prior_monthly_feedback']
            and observation['prior_own_approval_outcomes']==observed['prior_approval_decisions'],'GOV-A12 did not read exact actual own history')
        require(observation['market_demand']['value']==str(observed['macro_environment']['market_demand_index'])
            and policy['minimum_demand_for_focus']['value']=='1' and policy['maximum_focus_operations']==policy['maximum_guidance_operations']==1,
            'Original macro parameter did not enter the fixed independently authorized judgment')
        require(any(s['projection'].get('content_hash')==task_digest(observed) for s in micro['source_reading']),'Actual inputs/history evidence not read')
        judgment=result_judgment(micro);require(judgment is not None,'Original GOV-A12 did not form a monthly judgment')
        operation=judgment.operation;history=observed['prior_monthly_feedback']
        require(len(history)==scope['tick']-1,'Own strictly earlier monthly history incomplete')
        counts={op:0 for op in OPERATIONS}
        for h in history:
            receipt=one(inbox,lambda e:e['event_id']==h['event_id'] and e['organization_id']==identity.organization_id,'Actual own receipt missing')
            previous=one(records,lambda r:r['scope']==h['native_monthly_feedback_scope'],'Micro origin of prior own operation missing')
            prior_micro=worker_map[TaskIdentity(**previous['identity']).key];prior_judgment=result_judgment(prior_micro)
            require(h['organization_id']==identity.organization_id and h['tick']<scope['tick']
                and receipt['payload']['agent_id']==identity.organization_id and receipt['payload']['tick']==h['tick']
                and receipt['payload']['data']['operation']==prior_judgment.operation==h.get('operation','review_policy_feedback')
                and h['micro_result_sha256']==prior_micro['result_sha256'] and h['proposal_response_sha256']==previous['proposal_response_sha256']
                and len(h['source_event_sha256'])==64,'Prior own actual monthly result was substituted')
            counts[prior_judgment.operation]+=1
        require(judgment.own_prior_operation_counts==counts and judgment.market_demand.model_dump(mode='json')==observation['market_demand'],
            'Actual prior work or current macro demand did not enter GOV-A12 calculation')
        for h in observed['prior_approval_decisions']:
            event=one(events,lambda e:e['event_id']==h['event_id'],'Actual original project approval outcome missing')
            require(h['organization_id']==identity.organization_id and h['tick']<scope['tick']
                and event['project_id']==h['project_id'] and event['tick']==h['tick']
                and worker_map[h['micro_task_key']]['identity']['organization_id']==identity.organization_id
                and worker_map[h['micro_task_key']]['result_sha256']==h['micro_result_sha256'],'Approval source borrows another agency/future/synthetic result')
        require(judgment.prior_own_approval_count==len(observed['prior_approval_decisions'])
            and judgment.prior_actual_rectification_count==sum(h.get('native_outcome')=='rectification_required' for h in observed['prior_approval_decisions']),
            'Original approval observations did not enter micro analysis')
        if operation=='adjust_regulatory_focus':
            require(counts[operation]<1 and (Decimal(judgment.market_demand.value)>=Decimal(judgment.threshold.value)
                or judgment.prior_actual_rectification_count>0),'Focus choice lacks demand/risk justification')
        if operation=='publish_guidelines':
            require(counts['monitor_compliance']>0 and counts[operation]<1 and judgment.guidance
                and all(p in judgment.guidance for p in policy['guidance_principles']),'Guidance was not generated from monitored own signals and independent mandate')
        if scope['tick']==1:require(operation==('adjust_regulatory_focus' if high else 'monitor_compliance'),'Controlled demand did not change first monthly judgment')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original monthly confirmation missing')['output']
        receipt=one(inbox,lambda e:e['organization_id']==identity.organization_id and e['payload']['event_type']=='agent_operation'
            and e['payload']['tick']==scope['tick'],'Original monthly execution receipt missing')
        data=receipt['payload']['data'];description=judgment.guidance or judgment.interpretation
        require(proposal['action_type']==final['action_type']==data['operation']==operation
            and proposal['accepted'] is final['decision'] is data['decision_accepted'] is True
            and record['proposal_response_sha256']==final['data']['proposal_response_sha256']==task_digest(proposal)
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and proposal['data']['description']==data['description']==description,'Actual native scheduler changed original micro judgment/artifact')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Native agency missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==scope['tick'] and m.get('operation')==operation,'Actual original agency memory missing')
        require(memory['label']==data['label'] and memory['capability_update']==data['capability_update']
            and memory['decision_factors']==data['decision_factors'],'Native retained operation memory changed actual execution')
        proofs.append({'identity':identity.as_dict(),'scope':scope,'observation':observation,'independent_policy':policy,
            'judgment':judgment.model_dump(mode='json'),'micro_result_sha256':micro['result_sha256'],'source_reading_sha256':micro['source_reading_sha256'],
            'original_proposal':proposal,'original_final':final,'actual_event_id':receipt['event_id'],
            'actual_native_projection':receipt['payload'],'actual_projection_sha256':task_digest(receipt['payload']),
            'actual_retained_native_memory':memory,'consumed_own_monthly_history':history,'consumed_own_approval_outcomes':observed['prior_approval_decisions']})
    consumed_ids={h['event_id'] for p in proofs for h in p['consumed_own_monthly_history']}
    require(NEW_OPERATIONS<={p['judgment']['operation'] for p in proofs},'An original monthly business was never executed')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only verification modified original journal')
    return {'status':'original_monthly_business_and_later_own_consumption_verified','technical_tasks':len(tasks),'original_monthly_GOV_A12_decisions':len(proofs),
        'actual_operations':dict(Counter(p['judgment']['operation'] for p in proofs)),'proofs':proofs,
        'window_tail_results_without_later_tick':[{'event_id':p['actual_event_id'],'scope':p['scope'],'operation':p['judgment']['operation']}
            for p in proofs if p['actual_event_id'] not in consumed_ids],
        'journal_sha256':before,'native_project_diagnostics':[e for e in events if e['event_type']=='invalid_action'],
        'evidence_boundary':'Own inbox projection and original agency memory preserve actual native work. Earlier raw global event hashes were authenticated against live original events by prior_monthly_feedback; archived projection hashes are distinct and are not presented as full raw event hashes.',
        'formal_publication_permit_physical_inspection_or_compliance_clearance_proven':False}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    for operation in NEW_OPERATIONS:
        require(any(p['judgment']['operation']==operation and any(h['event_id']==p['actual_event_id']
            for later in case['proofs'] if later['scope']['organization_id']==p['scope']['organization_id']
            for h in later['consumed_own_monthly_history']) for case in cases.values() for p in case['proofs']),
            'An original monthly business has no actual later own consumer in the delivered cases')
    high=read(directory/'high/input/macro-request.json');low=read(directory/'low/input/macro-request.json')
    high['macro_environment']['market_demand_index']=low['macro_environment']['market_demand_index']
    require(high==low,'Original macro inputs differ beyond controlled demand')
    private=[]
    for name in config['scenarios']:
        doc=read(directory/name/'input/government-monthly-input.json');doc.pop('run_id')
        for plan in doc['plans']:plan['feedback']['context'].pop('run_id')
        private.append(doc)
    require(private[0]==private[1],'Controlled cases changed private monthly policy or initial facts')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    contacts=[]
    for operation in sorted(NEW_OPERATIONS):
        contacts.append({'role':'Government','operation':operation,'original_micro_action':'GOV-A12',
            'macro_input':'Actual current monthly macro environment; authenticated strictly earlier own original monthly and approval outcomes',
            'micro_handler':'integration.government_monthly_native:GovernmentMonthlyApplication',
            'micro_processing':'Original GOV-A12 record_feedback branch optionally computes an authorized monthly analysis; interpretation carries the validated judgment and actual prepared guidance text',
            'return_to_macro':'Saved original GOV-A12 judgment -> original proposal/final -> original monthly scheduler; actual description retains the analysis/guidance, while agency memory retains operation/label and native scalar factors',
            'feedback_consumer':'Later own GOV-A12 counts exact earlier actual monthly actions; original regulatory review also retains its existing own monthly feedback source',
            'actual_business_events':[{'scenario':name,'event_id':p['actual_event_id'],'projection_sha256':p['actual_projection_sha256']} for name,case in cases.items()
                for p in case['proofs'] if p['judgment']['operation']==operation],
            'later_consumers':[{'scenario':name,'identity':p['identity'],'history':p['consumed_own_monthly_history']} for name,case in cases.items()
                for p in case['proofs'] if any(h.get('operation','review_policy_feedback')==operation for h in p['consumed_own_monthly_history'])]})
    return {'batch':'3D-monthly','status':'three_remaining_government_monthly_businesses_verified_formal_effects_still_blocked',
        'cases':cases,'contacts':contacts,'macro':macro,'overall_goal3_complete':False,
        'boundary':'Original monthly focus analysis, visible signal monitoring and guidance preparation only. Independent mandate is a declared synthetic scenario assumption. No formal guideline publication, effective regulation, permit, physical inspection, safety/procurement compliance finding or financial clearance is inferred. Existing detailed regulatory blocks remain.'}


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':'3D-monthly','contacts':checks['contacts'],'overall_goal3_complete':False,'boundary':checks['boundary']})
    (directory/'RUN_RECORD.md').write_text('\n'.join(['# GOAL 3D 监管月度业务补接运行记录','',
        '复用原监管受理、审查、意见、反馈和月度传输；补接调整重点、监测信号、编制指引三项原月度业务。正式发文、许可和实体检查仍阻塞。','',
        '| 原期初需求 | 两机构首轮 | 后轮 |','| --- | --- | --- |',
        '| 1.2 | GOV-A12 按实际需求选择 adjust_regulatory_focus | 依本机构较早真实执行次数，先 monitor_compliance，再 publish_guidelines；后轮消费同一结果 |',
        '| 0.6 | GOV-A12 选择 monitor_compliance | 有监测结果后生成指引；后轮读取真实整改/完成意见及已开展次数，按同一私有规则继续判断 |','',
        '两组原宏观输入仅期初 market_demand_index 不同，种子 42；私有月度输入除运行标识外逐字段一致。实际需求指数先由原宏观更新，再由原 A12 计算，适配器不预填选择。',
        '原 A12 的既有 record_feedback interpretation 承载类型化月度判断；原动作、授权、任务与结果存储保留。指引正文保存在原微观结果、提案和实际事件投影，最终确认绑定同一结果。原机构记忆保留操作、标签及宏观标量，不声称存有正文。',
        f"两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个技术任务全部形成结果，16 项原月度 GOV-A12 判断；新增三类动作均有后轮本机构原动作消费证据。窗口末轮结果另行归档，不声称其后轮已运行。",
        'checks.json 保存实际输入、独立策略、原判断、原提案/最终确认、实际收件投影与机构记忆、后轮消费关联。原始全局事件摘要由运行中原历史查询核验；归档投影摘要与完整原事件摘要分别标识，不混称。',
        '复用既有四时点监管场景的两份期初在建项目和独立既有合同，不作为本轮从零投标或签约。GOV-A04/A07 的实际整改与汇总完成结果仍不等于许可、实体检查或明细结算。','',
        '新目录启动：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_government_monthly_business_chain `",
        '  --config config/government_monthly_business_chain.json `','  --output output/integration/goal3d_monthly_my_run','```','',
        '只读核对：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_government_monthly_business_chain --check-only --output '{directory.as_posix()}'",'```','',
        f"宏观 {checks['macro']['file_count']} 文件基线与全部宏观 Python 未改。月度累计 11/32，21 项未接通；详细业务阻塞保留，GOAL 3 与原 PLAN 未完成。",'']),encoding='utf-8')
    names=['integration/government_monthly_business.py','integration/government_monthly_business_development.py','integration/verify_government_monthly_business_chain.py',
        'integration/government_monthly_native.py','integration/government_monthly_native_sources.py','integration/government_approval_native_learning.py','integration/observations.py',
        'src/actions/contracts/government_monthly_objects.py','src/actions/contracts/government_feedback_objects.py','src/actions/roles/government_monthly.py','src/actions/roles/government_feedback.py',
        'config/government_monthly_business_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/监管月度业务接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'government-monthly-business-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/government_monthly_business_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.government_intake_native:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
