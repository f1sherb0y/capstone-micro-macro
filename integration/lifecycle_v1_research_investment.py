"""Plan or explicitly run Owner A03 using an actually received original QS A13 report."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.lifecycle_v3_architect_intake import _read
from integration.owner_role_contract_host import OwnerRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.sessions import atomic_json
from src.actions.contracts.owner_investment_objects import InvestmentResearchReceiptView
from src.coordination.tasks import TaskIdentity, task_digest


_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_RESEARCH_CHOICES = {'compare', 'cannot_rank', 'deliver_at_limit'}
_INVESTMENT_CHOICES = {'authorize_preparation', 'invest', 'reject', 'revise', 'study_more'}


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _prepare(input_path):
    current = _read(input_path)
    return _prepare_data(current)


def _prepare_data(current, *, captured_sources=None):
    data = current[2]
    fields = {'schema_version', 'scenario_id', 'run_id', 'owner_organization_id',
        'source_mode', 'research', 'request', 'configuration'}
    if (set(data) not in (fields, fields | {'assembly_sources'})
            or data['schema_version'] != 'lifecycle-v1-research-investment-input.v1'
            or data['scenario_id'] != 'V1' or data['source_mode'] != 'formal'
            or not isinstance(data['owner_organization_id'], str) or not data['owner_organization_id'].strip()):
        raise ValueError('V1 requires original QS research and an explicit current formal Owner investment input')
    source = data['research']
    if (not isinstance(source, dict) or set(source) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256', 'receipt_sha256', 'option_links_sha256', 'selection'}
            or not isinstance(source['result_path'], str) or not source['result_path'].strip()
            or any(not _digest(source[k]) for k in ('result_file_sha256', 'record_sha256',
                'result_sha256', 'reading_sha256', 'receipt_sha256', 'option_links_sha256'))):
        raise ValueError('V1 requires pinned original research, reception and option-link provenance')
    def read_source(path):
        path = Path(path).resolve()
        if captured_sources is not None and path in captured_sources:
            return captured_sources[path]
        return _read(path)

    previous = read_source(current[0].parent / source['result_path'])
    original = previous[2]
    identity = TaskIdentity(**source['identity'])
    evidence = original.get('execution_evidence', {})
    audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
    result = original.get('result', {})
    if (previous[1] != source['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('source_mode') != 'formal' or original.get('action_id') != 'QS-A13'
            or identity.run_id != data['run_id'] or identity.role != 'QS'
            or identity.action_id != 'QS-A13' or identity.purpose != 'action'
            or evidence.get('identity') != identity.as_dict() or evidence.get('result_table') != 'qs_research_results'
            or evidence.get('record_sha256') != source['record_sha256']
            or evidence.get('source_reading_sha256') != source['reading_sha256']
            or result.get('kind') != 'completed' or result.get('payload', {}).get('choice') not in _RESEARCH_CHOICES
            or not isinstance(result.get('payload', {}).get('comparison'), dict)
            or task_digest(result) != source['result_sha256'] or task.get('identity') != identity.as_dict()
            or task.get('output') != result or task.get('output_sha256') != source['result_sha256']
            or task.get('state') not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
            or original.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
            or any(audit.get(k) != v for k, v in {'run_id': data['run_id'], 'action_id': 'QS-A13',
                'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                'result_sha256': source['result_sha256'], 'result_kind': 'completed'}.items())):
        raise ValueError('V1 input changes original QS research result/task/audit provenance')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    if (request.context.run_id != data['run_id'] or request.context.contract_ref.id != 'OWN-A03'
            or request.context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'OWN-A03' or settings.research_comparison_inputs is None
            or identity.organization_id == data['owner_organization_id']
            or request.context.operation_id == identity.request_id
            or request.context.operation_id not in settings.research_comparison_inputs.selections):
        raise ValueError('V1 requires a distinct formal Owner A03 invocation and independently delegated QS research')
    selection = settings.research_comparison_inputs.selections[request.context.operation_id].model_dump(mode='json')
    if selection != source['selection'] or selection['source_task_sha256'] != identity.key:
        raise ValueError('V1 Owner configuration substitutes the selected original research or reception')
    files = [current, previous]
    if 'assembly_sources' in data:
        assembly = data['assembly_sources']
        if not isinstance(assembly, dict) or set(assembly) != {'owner_input', 'receipt'}:
            raise ValueError('V1 assembly requires its original Owner input and independent receipt file')
        captured = {}
        for label, binding in assembly.items():
            if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                    or not isinstance(binding['path'], str) or not binding['path'].strip()
                    or not _digest(binding['file_sha256'])):
                raise ValueError('V1 assembly source requires its original path and raw file SHA')
            item = read_source(current[0].parent / binding['path'])
            if item[1] != binding['file_sha256']:
                raise ValueError('V1 Owner input or original receipt file changed after assembly')
            files.append(item)
            captured[label] = item[2]
        owner = captured['owner_input']
        if owner != {key: data[key] for key in ('run_id', 'owner_organization_id', 'request', 'configuration')}:
            raise ValueError('V1 assembly substitutes the supplied original Owner input')
        receipt = InvestmentResearchReceiptView.model_validate(captured['receipt'])
        expected = {'source_task_sha256': identity.key, 'source_record_sha256': source['record_sha256'],
            'source_result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256']}
        if (task_digest(receipt.model_dump(mode='json')) != source['receipt_sha256']
                or receipt.ref.model_dump(mode='json') != selection['receipt_ref']
                or task_digest([link.model_dump(mode='json') for link in receipt.option_links]) != source['option_links_sha256']
                or receipt.run_id != data['run_id'] or receipt.recipient_organization_id != data['owner_organization_id']
                or receipt.author_organization_id != identity.organization_id or receipt.report != result['payload']['comparison']
                or any(getattr(receipt, key) != value for key, value in expected.items())):
            raise ValueError('V1 assembly receipt changes original report, recipient, option links or provenance')
    return tuple(files), deepcopy(data), identity, request, config


def build_v1_research_investment_input(*, research_result_path, owner_input_path, receipt_path, output_path):
    """Assemble pinned configuration from supplied originals without executing either action.

    owner_input contains run_id, owner_organization_id, request and configuration.
    The receipt is an actual full ResearchComparisonReceipt projection. Its
    publication/authorization remains independently verified by the source host.
    """
    original_file = _read(research_result_path)
    owner_file = _read(owner_input_path)
    receipt_file = _read(receipt_path)
    original, owner = original_file[2], owner_file[2]
    if (not isinstance(owner, dict) or set(owner) != {'run_id', 'owner_organization_id', 'request', 'configuration'}):
        raise ValueError('V1 configuration assembly requires explicit complete Owner request and host configuration')
    receipt = InvestmentResearchReceiptView.model_validate(receipt_file[2])
    evidence = original['execution_evidence']
    identity = TaskIdentity(**evidence['identity'])
    result = original['result']
    report = result['payload']['comparison']
    expected = {'source_task_sha256': identity.key, 'source_record_sha256': evidence['record_sha256'],
        'source_result_sha256': task_digest(result), 'source_reading_sha256': evidence['source_reading_sha256']}
    if (receipt.run_id != owner['run_id'] or receipt.recipient_organization_id != owner['owner_organization_id']
            or receipt.author_organization_id != identity.organization_id or receipt.report != report
            or any(getattr(receipt, k) != v for k, v in expected.items())):
        raise ValueError('V1 actual reception substitutes the selected original report, author, recipient or provenance')
    selection = {'source_task_sha256': identity.key, 'receipt_ref': receipt.ref.model_dump(mode='json')}
    data = {'schema_version': 'lifecycle-v1-research-investment-input.v1', 'scenario_id': 'V1',
        'run_id': owner['run_id'], 'owner_organization_id': owner['owner_organization_id'], 'source_mode': 'formal',
        'research': {'result_path': str(original_file[0]), 'result_file_sha256': original_file[1],
            'identity': identity.as_dict(), 'record_sha256': evidence['record_sha256'],
            'result_sha256': task_digest(result), 'reading_sha256': evidence['source_reading_sha256'],
            'receipt_sha256': task_digest(receipt.model_dump(mode='json')),
            'option_links_sha256': task_digest([link.model_dump(mode='json') for link in receipt.option_links]),
            'selection': selection},
        'request': deepcopy(owner['request']), 'configuration': deepcopy(owner['configuration']),
        'assembly_sources': {label: {'path': str(item[0]), 'file_sha256': item[1]}
            for label, item in (('owner_input', owner_file), ('receipt', receipt_file))}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V1 configuration output must be a new file')
    _prepare_data((destination, task_digest(data), data),
        captured_sources={item[0]: item for item in (original_file, owner_file, receipt_file)})
    if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in (original_file, owner_file, receipt_file)):
        raise ValueError('V1 supplied configuration sources changed during assembly')
    # Exclusive creation preserves existing input documents, including when
    # another writer created the destination during validation.
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


def run_v1_research_investment(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V1 execution selection must be an explicit boolean')
    files, data, source_identity, request, config = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v1-research-investment-plan.v1', 'scenario_id': 'V1',
        'run_id': data['run_id'], 'source_mode': 'formal', 'mode': 'plan_only', 'factory': _FACTORY,
        'inputs': [{'path': str(p), 'sha256': sha} for p, sha, _ in files],
        'request_sha256': task_digest(request.model_dump(mode='json')),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'research': deepcopy(data['research']),
        'assembly_source_provenance': 'retained_file_hashes' if 'assembly_sources' in data else 'legacy_inline_only',
        'limitations': ['Limited research does not supply lifecycle cash forecasts or investment approval.',
            'Application sources must supply original QS records, actual research reception, exact option mappings and independent validators.',
            'An Owner decision is separate from native investment authorization and project creation.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'research-result-input.json', files[1][2])
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {**plan, 'status': 'started', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V1 original research or Owner input changed before execution')
        output = run_role_contract(request=request, configuration=config, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'owner', offline=False)
        evidence, result = output['execution_evidence'], output['result']
        identity, task = evidence['identity'], evidence['task']
        provenance = evidence['research_comparison_input']
        source = data['research']
        expected = {'source_task_sha256': source_identity.key, 'source_record_sha256': source['record_sha256'],
            'source_result_sha256': source['result_sha256'], 'source_reading_sha256': source['reading_sha256'],
            'report_sha256': task_digest(files[1][2]['result']['payload']['comparison']),
            'receipt_ref': source['selection']['receipt_ref'], 'receipt_sha256': source['receipt_sha256'],
            'option_links_sha256': source['option_links_sha256']}
        if (output['source_mode'] != 'formal' or output['action_id'] != 'OWN-A03'
                or identity['run_id'] != data['run_id'] or identity['organization_id'] != data['owner_organization_id']
                or identity['action_id'] != 'OWN-A03' or identity['role'] != 'Owner' or identity['purpose'] != 'action'
                or identity['request_id'] != request.context.operation_id
                or identity['input_sha256'] != task_digest(request.action_input)
                or identity['context_sha256'] != task_digest(request.context.model_dump(mode='json'))
                or evidence['result_table'] != 'owner_investment_results' or task['identity'] != identity
                or not _digest(evidence['record_sha256']) or not _digest(evidence['source_reading_sha256'])
                or output['audit'] != [evidence['saved_audit']]
                or any(evidence['saved_audit'].get(k) != v for k, v in {'run_id': data['run_id'],
                    'action_id': 'OWN-A03', 'operation_id': request.context.operation_id,
                    'input_sha256': identity['input_sha256'], 'result_sha256': task_digest(result),
                    'result_kind': result['kind']}.items())
                or not isinstance(provenance, dict) or any(provenance.get(k) != v for k, v in expected.items())
                or not _digest(provenance.get('execution_source_reading_sha256'))):
            raise ValueError('V1 Owner outcome lacks original durable task/audit or selected research reception provenance')
        if result['kind'] == 'completed':
            if (result['payload']['choice'] not in _INVESTMENT_CHOICES or task['output'] != result
                    or task['output_sha256'] != task_digest(result)):
                raise ValueError('V1 outcome substitutes an investment decision or its durable output')
        elif task['output'] is not None or task['state'] not in {'waiting_input', 'technical_failure'}:
            raise ValueError('V1 incomplete investment must preserve waiting or technical failure')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != sha for p, sha, _ in files):
            raise ValueError('V1 original research or Owner input changed during execution')
        summary = {**plan, 'mode': 'executed_formal', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result_kind': result['kind'],
            'result_path': 'owner/result.json', 'result_sha256': task_digest(output)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'result_kind': result['kind']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--input', type=Path)
    inputs.add_argument('--research-result', type=Path)
    parser.add_argument('--owner-input', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.research_result is not None:
        if args.owner_input is None or args.receipt is None or args.execute:
            parser.error('--research-result requires --owner-input and --receipt; assembly does not execute actions')
        build_v1_research_investment_input(research_result_path=args.research_result,
            owner_input_path=args.owner_input, receipt_path=args.receipt, output_path=args.output)
    else:
        if args.owner_input is not None or args.receipt is not None:
            parser.error('--owner-input and --receipt require --research-result')
        run_v1_research_investment(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
