"""Run actual original construction and verify subsequent original A12 consumers."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.professional_construction_development import build_bundle
from integration.professional_methods_native import MonthlyMethodPlan, bind_sources, result_judgment, OPERATIONS, CAPABILITIES
from integration.professional_construction_feedback import BOUNDARY
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_closed_loop import read, require, one, digest_valid, macro_hashes
from integration.contractor_tender_development import _write, verify_bundle
from src.actions.roles.professional_construction_feedback import EVENT_TYPES
from src.coordination.tasks import TaskIdentity, task_digest


def verify(directory, *, macro_snapshot_reader=macro_hashes):
    config = read(directory / 'source-config.json'); case = directory / 'construction'
    require(any(config == read(Path(p)) for p in ('config/professional_construction_feedback_chain.json',
        'config/professional_safety_feedback_chain.json')), 'Fixed configuration changed')
    for manifest in (case / 'input').rglob('input-manifest.json'): verify_bundle(manifest.parent)
    require(read(case / 'exit.json')['exit_code'] == 0, 'Original construction process failed')
    require(macro_snapshot_reader() == read(directory / 'macro-before.json'), 'Macro changed during the recorded run')
    initial = read(case / 'input/macro-request.json'); output = read(case / 'runtime/result.json')
    simulation = output['simulation']; host = output['module_host_extension']['host']
    records = host['requests']; events = host['original_global_events']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == config['ticks'], 'Native window incomplete')
    require(host['initial_projects'] == initial['initial_projects'], 'Initial relationship snapshot changed during execution')
    require(not any(e['data'].get('agent_observer_errors') for e in events), 'Original observer failed')
    plans = read(case / 'input/professional-methods-input.json')['plans']
    database = case / 'runtime/tasks.sqlite'; database_sha = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM metadata')}
        micros = {TaskIdentity(**r['identity']).key: r for table in ('architect_learning_results', 'engineer_learning_results')
            for v, in db.execute('SELECT record FROM ' + table) for r in [json.loads(v)]}
    require(len(records) == 2 * config['ticks'] and all(t['state'] == 'output_formed'
        and t['output_sha256'] == task_digest(t['output']) for t in tasks), 'Original tasks or monthly judgments incomplete')
    proofs = []; consumed_types = set(); actual_improvement_followups = 0
    for record in records:
        digest_valid(record); require(metadata[record['key']] == record and record['state'] == 'formed', 'Durable record changed')
        identity = TaskIdentity(**record['identity']); micro = micros[identity.key]; digest_valid(micro)
        tick = record['scope']['tick']; org = identity.organization_id; role = identity.role; observed = record['observed']
        plan = MonthlyMethodPlan.model_validate(one(plans, lambda p: p['organization_id'] == org and p['tick'] == tick, 'Own plan missing'))
        require(micro['result_sha256'] == record['result_sha256'] == task_digest(micro['result'])
            and micro['source_reading_sha256'] == task_digest(micro['source_reading'])
            and identity.action_id == role.upper() + '-A12' and identity.run_id == config['run_id'], 'Micro identity/result changed')
        require(record['context'] == plan.context.model_dump(mode='json') and record['action_input'] == plan.action_input,
            'Original A12 invocation changed')
        expected = []
        field = {'Architect': 'selected_architect_id', 'Engineer': 'selected_engineer_id'}[role]
        for project in initial['initial_projects']:
            if project[field] != org: continue
            for event in events:
                if event['project_id'] == project['project_id'] and event['tick'] < tick and event['event_type'] in EVENT_TYPES:
                    expected.append({'run_id': config['run_id'], 'project_id': project['project_id'], 'event': event,
                        'event_sha256': task_digest(event), 'initial_assignment': project, 'initial_assignment_sha256': task_digest(project)})
        require(observed['construction_results'] == expected, 'Consumer did not receive exactly the actual earlier own events')
        require(observed['native_request_sha256'] == task_digest(record['native_request'])
            and observed['macro_environment'] == record['native_request']['inputs']['macro_environment'], 'Native input changed')
        profile = observed['native_profile']; native = record['native_request']['agent']
        require(profile['capability'] == native['capabilities'][CAPABILITIES[role]]
            and profile['free_ratio'] == native['resources']['available_resource'] / native['resources']['total_resource_capacity'],
            'Own actual native capability/free ratio changed')
        objects = bind_sources(plan, observed)
        observation = one(objects, lambda r: r['ref'] == plan.observation_ref.model_dump(mode='json'), 'Observation missing')['value']
        require(observation['construction_results'] is None, 'Actual events were prefilled')
        observation['construction_results'] = deepcopy(expected)
        require(task_digest(objects) == record['source_sha256'], 'Dynamic source changed')
        consumed = one(micro['source_reading'], lambda r: r['ref']['kind'] == 'MonthlyMethodObservation', 'A12 never read results')['projection']
        policy = one(micro['source_reading'], lambda r: r['ref']['kind'] == 'MonthlyMethodPolicy', 'A12 never read policy')['projection']
        require(consumed == observation and any(r['projection'].get('content_hash') == task_digest(observed)
            for r in micro['source_reading']), 'A12 did not consume exact source evidence')
        require(policy['construction_review'] == config['review_policy'] and policy['baseline_requirement']['value'] == '0'
            and policy['regulatory_pressure_weight']['value'] == '0', 'Independent feedback policy changed')
        history = observed['prior_own_monthly_outcomes']
        require(len(history) == tick - 1 and history == consumed['prior_own_outcomes'], 'Own executed history missing')
        for h in history:
            event = one(events, lambda e: e['event_id'] == h['event_id'], 'Earlier native operation missing')
            prior = micros[TaskIdentity(**h['micro_identity']).key]; judgment = result_judgment(prior)
            require(event['agent_id'] == org and event['tick'] == h['tick'] < tick
                and task_digest(event) == h['source_event_sha256'] and prior['result_sha256'] == h['micro_result_sha256']
                and h['participated'] == judgment.participate and h['method_focus'] == judgment.method_focus
                and h['operation'] == event['data']['operation'] == (OPERATIONS[role] if judgment.participate else 'maintain_operations'),
                'Prior feedback is not the same actual execution')
            agent = one(simulation['agent_results'], lambda a: a['agent_id'] == org, 'Own final profile missing')
            require(h['original_native_memory'] == one(agent['episodic_memory'], lambda m: m.get('tick') == h['tick']
                and m.get('operation') == h['operation'], 'Actual earlier memory missing'), 'Later memory consumption changed')
        judgment = result_judgment(micro); reviews = judgment.construction_review
        require(judgment.prior_actual_improvement_count == sum(h['participated'] for h in history)
            and judgment.consumed_event_ids == [h['event_id'] for h in history], 'Actual history did not enter judgment')
        require(sorted(e['event']['event_id'] for e in expected) == sorted(i for r in reviews for i in r['consumed_event_ids']),
            'Judgment dropped actual construction feedback')
        for review in reviews:
            own = [r['event'] for r in expected if r['project_id'] == review['project_id']]
            require(review['consumed_event_sha256'] == [task_digest(e) for e in sorted(own, key=lambda e:(e['tick'],e['event_id']))], 'Event hashes changed')
            for prefix, output_key, expected_kind in [('inspection_', 'latest_inspection_failed', 'inspection_failed'),
                    ('variation_', 'variation_open', 'variation_requested')]:
                latest = sorted([e for e in own if e['event_type'].startswith(prefix)], key=lambda e:(e['tick'],e['event_id']))
                require(review[output_key] == bool(latest and latest[-1]['event_type'] == expected_kind), 'Later recovery/result was not used')
            if 'safety_issue' in config.get('required_event_types', []):
                from decimal import Decimal
                safety = [e for e in own if e['event_type'] == 'safety_issue']
                risk_samples = sorted([e for e in own if e['event_type'] in {'safety_issue','inspection_passed','inspection_failed'}],
                    key=lambda e:(e['tick'],e['event_id']))
                excess = max(Decimal(0), Decimal(str(risk_samples[-1]['data']['safety_risk']))
                    - Decimal(str(policy['construction_review']['maximum_safety_risk']))) if safety else Decimal(0)
                require(Decimal(review['safety_risk_excess']) == excess
                    and (excess == 0 or review['priority'] == 'site_safety_review'), 'Actual safety result did not enter threshold/priority judgment')
        require(judgment.participate == (any(r['needs_review'] for r in reviews) and profile['free_ratio'] >= 0.2
            and sum(h['participated'] for h in history) < config['ticks']), 'Feedback did not constrain the monthly decision')
        proposal = one(tasks, lambda t: t['identity']['purpose'] == 'propose' and t['output'].get('factors', {}).get('micro_task_key') == identity.key, 'Original proposal missing')['output']
        final = one(tasks, lambda t: t['identity']['purpose'] == 'decide' and t['output'].get('data', {}).get('micro_task_key') == identity.key, 'Original final missing')['output']
        event = one(events, lambda e:e['event_type'] == 'agent_operation' and e['agent_id'] == org and e['tick'] == tick, 'Actual monthly execution missing')
        require(proposal['accepted'] is True and final['decision'] == judgment.participate == event['data']['decision_accepted']
            and proposal['action_type'] == final['action_type'] == judgment.operation
            and event['data']['operation'] == (judgment.operation if judgment.participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256'] == final['data']['micro_result_sha256'] == micro['result_sha256']
            and task_digest(proposal) == record['proposal_response_sha256'] == final['data']['proposal_response_sha256']
            and event['description'] == judgment.interpretation + ' ' + judgment.method_focus, 'Native execution differs from actual micro result')
        consumed_types.update(r['event']['event_type'] for r in expected)
        actual_improvement_followups += judgment.prior_actual_improvement_count > 0
        proofs.append({'scope': record['scope'], 'identity': identity.as_dict(), 'result_sha256': micro['result_sha256'],
            'observed': observed, 'judgment': judgment.model_dump(mode='json'), 'original_proposal': proposal,
            'original_final': final, 'actual_event': event})
    required = set(config.get('required_event_types', ['construction_progress_updated','inspection_failed',
        'inspection_passed','variation_requested','variation_resolved']))
    require(required <= consumed_types and actual_improvement_followups > 0, 'Required actual event consumers missing')
    require(hashlib.sha256(database.read_bytes()).hexdigest() == database_sha, 'Read-only verification changed database')
    return {'batch': '3G-aggregate-feedback', 'status': 'actual_original_events_consumed_by_later_A12',
        'technical_tasks': len(tasks), 'micro_actions': len(proofs), 'consumed_event_types': sorted(consumed_types),
        'actual_improvement_followups': actual_improvement_followups, 'proofs': proofs, 'database_sha256': database_sha,
        'native_execute_work_invalid_actions': [e for e in events if e['event_type'] == 'invalid_action'],
        'macro_unchanged': macro_snapshot_reader(), 'overall_goal3_complete': False, 'boundary': BOUNDARY}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config/professional_construction_feedback_chain.json'))
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv); directory = args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True, exist_ok=False); config = read(args.config)
        _write(directory, 'source-config.json', config); _write(directory, 'macro-before.json', macro_hashes())
        build_bundle(directory / 'construction/input', run_id=config['run_id'], config=config)
        run_existing_input(directory / 'construction', assembly_hook='integration.professional_construction_feedback:configure_assembly')
    checks = verify(directory)
    if args.check_only:
        require(checks == read(directory / 'checks.json'), 'Stored checks changed')
        for name, digest in read(directory / 'artifact-manifest.json')['files'].items():
            require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest, 'Evidence artifact changed: ' + name)
    else:
        _write(directory, 'checks.json', checks)
        _write(directory, 'artifact-manifest.json', {'files': {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}})
    print(json.dumps({k:checks[k] for k in ('status','technical_tasks','micro_actions','consumed_event_types','actual_improvement_followups')}))


if __name__ == '__main__': main()
