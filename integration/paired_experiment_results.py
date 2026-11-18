"""Record original paired results and observed usage without executing actions."""
from collections import Counter
from copy import deepcopy
from pathlib import Path

from integration.action_catalog import write_new
from integration.module_host import module_factory_descriptor
from integration.paired_experiment_callbacks import (
    PairedCallbackSet, check_saved_paired_callbacks, check_paired_callback_association,
)
from integration.paired_experiment_costs import checked_paired_cost, summarize_paired_costs
from integration.paired_experiment_hosts import PairedModelHosts, recheck_paired_model_hosts
from integration.paired_experiments import prepare_paired_experiment
from integration.paired_experiment_sources import _run_neutral
from integration.scenario_v2 import read_input_json
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def _observed_usage(audit):
    decision = (audit or {}).get('decision') or {}
    execution = decision.get('execution') or {}
    attempts = execution.get('model_calls')
    if type(attempts) is not int or attempts < 0:
        return {'adapter_attempts': None, 'returned_responses': None,
            'input_tokens': None, 'output_tokens': None, 'total_tokens': None,
            'monetary_cost': None}
    if 'calls' in execution:
        traces = execution['calls']
        if not isinstance(traces, list) or len(traces) != attempts or any(not isinstance(row, dict) for row in traces):
            raise TaskConflict('Paired discussion audit has inconsistent model attempt traces')
    else:
        if attempts > 1:
            raise TaskConflict('Paired single-agent audit exceeds its one-call protocol')
        traces = [execution] if attempts else []
    usage = {'adapter_attempts': attempts,
        'returned_responses': len(traces) if all(isinstance(row.get('response_sha256'), str) for row in traces) else None,
        'monetary_cost': None}
    for key in ('input_tokens', 'output_tokens', 'total_tokens'):
        values = [row.get('usage_metadata', {}).get(key) for row in traces]
        usage[key] = sum(values) if all(type(value) is int and value >= 0 for value in values) else None
    return usage


