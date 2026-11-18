"""Freeze original QS certifications and actual single or allocated Owner receptions."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.lifecycle_v5_owner_bank_reception import _read, run_prepared
from integration.owner_role_contract_host import OwnerPaymentCertificateMappingSelection, OwnerRoleContractSettings
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_payment_objects import OwnerPaymentCertificateReceiptView
from src.coordination.tasks import TaskIdentity, task_digest
from src.organization.registry import scope_covers


_SCHEMA = 'lifecycle-v5-qs-certificate-owner-input.v1'
_OWNER_FIELDS = {'run_id', 'owner_organization_id', 'request', 'configuration'}
_DECLARATION = {'prefix': 'lifecycle-v5-qs-certificate-owner', 'recipient': 'OWN-A06',
    'recipient_table': 'owner_payment_results', 'evidence': 'certificate_input', 'source_labels': ()}


def _prepare_data(current, *, captured=None):
    data = current[2]
    if (set(data) != _OWNER_FIELDS | {'schema_version', 'scenario_id', 'sources'}
            or data['schema_version'] != _SCHEMA or data['scenario_id'] != 'V5'
            or not isinstance(data['owner_organization_id'], str) or not data['owner_organization_id'].strip()
            or not isinstance(data['sources'], dict)
            or set(data['sources']) != {'owner_input', 'certificate_sources', 'certificates'}):
        raise ValueError('V5 certificate reception requires original Owner input and explicitly retained QS file groups')
    files = [current]

    def retained(binding):
        if (not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}
                or not isinstance(binding['path'], str) or not binding['path'].strip()
                or not isinstance(binding['file_sha256'], str) or len(binding['file_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in binding['file_sha256'])):
            raise ValueError('V5 original certificate file requires its path and raw SHA256')
        path = (current[0].parent / binding['path']).resolve()
        item = captured.get(path) if captured is not None else None
        if item is None:
            item = _read(path)
        if item[1] != binding['file_sha256']:
            raise ValueError('V5 retained certificate source changed')
        files.append(item)
        return item

    sources = data['sources']
    owner_file, selection_file = retained(sources['owner_input']), retained(sources['certificate_sources'])
    if owner_file[2] != {key: data[key] for key in _OWNER_FIELDS}:
        raise ValueError('V5 certificate reception replaces original Owner input/configuration')
    groups = selection_file[2]
    if (set(groups) != {'schema_version', 'certificates'}
            or groups['schema_version'] != 'lifecycle-v5-certificate-observation-files.v1'
            or not isinstance(groups['certificates'], list) or not groups['certificates']
            or not isinstance(sources['certificates'], list)):
        raise ValueError('V5 certificate reception requires explicit original certificate file selections')
    request = RoleContractInvocation.model_validate(data['request'])
    config = RoleContractHostConfiguration.model_validate(data['configuration'])
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    context = request.context
    if (context.run_id != data['run_id'] or context.contract_ref.id != 'OWN-A06'
            or context.execution_mode != 'llm' or request.execution_path == 'deterministic'
            or settings.action_id != 'OWN-A06' or settings.certificate_inputs is None
            or context.operation_id not in settings.certificate_inputs.selections):
        raise ValueError('V5 certificate reception requires formal Owner A06 and current certificate selection')
    selected = settings.certificate_inputs.selections[context.operation_id]
    mapping = isinstance(selected, OwnerPaymentCertificateMappingSelection)
    selections = selected.certificates if mapping else [selected]
    if len(selections) != len(sources['certificates']) or len(selections) != len(groups['certificates']):
        raise ValueError('V5 certificate reception omits or adds an original selected certificate')
    provenance, tasks, receipt_refs = [], set(), set()
    due_refs = {Reference.model_validate(ref) for ref in request.action_input['due_refs']}
    for binding, group, selection in zip(sources['certificates'], groups['certificates'], selections):
        if (not isinstance(binding, dict) or set(binding) != {'qs_result', 'receipt'}
                or not isinstance(group, dict) or set(group) != {'qs_result', 'receipt'}):
            raise ValueError('V5 certificate selection requires original QS result and actual reception paths')
        items = {}
        for label in ('qs_result', 'receipt'):
            items[label] = retained(binding[label])
            if (not isinstance(group[label], str) or not group[label].strip()
                    or (selection_file[0].parent / group[label]).resolve() != items[label][0]):
                raise ValueError('V5 certificate group replaces its original file selection')
        original = items['qs_result'][2]
        evidence, result = original['execution_evidence'], original['result']
        identity = TaskIdentity(**evidence['identity'])
        task, audit = evidence['task'], evidence['saved_audit']
        if (identity.key != selection.source_task_sha256 or identity.key in tasks
                or identity.run_id != data['run_id'] or identity.role != 'QS' or identity.action_id != 'QS-A08'
                or identity.purpose != 'action' or identity.organization_id == data['owner_organization_id']
                or identity.request_id == context.operation_id or original['run_id'] != data['run_id']
                or original['action_id'] != 'QS-A08' or original['source_mode'] != 'formal'
                or evidence['result_table'] != 'qs_payment_results' or result['kind'] != 'completed'
                or result['payload']['choice'] not in {'certify', 'correct_certificate'}
                or task['identity'] != identity.as_dict() or task['output'] != result
                or task['output_sha256'] != task_digest(result)
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or original['audit'] != [audit] or audit.get('reading', {}).get('source_mode') != 'formal'
                or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'QS-A08',
                    'operation_id': identity.request_id, 'input_sha256': identity.input_sha256,
                    'result_sha256': task_digest(result), 'result_kind': 'completed'}.items())):
            raise ValueError('V5 certificate reception changes original formal QS task/result/audit')
        receipt = OwnerPaymentCertificateReceiptView.model_validate(items['receipt'][2])
        receipt_sha = task_digest(receipt.model_dump(mode='json'))
        expected = {'source_task_sha256': identity.key, 'source_record_sha256': evidence['record_sha256'],
            'source_result_sha256': task_digest(result), 'source_reading_sha256': evidence['source_reading_sha256']}
        if (any(getattr(receipt, key) != value for key, value in expected.items())
                or receipt.run_id != data['run_id'] or receipt.author_organization_id != identity.organization_id
                or receipt.recipient_organization_id != data['owner_organization_id'] or receipt.ref in receipt_refs
                or receipt.ref != selection.receipt_ref or selection.receipt_sha256 != receipt_sha
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise ValueError('V5 certificate reception replaces original QS/Owner parties, sources or retained receipt')
        if mapping:
            if receipt.obligation_ref is not None or not receipt.allocations or any(
                    row.obligation_ref not in due_refs for row in receipt.allocations):
                raise ValueError('V5 allocated certificates require explicit current due-obligation mappings')
        elif receipt.allocations is not None or receipt.obligation_ref not in due_refs:
            raise ValueError('V5 single certificate requires its original current due obligation')
        tasks.add(identity.key)
        receipt_refs.add(receipt.ref)
        provenance.append({**expected, 'receipt_ref': receipt.ref.model_dump(mode='json'), 'receipt_sha256': receipt_sha})
    expected = {'certificates': provenance} if mapping else provenance[0]
    return tuple(files), deepcopy(data), request.model_dump(mode='json'), config.model_dump(mode='json'), expected


def build_v5_qs_certificate_owner_input(*, owner_input_path, certificate_sources_path, output_path):
    owner_file, selection_file = _read(owner_input_path), _read(certificate_sources_path)
    owner, groups = owner_file[2], selection_file[2]
    if set(owner) != _OWNER_FIELDS or not isinstance(groups.get('certificates'), list):
        raise ValueError('V5 certificate assembly requires complete Owner input and explicit original file groups')
    captured = {owner_file[0]: owner_file, selection_file[0]: selection_file}

    def file_binding(item):
        return {'path': str(item[0]), 'file_sha256': item[1]}

    certificates = []
    for group in groups['certificates']:
        if not isinstance(group, dict) or set(group) != {'qs_result', 'receipt'}:
            raise ValueError('V5 certificate file group requires original QS result and receipt paths')
        row = {}
        for label, path in group.items():
            if not isinstance(path, str) or not path.strip():
                raise ValueError('V5 certificate source path must be explicit')
            item = _read(selection_file[0].parent / path)
            if item[0] in captured and captured[item[0]] != item:
                raise ValueError('V5 original certificate source changed during assembly')
            captured[item[0]] = item
            row[label] = file_binding(item)
        certificates.append(row)
    data = {'schema_version': _SCHEMA, 'scenario_id': 'V5', **deepcopy(owner), 'sources': {
        'owner_input': file_binding(owner_file), 'certificate_sources': file_binding(selection_file), 'certificates': certificates}}
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError('V5 certificate input must be a new file')
    _prepare_data((destination, task_digest(data), data), captured=captured)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in captured.values()):
        raise ValueError('V5 original certificate files changed during assembly')
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


def run_v5_qs_certificate_owner(*, input_path, output_directory, execute=False):
    return run_prepared(_prepare_data(_read(input_path)), declaration=_DECLARATION,
        output_directory=output_directory, execute=execute)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--owner-input', type=Path)
    parser.add_argument('--certificate-sources', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.owner_input is not None or args.certificate_sources is not None:
        if args.input is not None or args.execute or args.owner_input is None or args.certificate_sources is None:
            parser.error('Assembly requires --owner-input and --certificate-sources, without --input or --execute')
        build_v5_qs_certificate_owner_input(owner_input_path=args.owner_input,
            certificate_sources_path=args.certificate_sources, output_path=args.output)
        return
    if args.input is None:
        parser.error('Provide --input or both original assembly files')
    print(run_v5_qs_certificate_owner(input_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
