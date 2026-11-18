"""Fixed native strategy cases with independent read-only source, method and feedback verification."""
import argparse
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.owner_monthly_strategy import (
    MonthlyOwnerStrategyPlan,OwnerMonthlyStrategyApplication,bind_sources,bind_investment_sources,result_judgment,BOUNDARY,
)
from integration.owner_monthly_strategy_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity,task_digest
from src.methods.owner_investment import OptionComparisonInput,compare_option_intervals


def validate_config(config):
    require(set(config)=={'schema_version','run_id','ticks','scenarios'} and config['schema_version']=='owner-monthly-strategy-chain.v1'
        and config['ticks']==2 and config['scenarios']=={'normal':{'financing_condition_index':1.2},'watch':{'financing_condition_index':0.7}},
        'Unsupported fixed Owner strategy controls')


def verify_reading(record,saved,plan,objects,schemas,snapshots,tasks):
    digest_valid(record);digest_valid(saved);identity=TaskIdentity(**record['identity'])
    require(record['state']=='formed' and saved['identity']==identity.as_dict()
        and saved['result_sha256']==record['result_sha256']==task_digest(saved['result'])
        and saved['source_reading_sha256']==task_digest(saved['source_reading'])
        and one(tasks,lambda t:t['identity']==identity.as_dict(),'Original action task missing')['output']==saved['result'],
        'Original action identity/result/reading changed')
    snapshot=snapshots[identity.key]
    require(record['context']==plan.context.model_dump(mode='json')==snapshot['context']
        and record['action_input']==plan.action_input==snapshot['action_input']
        and identity.input_sha256==task_digest(plan.action_input)==saved['audit']['input_sha256'],
        'Original prepared invocation changed')
    require(record['source_sha256']==task_digest(objects) and record['observed']['native_request_sha256']==task_digest(record['native_request']),
        'Actual bound input/feedback or request binding changed')
    for source in saved['source_reading']:
        row=one(objects,lambda r:r['ref']==source['ref'],'Undeclared action reading')['value']
        require(source['projection']==schemas.validate_projection(Reference.model_validate(source['ref']),row).model_dump(mode='json'),
            'Saved original typed reading changed')
    return identity


