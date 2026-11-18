"""Run or read-only verify actual Owner monthly financing-capacity reviews."""
import argparse
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.owner_monthly_capacity import MonthlyOwnerCapacityPlan,OwnerMonthlyCapacityApplication,bind_sources,result_judgment,BOUNDARY
from integration.owner_monthly_capacity_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.contractor_tender_development import _write,verify_bundle
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity,task_digest
from src.methods.owner_investment import CashCalendarInput,check_cash_calendar


def validate_config(config):
    require(config['schema_version']=='owner-monthly-capacity-chain.v1' and config['ticks']==2 and config['scenarios']=={
        'normal':{'financing_condition_index':1.2,'actual_cash':'100'},'environment_watch':{'financing_condition_index':0.7,'actual_cash':'100'},
        'cash_shortfall':{'financing_condition_index':1.2,'actual_cash':'30'}},'Unsupported fixed financing-capacity controls')


def verify_scenario(directory,*,name):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Original review process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host'];records=host['requests'];events=host['original_global_events']
    plans=read(directory/'input/owner-monthly-capacity-input.json')['plans'];policy=read(directory/'input/source-policy.json')
    require(simulation['status']=='completed' and simulation['current_tick']==2 and len(records)==2 and host['boundary']==BOUNDARY,'Two completed original review months required')
    require(not any(e['data'].get('agent_observer_errors') for e in events) and {e['event_type'] for e in events}<={'project_state_updated','agent_operation'},'Review unexpectedly executed financing or observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')];metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM owner_financing_results')]
        snapshots={k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    require(len(tasks)==6 and len(workers)==2 and all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Original task count/state/digest changed')
    schemas=OwnerMonthlyCapacityApplication.COMPONENTS['Owner'][0].SOURCE_SCHEMAS();proofs=[];financial_snapshots=[]
    for record in sorted(records,key=lambda r:r['scope']['tick']):
        digest_valid(record);require(record==metadata[record['key']] and record['state']=='formed','Original journal changed')
        identity=TaskIdentity(**record['identity']);tick=record['scope']['tick'];observed=record['observed']
        micro=one(workers,lambda w:w['identity']==identity.as_dict(),'Original OWN-A05 result missing');digest_valid(micro);judgment=result_judgment(micro)
        require(identity.role=='Owner' and identity.action_id=='OWN-A05' and record['result_sha256']==micro['result_sha256']==task_digest(micro['result'])
            and micro['source_reading_sha256']==task_digest(micro['source_reading']) and one(tasks,lambda t:t['identity']==identity.as_dict(),'A05 task missing')['output']==micro['result'],'Original A05 task/result changed')
        plan=MonthlyOwnerCapacityPlan.model_validate(one(plans,lambda p:p['organization_id']==identity.organization_id and p['tick']==tick,'Own plan missing'))
        snapshot=snapshots[identity.key]
        require(record['context']==plan.context.model_dump(mode='json')==snapshot['context'] and record['action_input']==plan.action_input==snapshot['action_input']
            and identity.input_sha256==task_digest(plan.action_input)==micro['audit']['input_sha256'],'Original authorized invocation changed')
        require(observed['native_request_sha256']==task_digest(record['native_request']) and observed['macro_environment']==record['native_request']['inputs']['macro_environment']
            and record['native_request']['agent']['agent_id']==identity.organization_id,'Actual native request binding changed')
        objects=bind_sources(plan,observed);require(task_digest(objects)==record['source_sha256'],'Bound source hash changed')
        for reading in micro['source_reading']:
            supplied=one(objects,lambda r:r['ref']==reading['ref'],'Undeclared actual reading')['value']
            require(reading['projection']==schemas.validate_projection(Reference.model_validate(reading['ref']),supplied).model_dump(mode='json'),'Actual typed source reading changed')
        def source(kind):return one(objects,lambda r:r['ref']['kind']==kind,'Required source missing: '+kind)['value']
        observation=source('MonthlyOwnerCapacityObservation');profile=source('FundingProfile');account=source('Account');funding=source('FundingSource');debt=source('Debt');obligation=source('Obligation')
        current=Decimal(str(observed['macro_environment']['financing_condition_index']));shortfall=name=='cash_shortfall';environment=name=='environment_watch'
        require(profile['policy']=={'state':'known','value':'own_funds'} and profile['coverage']==account['coverage']==funding['coverage']==debt['coverage']=='complete'
            and account['actual_cash']==funding['actual_cash'] and account['actual_cash']['value']['value']==('30' if shortfall else '100')
            and account['restricted_cash']['value']['value']=='10' and debt['outstanding_principal']['value']['value']=='15'
            and obligation['actual_due']['value']['value']=='20' and obligation['actual_paid']['value']['value']=='5'
            and not plan.action_input['offers'] and profile['monthly_capacity_observation_ref']==plan.observation_ref.model_dump(mode='json'),'Declared complete current treasury was changed or replaced by normalized native capacity')
        require(observation['actual_financing_index']['value']==str(current) and observation['actual_financing_index']['unit']=='index'
            and observation['independent_watch_threshold']['value']=='0.95' and observation['independent_watch_threshold']['unit']=='index'
            and observation['private_portfolio_coverage']=='complete_declared_synthetic_initial_portfolio','Actual index/independent risk rule changed')
        methods=micro['audit']['method_calls'];require(len(methods)==1 and methods[0]['method_ref']['id']=='micro.owner.financing_cash_calendar'
            and methods[0]['result']['kind']=='ok' and methods[0]['registry_digest']==identity.versions['method'],'Original A05 cash method was replaced')
        cash_input=CashCalendarInput.model_validate(methods[0]['input']);cash_report=check_cash_calendar(cash_input)
        minimum=min(Fraction(p.available.numerator,p.available.denominator) for p in cash_report.checkpoints)
        require(cash_report.model_dump(mode='json')==methods[0]['result']['value'] and minimum==(-15 if shortfall else 55)
            and cash_report.feasible is (not shortfall) and cash_input.accounts[0].opening_available.value==('20' if shortfall else '90')
            and len(cash_input.inflows)==1 and cash_input.inflows[0].amount.value=='100' and cash_input.inflows[0].time.offset==10
            and len(cash_input.existing_outflows)==1 and cash_input.existing_outflows[0].amount.value=='15' and cash_input.existing_outflows[0].time.offset==4
            and len(cash_input.proposed_outflows)==1 and cash_input.proposed_outflows[0].amount.value=='20' and cash_input.proposed_outflows[0].time.offset==2,
            'Original cash calendar erased an obligation, spent restricted/forecast money, or credited a future release too early')
        history=observed['prior_own_monthly_outcomes'];require(len(history)==tick-1,'Earlier actual own review missing')
        for h in history:
            previous=one(proofs,lambda p:p['actual_event']['event_id']==h['event_id'],'Earlier actual proof missing');event=previous['actual_event']
            require(h['source_event_sha256']==task_digest(event) and h['micro_identity']==previous['identity'] and h['micro_result_sha256']==previous['micro_result_sha256']
                and h['operation']==event['data']['operation']=='review_financing_capacity' and h['tick']==event['tick']<tick and event['agent_id']==identity.organization_id
                and h['participated'] is True and h['review']==previous['judgment'] and h['review_sha256']==task_digest(previous['judgment']),
                'Later micro review differs from the earlier actually executed own review')
        previous=None if not history else history[-1]['review'];watch=shortfall or environment
        require(judgment.original_choice==('no_finance' if shortfall else 'own_funds') and judgment.cash_feasible is (not shortfall)
            and judgment.minimum_available==str(minimum) and judgment.currency=='HKD' and judgment.actual_financing_index.model_dump(mode='json')==observation['actual_financing_index']
            and judgment.environment_watch is environment and judgment.environment_watch is (current<Decimal('0.95')) and judgment.financing_watch is watch
            and judgment.prior_review_count==len(history) and judgment.previous_minimum_available==(None if previous is None else previous['minimum_available'])
            and judgment.change_in_minimum_available==(None if previous is None else '0') and judgment.previous_environment_index==(None if previous is None else previous['actual_financing_index']['value'])
            and judgment.change_in_environment_index==(None if previous is None else str(current-Decimal(previous['actual_financing_index']['value'])))
            and judgment.monitoring_transition==(('initial_watch' if watch else 'initial_clear') if tick==1 else ('watch_continues' if watch else 'clear_continues'))
            and judgment.consumed_event_ids==[h['event_id'] for h in history] and judgment.consumed_review_sha256==[h['review_sha256'] for h in history],
            'Original review did not use cash constraints, actual environment risk or its executed prior baseline')
        proposal_task=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation' and t['output'].get('factors',{}).get('micro_task_key')==identity.key,'Original proposal missing')
        proposal=proposal_task['output'];transport=proposal_task['identity']
        require(transport['input_sha256']==task_digest({'run_id':transport['run_id'],'versions':transport['versions'],'request':record['native_request']}),'Durable actual transport request differs')
        final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['output'].get('data',{}).get('micro_task_key')==identity.key,'Original final missing')['output']
        event=one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==identity.organization_id and e['tick']==tick,'Actual review event missing')
        require(proposal['accepted'] is final['decision'] is event['data']['decision_accepted'] is True and proposal['action_type']==final['action_type']==event['data']['operation']=='review_financing_capacity'
            and proposal['factors']['micro_result_sha256']==micro['result_sha256']==final['data']['micro_result_sha256']
            and record['proposal_response_sha256']==task_digest(proposal)==final['data']['proposal_response_sha256']
            and event['description']==proposal['data']['description']==judgment.interpretation and event['data']['decision_source']=='llm_agent','Original macro did not actually process this review')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==identity.organization_id,'Native owner missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='review_financing_capacity','Actual review memory missing')
        require(memory['label']==event['data']['label'] and memory['decision_factors']==event['data']['decision_factors'],'Actual memory differs')
        feedback=one(read(directory/'runtime/observations.json')['records'],lambda o:o['event_id']==event['event_id'] and o['organization_id']==identity.organization_id,'Actual committed own feedback missing')
        require(feedback['payload']['committed'] is True and feedback['payload']['data']['operation']=='review_financing_capacity' and feedback['payload']['data']['description']==event['description'],'Committed feedback differs')
        financial_snapshots.append({k:deepcopy(source(k)) for k in ('Account','FundingSource','Debt','Obligation')})
        proofs.append({'identity':identity.as_dict(),'scope':record['scope'],'judgment':judgment.model_dump(mode='json'),'micro_result_sha256':micro['result_sha256'],
            'original_result':micro['result'],'original_cash_method':methods[0],'original_proposal':proposal,'original_proposal_task_identity':transport,'original_final':final,
            'actual_event':event,'actual_native_memory':memory,'original_committed_feedback':feedback,'consumed_own_history':history})
    def timeless(value):
        if isinstance(value,list):return [timeless(v) for v in value]
        if isinstance(value,dict):return {k:timeless(v) for k,v in value.items() if k not in ('version','as_of')}
        return value
    require(timeless(financial_snapshots[0])==timeless(financial_snapshots[1]),'Monthly review mutated private money/debt/obligation state')
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Read-only validation changed the task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'actual_reviews':2,'later_actual_review_consumers':1,'database_sha256':before,'independent_initial_policy':policy,'private_financial_state_unchanged':True}


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config);macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro source changed')
    cases={name:verify_scenario(directory/name,name=name) for name in config['scenarios']}
    def normalized(value,name):return json.dumps(value,sort_keys=True,ensure_ascii=False).replace(config['run_id']+'-'+name,'SAME_RUN')
    macro_inputs={name:read(directory/name/'input/macro-request.json') for name in cases}
    for name,value in macro_inputs.items():require(value['macro_environment'].pop('financing_condition_index')==config['scenarios'][name]['financing_condition_index'],'Original configured control changed')
    require(len({normalized(value,name) for name,value in macro_inputs.items()})==1,'Original macro inputs differ beyond the financing-index control')
    plans={name:read(directory/name/'input/owner-monthly-capacity-input.json') for name in cases}
    require(normalized(plans['normal'],'normal')==normalized(plans['environment_watch'],'environment_watch'),'Environment control changed private money or policy')
    for name,document in plans.items():
        for plan in document['plans']:
            for row in plan['objects']:
                if row['ref']['kind'] in {'Account','FundingSource'}:row['value']['actual_cash']['value']['value']='CONTROLLED_CASH'
                if row['ref']['kind']=='Evidence' and row['value']['basis_kind']=='assumed':
                    require(row['value']['content_hash']==task_digest(cases[name]['independent_initial_policy']),'Private declaration digest changed');row['value']['content_hash']='CONTROLLED_DECLARATION'
    require(len({normalized(value,name) for name,value in plans.items()})==1,'Private controls changed more than declared actual opening cash')
    return {'status':'passed','macro':macro,'cases':cases,'controlled_difference':'Original initial financing index 1.2/0.7 with identical treasury; separate declared initial actual cash 100/30 HKD with identical original macro inputs',
        'actual_reviews':6,'later_actual_review_consumers':3,'boundary':BOUNDARY,'scope':'Owner.review_financing_capacity only; native no_finance selection and formal money interfaces remain blocked'}


