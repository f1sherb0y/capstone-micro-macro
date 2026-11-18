"""Plan or explicitly evaluate formal V6 continuation from original closeout feedback."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.owner_closeout_feedback import OwnerCloseoutSubmissionFeedback
from integration.owner_formal_application import OwnerFormalApplicationSettings
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_continuation_objects import (
    OwnerCloseoutContinuationBasisView, OwnerContinuationDutyView, OwnerContinuationStateView,
)
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_CHOICES = ('suspend', 'reduce', 'remedy', 'replace', 'transfer', 'terminate', 'resume')
_OWNER_FIELDS = {'run_id', 'owner_organization_id', 'request', 'configuration'}


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare(input_path):
    return _prepare_data(_read(input_path))


def _check_formal_closeout_history(settings, *, request, identity, feedback_record_sha256):
    """Check the declared original reader before loading business dependencies."""
    if settings.source_factory != 'integration.owner_formal_application:build_sources':
        return
    formal = OwnerFormalApplicationSettings.model_validate(settings.source_settings)
    history = formal.closeout_history
    if (formal.action_id != 'OWN-A13' or history is None or formal.payment_reception is not None
            or formal.client_version != settings.client_version or formal.model_version != settings.model_version
            or settings.source_version != formal.declared_source_version):
        raise ValueError('V6 formal continuation requires matching source/client/model versions and original closeout history')
    own, recipient = history.owner_request.context, history.recipient_context
    if (history.identity.as_dict() != identity.as_dict() or recipient != request.context
            or history.feedback_record_sha256 != feedback_record_sha256
            or own.run_id != identity.run_id or own.contract_ref.id != 'OWN-A12'
            or own.execution_mode != 'llm' or history.owner_request.execution_path == 'deterministic'
            or own.business_time != recipient.business_time or own.operation_id == recipient.operation_id
            or own.read_token == recipient.read_token or own.task_ref == recipient.task_ref):
        raise ValueError('V6 formal continuation changes original feedback identity/digest or current A12/A13 declarations')


def _prepare_data(current, *, captured=None):
    data = current[2]
    required = _OWNER_FIELDS | {'schema_version', 'scenario_id', 'source_mode', 'closeout_feedback'}
    if (set(data) not in (required, required | {'sources'})
            or data['schema_version'] != 'lifecycle-v6-owner-continuation-input.v1'
            or data['scenario_id'] != 'V6' or data['source_mode'] != 'formal'
            or not isinstance(data['owner_organization_id'], str) or not data['owner_organization_id'].strip()):
        raise ValueError('V6 continuation requires formal original closeout feedback and current Owner sources')
    selection = data['closeout_feedback']
    if (not isinstance(selection, dict) or set(selection) != {'record_path', 'record_file_sha256',
            'feedback_record_sha256', 'basis_ref'}
            or not isinstance(selection['record_path'], str) or not selection['record_path'].strip()):
        raise ValueError('V6 continuation requires an explicit original feedback file and current basis reference')
    for field in ('record_file_sha256', 'feedback_record_sha256'):
        value = selection[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V6 closeout provenance requires SHA256 digests')
    previous_path = (current[0].parent / selection['record_path']).resolve()
    previous = captured.get(previous_path) if captured is not None else None
    if previous is None:
        previous = _read(previous_path)
    record = previous[2]
    if (set(record) != {'schema_version', 'identity', 'receipt', 'context', 'observation',
            'sources', 'source_evidence', 'configuration_sha256', 'record_sha256'}
            or previous[1] != selection['record_file_sha256']
            or record['schema_version'] != OwnerCloseoutSubmissionFeedback.VERSION
            or record['record_sha256'] != selection['feedback_record_sha256']
            or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != record['record_sha256']):
        raise ValueError('V6 replaces original closeout feedback file, closed schema or record digest')
    identity = TaskIdentity(**record['identity'])
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    basis = Reference.model_validate(selection['basis_ref'])
    if (identity.run_id != data['run_id'] or identity.organization_id != data['owner_organization_id']
            or identity.role != 'Owner' or identity.action_id != 'OWN-A12' or identity.purpose != 'action'
            or record['observation']['target_action_id'] != 'OWN-A12'
            or record['context']['execution_mode'] == 'offline_fixture'
            or record['receipt']['identity'] != identity.as_dict()
            or record['receipt']['receipt']['disposition'] != 'accepted'
            or record['receipt']['receipt_sha256'] != task_digest(record['receipt']['receipt'])
            or request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'OWN-A13'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or request.context.operation_id == identity.request_id
            or request.context.read_token == record['context']['read_token']
            or request.context.task_ref.model_dump(mode='json') == record['context']['task_ref']
            or settings.action_id != 'OWN-A13' or basis.kind != 'CloseoutContinuationBasis'
            or settings.closeout_continuation_inputs is None
            or request.context.operation_id not in settings.closeout_continuation_inputs.selections):
        raise ValueError('V6 requires original formal A12 feedback and a distinct current same-owner A13 invocation')
    selected = settings.closeout_continuation_inputs.selections[request.context.operation_id]
    if selected.feedback_record_sha256 != record['record_sha256'] or selected.basis_ref.key() != basis.key():
        raise ValueError('V6 configuration changes selected original feedback or current continuation basis')
    _check_formal_closeout_history(settings, request=request, identity=identity,
        feedback_record_sha256=record['record_sha256'])
    files = [current, previous]
    if 'sources' in data:
        if not isinstance(data['sources'], dict) or set(data['sources']) != {'owner_input', 'native_basis'}:
            raise ValueError('V6 continuation assembly must retain complete Owner input and actual native mapping files')
        for label in ('owner_input', 'native_basis'):
            binding = data['sources'][label]
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()):
                raise ValueError('V6 continuation source requires its original file path and raw SHA256')
            path = (current[0].parent / binding['path']).resolve()
            item = captured.get(path) if captured is not None else None
            if item is None:
                item = _read(path)
            if item[1] != binding['file_sha256']:
                raise ValueError('V6 retained continuation source changed')
            files.append(item)
        if files[2][2] != {key: data[key] for key in _OWNER_FIELDS}:
            raise ValueError('V6 continuation assembly changes complete original Owner input/configuration')
        _validate_native_basis(files[3][2], record=record, identity=identity, request=request, basis_ref=basis)
    return tuple(files), deepcopy(data), identity, request.model_dump(mode='json'), config.model_dump(mode='json')


def _validate_native_basis(native, *, record, identity, request, basis_ref):
    if (not isinstance(native, dict) or set(native) != {'schema_version', 'feedback_record_sha256', 'basis',
            'current_context', 'current_input', 'continuation_state', 'targets', 'disposition_evidence', 'coverage'}
            or native['schema_version'] != 'owner-closeout-continuation-native-basis.v1'
            or native['feedback_record_sha256'] != record['record_sha256'] or native['coverage'] != 'complete'
            or native['current_context'] != request.context.model_dump(mode='json')
            or native['current_input'] != request.action_input):
        raise ValueError('V6 native mapping changes selected feedback, complete current context/input or coverage')
    basis = OwnerCloseoutContinuationBasisView.model_validate(native['basis'])
    state = OwnerContinuationStateView.model_validate(native['continuation_state'])
    context = request.context
    if (basis.ref.key() != basis_ref.key() or basis.run_id != identity.run_id or basis.organization_id != identity.organization_id
            or basis.source_task_sha256 != identity.key or basis.feedback_record_sha256 != record['record_sha256']
            or basis.source_result_sha256 != record['receipt']['receipt']['output_sha256']
            or basis.source_receipt_sha256 != record['receipt']['receipt_sha256'] or basis.scope != context.scope
            or basis.continuation_state_ref != state.ref or state.organization_id != identity.organization_id
            or state.scope != context.scope or state.coverage != 'complete' or state.as_of != context.business_time
            or not basis.effective_window.contains(context.business_time)
            or basis.native_evidence_ref not in basis.evidence_refs):
        raise ValueError('V6 native basis replaces original closeout relation or current actual Owner state')
    originals = {Reference.model_validate(row['ref']).key() for row in record['sources']}
    liabilities = {key for key in originals if key[0] in {'Obligation', 'ContinuingResponsibility',
        'Defect', 'Issue', 'SettlementComponent', 'ActualSettlementComponent'}}
    dispositions = {row.source_ref.key(): row for row in basis.dispositions}
    if (len(originals) != len(record['sources']) or basis.decision_ref.key() not in originals
            or len(dispositions) != len(basis.dispositions) or set(dispositions) != liabilities):
        raise ValueError('V6 native basis drops or repeats original residual-duty dispositions')
    expected_targets, expected_evidence = set(), set()
    for row in basis.dispositions:
        if (row.disposition in {'retained', 'superseded'} and not row.target_refs
                or len(set(row.target_refs)) != len(row.target_refs)
                or len(set(row.basis_refs)) != len(row.basis_refs) or basis.native_evidence_ref in row.basis_refs):
            raise ValueError('V6 residual-duty mapping lacks independent targets or separate actual disposition evidence')
        expected_targets.update(ref.key() for ref in row.target_refs)
        expected_evidence.update(ref.key() for ref in row.basis_refs)
    targets = {}
    input_obligations = {Reference.model_validate(ref).key() for ref in request.action_input['obligation_refs']}
    state_obligations = {ref.key() for ref in state.obligation_refs}
    state_duties = {ref.key() for ref in state.retained_duty_refs}
    for value in native['targets']:
        ref = Reference.model_validate(value['ref'])
        model = {'Obligation': OwnerPaymentObligationView, 'ContinuingDuty': OwnerContinuationDutyView}.get(ref.kind)
        if model is None or ref.key() in targets:
            raise ValueError('V6 native mapping repeats a target or invents a residual-duty target type')
        target = model.model_validate(value)
        if (ref.kind == 'Obligation' and (target.as_of != context.business_time
                or ref.key() not in input_obligations or ref.key() not in state_obligations)
                or ref.kind == 'ContinuingDuty' and (target.organization_id != identity.organization_id
                    or ref.key() not in state_duties)):
            raise ValueError('V6 native residual target is missing from the current Owner input/state')
        targets[ref.key()] = target
    observations = [EvidenceRecord.model_validate(value) for value in native['disposition_evidence']]
    if (set(targets) != expected_targets or len({row.ref.key() for row in observations}) != len(observations)
            or {row.ref.key() for row in observations} != expected_evidence
            or any(row.source_kind == 'synthetic' or row.basis_kind != 'observed'
                or row.effective_window is not None and not row.effective_window.contains(context.business_time)
                for row in observations)):
        raise ValueError('V6 retained native mapping omits original targets or independent actual disposition evidence')


def build_v6_owner_continuation_input(*, feedback_path, owner_input_path, native_basis_path, output_path):
    originals = tuple(_read(path) for path in (feedback_path, owner_input_path, native_basis_path))
    record, owner, native = (item[2] for item in originals)
    if set(owner) != _OWNER_FIELDS:
        raise ValueError('V6 continuation assembly requires complete explicit Owner input')
    data = {'schema_version': 'lifecycle-v6-owner-continuation-input.v1', 'scenario_id': 'V6',
        'source_mode': 'formal', **deepcopy(owner),
        'closeout_feedback': {'record_path': str(originals[0][0]), 'record_file_sha256': originals[0][1],
            'feedback_record_sha256': record['record_sha256'], 'basis_ref': deepcopy(native['basis']['ref'])},
        'sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in zip(('owner_input', 'native_basis'), originals[1:])}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V6 continuation input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured={item[0]: item for item in originals})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in originals):
        raise ValueError('V6 original continuation files changed during assembly')
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


def run_v6_owner_continuation(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 continuation execution selection must be an explicit boolean')
    files, data, original_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-owner-continuation-plan.v1', 'scenario_id': 'V6',
        'run_id': data['run_id'], 'action_id': 'OWN-A13', 'source_mode': 'formal', 'origin': 'actual_input',
        'mode': 'execute_formal' if execute else 'plan_only', 'factory': _FACTORY,
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'source_identity': original_identity.as_dict(), 'closeout_feedback': deepcopy(data['closeout_feedback']),
        'allowed_choices': list(_CHOICES),
        'limitations': ['A feedback file and transport acceptance do not establish lawful continuation or discharged duties.',
            'Source factory must authorize original history and independently authenticate complete current liability mapping.']}
    if 'sources' in data:
        plan['native_basis_sha256'] = task_digest(files[3][2])
    for name, value in (('input', data), ('closeout-feedback-input', files[1][2]),
            ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if 'sources' in data:
        for label, item in zip(('owner-input', 'native-basis-input'), files[2:]):
            atomic_json(directory / (label + '.json'), item[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-owner-continuation-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V6 current input or original closeout feedback changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=False)
        evidence = result['execution_evidence']
        identity, task, mapping = evidence['identity'], evidence['task'], evidence['closeout_continuation_input']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data['owner_organization_id'],
            'role': 'Owner', 'action_id': 'OWN-A13', 'request_id': request['context']['operation_id'],
            'purpose': 'action', 'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        expected_mapping = {'feedback_record_sha256': data['closeout_feedback']['feedback_record_sha256'],
            'source_identity': original_identity.as_dict(), 'basis_ref': data['closeout_feedback']['basis_ref'],
            'execution_source_reading_sha256': evidence['source_reading_sha256']}
        if (result['source_mode'] != 'formal' or result['action_id'] != 'OWN-A13'
                or evidence['result_table'] != 'owner_continuation_results'
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or task['identity'] != identity or result['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result['result'])
                or not isinstance(mapping, dict) or any(mapping.get(key) != value for key, value in expected_mapping.items())
                or not isinstance(mapping.get('native_basis_sha256'), str) or len(mapping['native_basis_sha256']) != 64
                or any(char not in '0123456789abcdef' for char in mapping['native_basis_sha256'])
                or 'sources' in data and mapping['native_basis_sha256'] != plan['native_basis_sha256']):
            raise ValueError('V6 continuation lacks original durable task/audit or selected complete closeout mapping')
        if result['result']['kind'] == 'completed':
            if (task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
                    or result['result']['payload']['choice'] not in _CHOICES):
                raise ValueError('V6 continuation substitutes original output or legal branch')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V6 incomplete continuation must preserve original pending or failure state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V6 retained continuation files changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'closeout_continuation_input': deepcopy(mapping),
            'result': deepcopy(result['result']),
            'limitations': ['Local continuation output does not execute suspension, transfer, termination or duty release.',
                'Actual endpoints and all V6 branches still require final functional verification.']}
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
    parser.add_argument('--feedback', type=Path)
    parser.add_argument('--owner-input', type=Path)
    parser.add_argument('--native-basis', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.feedback, args.owner_input, args.native_basis)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --feedback, --owner-input and --native-basis without --input or --execute')
        build_v6_owner_continuation_input(feedback_path=args.feedback, owner_input_path=args.owner_input,
            native_basis_path=args.native_basis, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    result = run_v6_owner_continuation(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
