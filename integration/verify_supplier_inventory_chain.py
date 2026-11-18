"""Run original inventory planning and later consumption of actual supply results."""
import argparse
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sqlite3
from integration.supplier_inventory_development import build_bundle, HOOK
from integration.supplier_monthly_inventory import InventoryPlan, bind_sources, result_judgment
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes, _write, verify_bundle
from src.coordination.tasks import TaskIdentity, task_digest


def verify_case(directory):
    for manifest in (directory/'input').rglob('input-manifest.json'): verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code'] == 0, 'Original inventory process failed')
    initial = read(directory/'input/macro-request.json')
    output = read(directory/'runtime/result.json'); simulation = output['simulation']; host = output['module_host_extension']['host']
    monthly = host.get('monthly', host); records = monthly['requests']; events = monthly['original_global_events']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == initial['ticks'], 'Inventory window incomplete')
    require(not any(e['data'].get('agent_observer_errors') for e in events), 'Original observer failed')
    database = directory/'runtime/tasks.sqlite'; before = file_hash(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        workers = [json.loads(v) for v, in db.execute('SELECT record FROM supplier_planning_results')]
        snapshots = {k: json.loads(v) for k, v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
        metadata = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM metadata')}
    require(all(t['state'] == 'output_formed' and t['output_sha256'] == task_digest(t['output']) for t in tasks), 'Task unresolved or changed')
    saved = {TaskIdentity(**w['identity']).key: w for w in workers}
    taskmap = {TaskIdentity(**t['identity']).key: t for t in tasks}
    plans = read(directory/'input/inventory-input.json')['plans']; proofs = []
    require(len(plans) == len(records) == len(workers), 'Missing original inventory A05 invocation')
    for r in sorted(records, key=lambda r: (r['scope']['tick'], r['scope']['organization_id'])):
        digest_valid(r); i = TaskIdentity(**r['identity']); w = saved[i.key]; digest_valid(w)
        snapshot = snapshots[i.key]; digest_valid(snapshot, 'snapshot_sha256')
        j = result_judgment(w); org, tick = r['scope']['organization_id'], r['scope']['tick']
        p = InventoryPlan.model_validate(one(plans, lambda p: (p['organization_id'], p['tick']) == (org, tick), 'Missing initial plan'))
        require(r == metadata[r['key']] and r['state'] == 'formed' and r['identity'] == w['identity']
            and i.action_id == 'SUPPLIER-A05' and i.organization_id == org
            and w['result_sha256'] == task_digest(w['result']) == r['result_sha256']
            and w['source_reading_sha256'] == task_digest(w['source_reading']) and taskmap[i.key]['output'] == w['result']
            and i.context_sha256 == task_digest(snapshot['context']) and i.input_sha256 == task_digest(snapshot['action_input'])
            and snapshot['context'] == r['context'] == p.context.model_dump(mode='json')
            and snapshot['action_input'] == {'scope_ref': p.context.scope.model_dump(mode='json'), **p.action_input}, 'Original action identities/results changed')
        def source(kind): return one(w['source_reading'], lambda x: x['ref']['kind'] == kind, 'Missing '+kind)['projection']
        observed = r['observed']; obs = source('SupplierInventoryObservation'); policy = source('SupplierInventoryPolicy')
        objects = bind_sources(p, observed)
        require(task_digest(objects) == r['source_sha256'] and one(objects, lambda x: x['ref'] == p.observation_ref.model_dump(mode='json'), 'Missing observation')['value'] == obs
            and any(x['ref']['kind'] == 'Evidence' and x['projection'].get('content_hash') == task_digest(observed) for x in w['source_reading']), 'Actual original source binding changed')
        request = r['native_request']; agent = request['agent']; profile = observed['native_profile']
        require(observed['native_request_sha256'] == task_digest(request) and observed['scope'] == r['scope']
            and observed['macro_environment'] == request['inputs']['macro_environment']
            and profile['available_resource'] == agent['resources']['available_resource']
            and profile['total_resource_capacity'] == agent['resources']['total_resource_capacity']
            and profile['free_ratio'] == profile['available_resource']/profile['total_resource_capacity'], 'Native input origin changed')
        require(source('InventorySnapshot')['coverage'] == 'unknown' and source('InventorySnapshot')['lots'] == []
            and source('SupplierCapacity')['resource_coverage'] == source('SupplierCapacity')['commitment_coverage'] == 'unknown'
            and source('SupplyWorkAuthorization')['order_ref'] is None and source('StockingAuthority')['risk_bearer_id'] == org,
            'Native aggregates promoted into physical inventory or effective order')
        history = obs['prior_own_outcomes']; supply = obs['actual_supply_outcomes']
        require(history == observed['prior_own_monthly_outcomes'] and len(history) == tick-1
            and supply == observed['actual_supply_outcomes'], 'Actual earlier results omitted')
        for h in history:
            prior = saved[TaskIdentity(**h['micro_identity']).key]; prior_j = result_judgment(prior)
            e = one(events, lambda e: e['event_id'] == h['event_id'], 'Missing actual earlier monthly event')
            native_agent = one(simulation['agent_results'], lambda a: a['agent_id'] == org, 'Missing own native profile')
            require(e['agent_id'] == org and e['tick'] == h['tick'] < tick and task_digest(e) == h['source_event_sha256']
                and h['micro_identity'] == prior['identity'] and h['micro_result_sha256'] == prior['result_sha256']
                and h['review'] == prior_j.model_dump(mode='json') and h['backup_request'] == prior_j.current_backup_request
                and h['participated'] == prior_j.participate and h['operation'] == e['data']['operation']
                and h['original_native_memory'] == one(native_agent['episodic_memory'], lambda m: m.get('tick') == h['tick'] and m.get('operation') == h['operation'], 'Missing actual native memory'), 'Later monthly result is not exact own actual execution')
        for a in supply:
            digest_valid(a)
            require(a == metadata[a['key']] and a in host['supply_observations'] and a['organization_id'] == org
                and a['run_id'] == i.run_id and a['tick'] < tick, 'Supply source is not own original saved observation')
            e = one(events, lambda e: e['event_id'] == a['event_id'], 'Missing actual supply event')
            raw = deepcopy(e); raw['data'].pop('agent_observer_errors', None)
            project = one(simulation['project_results'], lambda p: p['project_id'] == a['project_id'], 'Missing supply project')
            require(task_digest(raw) == a['source_event_sha256'] and e['tick'] == a['tick'] and e['event_type'] == a['event_type']
                and org in project['selected_supplier_ids'] and a['formal_effects_created'] is False
                and any(task_digest(g) == a['engagement_sha256'] for g in project['engagements'] if g['agent_id'] == org), 'Supply observation lost actual native event or own selection')
            if a['event_type'] == 'supply_delay':
                require(round(a['native_state']['material_availability'], 3) == e['data']['material_availability'], 'Actual supply reduction differs')
            if a['event_type'] == 'construction_progress_updated':
                require(abs(a['native_state']['supply_delay_risk']-(1-a['native_supplier_profile_averages']['average_reliability'])) < 1e-9, 'Actual native reliability calculation differs')
        expected_supply = sorted([a for a in host.get('supply_observations', []) if a['organization_id'] == org and a['tick'] < tick], key=lambda a: (a['tick'], a['event_id'], a['project_id']))
        require(supply == expected_supply, 'A later micro reading omitted an eligible own actual supply result')
        index = Decimal(str(observed['macro_environment']['material_price_index']))
        gap = index-Decimal(policy['minimum_material_index']['value']); price = gap >= 0
        latest = {}
        for a in supply:
            if a['event_type'] != 'supplier_selected': latest[a['project_id']] = a
        risk = any(Decimal(str(a['native_state']['material_availability'])) < Decimal(policy['minimum_material_availability']['value'])
            or Decimal(str(a['native_state']['supply_delay_risk'])) > Decimal(policy['maximum_supply_delay_risk']['value']) for a in latest.values())
        count = sum(h['participated'] for h in history)
        participate = (price or risk) and Decimal(str(profile['free_ratio'])) >= Decimal(policy['minimum_free_ratio']['value']) and count < policy['maximum_prior_reviews']
        require(j.participate == participate and j.price_triggered == price and j.supply_risk_triggered == risk
            and Decimal(j.material_index_gap) == gap and j.prior_actual_review_count == count
            and j.consumed_event_ids == [h['event_id'] for h in history]+[a['event_id'] for a in supply]
            and j.consumed_micro_result_sha256 == [h['micro_result_sha256'] for h in history]
            and j.consumed_supply_record_sha256 == [a['record_sha256'] for a in supply], 'Independent planning decision or exact feedback oracle failed')
        proposal = one(tasks, lambda t: t['identity']['purpose'] == 'propose' and t['output'].get('factors', {}).get('micro_task_key') == i.key, 'Missing original proposal')['output']
        final = one(tasks, lambda t: t['identity']['purpose'] == 'decide' and t['output'].get('data', {}).get('micro_task_key') == i.key, 'Missing original final')['output']
        event = one(events, lambda e: e['event_type'] == 'agent_operation' and e['agent_id'] == org and e['tick'] == tick, 'Missing original actual operation')
        require(proposal['accepted'] is True and final['decision'] is event['data']['decision_accepted'] is participate
            and proposal['action_type'] == final['action_type'] == 'adjust_inventory'
            and event['data']['operation'] == ('adjust_inventory' if participate else 'maintain_operations')
            and final['data']['micro_result_sha256'] == proposal['factors']['micro_result_sha256'] == w['result_sha256']
            and task_digest(proposal) == r['proposal_response_sha256'] == final['data']['proposal_response_sha256'], 'Micro judgment not actually executed by original macro')
        proofs.append({'scope': r['scope'], 'identity': i.as_dict(), 'result_sha256': w['result_sha256'],
            'source_reading_sha256': w['source_reading_sha256'], 'observed': observed, 'judgment': j.model_dump(mode='json'),
            'original_proposal': proposal, 'original_final': final, 'actual_event': event})
    require(file_hash(database) == before, 'Read-only checks modified original journal')
    return {'technical_tasks': len(tasks), 'micro_inventory_actions': len(records), 'proofs': proofs, 'database_sha256': before}


def collect(directory):
    config = read(directory/'source-config.json')
    allowed = [read(ROOT/'config/supplier_inventory_chain.json'), read(ROOT/'config/supplier_supply_delay_chain.json')]
    require(config in allowed, 'Fixed scenario configuration changed')
    cases = {name: verify_case(directory/name) for name in config['scenarios']}
    if set(cases) == {'delay_feedback'}:
        proofs = cases['delay_feedback']['proofs']
        consumed = [p for p in proofs if any(r['event_type'] == 'supply_delay' for r in p['observed']['actual_supply_outcomes'])]
        require(consumed and all(p['judgment']['supply_risk_triggered'] for p in consumed),
            'Actual native supply_delay was not consumed by a later original micro judgment')
        current = macro_hashes(); require(current == read(directory/'macro-before.json'), 'Frozen macro changed')
        return {'batch': '3F-N07-delay', 'status': 'executed_actual_supply_delay_and_later_same_event_micro_consumption',
            'cases': cases, 'later_delay_consumers': len(consumed), 'macro_unchanged': current,
            'physical_stock_or_detailed_fulfillment_proved': False, 'overall_goal3_complete': False}
    high, low = cases['high_price']['proofs'], cases['low_price']['proofs']
    require(sum(p['judgment']['participate'] for p in high) == 2 and not any(p['judgment']['participate'] for p in low)
        and all(p['judgment']['prior_actual_review_count'] == 1 for p in high if p['scope']['tick'] == 2), 'Price effect or later suppression missing')
    for left, right, fields in [('high_price', 'low_price', ['material_price_index']), ('reliable_supply', 'weak_supply', [])]:
        a = read(directory/left/'input/macro-request.json'); b = read(directory/right/'input/macro-request.json')
        for k in fields: a['macro_environment'].pop(k); b['macro_environment'].pop(k)
        if not fields:
            for m in [a, b]:
                for agent in m['agents']:
                    if agent['role'] == 'Supplier': agent.pop('supply_reliability'); agent.pop('material_quality')
        require(a == b, 'Controlled native initial scenario changed unrelated fields')
    weak = cases['weak_supply']['proofs']; reliable = cases['reliable_supply']['proofs']
    require(any(p['judgment']['supply_risk_triggered'] and p['judgment']['participate'] for p in weak)
        and not any(p['judgment']['supply_risk_triggered'] for p in reliable)
        and all(not p['judgment']['price_triggered'] for p in weak+reliable), 'Actual supply feedback did not influence later micro judgment')
    current = macro_hashes(); require(current == read(directory/'macro-before.json'), 'Frozen macro changed')
    return {'batch': '3F-N04-N07', 'status': 'executed_monthly_inventory_planning_and_later_actual_supply_consumption',
        'cases': cases, 'macro_unchanged': current, 'physical_stock_or_detailed_fulfillment_proved': False, 'overall_goal3_complete': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT/'config/supplier_inventory_chain.json'); p.add_argument('--check-only', action='store_true')
    a = p.parse_args(argv); directory = a.output.resolve()
    if not a.check_only:
        config = read(a.config)
        require(config['schema_version'] == 'supplier-inventory-planning-chain.v1', 'Unsupported inventory scenario')
        directory.mkdir(parents=True, exist_ok=False); _write(directory, 'source-config.json', config); _write(directory, 'macro-before.json', macro_hashes())
        for name, options in config['scenarios'].items():
            print('Running original inventory/supply case '+name, flush=True)
            build_bundle(directory/name/'input', run_id=config['run_id']+'-'+name, **options)
            run_existing_input(directory/name, assembly_hook=HOOK)
    elif (directory/'artifact-manifest.json').exists(): verify_history(directory)
    checks = collect(directory)
    if not a.check_only:
        _write(directory, 'checks.json', checks)
        _write(directory, 'artifact-manifest.json', {'schema_version': 'supplier-inventory-chain-artifacts.v1',
            'files': {f.relative_to(directory).as_posix(): file_hash(f) for f in directory.rglob('*') if f.is_file()}})
    print(json.dumps({'status': checks['status'], 'cases': {k: {f: v for f, v in c.items() if f != 'proofs'} for k, c in checks['cases'].items()}}))


if __name__ == '__main__': main()
