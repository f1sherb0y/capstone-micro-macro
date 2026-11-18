"""Explicit Owner submission routes over the original persistent result workers."""
from copy import deepcopy
import importlib
import json
from types import MappingProxyType
from typing import Literal

from integration.module_host import module_factory_descriptor
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.owner_payment_submission import OwnerPaymentSubmission
from integration.owner_payment_settlement import OwnerPaymentSettlementReconciler
from integration.owner_role_contract_host import _ACTIONS
from integration.owner_submission import OwnerResultSubmission, OwnerSubmissionCallbacks
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest


class OwnerSubmissionRoute(StrictRecord):
    action_id: TextId
    binding_id: TextId
    binding_version: TextId
    macro_version: TextId
    supported_choices: list[TextId]
    native_payment_execution: bool = False
    native_payment_settlement: bool = False


class OwnerSubmissionHostConfiguration(StrictRecord):
    schema_version: Literal['owner-submission-host-config.v1']
    host_id: TextId
    version: TextId
    routes: list[OwnerSubmissionRoute]


class OwnerSubmissionHost:
    """Assemble declared application routes; submit and receipt reads are explicit.

    All workers and snapshots share the original registry/persistent journal.
    Application read_guard(identity) holds current sources and authorization.
    The application owns cleanup, real endpoints and action-specific validation.
    role_contract produces local decisions without automatically submitting them.
    """
    VERSION = 'owner-submission-host.v1'

    def __init__(self, *, store, registry, workers, callbacks, read_guard, configuration,
            read_native_payment_execution=None, read_native_payment_settlement=None,
            validate_native_payment_settlement=None):
        config = OwnerSubmissionHostConfiguration.model_validate(configuration).model_copy(deep=True)
        actions = [route.action_id for route in config.routes]
        bindings = [route.binding_id for route in config.routes]
        if (not isinstance(store, TaskStore) or store.path is None or not isinstance(registry, ActionRegistry)
                or not isinstance(workers, dict) or not isinstance(callbacks, dict) or not callable(read_guard)
                or len(set(actions)) != len(actions) or len(set(bindings)) != len(bindings)
                or not set(actions) <= set(_ACTIONS) or set(workers) != set(actions) or set(callbacks) != set(actions)):
            raise ValueError('Owner submission host requires unique explicit routes and original persistent components')
        native_routes = [route for route in config.routes if route.native_payment_execution]
        if (any(route.action_id != 'OWN-A06' or not route.supported_choices
                    or not set(route.supported_choices) <= {'pay', 'repay'} for route in native_routes)
                or native_routes and not callable(read_native_payment_execution)
                or not native_routes and read_native_payment_execution is not None):
            raise ValueError('Native payment observation requires an explicit OWN-A06 pay/repay route and actual reader')
        settlement_routes = [route for route in config.routes if route.native_payment_settlement]
        settlement_callbacks = (read_native_payment_settlement, validate_native_payment_settlement)
        if (any(not route.native_payment_execution for route in settlement_routes)
                or settlement_routes and not all(callable(callback) for callback in settlement_callbacks)
                or not settlement_routes and any(callback is not None for callback in settlement_callbacks)):
            raise ValueError('Native payment settlement requires an enabled execution route and actual reader/validator')
        for route in config.routes:
            worker, callback = workers[route.action_id], callbacks[route.action_id]
            module, name = _ACTIONS[route.action_id]
            worker_type = getattr(importlib.import_module('integration.owner_' + module + '_results'),
                'Owner' + name + 'ResultWorker')
            registration = registry.get(route.action_id)
            if (not isinstance(worker, OwnerObservationResultWorker) or not isinstance(worker, worker_type)
                    or worker.ACTION_ID != route.action_id or worker.ROLE != 'Owner' or worker.store is not store
                    or worker.snapshots.store is not store or worker.registry is not registry
                    or not isinstance(callback, OwnerSubmissionCallbacks)
                    or registration.role != 'Owner' or not registration.implemented or registration.skill is None
                    or not route.supported_choices
                    or len(set(route.supported_choices)) != len(route.supported_choices)
                    or not set(route.supported_choices) <= set(registration.contract.choices)
                    or route.action_id == 'OWN-A06' and 'reconcile' in route.supported_choices and callback.query is None
                    or route.native_payment_execution and callback.query is None
                    or route.action_id == 'OWN-A14' and 'reconcile_receipt' in route.supported_choices and callback.query is None):
                raise ValueError('Owner route requires its original worker, journal, branches and actual callbacks; reconciliation needs query')
        self.store, self.registry, self.read_guard = store, registry, read_guard
        self.configuration = config
        self.workers = MappingProxyType(dict(workers))
        self.callbacks = MappingProxyType(dict(callbacks))
        routes = {}
        for route in config.routes:
            arguments = dict(worker=workers[route.action_id], binding_id=route.binding_id,
                binding_version=route.binding_version, macro_version=route.macro_version,
                supported_choices=route.supported_choices, callbacks=callbacks[route.action_id])
            routes[route.action_id] = (OwnerPaymentSubmission(**arguments,
                read_native_execution=read_native_payment_execution) if route.native_payment_execution
                else OwnerResultSubmission(**arguments))
        self.routes = MappingProxyType(routes)
        self.payment_settlements = MappingProxyType({route.action_id: OwnerPaymentSettlementReconciler(
            submission=routes[route.action_id], read_native_settlement=read_native_payment_settlement,
            validate_native_settlement=validate_native_payment_settlement) for route in settlement_routes})
        self._original_payment_settlements = tuple(self.payment_settlements.items())
        self._declared = self._configuration()
        self._key = 'owner_submission_host:' + config.host_id
        with store._transaction():
            prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original Owner submission host configuration or code changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration': self.configuration.model_dump(mode='json'),
            'host': module_factory_descriptor(type(self).submit, self.VERSION),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard'),
            'native_payment_settlements': {action_id: {
                'schema_version': reconciler.VERSION,
                'query': module_factory_descriptor(type(reconciler).query, 'query_payment_settlement'),
                'reader': module_factory_descriptor(reconciler.read_native_settlement, 'read_native_payment_settlement'),
                'validator': module_factory_descriptor(reconciler.validate_native_settlement, 'validate_native_payment_settlement')}
                for action_id, reconciler in sorted(self.payment_settlements.items())},
            'routes': {action_id: {'binding': route._configuration(),
                'execution': module_factory_descriptor(route.execute, action_id),
                'transport': module_factory_descriptor(route._submit, action_id),
                'worker': {'table': self.workers[action_id].RESULT_TABLE,
                    'client_version': self.workers[action_id].client_version,
                    'model_version': self.workers[action_id].model_version}}
                for action_id, route in sorted(self.routes.items())}}

    def _check(self):
        if (len(self.payment_settlements) != len(self._original_payment_settlements)
                or any(self.payment_settlements.get(action_id) is not original
                    for action_id, original in self._original_payment_settlements)):
            raise TaskConflict('Owner native settlement replaced its original reconciler')
        if self._configuration() != self._declared:
            raise TaskConflict('Owner submission host routes, configuration or actual code changed')
        for action_id, route in self.routes.items():
            worker = self.workers[action_id]
            if (route.worker is not worker or worker.store is not self.store or worker.snapshots.store is not self.store
                    or worker.registry is not self.registry or worker.ACTION_ID != action_id
                    or route.callbacks is not self.callbacks[action_id]):
                raise TaskConflict('Owner submission route substituted its original components')
            route._check_binding()
        for action_id, reconciler in self.payment_settlements.items():
            if reconciler.submission is not self.routes[action_id]:
                raise TaskConflict('Owner native settlement replaced its original payment route')
            reconciler._check()
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Owner submission host evidence is missing or changed')

    def _dispatch(self, identity, operation):
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if (identity.run_id != self.store.run_id or identity.organization_id not in self.store.organization_ids
                or identity.role != 'Owner' or identity.purpose != 'action' or identity.action_id not in self.routes):
            raise TaskConflict('Owner submission requires its configured own original task and action route')
        with self.read_guard(TaskIdentity(**identity.as_dict())):
            return self._dispatch_guarded(identity, operation)

    def _dispatch_guarded(self, identity, operation):
        """Caller holds the actual source/authorization boundary for identity."""
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if (identity.run_id != self.store.run_id or identity.organization_id not in self.store.organization_ids
                or identity.role != 'Owner' or identity.purpose != 'action' or identity.action_id not in self.routes):
            raise TaskConflict('Owner submission requires its configured own original task and action route')
        result = (self.payment_settlements[identity.action_id].query(identity)
            if operation == 'query_payment_settlement'
            else getattr(self.routes[identity.action_id], operation)(identity))
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

    def _read_receipt_guarded(self, identity):
        """Internal receipt read under an already-held original source boundary.

        The boundary must protect current receipt authority for this original
        identity. All route, task, saved-receipt and validate_query checks stay
        in place; this helper only avoids acquiring the same source lock twice.
        """
        return self._dispatch_guarded(identity, 'read_receipt')

    def query_payment_execution(self, identity):
        """Observe original pay/repay commands under the configured source guard."""
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if identity.action_id != 'OWN-A06' or not isinstance(self.routes.get('OWN-A06'), OwnerPaymentSubmission):
            raise TaskConflict('Native payment query requires the explicitly configured original payment route')
        return self._dispatch(identity, 'query_execution')

    def query_payment_settlement(self, identity):
        """Read independently verified native balances/postings; never post funds."""
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        if identity.action_id != 'OWN-A06' or identity.action_id not in self.payment_settlements:
            raise TaskConflict('Native payment settlement requires its explicitly configured original reconciler')
        return self._dispatch(identity, 'query_payment_settlement')

    def capabilities(self):
        self._check()
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'configuration_sha256': task_digest(self._declared),
            'native_payment_settlement_actions': sorted(self.payment_settlements),
            'actions': {action_id: self.routes[action_id].capabilities() if action_id in self.routes else {
                'action_id': action_id, 'status': 'unbound', 'reason': 'No actual application submission route configured'}
                for action_id in _ACTIONS},
            'limitations': ['Configured routes remain unverified until actual native/private application execution is observed.',
                'Application owns real sources, business gates, locks and cleanup; no automatic execution or inferred effects.']}
