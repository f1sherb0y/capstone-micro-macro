"""Reuse saved long-chain checks and export the two demonstrations without replay."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

from integration.dual_lifecycle_case import read, execution_contexts, verify_inputs
from integration.contractor_tender_development import _write
from integration.verify_goal4_integration import verify_tender, journal
from integration.verify_goal3_minimal_native_fix import macro_snapshot, save_or_match
from src.coordination.tasks import task_digest


def normalized_host(path):
    host = execution_contexts(read(path), 'rule')
    source = host['settings']['tender']['settings']['source_settings']
    for key in ['snapshots', 'quantity_snapshots']:
        source[key] = execution_contexts(read(source[key]['snapshot_path']), 'rule')
    app = source['application_settings']['owner_contractor']['contractor']
    app['model_host_factory'] = None
    app['model_host_settings'] = None
    return host


def verify_mode(directory, mode):
    folder = Path(directory) / mode
    proof = verify_tender(folder)
    result = read(folder/'runtime/result.json')
    host = result['module_host_extension']['host']
    project, = result['simulation']['project_results']
    tasks, metadata, workers, db_sha = journal(folder)
    calls = []
    quotes = []
    events = host['original_global_events']
    for key, worker in workers.items():
        if worker['identity']['action_id'] != 'CONTRACTOR-A02':
            continue
        payload = worker['result']['payload']
        if payload['choice'] != 'submit_bid':
            continue
        org = worker['identity']['organization_id']
        native, = [e for e in events if e['event_type'] == 'bid_submitted' and e['agent_id'] == org]
        assert native['data']['decision_factors']['micro_result_sha256'] == worker['result_sha256']
        price = payload['bid']['price']['value']
        assert Decimal(str(native['data']['bid_price'])) == Decimal(price)
        quotes.append({'organization_id': org, 'micro_task_key': key,
            'micro_result_sha256': worker['result_sha256'], 'price_HKD': price,
            'native_event_id': native['event_id'], 'native_event_sha256': task_digest(native)})
        execution = worker['audit'].get('decision', {}).get('execution', {})
        if execution.get('model_calls', 0):
            assert mode == 'model' and execution['status'] == 'selected'
            calls.append({**quotes[-1], 'execution': execution})
    budget = host['tender']['model_host']['call_budget'] if mode == 'model' else None
    if mode == 'model':
        assert len(calls) == 2 and sum(c['execution']['model_calls'] for c in calls) == 2
        assert budget['charged_or_reserved_calls'] == 2 and budget['max_calls'] <= 4
    else:
        assert not calls and host['tender']['model_host'] is None
    usage = {name: sum(c['execution'].get('usage_metadata', {}).get(name, 0) for c in calls)
        for name in ['input_tokens', 'output_tokens', 'total_tokens']}
    settlement, = [e for e in events if e['event_type'] == 'final_account_settled']
    output = {'status': 'passed', 'mode': mode, 'simulation_id': result['simulation']['simulation_id'],
        'ticks': result['simulation']['current_tick'], 'final_stage': project['current_stage'],
        'selected_contractor_id': project['selected_contractor_id'],
        'contract_sum': project['contract_sum'], 'contracts': project['contracts'],
        'bid_effects': quotes, 'settlement': settlement,
        'later_owner_consumers': proof['later_owner_consumers'],
        'model_calls': calls, 'call_budget': budget, 'usage_metadata': usage,
        'technical_tasks': len(tasks), 'journal_sha256': db_sha,
        'validation_only_diagnostics': proof['native_pre_signature_diagnostics'],
        'boundary': 'Only A02 pricing selection uses the live model. Later Owner A03 applies an existing rule to actual settlement. Native ranking, aggregate work and settlement remain native; cash clearance is not proven.'}
    save_or_match(folder, 'chain-checks.json', proof)
    save_or_match(folder, 'case-summary.json', output)
    return output


def verify_pair(directory):
    directory = Path(directory).resolve()
    verify_inputs(directory)
    assert normalized_host(directory/'offline/input/assembly-host.json') == normalized_host(
        directory/'model/input/assembly-host.json'), 'Business inputs differ after normalizing execution configuration'
    offline_native = read(directory/'offline/input/native-host.json')
    model_native = read(directory/'model/input/native-host.json')
    assert offline_native['settings'] == model_native['settings']['native']
    current_macro = macro_snapshot()
    baseline = read(directory/'macro-before.json')
    assert current_macro == baseline, 'Macro source changed during this case'
    cases = {mode: verify_mode(directory, mode) for mode in ['offline', 'model']}
    report = {'status': 'passed', 'initial_business_inputs_equal': True,
        'shared_macro_request_sha256': task_digest(read(directory/'offline/input/macro-request.json')),
        'macro_unchanged': {'all_files': len(current_macro['files']),
            'python_sources': len(current_macro['python_sources']), 'snapshot_sha256': task_digest(current_macro)},
        'cases': cases,
        'comparison_boundary': 'One paired engineering demonstration; no strategy superiority, repeated-trial statistics or all-action LLM coverage claim.'}
    save_or_match(directory, 'pair-checks.json', report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', required=True, type=Path)
    p.add_argument('--mode', choices=['offline', 'model'])
    args = p.parse_args(argv)
    result = verify_mode(args.directory, args.mode) if args.mode else verify_pair(args.directory)
    print(json.dumps({'status': result['status'], 'mode': args.mode or 'pair'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
