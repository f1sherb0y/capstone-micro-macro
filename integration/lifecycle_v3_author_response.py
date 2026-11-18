"""Plan or explicitly prepare an A08 author response from the original received opinion."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.architect_role_contract_host import ArchitectRoleContractSettings, build_role_host
from integration.lifecycle_v3_architect_intake import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.sessions import atomic_json
from src.actions.contracts.architect_review_objects import ArchitectReviewOpinionReceiptView
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.architect_role_contract_host:build_role_host'


def _prepare(input_path):
    current = _read(input_path)
    return _prepare_data(current)


def _prepare_data(current, *, captured_sources=None):
    data = current[2]
    fields = {'schema_version', 'scenario_id', 'run_id', 'author_organization_id',
        'source_mode', 'reviewer_opinion', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] != 'lifecycle-v3-author-response-input.v1'
            or data['scenario_id'] != 'V3' or data['source_mode'] != 'formal'
            or not isinstance(data['author_organization_id'], str) or not data['author_organization_id'].strip()):
        raise ValueError('V3 author response requires an original opinion and explicit current formal author input')
    selected = data['reviewer_opinion']
    if (not isinstance(selected, dict) or set(selected) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'selection'}
            or not isinstance(selected['result_path'], str) or not selected['result_path'].strip()):
        raise ValueError('V3 author response requires original reviewer result and explicit received-opinion selection')
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
            or original.get('source_mode') != 'formal' or original.get('action_id') != 'ARCHITECT-A08'
            or identity.run_id != data['run_id'] or identity.role != 'Architect'
            or identity.action_id != 'ARCHITECT-A08' or identity.purpose != 'action'
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'architect_review_results'
            or evidence.get('record_sha256') != selected['record_sha256']
            or evidence.get('source_reading_sha256') != selected['reading_sha256']
            or result.get('kind') != 'completed' or result.get('payload', {}).get('choice') != 'review'
            or task_digest(result) != selected['result_sha256'] or task.get('identity') != identity.as_dict()
            or task.get('output') != result or task.get('output_sha256') != selected['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(k) != v for k, v in {'run_id': data['run_id'], 'action_id': 'ARCHITECT-A08',
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': selected['result_sha256'], 'result_kind': 'completed'}.items())):
        raise ValueError('V3 author input changes original reviewer result/task/audit provenance')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = ArchitectRoleContractSettings.model_validate(config.settings)
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'ARCHITECT-A08'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'ARCHITECT-A08' or settings.received_opinion_inputs is None
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.received_opinion_inputs.selections):
        raise ValueError('V3 author response requires a distinct formal A08 invocation and received-opinion sources')
    selection = settings.received_opinion_inputs.selections[request.context.operation_id].model_dump(mode='json')
    if selection != selected['selection'] or selection['source_task_sha256'] != identity.key:
        raise ValueError('V3 author configuration substitutes the selected original opinion or receipt evidence')
    files = [current, previous]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        if not isinstance(assembly, dict) or set(assembly) != {'author_input', 'receipt'}:
            raise ValueError('V3 author assembly requires original author input and actual opinion receipt files')
        for label in ('author_input', 'receipt'):
            binding = assembly[label]
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()
                    or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
                raise ValueError('V3 author assembly source requires its original path and raw SHA')
            item = read_source(current[0].parent / binding['path'])
            if item[1] != binding['file_sha256']:
                raise ValueError('V3 original author input or actual opinion receipt changed after assembly')
            files.append(item)
        if files[2][2] != {key: data[key] for key in ('run_id', 'author_organization_id', 'request', 'configuration')}:
            raise ValueError('V3 author assembly substitutes original author input or configuration')
        receipt = ArchitectReviewOpinionReceiptView.model_validate(files[3][2])
        expected = {'run_id': data['run_id'], 'reviewer_organization_id': identity.organization_id,
            'author_organization_id': data['author_organization_id'], 'author_actor_id': request.context.actor_id,
            'task_sha256': identity.key, 'record_sha256': selected['record_sha256'],
            'result_sha256': selected['result_sha256'], 'source_reading_sha256': selected['reading_sha256'],
            'scope': request.context.scope}
        if (any(getattr(receipt, key) != value for key, value in expected.items())
                or receipt.ref.model_dump(mode='json') != selection['receipt_ref']
                or receipt.opinion.model_dump(mode='json') != result['payload']['opinion']
                or receipt.opinion_content_sha256 != content_digest(receipt.opinion)
                or receipt.author_review_request_ref.model_dump(mode='json') != request.action_input['review_request_ref']):
            raise ValueError('V3 opinion receipt substitutes original opinion, reviewer, author or response task')
    return tuple(files), deepcopy(data), identity, request, config


def build_v3_author_response_input(*, reviewer_result_path, author_input_path, receipt_path, output_path):
    """Assemble original opinion/reception/configuration without creating a response."""
    original_file, author_file, receipt_file = (
        _read(reviewer_result_path), _read(author_input_path), _read(receipt_path))
    original, author = original_file[2], author_file[2]
    if (not isinstance(author, dict) or set(author) != {
            'run_id', 'author_organization_id', 'request', 'configuration'}):
        raise ValueError('V3 author assembly requires complete explicit author request and host configuration')
    request = RoleContractInvocation.model_validate(author['request'])
    config = RoleContractHostConfiguration.model_validate(author['configuration'])
    settings = ArchitectRoleContractSettings.model_validate(config.settings)
    if settings.received_opinion_inputs is None or request.context.operation_id not in settings.received_opinion_inputs.selections:
        raise ValueError('V3 author assembly requires an independently selected actual opinion receipt')
    selection = settings.received_opinion_inputs.selections[request.context.operation_id].model_dump(mode='json')
    evidence = original['execution_evidence']
    data = {'schema_version': 'lifecycle-v3-author-response-input.v1', 'scenario_id': 'V3',
        'run_id': author['run_id'], 'author_organization_id': author['author_organization_id'], 'source_mode': 'formal',
        'request': deepcopy(author['request']), 'configuration': deepcopy(author['configuration']),
        'reviewer_opinion': {'result_path': str(original_file[0]), 'result_file_sha256': original_file[1],
            'identity': deepcopy(evidence['identity']), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'selection': selection},
        'assembly_sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in (('author_input', author_file), ('receipt', receipt_file))}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V3 assembled author configuration must be a new file')
    supplied_files = (original_file, author_file, receipt_file)
    _prepare_data((destination, task_digest(data), data), captured_sources={item[0]: item for item in supplied_files})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in supplied_files):
        raise ValueError('V3 original author configuration sources changed during assembly')
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


def run_v3_author_response(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V3 author execution selection must be an explicit boolean')
    files, data, source_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v3-author-response-plan.v1', 'scenario_id': 'V3',
        'run_id': data['run_id'], 'source_mode': 'formal', 'mode': 'plan_only', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request.model_dump(mode='json')),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'reviewer_opinion': deepcopy(data['reviewer_opinion']),
        'assembly_source_provenance': 'retained_file_hashes' if 'assembly_sources' in data else 'legacy_inline_only',
        'limitations': ['Opinion receipt is distinct from author response, actual revision and issue closure.',
            'The application must supply actual original reviewer history, submission and independently received comment.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'reviewer-result-input.json', files[1][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {**plan, 'status': 'started', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original opinion or author input changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'author', offline=False)
        evidence, result = output['execution_evidence'], output['result']
        identity, task, provenance = evidence['identity'], evidence['task'], evidence['received_opinion_input']
        source = data['reviewer_opinion']
        expected = {'task_sha256': source_identity.key, 'record_sha256': source['record_sha256'],
            'result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'opinion_sha256': task_digest(files[1][2]['result']['payload']['opinion']),
            'native_source_sha256': source['selection']['native_source_sha256'],
            'invocation_reading_sha256': evidence['source_reading_sha256']}
        if 'assembly_sources' in data:
            expected['receipt_sha256'] = content_digest(ArchitectReviewOpinionReceiptView.model_validate(files[3][2]))
        if (output['source_mode'] != 'formal' or output['action_id'] != 'ARCHITECT-A08'
                or identity['run_id'] != data['run_id'] or identity['organization_id'] != data['author_organization_id']
                or identity['action_id'] != 'ARCHITECT-A08' or identity['role'] != 'Architect' or identity['purpose'] != 'action'
                or identity['request_id'] != request.context.operation_id
                or identity['input_sha256'] != task_digest(request.action_input)
                or identity['context_sha256'] != task_digest(request.context.model_dump(mode='json'))
                or evidence['result_table'] != 'architect_review_results' or task['identity'] != identity
                or output['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result)
                or not isinstance(provenance, dict) or any(provenance.get(k) != v for k, v in expected.items())):
            raise ValueError('V3 author outcome lacks original durable task/audit or selected reviewer provenance')
        submission = provenance.get('submission', {})
        if (submission.get('identity') != source_identity.as_dict()
                or submission.get('record_sha256') != source['record_sha256']
                or submission.get('receipt', {}).get('disposition') != 'accepted'):
            raise ValueError('V3 author outcome lacks the original accepted reviewer submission')
        if result['kind'] == 'completed':
            if (result['payload']['choice'] not in {'respond', 'propose_revision'} or task['output'] != result
                    or task['output_sha256'] != task_digest(result)):
                raise ValueError('V3 author outcome substitutes a reviewer decision for author response or revision proposal')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V3 incomplete author response must preserve waiting or technical failure')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original opinion or author input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result_kind': result['kind'],
            'result_path': 'author/result.json', 'result_sha256': task_digest(output)}
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
    parser.add_argument('--reviewer-result', type=Path)
    parser.add_argument('--author-input', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.reviewer_result, args.author_input, args.receipt)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --reviewer-result, --author-input and --receipt, without --input or --execute')
        build_v3_author_response_input(reviewer_result_path=args.reviewer_result, author_input_path=args.author_input,
            receipt_path=args.receipt, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    run_v3_author_response(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
