"""Probe native stock-adjustment labels; never equate them with inventory effects."""
import argparse
import json
from pathlib import Path
import sqlite3

from integration.contractor_construction_source_review import _source
from integration.verify_procurement_chain import build_inputs, verify_scenario as verify_procurement
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, _write, macro_hashes, one, read, require
from src.coordination.tasks import task_digest


MISSING = [
    'actual_current_physical_stock_batches_allocations_orders_and_remaining_commitments',
    'authorized_stocking_target_risk_bearer_and_independent_cost_basis',
    'equivalent_original_stock_movement_issuer_and_current_query_binding',
    'original_A05_A06_decision_and_later_consumer_of_the_same_actual_stock_result',
]
BOUNDARY = ('Original native monthly activity and private procurement only. No monthly inventory '
    'micro judgment, physical ledger, reservation, production or stock movement is proved. '
    'A05 plans/requests and A06 inventory-query readers cannot issue stock. Missing original '
    'sources and equivalent issuer/query remain blockers; no new micro coverage is added.')
IMPLEMENTATIONS = [
    'integration/verify_supplier_inventory_sources.py', 'config/supplier_inventory_sources.json',
    'integration/verify_procurement_chain.py', 'integration/supplier_order_native_development.py',
    'integration/verify_professional_monthly_chain.py', 'integration/supplier_order_native.py',
    'src/actions/roles/supplier_planning.py', 'integration/supplier_inventory_reader.py',
    'integration/supplier_quote_inventory_source.py', 'src/coordination/supplier_inventory_conditions.py',
]


def validate_config(config):
    require(set(config) == {'schema_version', 'run_id', 'scenarios', 'source_note'}
        and config['schema_version'] == 'supplier-inventory-source-probe.v1'
        and isinstance(config['run_id'], str) and config['run_id'].strip()
        and config['scenarios'] == {'high': {'material_price_index': 1.3}, 'low': {'material_price_index': 0.8}}
        and isinstance(config['source_note'], str) and config['source_note'].strip(), 'Unsupported fixed inventory source probe')


def build_probe(directory, *, config, material_price_index):
    """Author supported initial inputs before running any original process."""
    directory.mkdir(parents=True, exist_ok=False)
    foundation = directory / 'foundation'
    hook = build_inputs(foundation, run_id=config['run_id'], options={'mode': 'supply', 'first_decline_stage': None})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    request = read(foundation / 'macro-request.json')
    request['macro_environment'] = {'material_price_index': material_price_index}
    request = SimulationCreateRequest.model_validate(request).model_dump(mode='json')
    _write(directory, 'macro-request.json', request)
    for name in ('native-host.json', 'assembly-host.json'):
        _write(directory, name, read(foundation / name))
    _write(directory, 'input-manifest.json', {'schema_version': 'integration-development-input.v1',
        'source_note': config['source_note'], 'files': {p.relative_to(directory).as_posix(): file_hash(p)
            for p in directory.rglob('*') if p.is_file()}})
    return hook


