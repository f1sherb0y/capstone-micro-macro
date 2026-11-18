"""Plan or explicitly query one original uncertain BANK-A07 submission after restart."""
import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
from typing import Callable

from integration.bank_submission_host import BankSubmissionHost
from integration.module_host import module_factory_descriptor
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import TaskIdentity, task_digest


@dataclass(frozen=True)
class BankRecoverySources:
    """Application reopens its original host/journal with current query authority.

    Factory owns cleanup, must not submit, rerun an action, or create an original
    task. Host query/receipt validators retain native authentication and access
    checks. This entry exercises recovery only; it cannot prove a third-party
    callback is read-only without independent native transport evidence.
    """
    host: BankSubmissionHost
    close: Callable

    def __post_init__(self):
        if not isinstance(self.host, BankSubmissionHost) or not callable(self.close):
            raise ValueError('V7 recovery requires original Bank submission host and application cleanup')


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _snapshot(host, identity):
    with host.read_guard(TaskIdentity(**identity.as_dict())):
        host._check()
        row = host.store.get(identity)
        record = host.workers[identity.action_id].get_record(identity)
        host._check()
        return row, record


def _prepare(input_path):
    current = _read(input_path)
    data = current[2]
    if (set(data) != {'schema_version', 'scenario_id', 'run_id', 'source_mode', 'original_execution', 'recovery'}
            or data['schema_version'] != 'lifecycle-v7-bank-recovery-input.v1'
            or data['scenario_id'] != 'V7' or data['source_mode'] != 'formal'):
        raise ValueError('V7 recovery requires original formal Bank execution and explicit existing journal binding')
    selected, recovery = data['original_execution'], data['recovery']
    if (not isinstance(selected, dict) or set(selected) != {'result_path', 'result_file_sha256', 'identity',
            'record_sha256', 'result_sha256', 'reading_sha256'}
            or not isinstance(recovery, dict) or set(recovery) != {'factory', 'settings', 'journal_path',
                'host_configuration_sha256', 'task_sha256', 'expected_outcome'}
            or recovery['expected_outcome'] not in {'unknown', 'accepted', 'rejected'}
            or not isinstance(recovery['factory'], str) or recovery['factory'].count(':') != 1
            or not all(recovery['factory'].split(':')) or not isinstance(recovery['settings'], dict)
            or any(not isinstance(value, str) or not value.strip()
                for value in (selected['result_path'], recovery['journal_path']))):
        raise ValueError('V7 requires exact original provenance, existing journal, factory and expected query outcome')
    for value in [selected[key] for key in ('result_file_sha256', 'record_sha256', 'result_sha256', 'reading_sha256')] + [
            recovery['host_configuration_sha256'], recovery['task_sha256']]:
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V7 original execution/recovery provenance requires SHA256 digests')
    previous = _read(current[0].parent / selected['result_path'])
    original = previous[2]
    identity = TaskIdentity(**selected['identity'])
    evidence = original.get('execution_evidence', {})
    audit, task = evidence.get('saved_audit', {}), evidence.get('task', {})
    if (previous[1] != selected['result_file_sha256'] or original.get('run_id') != data['run_id']
            or original.get('action_id') != 'BANK-A07' or original.get('source_mode') != 'formal'
            or identity.run_id != data['run_id'] or identity.role != 'Bank' or identity.action_id != 'BANK-A07'
            or identity.purpose != 'action' or evidence.get('identity') != identity.as_dict()
            or evidence.get('result_table') != 'bank_execution_results'
            or evidence.get('record_sha256') != selected['record_sha256']
            or evidence.get('source_reading_sha256') != selected['reading_sha256']
            or original.get('result', {}).get('kind') != 'completed'
            or original['result']['payload']['choice'] != 'execute'
            or task_digest(original['result']) != selected['result_sha256']
            or task.get('identity') != identity.as_dict() or task.get('output') != original['result']
            or task.get('output_sha256') != selected['result_sha256'] or original.get('audit') != [audit]
            or any(audit.get(key) != value for key, value in {'run_id': data['run_id'], 'action_id': 'BANK-A07',
                'input_sha256': identity.input_sha256, 'operation_id': identity.request_id,
                'result_sha256': selected['result_sha256'], 'result_kind': 'completed'}.items())
            or audit.get('reading', {}).get('source_mode') != 'formal'):
        raise ValueError('V7 changes original formal Bank execution task/result/audit')
    journal = (current[0].parent / recovery['journal_path']).resolve()
    if not journal.is_file():
        raise ValueError('V7 recovery requires the existing original journal; no recreation')
    return (current, previous), deepcopy(data), identity, journal


