"""Explicit GBA host factory configuration and original run-local source evidence."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import Field

from integration.scenario_v2 import read_input_json
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, canonical, task_digest


class GbaModuleHostConfiguration(StrictRecord):
    schema_version: Literal['gba-module-host-config.v1']
    host_id: TextId
    version: TextId
    settings: dict = Field(default_factory=dict)


def load_module_host_configuration(path):
    """Read explicit settings without loading credentials, building a client or calling a factory."""
    _, raw = read_input_json(path)
    configuration = GbaModuleHostConfiguration.model_validate(raw).model_copy(deep=True)
    task_digest(configuration.model_dump(mode='json'))
    return configuration


def module_factory_descriptor(factory, specification):
    code = getattr(factory, '__code__', None)
    if code is None:
        code = getattr(getattr(factory, '__call__', None), '__code__', None)
    path = Path(code.co_filename) if code is not None else None
    return {'specification': specification,
        'component': getattr(factory, '__module__', type(factory).__module__) + '.'
            + getattr(factory, '__qualname__', type(factory).__qualname__),
        'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.is_file() else None}


def module_client_implementation(client):
    """Identify actual transport, handlers and feedback code without invoking it.

    Handler state and closure data remain the host's explicit configuration
    responsibility. Source/runtime digests contain no captured business data.
    """
    from integration.agent_client import GbaV1AgentClient, observation_digest

    if not isinstance(client, GbaV1AgentClient):
        raise ValueError('Actual GBA client required for implementation evidence')
    with client._lock:
        return {'schema_version': 'gba-client-implementation.v2',
            'entries': {name: callable_implementation(getattr(client, name)) for name in
                ('propose', 'recover_proposal', '_reconcile_proposal', '_proposal_route', '_proposal_recovery',
                 '_proposal_recovery_guard', '_invocation_identity',
                 'decide', 'decide_async', 'observe', '_identity', '_task_request_id', '_invoke', '_input_snapshot', '_response',
                 'capabilities', 'health')},
            'proposal_handlers': [{'role': role, 'operation': operation,
                'implementation': callable_implementation(handler),
                'saved_result_recovery': callable_implementation(client._proposal_recovery(handler))
                    if client._proposal_recovery(handler) is not None else None,
                'saved_result_recovery_guard': callable_implementation(client._proposal_recovery_guard(handler))
                    if client._proposal_recovery_guard(handler) is not None else None}
                for (role, operation), handler in sorted(client.proposal_handlers.items())],
            'decision_handler': callable_implementation(client.decision_handler),
            'observation_projection': callable_implementation(client._projection),
            'observation_digest': callable_implementation(observation_digest),
            'observation_delivery': callable_implementation(client.inbox.deliver),
            'task_journal': callable_implementation(client.tasks.ensure),
            'continuation_dispatcher': callable_implementation(client.continuation_dispatcher)
                if client.continuation_dispatcher is not None else None,
            'tender_feedback': callable_implementation(client._tender_feedback.record)
                if client._tender_feedback is not None else None,
            'boundary': callable_implementation(module_client_implementation)}


def validate_module_host_client(client, metadata):
    """Check the original factory result before running/exporting without a hook."""
    with client._lock:
        if (metadata.get('schema_version') != 'gba-module-host-assembly.v2'
                or metadata.get('run_id') != client.run_id
                or metadata.get('client_versions') != client.versions
                or metadata.get('organization_roles') != client.organization_roles
                or metadata.get('client_implementation') != module_client_implementation(client)
                or task_digest({key: value for key, value in metadata.items() if key != 'assembly_sha256'})
                    != metadata.get('assembly_sha256')):
            raise TaskConflict('Original module client versions, recipients or executable handlers changed')


def build_module_host_client(*, factory, specification, request, output_directory, offline, configuration=None):
    """Invoke the selected factory once and pin the actual source/configuration to its own journal."""
    from integration.agent_client import GbaV1AgentClient

    if not callable(factory) or type(offline) is not bool:
        raise ValueError('Module host requires its explicit factory and model mode')
    if configuration is not None and not isinstance(configuration, GbaModuleHostConfiguration):
        raise ValueError('Module host configuration must use its explicit closed schema')
    descriptor = module_factory_descriptor(factory, specification)
    kwargs = {'request': request.model_copy(deep=True), 'output_directory': Path(output_directory), 'offline': offline}
    if configuration is not None:
        kwargs['configuration'] = configuration.model_dump(mode='json')
    client = factory(**kwargs)
    if not isinstance(client, GbaV1AgentClient):
        raise ValueError('GBA module factory must return its original GbaV1AgentClient with explicit handlers and versions')
    try:
        metadata = {'schema_version': 'gba-module-host-assembly.v2', 'run_id': client.run_id,
            'host_id': configuration.host_id if configuration is not None else specification,
            'factory': descriptor, 'requested_model_mode': 'offline' if offline else 'llm',
            'configuration_version': configuration.version if configuration is not None else None,
            'configuration_sha256': task_digest(configuration.model_dump(mode='json')) if configuration is not None else None,
            'initial_request_sha256': task_digest(request.model_dump(mode='json')),
            'client_component': type(client).__module__ + '.' + type(client).__qualname__,
            'client_versions': dict(client.versions), 'organization_roles': dict(client.organization_roles),
            'client_implementation': module_client_implementation(client)}
        metadata['assembly_sha256'] = task_digest(metadata)
        key = 'gba_module_host:' + metadata['host_id']
        if module_factory_descriptor(factory, specification) != descriptor:
            raise TaskConflict('Actual module host factory source changed while constructing the client')
        validate_module_host_client(client, metadata)
        with client.tasks._transaction():
            previous = client.tasks._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(metadata)))
            elif json.loads(previous[0]) != metadata:
                raise TaskConflict('Original module host factory/configuration/request/client versions changed')
    except Exception:
        client.close()
        raise
    return client, deepcopy(metadata)


@dataclass(frozen=True)
class GbaModuleHostExtension:
    """Explicit engine-dependent host resources, live evidence and cleanup."""
    version: str
    evidence: Callable
    close: Callable
    writer_guard: Callable | None = None
    checkpoint_validator: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not callable(self.evidence) or not callable(self.close)
                or self.writer_guard is not None and not callable(self.writer_guard)
                or self.checkpoint_validator is not None and not callable(self.checkpoint_validator)):
            raise ValueError('Module host extension requires a version, actual evidence reader and cleanup')


class BoundModuleHostExtension:
    """Keep the actual configured engine/client and source/version evidence together."""
    def __init__(self, *, assembly, extension, hook, specification, metadata):
        self.assembly, self.extension = assembly, extension
        self.hook, self.specification = hook, specification
        self.metadata = deepcopy(metadata)
        self._engine, self._client = assembly.engine, assembly.client
        self._extension, self._writer_guard = extension, extension.writer_guard
        self._checkpoint_validator = extension.checkpoint_validator
        self._run_started = False
        self._closed = False

    def evidence(self):
        with self._writer_guard() if self._writer_guard is not None else nullcontext():
            return self._evidence()

    def _evidence(self):
        self._check_binding()
        original_tick = self._engine.current_tick
        evidence = self.extension.evidence()
        if not isinstance(evidence, dict):
            raise ValueError('Module host extension evidence must be an actual JSON object')
        self._check_binding()
        if self._engine.current_tick != original_tick:
            raise TaskConflict('Module host evidence reader changes core state or execution configuration')
        json.dumps(evidence, allow_nan=False)
        return {'assembly': deepcopy(self.metadata), 'host': deepcopy(evidence)}

    def _check_binding(self):
        self.assembly._validate_components()
        if (self._closed or self.extension is not self._extension
                or self.extension.writer_guard is not self._writer_guard
                or self.extension.checkpoint_validator is not self._checkpoint_validator
                or (module_factory_descriptor(self._checkpoint_validator, 'extension.checkpoint_validator')
                    if self._checkpoint_validator is not None else None) != self.metadata.get('checkpoint_validator')
                or (module_factory_descriptor(self._writer_guard, 'extension.writer_guard')
                    if self._writer_guard is not None else None) != self.metadata.get('writer_guard')
                or self.assembly.engine is not self._engine or self.assembly.client is not self._client
                or self._client.run_id != self.metadata['run_id']
                or self._client.simulation_id != self.metadata['simulation_id']
                or self._engine.simulation_id != self.metadata['simulation_id']
                or self._client.versions != self.metadata['client_versions_after']
                or self._client.organization_roles != self.metadata['organization_roles']
                or module_client_implementation(self._client) != self.metadata['client_implementation_after']
                or self.extension.version != self.metadata['extension_version']
                or module_factory_descriptor(self.hook, self.specification) != self.metadata['hook']
                or module_factory_descriptor(self.extension.evidence, 'extension.evidence') != self.metadata['evidence_reader']
                or module_factory_descriptor(self.extension.close, 'extension.close') != self.metadata['cleanup']):
            raise TaskConflict('Configured module host changes original engine, client, versions or actual extension source')

    def run_engine(self, *, ticks=None):
        """Advance the original engine once under the application's shared guard.

        The guard must allow same-thread reentry: native callbacks and source
        readers run inside engine.run and use this same guard. Other application
        writers must also use it. Failed/interrupted execution is not replayed.
        This wrapper does not replace or patch any native engine method.
        """
        with self._writer_guard() if self._writer_guard is not None else nullcontext():
            self._client._assert_runtime_ready()
            self._evidence()
            if self._run_started:
                raise TaskConflict('Module host engine run was already started; explicit recovery is required')
            self._run_started = True
            return self._engine.run(ticks=ticks) if ticks is not None else self._engine.run()

    def save_checkpoint(self, *, request, path):
        from integration.native_checkpoint import save_native_checkpoint
        with self._writer_guard() if self._writer_guard is not None else nullcontext():
            self._check_binding()
            if self._checkpoint_validator is None:
                self._evidence()
            else:
                tick = self._engine.current_tick
                if self._checkpoint_validator() is not None or self._engine.current_tick != tick:
                    raise TaskConflict('Checkpoint validator must check original sources without advancing business')
                self._check_binding()
            return save_native_checkpoint(self.assembly, request=request, path=path,
                                          read_guard=self._writer_guard)

    def close(self):
        if not self._closed:
            self._closed = True
            self.extension.close()


def configure_module_host_extension(*, assembly, hook, specification, request,
        output_directory, offline, host_evidence, configuration=None, extension_configuration=None):
    """Reinstall checkpoint applications before releasing restored business requests."""
    from integration.native_checkpoint import checkpoint_reinstallation
    bound = None
    try:
        with checkpoint_reinstallation(assembly) as window:
            bound = _configure_module_host_extension(assembly=assembly, hook=hook, specification=specification,
                request=request, output_directory=output_directory, offline=offline, host_evidence=host_evidence,
                configuration=configuration, extension_configuration=extension_configuration)
            window['read_guard'] = bound._writer_guard
        return bound
    except BaseException:
        if bound is not None:
            bound.close()
        raise


def _configure_module_host_extension(*, assembly, hook, specification, request,
        output_directory, offline, host_evidence, configuration=None, extension_configuration=None):
    """Configure one explicit hook after engine creation and before core execution.

    The hook may install actual routes and source providers, but may not advance
    the core. It owns resources until a typed extension is returned; failed hook
    construction must clean up its own partially constructed resources.
    configuration identifies the original client factory. An explicit
    extension_configuration supplies independent hook settings; when omitted,
    the hook retains the existing shared-configuration behavior.
    """
    from integration.bindings.gba_v1 import GbaV1Assembly

    if (not isinstance(assembly, GbaV1Assembly) or not callable(hook) or type(offline) is not bool
            or not isinstance(host_evidence, dict)
            or configuration is not None and not isinstance(configuration, GbaModuleHostConfiguration)
            or extension_configuration is not None and not isinstance(extension_configuration, GbaModuleHostConfiguration)):
        raise ValueError('Module extension requires its original assembly and explicit hook/configuration')
    assembly._validate_components()
    client, engine = assembly.client, assembly.engine
    original_tick, original_simulation = engine.current_tick, engine.simulation_id
    before_versions = deepcopy(client.versions)
    before_roles = deepcopy(client.organization_roles)
    descriptor = module_factory_descriptor(hook, specification)
    parent = deepcopy(host_evidence)
    validate_module_host_client(client, parent)
    if (task_digest({key: value for key, value in parent.items() if key != 'assembly_sha256'}) != parent.get('assembly_sha256')
            or parent.get('run_id') != client.run_id or parent.get('client_versions') != before_versions
            or parent.get('organization_roles') != before_roles
            or parent.get('initial_request_sha256') != task_digest(request.model_dump(mode='json'))
            or parent.get('configuration_sha256') != (task_digest(configuration.model_dump(mode='json')) if configuration is not None else None)
            or parent.get('requested_model_mode') != ('offline' if offline else 'llm')):
        raise TaskConflict('Module extension requires original matching pre-engine host evidence')
    kwargs = {'assembly': assembly, 'request': request.model_copy(deep=True),
        'output_directory': Path(output_directory), 'offline': offline}
    hook_configuration = extension_configuration if extension_configuration is not None else configuration
    if hook_configuration is not None:
        kwargs['configuration'] = hook_configuration.model_dump(mode='json')
    extension = hook(**kwargs)
    if not isinstance(extension, GbaModuleHostExtension):
        raise ValueError('Module assembly hook must return GbaModuleHostExtension')
    bound = None
    try:
        assembly._validate_components()
        if (assembly.client is not client or assembly.engine is not engine
                or engine.current_tick != original_tick or engine.simulation_id != original_simulation
                or client.simulation_id != original_simulation or client.organization_roles != before_roles
                or set(client.versions) != set(before_versions)
                or any(not isinstance(value, str) or not value.strip() for value in client.versions.values())
                or module_factory_descriptor(hook, specification) != descriptor):
            raise TaskConflict('Module assembly hook changed core tick, original engine/client/recipient or hook source')
        metadata = {'schema_version': 'gba-module-host-extension.v2', 'run_id': client.run_id,
            'simulation_id': original_simulation, 'host_id': parent['host_id'],
            'parent_host_assembly_sha256': parent['assembly_sha256'],
            'configuration_sha256': task_digest(hook_configuration.model_dump(mode='json')) if hook_configuration is not None else None,
            'requested_model_mode': parent['requested_model_mode'], 'hook': descriptor,
            'extension_component': type(extension).__module__ + '.' + type(extension).__qualname__,
            'extension_version': extension.version,
            'evidence_reader': module_factory_descriptor(extension.evidence, 'extension.evidence'),
            'cleanup': module_factory_descriptor(extension.close, 'extension.close'),
            'client_versions_before': before_versions, 'client_versions_after': deepcopy(client.versions),
            'client_implementation_before': deepcopy(parent['client_implementation']),
            'client_implementation_after': module_client_implementation(client),
            'organization_roles': before_roles}
        if extension.writer_guard is not None:
            metadata['writer_guard'] = module_factory_descriptor(extension.writer_guard, 'extension.writer_guard')
        if extension.checkpoint_validator is not None:
            metadata['checkpoint_validator'] = module_factory_descriptor(extension.checkpoint_validator, 'extension.checkpoint_validator')
        if extension_configuration is not None:
            metadata['parent_configuration_sha256'] = parent['configuration_sha256']
            metadata['extension_host_id'] = hook_configuration.host_id
            metadata['extension_configuration_version'] = hook_configuration.version
        metadata['assembly_sha256'] = task_digest(metadata)
        bound = BoundModuleHostExtension(assembly=assembly, extension=extension,
            hook=hook, specification=specification, metadata=metadata)
        bound.evidence()
        with client.tasks._transaction():
            key = 'gba_module_host_extension:' + parent['host_id']
            row = client.tasks._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if row is None:
                client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(metadata)))
            elif json.loads(row[0]) != metadata:
                raise TaskConflict('Original module extension source/configuration/engine or execution versions changed')
    except Exception:
        if bound is None:
            extension.close()
        else:
            bound.close()
        raise
    return bound