def write_delivery(directory,checks):
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_capacity --config config/owner_monthly_capacity_chain.json --output $OutputDirectory\n",encoding='utf-8')
    lines=['# GOAL 3B 业主月度融资容量复核实跑记录','','原 OWN-A05 现金日历 → 原月度复核实际执行 → 后轮原 A05 读取同一已执行复核并计算变化与监测状态。','',
        '| 场景 | 月 | 实际融资指数 | 原 A05 | 日历最低余量 HKD | 风险监测 | 实际事件 | 消费前轮事件 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name,case in checks['cases'].items():
        for p in case['proofs']:
            j=p['judgment'];lines.append(f"| {name} | {p['scope']['tick']} | {j['actual_financing_index']['value']} | {j['original_choice']} | {j['minimum_available']} | {j['monitoring_transition']} | {p['actual_event']['event_id']} | {', '.join(j['consumed_event_ids']) or '无'} |")
    lines+=['','三组各 6 个技术任务，共 18 个任务全部形成结果；6 次原宏观 review_financing_capacity，3 次后轮真实复核消费。',
        '独立初始私有数据：现金 100 / 30 HKD，受限现金 10，旧债本金 15，原义务 20 已付 5，剩余 15；拟议用途 20，未来第 10 月获独立批准的非银行释放 100。原 A05 先扣除受限现金，再按第 2 月拟议用途和第 4 月既有义务计算余额，不能提前使用未来释放，1000 的预测可用额也不作实际现金。最低余额分别为 55 / -15。',
        '原请求的实际融资指数与独立 0.95 index 风险阈值比较；相同现金在低指数组仍可覆盖计划，但需要环境风险监测。现金不足组保留原 A05 的 no_finance，不冒充可自筹资金。三组完成的是月度分析，故原宏观均实际执行复核；没有提交融资选择、资金或债务执行。',
        '后轮只读同机构、严格较早、真实原月度执行所对应的同一 A05 复核，计算最低余额差、环境指数差与 clear_continues/watch_continues。私有资金、旧债和义务保持不变。','',
        '新目录运行：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_capacity `",'  --config config/owner_monthly_capacity_chain.json `','  --output output/integration/goal3b_owner_capacity_my_run','```','',
        '只读核验本次归档：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.verify_owner_monthly_capacity --check-only --output '{directory.as_posix()}'",'```','',
        '完整输入、源读取、现金计算审计、原提案、最终决定、真实事件、记忆、已提交反馈和后轮对应关系见 checks.json 与各组 runtime。声明的历史贷款与批准来自合成初始资料，不冒充当前原宏观新签约或到账。',
        '本批只增加业主月度融资容量复核；月度累计 21/32，仍有 11 项月度动作、47 项来源或接口阻塞。no_finance 的正式融资选择接口、正式贷款登记、提款和资金执行等原阻塞继续保留。GOAL 3 和原 PLAN 未全部完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    names=['integration/owner_monthly_capacity.py','integration/owner_monthly_capacity_development.py','integration/verify_owner_monthly_capacity.py',
        'src/actions/contracts/owner_monthly_capacity.py','src/actions/roles/owner_monthly_capacity.py','src/actions/contracts/owner_financing_objects.py','src/actions/roles/owner_financing.py',
        'src/methods/owner_financing.py','src/methods/owner_investment.py','integration/professional_monthly_native.py',
        'tests/test_owner_monthly_capacity.py','tests/fixtures/roles/owner_financing.v1.json','config/owner_monthly_capacity_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
        'docs/业主月度融资容量复核接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'owner-monthly-capacity-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/owner_monthly_capacity_chain.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile);run_existing_input(directory/name,assembly_hook='integration.owner_monthly_capacity:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
