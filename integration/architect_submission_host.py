"""Explicit Architect submission routes over the original persistent result workers."""
from copy import deepcopy
import importlib
import json
from types import MappingProxyType
from typing import Literal

from integration.module_host import module_factory_descriptor
from integration.architect_role_contract_host import _ACTIONS
from integration.architect_submission import ArchitectResultSubmission, ArchitectSubmissionCallbacks, _worker_metadata
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest


class ArchitectSubmissionRoute(StrictRecord):
    action_id: TextId
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId
    supported_choices: list[TextId]


class ArchitectSubmissionHostConfiguration(StrictRecord):
    schema_version: Literal['architect-submission-host-config.v1']
    host_id: TextId
    version: TextId
    routes: list[ArchitectSubmissionRoute]


class ArchitectSubmissionHost:
    """Assemble declared application routes; submit and receipt reads are explicit.

    All workers and snapshots share the original registry/persistent journal.
    Design, review, billing and transition endpoints are supplied explicitly
    by the actual application; every action retains its original result table.
    Application read_guard(identity) holds current sources and authorization.
    The application owns cleanup, real endpoints and action-specific validation.
    role_contract produces local decisions without automatically submitting them.
    """
    VERSION = 'architect-submission-host.v1'

    def __init__(self, *, store, registry, workers, callbacks, read_guard, configuration):
        config = ArchitectSubmissionHostConfiguration.model_validate(configuration).model_copy(deep=True)
        actions = [route.action_id for route in config.routes]
        bindings = [route.binding_id for route in config.routes]
        if (not isinstance(store, TaskStore) or store.path is None or not isinstance(registry, ActionRegistry)
                or not isinstance(workers, dict) or not isinstance(callbacks, dict) or not callable(read_guard)
                or len(set(actions)) != len(actions) or len(set(bindings)) != len(bindings)
                or not set(actions) <= set(_ACTIONS) or set(workers) != set(actions) or set(callbacks) != set(actions)):
            raise ValueError('Architect submission host requires unique explicit routes and original persistent components')
        for route in config.routes:
            worker, callback = workers[route.action_id], callbacks[route.action_id]
            module, name = _ACTIONS[route.action_id]
            worker_type = getattr(
                importlib.import_module('integration.architect_' + module + '_results'),
                'Architect' + name + 'ResultWorker')
            worker_registry, _, _ = _worker_metadata(worker, route.action_id)
            registration = registry.get(route.action_id)
            if (not isinstance(worker, worker_type) or worker.store is not store
                    or worker.snapshots.store is not store or worker_registry is not registry
                    or not isinstance(callback, ArchitectSubmissionCallbacks)
                    or registration.role != 'Architect' or not registration.implemented or registration.skill is None
                    or not route.supported_choices
                    or len(set(route.supported_choices)) != len(route.supported_choices)
                    or not set(route.supported_choices) <= set(registration.contract.choices)
                    or set(route.supported_choices) & {'reconcile', 'reconcile_upstream', 'reconcile_execution'}
                    and callback.query is None):
                raise ValueError('Architect route requires its original worker, journal, branches and actual callbacks; reconciliation needs query')
        self.store, self.registry, self.read_guard = store, registry, read_guard
        self.configuration = config
        self.workers = MappingProxyType(dict(workers))
        self.callbacks = MappingProxyType(dict(callbacks))
        self.routes = MappingProxyType({route.action_id: ArchitectResultSubmission(worker=workers[route.action_id], action_id=route.action_id,
            binding_id=route.binding_id, binding_version=route.binding_version, macro_version=route.macro_version,
            supported_choices=route.supported_choices, callbacks=callbacks[route.action_id]) for route in config.routes})
        self._components = (store, registry, read_guard, self.workers, self.callbacks, self.routes)
        self._declared = self._configuration()
        self._key = 'architect_submission_host:' + config.host_id
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original Architect submission host configuration or code changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration': self.configuration.model_dump(mode='json'),
            'host': module_factory_descriptor(type(self).submit, self.VERSION),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard'),
            'routes': {action_id: {'binding': route._configuration(),
                'execution': module_factory_descriptor(route.execute, action_id),
                'transport': module_factory_descriptor(route._submit, action_id),
                'worker': {'table': route.RESULT_TABLE,
                    'client_version': self.workers[action_id].client_version,
                    'model_version': self.workers[action_id].model_version}}
                for action_id, route in sorted(self.routes.items())}}

    def _check(self):
        current = (self.store, self.registry, self.read_guard, self.workers, self.callbacks, self.routes)
        if any(actual is not original for actual, original in zip(current, self._components)):
            raise TaskConflict('Architect submission host substituted its original components')
        if self._configuration() != self._declared:
            raise TaskConflict('Architect submission host routes, configuration or actual code changed')
        for action_id, route in self.routes.items():
            worker = self.workers[action_id]
            if (route.worker is not worker or worker.store is not self.store or worker.snapshots.store is not self.store
                    or _worker_metadata(worker, action_id) != (self.registry, route.RESULT_TABLE, route.RESULT_SCHEMA)
                    or route.callbacks is not self.callbacks[action_id]):
                raise TaskConflict('Architect submission route substituted its original components')
            route._check_binding()
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Architect submission host evidence is missing or changed')

    def _dispatch(self, identity, operation):
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if (identity.run_id != self.store.run_id or identity.organization_id not in self.store.organization_ids
                or identity.role != 'Architect' or identity.purpose != 'action' or identity.action_id not in self.routes):
            raise TaskConflict('Architect submission requires its configured own original task and action route')
        with self.read_guard(TaskIdentity(**identity.as_dict())):
            self._check()
            result = getattr(self.routes[identity.action_id], operation)(identity)
            self._check()
            return deepcopy(result)

    def submit(self, identity):
        """Explicitly transport a saved result or recover an uncertain submission."""
        return self._dispatch(identity, 'execute')

    def recover(self, identity):
        """Query the original identity without resubmitting or rerunning a processor."""
        return self._dispatch(identity, 'recover')

    def read_receipt(self, identity):
        """Read a confirmed original receipt under current own receipt authority."""
        return self._dispatch(identity, 'read_receipt')

    def capabilities(self):
        self._check()
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration_sha256': task_digest(self._declared),
            'actions': {action_id: self.routes[action_id].capabilities() if action_id in self.routes else {
                'action_id': action_id, 'status': 'unbound', 'reason': 'No actual application submission route configured'}
                for action_id in _ACTIONS},
            'limitations': ['Configured routes remain unverified until actual native/private application execution is observed.',
                'Application owns real sources, business gates, locks and cleanup; no automatic execution or inferred design acceptance, permission, use release, fees or cash effects.']}
