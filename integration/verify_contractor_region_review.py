"""Run/check original A01 -> native regional review -> later original A01."""
from copy import deepcopy
from decimal import Decimal
import argparse
import json
from pathlib import Path
import sqlite3
from integration.contractor_region_development import build_bundle
from integration.contractor_region_review import BOUNDARY,RegionReviewPlan,result_judgment,bind_sources
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes,_write,verify_bundle
from integration.verify_tender_basic import verify_history,file_hash
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(set(config)=={'schema_version','run_id','scenarios','source_note'}
        and config['schema_version']=='contractor-region-review-chain.v1'
        and config['scenarios']=={'low':{'regional_friction':0.15},'high':{'regional_friction':0.65}}
        and config['run_id'] and config['source_note'],'Unsupported fixed region review scenario')


def verify_scenario(directory,*,low):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original regional review process failed')
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
            'Original A01 result, reading, task or snapshot changed')
    plans=read(directory/'input/region-review-input.json')['plans'];proofs=[]
    def source(micro,kind):return one(micro['source_reading'],lambda r:r['ref']['kind']==kind,'Missing original '+kind)['projection']
    def event_for(identity):return one(events,lambda e:e['event_id']==identity,'Missing original actual event')
    for record in sorted(records,key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record);scope=record['scope'];org=scope['organization_id'];tick=scope['tick'];identity=TaskIdentity(**record['identity']);micro=saved[identity.key]
        j=result_judgment(micro);observed=record['observed'];plan=RegionReviewPlan.model_validate(one(plans,lambda p:(p['organization_id'],p['tick'])==(org,tick),'Missing regional plan'))
        require(record==metadata[record['key']] and record['state']=='formed' and record['result_sha256']==micro['result_sha256']
            and identity.action_id=='CONTRACTOR-A01' and identity.organization_id==org and identity.role=='Contractor'
            and record['context']==plan.context.model_dump(mode='json')==snapshots[identity.key]['context']
            and record['action_input']==plan.action_input==snapshots[identity.key]['action_input'],'Original regional input changed')
        request_agent=record['native_request']['agent'];profile=observed['native_profile'];environment=observed['macro_environment']
        require(observed['scope']==scope and observed['native_request_sha256']==task_digest(record['native_request'])
            and environment==record['native_request']['inputs']['macro_environment']
            and request_agent['agent_id']==org and request_agent['role']=='Contractor' and profile['home_region']==request_agent['region']=='Hong Kong'
            and observed['native_friction']==environment['regional_friction_matrix']['Hong Kong']['Macao']
            and profile['available_resource']==request_agent['resources']['available_resource']
            and profile['total_resource_capacity']==request_agent['resources']['total_resource_capacity']
            and profile['free_ratio']==profile['available_resource']/profile['total_resource_capacity'],'Native actual region/friction/resources replaced')
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in micro['source_reading']),'Original result did not read observed provenance')
        observation=source(micro,'RegionEntryReviewObservation');policy=source(micro,'RegionEntryReviewPolicy');objects=bind_sources(plan,observed)
        require(one(objects,lambda r:r['ref']==plan.observation_ref.model_dump(mode='json'),'Missing bound observation')['value']==observation
            and task_digest(objects)==record['source_sha256'],'Original A01 did not read exact actual observations')
        package=source(micro,'ProcurementPackage');capability=source(micro,'ContractorCapability');commitments=source(micro,'CommitmentSnapshot')
        qualification=source(micro,'Qualification');method=source(micro,'WorkMethod');partner=source(micro,'RegionalPartnerDisclosure')
        require(policy['purpose']=='preliminary_qualification_and_local_partner_review' and policy['home_region']=='Hong Kong' and policy['target_region']=='Macao'
            and policy['maximum_friction']['value']=='0.35' and policy['minimum_free_ratio']['value']=='0.2'
            and source(micro,'OpportunityScreeningProfile')['outreach_limits'] is None
            and package['region_id']=={'state':'known','value':'Macao'} and package['work_types']['value']==['building']
            and package['access_mode']=='public' and not plan.action_input['invitation_refs']
            and qualification['standing']=={'state':'known','value':True} and qualification['region_ids']==method['region_ids']==['Macao']
            and qualification['qualification_code']==package['qualification_requirements']['value'][0]['qualification_code']
            and capability['qualification_coverage']==capability['resource_coverage']==commitments['coverage']=='complete'
            and len(capability['resources'])==len(commitments['allocations'])==len(package['resource_demands']['value'])==1
            and capability['resources'][0]['total']['value']['value']=='2'
            and commitments['allocations'][0]['quantity']['value']==package['resource_demands']['value'][0]['quantity']['value']=='1'
            and partner['reviewing_organization_id']==org and partner['region_ids']==['Macao'] and partner['work_types']==['building']
            and partner['disclosure_use']=='public_preliminary_candidate_review','Independent regional eligibility, public candidate or policy changed')
        capacity_calls=[c for c in micro['audit']['method_calls'] if c['method_ref']['id']=='micro.capacity.fixed_location']
        require(len(capacity_calls)==1 and capacity_calls[0]['result']['kind']=='ok'
            and capacity_calls[0]['result']['value']['feasible'] is True and capacity_calls[0]['input']['commitments']
            and j.screening_choice==micro['result']['payload']['choice']=='participate','Original A01 capacity/eligibility was bypassed')
        assessment={'home_region':'Hong Kong','target_region':'Macao','screening_choice':'participate',
            'screening_note':'Applicable invitation, qualification, method and capacity checks support participation intent only',
            'public_local_partner_candidates':[partner['partner_organization_id']],'preliminary_fit':True,
            'friction_within_private_limit':Decimal(str(observed['native_friction']))<=Decimal('0.35'),
            'formal_entry_permission':'unknown','counterparty_consent':'unknown','joint_venture_formed':False}
        require(j.assessment==assessment and j.screening_note==assessment['screening_note'],'A01 changed original result or inferred regional consent/permission')
        history=observation['prior_own_outcomes'];previous=[];agent=one(simulation['agent_results'],lambda a:a['agent_id']==org,'Missing native Contractor')
        require(history==observed['prior_own_monthly_outcomes'] and len(history)==tick-1,'Earlier actual own regional history missing')
        for h in history:
            prior=saved[TaskIdentity(**h['micro_identity']).key];prior_j=result_judgment(prior);earlier=event_for(h['event_id'])
            require(h['tick']<tick and earlier['tick']==h['tick'] and earlier['agent_id']==org and h['micro_identity']['organization_id']==org
                and h['source_event_sha256']==task_digest(earlier) and h['micro_result_sha256']==prior['result_sha256']
                and h['review']==prior_j.model_dump(mode='json') and h['assessment']==prior_j.assessment
                and h['participated']==prior_j.participate and h['operation']==earlier['data']['operation']==(j.operation if prior_j.participate else 'maintain_operations')
                and h['original_native_memory']==one(agent['episodic_memory'],lambda m:m.get('tick')==h['tick'] and m.get('operation')==h['operation'],'Missing earlier native memory'),
                'Later A01 lost exact actually executed regional assessment')
            if h['participated']:previous.append(h['assessment'])
        unchanged=assessment in previous;friction=Decimal(str(observed['native_friction']));margin=Decimal('0.35')-friction
        participate=friction<=Decimal('0.35') and Decimal(str(profile['free_ratio']))>=Decimal('0.2') and not unchanged
        require(j.participate==participate and j.unchanged_review==unchanged and Decimal(j.friction_margin)==margin
            and j.native_friction.model_dump(mode='json')==observation['native_friction']
            and j.native_free_ratio.model_dump(mode='json')==observation['native_free_ratio']
            and j.prior_actual_assessments==previous and j.consumed_event_ids==[h['event_id'] for h in history]
            and j.consumed_micro_result_sha256==[h['micro_result_sha256'] for h in history],'Independent regional decision oracle failed')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Missing original proposal')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Missing original final')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing original actual execution')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')==event['data']['operation'],'Missing native memory')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['request_id']==record['native_request']['request_id'] and event['data']['decision_source']=='llm_agent'
            and proposal['action_type']==final['action_type']==j.operation and event['data']['operation']==(j.operation if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==micro['result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==j.interpretation
            and memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Native execution differs from original regional judgment')
        proofs.append({'scope':scope,'identity':identity.as_dict(),'observed':observed,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':micro['result_sha256'],'original_capacity_method_call':capacity_calls[0],
            'original_proposal':proposal,'original_final':final,'actual_event':event,'actual_event_sha256':task_digest(event),'original_native_memory':memory})
    require(sum(p['judgment']['participate'] for p in proofs)==(2 if low else 0),'Unexpected regional review execution count')
    require(all(not p['judgment']['participate'] and p['judgment']['unchanged_review']==low
        for p in proofs if p['scope']['tick']==2),'Later exact assessment did not prevent repeated review')
    require(file_hash(database)==before,'Read-only check changed the journal')
    return {'status':'passed','technical_tasks':len(tasks),'original_micro_actions':len(workers),'monthly_actions':len(records),
        'actual_regional_reviews':sum(p['judgment']['participate'] for p in proofs),'proofs':proofs}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    native=[];private=[]
    for name in config['scenarios']:
        r=read(directory/name/'input/macro-request.json')
        require(r['macro_environment']['regional_friction_matrix']=={'Hong Kong':{'Macao':config['scenarios'][name]['regional_friction']}},'Supported initial regional friction difference missing')
        r['macro_environment']['regional_friction_matrix']={'Hong Kong':{'Macao':0.15}};native.append(r)
        p=read(directory/name/'input/region-review-input.json');p.pop('run_id')
        for plan in p['plans']:plan['context'].pop('run_id')
        private.append(p)
    require(native[0]==native[1] and private[0]==private[1],'Controlled cases differ beyond original initial regional friction')
    cases={name:verify_scenario(directory/name,low=name=='low') for name in config['scenarios']}
    return {'batch':'3A-Contractor-region-review','status':'passed','overall_goal3_complete':False,'macro':macro,
        'only_initial_macro_difference':'macro_environment.regional_friction_matrix.Hong Kong.Macao',
        'cases':cases,'contacts':[{'macro_action':'Contractor.evaluate_region_entry','micro_action':'CONTRACTOR-A01 original target-region eligibility with typed monthly public partner review',
            'macro_input':'Actual native home/target regional friction and own free ratio; independent synthetic target-region qualification, method, nonempty capacity/commitment dossier and public partner disclosures',
            'return_to_macro':'Original monthly proposal/final, scheduler agent_operation and retained episodic memory',
            'native_event_correlation':'Unique own organization/tick, exact operation/description and memory against original proposal/final; native event has no private micro result hash.',
            'feedback_consumer':'Later own original A01 consumes the same actual regional assessment; unchanged confirmed assessment prevents repeated review',
            'actual_events':[p['actual_event'] for p in cases['low']['proofs'] if p['judgment']['participate']]}],
        'remaining_blockers':['Contractor.seek_joint_venture_partner: scoped independent JV review/selection sources and original result/actual feedback binding remain absent',
            'Contractor.maintain_supplier_relationship: separate authorized current supplier-task and maintenance decision/effect/consumer remain absent'], 'boundary':BOUNDARY}


IMPLEMENTATIONS=['integration/contractor_region_review.py','integration/contractor_region_development.py','integration/verify_contractor_region_review.py',
    'integration/contractor_screening_actions.py','integration/contractor_screening_results.py','integration/contractor_monthly_development.py',
    'integration/professional_monthly_native.py','integration/bank_financing_private.py','integration/contractor_tender_authority_runtime.py',
    'src/actions/contracts/contractor_region_review.py','src/actions/contracts/contractor_objects.py','src/actions/roles/contractor_region_review.py','src/actions/roles/contractor.py',
    'config/contractor_region_review_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
    'docs/承包商月度区域评估接线与验收.md','docs/宏观动作接线清单.md','tests/test_contractor_region_review.py']


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':checks['batch'],'contacts':checks['contacts'],'boundary':BOUNDARY,'overall_goal3_complete':False})
    lines=['# GOAL 3A 承包商月度区域评估实际运行记录','','| 场景 | 企业 | tick | 实际区域摩擦 | 与上限 0.35 余量 | 同一已执行评估 | 原宏观实际动作 | 消费事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append('| '+' | '.join(map(str,[name,p['scope']['organization_id'],p['scope']['tick'],j['native_friction']['value'],j['friction_margin'],
                j['unchanged_review'],p['actual_event']['data']['operation'],','.join(j['consumed_event_ids']) or 'none']))+' |')
    lines+=['','仅通过原 SimulationCreateRequest.macro_environment.regional_friction_matrix 改变香港→澳门摩擦 0.15 / 0.65；其他宏观输入与独立私有资料相同。',
        '原 A01 在两组都完成指定区域资格、施工方法及 2 crew 容量/1 crew 已有承诺/1 crew 需求校验。公开候选资料不授予合作方同意、JV 或正式市场准入。',
        '月度评估要求摩擦不高于 0.35、空闲比例至少 0.2 且不存在相同已执行评估。低组首次两家实际 evaluate_region_entry，后轮原 A01 消费同一原评估后不重复开展；高组区域摩擦门槛未通过，维持运营。',
        '原提议合法 accepted=True 是候选；原最终 decide 的布尔值携带真正月度判断。原 A01 的初步参加意向仍是原有 participate，不等于已投标或已实际进入区域。',
        '各组 command.json 是完整普通 integration.run 命令，stdout.log/stderr.log 保留诊断；runtime/result.json、tasks.sqlite 和 checks.json 保存输入、决定、执行与后轮对应关系。',
        BOUNDARY,'宏观 174 文件基线与全部 120 个 Python 源码未改。JV、供应商关系及其他正式接口继续阻塞；GOAL 3 和原 PLAN 未全部完成。','']
    with (directory/'RUN_RECORD.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines))
    _write(directory,'artifact-manifest.json',{'schema_version':'contractor-region-review-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()},
        'implementations':{n:file_hash(ROOT/n) for n in IMPLEMENTATIONS}})


def run_cases(directory,config):
    validate_config(config);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    for name,profile in config['scenarios'].items():
        build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
        print('Running original Contractor regional review case '+name,flush=True)
        run_existing_input(directory/name,assembly_hook='integration.contractor_region_review:configure_assembly')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/contractor_region_review_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv)
    directory=a.output.resolve()
    if not a.check_only:run_cases(directory,read(a.config))
    elif (directory/'artifact-manifest.json').exists():
        verify_history(directory);require(all(file_hash(ROOT/n)==h for n,h in read(directory/'artifact-manifest.json')['implementations'].items()),'Current regional implementation differs from sealed version')
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'cases':{k:{f:v for f,v in c.items() if f!='proofs'} for k,c in checks['cases'].items()},
        'macro_files_unchanged':checks['macro']['file_count'],'output':str(directory)},ensure_ascii=False))


if __name__=='__main__':main()
