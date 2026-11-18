"""Plan or explicitly execute the formal V5 Contractor payment-reconciliation step."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.contractor_formal_application import ContractorFormalApplicationSettings
from integration.contractor_role_contract_host import ContractorRoleContractSettings, build_role_host
from integration.owner_payment_observation_files import validate_retained_payment_settlement
from integration.owner_payment_submission import OwnerPaymentExecutionObservation
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.contractor_role_contract_host:build_role_host'
_SCHEMA = 'lifecycle-v5-contractor-payment-formal-input.v2'
_LEGACY_SCHEMA = 'lifecycle-v5-contractor-payment-formal-input.v1'


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), data


def _prepare(input_path):
    """Read actual supplied files without source factories or native queries."""
    return _prepare_data(_read(input_path))


def _check_formal_payment_reception(settings, *, request, owner):
    """Check known formal declarations before constructing actual dependencies."""
    if settings.source_factory != 'integration.contractor_formal_application:build_sources':
        return
    formal = ContractorFormalApplicationSettings.model_validate(settings.source_settings)
    reader = formal.payment_reception
    if (formal.action_id != 'CONTRACTOR-A10' or reader is None
            or formal.client_version != settings.client_version or formal.model_version != settings.model_version
            or settings.source_version != formal.declared_source_version):
        raise ValueError('V5 formal Contractor reception requires matching versions and explicit payment reader settings')
    if (reader.recipient_context != request.context or reader.identity.as_dict() != owner['identity']
            or reader.source_record_sha256 != owner['record_sha256']
            or reader.source_result_sha256 != owner['result_sha256']
            or reader.source_reading_sha256 != owner['reading_sha256']
            or [ref.key() for ref in reader.execution_refs]
                != [Reference.model_validate(ref).key() for ref in owner['execution_refs']]
            or reader.sharing_authorized is not True):
        raise ValueError('V5 formal Contractor reception changes original payer identity, hashes, selection or current recipient')


def _prepare_data(current, *, captured_sources=None):
    data = current[2]
    fields = {'schema_version', 'scenario_id', 'run_id', 'contractor_organization_id',
        'owner_payment', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] not in {_SCHEMA, _LEGACY_SCHEMA} or data['scenario_id'] != 'V5'
            or not isinstance(data['contractor_organization_id'], str) or not data['contractor_organization_id'].strip()):
        raise ValueError('V5 Contractor input requires actual explicit request, configuration and original Owner payment provenance')
    retain_settlement = data['schema_version'] == _SCHEMA
    if retain_settlement and 'assembly_sources' not in data:
        raise ValueError('V5 Contractor v2 requires retained original result, issued, settlement and Contractor input selections')
    owner = data['owner_payment']
    if (not isinstance(owner, dict) or set(owner) != {'identity', 'record_sha256', 'result_sha256',
            'reading_sha256', 'execution_refs'} or not owner['execution_refs']):
        raise ValueError('V5 Contractor input requires original Owner task, source hashes and selected actual commands')
    identity = TaskIdentity(**owner['identity'])
    selected = [Reference.model_validate(ref) for ref in owner['execution_refs']]
    for field in ('record_sha256', 'result_sha256', 'reading_sha256'):
        value = owner[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V5 Contractor original Owner provenance requires explicit SHA256 digests')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    context = request.context
    payment = settings.received_payment_inputs
    if (identity.role != 'Owner' or identity.action_id != 'OWN-A06' or identity.purpose != 'action'
            or identity.run_id != data['run_id'] or context.run_id != data['run_id']
            or identity.organization_id == data['contractor_organization_id']
            or context.contract_ref.id != 'CONTRACTOR-A10' or context.execution_mode != 'llm'
            or request.execution_path not in {None, 'single_agent', 'organization_discussion'}
            or settings.action_id != 'CONTRACTOR-A10' or payment is None
            or context.operation_id not in payment.selections
            or context.operation_id == identity.request_id
            or len({(ref.kind, ref.id) for ref in selected}) != len(selected)
            or any(ref.kind != 'PaymentExecution' for ref in selected)):
        raise ValueError('V5 Contractor step requires a fresh formal invocation and original separate payer identity')
    selection = payment.selections[context.operation_id]
    selected_keys = [ref.key() for ref in selected]
    if (selection.source_task_sha256 != identity.key
            or [ref.key() for ref in selection.execution_refs] != selected_keys
            or not set(selected_keys) <= {Reference.model_validate(ref).key()
                for ref in request.action_input['execution_refs']}):
        raise ValueError('V5 Contractor selection changes original Owner task or declared actual execution references')
    _check_formal_payment_reception(settings, request=request, owner=owner)
    files = [current]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        labels = ('owner_result', 'issued_reception', 'contractor_input')
        if retain_settlement:
            labels += ('settlement',)
        if not isinstance(assembly, dict) or set(assembly) != set(labels):
            raise ValueError('V5 assembly requires original Owner result, issued observation and Contractor input files')
        for label in labels:
            binding = assembly[label]
            if label == 'settlement' and binding is None:
                continue
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()
                    or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
                raise ValueError('V5 assembly source requires original path and raw SHA256')
            source_path = (current[0].parent / binding['path']).resolve()
            item = captured_sources.get(source_path) if captured_sources is not None else None
            if item is None:
                item = _read(source_path)
            if item[1] != binding['file_sha256']:
                raise ValueError('V5 original payment assembly source changed')
            files.append(item)
        original, issued, contractor = (item[2] for item in files[1:4])
        evidence = original.get('execution_evidence', {})
        audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
        if (contractor != {key: data[key] for key in ('run_id', 'contractor_organization_id', 'request', 'configuration')}
                or original.get('run_id') != data['run_id'] or original.get('action_id') != 'OWN-A06'
                or original.get('source_mode') != 'formal' or evidence.get('identity') != identity.as_dict()
                or evidence.get('result_table') != 'owner_payment_results'
                or evidence.get('record_sha256') != owner['record_sha256']
                or evidence.get('source_reading_sha256') != owner['reading_sha256']
                or original.get('result', {}).get('kind') != 'completed'
                or original['result'].get('payload', {}).get('choice') != 'pay'
                or task_digest(original['result']) != owner['result_sha256']
                or task.get('identity') != identity.as_dict() or task.get('output') != original['result']
                or task.get('output_sha256') != owner['result_sha256']
                or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
                or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'OWN-A06',
                    'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                    'result_sha256': owner['result_sha256'], 'result_kind': 'completed'}.items())):
            raise ValueError('V5 assembly replaces original formal payer result/audit or Contractor configuration')
        expected = {'schema_version': 'owner-payment-issued-reception.v1', 'source_identity': identity.as_dict(),
            'source_record_sha256': owner['record_sha256'], 'source_result_sha256': owner['result_sha256'],
            'source_reading_sha256': owner['reading_sha256']}
        if (not isinstance(issued, dict) or set(issued) != {*expected, 'submission_receipt', 'payment_plan', 'observation'}
                or any(issued[key] != value for key, value in expected.items())):
            raise ValueError('V5 assembly substitutes original complete issued observation provenance')
        observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
        rows = {row.execution.ref.key(): row for row in observation.lines}
        if (len(rows) != len(observation.lines) or any(ref.key() not in rows for ref in selected)
                or any(rows[ref.key()].execution.organization_id != identity.organization_id
                    or rows[ref.key()].execution.beneficiary_id != data['contractor_organization_id']
                    or rows[ref.key()].execution.operation != 'pay' for ref in selected)):
            raise ValueError('V5 assembly changes selected original payer commands or Contractor beneficiary')
        if retain_settlement:
            validate_retained_payment_settlement(issued=issued,
                settlement=files[4][2] if len(files) == 5 else None,
                provenance={key: value for key, value in expected.items() if key != 'schema_version'},
                context=context)
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json')


def build_v5_contractor_payment_input(*, owner_result_path, issued_reception_path, contractor_input_path, output_path,
        settlement_path=None):
    """Freeze supplied originals; authentic native reception remains independently checked by the host."""
    originals = (_read(owner_result_path), _read(issued_reception_path), _read(contractor_input_path))
    if settlement_path is not None:
        originals += (_read(settlement_path),)
    original, _, contractor = (item[2] for item in originals[:3])
    if not isinstance(contractor, dict) or set(contractor) != {'run_id', 'contractor_organization_id', 'request', 'configuration'}:
        raise ValueError('V5 assembly requires explicit complete current Contractor input')
    request = RoleContractInvocation.model_validate(contractor['request'])
    settings = ContractorRoleContractSettings.model_validate(
        RoleContractHostConfiguration.model_validate(contractor['configuration']).settings)
    if settings.received_payment_inputs is None or request.context.operation_id not in settings.received_payment_inputs.selections:
        raise ValueError('V5 assembly requires explicit current original-command selection')
    selection = settings.received_payment_inputs.selections[request.context.operation_id]
    evidence = original['execution_evidence']
    data = {'schema_version': _SCHEMA, 'scenario_id': 'V5', **deepcopy(contractor),
        'owner_payment': {'identity': deepcopy(evidence['identity']), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'execution_refs': [ref.model_dump(mode='json') for ref in selection.execution_refs]},
        'assembly_sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in zip(('owner_result', 'issued_reception', 'contractor_input', 'settlement'), originals)}}
    data['assembly_sources'].setdefault('settlement', None)
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V5 assembled input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured_sources={item[0]: item for item in originals})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in originals):
        raise ValueError('V5 original files changed during input assembly')
    raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as stream:
        try:
            stream.write(raw)
        except BaseException:
            stream.close()
            destination.unlink()
            raise
    return data


def run_v5_contractor_payment(*, input_path, output_directory, execute=False):
    """Create a new reviewable plan; execution uses the original formal host once.

    Input contains actual sources/configuration, never a synthetic payment claim.
    --execute may invoke the application's explicitly configured model strategy.
    This entry only consumes receipts; it never sends or retries a payment.
    """
    if type(execute) is not bool:
        raise ValueError('V5 Contractor execution selection must be an explicit boolean')
    files, data, request, config = _prepare(input_path)
    retain_settlement = data['schema_version'] == _SCHEMA
    settlement_sha256 = files[4][2]['native_settlement_sha256'] if retain_settlement and len(files) == 5 else None
    path, raw_sha, _ = files[0]
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-contractor-payment-plan.v1', 'scenario_id': 'V5',
        'run_id': data['run_id'], 'action_id': 'CONTRACTOR-A10', 'factory': _FACTORY,
        'mode': 'execute_formal' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': raw_sha},
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'assembly_source_provenance': ('retained_execution_and_settlement_files' if retain_settlement
            else 'legacy_retained_execution_files' if 'assembly_sources' in data else 'legacy_inline_only'),
        'settlement_selection_pinned': retain_settlement,
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'contractor_organization_id': data['contractor_organization_id'], 'owner_payment': deepcopy(data['owner_payment']),
        'target_choice': 'reconcile', 'limitations': ['Plan does not authenticate native sources or prove beneficiary cash.',
            'Execution requires actual authorized source/model bindings and receiver validation; no payment transport occurs.']}
    if retain_settlement:
        plan['native_settlement_sha256'] = settlement_sha256
    else:
        plan['limitations'].append('Legacy v1 input does not retain or pin an original settlement file; reassemble explicitly for v2.')
    for name, value in (('input', data), ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    for label, item in zip(('owner-result-input', 'issued-reception-input', 'contractor-input', 'settlement-input'), files[1:]):
        atomic_json(directory / (label + '.json'), item[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-contractor-payment-attempt.v1', 'status': 'started',
        'input_sha256': raw_sha, 'request_sha256': plan['request_sha256'], 'configuration_sha256': plan['configuration_sha256']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 Contractor input or retained original payment evidence changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'contractor', offline=False)
        evidence = result['execution_evidence']
        identity, task = evidence['identity'], evidence['task']
        reception = evidence['received_payment_input']
        original = data['owner_payment']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data['contractor_organization_id'],
            'role': 'Contractor', 'action_id': 'CONTRACTOR-A10', 'request_id': request['context']['operation_id'],
            'purpose': 'action', 'input_sha256': task_digest(request['action_input']),
            'context_sha256': task_digest(request['context'])}
        expected_reception = {'source_identity': original['identity'], 'source_record_sha256': original['record_sha256'],
            'source_result_sha256': original['result_sha256'], 'source_reading_sha256': original['reading_sha256'],
            'execution_refs': original['execution_refs'], 'execution_source_reading_sha256': evidence['source_reading_sha256']}
        if 'assembly_sources' in data:
            expected_reception['issued_reception_sha256'] = task_digest(files[2][2])
        if retain_settlement:
            expected_reception['native_settlement_sha256'] = settlement_sha256
        if (result['source_mode'] != 'formal' or evidence['result_table'] != 'contractor_payment_results'
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or task['identity'] != identity
                or evidence['saved_audit']['result_sha256'] != task_digest(result['result'])
                or not isinstance(reception, dict)
                or any(key not in reception or reception[key] != value for key, value in expected_reception.items())):
            raise ValueError('V5 Contractor execution lacks original durable result or explicitly selected Owner payment provenance')
        if result['result']['kind'] == 'completed':
            payload = result['result']['payload']
            if (task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
                    or payload['choice'] != 'reconcile' or payload['execution_refs'] != original['execution_refs']):
                raise ValueError('V5 Contractor reconciliation changed its explicit original execution selection')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V5 Contractor pending/error result must preserve its original incomplete task state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 retained original payment or Contractor input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'result_kind': result['result']['kind'],
            'identity': deepcopy(identity), 'record_sha256': evidence['record_sha256'],
            'source_reading_sha256': evidence['source_reading_sha256'], 'received_payment_input': deepcopy(reception),
            'result': deepcopy(result['result']), 'limitations': [
                'Native authenticity and actual beneficiary credit were checked by the configured receiver; this step creates no cash.',
                'Local reconciliation output does not prove full PLAN or all lifecycle branches completed.']}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['result']['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--owner-result', type=Path)
    parser.add_argument('--issued-reception', type=Path)
    parser.add_argument('--contractor-input', type=Path)
    parser.add_argument('--settlement', type=Path,
        help='Original settlement query file; required for a fully final command group, absent for pending/unknown')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Execute the explicitly configured actual formal action once')
    args = parser.parse_args()
    assembly = (args.owner_result, args.issued_reception, args.contractor_input)
    if any(item is not None for item in assembly) or args.settlement is not None:
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --owner-result, --issued-reception and --contractor-input, without --input or --execute')
        build_v5_contractor_payment_input(owner_result_path=args.owner_result, issued_reception_path=args.issued_reception,
            contractor_input_path=args.contractor_input, output_path=args.output, settlement_path=args.settlement)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    result = run_v5_contractor_payment(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
