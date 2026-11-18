"""Fixed Contractor monthly A01 screening, native execution and later own consumption."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.contractor_monthly_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input,verify_scenario
from integration.contractor_tender_development import _write
from integration.verify_tender_closed_loop import ROOT,read,require,macro_hashes

OPERATION='scan_tender_opportunities'
REMAINING={
    'adjust_bid_strategy':{'existing_micro_contact':'Original CONTRACTOR-A02 evaluates a scoped bid and its declared pricing/cost policy; it is not an organization-wide strategy publisher.',
        'missing':['authorized_current_firm_bid_strategy_candidates_and_policy_version','appropriate_firm_scope_micro_strategy_judgment','authentic_strategy_publication_and_later_bid_consumer']},
    'evaluate_region_entry':{'existing_micro_contact':'Original CONTRACTOR-A01 checks scoped package qualifications, region, work method and resources; one public package is not a complete regional-entry dossier.',
        'missing':['authorized_region_entry_target_and_qualification_regulatory_scope','independent_region_cost_commitment_and_collaboration_basis','scoped_micro_entry_judgment_and_actual_result_consumer']},
    'seek_joint_venture_partner':{'existing_micro_contact':'Existing commercial/advice processors require explicit counterpart authority and obligations; no suitable partner set is supplied by this monthly request.',
        'missing':['authorized_current_partner_targets_and_shared_scope','independent_counterparty_consent_capacity_and_commercial_sources','actual_partner_outreach_and_own_feedback_consumer']},
    'maintain_supplier_relationship':{'existing_micro_contact':'Existing procurement CONTRACTOR-A05 selects an actual supplier for a particular order; this does not prove relationship maintenance.',
        'missing':['actual_authorized_supplier_relationship_and_task_targets','independent_current_contact_terms_and_remaining_obligations','scoped_micro_maintenance_judgment_and_authentic_contact_outcome']}}


def validate_config(config):
    require(config['schema_version']=='contractor-monthly-chain.v1' and config['ticks']==2
        and config['scenarios']=={'high':{'market_demand_index':1.2},'low':{'market_demand_index':0.6}},'Unsupported fixed monthly cases')


def collect_checks(directory):
    config=read(directory/'source-config.json');validate_config(config)
    cases={name:verify_scenario(directory/name,participates=name=='high',role_operations={'Contractor':OPERATION},
        worker_tables={'Contractor':'contractor_screening_results'},expected_records=4,participation_choice='participate') for name in config['scenarios']}
    for case in cases.values():
        case.pop('remaining_professional_monthly_subactions',None)
        case['status']='actual_original_contractor_monthly_screening_native_execution_and_own_feedback_verified'
        case['remaining_contractor_monthly_subactions']=4
    for name,case in cases.items():
        database=directory/name/'runtime/tasks.sqlite'
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            originals=[json.loads(v) for v, in db.execute('SELECT record FROM contractor_screening_results')]
        capacity=[]
        for saved in originals:
            calls=[c for c in saved['audit']['method_calls'] if c['method_ref']['id']=='micro.capacity.fixed_location']
            require(len(calls)==1 and calls[0]['result']['kind']=='ok' and calls[0]['result']['value']['feasible'] is True
                and calls[0]['input']['commitments'],'Original capacity checks or nonempty disclosed commitments were bypassed')
            capacity.append({'identity':saved['identity'],'original_capacity_method_call':calls[0]})
        case['original_capacity_calculations']=capacity
    high=read(directory/'high/input/macro-request.json');low=read(directory/'low/input/macro-request.json')
    high['macro_environment']['market_demand_index']=low['macro_environment']['market_demand_index']
    require(high==low,'Controlled original macro cases differ beyond initial market demand')
    macro=macro_hashes();require(macro==read(directory/'macro-before.json'),'Frozen macro changed')
    return {'batch':'3A-monthly','status':'contractor_monthly_screening_verified_four_other_monthly_actions_blocked','cases':cases,
        'contact':{'role':'Contractor','operation':OPERATION,'macro_input':'Actual current monthly macro_environment and strictly earlier own micro-origin monthly outcomes',
            'micro_handler':'integration.contractor_monthly_native:ContractorMonthlyApplication','original_micro_action':'CONTRACTOR-A01',
            'micro_processing':'Original qualification, work-method, physical resource/commitment capacity and private policy checks; optional sourced demand/own-outreach constraint runs inside the original A01 processor',
            'return_to_macro':'Legal original candidate proposal then original final decision carries actual A01 participate/decline; original scheduler executes scan or maintain_operations',
            'feedback_consumer':'Later own original A01 consumes exact earlier original monthly event and counts actual scan, excluding maintenance and other organizations'},
        'blocked_monthly_contacts':REMAINING,'macro':macro,'overall_goal3_complete':False,
        'boundary':'Independent synthetic public package and private capability/qualification/nonempty commitment disclosures; no actual invitation, bid, appointment, new physical commitment, firm strategy publication, regional entry, partner or supplier relationship is proved. Native normalized capability mechanics remain original.'}


def write_delivery(directory,checks):
    _write(directory,'monthly-contacts.json',{'batch':'3A-monthly','executed_contact':checks['contact'],'blocked_contacts':REMAINING,'overall_goal3_complete':False})
    lines=['# GOAL 3A 承包商月度投标业务补接','',
        '原 CONTRACTOR-A01 已接原 scan_tender_opportunities。原月度传输及反馈校验复用专业月度组件，不重写已有投标流程；其余四项承包商月度动作仍阻塞。','',
        '| 原期初需求指数 | 原 tick 1 | 原 tick 2 |','| --- | --- | --- |',
        '| 1.2 | 两家 A01 完成资格、方法、容量及约束判断，各 participate；原宏观实际扫描 | 各自读取本机构较早实际扫描事件，次数 1 达阈值，原 A01 decline；原宏观实际 maintain_operations |',
        '| 0.6 | 两家 A01 均因实际需求低于私有阈值 1 而 decline；原维护 | 各自消费较早维护事件，实际扫描次数保持 0，需求仍不足，继续原维护 |','',
        '两组原 SimulationCreateRequest 除初始 macro_environment.market_demand_index 外逐字段一致，同种子 42。指数由原宏观更新后交原 A01 的 OutreachObservation，独立策略 minimum=1、maximum_prior_outreach=1 固定在启动前；没有适配器预填决定或篡改正式状态。',
        '原正向候选提案 accepted=True 仅满足原接口候选契约；真正参加/拒绝由同一原 A01 结果经原最终接口交回，并与实际 agent_operation 对应，不把候选算已执行。后轮按本运行、本机构、本入口严格较早的原结果计数，维护不增加扫描次数。',
        '源码层保留非空独立既有承诺披露：原两单位 crew 容量、已有一单位承诺及一单位需求交原容量方法，不从宏观 normalized scalar 推导物理库存。公开招标包档案、资格和当前披露均为明确的初始合成假设，不是实际邀请或投标收件。',
        '新目录启动：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_contractor_monthly_chain `",
        '  --config config/contractor_monthly_chain.json `','  --output output/integration/goal3a_monthly_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_contractor_monthly_chain --check-only --output '{directory.as_posix()}'",'```','',
        f"两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个原技术任务全部 output_formed；8 个原 A01 决定、2 次实际扫描、6 次实际维护；第二轮四项原 A01 消费本机构原事件。",
        '独立期初待汇总结算项目只用于原引擎自然推进两时点，不计从零投标履约或清债。未发布投标或注册新的占用。原随机能力标量变化仍归宏观机制。',
        'monthly-contacts.json 为本批一项执行和四项具体阻塞定位，checks.json 保存原微观输入/结果、提案、最终响应、实际事件及后轮消费；runtime/ 保留原任务库和原进程输出。',
        f"宏观 {checks['macro']['file_count']} 文件基线及全部宏观 Python 未改。当前累计月度覆盖为 7/32，25 项仍未接通；GOAL 3 与原 PLAN 均未完成。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/contractor_monthly_native.py','integration/contractor_monthly_development.py','integration/verify_contractor_monthly_chain.py',
        'integration/professional_monthly_native.py','integration/verify_professional_monthly_chain.py','integration/contractor_screening_actions.py',
        'src/actions/contracts/contractor_objects.py','src/actions/roles/contractor.py','src/actions/roles/professional_outreach.py',
        'config/contractor_monthly_chain.json','config/gba_v1_business_wiring.json','config/gba_v1_monthly_business_wiring.json',
        'docs/承包商月度投标业务接线与验收.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'contractor-monthly-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path,default=ROOT/'config/contractor_monthly_chain.json');p.add_argument('--check-only',action='store_true');a=p.parse_args(argv);directory=a.output.resolve()
    if not a.check_only:
        config=read(a.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,**profile,ticks=config['ticks'])
            run_existing_input(directory/name,assembly_hook='integration.contractor_monthly_native:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks=collect_checks(directory)
    if not a.check_only:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'macro_unchanged_files':checks['macro']['file_count'],'output':str(directory)}))


if __name__=='__main__':main()
