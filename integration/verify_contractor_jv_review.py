"""Fixed original A01 JV review, real monthly execution and later consumption."""
from decimal import Decimal
import argparse
import json
from pathlib import Path
import sqlite3
from integration.contractor_jv_development import build_bundle
from integration.contractor_jv_review import BOUNDARY,JVReviewPlan,result_judgment,bind_sources
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(set(config)=={'schema_version','run_id','scenarios','source_note'}
        and config['schema_version']=='contractor-jv-review-chain.v1'
        and config['scenarios']=={'low':{'regional_friction':0.15},'high':{'regional_friction':0.65}}
        and config['run_id'] and config['source_note'],'Unsupported fixed JV review scenario')


def verify_scenario(directory,*,high):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original JV review process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host'];records=host['requests'];events=host['original_global_events']
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==4,'Expected two Contractors over two ticks')
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Original observer failed')
    database=directory/'runtime/tasks.sqlite';before=file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_screening_results')]
    require(len(workers)==4 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Unresolved original tasks')
    taskmap={TaskIdentity(**t['identity']).key:t for t in tasks};saved={TaskIdentity(**r['identity']).key:r for r in workers}
    for micro in workers:
        digest_valid(micro);identity=TaskIdentity(**micro['identity']);snapshot=snapshots[identity.key];digest_valid(snapshot,'snapshot_sha256')
        require(micro['result_sha256']==task_digest(micro['result']) and micro['source_reading_sha256']==task_digest(micro['source_reading'])
            and micro['result']['kind']=='completed' and taskmap[identity.key]['output']==micro['result']
            and identity.context_sha256==task_digest(snapshot['context']) and identity.input_sha256==task_digest(snapshot['action_input']),
            'Original A01 result, source reading, task or snapshot changed')
    plans=read(directory/'input/jv-review-input.json')['plans'];proofs=[]
    def source(micro,kind):return one(micro['source_reading'],lambda r:r['ref']['kind']==kind,'Missing original '+kind)['projection']
    def event_for(event_id):return one(events,lambda e:e['event_id']==event_id,'Missing original actual event')
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];identity=TaskIdentity(**record['identity']);micro=saved[identity.key]
        j=result_judgment(micro);observed=record['observed'];plan=JVReviewPlan.model_validate(one(plans,lambda p:(p['organization_id'],p['tick'])==(org,tick),'Missing JV plan'))
        require(record==metadata[record['key']] and record['state']=='formed' and record['result_sha256']==micro['result_sha256']
            and identity.action_id=='CONTRACTOR-A01' and identity.organization_id==org and identity.role=='Contractor'
            and record['context']==plan.context.model_dump(mode='json')==snapshots[identity.key]['context']
            and record['action_input']==plan.action_input==snapshots[identity.key]['action_input'],'Original JV input changed')
        request_agent=record['native_request']['agent'];profile=observed['native_profile'];environment=observed['macro_environment']
        require(observed['scope']==scope and observed['native_request_sha256']==task_digest(record['native_request'])
            and environment==record['native_request']['inputs']['macro_environment']
            and request_agent['agent_id']==org and request_agent['role']=='Contractor' and profile['home_region']==request_agent['region']=='Hong Kong'
            and observed['native_friction']==environment['regional_friction_matrix']['Hong Kong']['Macao']
            and profile['available_resource']==request_agent['resources']['available_resource']
            and profile['total_resource_capacity']==request_agent['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],'Native friction/home/resources changed')
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in micro['source_reading']),'A01 did not read actual observed provenance')
        observation=source(micro,'JVPartnerReviewObservation');policy=source(micro,'JVPartnerReviewPolicy');objects=bind_sources(plan,observed)
        require(one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Missing bound JV observation')['value']==observation
            and task_digest(objects)==record['source_sha256'],'Original A01 did not read exact runtime JV sources')
        package=source(micro,'ProcurementPackage');capability=source(micro,'ContractorCapability');commitments=source(micro,'CommitmentSnapshot')
        qualification=source(micro,'Qualification');method=source(micro,'WorkMethod');screening=source(micro,'OpportunityScreeningProfile')
        disclosures=[r['projection'] for r in micro['source_reading'] if r['ref']['kind']=='RegionalPartnerDisclosure']
        require(policy['purpose']=='private_cross_region_risk_sharing_candidate_review' and policy['home_region']=='Hong Kong' and policy['target_region']=='Macao'
            and policy['minimum_free_ratio']['value']=='0.2' and screening['outreach_limits'] is None
            and screening['monthly_region_policy_ref'] is screening['monthly_region_observation_ref'] is None
            and package['region_id']=={'state':'known','value':'Macao'} and package['work_types']['value']==['building']
            and package['access_mode']=='public' and not plan.action_input['invitation_refs']
            and qualification['standing']=={'state':'known','value':True} and qualification['region_ids']==method['region_ids']==['Macao']
            and qualification['qualification_code']==package['qualification_requirements']['value'][0]['qualification_code']
            and capability['qualification_coverage']==capability['resource_coverage']==commitments['coverage']=='complete'
            and len(capability['resources'])==len(commitments['allocations'])==len(package['resource_demands']['value'])==1
            and capability['resources'][0]['total']['value']['value']=='2'
            and commitments['allocations'][0]['quantity']['value']==package['resource_demands']['value'][0]['quantity']['value']=='1'
            and len(disclosures)==len(policy['options'])==2,'Original own eligibility or bounded JV scope changed')
        capacity_calls=[c for c in micro['audit']['method_calls'] if c['method_ref']['id']=='micro.capacity.fixed_location']
        require(len(capacity_calls)==1 and capacity_calls[0]['result']['kind']=='ok' and capacity_calls[0]['result']['value']['feasible'] is True
            and capacity_calls[0]['input']['commitments'] and j.screening_choice==micro['result']['payload']['choice']=='participate','Original A01 method/eligibility bypassed')
        friction=Decimal(str(observed['native_friction']));expected=[]
        for partner_id,weight,effort in [('declared-public-macao-partner-a','0.6','0.1'),('declared-public-macao-partner-b','0.2','0.05')]:
            disclosure=one(disclosures,lambda d:d['partner_organization_id']==partner_id,'Missing declared public JV candidate')
            option=one(policy['options'],lambda o:o['disclosure_ref']==disclosure['ref'],'Missing matching private JV option')
            require(disclosure['reviewing_organization_id']==org and disclosure['scope']==plan.context.scope.model_dump(mode='json')
                and disclosure['region_ids']==['Macao'] and disclosure['work_types']==['building']
                and disclosure['disclosure_use']=='public_preliminary_candidate_review'
                and option['regional_review_weight']['value']==weight and option['own_review_effort_ratio']['value']==effort
                and option['regional_review_weight']['unit']==option['own_review_effort_ratio']['unit']=='ratio','Public disclosure/private effort was replaced by consent, physical capacity or money')
            expected.append({'partner_organization_id':partner_id,'public_region_work_fit':True,'regional_review_weight':weight,
                'own_review_effort_ratio':effort,'private_review_priority':str(friction*Decimal(weight)-Decimal(effort))})
        expected.sort(key=lambda c:(-Decimal(c['private_review_priority']),c['partner_organization_id']))
        preferred=next((c['partner_organization_id'] for c in expected if Decimal(c['private_review_priority'])>0),None)
        assessment={'home_region':'Hong Kong','target_region':'Macao','screening_choice':'participate',
            'screening_note':'Applicable invitation, qualification, method and capacity checks support participation intent only',
            'native_friction':str(friction),'ranked_public_candidates':expected,'preferred_private_review_candidate':preferred,
            'counterparty_consent':'unknown','committed_partner_capacity':'unknown','formal_entry_permission':'unknown','joint_venture_formed':False,
            'priority_interpretation':'Own preliminary review priority; weights and effort are independent private assumptions, not promised risk transfer, actual mitigation or quoted money.'}
        require(j.assessment==assessment and j.screening_note==assessment['screening_note'],'Independent JV candidate/priority oracle failed')
        history=observation['prior_own_outcomes'];previous=[];agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Missing native Contractor')
        require(history==observed['prior_own_monthly_outcomes'] and len(history)==tick-1,'Earlier actual own JV review missing')
        for h in history:
            prior=saved[TaskIdentity(**h['micro_identity']).key];prior_j=result_judgment(prior);earlier=event_for(h['event_id'])
            require(h['tick']<tick and earlier['tick']==h['tick'] and earlier['agent_id']==org and h['micro_identity']['organization_id']==org
                and h['source_event_sha256']==task_digest(earlier) and h['micro_result_sha256']==prior['result_sha256']
                and h['review']==prior_j.model_dump(mode='json') and h['assessment']==prior_j.assessment and h['participated']==prior_j.participate
                and h['operation']==earlier['data']['operation']==(j.operation if prior_j.participate else 'maintain_operations')
                and h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick'] and m.get('operation')==h['operation'],'Missing prior memory'),
                'Later A01 replaced the same actual JV review assessment')
            if h['participated']:previous.append(h['assessment'])
        unchanged=assessment in previous;participate=preferred is not None and Decimal(str(profile['free_ratio']))>=Decimal('0.2') and not unchanged
        require(j.participate==participate and j.unchanged_review==unchanged
            and j.native_friction.model_dump(mode='json')==observation['native_friction'] and j.native_free_ratio.model_dump(mode='json')==observation['native_free_ratio']
            and j.prior_actual_assessments==previous and j.consumed_event_ids==[h['event_id'] for h in history]
            and j.consumed_micro_result_sha256==[h['micro_result_sha256'] for h in history],'Original later A01 did not use confirmed review')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing original proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing original final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing native JV monthly execution')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Missing native memory')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['request_id']==record['native_request']['request_id'] and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==j.operation and event['data']['operation']==(j.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==j.interpretation
            and memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Original native execution differs from JV judgment')
        proofs.append({'scope':scope,'identity':identity.as_dict(),'observed':observed,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_capacity_method_call':capacity_calls[0],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),'original_native_memory':memory})
    require(sum(p['judgment']['participate'] for p in proofs)==(2 if high else 0),'Unexpected actual JV review count')
    require(all(not p['judgment']['participate'] and p['judgment']['unchanged_review']==high for p in proofs if p['scope']['tick']==2),'Confirmed assessment did not prevent repeated review')
    require(file_hash(database)==before,'Read-only verifier changed journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'monthly_actions':len(records),
        'actual_JV_candidate_reviews':sum(p['judgment']['participate'] for p in proofs),'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    native=[];private=[]
    for name in config['scenarios']:
        r=read(directory/name/'input/macro-request.json');require(r['macro_environment']['regional_friction_matrix']=={'Hong Kong':{'Macao':config['scenarios'][name]['regional_friction']}},'Initial supported friction difference missing')
        r['macro_environment']['regional_friction_matrix']={'Hong Kong':{'Macao':0.15}};native.append(r)
        p=read(directory/name/'input/jv-review-input.json');p.pop('run_id')
        for plan in p['plans']:plan['context'].pop('run_id')
        private.append(p)
    require(native[0]==native[1] and private[0]==private[1],'Controlled cases differ beyond original initial regional friction')
    cases={name:verify_scenario(directory/name,high=name=='high') for name in config['scenarios']}
    return {'batch':'3A-Contractor-JV-review','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'macro_environment.regional_friction_matrix.Hong Kong.Macao','cases':cases,
        'contacts':[{'macro_action':'Contractor.seek_joint_venture_partner','micro_action':'CONTRACTOR-A01 original eligibility plus typed private JV candidate risk-sharing priority',
            'macro_input':'Actual native regional friction and own free ratio; independent target-region eligibility, two public partner disclosures and private review hypotheses',
            'return_to_macro':'Original monthly proposal/final, scheduler agent_operation and retained episodic memory',
            'native_event_correlation':'Unique own organization/tick, exact operation/description and memory against original proposal/final; native event itself has no private micro result hash.',
            'feedback_consumer':'Later own original A01 reads exactly the confirmed candidate ranking; unchanged actually executed review prevents duplicate activity',
            'actual_events':[p['actual_event'] for p in cases['high']['proofs'] if p['judgment']['participate']]}],
        'remaining_blockers':['Contractor.maintain_supplier_relationship needs separate current supplier/task, judgment, actual effect and same-result consumer',
            'Formal JV commitment would require independent counterparty authority and consent; this monthly action does not create it'], 'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/contractor_jv_review.py','integration/contractor_jv_development.py','integration/verify_contractor_jv_review.py',
    'integration/contractor_region_review.py','integration/contractor_region_development.py','integration/contractor_screening_actions.py','integration/contractor_screening_results.py',
    'integration/professional_monthly_native.py','integration/bank_financing_private.py','integration/contractor_tender_authority_runtime.py',
    'src/actions/contracts/contractor_jv_review.py','src/actions/contracts/contractor_objects.py','src/actions/contracts/contractor_region_review.py',
    'src/actions/roles/contractor_jv_review.py','src/actions/roles/contractor.py','src/actions/roles/contractor_region_review.py',
    'config/contractor_jv_review_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
    'docs/承包商月度JV伙伴复核接线与验收.md','docs/宏观动作接线清单.md','tests/test_contractor_jv_review.py',
    'tests/test_contractor_region_review.py','tests/test_contractor_screening.py','integration/verify_contractor_region_review.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],'boundary':BOUNDARY,'overall_goal3_complete':False})
    lines=['# GOAL 3A 承包商月度 JV 伙伴复核实际记录','','| 场景 | 企业 | tick | 实际区域摩擦 | A 优先级 | B 优先级 | 私有首选 | 原宏观动作 | 消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];a=j['assessment'];scores={c['partner_organization_id']:c['private_review_priority'] for c in a['ranked_public_candidates']}
            lines.append('| '+' | '.join(map(str,[name,p['scope']['organization_id'],p['scope']['tick'],j['native_friction']['value'],
                scores['declared-public-macao-partner-a'],scores['declared-public-macao-partner-b'],a['preferred_private_review_candidate'] or 'none',
                p['actual_event']['data']['operation'],','.join(j['consumed_event_ids']) or 'none']))+' |')
    lines+=['','只通过原 SimulationCreateRequest.macro_environment.regional_friction_matrix 改变香港→澳门摩擦 0.15 / 0.65；其他宏观输入及独立私有资料相同。',
        '原 A01 先完成指定区域资质、方法及非空容量/承诺校验。私有候选优先级 = 实际摩擦 × 自己的复核权重 − 自己的复核投入比例。A 为 0.6 / 0.1，B 为 0.2 / 0.05；它们不是对方承诺、真实成本或实际风险转移。',
        '高组 A=0.29、B=0.08，首轮两家各实际 seek_joint_venture_partner；后轮原 A01 消费同一执行事件和完全相同的排序评估，停止重复复核。低组 A=-0.01、B=-0.02，没有正优先级候选，维持运营。',
        '原 A01 参加意向和原月度活动布尔值分别保留；合法正向候选提议不等于原宏观已执行。原提议/最终决定、真实事件及同轮记忆逐项对应。',
        '各组 command.json 是普通 integration.run 完整命令，stdout.log/stderr.log 保存诊断；runtime/result.json、tasks.sqlite 和 checks.json 保存输入、决定、执行及后轮消费。',
        BOUNDARY,'宏观 174 文件基线及全部 120 个 Python 源码未改。其他月度及正式来源/接口缺口保留；GOAL 3 和原 PLAN 未全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'contractor-jv-review-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
        print('Running original Contractor JV review case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.contractor_jv_review:configure_assembly')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/contractor_jv_review_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:run_cases(directory,read(a.config))
    elif (directory/'artifact-manifest.json').exists():
        verify_history(directory);require(all(file_hash(ROOT/n)==h for n,h in read(directory/'artifact-manifest.json')['implementations'].items()),'Current JV implementation differs from sealed version')
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f!='proofs'} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