def inspect_case(directory, *, high):
    procurement = verify_procurement(directory, name='accepted_feedback')
    simulation = read(directory / 'runtime/result.json')['simulation']
    database = directory / 'runtime/tasks.sqlite'
    before = file_hash(database)
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        quotes = [json.loads(v) for v, in db.execute('SELECT record FROM supplier_quote_results')]
    require(not any(t['identity']['action_id'] in {'SUPPLIER-A05', 'SUPPLIER-A06'} for t in tasks),
        'Source probe now has actual planning/execution; inspect exact stock lineage instead')
    suppliers = {a['agent_id']: a for a in simulation['agent_results'] if a['role'] == 'Supplier'}
    proofs = []
    for feedback in read(directory / 'runtime/observations.json')['records']:
        payload = feedback['payload']; org = feedback['organization_id']
        if org not in suppliers or payload['event_type'] != 'agent_operation':
            continue
        tick = payload['tick']; operation = payload['data']['operation']
        proposal = one(tasks, lambda t: t['identity']['organization_id'] == org
            and t['identity']['purpose'] == 'propose'
            and t['identity']['request_id'] == f'proposal-tick{tick}-none-{org}-decide_monthly_operation', 'Original Supplier monthly proposal missing')
        final = one(tasks, lambda t: t['identity']['organization_id'] == org
            and t['identity']['purpose'] == 'decide'
            and t['identity']['request_id'] == f'tick{tick}-no_project-{org}-monthly_enterprise_operation', 'Original Supplier monthly final missing')
        memory = one(suppliers[org]['episodic_memory'], lambda m: m.get('tick') == tick
            and m.get('operation') == operation, 'Original Supplier monthly memory missing')
        require(proposal['identity']['run_id'] == final['identity']['run_id'] == feedback['run_id']
            and payload['committed'] is True and payload['agent_id'] == org
            and proposal['output']['accepted'] is True and final['output']['decision'] is True
            and proposal['output']['action_type'] == final['output']['action_type'] == operation
            and proposal['output']['factors']['decision_source'] == final['output']['data']['decision_source'] == 'native_macro'
            and not proposal['output']['factors'].get('micro_task_key'), 'Monthly route is no longer native-only')
        material_index = memory['decision_factors']['material_price_index']
        require((material_index > 1.05) == high and (operation == 'adjust_inventory') == high,
            'Original material threshold did not trigger the expected native activity')
        require(memory['label'] == payload['data']['label']
            and memory.get('capability_update') == payload['data'].get('capability_update'), 'Native monthly memory/feedback differ')
        proofs.append({'organization_id': org, 'tick': tick, 'event_id': feedback['event_id'],
            'observed_material_price_index': material_index, 'native_operation': operation,
            'original_proposal': proposal, 'original_final': final, 'committed_feedback': feedback,
            'feedback_sha256': task_digest(feedback), 'original_memory': memory,
            'actual_stock_effect_verified': False, 'counts_as_micro_coverage': False})
    require(len(proofs) == 4 and {p['organization_id'] for p in proofs} == {'supply-a', 'supply-b'},
        'Expected both own Suppliers over two original ticks')
    inventory_inputs = []
    for row in quotes:
        sources = {task_digest(s['ref']): s['projection'] for s in row['source_reading']}
        for s in row['source_reading']:
            if s['ref']['kind'] != 'InventorySnapshot':
                continue
            inventory = s['projection']
            evidence = [sources[task_digest(r)] for r in inventory['evidence_refs']]
            require(evidence and all(e['source_kind'] == 'synthetic' for e in evidence),
                'Inventory input now has another source; review actual ledger provenance separately')
            inventory_inputs.append({'identity': row['identity'], 'result_sha256': row['result_sha256'],
                'inventory': inventory, 'evidence': evidence, 'is_actual_stock_movement': False})
    require(len(inventory_inputs) == 4, 'Expected four original A03 declared inventory inputs')
    require(file_hash(database) == before, 'Read-only source inspection changed original journal')
    return {'status': 'native_source_probe_verified_inventory_wiring_still_blocked',
        'technical_tasks': procurement['technical_tasks'], 'original_procurement_actions': procurement['original_procurement_actions'],
        'original_procurement_verification': procurement, 'source_database_sha256': before,
        'native_only_monthly_proofs': proofs, 'synthetic_commercial_inventory_inputs': inventory_inputs,
        'monthly_stock_micro_invocations': 0, 'actual_stock_effect_verified': False}


