"""Explicit host configuration of model strategies with one durable call budget."""
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Callable

from pydantic import Field

from src.actions.contracts.common import StrictRecord, TextId
from src.actions.contracts.references import ActionReadView
from src.actions.model_strategy import SingleAgentActionStrategy, model_client_request_policy
from src.actions.organization_strategy import OrganizationDiscussionActionStrategy
from src.actions.registry import ActionRegistry
from src.actions.runner import ActionRunner
from src.actions.decision_strategies import DecisionStrategyBinding
from src.actions.implementation import callable_implementation
from src.coordination.model_budget import ModelCallBudget
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest, _text


class ActionModelHostConfiguration(StrictRecord):
    host_id: TextId
    budget_id: TextId
    max_calls: Annotated[int, Field(gt=0)]
    action_ids: Annotated[list[TextId], Field(min_length=1)]
    max_options: Annotated[int, Field(gt=0)] = 3
    max_prompt_chars: Annotated[int, Field(gt=0)] = 60000
    max_response_chars: Annotated[int, Field(gt=0)] = 4096
    max_members: Annotated[int, Field(gt=0)] = 4
    max_reason_chars: Annotated[int, Field(gt=0)] = 800


@dataclass(frozen=True)
class ActionOptionSource:
    """Actual callbacks/version; optional local preparation precedes task claim."""
    version: str
    prepare_options: Callable
    validate_options: Callable
    prepare_invocation: Callable | None = None

    def __post_init__(self):
        _text(self.version)
        if (not callable(self.prepare_options) or not callable(self.validate_options)
                or self.prepare_invocation is not None and not callable(self.prepare_invocation)):
            raise ValueError('Explicit original option production and validation callbacks required')