def verify_scenario(directory,*,name):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original native strategy process failed')
    result=read(directory/'runtime/result.json');host=result['module_host_extension']['host'];events=host['original_global_events']
    require(result['simulation']['status']=='completed' and result['simulation']['current_tick']==2
        and host['boundary']==BOUNDARY and len(host['requests'])==len(host['investment_requests'])==2,
        'Both original monthly strategy and private comparison calls must finish')
    require({e['event_type'] for e in events}<={'project_state_updated','agent_operation'}
        and not any(e['data'].get('agent_observer_errors') for e in events),'Unexpected native investment, lifecycle effect or observer diagnostic')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM owner_operating_results')]
        comparisons=[json.loads(v) for v, in db.execute('SELECT record FROM owner_investment_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(len(tasks)==20 and len(workers)==len(comparisons)==2
        and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original technical task count/state/hash changed')
    plans=read(directory/'input/owner-strategy-input.json')['plans'];declaration=read(directory/'input/source-policy.json')
    proofs=[];investment_proofs=[]
    from integration.owner_investment_actions import OwnerInvestmentActionAssembler
    for record in sorted(host['requests'],key=lambda r:r['scope']['tick']):
        tick=record['scope']['tick'];plan=MonthlyOwnerStrategyPlan.model_validate(one(plans,lambda p:p['tick']==tick,'Own plan missing'))
        saved=one(workers,lambda w:w['identity']==record['identity'],'Original OWN-A15 result missing')
        objects=bind_sources(plan,record['observed'])
        identity=verify_reading(record,saved,plan,objects,OwnerMonthlyStrategyApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS(),snapshots,tasks)
        require(record==metadata[record['key']] and identity.action_id=='OWN-A15' and identity.organization_id==plan.organization_id,
            'Durable original monthly record changed')
        observed=record['observed'];j=result_judgment(saved)
        require(observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and observed['actual_own_project']=={'project_id':plan.project_id,'owner_id':plan.organization_id},'Actual own macro request/project changed')
        def source(kind,identity_ref=None):return one(objects,lambda r:r['ref']['kind']==kind and (identity_ref is None or r['ref']==identity_ref),'Source missing: '+kind)['value']
        portfolio=source('OwnerPortfolio',plan.action_input['portfolio_ref']);obligation=source('Obligation',plan.action_input['obligation_refs'][0])
        profile=source('OwnerOperatingProfile',plan.action_input['operating_profile_ref'])
        policy=source('MonthlyInvestmentPolicy',profile['monthly_strategy_policy_ref'])
        market=source('Observation',plan.action_input['observation_refs'][0])
        require(portfolio['coverage']=='complete' and portfolio['as_of']==plan.context.business_time.model_dump(mode='json')
            and len(portfolio['obligation_refs'])==1 and portfolio['obligation_refs']==plan.action_input['obligation_refs']
            and obligation['actual_due']['value']['value']=='5' and obligation['actual_paid']['value']['value']=='0'
            and profile['choice']=='retain_policy' and profile['preference_profile_ref'] is None
            and profile['proposed_limit'] is None and not profile['allocations']
            and market['kind']=='market' and market['outcome_code'] is None and not market['dimension_codes']
            and market['event_id']=='actual-native-request:'+observed['native_request_sha256'],
            'Source prefilled a choice, created a learned outcome, or dropped an old obligation')
        require(policy['financing_watch_threshold']['value']=='0.95' and policy['minimum_weight_change']=='0.1' and policy['maximum_updates']==1,
            'Independent authorized rule changed')
        watch=Decimal(j.financing_index.value)<Decimal('0.95')
        require(watch is (name=='watch') and j.financing_watch==watch
            and j.financing_index.value==str(observed['macro_environment']['financing_condition_index'])
            and j.participate is (tick==1) and j.original_choice==('revise_preferences' if tick==1 else 'retain_policy'),
            'Actual index did not select the private strategy/retain decision')
        expected=declaration['watch' if watch else 'normal'];require(j.effective_scores==expected and j.proposed_scores==expected,'Original micro did not select the declared finite weights')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1 and j.prior_actual_update_count==tick-1,'Actual own earlier strategy missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Prior actual own native strategy missing')
            require(h['micro_identity']==previous['identity'] and h['micro_result_sha256']==previous['micro_result_sha256']
                and h['strategy']==previous['judgment'] and h['strategy_sha256']==task_digest(previous['judgment'])
                and h['source_event_sha256']==previous['actual_event_sha256']
                and h['source_reading']==previous['source_reading'] and h['source_reading_sha256']==previous['source_reading_sha256']
                and h['accepted_preference']==previous['effective_preference'] and h['accepted_preference_sha256']==task_digest(previous['effective_preference'])
                and h['original_native_memory']['operation']==h['operation']=='adjust_investment_strategy'
                and h['original_native_memory']['label']==previous['actual_event']['data']['label']
                and h['original_native_memory']['capability_update']==previous['actual_event']['data'].get('capability_update'),
                'Later strategy adopted a foreign, changed, unexecuted or different-result preference')
        if tick==2:
            require(j.current_preference_ref.model_dump(mode='json')==history[0]['accepted_preference']['ref']
                and j.effective_preference_ref==j.current_preference_ref and Decimal(j.maximum_weight_change)==0
                and j.consumed_event_ids==[history[0]['event_id']],'Next original A15 did not consume/retain the exact actually adopted version')
        proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
            and t['output']['factors'].get('micro_task_key')==identity.key,'Original candidate proposal missing')['output']
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
            and t['output']['data'].get('micro_task_key')==identity.key,'Original final decision missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual original monthly execution missing')
        require(proposal['accepted'] is True and proposal['factors']['micro_participation']==final['decision']==j.participate
            and proposal['action_type']==final['action_type']=='adjust_investment_strategy'
            and proposal['factors']['micro_result_sha256']==final['data']['micro_result_sha256']==saved['result_sha256']
            and final['data']['proposal_response_sha256']==record['proposal_response_sha256']==task_digest(proposal)
            and event['data']['operation']==('adjust_investment_strategy' if j.participate else 'maintain_operations')
            and event['description']==proposal['data']['description']==j.model_dump_json(),
            'Original native execution differs from the actual micro choice/profile')
        effective=source('OwnerPreferenceProfile',j.effective_preference_ref.model_dump(mode='json'))
        proofs.append({'identity':identity.as_dict(),'tick':tick,'judgment':j.model_dump(mode='json'),
            'micro_result_sha256':saved['result_sha256'],'source_reading':saved['source_reading'],'source_reading_sha256':saved['source_reading_sha256'],
            'effective_preference':effective,'original_proposal':proposal,'original_final':final,
            'actual_event':event,'actual_event_sha256':task_digest(event),'history':history})
        comparison_record=one(host['investment_requests'],lambda r:r['scope']['tick']==tick,'Private original comparison missing')
        comparison=one(comparisons,lambda r:r['identity']==comparison_record['identity'],'Original OWN-A03 result missing')
        comparison_objects=bind_investment_sources(plan,comparison_record['observed'])
        ci=verify_reading(comparison_record,comparison,plan.investment,comparison_objects,OwnerInvestmentActionAssembler.SOURCE_SCHEMAS(),snapshots,tasks)
        require(comparison_record==metadata[comparison_record['key']] and ci.action_id=='OWN-A03' and ci.organization_id==identity.organization_id,
            'Original private comparison journal changed')
        adopted=comparison_record['observed']['applied_preference']
        expected_preference=effective if tick==2 else one(plan.objects,lambda r:r['ref']==plan.initial_preference_ref.model_dump(mode='json'),'Initial preference missing')['value']
        if tick==2:expected_preference=proofs[0]['effective_preference']
        require(adopted==expected_preference and comparison_record['observed']['applied_preference_sha256']==task_digest(adopted)
            and comparison_record['observed']['applied_scores']==adopted['scores']
            and comparison_record['observed']['prior_own_monthly_outcomes']==history,'Original A03 consumed a different or unexecuted private strategy')
        calls=[c for c in comparison['audit']['method_calls'] if c['method_ref']['id']=='micro.owner.declared_option_intervals']
        require(len(calls)==2,'Original A03 must actually calculate full and viable comparisons')
        for call in calls:
            data=OptionComparisonInput.model_validate(call['input']);report=compare_option_intervals(data)
            require(call['result']['kind']=='ok' and call['result']['value']==report.model_dump(mode='json')
                and call['registry_digest']==ci.versions['method']
                and {c.code:c.weight for c in data.criteria}==adopted['scores'],'Original method did not use actual adopted weights')
        old=one(comparison['source_reading'],lambda r:r['ref']['kind']=='Obligation','Comparison omitted original old obligation')['projection']
        require(old['actual_due']['value']['value']=='5' and old['actual_paid']['value']['value']=='0'
            and comparison['result']['kind']=='completed' and comparison['result']['payload']['choice']=='invest',
            'Comparison discarded an old duty or changed its original bounded proposal')
        ranking=calls[-1]['result']['value'];scores={r['option_ref']['id']:str(Fraction(r['conservative']['numerator'],r['conservative']['denominator'])) for r in ranking['scores']}
        require(scores['build']==('2/5' if tick==1 else '7/100' if watch else '73/100'),
            'Original later comparison score does not reflect actual private strategy adoption')
        investment_proofs.append({'identity':ci.as_dict(),'tick':tick,'applied_preference':adopted,'micro_result_sha256':comparison['result_sha256'],
            'comparison_method_calls':calls,'conservative_scores':scores,'private_choice':comparison['result']['payload']['choice'],
            'actual_native_investment_executed':False})
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only verification changed the original journal')
    return {'status':'actual_original_strategy_execution_adoption_and_later_investment_comparison_verified','proofs':proofs,
        'investment_proofs':investment_proofs,'technical_tasks':len(tasks),'owner_technical_tasks':8,'native_background_tasks_not_counted_as_micro_coverage':12,
        'read_only_journal_sha256':before,'formal_investment_or_cash_movement_inferred':False}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name,name=name) for name in config['scenarios']}
    a=read(directory/'normal/input/macro-request.json');b=read(directory/'watch/input/macro-request.json')
    a['macro_environment']['financing_condition_index']=b['macro_environment']['financing_condition_index'];require(a==b,'Native controls differ beyond supported financing index')
    a=read(directory/'normal/input/owner-strategy-input.json');b=read(directory/'watch/input/owner-strategy-input.json')
    a['run_id']=b['run_id']
    for plan in a['plans']:
        plan['context']['run_id']=b['run_id'];plan['investment']['context']['run_id']=b['run_id']
    require(a==b,'Independent private inputs differ between controlled cases')
    require(cases['normal']['investment_proofs'][0]['conservative_scores']==cases['watch']['investment_proofs'][0]['conservative_scores']
        and cases['normal']['investment_proofs'][1]['conservative_scores']!=cases['watch']['investment_proofs'][1]['conservative_scores'],
        'Actual environment-controlled strategy did not affect a later original calculation')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    return {'batch':'3I-Owner-strategy','status':'original_private_strategy_actual_native_execution_and_later_original_investment_consumer_verified',
        'overall_goal3_complete':False,'cases':cases,'boundary':BOUNDARY,'macro':macro,
        'controlled_input_difference':'Original supported macro_environment.financing_condition_index=1.2 versus 0.7; same seed, private initial portfolio, independent finite preferences and comparison dossier',
        'monthly_pipeline_screening':'Still blocked: this fixed monthly request has only macro_environment, not the actual original candidate set; no opportunity or candidate was generated to impersonate that missing source.'}


