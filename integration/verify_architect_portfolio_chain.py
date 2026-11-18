"""Run/check same-run native selections -> private A12 portfolio -> native monthly -> next A12."""
from copy import deepcopy
from decimal import Decimal
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from integration.architect_portfolio_development import build_bundle
from integration.architect_portfolio_native import BOUNDARY,PortfolioPlan,result_judgment
from integration.bank_financing_private import evidence_binding
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(set(config)=={'schema_version','run_id','scenarios','source_note'}
        and config['schema_version']=='architect-portfolio-chain.v1'
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}}
        and config['run_id'] and config['source_note'],'Unsupported fixed portfolio scenario')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original portfolio process did not complete')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    monthly=host['monthly'];records=monthly['requests'];events=monthly['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==4,'Expected both Architects over two ticks')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original reception reported an observer error')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        tables=[n for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if n.endswith('_results')]
        require(all(re.fullmatch('[a-z_]+',n) for n in tables),'Invalid original journal table name')
        workers=[json.loads(v) for n in tables for v, in db.execute('SELECT record FROM '+n)]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Unresolved or changed original task')
    taskmap={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in workers}
    for micro in workers:
        digest_valid(micro);identity=TaskIdentity(**micro['identity']);snapshot=snapshots[identity.key];digest_valid(snapshot,'snapshot_sha256')
        require(micro['result_sha256']==task_digest(micro['result']) and micro['source_reading_sha256']==task_digest(micro['source_reading'])
            and micro['result']['kind']=='completed' and taskmap[identity.key]['output']==micro['result']
            and identity.context_sha256==task_digest(snapshot['context']) and identity.input_sha256==task_digest(snapshot['action_input']),
            'Original result, reading, snapshot or task identity changed')
    plans=read(directory/'input/portfolio-input.json')['plans']
    receipts=host['professional']['appointment']['receipts']
    require(len(receipts)==5,'Original selected professional receipts missing')
    def source(micro,kind):return one(micro['source_reading'],lambda r:r['ref']['kind']==kind,'Missing original '+kind)['projection']
    def event_for(event_id):return one(events,lambda e:e['event_id']==event_id,'Missing original event')
    def bound(micro,observed):
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in micro['source_reading']),'Original result did not read its observed provenance')
    # Check real independent professional/owner acceptance as well as original A03 reception.
    for receipt in receipts:
        digest_valid(receipt);event=event_for(receipt['event_id']);observed=receipt['observed']
        key=TaskIdentity(**receipt['identity']).key;micro=saved[key];field=receipt['role'].lower()+'_id'
        require(metadata['professional_appointment_received:'+task_digest({'event_id':event['event_id'],'organization_id':receipt['organization_id']})]==receipt,
            'Original appointment receipt not durable')
        require(receipt['state']=='formed' and receipt['choice']==micro['result']['payload']['choice']=='confirm'
            and receipt['result_sha256']==micro['result_sha256'] and event['data'][field]==receipt['organization_id']
            and observed['event_sha256']==task_digest(event),'A03 lost the exact actual native selection')
        bound(micro,observed)
        appointment=source(micro,'Appointment')
        require(appointment['status']=='selected' and appointment['service_relationship_ref'] is None
            and appointment['reservation_ref'] is None,'A03 fabricated formal service completion or reservation')
        for prefix,action,prop,finalop in (('provider',receipt['role'].upper()+'-A02','consider_appointment',receipt['role'].lower()+'_appointment_acceptance'),
                                         ('owner','OWN-A04','select_appointment','owner_select_'+receipt['role'].lower())):
            prior=saved[observed[prefix+'_task_key']];identity=TaskIdentity(**prior['identity'])
            proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']==prop
                and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing independent selection proposal')['output']
            final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']==finalop
                and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing independent selection final')['output']
            require(identity.action_id==action and prior['result']['payload']['choice']=='accept'
                and observed[prefix+'_result_sha256']==prior['result_sha256']==proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']
                and proposal['accepted'] is final['decision'] is True
                and task_digest(proposal)==observed[prefix+'_proposal_sha256'] and task_digest(final)==observed[prefix+'_final_sha256'],
                'Portfolio original independent acceptance was replaced')
            if prefix=='owner':
                selection=event['data']['owner_selections'][receipt['role'].lower()]
                require(all(selection['decision_factors'].get(k)==v for k,v in proposal['factors'].items())
                    and final['data']['selected_agent_id']==receipt['organization_id'],
                    'Native selected provider differs from the original Owner decision')
            else:
                accepted=event_for(observed['acceptance_event_id'])
                require(accepted['data']['accepted'] is True
                    and all(accepted['data']['decision_factors'].get(k)==v for k,v in proposal['factors'].items()),
                    'Native did not execute this provider acceptance')
    proofs=[]
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];identity=TaskIdentity(**record['identity'])
        micro=saved[identity.key];judgment=result_judgment(micro);observed=record['observed']
        plan=PortfolioPlan.model_validate(one(plans,lambda p:(p['organization_id'],p['tick'])==(org,tick),'Missing monthly plan'))
        require(record==metadata[record['key']] and record['state']=='formed' and record['result_sha256']==micro['result_sha256']
            and identity.action_id=='ARCHITECT-A12' and identity.role=='Architect' and identity.organization_id==org
            and record['context']==plan.context.model_dump(mode='json')==snapshots[identity.key]['context']
            and record['action_input']==plan.action_input==snapshots[identity.key]['action_input'],'Monthly original request/action changed')
        require(observed['scope']==scope and observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],'Monthly macro input lost its actual origin')
        request_agent=record['native_request']['agent'];profile=observed['native_profile']
        require(request_agent['agent_id']==org and request_agent['role']=='Architect'
            and profile['available_resource']==request_agent['resources']['available_resource']
            and profile['total_resource_capacity']==request_agent['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],'Monthly native resources replaced')
        bound(micro,observed);observation=source(micro,'MonthlyPortfolioObservation');policy=source(micro,'MonthlyPortfolioPolicy')
        objects=deepcopy(plan.objects);basis=plan.native_evidence_ref.model_dump(mode='json');evidence_binding(objects,basis,observed)
        raw=one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Unbound observation missing')['value']
        require(all(raw[k] is None for k in ('market_demand','native_free_ratio','selected_entries','prior_own_outcomes')),'Prefilled portfolio decisions/sources')
        raw.update(market_demand={'value':str(observed['macro_environment']['market_demand_index']),'unit':'index','basis_ref':basis},
            native_free_ratio={'value':str(profile['free_ratio']),'unit':'ratio','basis_ref':basis},
            selected_entries=observed['selected_entries'],prior_own_outcomes=observed['prior_own_monthly_outcomes'])
        require(raw==observation and task_digest(objects)==record['source_sha256'],'A12 did not read exact runtime observations')
        require(source(micro,'ArchitectLearningState')['coverage']=='unknown' and source(micro,'Capability')['status']=='unknown'
            and policy['use']=='private_selection_portfolio_only' and policy['permitted_regions']==['Hong Kong']
            and policy['minimum_market_demand']['value']=='1' and policy['minimum_free_ratio']['value']=='0.2','Private bounded policy or unknown formal state changed')
        selected=[]
        for e in events:
            if e['event_type']!='consultant_team_appointed' or e['tick']>tick or e['data'].get('architect_id')!=org:continue
            receipt=one(receipts,lambda r:r['organization_id']==org and r['event_id']==e['event_id'],'Selected source lost original receipt')
            project=one(simulation['project_results'],lambda p:p['project_id']==e['project_id'],'Selected project missing')
            selected.append({'organization_id':org,'project_id':e['project_id'],'region':project['region'],
                'client_organization_id':e['agent_id'],'tick':e['tick'],'event_id':e['event_id'],'source_event_sha256':task_digest(e),
                'appointment_identity':receipt['identity'],'appointment_result_sha256':receipt['result_sha256'],
                'receipt_record_sha256':receipt['record_sha256'],'status':'selected_and_privately_confirmed'})
        selected.sort(key=lambda e:(e['tick'],e['project_id'],e['event_id']))
        require(observation['selected_entries']==selected==[e.model_dump(mode='json') for e in judgment.selected_entries],
            'Portfolio borrows, drops or invents an actual own confirmed selection')
        history=observation['prior_own_outcomes'];prior_entries=[]
        require(history==observed['prior_own_monthly_outcomes'] and len(history)==tick-1,'Earlier own monthly outcomes missing')
        for h in history:
            prior=saved[TaskIdentity(**h['micro_identity']).key];prior_judgment=result_judgment(prior);earlier=event_for(h['event_id'])
            require(h['tick']<tick and earlier['tick']==h['tick'] and earlier['agent_id']==org
                and h['micro_identity']['organization_id']==org and h['source_event_sha256']==task_digest(earlier)
                and h['micro_result_sha256']==prior['result_sha256'] and h['portfolio_judgment']==prior_judgment.model_dump(mode='json')
                and h['participated']==prior_judgment.participate
                and h['operation']==earlier['data']['operation']==(judgment.operation if prior_judgment.participate else 'maintain_operations'),
                'Later A12 did not consume the same actually executed portfolio artifact')
            prior_entries=[e.model_dump(mode='json') for e in prior_judgment.adopted_entries]
        new=sorted({e['event_id'] for e in selected}-{e['event_id'] for e in prior_entries})
        market_gate=Decimal(str(observed['macro_environment']['market_demand_index']))>=1
        capacity_gate=Decimal(str(profile['free_ratio']))>=Decimal('0.2');participate=market_gate and capacity_gate and bool(new)
        require(judgment.market_gate==market_gate and judgment.capacity_gate==capacity_gate and judgment.new_entry_event_ids==new
            and judgment.participate==participate and judgment.market_demand.model_dump(mode='json')==observation['market_demand']
            and judgment.native_free_ratio.model_dump(mode='json')==observation['native_free_ratio']
            and [e.model_dump(mode='json') for e in judgment.adopted_entries]==(selected if participate else prior_entries)
            and judgment.consumed_monthly_event_ids==[h['event_id'] for h in history], 'Original A12 failed the independent portfolio decision oracle')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original monthly proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original monthly final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Actual native monthly execution missing')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['request_id']==record['native_request']['request_id']
            and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==judgment.operation
            and event['data']['operation']==(judgment.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==judgment.interpretation,'Native did not execute this original monthly result')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Native agent missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Native operation memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native memory differs from actual execution')
        for h in history:
            require(h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick']
                and m.get('operation')==h['operation'],'Earlier native memory missing'),'Later portfolio uses another native memory')
        proofs.append({'scope':scope,'identity':identity.as_dict(),'observed':observed,'judgment':judgment.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_proposal':proposal,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'original_native_memory':memory})
    require(sum(p['judgment']['participate'] for p in proofs)==(2 if high else 0),'Unexpected fixed-case portfolio update count')
    later=one(proofs,lambda p:p['scope']['organization_id']=='professional-architect' and p['scope']['tick']==2,'Later main Architect missing')
    require(later['judgment']['participate'] is False and (not later['judgment']['new_entry_event_ids']) is high,
        'Confirmed first portfolio must remove repeated update work only in the high case')
    require(file_hash(database)==before,'Read-only verifier changed the journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'monthly_actions':len(records),
        'original_portfolio_updates':sum(p['judgment']['participate'] for p in proofs),'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    before=read(directory/'macro-before.json');macro=macro_hashes();require(before==macro,'Macro changed during the batch')
    requests=[read(directory/name/'input/macro-request.json') for name in config['scenarios']]
    normalized=deepcopy(requests)
    for r in normalized:r['macro_environment']['market_demand_index']=1.2
    require(normalized[0]==normalized[1],'Controlled initial native inputs differ beyond market demand')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    first=one(cases['high']['proofs'],lambda p:p['scope']['organization_id']=='professional-architect' and p['scope']['tick']==1,'Missing actual first update')
    later=one(cases['high']['proofs'],lambda p:p['scope']['organization_id']=='professional-architect' and p['scope']['tick']==2,'Missing later consumer')
    require(first['actual_event']['event_id'] in later['judgment']['consumed_monthly_event_ids']
        and first['judgment']['adopted_entries']==later['judgment']['adopted_entries'],'Required actual first update was not used later')
    return {'batch':'3C-Architect-portfolio','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'market_demand_index','cases':cases,'contacts':[{
            'macro_action':'Architect.build_cross_region_reputation','micro_action':'ARCHITECT-A12 optional private selection portfolio recording',
            'macro_input':'Actual market_demand_index, own native free ratio, same-run native selected project events and original A03 confirmations',
            'return_to_macro':'Original monthly proposal/final and scheduler agent_operation',
            'native_event_correlation':'Unique own organization/tick event, exact operation/description and retained memory against original proposal/final; the frozen monthly event itself does not contain the private micro result hash.',
            'feedback_consumer':'Later own A12 uses the same executed portfolio artifact; unchanged entries defer repeated update',
            'actual_events':[p['actual_event'] for p in cases['high']['proofs'] if p['judgment']['participate']],
            'later_consumer':{'identity':later['identity'],'consumed_event_id':first['actual_event']['event_id'],
                'prior_micro_result_sha256':first['micro_result_sha256'],'adopted_entries':later['judgment']['adopted_entries']}}],
        'remaining_engineer_qualification_blocker':{
            'operation':'Engineer.maintain_professional_qualifications','status':'blocked',
            'checked':['src/actions/roles/engineer_learning.py','integration/engineer_qualification_verification_handoff.py'],
            'missing':'Independent credential issuer event and exact responsible verification service; native activity logs and normalized capability are insufficient.'},
        'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/architect_portfolio_native.py','integration/architect_portfolio_development.py',
    'integration/verify_architect_portfolio_chain.py','integration/professional_monthly_native.py',
    'src/actions/contracts/architect_monthly_portfolio.py','src/actions/contracts/architect_learning_objects.py',
    'src/actions/roles/architect_monthly_portfolio.py','src/actions/roles/service_learning.py','config/architect_portfolio_chain.json',
    'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/宏观动作接线清单.md',
    'docs/建筑师月度作品集接线与验收.md','tests/test_architect_monthly_portfolio.py',
    'integration/professional_intake_native.py','integration/professional_intake_development.py',
    'integration/professional_appointment_native.py','integration/professional_appointment_native_sources.py',
    'integration/architect_learning_actions.py','integration/architect_learning_results.py',
    'integration/contractor_tender_authority_runtime.py','integration/bank_financing_private.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],'boundary':BOUNDARY,'overall_goal3_complete':False})
    lines=['# GOAL 3C 建筑师月度作品集实际运行记录','','原 A01/A02 → 原业主选择 → 原宏观选聘 → 原 A03 确认 → 原 A12 → 原月度动作 → 后轮原 A12。','',
        '| 场景 | 企业 | tick | 实际市场需求 | 已确认选聘 | 新记录数 | 原宏观实际动作 | 消费的先前月度事件 |','| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append('| '+' | '.join(map(str,[name,p['scope']['organization_id'],p['scope']['tick'],j['market_demand']['value'],
                len(j['selected_entries']),len(j['new_entry_event_ids']),p['actual_event']['data']['operation'],','.join(j['consumed_monthly_event_ids']) or 'none']))+' |')
    lines+=['','只通过原 SimulationCreateRequest.macro_environment 改变期初市场需求 1.2 / 0.6；其他宏观输入相同。私有阈值 1 和 0.2 独立事先声明，运行观测、选聘、确认和反馈未预填。',
        '高组实际开展两次作品集更新，主建筑师 tick 2 消费 tick 1 的同一次原宏观执行与私有作品集结果，因为没有新选聘而保留原作品集；低组市场门槛不满足，均不新增更新。',
        BOUNDARY,'','各组 command.json 保存普通 integration.run 启动命令，stdout.log/stderr.log 保存完整诊断；runtime/result.json 和 tasks.sqlite 保留原事件、决定和读取。checks.json 列出输入、结果、执行和后轮对应关系。',
        '原 scheduler 的随机能力更新不证明本活动导致能力提升。所有真实选聘均为香港项目，不声称已形成跨区域成功业绩、完成服务或客户评价。',
        '宏观 174 文件基线与全部 Python 源码保持不变。工程师资质仍缺独立颁发和核验来源。该项交付不代表 GOAL 3 或原 PLAN 全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'architect-portfolio-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
        print('Running original professional/portfolio case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.architect_portfolio_native:configure_assembly')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/architect_portfolio_chain.json');parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        run_cases(directory,read(args.config))
    elif (directory/'artifact-manifest.json').exists():
        manifest=verify_history(directory)
        pins=read(directory/'artifact-manifest.json')['implementations']
        require(all(file_hash(ROOT/n)==d for n,d in pins.items()),'Current portfolio implementation differs from its sealed version')
    checks=collect_checks(directory)
    if not args.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f!='proofs'} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
