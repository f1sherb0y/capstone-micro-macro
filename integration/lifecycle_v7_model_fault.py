"""Plan or explicitly inject one local fault into an authorized action selection."""
import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
from typing import Callable

from integration.action_model_host import ActionModelHost, ActionOptionSource
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.scenario_v2 import parse_input_json
from integration.scripted_model_fault_client import build_scripted_model_fault_client
from integration.sessions import atomic_json
from src.actions.model_strategy import ActionDecisionOption
from src.actions.runner import ActionRunner, JsonlActionAuditSink
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest


@dataclass(frozen=True)
class ModelFaultSources:
    """Application-owned fixture reader, original runner and independent validators.

    The runner has no model binding. This entry creates the only model host,
    using a local script. The application supplies genuine alternatives and
    validates their original authority, facts and complete task versions.
    """
    runner: ActionRunner
    store: TaskStore
    option_source: ActionOptionSource
    validate_invocation: Callable
    read_guard: Callable
    close: Callable

    def __post_init__(self):
        if (not isinstance(self.runner, ActionRunner) or not isinstance(self.store, TaskStore)
                or self.store.path is None or not isinstance(self.option_source, ActionOptionSource)
                or not all(callable(f) for f in (self.validate_invocation, self.read_guard, self.close))):
            raise ValueError('V7 model fault requires durable original sources and independent validation')


def _prepare(input_path):
    path = Path(input_path).resolve()
    raw = path.read_bytes()
    _, data = parse_input_json(raw)
    if (set(data) != {'schema_version', 'scenario_id', 'origin', 'request', 'identity',
            'client_settings', 'model_configuration', 'options', 'sources'}
            or data['schema_version'] != 'lifecycle-v7-model-fault-input.v1'
            or data['scenario_id'] != 'V7' or data['origin'] != 'synthetic'):
        raise ValueError('V7 model fault requires a complete explicit synthetic invocation')
    request = RoleContractInvocation.model_validate(data['request'])
    identity = TaskIdentity(**data['identity'])
    context = request.context
    if (request.execution_path != 'single_agent' or context.execution_mode != 'offline_fixture'
            or identity.run_id != context.run_id or identity.request_id != context.operation_id
            or identity.action_id != context.contract_ref.id or identity.purpose != 'action'
            or identity.context_sha256 != task_digest(context.model_dump(mode='json'))):
        raise ValueError('V7 model fault changes its original fixture task or selection path')
    settings, config = data['client_settings'], data['model_configuration']
    if (not isinstance(settings, dict) or settings.get('origin') != 'synthetic'
            or settings.get('fault') not in {'timeout', 'invalid_json'}
            or not isinstance(config, dict) or set(config) != {'host_id', 'budget_id', 'max_calls',
                'action_ids', 'max_options', 'max_prompt_chars', 'max_response_chars'}
            or type(config['max_calls']) is not int or config['max_calls'] != 1
            or config['action_ids'] != [identity.action_id]
            or type(config['max_options']) is not int or config['max_options'] < 2
            or identity.versions['model'] != 'synthetic-local-model-fault.v1'):
        raise ValueError('V7 local fault requires a single-call budget and explicit synthetic model version')
    options = data['options']
    if (not isinstance(options, list) or not 2 <= len(options) <= config['max_options']
            or any(not isinstance(o, dict) or set(o) != {'option_id', 'action_input'}
                or not isinstance(o['option_id'], str) or not o['option_id'].strip()
                or not isinstance(o['action_input'], dict) for o in options)
            or len({o['option_id'] for o in options}) != len(options)
            or len({task_digest(o['action_input']) for o in options}) != len(options)):
        raise ValueError('V7 fault needs distinct complete alternatives, never duplicated dummy options')
    source = data['sources']
    if (not isinstance(source, dict) or set(source) != {'factory', 'settings', 'journal_path'}
            or not isinstance(source['factory'], str) or source['factory'].count(':') != 1
            or not all(source['factory'].split(':')) or not isinstance(source['settings'], dict)
            or not isinstance(source['journal_path'], str) or not source['journal_path'].strip()):
        raise ValueError('V7 fault requires explicit original source factory and journal')
    return path, hashlib.sha256(raw).hexdigest(), data, request, identity