def write_delivery(directory,checks):
    rows=[]
    for name,case in checks['cases'].items():
        j=case['proofs'][0]['judgment'];later=case['investment_proofs'][1]
        rows.append(f"| {name} | {j['financing_index']['value']} | {j['effective_scores']['expected_return']} / {j['effective_scores']['risk']} | {case['proofs'][0]['actual_event']['event_id']} | 2/5 → {later['conservative_scores']['build']} |")
    lines=['# GOAL 3I 业主投资策略及后轮比较运行记录','',
        '原 OWN-A15 根据实际融资环境在独立授权的有限偏好中选择；原宏观实际执行后，后轮原 OWN-A03 才使用同一策略版本，原 OWN-A15 同时比较并保留该版本。','',
        '| 场景 | 首轮实际融资指数 | 收益 / 风险权重 | 原策略执行事件 | 后轮原 A03 建设方案保守得分 |',
        '| --- | --- | --- | --- | --- |',*rows,'',
        '首轮两组均使用初始权重进行原投资比较。第二轮仅采用严格较早且由真实原事件、提案、最终决定、微观结果和原记忆共同确认的偏好。'
        '旧应付 5 HKD、已付 0 在原 A15 和 A03 中均保留；偏好不产生现金或清偿债务。原 A03 的 invest 是私人授权提议，未交给原宏观创建项目。','',
        '复现（目录必须不存在）：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_strategy --output output/integration/owner_strategy_my_run",'```','',
        '只读复核：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_strategy --check-only --output '{directory.as_posix()}'",'```','',
        '输入、原读取、原处理器决定、两次比较方法审计、真实执行、后轮采用关系见 checks.json 与各组 input/runtime。'
        '每组 20 个技术任务，其中业主 8 个，其余 12 个为原生背景任务，不计入新增微观覆盖。','',BOUNDARY,'',
        '月度项目管线筛选仍缺实际候选来源。完整微观和正式接口缺口继续保留，GOAL 3 和原 PLAN 均未全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/owner_monthly_strategy.py','integration/owner_monthly_strategy_development.py','integration/verify_owner_monthly_strategy.py',
        'src/actions/contracts/owner_monthly_strategy.py','src/actions/roles/owner_monthly_strategy.py','src/actions/contracts/owner_operating_objects.py',
        'src/actions/roles/owner_operating.py','src/actions/roles/owner_investment.py','src/methods/owner_investment.py',
        'integration/professional_monthly_native.py','tests/test_owner_monthly_strategy.py','tests/fixtures/roles/owner_investment.v1.json',
        'tests/fixtures/roles/lifecycle_v6_owner_operating_budget_inputs.v1.json','config/owner_monthly_strategy_chain.json',
        'config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json','docs/业主月度投资策略接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'owner-monthly-strategy-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/owner_monthly_strategy_chain.json');parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile)
            run_existing_input(directory/name,assembly_hook='integration.owner_monthly_strategy:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not args.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