def record_paired_action_result(assembly, *, output_root: Path, strategy, worker, identity,
        validate_current, feedback_records=(), read_cost=None, validate_cost=None):
    """Read the original worker/task once; never run, submit or recover a result.

    The caller holds its actual result/source guard. validate_current verifies
    current own read authority, original snapshot/attempt/model correlation and
    actual feedback provenance. Missing result or usage remains explicitly absent.
    Artifacts are immutable content-addressed records in the original arm path.
    """
    if ((read_cost is None) != (validate_cost is None)
            or read_cost is not None and not all(callable(gate) for gate in (read_cost, validate_cost))):
        raise TaskConflict('Paired cost recording requires its explicit reader and actual source gate')
    if (not isinstance(assembly, PairedModelHosts) or strategy not in assembly.hosts
            or not isinstance(identity, TaskIdentity) or not callable(validate_current)):
        raise TaskConflict('Paired result requires its original assembly, identity and actual read gate')
    callbacks = PairedCallbackSet(validate_current=validate_current, read_cost=read_cost, validate_cost=validate_cost)
    if assembly.evidence.get('application_callbacks') is not None:
        check_paired_callback_association(callbacks.evidence(), assembly.evidence['application_callbacks'],
            {'validate_current': 'validate_record', 'read_cost': 'read_cost', 'validate_cost': 'validate_cost'})
    identity = TaskIdentity(**identity.as_dict())
    recheck_paired_model_hosts(assembly, output_root=output_root)
    host = assembly.hosts[strategy]
    arm = next(arm for arm in assembly.configuration.arms if arm.strategy == strategy)
    if (identity.run_id != arm.run_id or identity.action_id not in arm.model_host.action_ids
            or identity.purpose != 'action' or getattr(worker, 'store', None) is not host.store
            or getattr(worker, 'registry', None) is not host.registry
            or getattr(worker, 'ACTION_ID', None) != identity.action_id
            or not callable(getattr(worker, 'get_record', None))):
        raise TaskConflict('Paired result changes its original worker, run, task or model host')
    task = worker.store.get(identity)
    saved = worker.get_record(identity)
    snapshot = worker.snapshots.get(identity)
    original_components = (worker.store, worker.registry, worker.snapshots)
    identity_sha256 = task_digest(identity.as_dict())

    def recheck_original():
        callbacks.check()
        if (any(current is not original for current, original in zip(
                (worker.store, worker.registry, worker.snapshots), original_components))
                or task_digest(identity.as_dict()) != identity_sha256
                or task_digest(worker.store.get(identity)) != task_digest(task)
                or task_digest(worker.get_record(identity)) != task_digest(saved)
                or task_digest(worker.snapshots.get(identity)) != task_digest(snapshot)):
            raise TaskConflict('Original paired task, result, input or worker components changed during recording')
        recheck_paired_model_hosts(assembly, output_root=output_root)
    basis = next(basis for basis in assembly.configuration.action_basis if basis.action_id == identity.action_id)
    if (task_digest(_run_neutral(snapshot['action_input'], identity.run_id)) != basis.input_sha256
            or snapshot['context']['run_id'] != identity.run_id
            or task_digest(snapshot['context']) != identity.context_sha256):
        raise TaskConflict('Paired result snapshot changes the original frozen input or task context')
    audit = None
    result = None
    if saved is not None:
        audit, result = saved['audit'], saved['result']
        binding = host.bindings[0]
        decision = audit.get('decision')
        if (task_digest(saved.get('identity')) != task_digest(identity.as_dict())
                or saved.get('record_sha256') != task_digest({key: value for key, value in saved.items() if key != 'record_sha256'})
                or audit.get('run_id') != identity.run_id or audit.get('action_id') != identity.action_id
                or audit.get('operation_id') != snapshot['context']['operation_id']
                or audit.get('input_sha256') != identity.input_sha256
                or audit.get('result_sha256') != task_digest(result)
                or audit.get('execution_path') != strategy or audit.get('strategy') != strategy
                or audit.get('model_version') != assembly.configuration.model_version
                or not isinstance(decision, dict)
                or any(task_digest(decision.get(key)) != task_digest(value)
                    for key, value in binding.evidence(status='started').items() if key != 'status')):
            raise TaskConflict('Paired original result/audit lost its task, model or exact strategy binding')
    feedback = deepcopy(list(feedback_records))
    if any(not isinstance(row, dict) for row in feedback):
        raise TaskConflict('Paired feedback must retain original structured records')
    if callbacks.invoke('validate_current', identity=identity, host=host, task=deepcopy(task), saved=deepcopy(saved),
            snapshot=deepcopy(snapshot), comparison_basis=basis.model_copy(deep=True),
            feedback_records=deepcopy(feedback)) is not True:
        raise TaskConflict('Paired result requires actual current recipient/attempt/model/feedback checks')
    recheck_original()
    usage = _observed_usage(audit)
    cost = None
    if read_cost is not None:
        supplied = callbacks.invoke('read_cost', strategy=strategy, identity=identity, host=host)
        recheck_original()
        if supplied is not None:
            cost = checked_paired_cost(supplied, identity=identity, audit=audit,
                model_version=assembly.configuration.model_version, adapter_attempts=usage['adapter_attempts'])
            if callbacks.invoke('validate_cost', identity=identity, host=host, task=deepcopy(task), saved=deepcopy(saved),
                    snapshot=deepcopy(snapshot), cost_evidence=deepcopy(cost)) is not True:
                raise TaskConflict('Paired cost lacks actual original billing/estimate source and allocation validation')
            recheck_original()
    recheck_original()
    record = {'schema_version': 'paired-action-observation.v2', 'callbacks': callbacks.evidence(),
        'status': 'result_observed' if saved is not None else 'result_unavailable',
        'assembly_sha256': assembly.evidence['record_sha256'], 'strategy': strategy,
        'comparison_basis_sha256': task_digest(basis.model_dump(mode='json')),
        'identity': identity.as_dict(), 'task_revision': task['revision'], 'task_state': task['state'],
        'snapshot': deepcopy(snapshot), 'original_result_record_sha256': saved['record_sha256'] if saved else None,
        'result': deepcopy(result), 'audit': deepcopy(audit), 'usage': usage,
        'budget_usage': host.budget.usage(), 'feedback_records': feedback,
        'limitations': 'Observed original output and adapter attempts only; missing usage/cost remains unknown. A completed result or accepted receipt does not prove a business effect.'}
    if read_cost is not None:
        record.update(cost_evidence=cost, cost_read_status='observed' if cost is not None else 'unavailable',
            cost_source={'reader': module_factory_descriptor(read_cost, 'paired.cost_reader'),
                'validator': module_factory_descriptor(validate_cost, 'paired.cost_validator')})
    record['record_sha256'] = task_digest(record)
    plan = prepare_paired_experiment(assembly.configuration, output_root=output_root)
    if plan['plan_sha256'] != assembly.source_check['plan_sha256']:
        raise TaskConflict('Paired observation output root changes the original checked plan')
    namespace = next(row['output_directory'] for row in plan['run_plans'] if row['strategy'] == strategy)
    path = Path(namespace) / 'observations' / identity.key / (record['record_sha256'] + '.json')
    if not path.resolve().is_relative_to(Path(namespace)):
        raise TaskConflict('Paired observation path escapes its original arm namespace')
    if path.exists():
        _, prior = read_input_json(path)
        if task_digest(prior) != task_digest(record):
            raise TaskConflict('Existing paired observation differs from its immutable record')
    else:
        write_new(path, record)
    return {'path': path.as_posix(), 'record': record}


