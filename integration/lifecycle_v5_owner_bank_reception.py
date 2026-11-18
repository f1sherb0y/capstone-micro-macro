"""Shared file assembly and explicit execution for declared formal Owner/Bank receptions."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.bank_role_contract_host import BankRoleContractSettings, build_role_host as build_bank_host
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.bank_arrangement_objects import OwnerFinancingAcceptanceReceiptView
from src.actions.contracts.bank_draw_objects import OwnerDrawRequestReceiptView
from src.actions.contracts.bank_objects import OwnerFinanceApplicationReceiptView
from src.actions.contracts.owner_financing_objects import FinancingApplicationDraft, OwnerFinancingOfferReceiptView
from src.actions.contracts.owner_payment_objects import OwnerBankExecutionReceptionView, OwnerPaymentArrangementReceiptView
from src.coordination.tasks import TaskIdentity, task_digest
from src.organization.registry import scope_covers


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_ROUTES = {
    'execution': {'prefix': 'lifecycle-v5-bank-execution-owner', 'action': 'BANK-A07', 'choices': {'reconcile'},
        'recipient': 'OWN-A06', 'recipient_table': 'owner_payment_results',
        'table': 'bank_execution_results', 'settings': 'bank_execution_inputs', 'evidence': 'bank_execution_input',
        'model': OwnerBankExecutionReceptionView, 'ref': 'reception_ref', 'digest': 'reception_sha256'},
    'arrangement': {'prefix': 'lifecycle-v5-bank-arrangement-owner', 'action': 'BANK-A05', 'choices': {'confirm'},
        'recipient': 'OWN-A06', 'recipient_table': 'owner_payment_results',
        'table': 'bank_arrangement_results', 'settings': 'payment_arrangement_inputs', 'evidence': 'payment_arrangement_input',
        'model': OwnerPaymentArrangementReceiptView, 'ref': 'receipt_ref', 'digest': 'receipt_sha256'},
    'offer': {'prefix': 'lifecycle-v5-bank-quote-owner', 'action': 'BANK-A04', 'choices': {'offer', 'conditional_offer'},
        'recipient': 'OWN-A05', 'recipient_table': 'owner_financing_results',
        'table': 'bank_quote_results', 'settings': 'financing_offer_inputs', 'evidence': 'financing_offer_input',
        'model': OwnerFinancingOfferReceiptView, 'ref': 'receipt_ref', 'digest': 'receipt_sha256'},
    'draw_request': {'prefix': 'lifecycle-v5-owner-draw-bank', 'action': 'OWN-A06', 'choices': {'draw_request'},
        'source_role': 'Owner', 'recipient': 'BANK-A06', 'recipient_role': 'Bank',
        'recipient_table': 'bank_draw_results', 'organization_field': 'bank_organization_id',
        'settings_type': BankRoleContractSettings, 'factory': build_bank_host,
        'factory_specification': 'integration.bank_role_contract_host:build_role_host',
        'source_names': ('owner_result', 'bank_input', 'reception'),
        'source_labels': ('owner-result-input', 'bank-input', 'reception-input'),
        'table': 'owner_payment_results', 'settings': 'owner_draw_request_inputs', 'evidence': 'owner_draw_request_input',
        'model': OwnerDrawRequestReceiptView, 'ref': 'receipt_ref', 'digest': 'receipt_sha256'},
    'application': {'prefix': 'lifecycle-v5-owner-application-bank', 'action': 'OWN-A05', 'choices': {'apply'},
        'source_role': 'Owner', 'recipient': 'BANK-A02', 'recipient_role': 'Bank',
        'recipient_table': 'bank_intake_results', 'organization_field': 'bank_organization_id',
        'settings_type': BankRoleContractSettings, 'factory': build_bank_host,
        'factory_specification': 'integration.bank_role_contract_host:build_role_host',
        'source_names': ('owner_result', 'bank_input', 'reception'),
        'source_labels': ('owner-result-input', 'bank-input', 'reception-input'),
        'table': 'owner_financing_results', 'settings': 'owner_application_inputs', 'evidence': 'owner_application_input',
        'model': OwnerFinanceApplicationReceiptView, 'ref': 'receipt_ref', 'digest': 'receipt_sha256',
        'reading_provenance': False},
    'acceptance': {'prefix': 'lifecycle-v5-owner-acceptance-bank', 'action': 'OWN-A05', 'choices': {'accept_offer'},
        'source_role': 'Owner', 'recipient': 'BANK-A05', 'recipient_role': 'Bank',
        'recipient_table': 'bank_arrangement_results', 'organization_field': 'bank_organization_id',
        'settings_type': BankRoleContractSettings, 'factory': build_bank_host,
        'factory_specification': 'integration.bank_role_contract_host:build_role_host',
        'source_names': ('owner_result', 'bank_input', 'reception'),
        'source_labels': ('owner-result-input', 'bank-input', 'reception-input'),
        'table': 'owner_financing_results', 'settings': 'owner_acceptance_inputs', 'evidence': 'owner_acceptance_input',
        'model': OwnerFinancingAcceptanceReceiptView, 'ref': 'receipt_ref', 'digest': 'receipt_sha256'},
}


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare_data(current, *, captured=None, route='execution'):
    declaration = _ROUTES[route]
    organization_field = declaration.get('organization_field', 'owner_organization_id')
    recipient_fields = {'run_id', organization_field, 'request', 'configuration'}
    source_names = declaration.get('source_names', ('bank_result', 'owner_input', 'reception'))
    data = current[2]
    if (set(data) != recipient_fields | {'schema_version', 'scenario_id', 'sources'}
            or data['schema_version'] != declaration['prefix'] + '-input.v1' or data['scenario_id'] != 'V5'
            or not isinstance(data[organization_field], str) or not data[organization_field].strip()
            or not isinstance(data['sources'], dict)
            or set(data['sources']) != set(source_names)):
        raise ValueError('V5 Bank reception requires current Owner input and three original source files')
    files = [current]
    for label in source_names:
        binding = data['sources'][label]
        if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                or not isinstance(binding['path'], str) or not binding['path'].strip()
                or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
            raise ValueError('V5 original source binding requires a path and raw SHA256')
        path = (current[0].parent / binding['path']).resolve()
        item = captured.get(path) if captured is not None else None
        if item is None:
            item = _read(path)
        if item[1] != binding['file_sha256']:
            raise ValueError('V5 original Bank reception source changed')
        files.append(item)
    original, owner, receipt_data = (item[2] for item in files[1:])
    if owner != {key: data[key] for key in recipient_fields}:
        raise ValueError('V5 reception replaces original current Owner input or configuration')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = declaration.get('settings_type', OwnerRoleContractSettings).model_validate(config.settings)
    selected_inputs = getattr(settings, declaration['settings'])
    context = request.context
    if (context.run_id != data['run_id'] or context.contract_ref.id != declaration['recipient']
            or context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != declaration['recipient'] or selected_inputs is None
            or context.operation_id not in selected_inputs.selections):
        raise ValueError('V5 Bank reception requires its formal Owner action and explicit current original Bank selection')
    selection = selected_inputs.selections[context.operation_id]
    evidence, result = original['execution_evidence'], original['result']
    identity = TaskIdentity(**evidence['identity'])
    task, audit = evidence['task'], evidence['saved_audit']
    if (identity.key != selection.source_task_sha256 or identity.run_id != data['run_id']
            or identity.role != declaration.get('source_role', 'Bank') or identity.action_id != declaration['action']
            or identity.purpose != 'action'
            or identity.organization_id == data[organization_field] or identity.request_id == context.operation_id
            or original['run_id'] != data['run_id'] or original['action_id'] != declaration['action']
            or original['source_mode'] != 'formal' or evidence['result_table'] != declaration['table']
            or result['kind'] != 'completed' or result['payload']['choice'] not in declaration['choices']
            or task['identity'] != identity.as_dict() or task['output'] != result
            or task['output_sha256'] != task_digest(result)
            or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original['audit'] != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': declaration['action'],
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': task_digest(result), 'result_kind': 'completed'}.items())):
        raise ValueError('V5 Bank reception changes original formal source task/result/audit')
    reception = declaration['model'].model_validate(receipt_data)
    receipt_sha = task_digest(reception.model_dump(mode='json'))
    expected = {'source_task_sha256': identity.key, 'source_record_sha256': evidence['record_sha256'],
        'source_result_sha256': task_digest(result), 'source_reading_sha256': evidence['source_reading_sha256']}
    if (any(getattr(reception, key) != value for key, value in expected.items())
            or reception.run_id != data['run_id'] or reception.author_organization_id != identity.organization_id
            or reception.recipient_organization_id != data[organization_field]
            or reception.ref != getattr(selection, declaration['ref'])
            or getattr(selection, declaration['digest']) != receipt_sha
            or not scope_covers(context.scope, reception.scope) or not reception.effective_window.contains(context.business_time)):
        raise ValueError('V5 reception changes retained original Bank/Owner relation, command selection or observation digest')
    if route == 'execution':
        if (reception.bank_execution_ref.model_dump(mode='json') not in result['payload']['execution_refs']
                or reception.owner_execution_ref.model_dump(mode='json') not in request.action_input['pending_execution_refs']):
            raise ValueError('V5 execution reception changes original Bank/Owner command selection')
    elif route == 'arrangement':
        if (reception.arrangement_ref.model_dump(mode='json') not in request.action_input['arrangement_refs']
                or reception.confirmed_conditions_sha256 != task_digest(result['payload']['conditions'])):
            raise ValueError('V5 arrangement reception changes selected facility or original confirmed conditions')
    elif route == 'offer':
        if (reception.offer_ref.model_dump(mode='json') not in request.action_input['offers']
                or reception.reservation_policy_ref.model_dump(mode='json') != result['payload']['reservation_policy_ref']):
            raise ValueError('V5 offer reception changes selected offer or original reservation policy')
    elif route == 'draw_request':
        if (reception.draw_request_ref.model_dump(mode='json') != request.action_input['draw_request_ref']
                or result['payload']['arrangement_ref'] != request.action_input['arrangement_ref']
                or not reception.transfer_lines
                or any(line.beneficiary_id != result['payload']['beneficiary_id'] for line in reception.transfer_lines)):
            raise ValueError('V5 draw reception changes original request, facility or transfer beneficiary')
    elif route == 'application':
        draft = FinancingApplicationDraft.model_validate(result['payload']['application']).model_dump(mode='json')
        if (reception.application_ref.model_dump(mode='json') != request.action_input['application_ref']
                or draft['borrower_id'] != identity.organization_id or draft['lender_id'] != data[organization_field]
                or draft['scope_ref'] != reception.scope.model_dump(mode='json')
                or any(request.action_input.get(key) != value for key, value in draft.items()
                    if key not in {'lender_id', 'scope_ref'})):
            raise ValueError('V5 application reception replaces original complete draft, lender or borrower')
    elif route == 'acceptance':
        if (reception.offer_ref.model_dump(mode='json') != result['payload']['offer_ref']
                or reception.offer_ref.model_dump(mode='json') != request.action_input['offer_ref']
                or reception.acceptance_ref.model_dump(mode='json') != request.action_input['borrower_acceptance_ref']):
            raise ValueError('V5 acceptance reception replaces original offer version or independent borrower acceptance')
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), {
        **expected, declaration['ref']: reception.ref.model_dump(mode='json'), declaration['digest']: receipt_sha}


def build_input(*, source_result_path, recipient_input_path, reception_path, output_path, route):
    declaration = _ROUTES[route]
    recipient_fields = {'run_id', declaration.get('organization_field', 'owner_organization_id'), 'request', 'configuration'}
    source_names = declaration.get('source_names', ('bank_result', 'owner_input', 'reception'))
    originals = (_read(source_result_path), _read(recipient_input_path), _read(reception_path))
    owner = originals[1][2]
    if set(owner) != recipient_fields:
        raise ValueError('V5 assembly requires complete explicit current recipient input')
    data = {'schema_version': _ROUTES[route]['prefix'] + '-input.v1', 'scenario_id': 'V5', **deepcopy(owner),
        'sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in zip(source_names, originals)}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V5 Bank reception input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured={item[0]: item for item in originals}, route=route)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in originals):
        raise ValueError('V5 original Bank reception files changed during assembly')
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


def run_reception(*, input_path, output_directory, execute=False, route):
    declaration = _ROUTES[route]
    prepared = _prepare_data(_read(input_path), route=route)
    return run_prepared(prepared, declaration=declaration, output_directory=output_directory, execute=execute)


def run_prepared(prepared, *, declaration, output_directory, execute=False):
    """Shared execution of a route's already checked retained files and provenance."""
    if type(execute) is not bool:
        raise ValueError('V5 Bank reception execution selection must be an explicit boolean')
    files, data, request, config, provenance = prepared
    recipient_role = declaration.get('recipient_role', 'Owner')
    organization_field = declaration.get('organization_field', 'owner_organization_id')
    factory = declaration.get('factory', build_role_host)
    specification = declaration.get('factory_specification', _FACTORY)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': declaration['prefix'] + '-plan.v1', 'scenario_id': 'V5',
        'run_id': data['run_id'], 'action_id': declaration['recipient'], 'factory': specification,
        'mode': 'execute_formal' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        declaration['evidence']: deepcopy(provenance),
        'limitations': ['Retained Bank decisions and reception files do not independently prove signature, capacity, cash or debt effects.',
            'Original host and independent receiver validators authenticate the actual terms, permissions and financial mapping.']}
    for name, value in (('input', data), ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    labels = declaration.get('source_labels', ('bank-result-input', 'owner-input', 'reception-input'))
    for index, item in enumerate(files[1:]):
        label = labels[index] if index < len(labels) else f'source-{index + 1}'
        atomic_json(directory / (label + '.json'), item[2])
    if not execute:
        return plan
    attempt = {'schema_version': declaration['prefix'] + '-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 original Bank reception files changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=factory,
            specification=specification, output_directory=directory / recipient_role.lower(), offline=False)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_provenance = deepcopy(provenance)
        if declaration.get('reading_provenance', True):
            expected_provenance['execution_source_reading_sha256'] = evidence['source_reading_sha256']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data[organization_field],
            'role': recipient_role, 'action_id': declaration['recipient'], 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'formal' or output['action_id'] != declaration['recipient']
                or evidence['result_table'] != declaration['recipient_table'] or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or evidence[declaration['evidence']] != expected_provenance):
            raise ValueError('V5 Bank reception output changes original durable result or actual retained reception')
        if result['kind'] == 'completed':
            if task['output'] != result or task['output_sha256'] != task_digest(result):
                raise ValueError('V5 Owner output differs from its original durable task')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V5 incomplete reception must preserve original pending/error state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V5 original Bank reception files changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], declaration['evidence']: deepcopy(evidence[declaration['evidence']]),
            'result_kind': result['kind'], 'result': deepcopy(result)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main(route):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    source_option, recipient_option = ('--owner-result', '--bank-input') if _ROUTES[route].get('source_role') == 'Owner' else ('--bank-result', '--owner-input')
    parser.add_argument(source_option, dest='source_result', type=Path)
    parser.add_argument(recipient_option, dest='recipient_input', type=Path)
    parser.add_argument('--reception', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.source_result, args.recipient_input, args.reception)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error(f'Assembly requires {source_option}, {recipient_option} and --reception, without --input or --execute')
        build_input(source_result_path=args.source_result, recipient_input_path=args.recipient_input,
            reception_path=args.reception, output_path=args.output, route=route)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly inputs')
    print(run_reception(input_path=args.input, output_directory=args.output, execute=args.execute, route=route)['mode'])
