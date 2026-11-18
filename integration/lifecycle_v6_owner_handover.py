"""Plan or explicitly evaluate V6 Owner handover from an original Contractor result."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.owner_formal_application import OwnerFormalApplicationSettings
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_closeout_objects import ContractorAsBuiltView, ContractorHandoverRequestView
from src.actions.contracts.owner_closeout_objects import OwnerHandoverSubmissionView
from src.coordination.tasks import TaskIdentity, task_digest
from src.organization.registry import scope_covers


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_CHOICES = ('accept_scope', 'request_rectification', 'agree_settlement', 'dispute_settlement', 'release_retention')
_OWNER_FIELDS = {'run_id', 'owner_organization_id', 'request', 'configuration'}


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare(input_path):
    return _prepare_data(_read(input_path))


def _check_formal_handover_reception(settings, *, request, identity, handover):
    """Check original reader declarations before loading business dependencies."""
    if settings.source_factory != 'integration.owner_formal_application:build_sources':
        return
    formal = OwnerFormalApplicationSettings.model_validate(settings.source_settings)
    history = formal.handover_reception
    if (formal.action_id != 'OWN-A12' or history is None
            or formal.payment_reception is not None or formal.closeout_history is not None
            or formal.client_version != settings.client_version or formal.model_version != settings.model_version
            or settings.source_version != formal.declared_source_version):
        raise ValueError('V6 formal handover requires matching source/client/model versions and original reception history')
    own, recipient = history.contractor_request.context, history.recipient_context
    if (history.identity.as_dict() != identity.as_dict() or recipient != request.context
            or history.source_record_sha256 != handover['record_sha256']
            or history.source_result_sha256 != handover['result_sha256']
            or history.source_reading_sha256 != handover['reading_sha256']
            or history.sharing_authorized is not True
            or own.run_id != identity.run_id or own.contract_ref.id != 'CONTRACTOR-A11'
            or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
            or history.contractor_request.execution_path == 'deterministic'
            or own.business_time != recipient.business_time):
        raise ValueError('V6 formal handover changes original Contractor identity/digests, sharing or current recipient declarations')


def _prepare_data(input_file, *, captured=None):
    data = input_file[2]
    required = _OWNER_FIELDS | {'schema_version', 'scenario_id', 'source_mode', 'contractor_handover'}
    if (set(data) not in (required, required | {'sources'})
            or data['schema_version'] != 'lifecycle-v6-owner-handover-input.v1'
            or data['scenario_id'] != 'V6' or data['source_mode'] not in {'fixture', 'formal'}
            or not isinstance(data['owner_organization_id'], str) or not data['owner_organization_id'].strip()):
        raise ValueError('V6 handover requires explicit original Contractor evidence and current Owner request/source configuration')
    handover = data['contractor_handover']
    if (not isinstance(handover, dict) or set(handover) != {'result_path', 'result_file_sha256',
            'identity', 'record_sha256', 'result_sha256', 'reading_sha256', 'handover_ref', 'native_evidence_ref'}
            or not isinstance(handover['result_path'], str) or not handover['result_path'].strip()):
        raise ValueError('V6 handover requires original result file, task/source digests and actual reception references')
    for field in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256'):
        value = handover[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V6 original handover provenance requires SHA256 digests')
    predecessor_path = (input_file[0].parent / handover['result_path']).resolve()
    predecessor = captured.get(predecessor_path) if captured is not None else None
    if predecessor is None:
        predecessor = _read(predecessor_path)
    original = predecessor[2]
    identity = TaskIdentity(**handover['identity'])
    evidence = original.get('execution_evidence', {})
    audit = evidence.get('saved_audit', {})
    task = evidence.get('task', {})
    if (predecessor[1] != handover['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('action_id') != 'CONTRACTOR-A11' or original.get('source_mode') != data['source_mode']
            or identity.run_id != data['run_id'] or identity.role != 'Contractor' or identity.action_id != 'CONTRACTOR-A11'
            or identity.purpose != 'action' or identity.organization_id == data['owner_organization_id']
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'contractor_closeout_results'
            or evidence.get('record_sha256') != handover['record_sha256']
            or evidence.get('source_reading_sha256') != handover['reading_sha256']
            or original.get('result', {}).get('kind') != 'completed'
            or original['result']['payload']['choice'] != 'submit_handover'
            or task_digest(original['result']) != handover['result_sha256']
            or task.get('identity') != identity.as_dict() or task.get('output') != original['result']
            or task.get('output_sha256') != handover['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit]
            or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'CONTRACTOR-A11',
                'input_sha256': identity.input_sha256, 'operation_id': identity.request_id,
                'result_sha256': handover['result_sha256'], 'result_kind': 'completed'}.items())
            or audit.get('reading', {}).get('source_mode') != data['source_mode']):
        raise ValueError('V6 handover replaces original Contractor result, journal evidence or source mode')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    offline = data['source_mode'] == 'fixture'
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'OWN-A12'
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')
            or settings.action_id != 'OWN-A12' or settings.handover_inputs is None
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.handover_inputs.selections
            or offline and request.execution_path not in {None, 'deterministic'}
            or not offline and request.execution_path == 'deterministic'):
        raise ValueError('V6 requires a distinct current Owner A12 operation and explicitly matching source/model mode')
    selected = settings.handover_inputs.selections[request.context.operation_id]
    if (selected.source_task_sha256 != identity.key or selected.handover_ref.key() != Reference.model_validate(handover['handover_ref']).key()
            or selected.native_evidence_ref.key() != Reference.model_validate(handover['native_evidence_ref']).key()
            or selected.handover_ref.key() not in {Reference.model_validate(ref).key() for ref in request.action_input['handover_refs']}):
        raise ValueError('V6 Owner input changes explicitly selected original Contractor task or independent reception evidence')
    _check_formal_handover_reception(settings, request=request, identity=identity, handover=handover)
    files = [input_file, predecessor]
    if 'sources' in data:
        if not isinstance(data['sources'], dict) or set(data['sources']) != {'owner_input', 'native_reception'}:
            raise ValueError('V6 handover assembly requires complete Owner input and original native reception files')
        for label in ('owner_input', 'native_reception'):
            binding = data['sources'][label]
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()):
                raise ValueError('V6 retained handover source requires its original file path and raw SHA256')
            path = (input_file[0].parent / binding['path']).resolve()
            item = captured.get(path) if captured is not None else None
            if item is None:
                item = _read(path)
            if item[1] != binding['file_sha256']:
                raise ValueError('V6 retained handover source file changed')
            files.append(item)
        if files[2][2] != {key: data[key] for key in _OWNER_FIELDS}:
            raise ValueError('V6 handover assembly changes complete original Owner input/configuration')
        _validate_native_reception(files[3][2], original=original, data=data, request=request)
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), offline


def _validate_native_reception(native, *, original, data, request):
    handover = data['contractor_handover']
    if (not isinstance(native, dict) or set(native) != {'schema_version', 'source_identity', 'source_record_sha256',
            'source_result_sha256', 'source_reading_sha256', 'original_result', 'original_profile_ref',
            'handover_request', 'submission', 'configurations', 'recipient_organization_id'}
            or native['schema_version'] != 'contractor-owner-handover-reception.v1'
            or native['source_identity'] != handover['identity'] or native['source_record_sha256'] != handover['record_sha256']
            or native['source_result_sha256'] != handover['result_sha256']
            or native['source_reading_sha256'] != handover['reading_sha256']
            or native['original_result'] != original['result']
            or native['recipient_organization_id'] != data['owner_organization_id']
            or Reference.model_validate(native['original_profile_ref']).kind != 'HandoverProfile'):
        raise ValueError('V6 reception file substitutes original Contractor lineage, result or current Owner recipient')
    submission = OwnerHandoverSubmissionView.model_validate(native['submission'])
    registered = ContractorHandoverRequestView.model_validate(native['handover_request'])
    configurations = [ContractorAsBuiltView.model_validate(row) for row in native['configurations']]
    refs = {row.ref for row in configurations}
    evidence_ref = Reference.model_validate(handover['native_evidence_ref'])
    if (submission.ref.key() != Reference.model_validate(handover['handover_ref']).key()
            or submission.request_ref != registered.ref or submission.contract_ref != registered.contract_ref
            or submission.status not in {'submitted', 'pending'} or registered.status not in {'submitted', 'pending'}
            or submission.scope != registered.scope
            or submission.scope.model_dump(mode='json') != original['result']['payload']['scope_ref']
            or not scope_covers(request.context.scope, submission.scope)
            or len(refs) != len(configurations) or set(submission.as_built_refs) != refs
            or set(registered.as_built_refs) != refs
            or len(set(submission.as_built_refs)) != len(submission.as_built_refs)
            or len(set(registered.as_built_refs)) != len(registered.as_built_refs)
            or {ref.key() for ref in submission.issue_refs} != {
                Reference.model_validate(ref).key() for ref in original['result']['payload']['remaining_issue_refs']}
            or len(set(submission.issue_refs)) != len(submission.issue_refs)
            or any(row.contract_ref != submission.contract_ref
                or row.author_organization_id != handover['identity']['organization_id'] for row in configurations)):
        raise ValueError('V6 reception changes actual contract, full configuration or unresolved issue coverage')
    for row in (registered, submission):
        if (row.author_organization_id != handover['identity']['organization_id']
                or row.author_action_id != 'CONTRACTOR-A11' or evidence_ref.key() not in {ref.key() for ref in row.evidence_refs}
                or not row.effective_window.contains(row.authored_at)):
            raise ValueError('V6 reception substitutes original Contractor author or independent native evidence')
    points = [registered.authored_at, registered.available_at, submission.authored_at,
        submission.available_at, request.context.business_time]
    if (not submission.effective_window.contains(request.context.business_time)
            or any(point.clock_ref != request.context.business_time.clock_ref for point in points)
            or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
        raise ValueError('V6 reception changes actual registration/reception chronology or current availability')


def build_v6_owner_handover_input(*, contractor_result_path, owner_input_path, native_reception_path, output_path):
    originals = tuple(_read(path) for path in (contractor_result_path, owner_input_path, native_reception_path))
    original, owner, native = (item[2] for item in originals)
    if set(owner) != _OWNER_FIELDS:
        raise ValueError('V6 handover assembly requires complete explicit Owner input')
    request = RoleContractInvocation.model_validate(owner['request'])
    config = RoleContractHostConfiguration.model_validate(owner['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    if settings.handover_inputs is None or request.context.operation_id not in settings.handover_inputs.selections:
        raise ValueError('V6 handover assembly requires an explicit original Contractor reception selection')
    selected = settings.handover_inputs.selections[request.context.operation_id]
    evidence = original['execution_evidence']
    data = {'schema_version': 'lifecycle-v6-owner-handover-input.v1', 'scenario_id': 'V6',
        'source_mode': original['source_mode'], **deepcopy(owner),
        'contractor_handover': {'result_path': str(originals[0][0]), 'result_file_sha256': originals[0][1],
            'identity': deepcopy(evidence['identity']), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(original['result']), 'reading_sha256': evidence['source_reading_sha256'],
            'handover_ref': selected.handover_ref.model_dump(mode='json'),
            'native_evidence_ref': selected.native_evidence_ref.model_dump(mode='json')},
        'sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in zip(('owner_input', 'native_reception'), originals[1:])}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V6 handover input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured={item[0]: item for item in originals})
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in originals):
        raise ValueError('V6 original handover files changed during assembly')
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


def run_v6_owner_handover(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 handover execution selection must be an explicit boolean')
    files, data, request, config, offline = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-owner-handover-plan.v1', 'scenario_id': 'V6', 'run_id': data['run_id'],
        'action_id': 'OWN-A12', 'source_mode': data['source_mode'], 'origin': 'synthetic' if offline else 'actual_input',
        'mode': 'execute_offline' if execute and offline else 'execute_formal' if execute else 'plan_only',
        'factory': _FACTORY, 'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(config),
        'contractor_handover': deepcopy(data['contractor_handover']), 'allowed_choices': list(_CHOICES),
        'limitations': ['Original Contractor local result does not prove an actual received handover or Owner acceptance.',
            'Source factory must independently supply registration, reception and continuing duties; plan creates no source facts.']}
    if 'sources' in data:
        plan['native_reception_sha256'] = task_digest(files[3][2])
    for name, value in (('input', data), ('contractor-result-input', files[1][2]),
            ('request', request), ('configuration', config), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if 'sources' in data:
        for label, item in zip(('owner-input', 'native-reception-input'), files[2:]):
            atomic_json(directory / (label + '.json'), item[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-owner-handover-attempt.v1', 'status': 'started', 'inputs': plan['inputs']}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V6 current input or original Contractor evidence changed before execution')
        result = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=offline)
        evidence = result['execution_evidence']
        identity, task, reception = evidence['identity'], evidence['task'], evidence['handover_input']
        expected_identity = {'run_id': data['run_id'], 'organization_id': data['owner_organization_id'], 'role': 'Owner',
            'action_id': 'OWN-A12', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        handover = data['contractor_handover']
        original_identity = TaskIdentity(**handover['identity'])
        expected_reception = {'source_task_sha256': original_identity.key, 'source_record_sha256': handover['record_sha256'],
            'source_result_sha256': handover['result_sha256'], 'source_reading_sha256': handover['reading_sha256'],
            'handover_ref': handover['handover_ref'], 'execution_source_reading_sha256': evidence['source_reading_sha256']}
        if 'sources' in data:
            expected_reception.update(native_reception_sha256=plan['native_reception_sha256'],
                request_ref=deepcopy(files[3][2]['handover_request']['ref']))
        if (result['source_mode'] != data['source_mode'] or evidence['result_table'] != 'owner_closeout_results'
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or task['identity'] != identity or evidence['saved_audit']['result_sha256'] != task_digest(result['result'])
                or result['action_id'] != 'OWN-A12' or result['audit'] != [evidence['saved_audit']]
                or not isinstance(reception, dict) or any(reception.get(key) != value for key, value in expected_reception.items())):
            raise ValueError('V6 Owner outcome lacks its original durable task/audit or explicit Contractor reception provenance')
        if result['result']['kind'] == 'completed':
            payload = result['result']['payload']
            if (task['output'] != result['result'] or task['output_sha256'] != task_digest(result['result'])
                    or payload['choice'] not in _CHOICES
                    or payload['choice'] == 'accept_scope' and payload['handover_ref'] != handover['handover_ref']):
                raise ValueError('V6 Owner decision changes actual handover selection or original legal closeout branch')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V6 noncompleted outcome must retain original incomplete task state')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files):
            raise ValueError('V6 retained handover files changed during execution')
        summary = {**plan, 'mode': 'executed_offline' if offline else 'executed_formal',
            'identity': deepcopy(identity), 'record_sha256': evidence['record_sha256'],
            'handover_input': deepcopy(reception), 'result': deepcopy(result['result']),
            'limitations': ['Local closeout outcome creates no acceptance registration, use rights, cash or discharged responsibility.',
                'This step does not complete all V6 settlement/retention/continuation branches or full PLAN acceptance.']}
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
    parser.add_argument('--contractor-result', type=Path)
    parser.add_argument('--owner-input', type=Path)
    parser.add_argument('--native-reception', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assembly = (args.contractor_result, args.owner_input, args.native_reception)
    if any(item is not None for item in assembly):
        if args.input is not None or args.execute or any(item is None for item in assembly):
            parser.error('Assembly requires --contractor-result, --owner-input and --native-reception without --input or --execute')
        build_v6_owner_handover_input(contractor_result_path=args.contractor_result, owner_input_path=args.owner_input,
            native_reception_path=args.native_reception, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or all three original assembly files')
    result = run_v6_owner_handover(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
