"""Shared retained-file flow for original same-Bank review, draw and execution lineage."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from integration.bank_credit_handoff import BankCreditHandoffBasisView
from integration.bank_draw_handoff import BankDrawHandoffBasisView
from integration.bank_execution_reception import BankExecutionReceptionSettings
from integration.bank_intake_handoff import BankIntakeHandoffBasisView, BankIntakeRecordView
from integration.bank_role_contract_host import BankRoleContractSettings, build_role_host
from integration.lifecycle_v5_owner_bank_reception import _read, run_prepared
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from src.actions.contracts.bank_execution_objects import BankExecutionApprovalView, BankExecutionArrangementView
from src.actions.contracts.bank_quote_objects import QuoteCreditAssessmentView, QuoteRecordedReviewView, projection_digest
from src.coordination.tasks import TaskIdentity, task_digest
from src.organization.registry import scope_covers


_SCHEMA = 'lifecycle-v5-bank-intake-credit-input.v1'
_BANK_FIELDS = {'run_id', 'bank_organization_id', 'request', 'configuration'}
_LABELS = ('intake_result', 'bank_input', 'intake_basis', 'native_intake')
_DECLARATION = {'prefix': 'lifecycle-v5-bank-intake-credit', 'recipient': 'BANK-A03', 'recipient_role': 'Bank',
    'recipient_table': 'bank_credit_results', 'organization_field': 'bank_organization_id',
    'factory': build_role_host, 'factory_specification': 'integration.bank_role_contract_host:build_role_host',
    'evidence': 'intake_input', 'reading_provenance': False,
    'source_labels': ('intake-result-input', 'bank-input', 'intake-basis-input', 'native-intake-input')}
_ROUTES = {
    'intake': {'prefix': 'intake', 'action': 'BANK-A02', 'choice': 'accept_for_review',
        'table': 'bank_intake_results', 'settings': 'intake_inputs', 'labels': _LABELS, 'declaration': _DECLARATION},
    'credit': {'prefix': 'credit', 'action': 'BANK-A03', 'choice': None, 'table': 'bank_credit_results',
        'settings': 'credit_inputs', 'labels': ('credit_result', 'bank_input', 'credit_basis', 'assessment', 'recorded_review'),
        'declaration': {**_DECLARATION, 'prefix': 'lifecycle-v5-bank-credit-quote', 'recipient': 'BANK-A04',
            'recipient_table': 'bank_quote_results', 'evidence': 'credit_input',
            'source_labels': ('credit-result-input', 'bank-input', 'credit-basis-input', 'assessment-input', 'recorded-review-input')}},
    'draw': {'prefix': 'draw', 'action': 'BANK-A06', 'choice': 'approve_draw', 'table': 'bank_draw_results',
        'settings': 'draw_approval_inputs', 'labels': ('draw_result', 'bank_input', 'draw_basis', 'approval', 'execution_arrangement'),
        'declaration': {**_DECLARATION, 'prefix': 'lifecycle-v5-bank-draw-execution', 'recipient': 'BANK-A07',
            'recipient_table': 'bank_execution_results', 'evidence': 'draw_approval_input',
            'source_labels': ('draw-result-input', 'bank-input', 'draw-basis-input', 'approval-input', 'execution-arrangement-input')}},
    'execution': {'prefix': 'execution', 'action': 'BANK-A07', 'choice': 'execute', 'table': 'bank_execution_results',
        'settings': 'execution_receipt_inputs', 'labels': ('execution_result', 'bank_input', 'observation'),
        'declaration': {**_DECLARATION, 'prefix': 'lifecycle-v5-bank-execution-reconcile', 'recipient': 'BANK-A07',
            'recipient_table': 'bank_execution_results', 'evidence': 'execution_receipt_input',
            'source_labels': ('execution-result-input', 'bank-input', 'observation-input')}},
}


def _prepare_data(current, *, captured=None, route='intake'):
    specification = _ROUTES[route]
    declaration = specification['declaration']
    data = current[2]
    if (set(data) != _BANK_FIELDS | {'schema_version', 'scenario_id', 'sources'}
            or data['schema_version'] != declaration['prefix'] + '-input.v1' or data['scenario_id'] != 'V5'
            or not isinstance(data['bank_organization_id'], str) or not data['bank_organization_id'].strip()
            or not isinstance(data['sources'], dict) or set(data['sources']) != set(specification['labels'])):
        raise ValueError('V5 internal Bank input requires every declared original result, native observation and current input')
    files = [current]
    for label in specification['labels']:
        binding = data['sources'][label]
        if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                or not isinstance(binding['path'], str) or not binding['path'].strip()
                or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
            raise ValueError('V5 original Bank source requires its file path and raw SHA256')
        path = (current[0].parent / binding['path']).resolve()
        item = captured.get(path) if captured is not None else None
        if item is None:
            item = _read(path)
        if item[1] != binding['file_sha256']:
            raise ValueError('V5 retained original Bank source file changed')
        files.append(item)
    original, bank, basis_data = (item[2] for item in files[1:4])
    if bank != {key: data[key] for key in _BANK_FIELDS}:
        raise ValueError('V5 internal input replaces original current Bank input/configuration')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = BankRoleContractSettings.model_validate(config.settings)
    selected_inputs = getattr(settings, specification['settings'])
    context = request.context
    if (context.run_id != data['run_id'] or context.contract_ref.id != declaration['recipient']
            or context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != declaration['recipient'] or selected_inputs is None
            or context.operation_id not in selected_inputs.selections):
        raise ValueError('V5 internal input requires the route\'s formal Bank action and explicit original source selection')
    selected = selected_inputs.selections[context.operation_id]
    evidence, result = original['execution_evidence'], original['result']
    identity = TaskIdentity(**evidence['identity'])
    task, audit = evidence['task'], evidence['saved_audit']
    selected_history = (identity.key == selected.source_task_sha256 if route == 'execution'
        else identity == getattr(selected, specification['prefix'] + '_identity'))
    if (not selected_history or identity.run_id != data['run_id']
            or identity.organization_id != data['bank_organization_id'] or identity.role != 'Bank'
            or identity.action_id != specification['action'] or identity.purpose != 'action' or identity.request_id == context.operation_id
            or original['run_id'] != data['run_id'] or original['action_id'] != specification['action']
            or original['source_mode'] != 'formal' or evidence['result_table'] != specification['table']
            or result['kind'] != 'completed'
            or specification['choice'] is not None and result['payload']['choice'] != specification['choice']
            or task['identity'] != identity.as_dict() or task['output'] != result or task['output_sha256'] != task_digest(result)
            or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original['audit'] != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': specification['action'],
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': task_digest(result), 'result_kind': 'completed'}.items())):
        raise ValueError('V5 internal input changes the route\'s original same-Bank formal task/result/audit')
    if route == 'execution':
        provenance = _execution_provenance(request, identity, evidence, result, basis_data)
        return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), provenance
    if route in {'credit', 'draw'}:
        validator = _credit_provenance if route == 'credit' else _draw_provenance
        provenance = validator(data, request, selected, identity, evidence, result, audit, files)
        return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), provenance
    basis = BankIntakeHandoffBasisView.model_validate(basis_data)
    native = BankIntakeRecordView.model_validate(files[4][2])
    expected = {'intake_task_sha256': identity.key, 'intake_record_sha256': evidence['record_sha256'],
        'intake_input_sha256': identity.input_sha256, 'intake_context_sha256': identity.context_sha256,
        'intake_result_sha256': task_digest(result), 'intake_audit_sha256': task_digest(audit),
        'intake_source_reading_sha256': evidence['source_reading_sha256'],
        'native_record_sha256': task_digest(native.model_dump(mode='json'))}
    if (any(getattr(basis, key) != value for key, value in expected.items()) or basis.ref != selected.basis_ref
            or basis.native_record_ref != native.ref
            or any(row.run_id != data['run_id'] or row.organization_id != data['bank_organization_id'] for row in (basis, native))
            or basis.scope != native.scope or not scope_covers(context.scope, basis.scope)
            or native.as_of != context.business_time
            or native.application_ref.model_dump(mode='json') != request.action_input['application_ref']
            or native.product_ref.model_dump(mode='json') != request.action_input['product_ref']
            or result['payload']['application_ref'] != request.action_input['application_ref']
            or result['payload']['product_ref'] != request.action_input['product_ref']
            or [ref.model_dump(mode='json') for ref in native.required_condition_refs] != result['payload']['required_condition_refs']):
        raise ValueError('V5 credit lineage changes original native intake, review task, application, product or conditions')
    provenance = {'kind': 'prepared', 'source_mode': 'formal', 'intake_identity': identity.as_dict(),
        'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
            'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'review_task_id': native.review_task_id, 'native_event_id': native.native_event_id}}
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), provenance


def _credit_provenance(data, request, selected, identity, evidence, result, audit, files):
    basis = BankCreditHandoffBasisView.model_validate(files[3][2])
    assessment = QuoteCreditAssessmentView.model_validate(files[4][2])
    recorded = QuoteRecordedReviewView.model_validate(files[5][2])
    expected = {'credit_task_sha256': identity.key, 'credit_record_sha256': evidence['record_sha256'],
        'credit_input_sha256': identity.input_sha256, 'credit_context_sha256': identity.context_sha256,
        'credit_result_sha256': task_digest(result), 'credit_audit_sha256': task_digest(audit),
        'credit_source_reading_sha256': evidence['source_reading_sha256'],
        'assessment_sha256': projection_digest(assessment), 'recorded_decision_sha256': projection_digest(recorded)}
    if (any(getattr(basis, key) != value for key, value in expected.items()) or basis.ref != selected.basis_ref
            or basis.run_id != data['run_id'] or basis.organization_id != data['bank_organization_id']
            or basis.assessment_ref != assessment.ref or basis.recorded_decision_ref != recorded.ref
            or assessment.recorded_decision_ref != recorded.ref
            or assessment.ref.model_dump(mode='json') != request.action_input['assessment_ref']
            or assessment.source_run_id != data['run_id'] or recorded.source_run_id != data['run_id']
            or assessment.lender_id != data['bank_organization_id'] or recorded.organization_id != data['bank_organization_id']
            or basis.scope != assessment.scope_ref or recorded.scope_ref != basis.scope
            or not scope_covers(request.context.scope, basis.scope)
            or task_digest(assessment.review_input.model_dump(mode='json')) != identity.input_sha256
            or recorded.input != assessment.review_input or recorded.payload != assessment.review_payload
            or assessment.review_payload.model_dump(mode='json') != result['payload']
            or recorded.actor_id != assessment.author_actor_id or recorded.function_ref != assessment.author_function_ref
            or recorded.authority_refs != assessment.authority_refs or recorded.business_time != assessment.reviewed_at
            or assessment.application_ref.model_dump(mode='json') != request.action_input['application_ref']
            or assessment.product_ref.model_dump(mode='json') != request.action_input['product_ref']):
        raise ValueError('V5 quotation replaces original complete review, author, recorded assessment or native relation')
    return {'kind': 'prepared', 'source_mode': 'formal', 'credit_identity': identity.as_dict(),
        'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
            'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'native_record_id': basis.native_record_id, 'native_event_id': basis.native_event_id}}


def _draw_provenance(data, request, selected, identity, evidence, result, audit, files):
    basis = BankDrawHandoffBasisView.model_validate(files[3][2])
    approval = BankExecutionApprovalView.model_validate(files[4][2])
    arrangement = BankExecutionArrangementView.model_validate(files[5][2])
    operation = request.action_input['operation_context']
    expected = {'draw_task_sha256': identity.key, 'draw_record_sha256': evidence['record_sha256'],
        'draw_input_sha256': identity.input_sha256, 'draw_context_sha256': identity.context_sha256,
        'draw_result_sha256': task_digest(result), 'draw_audit_sha256': task_digest(audit),
        'draw_source_reading_sha256': evidence['source_reading_sha256'],
        'draw_request_sha256': basis.draw_request_sha256, 'draw_arrangement_sha256': basis.draw_arrangement_sha256,
        'draw_terms_sha256': basis.draw_terms_sha256, 'draw_conditions_sha256': task_digest(result['payload']['conditions']),
        'execution_arrangement_sha256': task_digest(arrangement.model_dump(mode='json')),
        'approval_sha256': task_digest(approval.model_dump(mode='json'))}
    if (any(getattr(basis, key) != value for key, value in expected.items()) or basis.ref != selected.basis_ref
            or basis.run_id != data['run_id'] or basis.organization_id != data['bank_organization_id']
            or basis.approval_ref != approval.ref or operation.get('kind') != 'initiate'
            or operation.get('draw_approval_ref') != approval.ref.model_dump(mode='json')
            or approval.arrangement_ref != arrangement.ref
            or arrangement.ref.model_dump(mode='json') != request.action_input['arrangement_ref']
            or any(row.lender_id != data['bank_organization_id'] for row in (approval, arrangement))
            or approval.borrower_id != arrangement.borrower_id or approval.terms_ref != arrangement.terms_ref
            or basis.scope != approval.scope or arrangement.scope != basis.scope
            or not scope_covers(request.context.scope, basis.scope)
            or not basis.effective_window.contains(request.context.business_time)
            or approval.amount.currency != result['payload']['approved_amount']['currency']
            or Decimal(approval.amount.value) != Decimal(result['payload']['approved_amount']['value'])
            or [line.transfer.model_dump(mode='json') for line in approval.lines] != result['payload']['transfer_lines']):
        raise ValueError('V5 execution input changes original registered draw approval, facility, amount or transfer lines')
    return {'kind': 'prepared', 'source_mode': 'formal', 'draw_identity': identity.as_dict(),
        'approval_ref': approval.ref.model_dump(mode='json'),
        'provenance': {**expected, 'basis_ref': basis.ref.model_dump(mode='json'),
            'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'native_approval_id': basis.native_approval_id, 'native_event_id': basis.native_event_id}}


def _execution_provenance(request, identity, evidence, result, observation):
    reception = BankExecutionReceptionSettings.model_validate(observation)
    operation = request.action_input['operation_context']
    expected = {'source_task_sha256': identity.key, 'source_record_sha256': evidence['record_sha256'],
        'source_result_sha256': task_digest(result), 'source_reading_sha256': evidence['source_reading_sha256']}
    executions, receipts = reception.executions, reception.receipts
    execution_refs = [row.ref.model_dump(mode='json') for row in executions]
    receipt_refs = [row.ref.model_dump(mode='json') for row in receipts]
    if (reception.identity != identity or any(getattr(reception, key) != value for key, value in expected.items()
            if key != 'source_task_sha256')
            or operation.get('kind') != 'existing'
            or len({row.ref.key() for row in executions}) != len(executions)
            or len({row.command_id for row in executions}) != len(executions)
            or len({row.business_key for row in executions}) != len(executions)
            or len({row.ref.key() for row in receipts}) != len(receipts)
            or sorted(execution_refs, key=task_digest) != sorted(operation['execution_refs'], key=task_digest)
            or sorted(receipt_refs, key=task_digest) != sorted(request.action_input['receipt_refs'], key=task_digest)
            or reception.native_evidence_ref == reception.relation_evidence_ref):
        raise ValueError('V5 reconciliation changes original command group, current input or native observation lineage')
    approval = BankExecutionApprovalView.model_validate(reception.native_payload['original_approval'])
    if (approval.ref.model_dump(mode='json') != result['payload']['approval_ref']
            or approval.lender_id != identity.organization_id
            or approval.arrangement_ref.model_dump(mode='json') != request.action_input['arrangement_ref']
            or any(row.lender_id != approval.lender_id or row.borrower_id != approval.borrower_id
                or row.approval_ref != approval.ref or row.arrangement_ref != approval.arrangement_ref
                or row.path_ref.model_dump(mode='json') != result['payload']['path_ref']
                or row.lines != approval.lines for row in executions)):
        raise ValueError('V5 reconciliation replaces original approval, parties, funding path or full allocation')
    expected_native = {'schema_version': 'bank-execution-observation.v1', 'source_identity': identity.as_dict(),
        **{key: value for key, value in expected.items() if key != 'source_task_sha256'},
        'original_approval': approval.model_dump(mode='json'),
        'executions': [row.model_dump(mode='json') for row in executions],
        'receipts': [row.model_dump(mode='json') for row in receipts], 'current_state': 'observed'}
    expected_relation = {'schema_version': 'bank-execution-observation-relation.v1',
        'source_identity': identity.as_dict(), 'source_record_sha256': evidence['record_sha256'],
        'current_context_sha256': task_digest(request.context.model_dump(mode='json')),
        'current_input_sha256': task_digest(request.action_input),
        'native_payload_sha256': task_digest(expected_native), 'current_state': 'active'}
    if reception.native_payload != expected_native or reception.relation_payload != expected_relation:
        raise ValueError('V5 reconciliation substitutes retained original native history or current authorized relation')
    return {**expected, 'native_payload_sha256': task_digest(expected_native),
        'relation_payload_sha256': task_digest(expected_relation),
        'execution_refs': execution_refs, 'receipt_refs': receipt_refs}


def build_input(*, paths, output_path, route):
    specification = _ROUTES[route]
    if len(paths) != len(specification['labels']):
        raise ValueError('V5 internal reception requires every declared original file')
    originals = tuple(_read(path) for path in paths)
    bank = originals[1][2]
    if set(bank) != _BANK_FIELDS:
        raise ValueError('V5 internal assembly requires complete explicit Bank input')
    data = {'schema_version': specification['declaration']['prefix'] + '-input.v1', 'scenario_id': 'V5', **deepcopy(bank),
        'sources': {label: {'path': str(item[0]), 'file_sha256': item[1]} for label, item in zip(specification['labels'], originals)}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V5 credit input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured={item[0]: item for item in originals}, route=route)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in originals):
        raise ValueError('V5 original Bank intake files changed during assembly')
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
    return run_prepared(_prepare_data(_read(input_path), route=route), declaration=_ROUTES[route]['declaration'],
        output_directory=output_directory, execute=execute)


def main(route):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    for label in _ROUTES[route]['labels']:
        parser.add_argument('--' + label.replace('_', '-'), dest=label, type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = tuple(getattr(args, label) for label in _ROUTES[route]['labels'])
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires every original file, without --input or --execute')
        build_input(paths=assembly, output_path=args.output, route=route)
        return
    if args.input is None:
        parser.error('Provide --input or every original assembly file')
    print(run_reception(input_path=args.input, output_directory=args.output, execute=args.execute, route=route)['mode'])