class ActionModelHost:
    """Build configured strategies only; never load credentials or invoke a model.

    One binding per configured strategy matches ActionRunner's dispatch. The
    host supplies each action's actual option source; unsupported actions do
    not gain a fabricated implementation. Both bindings share the same budget.
    """
    VERSION = 'action-model-host.v1'

    def __init__(self, *, store, registry, client, model_version, configuration, option_sources):
        if not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry):
            raise ValueError('Action model host requires the actual journal and action registry')
        _text(model_version)
        client_policy = model_client_request_policy(client)
        config = ActionModelHostConfiguration.model_validate(configuration).model_copy(deep=True)
        actions = frozenset(config.action_ids)
        if (len(actions) != len(config.action_ids) or not isinstance(option_sources, dict)
                or set(option_sources) != actions
                or any(not isinstance(source, ActionOptionSource) for source in option_sources.values())):
            raise ValueError('Every explicitly configured action needs exactly one actual option source')
        groups = {}
        for action_id in actions:
            registration = registry.get(action_id)
            if not registration.implemented or registration.skill is None:
                raise ValueError('Model host cannot activate an action without its processor and bound Skill')
            if registration.strategy not in {'single_agent', 'organization_discussion'}:
                raise ValueError('Model host requires the original explicitly configured role strategy')
            groups.setdefault(registration.strategy, set()).add(action_id)
        self.store, self.registry, self.model_version, self.configuration = store, registry, model_version, config
        self._client = client
        self.option_sources = MappingProxyType(dict(option_sources))
        self._option_source_declarations = self._source_declarations()
        self.budget = ModelCallBudget(store=store, budget_id=config.budget_id, max_calls=config.max_calls)
        self._preparation_callback = self.prepare_invocation

        def prepare_options(**kwargs):
            result = self._source(kwargs['registration']).prepare_options(**kwargs)
            self._check()
            return result

        def validate_options(**kwargs):
            result = self._source(kwargs['registration']).validate_options(**kwargs)
            self._check()
            return result

        self.components = []
        for strategy, action_ids in sorted(groups.items()):
            kwargs = {'run_id': store.run_id, 'client': client, 'model_version': model_version,
                'action_ids': frozenset(action_ids), 'prepare_options': prepare_options, 'validate_options': validate_options,
                'options_version': task_digest({action_id: self._option_source_declarations[action_id]
                    for action_id in sorted(action_ids)}),
                'max_calls': config.max_calls, 'max_options': config.max_options,
                'max_prompt_chars': config.max_prompt_chars, 'max_response_chars': config.max_response_chars,
                'call_budget': self.budget}
            if strategy == 'organization_discussion':
                component = OrganizationDiscussionActionStrategy(registry=registry, max_members=config.max_members,
                    max_reason_chars=config.max_reason_chars, **kwargs)
            else:
                component = SingleAgentActionStrategy(**kwargs)
            if any(option_sources[action_id].prepare_invocation is not None for action_id in action_ids):
                component._binding = replace(component.binding(), prepare_invocation=self._preparation_callback)
            self.components.append(component)
        self.components = tuple(self.components)
        self.bindings = tuple(component.binding() for component in self.components)
        paths = (Path(__file__), Path(SingleAgentActionStrategy.execute.__code__.co_filename),
                 Path(OrganizationDiscussionActionStrategy.execute.__code__.co_filename),
                 Path(ModelCallBudget.reserve.__code__.co_filename),
                 Path(ActionRunner.prepare_decision.__code__.co_filename),
                 Path(ActionReadView.calculate.__code__.co_filename),
                 Path(DecisionStrategyBinding.__post_init__.__code__.co_filename))
        metadata = {'schema_version': self.VERSION, 'run_id': store.run_id, 'model_version': model_version,
            'client_request_policy': client_policy,
            'configuration': config.model_dump(mode='json'),
            'option_sources': {key: source.version for key, source in sorted(option_sources.items())},
            'option_source_implementations': deepcopy(self._option_source_declarations),
            'bindings': [binding.evidence(status='configured') for binding in self.bindings],
            'code_sha256s': [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]}
        metadata['option_source_code_sha256s'] = {}
        for action_id, source in sorted(option_sources.items()):
            hashes = []
            callbacks = (source.prepare_options, source.validate_options)
            if source.prepare_invocation is not None:
                callbacks += (source.prepare_invocation,)
            for callback in callbacks:
                code = getattr(callback, '__code__', None)
                if code is None:
                    code = getattr(getattr(callback, '__call__', None), '__code__', None)
                path = Path(code.co_filename) if code is not None else None
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.is_file() else None)
            metadata['option_source_code_sha256s'][action_id] = hashes
        self.configuration_sha256 = task_digest(metadata)
        self.metadata = {**metadata, 'configuration_sha256': self.configuration_sha256}
        key = 'action_model_host:' + config.host_id
        with store._transaction():
            row = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if row is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(self.metadata)))
            elif json.loads(row[0]) != self.metadata:
                raise TaskConflict('Original model host configuration/code changed; no silent restart migration')
        self._runtime_components = (store, registry, client, self.budget, self.option_sources,
            self.components, self.bindings, self._preparation_callback)
        self._declared_metadata = deepcopy(self.metadata)
        self._strategy_callbacks = tuple((component.prepare_options, component.validate_options)
            for component in self.components)

    def _check(self):
        components = (self.store, self.registry, self._client, self.budget, self.option_sources,
            self.components, self.bindings, self._preparation_callback)
        if (any(actual is not original for actual, original in zip(components, self._runtime_components))
                or self.metadata != self._declared_metadata
                or self.configuration_sha256 != self._declared_metadata['configuration_sha256']
                or self.configuration.model_dump(mode='json') != self._declared_metadata['configuration']
                or self.model_version != self._declared_metadata['model_version']
                or self.store.run_id != self._declared_metadata['run_id']
                or self._source_declarations() != self._declared_metadata['option_source_implementations']
                or self._option_source_declarations != self._declared_metadata['option_source_implementations']
                or self.budget.store is not self.store):
            raise TaskConflict('Original model host components or configuration changed')
        config = self.configuration
        for component, binding, callbacks in zip(self.components, self.bindings, self._strategy_callbacks):
            preparation = self._preparation_callback if any(
                self.option_sources[action_id].prepare_invocation is not None for action_id in binding.action_ids) else None
            if (component.client is not self._client or component.call_budget is not self.budget
                    or component.binding() is not binding
                    or binding.prepare_invocation is not preparation
                    or component.prepare_options is not callbacks[0] or component.validate_options is not callbacks[1]
                    or component.run_id != self.store.run_id or component.model_version != self.model_version
                    or any(getattr(component, name) != getattr(config, name) for name in
                        ('max_calls', 'max_options', 'max_prompt_chars', 'max_response_chars'))
                    or binding.strategy == 'organization_discussion' and any(
                        getattr(component, name) != getattr(config, name) for name in ('max_members', 'max_reason_chars'))):
                raise TaskConflict('Original model strategy client, options or limits changed')
            component._check_model_request_policy()
        with self.store._lock:
            self.budget._budget()
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                ('action_model_host:' + config.host_id,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared_metadata:
                raise TaskConflict('Original model host configuration evidence changed')

    def _source_declarations(self):
        return {action_id: dict(version=source.version,
            prepare_options=callable_implementation(source.prepare_options),
            validate_options=callable_implementation(source.validate_options),
            prepare_invocation=callable_implementation(source.prepare_invocation)
                if source.prepare_invocation is not None else None)
            for action_id, source in sorted(self.option_sources.items())}

    def _source(self, registration):
        self._check()
        if self.registry.get(registration.action_id) is not registration:
            raise ValueError('Model option callback substituted its original action registry')
        return self.option_sources[registration.action_id]

    def prepare_invocation(self, *, context, action_input, registration, reading):
        """Prepare local option inputs before a worker claims its task.

        The role host holds its actual source/authorization guard. Existing
        direct option sources have no preparation hook and keep their original
        behavior. Durable sources may save explicit alternatives here, without
        running a processor, professional method or model.
        """
        source = self._source(registration)
        if source.prepare_invocation is None:
            return None
        if not isinstance(reading, ActionReadView) or context.run_id != self.store.run_id:
            raise TaskConflict('Option preparation requires its original authorized reading and journal run')
        reading.check_method_context(context, registration.action_id)
        before = reading.method_evidence()
        try:
            result = source.prepare_invocation(context=context.model_copy(deep=True),
                action_input=registration.contract.validate_input(action_input).model_copy(deep=True),
                registration=registration, reading=reading)
            if not isinstance(result, dict):
                raise TaskConflict('Option preparation requires explicit local snapshot evidence')
            task_digest(result)
            self._check()
            return deepcopy(result)
        finally:
            reading.recheck()
            if reading.method_evidence() != before:
                raise TaskConflict('Option preparation cannot execute professional methods')

    def evidence(self):
        self._check()
        return {'configuration_sha256': self.configuration_sha256, 'host_id': self.configuration.host_id,
            'bindings': [binding.evidence(status='configured') for binding in self.bindings],
            'call_budget': self.budget.usage()}


def resolve_action_model_host(*, registry, run_id, model_version, decision_strategies, model_host):
    """Use explicit host bindings or preserve the caller's existing direct configuration."""
    bindings = tuple(decision_strategies)
    if model_host is None:
        return model_version, bindings
    if (not isinstance(model_host, ActionModelHost) or model_host.registry is not registry
            or model_host.store.run_id != run_id or bindings
            or model_version is not None and model_version != model_host.model_version):
        raise ValueError('Assembler model host must share its registry/run without competing strategy configuration')
    model_host._check()
    return model_host.model_version, model_host.bindings
