"""Plan or explicitly queue one selected V7 wait as an independently revalidated successor."""
import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.action_catalog import ROOT
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import ActionContext
from src.coordination.continuations import ContinuationJournal, ContinuationPreparation, ResumeSignal
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class WaitRecoverySources:
    """Original journal with real current condition evaluators and preparation.

    Application callbacks own current fact/authority reads and locks. prepare
    supplies the independently assembled successor, and revalidate confirms it.
    Signal content is only a scheduling hint. Cleanup remains the application's.
    """
    journal: ContinuationJournal
    prepare: Callable
    revalidate: Callable
    read_guard: Callable
    close: Callable

    def __post_init__(self):
        if (not isinstance(self.journal, ContinuationJournal)
                or not all(callable(callback) for callback in (self.prepare, self.revalidate, self.read_guard, self.close))):
            raise ValueError('V7 wait recovery requires original journal and independent current preparation/validation')


def _prepare(input_path):
    path = Path(input_path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    if (set(data) != {'schema_version', 'scenario_id', 'source_identity', 'source_task_sha256',
            'wait_sha256', 'signal', 'successor', 'recovery'}
            or data['schema_version'] != 'lifecycle-v7-wait-recovery-input.v1' or data['scenario_id'] != 'V7'):
        raise ValueError('V7 wait recovery requires explicit original task/wait, signal and successor selection')
    identity = TaskIdentity(**data['source_identity'])
    signal = ResumeSignal.model_validate(data['signal'])
    inventory = json.loads((ROOT / 'config/action_registry.json').read_text(encoding='utf-8'))
    action_roles = {action['action_id']: action['role'] for action in inventory['actions']}
    if (action_roles.get(identity.action_id) != identity.role
            or identity.purpose != 'action' or signal.run_id != identity.run_id
            or signal.organization_id != identity.organization_id):
        raise ValueError('V7 wait recovery changes original supported action/run/recipient')
    successor = data['successor']
    if not isinstance(successor, dict) or set(successor) != {'identity', 'facts_sha256', 'authorization_sha256', 'input', 'context'}:
        raise ValueError('V7 successor requires explicit current input/context and independently checked fact/authority digests')
    preparation = ContinuationPreparation(TaskIdentity(**successor['identity']), successor['facts_sha256'],
        successor['authorization_sha256'], deepcopy(successor['input']), deepcopy(successor['context']))
    context = ActionContext.model_validate(preparation.next_context)
    if (any(getattr(preparation.successor, field) != getattr(identity, field)
            for field in ('run_id', 'organization_id', 'role', 'action_id', 'purpose'))
            or preparation.successor.key == identity.key or context.operation_id != preparation.successor.request_id
            or context.contract_ref.id != identity.action_id or context.execution_mode == 'offline_fixture'
            or context.run_id != identity.run_id or context.business_time != signal.business_time):
        raise ValueError('V7 successor must be a distinct same-action current formal invocation')
    recovery = data['recovery']
    if (not isinstance(recovery, dict) or set(recovery) != {'factory', 'settings', 'journal_path'}
            or not isinstance(recovery['factory'], str) or recovery['factory'].count(':') != 1
            or not all(recovery['factory'].split(':')) or not isinstance(recovery['settings'], dict)
            or not isinstance(recovery['journal_path'], str) or not recovery['journal_path'].strip()):
        raise ValueError('V7 wait requires explicit existing original journal and application factory')
    for value in (data['source_task_sha256'], data['wait_sha256']):
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V7 original task/wait selection requires SHA256 digests')
    journal = (path.parent / recovery['journal_path']).resolve()
    if not journal.is_file():
        raise ValueError('V7 wait recovery requires an existing journal; no original task recreation')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(data), identity, signal, preparation, journal


def run_v7_wait_recovery(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V7 wait execution selection must be an explicit boolean')
    path, digest, data, identity, signal, expected, journal_path = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v7-wait-recovery-plan.v1', 'scenario_id': 'V7',
        'mode': 'queue_selected_wait' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'source_identity': identity.as_dict(), 'signal': signal.model_dump(mode='json'),
        'successor': deepcopy(data['successor']), 'journal_path': str(journal_path),
        'limitations': ['Signal and new terms alone do not prove a condition is ready; actual current evaluators decide.',
            'Only the selected original wait may queue a successor; no action or transport is executed.']}
    atomic_json(directory / 'input.json', data)
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v7-wait-recovery-attempt.v1', 'status': 'started', 'input_sha256': digest}
    atomic_json(directory / 'attempt.json', attempt)
    sources = None
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or not journal_path.is_file():
            raise ValueError('V7 selected input changed or original journal disappeared')
        module, name = data['recovery']['factory'].split(':')
        factory = getattr(importlib.import_module(module), name)
        descriptor = module_factory_descriptor(factory, data['recovery']['factory'])
        sources = factory(identity=TaskIdentity(**identity.as_dict()), journal_path=journal_path,
            settings=deepcopy(data['recovery']['settings']))
        if not isinstance(sources, WaitRecoverySources) or Path(sources.journal.store.path).resolve() != journal_path:
            raise ValueError('V7 factory substituted the original continuation journal')
        journal, store = sources.journal, sources.journal.store
        original_registry = journal.registry
        original_callbacks = {name: getattr(sources, name) for name in ('prepare', 'revalidate', 'read_guard')}
        callbacks = {name: module_factory_descriptor(getattr(sources, name), name)
            for name in ('prepare', 'revalidate', 'read_guard')}

        def check_sources():
            if (sources.journal is not journal or journal.store is not store or journal.registry is not original_registry
                    or store.run_id != identity.run_id or Path(store.path).resolve() != journal_path
                    or module_factory_descriptor(factory, data['recovery']['factory']) != descriptor
                    or any(getattr(sources, name) is not original_callbacks[name]
                        or module_factory_descriptor(getattr(sources, name), name) != value
                        for name, value in callbacks.items())):
                raise TaskConflict('V7 original journal, condition registry, factory or validation callbacks changed')

        check_sources()
        with sources.read_guard(TaskIdentity(**identity.as_dict()), signal.model_copy(deep=True)):
            check_sources()
            before = store.get(identity)
            waits = [row for row in journal.pending(run_id=identity.run_id, organization_id=identity.organization_id)
                if row['identity'] == identity.as_dict()]
            if (task_digest(before) != data['source_task_sha256'] or before['state'] != 'waiting_input'
                    or before['output'] is not None or before['submission'] is not None or before['receipt'] is not None
                    or len(waits) != 1 or task_digest(waits[0]) != data['wait_sha256'] or store.continuation(identity) is not None):
                raise TaskConflict('V7 selected original wait changed or already has output/transport/successor')
            atomic_json(directory / 'before.json', before)

            def prepare(source, current_signal):
                check_sources()
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise TaskConflict('V7 selected recovery input changed before successor preparation')
                actual = sources.prepare(deepcopy(source), current_signal.model_copy(deep=True))
                check_sources()
                if (not isinstance(actual, ContinuationPreparation) or actual != expected
                        or source['identity'] != identity.as_dict() or current_signal != signal):
                    raise TaskConflict('V7 application preparation changes selected current successor or source wait')
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise TaskConflict('V7 selected recovery input changed during successor preparation')
                return actual

            def revalidate(source, preparation, current_signal):
                check_sources()
                if (source['identity'] != identity.as_dict() or preparation != expected or current_signal != signal
                        or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                    raise TaskConflict('V7 current validation changes selected original wait, successor or recovery input')
                ready = sources.revalidate(deepcopy(source), deepcopy(preparation), current_signal.model_copy(deep=True))
                check_sources()
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise TaskConflict('V7 selected recovery input changed during independent current revalidation')
                return ready

            check_sources()
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise TaskConflict('V7 selected recovery input changed before condition evaluation')
            links = journal.wake(signal, prepare=prepare, revalidate=revalidate,
                action_ids={identity.action_id}, source_keys={identity.key})
            check_sources()
            after = store.get(identity)
            link = store.continuation(identity)
            atomic_json(directory / 'after.json', after)
            if link is not None:
                atomic_json(directory / 'continuation.json', link)
            if links:
                expected_link = {'source': identity.as_dict(), 'successor': expected.successor.as_dict(),
                    'source_revision': before['revision'], 'conditions': waits[0]['conditions'],
                    'profile_versions': waits[0]['profile_versions'], 'signal': signal.model_dump(mode='json'),
                    'facts_sha256': expected.facts_sha256, 'authorization_sha256': expected.authorization_sha256,
                    'next_input': expected.next_input, 'next_context': expected.next_context}
                if (len(links) != 1 or links[0] != link
                        or any(link.get(key) != value for key, value in expected_link.items())):
                    raise TaskConflict('V7 wake changes selected successor, current facts/authority, conditions or complete snapshots')
                next_task = store.get(expected.successor)
                atomic_json(directory / 'successor.json', next_task)
                if (next_task['state'] != 'waiting_input' or next_task['output'] is not None
                        or next_task['submission'] is not None or next_task['receipt'] is not None):
                    raise TaskConflict('V7 wake executed a successor or produced transport/business effects')
                outcome = 'queued'
            elif link is not None or after != before:
                raise TaskConflict('V7 unready condition consumed or changed the original wait')
            else:
                outcome = 'waiting'
            if any(after[key] != before[key] for key in ('identity', 'output', 'output_sha256', 'submission', 'receipt', 'conditions')):
                raise TaskConflict('V7 wake overwrote original result, terms, conditions or transport evidence')
            check_sources()
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise TaskConflict('V7 selected recovery input changed during condition evaluation or successor commit')
            summary = {**plan, 'mode': 'selected_wait_checked', 'outcome': outcome, 'continuation': deepcopy(link)}
            atomic_json(directory / 'summary.json', summary)
            atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'outcome': outcome})
            return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise
    finally:
        if isinstance(sources, WaitRecoverySources):
            sources.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run_v7_wait_recovery(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
