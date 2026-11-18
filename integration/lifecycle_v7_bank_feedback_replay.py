"""Plan or explicitly acknowledge a delayed duplicate of persisted Bank feedback."""
import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
from typing import Callable

from integration.bank_submission_feedback import BankFeedbackObservation, BankSubmissionFeedback
from integration.module_host import module_factory_descriptor
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import ActionContext
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class BankFeedbackReplaySources:
    """Application owns current history authorization, original feedback and cleanup."""
    feedback: BankSubmissionFeedback
    context: ActionContext
    reading: ActionReadView
    read_guard: Callable
    close: Callable

    def __post_init__(self):
        if (not isinstance(self.feedback, BankSubmissionFeedback) or not isinstance(self.context, ActionContext)
                or not isinstance(self.reading, ActionReadView) or not callable(self.read_guard) or not callable(self.close)):
            raise ValueError('Bank duplicate feedback requires original persistence and current authorized history reading')


def acknowledge_saved_bank_feedback(sources, *, record, observation):
    """Deduplicate immutable historical content under independent current authority.

    New context/source versions do not replace the original record. This only
    acknowledges an already persisted exact event; a first delayed event still
    requires BankSubmissionFeedback.record and its native relation validation.
    It never resolves old source snapshots as current business facts.
    """
    if not isinstance(sources, BankFeedbackReplaySources):
        raise ValueError('Bank duplicate feedback requires explicit original/current source components')
    observation = BankFeedbackObservation.model_validate(observation)
    identity = TaskIdentity(**record['identity'])
    context = sources.context.model_copy(deep=True)
    reading = sources.reading
    if (set(record) != {'schema_version', 'identity', 'receipt', 'context', 'observation', 'sources',
            'source_evidence', 'configuration_sha256', 'record_sha256'}
            or record.get('schema_version') != sources.feedback.VERSION
            or record.get('record_sha256') != task_digest({key: value for key, value in record.items() if key != 'record_sha256'})
            or observation.model_dump(mode='json') != record['observation']
            or identity.run_id != context.run_id or identity.organization_id != reading.organization_id
            or identity.role != 'Bank' or identity.purpose != 'action'
            or observation.target_action_id != context.contract_ref.id):
        raise TaskConflict('Duplicate feedback changes original immutable record, observation or current recipient/action')
    historic = ActionContext.model_validate(record['context'])
    if (context.business_time.clock_ref != historic.business_time.clock_ref
            or context.business_time.offset <= historic.business_time.offset
            or context.read_token == historic.read_token or context.operation_id == historic.operation_id
            or context.task_ref == historic.task_ref):
        raise TaskConflict('Delayed duplicate needs a distinct later authorized history invocation')
    with sources.read_guard(context.model_copy(deep=True)):
        try:
            # read() authenticates persistent schema/hash/configuration and the
            # application's independent current history visibility validator.
            records = sources.feedback.read(context=context, reading=reading)
            matches = [row for row in records if row['record_sha256'] == record['record_sha256']]
            if len(matches) != 1 or matches[0] != record:
                raise TaskConflict('Delayed duplicate lacks its exact currently authorized original persisted feedback')
            event_id = 'bank-feedback:' + task_digest([identity.key, observation.native_event_id, observation.target_action_id])
            rows = sources.feedback.inbox.for_organization(run_id=identity.run_id, organization_id=identity.organization_id)
            expected = {'run_id': identity.run_id, 'event_id': event_id,
                'organization_id': identity.organization_id, 'payload': deepcopy(record)}
            if [row for row in rows if row['event_id'] == event_id] != [expected]:
                raise TaskConflict('Duplicate feedback substitutes original inbox event identity/content')
            inserted = sources.feedback.inbox.deliver(**expected)
            if inserted is not False or sources.feedback.inbox.for_organization(
                    run_id=identity.run_id, organization_id=identity.organization_id) != rows:
                raise TaskConflict('Original duplicate feedback changed inbox records')
            sources.feedback._check()
            return {'status': 'duplicate', 'inserted': False, 'event_id': event_id,
                'record_sha256': record['record_sha256'], 'source_identity': identity.as_dict(),
                'current_context_sha256': task_digest(context.model_dump(mode='json')),
                'current_reading_sha256': task_digest(reading.evidence())}
        finally:
            reading.recheck()
            if sources.context.model_dump(mode='json') != context.model_dump(mode='json'):
                raise TaskConflict('Duplicate feedback changed original current authorization context')


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare(input_path):
    current = _read(input_path)
    data = current[2]
    if (set(data) != {'schema_version', 'scenario_id', 'run_id', 'source_mode', 'original_feedback',
            'redelivered_observation', 'replay'}
            or data['schema_version'] != 'lifecycle-v7-bank-feedback-replay-input.v1'
            or data['scenario_id'] != 'V7' or data['source_mode'] != 'formal'):
        raise ValueError('V7 duplicate feedback requires original formal persisted Bank feedback')
    selection, replay = data['original_feedback'], data['replay']
    if (not isinstance(selection, dict) or set(selection) != {'record_path', 'record_file_sha256', 'record_sha256'}
            or not isinstance(replay, dict) or set(replay) != {'factory', 'settings', 'journal_path', 'inbox_path',
                'feedback_configuration_sha256', 'context_sha256'}
            or not isinstance(replay['factory'], str) or replay['factory'].count(':') != 1
            or not all(replay['factory'].split(':')) or not isinstance(replay['settings'], dict)
            or any(not isinstance(value, str) or not value.strip()
                for value in (selection['record_path'], replay['journal_path'], replay['inbox_path']))):
        raise ValueError('V7 replay requires original record and explicit original persistence/current source factory')
    for value in (selection['record_file_sha256'], selection['record_sha256'],
            replay['feedback_configuration_sha256'], replay['context_sha256']):
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('V7 feedback replay requires SHA256 provenance')
    previous = _read(current[0].parent / selection['record_path'])
    record = previous[2]
    if (set(record) != {'schema_version', 'identity', 'receipt', 'context', 'observation', 'sources',
            'source_evidence', 'configuration_sha256', 'record_sha256'}
            or record['schema_version'] != BankSubmissionFeedback.VERSION
            or previous[1] != selection['record_file_sha256'] or record['record_sha256'] != selection['record_sha256']
            or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != record['record_sha256']
            or record['identity']['run_id'] != data['run_id'] or record['identity']['action_id'] != 'BANK-A07'
            or record['configuration_sha256'] != replay['feedback_configuration_sha256']
            or BankFeedbackObservation.model_validate(data['redelivered_observation']).model_dump(mode='json') != record['observation']):
        raise ValueError('V7 duplicate changes selected original feedback record or observation')
    paths = [(current[0].parent / replay[key]).resolve() for key in ('journal_path', 'inbox_path')]
    if not all(path.is_file() for path in paths):
        raise ValueError('V7 duplicate requires existing original journal/inbox; no recreation')
    return (current, previous), deepcopy(data), paths