def run_v7_bank_recovery(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V7 recovery execution selection must be an explicit boolean')
    files, data, identity, journal = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v7-bank-recovery-plan.v1', 'scenario_id': 'V7', 'run_id': data['run_id'],
        'action_id': 'BANK-A07', 'source_mode': 'formal', 'mode': 'query_original' if execute else 'plan_only',
        'identity': identity.as_dict(), 'journal_path': str(journal),
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'recovery': deepcopy(data['recovery']),
        'limitations': ['Recovery queries an original uncertain submission; it does not initiate or retry a payment.',
            'Native callbacks remain external dependencies; receipt acceptance does not establish cash or principal effects.']}
    for name, value in (('input', data), ('bank-result-input', files[1][2]), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v7-bank-recovery-attempt.v1', 'status': 'started', 'inputs': plan['inputs'],
        'query_attempted': False, 'query_completed': False, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    sources = None
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files) or not journal.is_file():
            raise ValueError('V7 input/evidence changed or original journal disappeared before recovery')
        recovery = data['recovery']
        module, name = recovery['factory'].split(':')
        factory = getattr(importlib.import_module(module), name)
        descriptor = module_factory_descriptor(factory, recovery['factory'])
        sources = factory(identity=TaskIdentity(**identity.as_dict()), journal_path=journal,
            settings=deepcopy(recovery['settings']))
        if not isinstance(sources, BankRecoverySources):
            raise ValueError('V7 factory must return original BankRecoverySources')
        host = sources.host
        if (Path(host.store.path).resolve() != journal or host.store.run_id != identity.run_id
                or identity.action_id not in host.routes or host.callbacks[identity.action_id].query is None
                or host.capabilities()['configuration_sha256'] != recovery['host_configuration_sha256']):
            raise ValueError('V7 factory substituted original journal, host configuration or query route')
        before, original_record = _snapshot(host, identity)
        selected = data['original_execution']
        if (task_digest(before) != recovery['task_sha256'] or before['state'] not in {'waiting_receipt', 'receipt_unknown'}
                or before['receipt'] is not None or before['submission'] is None
                or before['output'] != files[1][2]['result'] or before['output_sha256'] != selected['result_sha256']
                or original_record is None or original_record['record_sha256'] != selected['record_sha256']
                or original_record['source_reading_sha256'] != selected['reading_sha256']):
            raise ValueError('V7 lacks exact existing original uncertain task and saved source/result record')
        atomic_json(directory / 'before.json', before)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files) or not journal.is_file():
            raise ValueError('V7 selected input/evidence changed during source initialization; query not started')
        attempt = {**attempt, 'query_attempted': True}
        atomic_json(directory / 'attempt.json', attempt)
        after = host.recover(identity, expected_task_sha256=recovery['task_sha256'])
        attempt = {**attempt, 'query_completed': True}
        atomic_json(directory / 'attempt.json', attempt)
        atomic_json(directory / 'after.json', after)
        current_row, current_record = _snapshot(host, identity)
        if (current_row != after or current_record != original_record
                or any(after[key] != before[key] for key in ('identity', 'output', 'output_sha256', 'submission', 'conditions'))
                or host.capabilities()['configuration_sha256'] != recovery['host_configuration_sha256']
                or module_factory_descriptor(factory, recovery['factory']) != descriptor):
            raise ValueError('V7 recovery changed original request/output/source record or host binding')
        if after['state'] == 'reconciled':
            receipt = host.read_receipt(identity)
            outcome = receipt['receipt']['disposition']
        elif after['state'] == 'receipt_unknown' and after['receipt'] is None:
            receipt, outcome = None, 'unknown'
        else:
            raise ValueError('V7 recovery did not preserve an unknown result or correlated terminal receipt')
        if outcome != recovery['expected_outcome']:
            raise ValueError('V7 original query outcome differs from explicitly declared scenario expectation')
        if (any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files)
                or not journal.is_file() or sources.host is not host or Path(host.store.path).resolve() != journal):
            raise ValueError('V7 recovery changed retained original input/evidence or original journal/host binding')
        summary = {**plan, 'mode': 'queried_original', 'outcome': outcome, 'factory': descriptor,
            'before_sha256': task_digest(before), 'after_sha256': task_digest(after), 'receipt': deepcopy(receipt),
            'limitations': ['Only original query recovery was invoked locally; independent native evidence is needed to prove transport behavior.',
                'This case does not cover every V7 timeout, changed term, late event, deduplication or invalid-output branch.']}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'outcome': outcome})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise
    finally:
        if isinstance(sources, BankRecoverySources):
            sources.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run_v7_bank_recovery(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