def collect_checks(directory):
    config = read(directory / 'source-config.json'); validate_config(config)
    macro = macro_hashes(); require(macro == read(directory / 'macro-before.json'), 'Frozen macro changed during original runs')
    requests = []
    for name, profile in config['scenarios'].items():
        request = read(directory / name / 'input/macro-request.json')
        require(request['macro_environment']['material_price_index'] == profile['material_price_index'], 'Supported initial input difference changed')
        request['macro_environment']['material_price_index'] = 1
        requests.append(request)
    require(requests[0] == requests[1], 'Original requests differ beyond the supported initial material index')
    high = directory / 'high/input/foundation'; low = directory / 'low/input/foundation'
    for p in high.rglob('*.json'):
        other = low / p.relative_to(high)
        # Host paths differ only because original sources are independently located.
        if p.name == 'input-manifest.json':
            continue  # separately verified original byte manifests include path-dependent hosts
        def normalize(value, prefix):
            if isinstance(value, str):
                return value.replace(str(prefix.resolve()), '<foundation>')
            if isinstance(value, list):
                return [normalize(v, prefix) for v in value]
            if isinstance(value, dict):
                return {k: normalize(v, prefix) for k, v in value.items()}
            return value
        require(normalize(read(p), high) == normalize(read(other), low),
            'Private initial dossier differs between controlled cases: ' + p.name)
    cases = {name: inspect_case(directory / name, high=name == 'high') for name in config['scenarios']}
    backend = Path(macro['root']) / 'gba_construction_sim/backend'
    anchors = [_source(ROOT, (backend / path).as_posix(), symbol) for path, symbol in [
        ('agents/supplier_agent.py', 'SupplierAgent.decide_monthly_operation'),
        ('simulation/agent_operation_scheduler.py', 'AgentOperationScheduler.step'),
        ('models/agent.py', 'EnterpriseAgentProfile'),
    ]]
    anchors.extend(_source(ROOT, p, s) for p, s in [
        ('src/actions/roles/supplier_planning.py', 'plan_supply'),
        ('integration/supplier_inventory_reader.py', 'SupplierInventoryReader'),
        ('integration/supplier_quote_inventory_source.py', 'SupplierQuoteInventorySourceView'),
    ])
    return {'schema_version': 'supplier-inventory-source-inspection.v1', 'batch': '3F-Supplier-inventory-sources',
        'status': 'waiting_actual_stock_ledger_and_equivalent_issuer', 'macro': macro,
        'only_initial_macro_difference': 'SimulationCreateRequest.macro_environment.material_price_index',
        'cases': cases, 'source_anchors': anchors, 'missing': MISSING,
        'counts_as_micro_coverage': False, 'overall_goal3_complete': False, 'boundary': BOUNDARY}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/supplier_inventory_sources.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv); directory = args.output.resolve()
    require(directory.is_relative_to((ROOT / 'output/integration').resolve()), 'Output must remain in workspace integration artifacts')
    if args.check_only:
        verify_history(directory)
        require(all(file_hash(ROOT / p) == h for p, h in read(directory / 'artifact-manifest.json')['implementations'].items()), 'Current inventory probe differs from sealed implementation')
    else:
        config = read(args.config); validate_config(config)
        directory.mkdir(parents=True, exist_ok=False)
        _write(directory, 'source-config.json', config); _write(directory, 'macro-before.json', macro_hashes())
        for name, profile in config['scenarios'].items():
            hook = build_probe(directory / name / 'input', config=config, **profile)
            print('Running original Supplier source probe ' + name, flush=True)
            run_existing_input(directory / name, assembly_hook=hook)
    checks = collect_checks(directory)
    if args.check_only:
        require(checks == read(directory / 'checks.json'), 'Current original sources differ from saved inspection')
    else:
        _write(directory, 'checks.json', checks)
        with (directory / 'RUN_RECORD.md').open('x', encoding='utf-8') as stream:
            stream.write('# 3F 供应商库存来源实跑记录\n\n'
                '原生来源检查通过，库存接线仍阻塞，不新增覆盖。\n\n'
                '两个独立进程使用同一运行标识和相同私人初始资料；仅通过原 SimulationCreateRequest 的初始材料指数 1.3 / 0.8 构造差异。'
                '高组两个供应商两轮共四次实际执行 adjust_inventory；低组无该活动。原采购链验证器分别通过。\n\n'
                'checks.json 保存当前实际指数、原提议、最终决定、事件、自身记忆与完整采购验证。两组原 A03 库存输入均为声明的合成资料；没有原 A05/A06 库存微观任务。'
                '原月度调度器记录活动及自身随机归一化能力变化；未找到等价实物库存账本、库存变更接口及原查询。因此没有库存实效或后轮消费的证明。\n\n'
                '各组 command.json 是原 integration.run 命令；input、runtime、stdout、stderr、退出码与任务库均保留。'
                '固定入口：python -m integration.verify_supplier_inventory_sources --output output/integration/inventory_sources_new。'
                '复核本次：python -m integration.verify_supplier_inventory_sources --check-only --output ' + directory.relative_to(ROOT).as_posix() + '。\n\n'
                '宏观 174 个基线文件及全部 120 个 Python 源码未改。月度仍为 30/32，全清单 38 项阻塞；GOAL 3 及原 PLAN 未全部完成。\n')
        _write(directory, 'artifact-manifest.json', {'schema_version': 'supplier-inventory-source-artifacts.v1',
            'files': {p.relative_to(directory).as_posix(): file_hash(p) for p in directory.rglob('*') if p.is_file()},
            'implementations': {p: file_hash(ROOT / p) for p in IMPLEMENTATIONS}})
    print(json.dumps({'status': checks['status'], 'cases': {n: {'technical_tasks': c['technical_tasks'],
        'native_only_inventory_events': sum(p['native_operation'] == 'adjust_inventory' for p in c['native_only_monthly_proofs'])}
        for n, c in checks['cases'].items()}, 'counts_as_micro_coverage': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
