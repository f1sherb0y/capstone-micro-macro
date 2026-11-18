"""Freeze actual complete pay/repay observations for a formal current Owner reconciliation."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.owner_payment_observation_files import validate_retained_payment_settlement
from integration.owner_payment_submission import OwnerPaymentExecutionObservation
from integration.owner_formal_application import OwnerFormalApplicationSettings
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_SCHEMA = 'lifecycle-v5-own-payment-reconciliation-input.v1'
_OWNER_FIELDS = {'run_id', 'owner_organization_id', 'request', 'configuration'}


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _binding(item):
    return {'path': str(item[0]), 'file_sha256': item[1]}


def _formal_payment_reception(settings):
    """Check the known formal factory declaration without loading dependencies."""
    if settings.source_factory != 'integration.owner_formal_application:build_sources':
        return None
    formal = OwnerFormalApplicationSettings.model_validate(settings.source_settings)
    routes = [] if formal.submission is None else formal.submission.routes
    payment = next((route for route in routes if route.action_id == 'OWN-A06'), None)
    if (formal.action_id != 'OWN-A06' or formal.payment_reception is None
            or formal.client_version != settings.client_version or formal.model_version != settings.model_version
            or settings.source_version != formal.declared_source_version
            or payment is None or not payment.native_payment_execution or not payment.native_payment_settlement
            or not payment.supported_choices or not set(payment.supported_choices) <= {'pay', 'repay'}):
        raise ValueError('V5 formal reception requires matching source/client/model versions, declared history and native settlement route')
    return formal


def _prepare_data(current, *, captured=None):
    data = current[2]
    if (set(data) != _OWNER_FIELDS | {'schema_version', 'scenario_id', 'payments', 'assembly_sources'}
            or data['schema_version'] != _SCHEMA or data['scenario_id'] != 'V5'
            or not isinstance(data['owner_organization_id'], str) or not data['owner_organization_id'].strip()
            or not isinstance(data['payments'], list) or not data['payments']):
        raise ValueError('V5 own reconciliation requires actual current Owner input and original complete payment groups')
    files = [current]

    def retained(binding):
        if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                or not isinstance(binding['path'], str) or not binding['path'].strip()
                or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
            raise ValueError('V5 retained observation requires an original file path and raw SHA256')
        path = (current[0].parent / binding['path']).resolve()
        item = captured.get(path) if captured is not None else None
        if item is None:
            item = _read(path)
        if item[1] != binding['file_sha256']:
            raise ValueError('V5 retained original payment source changed')
        files.append(item)
        return item

    assembly = data['assembly_sources']
    if not isinstance(assembly, dict) or set(assembly) != {'owner_input', 'payment_sources'}:
        raise ValueError('V5 own reconciliation must retain original Owner input and payment source selection')
    owner_file, selection_file = retained(assembly['owner_input']), retained(assembly['payment_sources'])
    if owner_file[2] != {key: data[key] for key in _OWNER_FIELDS}:
        raise ValueError('V5 own reconciliation replaces current Owner input or configuration')
    selection_data = selection_file[2]
    if (set(selection_data) != {'schema_version', 'payments'}
            or selection_data['schema_version'] != 'lifecycle-v5-own-payment-observation-files.v1'
            or not isinstance(selection_data['payments'], list)
            or len(selection_data['payments']) != len(data['payments'])):
        raise ValueError('V5 own reconciliation replaces original payment file selections')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    formal_reception = _formal_payment_reception(settings)
    context = request.context
    if (context.run_id != data['run_id'] or context.contract_ref.id != 'OWN-A06'
            or context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'OWN-A06' or settings.payment_execution_inputs is None
            or context.operation_id not in settings.payment_execution_inputs.selections):
        raise ValueError('V5 own reconciliation requires a formal current Owner A06 and explicit original payment selections')
    selections = settings.payment_execution_inputs.selections[context.operation_id].payments
    if len(selections) != len(data['payments']):
        raise ValueError('V5 own reconciliation omits or adds an original selected payment group')
    provenance, all_refs, tasks = [], set(), set()
    for source, declared, selected in zip(data['payments'], selection_data['payments'], selections):
        fields = {'owner_result', 'issued_reception', 'settlement'}
        if (not isinstance(source, dict) or set(source) != fields
                or not isinstance(declared, dict) or set(declared) != fields):
            raise ValueError('V5 own payment group requires original result, execution observation and optional settlement')
        items = {}
        for label in ('owner_result', 'issued_reception', 'settlement'):
            if source[label] is None:
                if label != 'settlement' or declared[label] is not None:
                    raise ValueError('Only uncertain payment settlement may be absent')
                continue
            items[label] = retained(source[label])
            if (not isinstance(declared[label], str) or not declared[label].strip()
                    or (selection_file[0].parent / declared[label]).resolve()
                        != items[label][0]):
                raise ValueError('V5 original payment selection changes a retained file path')
        original, issued = items['owner_result'][2], items['issued_reception'][2]
        evidence = original['execution_evidence']
        identity = TaskIdentity(**evidence['identity'])
        if formal_reception is not None:
            declared_identity = formal_reception.payment_reception.histories.get(identity.key)
            if declared_identity is None or declared_identity.as_dict() != identity.as_dict():
                raise ValueError('V5 formal reception replaces or omits the original retained payment TaskIdentity')
        audit, task, result = evidence['saved_audit'], evidence['task'], original['result']
        if (identity.key != selected.source_task_sha256 or identity.key in tasks
                or identity.organization_id != data['owner_organization_id'] or identity.run_id != data['run_id']
                or identity.role != 'Owner' or identity.action_id != 'OWN-A06' or identity.purpose != 'action'
                or identity.request_id == context.operation_id or original['run_id'] != data['run_id']
                or original['action_id'] != 'OWN-A06' or original['source_mode'] != 'formal'
                or evidence['result_table'] != 'owner_payment_results' or result['kind'] != 'completed'
                or result['payload']['choice'] not in {'pay', 'repay'} or task['identity'] != identity.as_dict()
                or task['output'] != result or task['output_sha256'] != task_digest(result)
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or original['audit'] != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
                or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'OWN-A06',
                    'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                    'result_sha256': task_digest(result), 'result_kind': 'completed'}.items())):
            raise ValueError('V5 own reconciliation substitutes original same-Owner formal task/result/audit')
        expected = {'source_identity': identity.as_dict(), 'source_record_sha256': evidence['record_sha256'],
            'source_result_sha256': task_digest(result), 'source_reading_sha256': evidence['source_reading_sha256']}
        if (not isinstance(issued, dict) or set(issued) != {'schema_version', *expected,
                'submission_receipt', 'payment_plan', 'observation'}
                or issued['schema_version'] != 'owner-payment-issued-reception.v1'
                or any(issued[key] != value for key, value in expected.items())):
            raise ValueError('V5 own reconciliation changes original complete issued observation provenance')
        observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
        refs = [row.execution.ref for row in observation.lines]
        # Concrete PaymentExecution refs and generic transport References are
        # different Pydantic classes. Compare their full business identities,
        # retaining kind and version, rather than model-instance equality.
        ref_keys = [ref.key() for ref in refs]
        selected_keys = [ref.key() for ref in selected.execution_refs]
        if (len(set(ref_keys)) != len(ref_keys) or len(set(selected_keys)) != len(selected_keys)
                or set(ref_keys) != set(selected_keys) or all_refs.intersection(ref_keys)
                or any(row.execution.organization_id != identity.organization_id
                    or row.execution.operation != result['payload']['choice'] for row in observation.lines)):
            raise ValueError('V5 own reconciliation repeats, substitutes or omits an original complete command group')
        settlement_sha = validate_retained_payment_settlement(issued=issued,
            settlement=items['settlement'][2] if 'settlement' in items else None,
            provenance=expected, context=context)
        tasks.add(identity.key)
        all_refs.update(ref_keys)
        provenance.append({**expected, 'execution_refs': [ref.model_dump(mode='json') for ref in selected.execution_refs],
            'issued_reception_sha256': task_digest(issued), 'native_settlement_sha256': settlement_sha})
    pending = [Reference.model_validate(ref).key() for ref in request.action_input['pending_execution_refs']]
    if not all_refs <= set(pending):
        raise ValueError('V5 own payment observations are outside the current pending execution inputs')
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), provenance


def build_v5_own_payment_reconciliation_input(*, owner_input_path, payment_sources_path, output_path):
    owner_file, selection_file = _read(owner_input_path), _read(payment_sources_path)
    owner, selection = owner_file[2], selection_file[2]
    if set(owner) != _OWNER_FIELDS or not isinstance(selection.get('payments'), list):
        raise ValueError('V5 assembly requires complete Owner input and explicit original payment file groups')
    captured = {owner_file[0]: owner_file, selection_file[0]: selection_file}
    payments = []
    for group in selection['payments']:
        if not isinstance(group, dict) or set(group) != {'owner_result', 'issued_reception', 'settlement'}:
            raise ValueError('V5 assembly requires original result/issued/optional settlement file paths')
        row = {}
        for label, path in group.items():
            if path is None and label == 'settlement':
                row[label] = None
            else:
                if not isinstance(path, str) or not path.strip():
                    raise ValueError('V5 original observation path must be explicit')
                item = _read(selection_file[0].parent / path)
                if item[0] in captured and captured[item[0]] != item:
                    raise ValueError('V5 source file changed during assembly')
                captured[item[0]] = item
                row[label] = _binding(item)
        payments.append(row)
    data = {'schema_version': _SCHEMA, 'scenario_id': 'V5', **deepcopy(owner), 'payments': payments,
        'assembly_sources': {'owner_input': _binding(owner_file), 'payment_sources': _binding(selection_file)}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V5 own reconciliation input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured=captured)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in captured.values()):
        raise ValueError('V5 original files changed during assembly')
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


def run_v5_own_payment_reconciliation(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V5 own reconciliation execution selection must be an explicit boolean')
    files, data, request, config, provenance = _prepare_data(_read(input_path))
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-own-payment-reconciliation-plan.v1', 'scenario_id': 'V5',
        'run_id': data['run_id'], 'action_id': 'OWN-A06', 'factory': _FACTORY,
        'mode': 'execute_formal' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'payments': deepcopy(provenance), 'target_choice': 'reconcile',
        'limitations': ['Retained files do not independently authenticate actual native financial effects.',
            'The original host requires authorized source readers and independent complete financial mapping validators.']}
    for name, value in (('input', data), ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    for index, item in enumerate(files[1:], 1):
        atomic_json(directory / f'source-{index}.json', item[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-own-payment-reconciliation-attempt.v1',
        'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 original own payment input changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=False)
        evidence = result['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data['owner_organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A06', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        reception = evidence['payment_execution_input']
        if (result['source_mode'] != 'formal' or result['action_id'] != 'OWN-A06'
                or evidence['result_table'] != 'owner_payment_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or result['audit'] != [audit] or audit['result_sha256'] != task_digest(result['result'])
                or reception != {'payments': provenance, 'execution_source_reading_sha256': evidence['source_reading_sha256']}):
            raise ValueError('V5 own reconciliation changes original durable result or retained execution/settlement evidence')
        if result['result']['kind'] == 'completed':
            payload = result['result']['payload']
            if (task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
                    or payload['choice'] != 'reconcile'
                    or payload['execution_refs'] != request['action_input']['pending_execution_refs']):
                raise ValueError('V5 own reconciliation changes its original current pending execution selection')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V5 incomplete reconciliation must retain original pending/error state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 original own payment input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'payment_execution_input': deepcopy(reception),
            'result_kind': result['result']['kind'], 'result': deepcopy(result['result'])}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['result']['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--owner-input', type=Path)
    parser.add_argument('--payment-sources', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.owner_input is not None or args.payment_sources is not None:
        if args.input is not None or args.execute or args.owner_input is None or args.payment_sources is None:
            parser.error('Assembly requires --owner-input and --payment-sources, without --input or --execute')
        build_v5_own_payment_reconciliation_input(owner_input_path=args.owner_input,
            payment_sources_path=args.payment_sources, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or both original assembly inputs')
    print(run_v5_own_payment_reconciliation(input_path=args.input,
        output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