def summarize_paired_results(assembly, observations):
    """Summarize latest original attempts, retaining incomplete and unpaired work.

    Budget snapshots are cumulative and are never summed as per-action cost.
    No business success, statistical advantage or unobserved token charge is
    inferred. Further attempt revisions must come from the original task store.
    """
    if not isinstance(assembly, PairedModelHosts):
        raise TaskConflict('Paired summary requires the original checked assembly')
    selected = {}
    feedback_history = {}
    cost_history = {}
    allocated = {}
    for record in observations:
        if (not isinstance(record, dict) or record.get('schema_version') not in {'paired-action-observation.v1', 'paired-action-observation.v2'}
                or record.get('assembly_sha256') != assembly.evidence['record_sha256']
                or record.get('record_sha256') != task_digest({key: value for key, value in record.items() if key != 'record_sha256'})):
            raise TaskConflict('Paired summary observation lacks original assembly or record digest')
        if record['schema_version'] == 'paired-action-observation.v2':
            check_saved_paired_callbacks(record.get('callbacks'), required=('validate_current',))
            declared = record['callbacks']['callbacks']
            if (set(declared) != {'validate_current', 'read_cost', 'validate_cost'}
                    or (declared['read_cost'] is None) != (declared['validate_cost'] is None)
                    or ('cost_evidence' in record) != (declared['read_cost'] is not None)):
                raise TaskConflict('Paired observation changed its original cost callback presence')
            if assembly.evidence.get('application_callbacks') is not None:
                check_paired_callback_association(record['callbacks'], assembly.evidence['application_callbacks'],
                    {'validate_current': 'validate_record', 'read_cost': 'read_cost', 'validate_cost': 'validate_cost'})
        identity = TaskIdentity(**record['identity'])
        arm = next((arm for arm in assembly.configuration.arms if arm.strategy == record['strategy']), None)
        basis = next((basis for basis in assembly.configuration.action_basis if basis.action_id == identity.action_id), None)
        if (arm is None or basis is None or identity.run_id != arm.run_id
                or record['comparison_basis_sha256'] != task_digest(basis.model_dump(mode='json'))
                or type(record['task_revision']) is not int or record['task_revision'] < 0
                or task_digest(record['usage']) != task_digest(_observed_usage(record['audit']))):
            raise TaskConflict('Paired observation changes original arm, action basis, revision or observed usage')
        if record.get('cost_evidence') is not None:
            if task_digest(checked_paired_cost(record['cost_evidence'], identity=identity, audit=record['audit'],
                    model_version=assembly.configuration.model_version,
                    adapter_attempts=record['usage']['adapter_attempts'])) != task_digest(record['cost_evidence']):
                raise TaskConflict('Paired observation changes its original normalized cost evidence')
            # Billing can arrive before a later receipt-only observation. Keep
            # its original invocation and evidence links independently of the
            # latest task revision, just as we retain feedback history below.
            cost = record['cost_evidence']
            invocation = (identity.key, cost['audit_sha256'])
            allocation = (cost['source_sha256'], cost['record_id'])
            if allocation in allocated and allocated[allocation] != invocation:
                raise TaskConflict('Paired cost source allocation is reused by another invocation')
            allocated[allocation] = invocation
            cost_key = (*invocation, cost['kind'])
            prior_cost = cost_history.get(cost_key)
            if prior_cost is not None and task_digest(prior_cost['cost_evidence']) != task_digest(cost):
                raise TaskConflict('Paired observations conflict for the same original cost allocation')
            history = cost_history.setdefault(cost_key, {
                'strategy': record['strategy'], 'action_id': identity.action_id,
                'task_key': identity.key, 'cost_evidence': deepcopy(cost),
                'observation_sha256s': []})
            if record['record_sha256'] not in history['observation_sha256s']:
                history['observation_sha256s'].append(record['record_sha256'])
        feedback_records = record.get('feedback_records', [])
        if (not isinstance(feedback_records, list)
                or any(not isinstance(feedback, dict) for feedback in feedback_records)):
            raise TaskConflict('Paired observation lost its original structured feedback records')
        # Result/cost selection must not erase independently observed feedback.
        # Keep each original record and all of its immutable observation links;
        # this history does not grant current authority or create a new input.
        for feedback in feedback_records:
            digest = task_digest(feedback)
            association = (record['strategy'], identity.key, digest)
            history = feedback_history.setdefault(association, {
                'action_id': identity.action_id, 'task_key': identity.key,
                'feedback_sha256': digest, 'record': deepcopy(feedback),
                'observation_sha256s': []})
            if record['record_sha256'] not in history['observation_sha256s']:
                history['observation_sha256s'].append(record['record_sha256'])
        key = identity.key
        prior = selected.get(key)
        prefer_cost = False
        if prior is not None and prior['task_revision'] == record['task_revision']:
            if (any(task_digest(prior[name]) != task_digest(record[name]) for name in ('identity', 'snapshot'))
                    or prior['original_result_record_sha256'] is not None and record['original_result_record_sha256'] is not None
                    and any(task_digest(prior[name]) != task_digest(record[name]) for name in ('original_result_record_sha256', 'result', 'audit'))):
                raise TaskConflict('Paired observations conflict for the same original task revision')
            old_cost, new_cost = prior.get('cost_evidence'), record.get('cost_evidence')
            if prior['original_result_record_sha256'] == record['original_result_record_sha256']:
                if (old_cost is not None and new_cost is not None and task_digest(old_cost) != task_digest(new_cost)
                        and old_cost['kind'] == new_cost['kind']):
                    raise TaskConflict('Paired observations conflict for the same original cost allocation')
                prefer_cost = new_cost is not None and (old_cost is None
                    or old_cost['kind'] == 'estimated' and new_cost['kind'] == 'billed')
        if (prior is None or record['task_revision'] > prior['task_revision']
                or record['task_revision'] == prior['task_revision']
                and (prior['original_result_record_sha256'] is None and record['original_result_record_sha256'] is not None
                    or prefer_cost)):
            selected[key] = deepcopy(record)
    arms = {}
    action_counts = {}
    for arm in assembly.configuration.arms:
        rows = [row for row in selected.values() if row['strategy'] == arm.strategy]
        counts = Counter(row['identity']['action_id'] for row in rows)
        action_counts[arm.strategy] = counts
        usage = {}
        for field in ('adapter_attempts', 'returned_responses', 'input_tokens', 'output_tokens', 'total_tokens'):
            values = [row['usage'][field] for row in rows]
            usage[field] = sum(values) if rows and all(value is not None for value in values) else None
        arms[arm.strategy] = {'observed_task_count': len(rows),
            'result_kind_counts': dict(Counter(row['result']['kind'] if row['result'] else 'unavailable' for row in rows)),
            'missing_action_ids': [basis.action_id for basis in assembly.configuration.action_basis if not counts[basis.action_id]],
            'actions_with_multiple_tasks': [action_id for action_id, count in counts.items() if count > 1],
            'usage': usage, 'monetary_cost': None,
            'records': [row['record_sha256'] for row in rows]}
        costs = [value for value in cost_history.values() if value['strategy'] == arm.strategy]
        if costs or any('cost_evidence' in row for row in rows):
            cost_rows = []
            for row in rows:
                audit_sha256 = task_digest(row['audit']) if row['audit'] is not None else None
                # A newer audit represents a different invocation. Older cost
                # evidence stays in history but cannot price that invocation.
                invocation = (TaskIdentity(**row['identity']).key, audit_sha256)
                known = (cost_history.get((*invocation, 'billed'))
                    or cost_history.get((*invocation, 'estimated')))
                cost_rows.append({'cost_evidence': known['cost_evidence'] if known else None})
            arms[arm.strategy]['costs'] = summarize_paired_costs(cost_rows)
        if costs:
            costs.sort(key=lambda value: (value['task_key'],
                value['cost_evidence']['audit_sha256'] or '', value['cost_evidence']['kind']))
            for value in costs:
                value['observation_sha256s'].sort()
            arms[arm.strategy]['cost_history'] = costs
        history = [value for (strategy, _, _), value in sorted(feedback_history.items())
            if strategy == arm.strategy]
        if history:
            for value in history:
                value['observation_sha256s'].sort()
            arms[arm.strategy]['feedback_history'] = history
    strategies = [arm.strategy for arm in assembly.configuration.arms]
    paired = [basis.action_id for basis in assembly.configuration.action_basis
        if all(action_counts[strategy][basis.action_id] == 1
            and any(row['strategy'] == strategy and row['identity']['action_id'] == basis.action_id
                and row['original_result_record_sha256'] is not None for row in selected.values()) for strategy in strategies)]
    report = {'schema_version': 'paired-experiment-results.v1', 'status': 'observations_only',
        'assembly_sha256': assembly.evidence['record_sha256'], 'paired_action_ids': paired,
        'unpaired_action_ids': [basis.action_id for basis in assembly.configuration.action_basis if basis.action_id not in paired],
        'arms': arms, 'limitations': 'Original outputs, attempts and explicitly source-validated cost allocations only. Missing costs stay unknown; estimates, billed costs and currencies stay separate. No execution closure or mechanism advantage is claimed.'}
    report['report_sha256'] = task_digest(report)
    return report
