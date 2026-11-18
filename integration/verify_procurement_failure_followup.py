"""Fixed original no-accepted-supplier run and read-only evidence verification."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.contractor_tender_development import _write,verify_bundle
from integration.procurement_failure_development import build_bundle
from integration.procurement_failure_followup import BOUNDARY,ProcurementFailureFollowup,project_failure_event
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import verify_history
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='procurement-failure-chain.v1' and config['scenarios']=={
        'all_refused':{'decline_all_quotes':True},'accepted_control':{'decline_all_quotes':False}},'Unsupported fixed refusal/accepted comparison')


def verify_scenario(directory,*,refused):
    from integration.bootstrap import enable_gba_imports
    enable_gba_imports()
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original native supply run failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==2,'Native scenario did not complete')
    initial=read(directory/'input/macro-request.json');roles={a['agent_id']:a['role'] for a in initial['agents']}
    require(all(not p['selected_supplier_ids'] and not p['event_log'] for p in initial['initial_projects']),'Native outcome prefilled')
    projects={p['project_id']:p for p in simulation['project_results']};events=[e for p in projects.values() for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Actual feedback consumer failed')
    failures=[e for e in events if e['event_type']=='supplier_selection_failed'];selections=[e for e in events if e['event_type']=='supplier_selected']
    records=host['failure_followup']['requests'];require(host['failure_followup']['boundary']==BOUNDARY,'Failure boundary changed')
    require((len(failures),len(selections),len(records))==((3,0,3) if refused else (0,2,0)),'Failure/control event correspondence changed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_planning_results')]
        supplier_workers=[json.loads(v) for table in ['supplier_screening_results','supplier_product_results','supplier_quote_results','supplier_order_results']
            for v, in db.execute('SELECT record FROM '+table)]
    require(len(tasks)==(55 if refused else 44) and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Unexpected or unresolved original task')
    require(len(workers)==len(records) and {k:v for k,v in metadata.items() if k.startswith(ProcurementFailureFollowup.PREFIX)}=={r['key']:r for r in records},
        'Private follow-up export changed durable journal')
    task_map={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in supplier_workers}
    for worker in supplier_workers+workers:
        digest_valid(worker);require(task_digest(worker['source_reading'])==worker['source_reading_sha256']
            and worker['result_sha256']==task_digest(worker['result']) and task_map[TaskIdentity(**worker['identity']).key]['output']==worker['result'],
            'Original worker result/readings/task changed')
    for worker in supplier_workers:
        if worker['identity']['action_id']=='SUPPLIER-A03':
            policy=one(worker['source_reading'],lambda r:r['ref']['kind']=='SupplyPricingProfile','Original pricing policy missing')['projection']['policy']
            require(policy==('decline_new_quotes' if refused else 'evaluate'),'Actual original processor did not read the controlled independent policy')
    inbox=read(directory/'runtime/observations.json')['records'];proofs=[]
    plans=read(directory/'input/failure-followup-input.json')['plans']
    for event in failures:
        org=event['agent_id'];scope={'project_id':event['project_id'],'contractor_id':org,'tick':event['tick']}
        record=one(records,lambda r:r['observed']['event_id']==event['event_id'],'Failure lacks its original A05 consumer');digest_valid(record)
        require(record['state']=='formed' and record['proof']['event']==event and record['proof']['event_sha256']==task_digest(event)
            and record['proof']['scope']==scope,'Failure proof replaced actual macro state')
        received=one(inbox,lambda r:r['event_id']==event['event_id'],'Failure must have exactly one own recipient')
        expected=project_failure_event(AgentObservationV1.model_validate(event),roles)
        require(set(expected)=={org} and received['organization_id']==org and received['payload']==expected[org]
            and record['proof']['received']==received==record['observed']['received'],'Failure feedback changed its actual private recipient')
        p=record['proof']['original_native_proposal'];f=record['proof']['original_native_final']
        for t in [p,f]:require(task_map[TaskIdentity(**t['identity']).key]==t,'Failure replaced original native transport task')
        require(p['output']['accepted'] is False and f['output']['decision'] is False
            and p['output']['factors']['decision_source']=='native_macro' and not p['output']['data'].get('selected_supplier_id')
            and f['output']['data']['proposal_response_sha256']==task_digest(p['output'])==event['data']['contractor_decision']['proposal_response_sha256']
            and event['data']['delay_days_added']==15,'Original no-accepted failure became a successful selection')
        causes=[e for e in events if e['event_type']=='supplier_order_decision' and e['project_id']==event['project_id'] and e['tick']==event['tick']]
        require(len(causes)==2 and all(e['data']['accepted'] is False and e['data']['micro_action_id']=='SUPPLIER-A03' for e in causes),
            'Failed selection not caused by actual original supplier quote refusals')
        for cause in causes:
            r=saved[cause['data']['micro_task_key']]
            require(r['identity']['organization_id']==cause['agent_id'] and r['result']['payload']['choice']=='decline_quote'
                and r['result_sha256']==cause['data']['micro_result_sha256'],'Original supplier refusal was fabricated')
        identity=TaskIdentity(**record['identity']);worker=one(workers,lambda r:r['identity']==identity.as_dict(),'Original A05 result missing')
        require(identity.action_id=='CONTRACTOR-A05' and identity.organization_id==org and identity.run_id==received['run_id']
            and worker['result']['kind']=='completed' and worker['result']['payload']['choice']=='request_quote'
            and worker['result_sha256']==record['result_sha256'],'Failure did not form an own original private inquiry proposal')
        plan=one(plans,lambda p:(p['organization_id'],p['project_id'],p['tick'])==(org,event['project_id'],event['tick']),'Original follow-up plan missing')
        require(record['context']==plan['context'] and record['action_input']==plan['action_input']
            and plan['trigger']=='own_committed_supplier_selection_failed','Failure changed declared current private authority')
        snapshot=snapshots[identity.key];require(snapshot['context']==record['context'] and task_digest(snapshot['action_input'])==identity.input_sha256,
            'Original worker changed exact invocation')
        sources={task_digest(r['ref']):r['projection'] for r in worker['source_reading']}
        require(sources[task_digest(plan['native_evidence_ref'])]['content_hash']==task_digest(record['observed'])
            and record['observed']['event_sha256']==task_digest(event) and record['observed']['scope']==scope,'Original A05 did not read same actual failure')
        objects=deepcopy(plan['objects'])
        from integration.bank_financing_private import evidence_binding
        evidence_binding(objects,plan['native_evidence_ref'],record['observed'])
        for r in objects:
            if r['ref']['kind']=='Evidence' and r['value'].get('content_hash') is None:
                evidence_binding(objects,r['ref'],{'source':'not_an_accepted_quote','failure_event_id':event['event_id'],'scope':scope})
        require(task_digest(objects)==record['source_sha256'],'Private source binding changed')
        profile=one(objects,lambda r:r['ref']['kind']=='WorkPlanningProfile','Original private profile missing')['value']
        recipient=sources[task_digest(profile['supplier_refs'][0])]
        require(profile['choice']=='request_quote' and worker['result']['payload']['supplier_ids']==[recipient['organization_id']]
            and worker['result']['payload']['requirement_refs']==profile['requirement_refs']==recipient['requirement_refs']
            and recipient['accepts_inquiries']=={'state':'known','value':True} and plan['action_input']['supplier_offer_refs']==[],
            'Original A05 did not use authorized current inquiry scope/recipient')
        proofs.append({'event':event,'received':received,'original_native_proposal':p,'original_native_final':f,
            'actual_supplier_refusal_events':causes,'consumer_identity':identity.as_dict(),'consumer_result':worker['result'],
            'consumer_result_sha256':worker['result_sha256'],'consumer_reading_sha256':worker['source_reading_sha256'],
            'actual_failure_evidence':sources[task_digest(plan['native_evidence_ref'])],'independent_inquiry_recipient':recipient})
    if refused:
        require(all(not p['selected_supplier_ids'] and not any(e['role']=='Supplier' for e in p['engagements'])
            and p['performance']['delay_days']==15*sum(e['project_id']==p['project_id'] for e in failures) for p in projects.values()),
            'Private inquiry proposal changed native appointment or original delay')
    else:require(all(p['selected_supplier_ids'] for p in projects.values()),'Accepted control failed native selection')
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed tasks')
    return {'status':'passed','technical_tasks':len(tasks),'failure_events':len(failures),'private_A05_inquiries':len(workers),
        'successful_native_selections':len(selections),'database_sha256':before,'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    cases={name:verify_scenario(directory/name,refused=profile['decline_all_quotes']) for name,profile in config['scenarios'].items()}
    values={name:json.dumps(read(directory/name/'input/macro-request.json'),sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN') for name in cases}
    require(len(set(values.values()))==1,'Native initial state differed between refusal and accepted control')
    def normalize(value,name):return json.dumps(value,sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN')
    dossiers={}
    for name in cases:
        settings=read(directory/name/'input/assembly-host.json')['settings']['supply']
        doc=read(Path(settings['file_path']))
        for plan in doc['plans']:
            profile=one(plan['quote']['objects'],lambda r:r['ref']['kind']=='SupplyPricingProfile','Declared quote policy missing')['value']
            require(profile.pop('policy')==('decline_new_quotes' if name=='all_refused' else 'evaluate'),'Initial policy difference changed')
        dossiers[name]=normalize(doc,name)
    require(len(set(dossiers.values()))==1,'Independent Supplier sources differed beyond the authorized quote policy')
    followups={}
    from integration.contractor_planning_actions import ContractorPlanningActionAssembler
    from src.actions.contracts.common import Reference
    from src.actions.roles.qs_change import content_digest
    for name in cases:
        doc=read(directory/name/'input/failure-followup-input.json')
        for plan in doc['plans']:
            for row in plan['objects']:
                if row['ref']['kind']=='ProcurementAuthority':
                    value=row['value'];terms=one(plan['objects'],lambda r:r['ref']==value['terms_ref'],'Original run-scoped terms missing')
                    typed=ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(terms['ref']),terms['value'])
                    require(value['terms_sha256']==content_digest(typed),'Original independent terms digest changed')
                    # Clock/run identities differ; validate each original digest before normalizing that derived checksum.
                    value['terms_sha256']='verified_run_scoped_terms_digest'
        followups[name]=normalize(doc,name)
    require(len(set(followups.values()))==1,'Private inquiry sources differed between refusal and accepted control')
    return {'status':'passed','macro':macro,'cases':cases,'boundary':BOUNDARY,'counts_as_new_monthly_coverage':False,
        'controlled_difference':'Original quote policy decline_new_quotes enabled versus unchanged default; no native state or result prefilled'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_procurement_failure_followup --config config/procurement_failure_followup.json --output $OutputDirectory\n",encoding='utf8')
    lines=['# GOAL 3E 无供应商接受时的失败反馈实跑记录','','全拒绝仅通过初始独立报价政策 decline_new_quotes 构造；接受对照使用原默认政策，两组原宏观初始状态相同。','',
        '| 场景 | 技术任务 | 原生失败 | 原 A05 私有重新询价 | 原生选供成功 |','| --- | --- | --- | --- | --- |']
    for name,c in checks['cases'].items():lines.append(f"| {name} | {c['technical_tasks']} | {c['failure_events']} | {c['private_A05_inquiries']} | {c['successful_native_selections']} |")
    lines+=['','全拒绝：原 A03 六次实际拒绝报价，原宏观三次选供失败，每次增加 15 天延误；原 A05 随后消费同一已提交失败，实际检查询价权限、需求和接收方后形成 request_quote 私有提议。没有询价发送回执或新供应商接受。','',
        '| 原生失败事件 | 项目 | 轮次 | 原 A05 结果摘要 |','| --- | --- | --- | --- |']
    for p in checks['cases']['all_refused']['proofs']:lines.append(f"| {p['event']['event_id']} | {p['event']['project_id']} | {p['event']['tick']} | {p['consumer_result_sha256']} |")
    lines+=['','接受对照：两次原生选供成功，未启动失败跟进。宏观源码冻结；完整源摘要、接收关系、原微观结果和方法边界见 checks.json。','',
        '全新目录运行：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_procurement_failure_followup `",'  --config config/procurement_failure_followup.json `','  --output output/integration/goal3e_noaccepted_my_run','```','',
        '只读核验：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_procurement_failure_followup --check-only --output '{directory.as_posix()}'",'```','',
        '本批补齐实际无接受供应商失败后的微观处理，不将原生负向选供称为 A05 微观选供决定。部分接受、修订条款、正式重新询价发送、详细订单及后续履约保持阻塞。月度仍为 19/32；GOAL 3 和原 PLAN 均未完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    names=['integration/procurement_failure_followup.py','integration/procurement_failure_development.py','integration/verify_procurement_failure_followup.py',
        'integration/supplier_order_native_development.py','integration/observations.py','tests/test_procurement_failure_followup.py','config/procurement_failure_followup.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/无接受供应商失败反馈接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'procurement-failure-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--config',type=Path,default=ROOT/'config/procurement_failure_followup.json');parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if args.check_only:verify_history(directory)
    else:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.procurement_failure_followup:configure_assembly')
    checks=collect_checks(directory)
    if not args.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