def run_v7_model_fault(*, input_path, output_directory, execute=False):
    path, digest, data, request, identity = _prepare(input_path)
    plan = {'schema_version': 'lifecycle-v7-model-fault-plan.v1', 'scenario_id': 'V7',
        'origin': 'synthetic', 'input_path': str(path), 'input_sha256': digest,
        'identity': identity.as_dict(), 'fault': data['client_settings']['fault'],
        'mode': 'plan_only', 'network_requests': 0,
        'limitations': ['Local fault injection does not prove real model/provider behavior.']}
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    atomic_json(directory / 'attempt.json', {**plan, 'status': 'started', 'automatic_retry': False})
    sources = None
    task = None
    original_sink = None
    try:
        module, name = data['sources']['factory'].split(':')
        factory = getattr(importlib.import_module(module), name)
        descriptor = module_factory_descriptor(factory, data['sources']['factory'])
        sources = factory(request=deepcopy(data), output_directory=directory)
        if not isinstance(sources, ModelFaultSources):
            raise ValueError('V7 fault source factory must return ModelFaultSources')
        runner, store = sources.runner, sources.store
        original_sink = runner.audit_sink
        if (runner.run_id != identity.run_id or store.run_id != identity.run_id
                or Path(store.path).resolve() != Path(data['sources']['journal_path']).resolve()
                or runner.organizations is None or runner.organizations.run_id != identity.run_id
                or runner.references is None or runner.references.run_id != identity.run_id
                or runner.references.source_mode != 'fixture' or runner.decision_strategies
                or runner.audit_records or runner.model_version is not None):
            raise ValueError('V7 fault requires an unused same-run fixture runner without model bindings')
        registration = runner.registry.get(identity.action_id)
        action_input = registration.contract.validate_input(request.action_input)
        if (registration.strategy != 'single_agent' or not registration.implemented or registration.skill is None
                or identity.input_sha256 != task_digest(action_input.model_dump(mode='json'))):
            raise ValueError('V7 fault lacks original Skill/processor or changes the validated input')
        callbacks = {key: module_factory_descriptor(getattr(sources, key), key)
            for key in ('validate_invocation', 'read_guard', 'close')}
        option_callbacks = {key: module_factory_descriptor(getattr(sources.option_source, key), key)
            for key in ('prepare_options', 'validate_options')}
        with sources.read_guard():
            if sources.validate_invocation(deepcopy(data), identity) is not True:
                raise ValueError('Original independent invocation/authority/version validation rejected V7 input')
            option_source = sources.option_source
            expected = {o['option_id']: registration.contract.validate_input(o['action_input']).model_dump(mode='json')
                for o in data['options']}
            if len({task_digest(v) for v in expected.values()}) != len(expected):
                raise ValueError('V7 normalized action alternatives are duplicates')

            def prepare_options(**kwargs):
                options = option_source.prepare_options(**kwargs)
                if (not isinstance(options, (list, tuple)) or any(not isinstance(o, ActionDecisionOption) for o in options)
                        or len(options) != len(expected)
                        or {o.option_id: registration.contract.validate_input(o.action_input).model_dump(mode='json')
                            for o in options} != expected):
                    raise TaskConflict('V7 original option producer differs from explicitly selected alternatives')
                return options

            client = build_scripted_model_fault_client(data['client_settings'])
            host = ActionModelHost(store=store, registry=runner.registry, client=client,
                model_version=identity.versions['model'], configuration=data['model_configuration'],
                option_sources={identity.action_id: ActionOptionSource(option_source.version,
                    prepare_options, option_source.validate_options)})
            if host.budget.usage()['charged_or_reserved_calls'] != 0:
                raise TaskConflict('V7 fault requires a fresh persistent call budget')
            runner.model_version = identity.versions['model']
            runner.decision_strategies = {b.strategy: b for b in host.bindings}
            sink = JsonlActionAuditSink(directory / 'actions.jsonl', run_id=identity.run_id)

            def audit_record(record):
                sink(record)
                if original_sink is not None:
                    original_sink(record)

            runner.audit_sink = audit_record
            with store._transaction():
                if store._read(identity) is not None:
                    raise TaskConflict('V7 fault task already exists; interrupted attempts are never replayed')
                task = store._ensure_in_transaction(identity)
            task = store.start(identity, task['revision'])
            result = runner.run_action(request.context, action_input, execution_path='single_agent')
            audit = [r.as_dict() for r in runner.audit_records]
            evidence = {'result': result.model_dump(mode='json'), 'audit': audit,
                'client': client.evidence(), 'model_host': host.evidence(), 'factory': descriptor}
            atomic_json(directory / 'result.json', evidence)
            expected_type = 'TimeoutError' if data['client_settings']['fault'] == 'timeout' else 'JSONDecodeError'
            binding = audit[0].get('decision') if len(audit) == 1 else None
            decision = binding.get('execution') if isinstance(binding, dict) else None
            if (result.kind != 'technical_error'
                    or evidence['result'].get('error', {}).get('code') != 'action_model_selection_failed'
                    or not isinstance(decision, dict) or decision.get('status') != 'model_selection_failed'
                    or decision.get('error_type') != expected_type or decision.get('option_count') != len(expected)
                    or decision.get('model_calls') != 1 or client.evidence()['script_calls'] != 1
                    or host.budget.usage()['charged_or_reserved_calls'] != 1):
                raise TaskConflict('V7 did not exercise exactly one original model selection failure')
            if sources.validate_invocation(deepcopy(data), identity) is not True:
                raise TaskConflict('V7 original source/authority/version validation changed during selection')
            task = store.fail(identity, task['revision'], error_code='action_model_selection_failed')
            atomic_json(directory / 'task.json', task)
            if any(task[k] is not None for k in ('output', 'submission', 'receipt')):
                raise TaskConflict('V7 technical fault formed business output or transport effects')
            if (module_factory_descriptor(factory, data['sources']['factory']) != descriptor
                    or sources.option_source is not option_source
                    or any(module_factory_descriptor(getattr(sources, k), k) != v for k, v in callbacks.items())
                    or any(module_factory_descriptor(getattr(option_source, k), k) != v
                        for k, v in option_callbacks.items())):
                raise TaskConflict('V7 source factory or original validation changed')
        summary = {**plan, 'mode': 'local_fault_checked', 'task_state': task['state'],
            'script_calls': 1, 'real_model_calls': 0}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**plan, 'status': 'finished', 'automatic_retry': False})
        return summary
    except Exception as exc:
        if isinstance(sources, ModelFaultSources) and task is not None and task['state'] == 'processing':
            task = sources.store.fail(identity, task['revision'], error_code='v7_model_fault_verification_failed')
            atomic_json(directory / 'task.json', task)
        atomic_json(directory / 'attempt.json', {**plan, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise
    finally:
        if isinstance(sources, ModelFaultSources):
            sources.runner.audit_sink = original_sink
            sources.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    run_v7_model_fault(input_path=args.input, output_directory=args.output, execute=args.execute)


if __name__ == '__main__':
    main()
