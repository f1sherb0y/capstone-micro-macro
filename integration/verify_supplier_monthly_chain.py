"""Fixed Supplier monthly A01, original native execution and later own consumption."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from integration.supplier_monthly_development import build_bundle
from integration.verify_professional_monthly_chain import run_existing_input, verify_scenario
from integration.contractor_tender_development import _write
from integration.verify_tender_closed_loop import ROOT, read, require, macro_hashes

OPERATION = 'seek_supply_contract'
REMAINING = {
    'adjust_inventory': {
        'existing_micro_contact': 'Original SUPPLIER-A05 planning accepts authorized order/speculative stocking sources. An A01 inquiry response is not a stock adjustment.',
        'missing': ['actual_current_stock_orders_allocations_and_remaining_commitments', 'authorized_stocking_target_and_risk_bearer_with_independent_cost_basis', 'appropriate_original_planning_judgment_actual_stock_effect_and_later_consumer']},
    'monitor_material_prices': {
        'existing_micro_contact': 'Original SUPPLIER-A01 track_market can retain a received observation; original A03 prices a scoped product proposal using independent cost sources. Neither is bound here to a monthly material-price monitoring/update task.',
        'missing': ['authorized_current_material_product_region_and_time_monitoring_scope', 'independent_visible_price_series_quote_or_cost_sources_with_units_and_versions', 'appropriate_monitoring_judgment_and_authentic_quote_update_consumer']},
    'improve_supply_reliability': {
        'existing_micro_contact': 'Original SUPPLIER-A05/A07/A08 require actual plan, quality and logistics sources. A monthly normalized capability increment does not prove physical backup or logistics improvement.',
        'missing': ['actual_current_supply_obligations_capacity_and_delivery_or_quality_history', 'authorized_backup_or_logistics_options_and_independent_cost_consent_basis', 'appropriate_micro_reliability_judgment_and_actual_execution_feedback']}}


def validate_config(config):
    require(config['schema_version'] == 'supplier-monthly-chain.v1' and config['ticks'] == 2
        and config['scenarios'] == {'high': {'market_demand_index': 1.2}, 'low': {'market_demand_index': 0.6}}, 'Unsupported fixed monthly cases')


def collect_checks(directory):
    config = read(directory/'source-config.json'); validate_config(config)
    cases = {name: verify_scenario(directory/name, participates=name == 'high', role_operations={'Supplier': OPERATION},
        worker_tables={'Supplier': 'supplier_screening_results'}, expected_records=4, participation_choice='respond', nonparticipation_choice='decline') for name in config['scenarios']}
    for name, case in cases.items():
        case.pop('remaining_professional_monthly_subactions', None)
        case.pop('formal_invitation_appointment_training_qualification_or_cost_database_effects_proven', None)
        case['status'] = 'actual_original_supplier_monthly_screening_execution_and_own_feedback_verified'
        case['formal_inquiry_receipt_quote_order_stock_or_physical_improvement_proven'] = False
        case['remaining_supplier_monthly_subactions'] = 3
        database = directory/name/'runtime/tasks.sqlite'
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
            originals = [json.loads(v) for v, in db.execute('SELECT record FROM supplier_screening_results')]
        capacity = []
        for saved in originals:
            calls = [c for c in saved['audit']['method_calls'] if c['method_ref']['id'] == 'micro.capacity.fixed_location']
            require(len(calls) == 1 and calls[0]['result']['kind'] == 'ok' and calls[0]['result']['value']['feasible'] is True
                and calls[0]['input']['commitments'], 'Original capacity check or nonempty independent commitments bypassed')
            capacity.append({'identity': saved['identity'], 'original_capacity_method_call': calls[0]})
        case['original_capacity_calculations'] = capacity
    high = read(directory/'high/input/macro-request.json'); low = read(directory/'low/input/macro-request.json')
    high['macro_environment']['market_demand_index'] = low['macro_environment']['market_demand_index']
    require(high == low, 'Controlled original macro cases differ beyond initial demand')
    private_cases = []
    for name in config['scenarios']:
        private = read(directory/name/'input/supplier-monthly-input.json')
        private.pop('run_id')
        for plan in private['plans']: plan['context'].pop('run_id')
        private_cases.append(private)
    require(private_cases[0] == private_cases[1], 'Controlled cases changed private policy or original screening sources')
    macro = macro_hashes(); require(macro == read(directory/'macro-before.json'), 'Frozen macro changed')
    return {'batch': '3E-monthly', 'status': 'supplier_monthly_screening_verified_three_other_monthly_actions_blocked', 'cases': cases,
        'contact': {'role': 'Supplier', 'operation': OPERATION,
            'macro_input': 'Actual current monthly macro_environment and strictly earlier own micro-origin monthly outcomes',
            'micro_handler': 'integration.supplier_monthly_native:SupplierMonthlyApplication', 'original_micro_action': 'SUPPLIER-A01',
            'micro_processing': 'Original exact inquiry/product/function/geography/work-method and shared physical capacity checks, then optional sourced demand/own-outreach constraint inside original A01',
            'return_to_macro': 'Legal original positive candidate proposal then original final decision carries actual A01 respond/decline; original scheduler executes seek_supply_contract or maintain_operations',
            'feedback_consumer': 'Later own original A01 reads exact earlier original monthly event; only actual contract-seeking counts toward its own outreach cap'},
        'blocked_monthly_contacts': REMAINING, 'macro': macro, 'overall_goal3_complete': False,
        'boundary': 'Independent initial synthetic inquiry and private product/method/physical capacity/nonempty commitment disclosures only. No actual macro inquiry receipt, quote, order, reservation, stock adjustment, price publication or physical reliability improvement. Original normalized scalar mechanics remain native.'}


def write_delivery(directory, checks):
    _write(directory, 'monthly-contacts.json', {'batch': checks['batch'], 'executed_contact': checks['contact'], 'blocked_contacts': REMAINING, 'overall_goal3_complete': False})
    lines = ['# GOAL 3E 供应商月度业务补接运行记录', '',
        '原 SUPPLIER-A01 已接原 seek_supply_contract，复用原月度传输及反馈校验组件；其余三项供应商月度动作仍阻塞。', '',
        '| 原期初需求指数 | 原 tick 1 | 原 tick 2 |', '| --- | --- | --- |',
        '| 1.2 | 两家原 A01 完成询价、产品、地域、方法、容量和约束检查，各 respond；原宏观实际 seek_supply_contract | 各自读取本机构较早实际经营事件，次数 1 达阈值；原 A01 decline，原宏观实际 maintain_operations |',
        '| 0.6 | 两家原 A01 因实际需求低于私有阈值 1 而 decline；原维护 | 消费本机构较早维护事件，实际拓客次数仍 0；需求不足，继续原维护 |', '',
        '两组原 SimulationCreateRequest 除期初 macro_environment.market_demand_index 外逐字段一致，同种子 42。指数经原宏观更新后进入原 A01 的 OutreachObservation；minimum=1、maximum_prior_outreach=1 是启动前声明的独立私有策略。适配器只绑定实际输入和事件，不预填微观选择。',
        '原容量方法使用 2 条生产线、1 条非空既有承诺以及 10 个 panel 在 [10,20) 的需求，全部 8 次实际计算通过。询价档案与物理数据均是独立初始合成假设，不是宏观正式询价回执，不由 normalized scalar 推导。',
        '原提案 accepted=True 只表示原接口允许的正向候选；最终决定携带原 A01 的 respond/decline，原调度器实际执行寻找合同或维护。后轮按本机构/本运行/本入口严格较早的真实原事件计数，维护不增加拓客次数。', '',
        '新目录启动：', '```powershell', "& '.venv-integration/Scripts/python.exe' -m integration.verify_supplier_monthly_chain `",
        '  --config config/supplier_monthly_chain.json `', '  --output output/integration/goal3e_monthly_my_run', '```', '',
        '只读核对：', '```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_supplier_monthly_chain --check-only --output '{directory.as_posix()}'", '```', '',
        f"两组共 {sum(c['technical_tasks'] for c in checks['cases'].values())} 个原技术任务全部 output_formed；8 个原 A01 决定、2 次实际寻求供货合同、6 次维护；第二轮四项原 A01 消费本机构原结果。",
        'monthly-contacts.json 定位本批一项执行与三项阻塞；checks.json 保存原输入、结果、提案、最终响应、实际事件、哈希及后轮消费对应关系。runtime/ 保留原任务库和进程输出。',
        '初始待汇总结算项目仅用于原引擎自然运行两时点，不计从零投标履约、详细结算或清偿。没有新增库存、报价、订单或实际生产/物流回执。',
        f"宏观 {checks['macro']['file_count']} 文件基线及全部宏观 Python 未改。累计月度覆盖 8/32，24 项未接通；GOAL 3 与原 PLAN 均未完成。", '']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines), encoding='utf-8')
    names = ['integration/supplier_monthly_native.py', 'integration/supplier_monthly_development.py', 'integration/verify_supplier_monthly_chain.py',
        'integration/examples/supplier_monthly_dossier.v1.json', 'integration/professional_monthly_native.py', 'integration/verify_professional_monthly_chain.py',
        'integration/supplier_screening_actions.py', 'src/actions/contracts/supplier_objects.py', 'src/actions/roles/supplier.py',
        'src/actions/contracts/professional_outreach.py', 'src/actions/roles/professional_outreach.py', 'config/supplier_monthly_chain.json',
        'config/gba_v1_business_wiring.json', 'config/gba_v1_monthly_business_wiring.json', 'docs/供应商月度业务接线与验收.md', 'docs/宏观动作接线清单.md']
    _write(directory, 'artifact-manifest.json', {'schema_version': 'supplier-monthly-artifacts.v1',
        'files': {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name != 'artifact-manifest.json'},
        'implementations': {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT/'config/supplier_monthly_chain.json'); p.add_argument('--check-only', action='store_true')
    a = p.parse_args(argv); directory = a.output.resolve()
    if not a.check_only:
        config = read(a.config); validate_config(config); directory.mkdir(parents=True, exist_ok=False)
        _write(directory, 'source-config.json', config); _write(directory, 'macro-before.json', macro_hashes())
        for name, profile in config['scenarios'].items():
            build_bundle(directory/name/'input', run_id=config['run_id']+'-'+name, **profile, ticks=config['ticks'])
            run_existing_input(directory/name, assembly_hook='integration.supplier_monthly_native:configure_assembly')
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks = collect_checks(directory)
    if not a.check_only: _write(directory, 'checks.json', checks); write_delivery(directory, checks)
    print(json.dumps({'status': checks['status'], 'macro_unchanged_files': checks['macro']['file_count'], 'output': str(directory)}))


if __name__ == '__main__': main()
