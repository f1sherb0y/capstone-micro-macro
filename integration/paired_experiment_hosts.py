"""Explicitly assemble original model hosts for a checked paired configuration."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from integration.action_model_host import ActionModelHost, ActionOptionSource
from integration.module_host import module_factory_descriptor
from integration.paired_experiment_callbacks import check_saved_paired_callbacks
from integration.paired_experiment_isolation import PairedRuntimeIsolation, bind_paired_runtime_isolation
from integration.paired_experiment_sources import (
    PairedActionSources, paired_action_basis, paired_invocation_digest, validate_paired_experiment_sources,
)
from integration.paired_experiments import PairedExperimentConfiguration, prepare_paired_experiment
from src.actions.implementation import callable_implementation
from src.actions.model_strategy import ActionDecisionOption, model_client_request_policy
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PairedModelHosts:
    configuration: PairedExperimentConfiguration
    hosts: object
    source_check: dict
    isolation_check: dict
    evidence: dict
    state_binding: PairedRuntimeIsolation | None = None


def recheck_paired_model_hosts(assembly, *, output_root):
    """Recheck sealed initial evidence and live hosts; do not reset arm state.

    Current facts and routing still require the application's execution gate.
    Initial cognition/cache hashes cannot be treated as current after an action.
    """
    if not isinstance(assembly, PairedModelHosts):
        raise TaskConflict('Paired runtime requires its original assembled model hosts')
    for record in (assembly.evidence, assembly.source_check, assembly.isolation_check):
        if (not isinstance(record, dict) or record.get('record_sha256')
                != task_digest({key: value for key, value in record.items() if key != 'record_sha256'})):
            raise TaskConflict('Paired assembly or preflight evidence changed its original digest')
    config = PairedExperimentConfiguration.model_validate(assembly.configuration.model_dump(mode='python'))
    plan = prepare_paired_experiment(config, output_root=output_root)
    strategies = {arm.strategy for arm in config.arms}
    if (assembly.evidence.get('configuration_sha256') != task_digest(config.model_dump(mode='json'))
            or assembly.evidence.get('schema_version') != 'paired-model-hosts.v2'
            or assembly.isolation_check.get('schema_version') != 'paired-experiment-isolation-check.v2'
            or not isinstance(assembly.state_binding, PairedRuntimeIsolation)
            or assembly.evidence.get('source_check_sha256') != assembly.source_check['record_sha256']
            or assembly.evidence.get('isolation_check_sha256') != assembly.isolation_check['record_sha256']
            or assembly.isolation_check.get('source_check_sha256') != assembly.source_check['record_sha256']
            or any(record.get('plan_sha256') != plan['plan_sha256']
                for record in (assembly.source_check, assembly.isolation_check))
            or set(assembly.hosts) != strategies
            or set(assembly.evidence.get('hosts', {})) != strategies):
        raise TaskConflict('Paired assembly changed original configuration, preflight links or arm set')
    if (assembly.state_binding.record_sha256 != assembly.isolation_check['record_sha256']
            or task_digest(assembly.state_binding.configuration.model_dump(mode='json'))
                != task_digest(config.model_dump(mode='json'))):
        raise TaskConflict('Paired host lost its original live state-adapter binding')
    assembly.state_binding.recheck(output_root=output_root)
    if (not isinstance(assembly.source_check.get('arms'), list)
            or len(assembly.source_check['arms']) != len(config.arms)):
        raise TaskConflict('Paired host lost its original checked journal set')
    for arm, checked in zip(config.arms, assembly.source_check['arms']):
        host = assembly.hosts[arm.strategy]
        if (not isinstance(host, ActionModelHost) or host.store.run_id != arm.run_id
                or not isinstance(checked, dict) or checked.get('run_id') != arm.run_id
                or checked.get('strategy') != arm.strategy or host.store.path is None
                or host.store.path.resolve().as_posix() != checked.get('task_store_path')
                or host.model_version != config.model_version
                or task_digest(host.configuration.model_dump(mode='json')) != task_digest(arm.model_host.model_dump(mode='json'))
                or task_digest(host.metadata) != task_digest(assembly.evidence['hosts'][arm.strategy])
                or len(host.bindings) != 1 or host.bindings[0].strategy != arm.strategy
                or host.bindings[0].action_ids != frozenset(arm.model_host.action_ids)):
            raise TaskConflict('Paired arm substituted its original host, run or strategy binding')
        host._check()


def _original_option_declaration(original, expected):
    callbacks = {'prepare': original.prepare_options, 'validate': original.validate_options}
    if original.prepare_invocation is not None:
        callbacks['prepare_invocation'] = original.prepare_invocation
    return {'schema_version': 'paired-original-options.v2', 'original_version': original.version,
        'basis': expected.model_dump(mode='json'),
        'callbacks': {name: {'descriptor': module_factory_descriptor(callback, 'paired.original_' + name),
            'implementation': callable_implementation(callback)} for name, callback in callbacks.items()}}


def _checked_option_source(*, registry, expected, sources, original):
    """Keep actual option callbacks and enforce the frozen paired input at use."""
    initial = PairedActionSources(context=sources.context.model_copy(deep=True),
        action_input=deepcopy(sources.action_input), reading=sources.reading,
        options=deepcopy(sources.options), binding_version=sources.binding_version,
        supported_choices=sources.supported_choices)
    expected = expected.model_copy(deep=True)

    declaration = _original_option_declaration(original, expected)

    def check_original():
        # The host fingerprints these wrappers; it cannot inspect the original
        # callback objects captured in their closures. Recheck them explicitly.
        if task_digest(_original_option_declaration(original, expected)) != task_digest(declaration):
            raise TaskConflict('Paired original option implementation or version changed')

    def check_invocation(kwargs):
        check_original()
        context = kwargs['context']
        if (kwargs['registration'] is not registry.get(expected.action_id)
                or task_digest(context.model_dump(mode='json')) != task_digest(initial.context.model_dump(mode='json'))
                or task_digest(registry.get(expected.action_id).contract.validate_input(
                    kwargs['action_input']).model_dump(mode='json')) != task_digest(
                    registry.get(expected.action_id).contract.validate_input(initial.action_input).model_dump(mode='json'))):
            raise TaskConflict('Paired model host received another original invocation')

    def prepare_options(**kwargs):
        check_invocation(kwargs)
        context, reading = kwargs['context'], kwargs['reading']
        before = reading.method_evidence()
        try:
            supplied = original.prepare_options(**kwargs)
        finally:
            check_original()
        check_invocation(kwargs)
        if (not isinstance(supplied, (list, tuple))
                or any(not isinstance(option, ActionDecisionOption) for option in supplied)):
            raise TaskConflict('Paired option source must return original typed options')
        current = PairedActionSources(context=context, action_input=kwargs['action_input'], reading=reading,
            options=tuple(supplied), binding_version=initial.binding_version,
            supported_choices=initial.supported_choices)
        if paired_action_basis(registry=registry, action_id=expected.action_id, sources=current) != expected:
            raise TaskConflict('Actual model options or authorized sources changed after paired preflight')
        if task_digest(reading.method_evidence()) != task_digest(before):
            raise TaskConflict('Paired option production cannot replay a registered method')
        return supplied

    def validate_options(**kwargs):
        check_invocation(kwargs)
        reading = kwargs['reading']
        before = reading.method_evidence()
        try:
            valid = original.validate_options(**kwargs)
        finally:
            check_original()
        check_invocation(kwargs)
        if valid is not True:
            raise TaskConflict('Original paired option legality gate did not succeed')
        current = PairedActionSources(context=kwargs['context'], action_input=kwargs['action_input'], reading=reading,
            options=tuple(kwargs['options']), binding_version=initial.binding_version,
            supported_choices=initial.supported_choices)
        if (paired_action_basis(registry=registry, action_id=expected.action_id, sources=current) != expected
                or task_digest(reading.method_evidence()) != task_digest(before)):
            raise TaskConflict('Paired option validation changed its frozen sources or executed a method')
        return True

    def prepare_invocation(**kwargs):
        check_invocation(kwargs)
        reading = kwargs['reading']
        before = reading.method_evidence()
        try:
            evidence = original.prepare_invocation(**kwargs)
        finally:
            check_original()
        check_invocation(kwargs)
        if not isinstance(evidence, dict):
            raise TaskConflict('Paired option preparation requires actual original snapshot evidence')
        # Preparation can persist local input snapshots, but cannot change the
        # frozen experiment alternatives, source relation or arm permissions.
        options = prepare_options(**kwargs)
        validate_options(options=options, **kwargs)
        reading.recheck()
        if task_digest(reading.method_evidence()) != task_digest(before):
            raise TaskConflict('Paired option preparation cannot execute professional methods')
        return dict(schema_version='paired-action-option-preparation.v1',
            original=deepcopy(evidence), basis_sha256=task_digest(expected.model_dump(mode='json')))

    return ActionOptionSource(version=task_digest(declaration), prepare_options=prepare_options,
        validate_options=validate_options,
        prepare_invocation=prepare_invocation if original.prepare_invocation is not None else None)


def assemble_paired_model_hosts(configuration, *, output_root: Path, arms, states, clients, option_sources,
        validate_sources, validate_isolation, validate_components, application_callbacks=None):
    """Construct two explicit hosts after actual gates, never execute strategies.

    The caller supplies existing clients and keeps actual source/state guards.
    validate_components(configuration, arms, states, clients, option_sources)
    verifies these exact components' routing and the actual model/seed/policy.
    Clients are neither auto-created nor loaded from credentials. Journals and
    their persistent budget metadata stay caller-owned on partial assembly.
    """
    config = PairedExperimentConfiguration.model_validate(configuration)
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    strategies = {arm.strategy for arm in config.arms}
    if application_callbacks is not None:
        check_saved_paired_callbacks(application_callbacks,
            required=('assembly_guard', 'validate_sources', 'validate_isolation', 'validate_components',
                'prepare_action', 'read_guard', 'validate_execute', 'validate_record', 'close'))
        application_callbacks = deepcopy(application_callbacks)
    if (not isinstance(clients, dict) or set(clients) != strategies
            or not isinstance(option_sources, dict) or set(option_sources) != strategies
            or not callable(validate_components)):
        raise TaskConflict('Paired assembly requires exact explicit clients, option sources and component routing gate')
    policies = {}
    original_clients = dict(clients)
    original_options = {}
    option_declarations = {}
    component_gate = {'descriptor': module_factory_descriptor(validate_components, 'paired.actual_components'),
        'implementation': callable_implementation(validate_components)}
    for arm in config.arms:
        sources = option_sources[arm.strategy]
        if (not isinstance(sources, dict) or set(sources) != set(arm.model_host.action_ids)
                or any(not isinstance(source, ActionOptionSource) for source in sources.values())):
            raise TaskConflict('Paired assembly requires one actual option source per original action')
        policy = model_client_request_policy(clients[arm.strategy])
        if task_digest(policy) != config.model_configuration_sha256:
            raise TaskConflict('Paired actual safe transport policy differs from its frozen model configuration')
        policies[arm.strategy] = policy
        original_options[arm.strategy] = dict(sources)
        option_declarations[arm.strategy] = {basis.action_id: _original_option_declaration(
            sources[basis.action_id], basis) for basis in config.action_basis}
    source_check = validate_paired_experiment_sources(config, output_root=output_root,
        arms=arms, validate_current=validate_sources)
    original_arms = {arm.strategy: (arms[arm.strategy], arms[arm.strategy].registry,
        arms[arm.strategy].store, {action_id: (sources, sources.reading)
            for action_id, sources in arms[arm.strategy].actions.items()}) for arm in config.arms}
    state_binding = bind_paired_runtime_isolation(config, output_root=output_root,
        source_check=source_check, states=states, validate_current=validate_isolation)
    isolation_check = deepcopy(state_binding.evidence)
    if validate_components(configuration=config.model_copy(deep=True), arms=arms, states=states,
            clients=clients, option_sources=option_sources) is not True:
        raise TaskConflict('Paired actual host/client/state/option routing and model configuration did not verify')
    current_gate = {'descriptor': module_factory_descriptor(validate_components, 'paired.actual_components'),
        'implementation': callable_implementation(validate_components)}
    if (set(clients) != strategies or set(option_sources) != strategies
            or task_digest(current_gate) != task_digest(component_gate)):
        raise TaskConflict('Paired component gate or original component set changed during assembly')
    state_binding.recheck(output_root=output_root, initial=True)
    for arm, checked in zip(config.arms, source_check['arms']):
        actual = arms[arm.strategy]
        original_arm, registry, store, original_actions = original_arms[arm.strategy]
        if (clients[arm.strategy] is not original_clients[arm.strategy]
                or actual is not original_arm or actual.registry is not registry or actual.store is not store
                or set(option_sources[arm.strategy]) != set(original_options[arm.strategy])
                or actual.store.run_id != arm.run_id or actual.store.path is None
                or actual.store.path.resolve().as_posix() != checked['task_store_path']
                or set(actual.actions) != set(checked['invocation_sha256s'])):
            raise TaskConflict('Paired assembly changed its original client, journal or action set')
        for basis in config.action_basis:
            original = original_options[arm.strategy][basis.action_id]
            sources = actual.actions[basis.action_id]
            if (option_sources[arm.strategy][basis.action_id] is not original
                    or sources is not original_actions[basis.action_id][0]
                    or sources.reading is not original_actions[basis.action_id][1]
                    or task_digest(_original_option_declaration(original, basis))
                        != task_digest(option_declarations[arm.strategy][basis.action_id])
                    or paired_invocation_digest(sources, actual.registry.get(basis.action_id))
                        != checked['invocation_sha256s'][basis.action_id]
                    or paired_action_basis(registry=actual.registry, action_id=basis.action_id, sources=sources) != basis):
                raise TaskConflict('Paired assembly changed preflight input, facts, options or their original implementation')
    hosts = {}
    for arm in config.arms:
        actual = arms[arm.strategy]
        sources = {basis.action_id: _checked_option_source(registry=actual.registry, expected=basis,
            sources=actual.actions[basis.action_id], original=option_sources[arm.strategy][basis.action_id])
            for basis in config.action_basis}
        if task_digest(model_client_request_policy(clients[arm.strategy])) != task_digest(policies[arm.strategy]):
            raise TaskConflict('Paired client transport changed during actual assembly gates')
        host = ActionModelHost(store=actual.store, registry=actual.registry, client=clients[arm.strategy],
            model_version=config.model_version, configuration=arm.model_host, option_sources=sources)
        if (len(host.bindings) != 1 or host.bindings[0].strategy != arm.strategy
                or host.bindings[0].action_ids != frozenset(arm.model_host.action_ids)):
            raise TaskConflict('Paired host failed to bind its exact configured original strategy and action set')
        hosts[arm.strategy] = host
    # Host construction may create original technical metadata. Runtime state
    # content can now evolve; its backing locations/adapters remain fixed.
    state_binding.recheck(output_root=output_root)
    evidence = {'schema_version': 'paired-model-hosts.v2', 'status': 'assembled_execution_unverified',
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'source_check_sha256': source_check['record_sha256'],
        'isolation_check_sha256': isolation_check['record_sha256'],
        'hosts': {strategy: deepcopy(host.metadata) for strategy, host in hosts.items()},
        'component_gate': component_gate,
        'limitations': 'Host construction and checked initial sources/state only; no model calls, macro effects, result comparison or measured advantage.'}
    if application_callbacks is not None:
        evidence['application_callbacks_sha256'] = application_callbacks['record_sha256']
        evidence['application_callbacks'] = application_callbacks
    evidence['record_sha256'] = task_digest(evidence)
    return PairedModelHosts(configuration=config.model_copy(deep=True), hosts=MappingProxyType(hosts),
        source_check=deepcopy(source_check), isolation_check=deepcopy(isolation_check), evidence=evidence,
        state_binding=state_binding)
