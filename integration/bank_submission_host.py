"""Explicit bank submission route assembly over the original persistent workers."""
from copy import deepcopy
import importlib
import json
from types import MappingProxyType
from typing import Literal

from integration.bank_intake_results import BankIntakeResultWorker
from integration.bank_role_contract_host import _ACTIONS
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest


class BankSubmissionRoute(StrictRecord):
    action_id: TextId
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId
    supported_choices: list[TextId]


class BankSubmissionHostConfiguration(StrictRecord):
    schema_version: Literal['bank-submission-host-config.v1']
    host_id: TextId
    version: TextId
    routes: list[BankSubmissionRoute]


class BankSubmissionHost:
    """Assemble only declared native/private application routes; never auto-submit.

    Workers, their snapshots and all routes share the original registry/journal.
    The application owns those resources and supplies read_guard(identity), a
    context manager holding current native source/authorization boundaries.
    submit, recover and read_receipt are separate explicit application calls;
    role_contract remains a local decision entry with no native submission.
    """
    VERSION = 'bank-submission-host.v1'

    def __init__(self, *, store, registry, workers, callbacks, read_guard, configuration):
        config = BankSubmissionHostConfiguration.model_validate(configuration).model_copy(deep=True)
        actions = [route.action_id for route in config.routes]
        bindings = [route.binding_id for route in config.routes]
        if (not isinstance(store, TaskStore) or store.path is None or not isinstance(registry, ActionRegistry)
                or not isinstance(workers, dict) or not isinstance(callbacks, dict) or not callable(read_guard)
                or len(set(actions)) != len(actions) or len(set(bindings)) != len(bindings)
                or not set(actions) <= set(_ACTIONS) or set(workers) != set(actions) or set(callbacks) != set(actions)):
            raise ValueError('Bank submission host requires explicit unique routes and original persistent components')
        prepared_routes = []
        for route in config.routes:
            worker, callback = workers[route.action_id], callbacks[route.action_id]
            module, name = _ACTIONS[route.action_id]
            worker_type = getattr(importlib.import_module('integration.bank_' + module + '_results'),
                'Bank' + name + 'ResultWorker')
            submission_type = getattr(importlib.import_module('integration.bank_' + module + '_submission'),
                'Bank' + name + 'Submission')
            if (not isinstance(worker, BankIntakeResultWorker) or not isinstance(worker, worker_type)
                    or worker.ACTION_ID != route.action_id or worker.store is not store
                    or worker.snapshots.store is not store or worker.registry is not registry
                    or not isinstance(callback, BankSubmissionCallbacks)
                    or not issubclass(submission_type, BankResultSubmission)
                    or not route.supported_choices
                    or len(set(route.supported_choices)) != len(route.supported_choices)
                    or not set(route.supported_choices) <= set(registry.get(route.action_id).contract.choices)
                    or route.action_id in {'BANK-A07', 'BANK-A09'} and 'reconcile' in route.supported_choices
                        and callback.query is None):
                raise ValueError('Bank route must retain its original worker/table, journal, contract branches and actual callbacks')
            prepared_routes.append((route, submission_type))
        self.store, self.registry, self.read_guard = store, registry, read_guard
        self.configuration = config
        self.workers = MappingProxyType(dict(workers))
        self.callbacks = MappingProxyType(dict(callbacks))
        self.routes = MappingProxyType({route.action_id: submission_type(worker=workers[route.action_id],
            binding_id=route.binding_id, binding_version=route.binding_version, macro_version=route.macro_version,
            supported_choices=route.supported_choices, callbacks=callbacks[route.action_id])
            for route, submission_type in prepared_routes})
        self._declared = self._configuration()
        self._key = 'bank_submission_host:' + config.host_id
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original bank submission host/configuration/code changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration': self.configuration.model_dump(mode='json'),
            'host': module_factory_descriptor(type(self).submit, self.VERSION),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard'),
            'routes': {action_id: {'binding': route._configuration(),
                'execution': module_factory_descriptor(route.execute, action_id),
                'transport': module_factory_descriptor(route._submit, action_id),
                'worker': {'table': self.workers[action_id].RESULT_TABLE,
                    'client_version': self.workers[action_id].client_version,
                    'model_version': self.workers[action_id].model_version}}
                for action_id, route in sorted(self.routes.items())}}

    def _check(self):
        if self._configuration() != self._declared:
            raise TaskConflict('Bank submission host route/configuration or actual code changed')
        for action_id, route in self.routes.items():
            worker = self.workers[action_id]
            if (route.worker is not worker or worker.store is not self.store or worker.snapshots.store is not self.store
                    or worker.registry is not self.registry or worker.ACTION_ID != action_id
                    or route.callbacks is not self.callbacks[action_id]):
                raise TaskConflict('Bank submission route substituted its original components')
            route._check_binding()
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Bank submission host evidence is missing or changed')

    def _dispatch(self, identity, operation, *, expected_task_sha256=None):
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if (identity.run_id != self.store.run_id or identity.organization_id not in self.store.organization_ids
                or identity.role != 'Bank' or identity.purpose != 'action' or identity.action_id not in self.routes):
            raise TaskConflict('Bank submission requires its configured own original task and action route')
        with self.read_guard(TaskIdentity(**identity.as_dict())):
            self._check()
            if (expected_task_sha256 is not None
                    and task_digest(self.store.get(identity)) != expected_task_sha256):
                raise TaskConflict('Selected original Bank task changed before guarded query recovery')
            result = getattr(self.routes[identity.action_id], operation)(identity)
            self._check()
            return deepcopy(result)

    def submit(self, identity):
        """Explicitly transport a saved result or recover an already uncertain one."""
        return self._dispatch(identity, 'execute')

    def recover(self, identity, *, expected_task_sha256=None):
        """Query the original identity, optionally requiring the selected current task.

        Selection is rechecked under the original source/query guard before any
        native recovery callback. A changed task is rejected without polling,
        running a processor or resubmitting.
        """
        return self._dispatch(identity, 'recover', expected_task_sha256=expected_task_sha256)

    def read_receipt(self, identity):
        """Read only a confirmed original receipt under current recipient authority."""
        return self._dispatch(identity, 'read_receipt')

    def capabilities(self):
        self._check()
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration_sha256': task_digest(self._declared),
            'actions': {action_id: self.routes[action_id].capabilities() if action_id in self.routes else {
                'action_id': action_id, 'status': 'unbound', 'reason': 'No actual application submission route configured'}
                for action_id in _ACTIONS},
            'limitations': ['Configured routes are unverified until actual native/private application execution is observed.',
                'Application owns journal cleanup and actual source/authorization locks; no automatic business execution.']}
