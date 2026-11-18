"""Plan or explicitly prepare an A08 review from the original A07 review-task intake."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.architect_role_contract_host import ArchitectRoleContractSettings, build_role_host
from integration.lifecycle_v3_architect_intake import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.sessions import atomic_json
from src.actions.contracts.architect_review_objects import ArchitectReviewTaskRegistrationView
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.architect_role_contract_host:build_role_host'


def _prepare(input_path):
    current = _read(input_path)
    return _prepare_data(current)


def _prepare_data(current, *, captured_sources=None):
    data = current[2]
    fields = {'schema_version', 'scenario_id', 'run_id', 'reviewer_organization_id',
        'source_mode', 'review_task', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] != 'lifecycle-v3-review-task-input.v1'
            or data['scenario_id'] != 'V3' or data['source_mode'] != 'formal'
            or not isinstance(data['reviewer_organization_id'], str) or not data['reviewer_organization_id'].strip()):
        raise ValueError('V3 review task requires an original A07 review request and explicit current formal reviewer input')
    selected = data['review_task']
    if (not isinstance(selected, dict) or set(selected) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'selection'}
            or not isinstance(selected['result_path'], str) or not selected['result_path'].strip()):
        raise ValueError('V3 review task requires original A07 request-review result and explicit review-task registration selection')
    for key in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256'):
        value = selected[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('V3 reviewer provenance requires SHA256 digests')
    def read_source(path):
        path = Path(path).resolve()
        if captured_sources is not None and path in captured_sources:
            return captured_sources[path]
        return _read(path)

    previous = read_source(current[0].parent / selected['result_path'])
    original = previous[2]
    identity = TaskIdentity(**selected['identity'])
    evidence = original.get('execution_evidence', {})
    audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
    result = original.get('result', {})
    if (previous[1] != selected['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('source_mode') != 'formal' or original.get('action_id') != 'ARCHITECT-A07'
            or identity.run_id != data['run_id'] or identity.role != 'Architect'
            or identity.action_id != 'ARCHITECT-A07' or identity.purpose != 'action'
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'architect_deliverable_results'
            or evidence.get('record_sha256') != selected['record_sha256']
            or evidence.get('source_reading_sha256') != selected['reading_sha256']
            or result.get('kind') != 'completed' or result.get('payload', {}).get('choice') != 'request_review'
            or task_digest(result) != selected['result_sha256'] or task.get('identity') != identity.as_dict()
            or task.get('output') != result or task.get('output_sha256') != selected['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(k) != v for k, v in {'run_id': data['run_id'], 'action_id': 'ARCHITECT-A07',
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': selected['result_sha256'], 'result_kind': 'completed'}.items())):
        raise ValueError('V3 reviewer input changes original A07 request-review result/task/audit provenance')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = ArchitectRoleContractSettings.model_validate(config.settings)
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'ARCHITECT-A08'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'ARCHITECT-A08' or settings.received_review_task_inputs is None
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.received_review_task_inputs.selections):
        raise ValueError('V3 review task requires a distinct formal A08 reviewer invocation and actual review-task registration sources')
    selection = settings.received_review_task_inputs.selections[request.context.operation_id].model_dump(mode='json')
    if selection != selected['selection'] or selection['source_task_sha256'] != identity.key:
        raise ValueError('V3 reviewer configuration substitutes the selected original A07 review request or registration evidence')
    files = [current, previous]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        if not isinstance(assembly, dict) or set(assembly) != {'reviewer_input', 'registration'}:
            raise ValueError('V3 review assembly requires original reviewer input and task registration files')
        for label in ('reviewer_input', 'registration'):
            binding = assembly[label]
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()
                    or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
                raise ValueError('V3 review assembly source requires an explicit original path and raw SHA')
            item = read_source(current[0].parent / binding['path'])
            if item[1] != binding['file_sha256']:
                raise ValueError('V3 original reviewer input or review-task registration changed after assembly')
            files.append(item)
        if files[2][2] != {key: data[key] for key in ('run_id', 'reviewer_organization_id', 'request', 'configuration')}:
            raise ValueError('V3 review assembly substitutes original reviewer input or configuration')
        registration = ArchitectReviewTaskRegistrationView.model_validate(files[3][2])
        payload = result['payload']
        expected = {'run_id': data['run_id'], 'requester_organization_id': identity.organization_id,
            'reviewer_organization_id': data['reviewer_organization_id'], 'reviewer_actor_id': request.context.actor_id,
            'reviewer_function_ref': request.context.function_ref, 'task_sha256': identity.key,
            'record_sha256': selected['record_sha256'], 'result_sha256': selected['result_sha256'],
            'source_reading_sha256': selected['reading_sha256'], 'scope': request.context.scope}
        if (any(getattr(registration, key) != value for key, value in expected.items())
                or registration.ref.model_dump(mode='json') != selection['registration_ref']
                or registration.target_ref.model_dump(mode='json') != payload['deliverable_ref']
                or registration.review_requirement_ref.model_dump(mode='json') != payload['review_requirement_ref']
                or registration.requested_use != payload['requested_use'] or registration.recipient_ids != payload['recipient_ids']
                or [ref.model_dump(mode='json') for ref in registration.unresolved_issue_refs] != payload['unresolved_issue_refs']):
            raise ValueError('V3 review registration substitutes original request, reviewer, target or source provenance')
    return tuple(files), deepcopy(data), identity, request, config


def build_v3_review_task_input(*, architect_result_path, reviewer_input_path, registration_path, output_path):
    """Assemble supplied originals without generating reviewer authority or task intake."""
    original_file, reviewer_file, registration_file = (
        _read(architect_result_path), _read(reviewer_input_path), _read(registration_path))
    original, reviewer = original_file[2], reviewer_file[2]
    if (not isinstance(reviewer, dict) or set(reviewer) != {
            'run_id', 'reviewer_organization_id', 'request', 'configuration'}):
        raise ValueError('V3 review assembly requires complete explicit reviewer request and host configuration')
    request = RoleContractInvocation.model_validate(reviewer['request'])
    config = RoleContractHostConfiguration.model_validate(reviewer['configuration'])
    settings = ArchitectRoleContractSettings.model_validate(config.settings)
    if settings.received_review_task_inputs is None or request.context.operation_id not in settings.received_review_task_inputs.selections:
        raise ValueError('V3 review assembly requires an independently selected actual review-task registration')
    selection = settings.received_review_task_inputs.selections[request.context.operation_id].model_dump(mode='json')
    evidence = original['execution_evidence']
    data = {'schema_version': 'lifecycle-v3-review-task-input.v1', 'scenario_id': 'V3',
        'run_id': reviewer['run_id'], 'reviewer_organization_id': reviewer['reviewer_organization_id'],
        'source_mode': 'formal', 'request': deepcopy(reviewer['request']), 'configuration': deepcopy(reviewer['configuration']),
        'review_task': {'result_path': str(original_file[0]), 'result_file_sha256': original_file[1],
            'identity': deepcopy(evidence['identity']), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'selection': selection},
        'assembly_sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in (('reviewer_input', reviewer_file), ('registration', registration_file))}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V3 assembled review configuration must be a new file')
    supplied_files = (original_file, reviewer_file, registration_file)
    _prepare_data((destination, task_digest(data), data), captured_sources={item[0]: item for item in supplied_files})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in supplied_files):
        raise ValueError('V3 original review configuration sources changed during assembly')
    raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as stream:
        try:
            stream.write(raw + '\n')
        except BaseException:
            stream.close()
            destination.unlink()
            raise
    return data


def run_v3_review_task(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V3 reviewer execution selection must be an explicit boolean')
    files, data, source_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v3-review-task-plan.v1', 'scenario_id': 'V3',
        'run_id': data['run_id'], 'source_mode': 'formal', 'mode': 'plan_only', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request.model_dump(mode='json')),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'review_task': deepcopy(data['review_task']),
        'assembly_source_provenance': 'retained_file_hashes' if 'assembly_sources' in data else 'legacy_inline_only',
        'limitations': ['Review-task intake is distinct from completed review, author response, approval and allowed use.',
            'The application must supply original A07 history/submission, actual registration, reviewer delegation and independent source validators.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'review-request-result-input.json', files[1][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {**plan, 'status': 'started', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original A07 review request or reviewer input changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'reviewer', offline=False)
        evidence, result = output['execution_evidence'], output['result']
        identity, task, provenance = evidence['identity'], evidence['task'], evidence['received_review_task_input']
        source = data['review_task']
        expected = {'task_sha256': source_identity.key, 'record_sha256': source['record_sha256'],
            'result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'native_source_sha256': source['selection']['native_source_sha256']}
        if 'assembly_sources' in data:
            expected['registration_sha256'] = content_digest(ArchitectReviewTaskRegistrationView.model_validate(files[3][2]))
        if (output['source_mode'] != 'formal' or output['action_id'] != 'ARCHITECT-A08'
                or identity['run_id'] != data['run_id'] or identity['organization_id'] != data['reviewer_organization_id']
                or identity['action_id'] != 'ARCHITECT-A08' or identity['role'] != 'Architect' or identity['purpose'] != 'action'
                or identity['request_id'] != request.context.operation_id
                or identity['input_sha256'] != task_digest(request.action_input)
                or identity['context_sha256'] != task_digest(request.context.model_dump(mode='json'))
                or evidence['result_table'] != 'architect_review_results' or task['identity'] != identity
                or output['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result)
                or not isinstance(provenance, dict) or any(provenance.get(k) != v for k, v in expected.items())):
            raise ValueError('V3 reviewer outcome lacks original durable task/audit or selected A07 request provenance')
        submission = provenance.get('submission', {})
        if (submission.get('identity') != source_identity.as_dict()
                or submission.get('record_sha256') != source['record_sha256']
                or submission.get('receipt', {}).get('disposition') != 'accepted'):
            raise ValueError('V3 reviewer outcome lacks the original accepted A07 review-request submission')
        if result['kind'] == 'completed':
            if (result['payload']['choice'] != 'review' or task['output'] != result
                    or task['output_sha256'] != task_digest(result)):
                raise ValueError('V3 reviewer outcome substitutes an author response or revision proposal for independent reviewer assessment')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V3 incomplete review must preserve waiting or technical failure')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original A07 review request or reviewer input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result_kind': result['kind'],
            'result_path': 'reviewer/result.json', 'result_sha256': task_digest(output)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--architect-result', type=Path)
    parser.add_argument('--reviewer-input', type=Path)
    parser.add_argument('--registration', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.architect_result, args.reviewer_input, args.registration)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --architect-result, --reviewer-input and --registration, without --input or --execute')
        build_v3_review_task_input(architect_result_path=args.architect_result, reviewer_input_path=args.reviewer_input,
            registration_path=args.registration, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    run_v3_review_task(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
