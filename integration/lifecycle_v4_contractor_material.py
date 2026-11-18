"""Plan or explicitly evaluate V4 Contractor materials from an original Supplier result."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.contractor_role_contract_host import ContractorRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_execution_objects import ContractorReceivedMaterialView
from src.coordination.tasks import TaskIdentity, task_digest
from src.organization.registry import scope_covers


_FACTORY = 'integration.contractor_role_contract_host:build_role_host'
_CHOICES = ('execute', 'rebalance', 'report', 'reconcile')


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
    fields = {'schema_version', 'scenario_id', 'run_id', 'contractor_organization_id',
        'source_mode', 'supplier_receiving', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] != 'lifecycle-v4-contractor-material-input.v1'
            or data['scenario_id'] != 'V4' or data['source_mode'] not in {'fixture', 'formal'}
            or not isinstance(data['contractor_organization_id'], str) or not data['contractor_organization_id'].strip()):
        raise ValueError('V4 requires original Supplier evidence and explicit current Contractor material sources')
    selected = data['supplier_receiving']
    if (not isinstance(selected, dict) or set(selected) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'material_basis_refs'}
            or not isinstance(selected['result_path'], str) or not selected['result_path'].strip()
            or not isinstance(selected['material_basis_refs'], list) or not selected['material_basis_refs']):
        raise ValueError('V4 requires original Supplier result, source digests and current material basis references')
    for field in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256'):
        value = selected[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V4 original material provenance requires SHA256 digests')
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
    if (previous[1] != selected['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('action_id') != 'SUPPLIER-A09' or original.get('source_mode') != data['source_mode']
            or identity.run_id != data['run_id'] or identity.role != 'Supplier' or identity.action_id != 'SUPPLIER-A09'
            or identity.purpose != 'action' or identity.organization_id == data['contractor_organization_id']
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'supplier_receiving_results'
            or evidence.get('record_sha256') != selected['record_sha256']
            or evidence.get('source_reading_sha256') != selected['reading_sha256']
            or original.get('result', {}).get('kind') != 'completed'
            or task_digest(original['result']) != selected['result_sha256']
            or task.get('identity') != identity.as_dict() or task.get('output') != original['result']
            or task.get('output_sha256') != selected['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit]
            or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'SUPPLIER-A09',
                'input_sha256': identity.input_sha256, 'operation_id': identity.request_id,
                'result_sha256': selected['result_sha256'], 'result_kind': 'completed'}.items())
            or audit.get('reading', {}).get('source_mode') != data['source_mode']):
        raise ValueError('V4 replaces original Supplier task/result/audit or source mode')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    offline = data['source_mode'] == 'fixture'
    refs = [Reference.model_validate(ref) for ref in selected['material_basis_refs']]
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'CONTRACTOR-A07'
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')
            or settings.action_id != 'CONTRACTOR-A07' or settings.received_material_inputs is None
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.received_material_inputs.selections
            or len({ref.key() for ref in refs}) != len(refs) or any(ref.kind != 'ReceivedMaterialBasis' for ref in refs)
            or offline and request.execution_path not in {None, 'deterministic'}
            or not offline and request.execution_path == 'deterministic'):
        raise ValueError('V4 requires a distinct Contractor A07 invocation and matching explicit source/model mode')
    material = settings.received_material_inputs.selections[request.context.operation_id]
    if (material.source_task_sha256 != identity.key
            or [ref.key() for ref in material.material_basis_refs] != [ref.key() for ref in refs]):
        raise ValueError('V4 configuration changes original Supplier task or selected current material basis versions')
    files = [current, previous]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        if not isinstance(assembly, dict) or set(assembly) != {'contractor_input', 'material_basis'}:
            raise ValueError('V4 assembly requires original Contractor input and actual material basis files')
        for label in ('contractor_input', 'material_basis'):
            binding = assembly[label]
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()
                    or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
                raise ValueError('V4 assembly source requires its original path and raw SHA')
            item = read_source(current[0].parent / binding['path'])
            if item[1] != binding['file_sha256']:
                raise ValueError('V4 original Contractor input or material basis changed after assembly')
            files.append(item)
        if files[2][2] != {key: data[key] for key in ('run_id', 'contractor_organization_id', 'request', 'configuration')}:
            raise ValueError('V4 assembly substitutes original Contractor input or configuration')
        if not isinstance(files[3][2], list) or not files[3][2]:
            raise ValueError('V4 actual material basis file must contain the ordered selected projections')
        bases = [ContractorReceivedMaterialView.model_validate(row) for row in files[3][2]]
        expected = {'run_id': data['run_id'], 'organization_id': data['contractor_organization_id'],
            'supplier_organization_id': identity.organization_id, 'receiving_task_sha256': identity.key,
            'receiving_record_sha256': selected['record_sha256'], 'receiving_result_sha256': selected['result_sha256'],
            'receiving_source_reading_sha256': selected['reading_sha256']}
        if ([basis.ref.key() for basis in bases] != [ref.key() for ref in refs]
                or any(any(getattr(basis, key) != value for key, value in expected.items())
                    or not scope_covers(request.context.scope, basis.scope) for basis in bases)):
            raise ValueError('V4 material basis substitutes original Supplier, Contractor, scope or selected source provenance')
    return tuple(files), deepcopy(data), identity, request.model_dump(mode='json'), config.model_dump(mode='json'), offline


def build_v4_contractor_material_input(*, supplier_result_path, contractor_input_path, material_basis_path, output_path):
    """Assemble supplied originals without creating stock, release or construction input."""
    original_file, contractor_file, basis_file = (
        _read(supplier_result_path), _read(contractor_input_path), _read(material_basis_path))
    original, contractor = original_file[2], contractor_file[2]
    if (not isinstance(contractor, dict) or set(contractor) != {
            'run_id', 'contractor_organization_id', 'request', 'configuration'}):
        raise ValueError('V4 assembly requires complete explicit Contractor request and host configuration')
    request = RoleContractInvocation.model_validate(contractor['request'])
    config = RoleContractHostConfiguration.model_validate(contractor['configuration'])
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    if settings.received_material_inputs is None or request.context.operation_id not in settings.received_material_inputs.selections:
        raise ValueError('V4 assembly requires independently selected actual material basis references')
    material = settings.received_material_inputs.selections[request.context.operation_id]
    evidence = original['execution_evidence']
    data = {'schema_version': 'lifecycle-v4-contractor-material-input.v1', 'scenario_id': 'V4',
        'run_id': contractor['run_id'], 'contractor_organization_id': contractor['contractor_organization_id'],
        'source_mode': original['source_mode'], 'request': deepcopy(contractor['request']),
        'configuration': deepcopy(contractor['configuration']),
        'supplier_receiving': {'result_path': str(original_file[0]), 'result_file_sha256': original_file[1],
            'identity': deepcopy(evidence['identity']), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'material_basis_refs': [ref.model_dump(mode='json') for ref in material.material_basis_refs]},
        'assembly_sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in (('contractor_input', contractor_file), ('material_basis', basis_file))}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V4 assembled material configuration must be a new file')
    supplied_files = (original_file, contractor_file, basis_file)
    _prepare_data((destination, task_digest(data), data), captured_sources={item[0]: item for item in supplied_files})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in supplied_files):
        raise ValueError('V4 original material configuration sources changed during assembly')
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


def run_v4_contractor_material(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 execution selection must be an explicit boolean')
    files, data, original_identity, request, config, offline = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-contractor-material-plan.v1', 'scenario_id': 'V4',
        'run_id': data['run_id'], 'action_id': 'CONTRACTOR-A07', 'source_mode': data['source_mode'],
        'origin': 'synthetic' if offline else 'actual_input',
        'mode': 'execute_offline' if execute and offline else 'execute_formal' if execute else 'plan_only',
        'factory': _FACTORY, 'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'supplier_receiving': deepcopy(data['supplier_receiving']), 'allowed_choices': list(_CHOICES),
        'assembly_source_provenance': 'retained_file_hashes' if 'assembly_sources' in data else 'legacy_inline_only',
        'limitations': ['Supplier local response does not prove accepted receipt, usable stock or actual construction.',
            'Independent receiver must validate original receipt/inspection/use-release and actual Contractor inventory lineage.']}
    for name, value in (('input', data), ('supplier-result-input', files[1][2]),
            ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-contractor-material-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V4 current input or original Supplier evidence changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'contractor', offline=offline)
        evidence = result['execution_evidence']
        identity, task, reception = evidence['identity'], evidence['task'], evidence['received_material_input']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data['contractor_organization_id'],
            'role': 'Contractor', 'action_id': 'CONTRACTOR-A07', 'request_id': request['context']['operation_id'],
            'purpose': 'action', 'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        source = data['supplier_receiving']
        expected_reception = {'source_task_sha256': original_identity.key, 'source_record_sha256': source['record_sha256'],
            'source_result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'material_basis_refs': source['material_basis_refs'], 'execution_source_reading_sha256': evidence['source_reading_sha256']}
        if 'assembly_sources' in data:
            expected_reception['material_basis_sha256'] = task_digest([
                ContractorReceivedMaterialView.model_validate(row).model_dump(mode='json') for row in files[3][2]])
        if (result['source_mode'] != data['source_mode'] or result['action_id'] != 'CONTRACTOR-A07'
                or evidence['result_table'] != 'contractor_execution_results'
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or task['identity'] != identity or result['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result['result'])
                or not isinstance(reception, dict) or any(reception.get(key) != value for key, value in expected_reception.items())):
            raise ValueError('V4 Contractor outcome lacks original durable task/audit or selected Supplier material provenance')
        if result['result']['kind'] == 'completed':
            if (task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
                    or result['result']['payload']['choice'] not in _CHOICES):
                raise ValueError('V4 Contractor outcome changes original result or legal execution branch')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V4 incomplete material outcome must preserve original waiting or technical failure state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V4 original Supplier, Contractor input or material basis changed during execution')
        summary = {**plan, 'mode': 'executed_offline' if offline else 'executed_formal',
            'identity': deepcopy(identity), 'record_sha256': evidence['record_sha256'],
            'received_material_input': deepcopy(reception), 'result': deepcopy(result['result']),
            'limitations': ['Local Contractor decision does not create stock, use permission, allocation or completed work.',
                'Other V4 production, quality, logistics and refusal/rework branches still require final acceptance.']}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['result']['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--supplier-result', type=Path)
    parser.add_argument('--contractor-input', type=Path)
    parser.add_argument('--material-basis', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.supplier_result, args.contractor_input, args.material_basis)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --supplier-result, --contractor-input and --material-basis, without --input or --execute')
        build_v4_contractor_material_input(supplier_result_path=args.supplier_result, contractor_input_path=args.contractor_input,
            material_basis_path=args.material_basis, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    result = run_v4_contractor_material(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
