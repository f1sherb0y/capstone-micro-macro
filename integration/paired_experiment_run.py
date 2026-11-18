"""Explicit single-action paired execution using original durable workers."""
from copy import deepcopy
from pathlib import Path

from integration.action_catalog import write_new
from integration.module_host import module_factory_descriptor
from integration.paired_experiment_callbacks import (
    PairedCallbackSet, check_saved_paired_callbacks, check_paired_callback_association,
)
from integration.paired_experiment_hosts import PairedModelHosts, recheck_paired_model_hosts
from integration.paired_experiment_results import record_paired_action_result
from integration.paired_experiments import prepare_paired_experiment
from integration.role_contract_host import prepare_role_contract_options
from integration.scenario_v2 import read_input_json
from src.actions.implementation import callable_implementation
from src.actions.model_strategy import model_client_request_policy
from src.coordination.tasks import TaskConflict, task_digest


def _same_record(left, right):
    """Compare complete JSON transport types, preserving object-key equivalence."""
    return task_digest(left) == task_digest(right)


def _submission_implementations(submit_action, validate_submission):
    return {name: {'descriptor': module_factory_descriptor(callback, specification),
        'implementation': callable_implementation(callback)} for name, callback, specification in (
            ('adapter', submit_action, 'paired.actual_submission'),
            ('validator', validate_submission, 'paired.submission_validation'))}


