"""Fixed original procurement/relationship review with read-only correspondence checks."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from integration.contractor_supplier_development import build_bundle
from integration.contractor_supplier_review import BOUNDARY,SupplierReviewPlan,result_judgment,bind_sources
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(c):
    require(set(c)=={'schema_version','run_id','scenarios','source_note'} and c['schema_version']=='contractor-supplier-review-chain.v1'
        and c['scenarios']=={'weak':{'supply_reliability':0.4},'strong':{'supply_reliability':0.95}}
        and c['run_id'] and c['source_note'],'Unsupported fixed supplier relationship review cases')


def verify_scenario(directory,*,weak):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original supplier review process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    monthly=host['monthly'];records=monthly['requests'];events=monthly['original_global_events'];initial=read(directory/'input/macro-request.json')
    require(simulation['status']=='completed' and simulation['current_tick']==3 and len(records)==3,'Expected three actual monthly calls')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed')
    require(all(not p['selected_supplier_ids'] and not p['event_log'] for p in initial['initial_projects']),'Selected supplier result prefilled')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers=[json.loads(v) for table in ('supplier_screening_results','supplier_product_results','supplier_quote_results','supplier_order_results','contractor_planning_results')
            for v, in db.execute('SELECT record FROM '+table)]
    require(len(workers)==21 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Unresolved original tasks')
    taskmap={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r);i=TaskIdentity(**r['identity']);snapshot=snapshots[i.key];digest_valid(snapshot,'snapshot_sha256')
        require(r['result_sha256']==task_digest(r['result']) and r['source_reading_sha256']==task_digest(r['source_reading'])
            and r['result']['kind']=='completed' and taskmap[i.key]['output']==r['result']
            and i.context_sha256==task_digest(snapshot['context']) and i.input_sha256==task_digest(snapshot['action_input']),
            'Original micro task, result, source reading or invocation changed')
    suppliers=host['supplier']['requests'];contractors=host['supplier']['contractor']['requests']
    require(len(suppliers)==4 and len(contractors)==2,'Original procurement foundation not actually executed')
    for record in suppliers+contractors:
        digest_valid(record);require(record==metadata[record['key']],'Procurement export differs from original journal')
        r=saved[TaskIdentity(**record['identity']).key]
        require(record['state']=='formed' and record['result_sha256']==r['result_sha256'],'Procurement result changed')
        if record in suppliers:
            require(r['result']['payload']['choice']=='accept','Original supplier refused unexpectedly')
            for stage,action in [('screening','SUPPLIER-A01'),('product','SUPPLIER-A02'),('quote','SUPPLIER-A03')]:
                predecessor=saved[TaskIdentity(**record[stage]['identity']).key]
                require(predecessor['identity']['action_id']==action and predecessor['result_sha256']==record[stage]['result_sha256'],
                    'Original upstream procurement action was replaced')
    selections=sorted([e for e in events if e['event_type']=='supplier_selected'],key=lambda e:e['tick'])
    require([e['data']['supplier_id'] for e in selections]==['supply-a','supply-b'],'Actual original A05 selection/history changed')
    for event in selections:
        native=event['data']['contractor_decision'];r=saved[native['micro_task_key']]
        record=one(contractors,lambda row:TaskIdentity(**row['identity']).key==native['micro_task_key'],'Missing actual A05 proposal')
        require(native['micro_result_sha256']==r['result_sha256'] and native['proposal_response_sha256']==record['proposal_response_sha256']
            and r['result']['payload']['choice']=='accept_supply_offer','Actual selected supplier lost original micro result')
        origin=record['observed']['origin']
        require(saved[origin['A03_task_key']]['result_sha256']==origin['A03_result_sha256']
            and saved[origin['A04_task_key']]['result_sha256']==origin['A04_result_sha256'],'Selection substituted actual quote/acceptance')
    plans=read(directory/'input/supplier-review-input.json')['plans'];proofs=[]
    def source(r,kind):return one(r['source_reading'],lambda s:s['ref']['kind']==kind,'Missing original '+kind)['projection']
    for record in sorted(records,key=lambda row:row['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']],'Monthly export changed durable record')
        scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];i=TaskIdentity(**record['identity']);r=saved[i.key];j=result_judgment(r)
        observed=record['observed'];plan=SupplierReviewPlan.model_validate(one(plans,lambda p:p['tick']==tick,'Missing fixed plan'))
        objects=bind_sources(plan,observed)
        require(record['state']=='formed' and record['result_sha256']==r['result_sha256'] and record['source_sha256']==task_digest(objects)
            and record['context']==plan.context.model_dump(mode='json') and snapshots[i.key]['context']==record['context']
            and observed['native_request_sha256']==task_digest(record['native_request'])
            and observed['macro_environment']==record['native_request']['inputs']['macro_environment'],
            'Monthly actual request or source binding changed')
        for obj in objects:
            require(one(r['source_reading'],lambda s:s['ref']==obj['ref'],'Original A05 did not read declared source')['projection']==obj['value'],
                'Original A05 replaced a bound current source')
        mandate=source(r,'WorkAuthorization');capacity=source(r,'ContractorCapacity');policy=source(r,'SupplierRelationshipReviewPolicy')
        require(mandate['mandate_kind']=='preparation' and mandate['allow_supply_acceptance']=={'state':'known','value':False}
            and mandate['procurement_used']['state']=='unknown' and not mandate['procurement_history_complete']
            and capacity['coverage']==capacity['qualification_coverage']=='unknown','Future review fabricated construction, purchasing or physical capacity')
        history=observed['prior_own_monthly_outcomes'];prior=[]
        require(len(history)==tick-1,'Later review skipped earlier original monthly execution')
        for h in history:
            e=one(events,lambda e:e['event_id']==h['event_id'],'Missing earlier original monthly event')
            prev=saved[TaskIdentity(**h['micro_identity']).key];pj=result_judgment(prev)
            require(h['tick']==e['tick']<tick and e['agent_id']==org and h['micro_identity']['organization_id']==org
                and h['source_event_sha256']==task_digest(e) and h['micro_result_sha256']==prev['result_sha256']
                and h['review']==pj.model_dump(mode='json') and h['participated']==pj.participate
                and h['operation']==e['data']['operation']==(j.operation if pj.participate else 'maintain_operations'),
                'Later A05 substituted actual executed supplier review')
            if h['participated']:prior.extend(deepcopy(pj.review_targets))
        assessments=[];targets=[];suppressed=[];relationships=observed['selected_relationships']
        require({row['selection']['event_id'] for row in relationships}=={e['event_id'] for e in selections if e['tick']<tick},
            'Monthly eligibility differs from own strictly earlier actual supplier selections')
        for row in relationships:
            origin=row['selection'];e=one(selections,lambda e:e['event_id']==origin['event_id'],'Missing actual supplier selection')
            require(origin['contractor_id']==org and origin['supplier_id']==e['data']['supplier_id'] and origin['project_id']==e['project_id']
                and origin['tick']==e['tick']<tick and origin['micro_task_key']==e['data']['contractor_decision']['micro_task_key']
                and origin['micro_result_sha256']==e['data']['contractor_decision']['micro_result_sha256']
                and origin['proposal_response_sha256']==e['data']['contractor_decision']['proposal_response_sha256'],
                'Review borrowed a foreign or unexecuted supplier relationship')
            reliability=Decimal(row['native_reliability']['value']);availability=Decimal(row['native_material_availability']['value'])
            initial_supplier=one(initial['agents'],lambda a:a['agent_id']==origin['supplier_id'],'Missing initial supplier')
            own_event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing own monthly event')
            earlier=events[:events.index(own_event)]
            improvements=sum(e['event_type']=='agent_operation' and e['agent_id']==origin['supplier_id'] and e['data'].get('capability_update')=='supply_reliability' for e in earlier)
            expected=min(Decimal(1),Decimal(str(initial_supplier['supply_reliability']))+Decimal('0.01')*improvements)
            require(abs(expected-reliability)<Decimal('1e-12') and 0<=availability<=1,'Current native reliability did not come from initial profile plus actual native changes')
            issues=[];rl=Decimal(policy['minimum_reliability']['value']);al=Decimal(policy['minimum_availability']['value'])
            if reliability<rl:issues.append('normalized_reliability_below_private_threshold')
            if availability<al:issues.append('aggregate_material_availability_below_private_threshold')
            key={'selection_event_id':origin['event_id'],'project_id':origin['project_id'],'supplier_id':origin['supplier_id'],'issues':issues}
            already=any(p['review_key']==key for p in prior)
            a={'selection':origin,'native_reliability':row['native_reliability'],'native_material_availability':row['native_material_availability'],
                'reliability_shortfall':str(max(Decimal(0),rl-reliability)),'availability_shortfall':str(max(Decimal(0),al-availability)),
                'review_key':key,'already_actually_reviewed':already}
            assessments.append(a)
            if issues and already:suppressed.append(deepcopy(a))
            if issues and not already and Decimal(str(observed['native_profile']['free_ratio']))>=Decimal(policy['minimum_free_ratio']['value']):targets.append(deepcopy(a))
        require(j.assessments==assessments and j.review_targets==targets and j.suppressed_targets==suppressed and j.participate==bool(targets)
            and j.prior_actual_reviews==prior and j.consumed_event_ids==[h['event_id'] for h in history]
            and j.consumed_micro_result_sha256==[h['micro_result_sha256'] for h in history],'Original A05 did not apply current indicators and same actual previous review')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==i.key,'Missing original monthly proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==i.key,'Missing original final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing actual monthly execution')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Missing actual Contractor')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Missing original memory')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is j.participate
            and proposal['request_id']==record['native_request']['request_id'] and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==j.operation and event['data']['operation']==(j.operation if j.participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==r['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==j.interpretation
            and memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native execution/memory differs from A05 judgment')
        proofs.append({'scope':scope,'identity':i.as_dict(),'observed':observed,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':r['result_sha256'],'original_proposal':proposal,'original_final':final,'actual_event':event,'original_native_memory':memory})
    require([p['judgment']['participate'] for p in proofs]==([False,True,True] if weak else [False,False,False]),'Unexpected monthly supplier reviews')
    require(len(proofs[2]['judgment']['suppressed_targets'])==(1 if weak else 0),'Confirmed earlier review did not suppress the same supplier issue')
    require(file_hash(database)==before,'Read-only verifier changed original journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'original_procurement_actions':18,
        'monthly_actions':3,'actual_supplier_reviews':sum(p['judgment']['participate'] for p in proofs),'selections':selections,'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    native=[];private=[]
    for name in config['scenarios']:
        request=read(directory/name/'input/macro-request.json')
        require(all(a['supply_reliability']==config['scenarios'][name]['supply_reliability'] for a in request['agents'] if a['role']=='Supplier'),
            'Supported initial Supplier reliability difference missing')
        for a in request['agents']:
            if a['role']=='Supplier':a['supply_reliability']=0.4
        native.append(request)
        private.append(read(directory/name/'input/supplier-review-input.json'))
    # Both isolated runs intentionally use the same logical run_id and identical private inputs.
    require(native[0]==native[1] and private[0]==private[1],'Controlled cases differ beyond supported initial supplier reliability')
    cases={name:verify_scenario(directory/name,weak=name=='weak') for name in config['scenarios']}
    regression=None
    if (directory/'procurement-regression').exists():
        from integration.verify_procurement_chain import verify_scenario as verify_procurement
        original=verify_procurement(directory/'procurement-regression',name='accepted_feedback')
        require(original==read(directory/'procurement-regression/regression-checks.json'),'Original independent procurement regression changed')
        regression={k:original[k] for k in ('status','native_ticks','technical_tasks','original_procurement_actions','read_only','journal_sha256')}
    return {'batch':'3E-Contractor-supplier-review','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'SimulationCreateRequest.agents[Supplier].supply_reliability','cases':cases,
        'standalone_original_procurement_regression':regression,'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/contractor_supplier_review.py','integration/contractor_supplier_development.py','integration/verify_contractor_supplier_review.py',
    'src/actions/contracts/contractor_supplier_review.py','src/actions/roles/contractor_supplier_review.py','src/actions/contracts/contractor_planning_objects.py',
    'src/actions/roles/contractor_planning.py','integration/contractor_planning_actions.py','integration/contractor_planning_results.py',
    'integration/supplier_order_native.py','integration/contractor_supply_native.py','integration/contractor_supply_native_feedback.py',
    'integration/supplier_order_native_development.py','integration/professional_monthly_native.py','integration/verify_procurement_chain.py',
    'config/contractor_supplier_review_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
    'docs/承包商月度供应商复核接线与验收.md','docs/宏观动作接线清单.md','tests/test_contractor_supplier_review.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'overall_goal3_complete':False,'boundary':BOUNDARY,
        'contacts':[{'macro_action':'Contractor.maintain_supplier_relationship','micro_action':'CONTRACTOR-A05',
            'macro_input':'Own actual earlier supplier selections, current public normalized supplier reliability, aggregate project material availability and own free ratio',
            'micro_processing':'Original independently authorized future inquiry preparation plus typed private deficit/issue review',
            'return_to_macro':'Original monthly proposal/final -> actual scheduler event and own memory',
            'feedback_consumer':'Later own A05 reads exact executed review and skips the same selected-relationship issue',
            'actual_events':[p['actual_event'] for p in checks['cases']['weak']['proofs'] if p['judgment']['participate']]}]})
    lines=['# GOAL 3E 承包商月度供应商复核运行记录','','| 场景 | tick | 已选关系 | 复核目标 | 已执行同问题而跳过 | 原宏观动作 | 消费月度事件 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for name,c in checks['cases'].items():
        for p in c['proofs']:
            j=p['judgment'];sid=lambda rows:','.join(r['selection']['supplier_id'] for r in rows) or 'none'
            lines.append('| '+' | '.join(map(str,[name,p['scope']['tick'],sid(j['assessments']),sid(j['review_targets']),sid(j['suppressed_targets']),
                p['actual_event']['data']['operation'],','.join(j['consumed_event_ids']) or 'none']))+' |')
    lines+=['','两组仅通过原 SimulationCreateRequest.agents 初始 Supplier.supply_reliability 0.4 / 0.95 构造差异。私有阈值、准备授权和未来一块 panel 需求相同；两个独立任务库使用相同逻辑 run_id，不共享或重放任务。',
        '每组先实际执行 18 个原采购动作：Supplier A01→A02→A03→A04，Contractor A05 选供。两项目依次选 A/B；关系来自本次原事件和原 A05 结果，未预填供应商关系。',
        '后续三个原 A05 保留 preparation 授权、产品/数量/接收时窗/询价渠道检查；采购额度、已用额度和容量未知，不能用于购买或施工。',
        '微观判断计算可靠性缺口=max(0,0.7−当前原生可靠性)，可得性缺口=max(0,0.3−当前原生项目材料可得性)。这些指标没有物理单位。',
        'tick 1 尚无较早真实关系；tick 2 弱组对 A 实际执行月度内部复核；tick 3 读取同一执行事件、微观结果和复核键，跳过 A 的同类问题，同时复核新中选 B。强组无可靠性缺口，保持运营。',
        'checks.json 保存原请求、原微观结果标识/哈希、真实选供及月度事件、原提议/最终决定和后轮消费。command.json 是普通 integration.run 完整命令；runtime/ 保存任务库和结果。',
        '原月度事件本身不含私有结果哈希；按本机构/时点唯一事件、精确动作和描述、原提议/决定以及自身记忆关联。',BOUNDARY,
        '宏观 174 个基线文件及全部 120 个 Python 源码未改。其余月度/正式来源阻塞保留；GOAL 3 与原 PLAN 未全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'contractor-supplier-review-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id'],**profile)
        print('Running original procurement/supplier review case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.contractor_supplier_review:configure_assembly')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/contractor_supplier_review_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:run_cases(directory,read(a.config))
    elif (directory/'artifact-manifest.json').exists():
        verify_history(directory);require(all(file_hash(ROOT/n)==h for n,h in read(directory/'artifact-manifest.json')['implementations'].items()),'Current supplier review implementation differs from sealed version')
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f not in {'proofs','selections'}} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
