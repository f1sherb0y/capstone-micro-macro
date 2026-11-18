"""Plan or explicitly run same-draft synthetic V5 application and Bank intake."""
import argparse
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import json

from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest

_HOSTS = {
    'OWN-A05': ('owner', 'Owner', 'owner_financing_results'),
    'BANK-A02': ('bank', 'Bank', 'bank_intake_results'),
}
_SCHEMAS = {
    'OWN-A05': 'src.actions.contracts.owner_financing_objects:owner_financing_schemas',
    'BANK-A02': 'src.actions.contracts.bank_objects:bank_intake_schemas',
}
_DRAFT_FIELDS = ('borrower_id', 'lender_id', 'scope_ref', 'requested', 'purpose_ref',
    'product_candidates', 'disclosure_refs', 'applicant_authority_ref')


def _prepare(case_path):
    """Validate supplied JSON bindings without constructing hosts or registries."""
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V5'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('run_id'), str) or not case['run_id'].strip()
            or [(s.get('action_id'), s.get('expected_kind'), s.get('expected_choice')) for s in case.get('steps', [])]
                != [('OWN-A05', 'completed', 'apply'), ('BANK-A02', 'completed', 'accept_for_review')]):
        raise ValueError('V5 application entry requires explicitly declared Owner apply and Bank intake inputs')
    prepared = []
    for step in case['steps']:
        fixture, binding = step['input_fixture'], step['offline_binding']
        request = deepcopy(binding['invocation'])
        request['action_input'] = deepcopy(fixture['input'])
        context = request['context']
        source = deepcopy(binding['source_projection_envelope'])
        source['objects'] = deepcopy(fixture['objects'] + binding['supplemental_objects'])
        if (fixture['source_kind'] != 'synthetic' or context['execution_mode'] != 'offline_fixture'
                or request['execution_path'] != 'deterministic' or context['run_id'] != case['run_id']
                or context['contract_ref']['id'] != step['action_id'] or context['operation_id'] != step['operation_id']
                or context['actor_id'] != fixture['actor_id'] or context['business_time'] != fixture['business_time']
                or binding['schema_factory'] != _SCHEMAS[step['action_id']]
                or binding['organization_snapshot']['run_id'] != case['run_id']
                or source['organization_id'] != fixture['organization_id']
                or any(source[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
                or context['visible_refs'] != [row['ref'] for row in source['objects']]):
            raise ValueError('V5 binding changes its original action, identity or authorized synthetic source')
        prefix, _, _ = _HOSTS[step['action_id']]
        prepared.append({'request': request,
            'factory': f'integration.{prefix}_role_contract_host:build_role_host', 'configuration': {
            'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
            'settings': {'action_id': step['action_id'],
                'source_factory': f'integration.{prefix}_role_contract_fixture_sources:build_sources',
                'source_version': f'configured-{prefix}-fixture-sources.v1',
                'macro_version': source['macro_version'],
                'client_version': f'role-contract-{prefix}-fixture.v1',
                'policy_version': f'role-contract-{prefix}-fixture.v1',
                'model_version': 'offline-fixture-no-model.v1',
                'source_settings': {'action_id': step['action_id'],
                'source_note': binding['source_note'], 'organization_snapshot': deepcopy(binding['organization_snapshot']),
                'source_projection': source, 'allow_saved_recovery': False}}}})
    owner, bank = prepared
    mapping = case['application_mapping']
    draft = mapping['draft']
    application_rows = [row['value'] for row in bank['configuration']['settings']['source_settings']['source_projection']['objects']
        if row['ref'] == mapping['application_ref']]
    profile_rows = [row['value'] for row in owner['configuration']['settings']['source_settings']['source_projection']['objects']
        if row['ref'] == owner['request']['action_input']['funding_profile_ref']]
    if len(application_rows) != 1 or len(profile_rows) != 1 or set(draft) != set(_DRAFT_FIELDS):
        raise ValueError('V5 requires one explicitly supplied same-version application and complete Owner draft')
    application, profile = application_rows[0], profile_rows[0]
    owner_context, bank_context = owner['request']['context'], bank['request']['context']
    points = [owner_context['business_time'], mapping['submitted_at'], bank_context['business_time']]
    if (profile['application'] != draft or owner_context['scope'] != draft['scope_ref']
            or bank_context['scope'] != draft['scope_ref']
            or any(application[k] != draft[k] for k in _DRAFT_FIELDS)
            or application['status'] != 'submitted' or application['submitted_at'] != mapping['submitted_at']
            or application['originating_action_id'] != 'OWN-A05'
            or application['applicant_actor_id'] != owner_context['actor_id']
            or application['applicant_function_ref'] != owner_context['function_ref']
            or application['lender_id'] != bank['configuration']['settings']['source_settings']['source_projection']['organization_id']
            or bank['request']['action_input'] != {'application_ref': mapping['application_ref'],
                **{k: draft[k] for k in _DRAFT_FIELDS if k not in {'lender_id', 'scope_ref'}}}
            or any(point['clock_ref'] != points[0]['clock_ref'] for point in points)
            or any(left['offset'] > right['offset'] for left, right in zip(points, points[1:]))
            or owner_context['operation_id'] == bank_context['operation_id']
            or owner_context['task_ref'] == bank_context['task_ref'] or owner_context['read_token'] == bank_context['read_token']):
        raise ValueError('V5 intake substitutes the complete original draft, declared registration, parties or chronology')
    return path, hashlib.sha256(raw).hexdigest(), case, prepared


def _bind_bank_reception(reception_path, *, case_sha256, steps, directory):
    """Bind explicit reception JSON; never infer objects, grants or native registration."""
    path = Path(reception_path).resolve()
    raw = path.read_bytes()
    _, supplied = parse_input_json(raw)
    if (set(supplied) != {'schema_version', 'case_sha256', 'bank_request', 'bank_source_settings',
            'owner_history', 'registration'} or supplied['schema_version'] != 'lifecycle-v5-bank-reception.v1'
            or supplied['case_sha256'] != case_sha256):
        raise ValueError('V5 reception must explicitly bind the original case and complete current sources')
    owner, bank = steps
    original_request = bank['request']
    request = deepcopy(supplied['bank_request'])
    sources = deepcopy(supplied['bank_source_settings'])
    history, registration = deepcopy(supplied['owner_history']), deepcopy(supplied['registration'])
    original_sources = bank['configuration']['settings']['source_settings']
    mutable_context = {'read_token', 'visible_refs', 'authorization_refs'}
    if (set(request) != set(original_request) or set(request['context']) != set(original_request['context'])
            or any(request[k] != v for k, v in original_request.items() if k != 'context')
            or any(request['context'][k] != v for k, v in original_request['context'].items() if k not in mutable_context)
            or set(sources) != set(original_sources) or sources['action_id'] != 'BANK-A02'
            or sources['journal_path'] != str(directory / 'step-2' / 'tasks.sqlite')
            or sources['allow_saved_recovery'] is not False
            or sources['organization_snapshot']['run_id'] != request['context']['run_id']):
        raise ValueError('V5 reception substitutes the original Bank action, case, input or current journal')
    context, projection = request['context'], sources['source_projection']
    original_projection = original_sources['source_projection']
    keys = [task_digest(row['ref']) for row in projection['objects']]
    current_rows = {task_digest(row['ref']): row for row in projection['objects']}
    if (set(projection) != set(original_projection) or len(set(keys)) != len(keys)
            or any(projection[k] != v for k, v in original_projection.items() if k not in {'read_token', 'state_version', 'objects'})
            or any(current_rows.get(task_digest(row['ref'])) != row for row in original_projection['objects'])
            or context['visible_refs'] != [row['ref'] for row in projection['objects']]
            or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))):
        raise ValueError('V5 reception replaces original facts or infers visibility rather than supplying a new authorized snapshot')
    owner_context = owner['request']['context']
    identity = history['identity']
    expected = {'run_id': owner_context['run_id'], 'organization_id': owner['configuration']['settings']['source_settings']['source_projection']['organization_id'],
        'role': 'Owner', 'action_id': 'OWN-A05', 'request_id': owner_context['operation_id'], 'purpose': 'action',
        'input_sha256': task_digest(owner['request']['action_input']), 'context_sha256': task_digest(owner_context)}
    task_key = task_digest([identity['run_id'], identity['organization_id'], identity['purpose'], identity['request_id']])
    if (any(identity.get(k) != v for k, v in expected.items())
            or history['request']['action_input'] != owner['request']['action_input']
            or history['request']['context']['business_time'] != context['business_time']
            or history['source_settings']['journal_path'] != str(directory / 'step-1' / 'tasks.sqlite')
            or history['source_settings']['allow_saved_recovery'] is not False
            or any(history[k] != owner['configuration']['settings'][k]
                for k in ('macro_version', 'client_version', 'policy_version', 'model_version'))
            or registration['source_identity'] != identity or registration['run_id'] != context['run_id']
            or registration['current_state'] != 'submitted' or registration['sharing_authorized'] is not True
            or registration['application'] != current_rows[task_digest(request['action_input']['application_ref'])]['value']
            or registration['recipient_organization_id'] != projection['organization_id']
            or registration['recipient_actor_id'] != context['actor_id']
            or registration['recipient_function_ref'] != context['function_ref']
            or registration['recipient_authorization_refs'] != context['authorization_refs']):
        raise ValueError('V5 reception changes original Owner identity, current read sources or independent registration')
    if (task_digest(registration['receipt_ref']) not in current_rows
            or task_digest(registration['native_evidence_ref']) not in current_rows):
        raise ValueError('V5 reception must explicitly supply its receipt and observed native evidence projections')
    receipt = current_rows[task_digest(registration['receipt_ref'])]['value']
    native = current_rows[task_digest(registration['native_evidence_ref'])]['value']
    if (receipt['source_task_sha256'] != task_key
            or any(receipt[k] != registration[k] for k in ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
            or receipt['native_record_sha256'] != task_digest(registration)
            or receipt['native_evidence_ref'] != registration['native_evidence_ref']
            or native['basis_kind'] != 'observed' or native['source_kind'] != 'synthetic'
            or native['content_hash'] != task_digest(registration)):
        raise ValueError('V5 reception evidence does not bind its explicitly declared native record and original lineage')
    sources.update(owner_history=history, registration=registration)
    bank['request'] = request
    settings = bank['configuration']['settings']
    settings.update(source_settings=sources,
        source_factory='integration.owner_application_bank_fixture_sources:build_sources',
        source_version='configured-bank-owner-application-fixture-sources.v1',
        owner_application_inputs={'version': 'v5-explicit-owner-application-reception.v1',
            'selections': {context['operation_id']: {'source_task_sha256': task_key, 'receipt_ref': registration['receipt_ref']}}})
    return path, hashlib.sha256(raw).hexdigest(), supplied


def _persistent_execution(step, result):
    """Bind original durable host evidence to this exact local invocation."""
    request = step['request']
    context = request['context']
    action_id = context['contract_ref']['id']
    _, role, table = _HOSTS[action_id]
    settings = step['configuration']['settings']['source_settings']
    execution = result.get('execution_evidence')
    if not isinstance(execution, dict):
        raise ValueError('V5 requires the original persistent host execution evidence')
    identity, audit, task = execution['identity'], execution['saved_audit'], execution['task']
    sources = execution['sources']
    expected_identity = {'run_id': context['run_id'], 'organization_id': settings['source_projection']['organization_id'],
        'role': role, 'action_id': action_id, 'request_id': context['operation_id'], 'purpose': 'action',
        'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(context)}
    expected_audit = {'schema_version': 'action-audit.v1', 'run_id': context['run_id'], 'action_id': action_id,
        'operation_id': context['operation_id'], 'input_version': context['contract_ref']['version'],
        'input_sha256': identity['input_sha256'], 'result_kind': result['result']['kind'],
        'result_sha256': task_digest(result['result']), 'execution_path': 'deterministic'}
    digests = (execution['record_sha256'], execution['source_reading_sha256'])
    if (any(identity.get(k) != v for k, v in expected_identity.items())
            or execution['result_table'] != table
            or any(not isinstance(d, str) or len(d) != 64 or any(c not in '0123456789abcdef' for c in d) for d in digests)
            or result['run_id'] != context['run_id'] or result['action_id'] != action_id
            or result['request_sha256'] != task_digest(request) or result['source_mode'] != 'fixture'
            or task['identity'] != identity or task['state'] != 'output_formed'
            or task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
            or result['audit'] != [audit] or any(audit.get(k) != v for k, v in expected_audit.items())
            or audit['stages']['authorization'] != 'accepted'
            or audit['reading']['read_token'] != context['read_token']
            or sources['journal_path'] != settings['journal_path']
            or sources['allow_saved_recovery'] is not False or sources['origin'] != 'synthetic'
            or sources['source_projection_sha256'] != task_digest(settings['source_projection'])):
        raise ValueError('V5 persistent evidence changes its original identity, source, journal, audit or result')
    return {'identity': deepcopy(identity), 'task_sha256': task_digest(identity),
        'record_sha256': execution['record_sha256'], 'result_table': table,
        'source_reading_sha256': execution['source_reading_sha256'], 'saved_audit': deepcopy(audit),
        'journal_path': settings['journal_path']}


def run_v5_offline(*, case_path, output_directory, execute=False, bank_reception_path=None):
    """Run local decisions only on explicit request; preserve the full pending V5 chain."""
    if type(execute) is not bool:
        raise ValueError('V5 execution requires an explicit boolean selection')
    path, source_sha, case, steps = _prepare(case_path)
    directory = Path(output_directory).resolve()
    for index, step in enumerate(steps, start=1):
        step['configuration']['settings']['source_settings']['journal_path'] = str(directory / f'step-{index}' / 'tasks.sqlite')
    reception = (_bind_bank_reception(bank_reception_path, case_sha256=source_sha, steps=steps, directory=directory)
        if bank_reception_path is not None else None)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-offline-plan.v1', 'origin': 'synthetic', 'run_id': case['run_id'],
        'case_path': str(path), 'case_sha256': source_sha,
        'mode': 'execute_offline' if execute else 'plan_only',
        'steps': [{'action_id': row['request']['context']['contract_ref']['id'],
            'factory': row['factory'],
            'request_sha256': task_digest(row['request']), 'configuration_sha256': task_digest(row['configuration']),
            'expected_choice': case['steps'][index]['expected_choice']} for index, row in enumerate(steps)],
        'application_mapping': deepcopy(case['application_mapping']), 'dependent_steps': deepcopy(case['dependent_steps']),
        'remaining_requirements': deepcopy(case['remaining_requirements']), 'limitations': case['limitations']}
    if reception is not None:
        plan['bank_reception'] = {'path': str(reception[0]), 'sha256': reception[1],
            'registration_sha256': task_digest(reception[2]['registration'])}
        atomic_json(directory / 'bank-reception-input.json', reception[2])
    for index, step in enumerate(steps, start=1):
        atomic_json(directory / f'step-{index}-request.json', step['request'])
        atomic_json(directory / f'step-{index}-configuration.json', step['configuration'])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-offline-attempt.v1', 'case_sha256': source_sha,
        'status': 'started', 'completed_steps': []}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        for index, step in enumerate(steps, start=1):
            if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
                raise ValueError('V5 declared input changed before execution')
            if reception is not None and hashlib.sha256(reception[0].read_bytes()).hexdigest() != reception[1]:
                raise ValueError('V5 declared reception changed before execution')
            module, name = step['factory'].split(':')
            factory = getattr(importlib.import_module(module), name)
            result = run_role_contract(request=step['request'], configuration=step['configuration'],
                factory=factory, specification=step['factory'], output_directory=directory / f'step-{index}', offline=True)
            execution = _persistent_execution(step, result)
            atomic_json(directory / f'step-{index}' / 'persistent-evidence.json', execution)
            observed = result['result']
            payload = observed.get('payload', {})
            if observed['kind'] != 'completed' or payload.get('choice') != case['steps'][index - 1]['expected_choice']:
                raise ValueError('V5 original action did not produce its declared local choice')
            if index == 1 and payload.get('application') != case['application_mapping']['draft']:
                raise ValueError('Original Owner result changes the complete draft supplied to Bank intake')
            if index == 2 and payload.get('product_ref') not in case['application_mapping']['draft']['product_candidates']:
                raise ValueError('Bank intake substitutes an undeclared original product version')
            if reception is not None:
                registration = reception[2]['registration']
                if index == 1 and (execution['identity'] != registration['source_identity']
                        or execution['record_sha256'] != registration['source_record_sha256']
                        or execution['source_reading_sha256'] != registration['source_reading_sha256']
                        or task_digest(observed) != registration['source_result_sha256']):
                    raise ValueError('V5 declared reception does not refer to this original saved Owner application')
                if index == 2:
                    provenance = result['execution_evidence'].get('owner_application_input')
                    selection = step['configuration']['settings']['owner_application_inputs']['selections'][step['request']['context']['operation_id']]
                    expected = {**selection, **{k: registration[k] for k in
                        ('source_record_sha256', 'source_result_sha256', 'source_reading_sha256')}}
                    if provenance != expected:
                        raise ValueError('V5 Bank intake did not save its original application reception provenance')
                    execution['owner_application_input'] = deepcopy(provenance)
                    atomic_json(directory / f'step-{index}' / 'persistent-evidence.json', execution)
            attempt['completed_steps'].append({'action_id': plan['steps'][index - 1]['action_id'],
                'result_path': f'step-{index}/result.json', 'result_sha256': task_digest(result),
                'persistent_evidence_path': f'step-{index}/persistent-evidence.json',
                'persistent_evidence_sha256': task_digest(execution), **execution})
            atomic_json(directory / 'attempt.json', attempt)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
            raise ValueError('V5 input changed during execution')
        if reception is not None and hashlib.sha256(reception[0].read_bytes()).hexdigest() != reception[1]:
            raise ValueError('V5 reception changed during execution')
        summary = {**plan, 'status': 'local_application_and_received_intake_completed' if reception is not None
                else 'local_application_and_intake_completed',
            'results': deepcopy(attempt['completed_steps'])}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_application_inputs.v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    parser.add_argument('--bank-reception', type=Path, help='Explicit current sources and independently declared registration JSON')
    args = parser.parse_args()
    report = run_v5_offline(case_path=args.case, output_directory=args.output, execute=args.execute_offline,
        bank_reception_path=args.bank_reception)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
