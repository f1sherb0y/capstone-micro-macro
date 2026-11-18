"""Plan or explicitly receive an original Architect A07 publication through GOV-A02."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.government_role_contract_host import GovernmentRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.government_role_contract_host:build_role_host'
_CHOICES = ('acknowledge', 'accept_for_processing', 'request_correction', 'decline_processing', 'refer')


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare(input_path):
    current = _read(input_path)
    return _prepare_data(current)


def _prepare_data(current, *, captured_sources=None):
    data = current[2]
    fields = {'schema_version', 'scenario_id', 'run_id', 'government_organization_id',
        'source_mode', 'architect_publication', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] != 'lifecycle-v3-architect-intake-input.v1'
            or data['scenario_id'] != 'V3' or data['source_mode'] != 'formal'
            or not isinstance(data['government_organization_id'], str)
            or not data['government_organization_id'].strip()):
        raise ValueError('V3 requires original Architect publication and explicit current formal Government input')
    selected = data['architect_publication']
    if (not isinstance(selected, dict) or set(selected) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'publication_path',
            'publication_file_sha256', 'publication_receipt_sha256', 'receipt_ref'}):
        raise ValueError('V3 requires complete original publication result and independent accepted receipt')
    for key in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256',
            'publication_file_sha256', 'publication_receipt_sha256'):
        value = selected[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('V3 original provenance requires SHA256 digests')
    for key in ('result_path', 'publication_path'):
        if not isinstance(selected[key], str) or not selected[key].strip():
            raise ValueError('V3 original evidence paths must be explicit')
    def read_source(path):
        path = Path(path).resolve()
        if captured_sources is not None and path in captured_sources:
            return captured_sources[path]
        return _read(path)

    previous = read_source(current[0].parent / selected['result_path'])
    publication = read_source(current[0].parent / selected['publication_path'])
    original, envelope = previous[2], publication[2]
    identity = TaskIdentity(**selected['identity'])
    evidence = original.get('execution_evidence', {})
    audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
    result = original.get('result', {})
    if (previous[1] != selected['result_file_sha256'] or publication[1] != selected['publication_file_sha256']
            or original.get('run_id') != data['run_id'] or original.get('source_mode') != 'formal'
            or original.get('action_id') != 'ARCHITECT-A07' or identity.run_id != data['run_id']
            or identity.role != 'Architect' or identity.action_id != 'ARCHITECT-A07' or identity.purpose != 'action'
            or identity.organization_id == data['government_organization_id']
            or evidence.get('identity') != identity.as_dict()
            or evidence.get('result_table') != 'architect_deliverable_results'
            or evidence.get('record_sha256') != selected['record_sha256']
            or evidence.get('source_reading_sha256') != selected['reading_sha256']
            or result.get('kind') != 'completed' or result.get('payload', {}).get('choice') not in {'submit', 'request_review'}
            or task_digest(result) != selected['result_sha256'] or task.get('identity') != identity.as_dict()
            or task.get('output') != result or task.get('output_sha256') != selected['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(k) != v for k, v in {'run_id': data['run_id'], 'action_id': 'ARCHITECT-A07',
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': selected['result_sha256'], 'result_kind': 'completed'}.items())):
        raise ValueError('V3 changes original Architect result/task/audit provenance')
    native = envelope.get('receipt', {})
    if (envelope.get('schema_version') != 'architect-deliverable-saved-receipt.v1'
            or envelope.get('identity') != identity.as_dict() or envelope.get('record_sha256') != selected['record_sha256']
            or envelope.get('receipt_sha256') != selected['publication_receipt_sha256']
            or task_digest(native) != selected['publication_receipt_sha256']
            or any(native.get(k) != v for k, v in {'run_id': data['run_id'],
                'organization_id': identity.organization_id, 'request_id': identity.request_id,
                'task_sha256': task_digest(identity.as_dict()), 'output_sha256': selected['result_sha256'],
                'disposition': 'accepted'}.items()) or not native.get('receipt_id') or 'original_receipt' not in native):
        raise ValueError('V3 lacks original independently accepted publication receipt')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = GovernmentRoleContractSettings.model_validate(config.settings)
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'GOV-A02'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'GOV-A02' or settings.architect_material_inputs is None
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.architect_material_inputs.selections):
        raise ValueError('V3 requires a distinct formal Government A02 invocation with actual material reception sources')
    selection = settings.architect_material_inputs.selections[request.context.operation_id]
    if (selection.source_task_sha256 != identity.key
            or selection.publication_receipt_sha256 != selected['publication_receipt_sha256']
            or selection.receipt_ref.model_dump(mode='json') != selected['receipt_ref']):
        raise ValueError('V3 Government configuration substitutes selected original Architect publication')
    files = [current, previous, publication]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        if not isinstance(assembly, dict) or set(assembly) != {'government_input'}:
            raise ValueError('V3 assembly requires its original Government input file')
        binding = assembly['government_input']
        if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                or not isinstance(binding['path'], str) or not binding['path'].strip()
                or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
            raise ValueError('V3 Government input requires an explicit original path and raw file SHA')
        government_file = read_source(current[0].parent / binding['path'])
        if (government_file[1] != binding['file_sha256']
                or government_file[2] != {key: data[key] for key in
                    ('run_id', 'government_organization_id', 'request', 'configuration')}):
            raise ValueError('V3 assembly substitutes the supplied original Government input or configuration')
        files.append(government_file)
    return tuple(files), deepcopy(data), identity, request, config


def build_v3_architect_intake_input(*, architect_result_path, publication_path, government_input_path, output_path):
    """Assemble from supplied original files without executing either organization."""
    original_file, publication_file, government_file = (
        _read(architect_result_path), _read(publication_path), _read(government_input_path))
    original, publication, government = original_file[2], publication_file[2], government_file[2]
    if (not isinstance(government, dict) or set(government) != {
            'run_id', 'government_organization_id', 'request', 'configuration'}):
        raise ValueError('V3 assembly requires a complete explicit Government request and host configuration')
    request = RoleContractInvocation.model_validate(government['request'])
    config = RoleContractHostConfiguration.model_validate(government['configuration'])
    settings = GovernmentRoleContractSettings.model_validate(config.settings)
    if settings.architect_material_inputs is None or request.context.operation_id not in settings.architect_material_inputs.selections:
        raise ValueError('V3 assembly requires an independently selected actual material receipt')
    selection = settings.architect_material_inputs.selections[request.context.operation_id]
    evidence = original['execution_evidence']
    identity = TaskIdentity(**evidence['identity'])
    data = {'schema_version': 'lifecycle-v3-architect-intake-input.v1', 'scenario_id': 'V3',
        'run_id': government['run_id'], 'government_organization_id': government['government_organization_id'],
        'source_mode': 'formal', 'request': deepcopy(government['request']),
        'configuration': deepcopy(government['configuration']),
        'architect_publication': {'result_path': str(original_file[0]), 'result_file_sha256': original_file[1],
            'identity': identity.as_dict(), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'publication_path': str(publication_file[0]), 'publication_file_sha256': publication_file[1],
            'publication_receipt_sha256': publication['receipt_sha256'],
            'receipt_ref': selection.receipt_ref.model_dump(mode='json')},
        'assembly_sources': {'government_input': {'path': str(government_file[0]), 'file_sha256': government_file[1]}}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V3 assembled configuration must be a new file')
    supplied_files = (original_file, publication_file, government_file)
    _prepare_data((destination, task_digest(data), data), captured_sources={item[0]: item for item in supplied_files})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in supplied_files):
        raise ValueError('V3 original configuration sources changed during assembly')
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


def run_v3_architect_intake(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V3 execution selection must be an explicit boolean')
    files, data, source_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v3-architect-intake-plan.v1', 'scenario_id': 'V3',
        'run_id': data['run_id'], 'action_id': 'GOV-A02', 'source_mode': 'formal', 'mode': 'plan_only',
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'factory': _FACTORY, 'request_sha256': task_digest(request.model_dump(mode='json')),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'architect_publication': deepcopy(data['architect_publication']),
        'assembly_source_provenance': 'retained_file_hashes' if 'assembly_sources' in data else 'legacy_inline_only',
        'limitations': ['Publication acceptance proves no regulatory case registration, technical approval or permitted use.',
            'Actual Government receipt, original sources and independent reception validator are required.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'architect-result-input.json', files[1][2])
    atomic_json(directory / 'publication-input.json', files[2][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {**plan, 'status': 'started', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original sources changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'government', offline=False)
        evidence, result = output['execution_evidence'], output['result']
        identity, task = evidence['identity'], evidence['task']
        material = evidence['architect_material_input']
        source = data['architect_publication']
        expected = {'source_task_sha256': source_identity.key, 'source_record_sha256': source['record_sha256'],
            'source_result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'publication_receipt_sha256': source['publication_receipt_sha256'],
            'publication_envelope_sha256': task_digest(files[2][2]), 'receipt_ref': source['receipt_ref'],
            'submission_ref': request.action_input['submission_ref'],
            'intake_source_reading_sha256': evidence['source_reading_sha256']}
        if (output['action_id'] != 'GOV-A02' or output['source_mode'] != 'formal'
                or identity['run_id'] != data['run_id'] or identity['organization_id'] != data['government_organization_id']
                or identity['action_id'] != 'GOV-A02' or identity['role'] != 'Government' or identity['purpose'] != 'action'
                or identity['request_id'] != request.context.operation_id
                or identity['input_sha256'] != task_digest(request.action_input)
                or identity['context_sha256'] != task_digest(request.context.model_dump(mode='json'))
                or evidence['result_table'] != 'government_intake_results' or task['identity'] != identity
                or output['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result)
                or not isinstance(material, dict) or any(material.get(k) != v for k, v in expected.items())):
            raise ValueError('V3 intake lacks original durable Government result or selected Architect provenance')
        if result['kind'] == 'completed':
            if (result['payload']['choice'] not in _CHOICES or task['output'] != result
                    or task['output_sha256'] != task_digest(result)):
                raise ValueError('V3 substitutes original Government intake decision')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V3 incomplete intake must retain waiting or technical failure')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V3 original sources changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result_kind': result['kind'],
            'result_path': 'government/result.json', 'result_sha256': task_digest(output)}
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
    parser.add_argument('--publication', type=Path)
    parser.add_argument('--government-input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.architect_result, args.publication, args.government_input)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --architect-result, --publication and --government-input, without --input or --execute')
        build_v3_architect_intake_input(architect_result_path=args.architect_result, publication_path=args.publication,
            government_input_path=args.government_input, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    run_v3_architect_intake(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