def run_paired_action(assembly, *, output_root: Path, strategy, worker, prepared, request_id,
        read_guard, validate_execute, validate_record, read_feedback=None,
        read_cost=None, validate_cost=None, submit_action=None, validate_submission=None):
    """Execute at most one original ready task, only on this explicit call.

    Existing results are observed without finalizing/replaying the worker.
    Processing, pending, failed, submitted or unresolved intent stays read-only.
    The caller owns clients/stores. Optional explicit submission uses the actual
    application's original durable host, with its own immutable no-replay intent.
    write_new claims an immutable intent before the original worker's claim,
    so a crash before worker.start is also retained for explicit diagnosis.
    An optional application reader supplies original feedback for the existing
    provenance gate. Reading cannot advance the task or create a submission.
    """
    if (not isinstance(assembly, PairedModelHosts) or strategy not in assembly.hosts
            or not all(callable(gate) for gate in (read_guard, validate_execute, validate_record))
            or read_feedback is not None and not callable(read_feedback)
            or (read_cost is None) != (validate_cost is None)
            or read_cost is not None and not all(callable(gate) for gate in (read_cost, validate_cost))
            or (submit_action is None) != (validate_submission is None)
            or submit_action is not None and not all(callable(gate) for gate in (submit_action, validate_submission))):
        raise TaskConflict('Paired run requires its actual assembly, source guard and explicit execution/read gates')
    callbacks = PairedCallbackSet(read_guard=read_guard, validate_execute=validate_execute,
        validate_record=validate_record, read_feedback=read_feedback, read_cost=read_cost,
        validate_cost=validate_cost, submit_action=submit_action, validate_submission=validate_submission)
    if assembly.evidence.get('application_callbacks') is not None:
        names = {name: name for name in ('read_guard', 'validate_execute', 'validate_record',
            'read_feedback', 'read_cost', 'validate_cost')}
        if submit_action is not None:
            names.update(submit_action='submit_action', validate_submission='validate_submission')
        check_paired_callback_association(callbacks.evidence(), assembly.evidence['application_callbacks'], names)
    host = assembly.hosts[strategy]
    config = assembly.configuration
    if (getattr(worker, 'store', None) is not host.store or getattr(worker, 'registry', None) is not host.registry
            or getattr(prepared, 'runner', None) is None or prepared.runner.registry is not host.registry
            or prepared.runner.run_id != host.store.run_id
            or prepared.runner.model_version != config.model_version
            or prepared.runner.decision_strategies.get(strategy) is not host.bindings[0]
            or prepared.context.run_id != host.store.run_id or prepared.context.execution_mode != 'llm'
            or prepared.context.contract_ref.id not in host.configuration.action_ids):
        raise TaskConflict('Paired worker/prepared runner must use the exact original model host and run binding')
    plan = prepare_paired_experiment(config, output_root=output_root)
    if plan['plan_sha256'] != assembly.source_check['plan_sha256']:
        raise TaskConflict('Paired run output root changed after source preflight')
    namespace = Path(next(row['output_directory'] for row in plan['run_plans'] if row['strategy'] == strategy))
    with callbacks.guard('read_guard', prepared.context.model_copy(deep=True)):
        recheck_paired_model_hosts(assembly, output_root=output_root)
        identity = worker.register(prepared, request_id=request_id, purpose='action')
        task = worker.store.get(identity)
        saved = worker.get_record(identity)
        intent_path = namespace / 'attempts' / identity.key / 'intent.json'
        if not intent_path.resolve().is_relative_to(namespace):
            raise TaskConflict('Paired execution intent escapes the original arm namespace')
        status = 'existing_result_observed' if saved is not None else 'task_not_ready'
        error_type = None
        option_preparation = None
        if saved is None and task['state'] == 'waiting_input' and not task['conditions']:
            if intent_path.exists():
                _, intent = read_input_json(intent_path)
                required = {'schema_version', 'status', 'assembly_sha256', 'strategy', 'identity',
                    'ready_task_revision', 'record_sha256'}
                if intent.get('schema_version') == 'paired-action-intent.v2':
                    required.add('callbacks')
                    check_saved_paired_callbacks(intent.get('callbacks'),
                        required=('read_guard', 'validate_execute', 'validate_record'))
                    if not _same_record(intent['callbacks'], callbacks.evidence()):
                        raise TaskConflict('Original paired action intent changed its actual callback dependencies')
                if (set(intent) not in (required, required | {'option_preparation'})
                        or intent.get('schema_version') not in {'paired-action-intent.v1', 'paired-action-intent.v2'}
                        or intent.get('status') != 'execution_requested'
                        or type(intent.get('ready_task_revision')) is not int or intent['ready_task_revision'] < 0
                        or 'option_preparation' in intent and not isinstance(intent['option_preparation'], dict)
                        or not _same_record(intent.get('identity'), identity.as_dict())
                        or intent.get('assembly_sha256') != assembly.evidence['record_sha256']
                        or intent.get('strategy') != strategy
                        or intent.get('record_sha256') != task_digest({key: value for key, value in intent.items() if key != 'record_sha256'})):
                    raise TaskConflict('Original paired intent changes its immutable task, assembly or digest')
                status = 'unresolved_intent_no_replay'
            else:
                cache = prepared.reading.evidence()
                methods = prepared.reading.method_evidence()
                context_sha = task_digest(prepared.context.model_dump(mode='json'))
                input_sha = task_digest(prepared.action_input.model_dump(mode='json'))
                basis = next(basis for basis in config.action_basis if basis.action_id == identity.action_id)
                if callbacks.invoke('validate_execute', configuration=config.model_copy(deep=True), comparison_basis=basis.model_copy(deep=True),
                        host=host, worker=worker, prepared=prepared, identity=identity, task=deepcopy(task),
                        source_check=deepcopy(assembly.source_check), isolation_check=deepcopy(assembly.isolation_check)) is not True:
                    raise TaskConflict('Paired execution lacks current original input/source/state/endpoint checks')
                prepared.reading.recheck()
                recheck_paired_model_hosts(assembly, output_root=output_root)
                if (not _same_record(prepared.reading.evidence(), cache) or not _same_record(prepared.reading.method_evidence(), methods)
                        or task_digest(prepared.context.model_dump(mode='json')) != context_sha
                        or task_digest(prepared.action_input.model_dump(mode='json')) != input_sha
                        or not _same_record(worker.store.get(identity), task) or worker.get_record(identity) is not None):
                    raise TaskConflict('Paired execution gate changed its original task, cache, input or method evidence')
                component = host.components[0]
                if task_digest(model_client_request_policy(component.client)) != config.model_configuration_sha256:
                    raise TaskConflict('Paired model transport changed before its explicit action attempt')
                option_preparation = prepare_role_contract_options(model_host=host, prepared=prepared)
                recheck_paired_model_hosts(assembly, output_root=output_root)
                if (not _same_record(prepared.reading.evidence(), cache) or not _same_record(prepared.reading.method_evidence(), methods)
                        or task_digest(prepared.context.model_dump(mode='json')) != context_sha
                        or task_digest(prepared.action_input.model_dump(mode='json')) != input_sha
                        or not _same_record(worker.store.get(identity), task) or worker.get_record(identity) is not None):
                    raise TaskConflict('Paired option preparation changed original task, sources, input or method evidence')
                intent = {'schema_version': 'paired-action-intent.v2', 'status': 'execution_requested',
                    'assembly_sha256': assembly.evidence['record_sha256'], 'strategy': strategy,
                    'identity': identity.as_dict(), 'ready_task_revision': task['revision'], 'callbacks': callbacks.evidence()}
                if option_preparation is not None:
                    intent['option_preparation'] = deepcopy(option_preparation)
                intent['record_sha256'] = task_digest(intent)
                try:
                    write_new(intent_path, intent)
                except FileExistsError:
                    # Another explicit driver claimed this task; do not invoke it.
                    status = 'intent_already_claimed_no_replay'
                else:
                    try:
                        worker.execute(identity, prepared)
                        status = 'worker_returned'
                    except Exception as exc:
                        # Keep original task/result state and sanitized failure type.
                        # No retry, result synthesis, alternate strategy or submit.
                        error_type = type(exc).__name__
                        status = 'worker_error_no_replay'
                    finally:
                        callbacks.check()
        submission = None
        if submit_action is not None:
            current_task = worker.store.get(identity)
            current_result = worker.get_record(identity)
            current_snapshot = worker.snapshots.get(identity)
            submission = {'status': 'task_not_ready', 'task_state': current_task['state']}
            if (current_task['state'] == 'output_formed' and current_result is not None
                    and current_result['result'].get('kind') == 'completed'):
                submission_path = namespace / 'attempts' / identity.key / 'submission-intent.json'
                if not submission_path.resolve().is_relative_to(namespace):
                    raise TaskConflict('Paired submission intent escapes the original arm namespace')
                implementations = _submission_implementations(submit_action, validate_submission)
                submission_intent = {'schema_version': 'paired-submission-intent.v2',
                    'identity': identity.as_dict(), 'assembly_sha256': assembly.evidence['record_sha256'],
                    'result_sha256': current_result['record_sha256'], 'task_revision': current_task['revision'],
                    **implementations}
                submission_intent['record_sha256'] = task_digest(submission_intent)
                if submission_path.exists():
                    _, prior = read_input_json(submission_path)
                    if not _same_record(prior, submission_intent):
                        raise TaskConflict('Original paired submission intent changed; no replay')
                    submission = {'status': 'unresolved_intent_no_replay', 'intent_path': submission_path.as_posix()}
                else:
                    if callbacks.invoke('validate_submission', stage='before', strategy=strategy, identity=identity, host=host,
                            worker=worker, submission=None) is not True:
                        raise TaskConflict('Paired submission lacks actual current route and authorization checks')
                    if (not _same_record(worker.store.get(identity), current_task)
                            or not _same_record(worker.get_record(identity), current_result)
                            or not _same_record(worker.snapshots.get(identity), current_snapshot)
                            or not _same_record(_submission_implementations(submit_action, validate_submission), implementations)):
                        raise TaskConflict('Paired submission gate changed original task, result or input')
                    recheck_paired_model_hosts(assembly, output_root=output_root)
                    try:
                        write_new(submission_path, submission_intent)
                    except FileExistsError:
                        submission = {'status': 'intent_already_claimed_no_replay'}
                    else:
                        try:
                            returned = callbacks.invoke('submit_action', strategy=strategy, identity=identity, host=host, worker=worker)
                        except Exception as exc:
                            submission = {'status': 'submission_error_no_replay', 'error_type': type(exc).__name__}
                        else:
                            if (not isinstance(returned, dict) or not _same_record(returned.get('identity'), identity.as_dict())
                                    or not _same_record(returned, worker.store.get(identity))
                                    or not _same_record(_submission_implementations(submit_action, validate_submission), implementations)
                                    or callbacks.invoke('validate_submission', stage='after', strategy=strategy, identity=identity,
                                        host=host, worker=worker, submission=deepcopy(returned)) is not True):
                                raise TaskConflict('Paired submission lacks its actual original journal state and receipt provenance')
                            if (not _same_record(returned, worker.store.get(identity))
                                    or not _same_record(_submission_implementations(submit_action, validate_submission), implementations)):
                                raise TaskConflict('Paired receipt validation changed original submission state')
                            submission = {'status': 'attempt_observed', 'task': deepcopy(returned)}
                        finally:
                            callbacks.check()
                if (not _same_record(worker.get_record(identity), current_result)
                        or not _same_record(worker.snapshots.get(identity), current_snapshot)):
                    raise TaskConflict('Paired submission changed original decision result or input')
        feedback_records = ()
        callbacks.check()
        if read_feedback is not None:
            original_task = worker.store.get(identity)
            original_result = worker.get_record(identity)
            original_snapshot = worker.snapshots.get(identity)
            feedback_records = callbacks.invoke('read_feedback', strategy=strategy, identity=identity, host=host)
            if (not isinstance(feedback_records, (list, tuple))
                    or any(not isinstance(record, dict) for record in feedback_records)):
                raise TaskConflict('Paired feedback reader must return original structured records')
            feedback_records = deepcopy(feedback_records)
            if (not _same_record(worker.store.get(identity), original_task)
                    or not _same_record(worker.get_record(identity), original_result)
                    or not _same_record(worker.snapshots.get(identity), original_snapshot)):
                raise TaskConflict('Paired feedback reading changed its original task, result or input')
        callbacks.check()
        observation = record_paired_action_result(assembly, output_root=output_root,
            strategy=strategy, worker=worker, identity=identity, validate_current=validate_record,
            feedback_records=feedback_records, read_cost=read_cost, validate_cost=validate_cost)
        callbacks.check()
        outcome = {'schema_version': 'paired-action-driver.v2', 'status': status, 'callbacks': callbacks.evidence(),
            'identity': identity.as_dict(), 'error_type': error_type,
            'intent_path': intent_path.as_posix() if intent_path.exists() else None,
            'observation_path': observation['path'], 'observation_sha256': observation['record']['record_sha256'],
            'feedback_read_status': 'read' if read_feedback is not None else 'not_configured',
            'task_state': worker.store.get(identity)['state'],
            'limitations': 'Original decision and optional explicitly requested submission attempt. Original receipt/task state does not prove a business effect; no automatic replay.'}
        if option_preparation is not None:
            outcome['option_preparation'] = deepcopy(option_preparation)
        if submit_action is not None:
            outcome['submission'] = submission
        outcome['record_sha256'] = task_digest(outcome)
        return {'driver': outcome, 'observation': observation['record']}