def run_v7_bank_feedback_replay(*, input_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V7 feedback replay execution selection must be an explicit boolean')
    files, data, paths = _prepare(input_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v7-bank-feedback-replay-plan.v1', 'scenario_id': 'V7',
        'run_id': data['run_id'], 'action_id': 'BANK-A07', 'source_mode': 'formal',
        'mode': 'acknowledge_duplicate' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'original_feedback': deepcopy(data['original_feedback']), 'replay': deepcopy(data['replay']),
        'limitations': ['Only an exact already persisted duplicate can be acknowledged; first delayed feedback needs native validation.',
            'No payment/query/model transport or business state update is performed by this entry.']}
    for name, value in (('input', data), ('feedback-record-input', files[1][2]), ('plan', plan)):
        atomic_json(directory / (name + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v7-bank-feedback-replay-attempt.v1', 'status': 'started', 'inputs': plan['inputs'],
        'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    sources = None
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files) or not all(path.is_file() for path in paths):
            raise ValueError('V7 duplicate input/record changed or original persistence disappeared')
        replay = data['replay']
        module, name = replay['factory'].split(':')
        factory = getattr(importlib.import_module(module), name)
        descriptor = module_factory_descriptor(factory, replay['factory'])
        sources = factory(record=deepcopy(files[1][2]), journal_path=paths[0], inbox_path=paths[1], settings=deepcopy(replay['settings']))
        if (not isinstance(sources, BankFeedbackReplaySources)
                or Path(sources.feedback.host.store.path).resolve() != paths[0]
                or Path(sources.feedback.inbox.path).resolve() != paths[1]
                or task_digest(sources.feedback._declared) != replay['feedback_configuration_sha256']
                or task_digest(sources.context.model_dump(mode='json')) != replay['context_sha256']):
            raise ValueError('V7 factory changes original feedback persistence/configuration or selected current context')
        original_components = (sources.feedback, sources.feedback.host, sources.feedback.host.store,
            sources.feedback.inbox, sources.reading, sources.read_guard)
        guard_descriptor = module_factory_descriptor(sources.read_guard, 'read_guard')

        def check_binding():
            current_components = (sources.feedback, sources.feedback.host, sources.feedback.host.store,
                sources.feedback.inbox, sources.reading, sources.read_guard)
            if (any(now is not original for now, original in zip(current_components, original_components))
                    or not all(path.is_file() for path in paths)
                    or Path(sources.feedback.host.store.path).resolve() != paths[0]
                    or Path(sources.feedback.inbox.path).resolve() != paths[1]
                    or task_digest(sources.feedback._declared) != replay['feedback_configuration_sha256']
                    or task_digest(sources.context.model_dump(mode='json')) != replay['context_sha256']
                    or module_factory_descriptor(sources.read_guard, 'read_guard') != guard_descriptor
                    or module_factory_descriptor(factory, replay['factory']) != descriptor
                    or any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha, _ in files)):
                raise ValueError('V7 duplicate acknowledgement changes original input, persistence, current authority or source binding')

        check_binding()
        outcome = acknowledge_saved_bank_feedback(sources, record=files[1][2], observation=data['redelivered_observation'])
        atomic_json(directory / 'outcome.json', outcome)
        check_binding()
        summary = {**plan, 'mode': 'acknowledged_duplicate', 'factory': descriptor, 'outcome': outcome}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished', 'inserted': False})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise
    finally:
        if isinstance(sources, BankFeedbackReplaySources):
            sources.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run_v7_bank_feedback_replay(input_path=args.input, output_directory=args.output, execute=args.execute)
    print(result['mode'])


if __name__ == '__main__':
    main()
