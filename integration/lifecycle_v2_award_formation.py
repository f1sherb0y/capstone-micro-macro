"""Plan or explicitly run Contractor formation from a received original Owner award."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.lifecycle_v3_architect_intake import _read
from integration.contractor_role_contract_host import ContractorRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.sessions import atomic_json
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.contractor_role_contract_host:build_role_host'


def _prepare(input_path):
    current = _read(input_path)
    data = current[2]
    if (set(data) != {'schema_version', 'scenario_id', 'run_id', 'contractor_organization_id',
            'source_mode', 'award', 'request', 'configuration'}
            or data['schema_version'] != 'lifecycle-v2-award-formation-input.v1'
            or data['scenario_id'] != 'V2' or data['source_mode'] != 'formal'
            or not isinstance(data['contractor_organization_id'], str) or not data['contractor_organization_id'].strip()):
        raise ValueError('V2 formation requires original Owner award and explicit current formal Contractor input')
    source = data['award']
    if (not isinstance(source, dict) or set(source) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'selection'}
            or not isinstance(source['result_path'], str) or not source['result_path'].strip()):
        raise ValueError('V2 formation requires complete original award provenance and reception selection')
    for key in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256'):
        value = source[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('V2 award provenance requires SHA256 digests')
    previous = _read(current[0].parent / source['result_path'])
    original = previous[2]
    identity = TaskIdentity(**source['identity'])
    evidence = original.get('execution_evidence', {})
    audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
    result = original.get('result', {})
    if (previous[1] != source['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('source_mode') != 'formal' or original.get('action_id') != 'OWN-A10'
            or identity.run_id != data['run_id'] or identity.role != 'Owner' or identity.action_id != 'OWN-A10'
            or identity.purpose != 'action' or identity.organization_id == data['contractor_organization_id']
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'owner_award_results'
            or evidence.get('record_sha256') != source['record_sha256']
            or evidence.get('source_reading_sha256') != source['reading_sha256']
            or result.get('kind') != 'completed' or result.get('payload', {}).get('choice') != 'accept'
            or task_digest(result) != source['result_sha256'] or task.get('identity') != identity.as_dict()
            or task.get('output') != result or task.get('output_sha256') != source['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(k) != v for k, v in {'run_id': data['run_id'], 'action_id': 'OWN-A10',
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': source['result_sha256'], 'result_kind': 'completed'}.items())):
        raise ValueError('V2 formation input changes original Owner award result/task/audit provenance')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'CONTRACTOR-A04'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'CONTRACTOR-A04' or settings.received_award_inputs is None
            or request.context.operation_id not in settings.received_award_inputs.selections):
        raise ValueError('V2 formation requires current formal Contractor A04 and original independent award reception sources')
    selection = settings.received_award_inputs.selections[request.context.operation_id].model_dump(mode='json')
    if selection != source['selection'] or selection['source_task_sha256'] != identity.key:
        raise ValueError('V2 formation configuration substitutes original Owner award or actual reception')
    return (current, previous), deepcopy(data), identity, request, config


def run_v2_award_formation(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V2 formation execution selection must be an explicit boolean')
    files, data, source_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v2-award-formation-plan.v1', 'scenario_id': 'V2',
        'run_id': data['run_id'], 'source_mode': 'formal', 'mode': 'plan_only', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files], 'award': deepcopy(data['award']),
        'request_sha256': task_digest(request.model_dump(mode='json')),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'limitations': ['Application must supply original Owner record/submission, actual independent acceptance and complete native offer/agreement mapping.',
            'Owner and Contractor acceptance, signature, effectiveness and native contract formation are separate gates.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'owner-award-result-input.json', files[1][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {**plan, 'status': 'started', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V2 original award or formation input changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'contractor', offline=False)
        evidence, result = output['execution_evidence'], output['result']
        identity, task, provenance = evidence['identity'], evidence['task'], evidence['received_award_input']
        source = data['award']
        expected = {'source_identity': source_identity.as_dict(), 'source_record_sha256': source['record_sha256'],
            'source_result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'acceptance_ref': source['selection']['acceptance_ref'], 'native_evidence_ref': source['selection']['native_evidence_ref']}
        if (output['source_mode'] != 'formal' or output['action_id'] != 'CONTRACTOR-A04'
                or identity['run_id'] != data['run_id'] or identity['organization_id'] != data['contractor_organization_id']
                or identity['action_id'] != 'CONTRACTOR-A04' or identity['role'] != 'Contractor' or identity['purpose'] != 'action'
                or identity['request_id'] != request.context.operation_id or identity['input_sha256'] != task_digest(request.action_input)
                or identity['context_sha256'] != task_digest(request.context.model_dump(mode='json'))
                or evidence['result_table'] != 'contractor_formation_results' or task['identity'] != identity
                or output['audit'] != [evidence['saved_audit']]
                or evidence['saved_audit']['result_sha256'] != task_digest(result)
                or not isinstance(provenance, dict) or any(provenance.get(k) != v for k, v in expected.items())):
            raise ValueError('V2 formation outcome lacks original durable task/audit or selected award reception provenance')
        publication = provenance.get('publication', {})
        if (publication.get('schema_version') != 'owner-award-saved-receipt.v1'
                or publication.get('identity') != source_identity.as_dict()
                or publication.get('record_sha256') != source['record_sha256']
                or publication.get('receipt', {}).get('disposition') != 'accepted'):
            raise ValueError('V2 formation outcome lacks original confirmed Owner award submission')
        if result['kind'] == 'completed':
            if (result['payload']['choice'] not in {'accept', 'revise', 'reject'} or task['output'] != result
                    or task['output_sha256'] != task_digest(result)):
                raise ValueError('V2 formation outcome changes original independent Contractor decision or durable output')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V2 incomplete formation must preserve waiting or technical failure')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V2 original award or formation input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result_kind': result['kind'],
            'result_path': 'contractor/result.json', 'result_sha256': task_digest(output)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    run_v2_award_formation(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
