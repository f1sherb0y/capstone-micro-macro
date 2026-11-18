"""Durable Government submission boundary for explicitly supplied application endpoints."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.government_advice_results import GovernmentAdviceResultWorker
from integration.government_role_contract_host import _ACTIONS as _ROLE_ACTIONS
from integration.task_submission import SubmissionRequest, TaskSubmission
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest, _text


@dataclass(frozen=True)
class GovernmentSubmissionCallbacks:
    """Actual transport and current application checks; query is read-only.

    validate_submit(request, record, snapshot) verifies original sources, current
    authority and action-specific business gates, returning True. validate_query
    checks current own receipt-read authority independently of submit authority.
    validate_receipt(request, raw) returns TaskSubmission's correlated envelope
    preserving raw as original_receipt. The application holds its source guard.
    """
    submit: Callable
    validate_submit: Callable
    validate_query: Callable
    validate_receipt: Callable
    query: Callable | None = None

    def __post_init__(self):
        if (not all(callable(getattr(self, item.name)) for item in fields(self) if item.name != 'query')
                or self.query is not None and not callable(self.query)):
            raise ValueError('Government submission requires actual transport and explicit current validators')


# Only original Government action/table/schema combinations can reach transport.
_ACTIONS = {action_id: route[0] for action_id, route in _ROLE_ACTIONS.items()}


def _worker_metadata(worker, action_id):
    if action_id not in _ACTIONS:
        raise ValueError('Government submission requires an explicit supported action')
    if (not isinstance(worker, GovernmentAdviceResultWorker) or worker.ACTION_ID != action_id
            or worker.ROLE != 'Government'):
        raise ValueError('Government submission requires its original action result worker')
    return worker.registry, worker.RESULT_TABLE, worker.SCHEMA


class GovernmentResultSubmission:
    """Submit an original formal result once through its actual application route.

    Native acceptance confirms the original request's disposition only. Actual
    case registration, assignments, disclosure/delivery, signed decisions, permit
    effects, measures, issue closure and policy publication require independent
    native evidence. validate_submit must bind the original native command or
    business identity and current action-specific authority; A11 use proposals
    retain the independent A07 signing route and A10 supervision obligations.
    Construction pins configuration without transport. Execution, recovery and
    receipt reading are explicit application calls; unknown requests are queried.
    """
    VERSION = 'government-result-submission.v1'

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks,
            action_id=None):
        action_id = action_id if action_id is not None else getattr(worker, 'ACTION_ID', None)
        registry, table, schema = _worker_metadata(worker, action_id)
        if (worker.store.path is None or worker.snapshots.store is not worker.store
                or not isinstance(callbacks, GovernmentSubmissionCallbacks)):
            raise ValueError('Government submission requires its original persistent worker and actual callbacks')
        module = _ACTIONS[action_id]
        expected = ('government_' + module + '_results', 'government-' + module.replace('_', '-') + '-result.v1')
        if (table, schema) != expected:
            raise ValueError('Government submission changes the closed original action/table/schema relation')
        self.registry, self.RESULT_TABLE, self.RESULT_SCHEMA = registry, table, schema
        for value in (binding_id, binding_version, macro_version):
            _text(value)
        choices = frozenset(supported_choices)
        registration = registry.get(action_id)
        if (registration.role != 'Government' or not registration.implemented or registration.skill is None
                or not choices or not choices <= set(registration.contract.choices)):
            raise ValueError('Government binding must select supported original implemented contract branches')
        self.ACTION_ID = action_id
        self.RECEIPT_SCHEMA = 'government-' + module.replace('_', '-') + '-saved-receipt.v1'
        self.worker, self.callbacks = worker, callbacks
        self._original_components = (worker, worker.store, worker.snapshots, registry, callbacks)
        self.binding_id, self.binding_version, self.macro_version = binding_id, binding_version, macro_version
        self.supported_choices = choices
        self._declared = self._configuration()
        self._key = 'government_' + module + '_submission:' + binding_id
        with worker.store._transaction():
            previous = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if previous is None:
                worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(previous[0]) != self._declared:
                raise TaskConflict('Government native submission binding changed; no silent restart migration')
        self._submission = TaskSubmission(worker.store, binding_id=binding_id, macro_version=macro_version,
            action_ids={self.ACTION_ID}, submit=self._submit, query=self._query if callbacks.query is not None else None,
            revalidate=self._revalidate, validate_receipt=self._validate_receipt)

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.worker.store.run_id,
            'binding_id': self.binding_id, 'binding_version': self.binding_version,
            'macro_version': self.macro_version, 'action_id': self.ACTION_ID,
            'result_table': self.RESULT_TABLE, 'result_schema': self.RESULT_SCHEMA,
            'receipt_schema': self.RECEIPT_SCHEMA, 'supported_choices': sorted(self.supported_choices),
            'callbacks': {item.name: module_factory_descriptor(getattr(self.callbacks, item.name), item.name)
                if getattr(self.callbacks, item.name) is not None else None for item in fields(self.callbacks)}}

    def _check_binding(self):
        current = (self.worker, self.worker.store, self.worker.snapshots, self.registry, self.callbacks)
        if any(actual is not original for actual, original in zip(current, self._original_components)):
            raise TaskConflict('Government original submission components changed')
        if (self._configuration() != self._declared
                or _worker_metadata(self.worker, self.ACTION_ID) != (self.registry, self.RESULT_TABLE, self.RESULT_SCHEMA)
                or self.worker.snapshots.store is not self.worker.store
                or self._submission.store is not self.worker.store or self._submission.binding_id != self.binding_id
                or self._submission.macro_version != self.macro_version
                or self._submission.action_ids != frozenset({self.ACTION_ID})):
            raise TaskConflict('Government original submission binding, result worker or journal changed')
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Government original submission binding evidence is missing or changed')

    def _original(self, identity):
        self._check_binding()
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != 'Government' or identity.purpose != 'action':
            raise TaskConflict('Government submission changes the original action, role or purpose')
        record = self.worker.get_record(identity)
        snapshot = self.worker.snapshots.get(identity)
        row = self.worker.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['result']['payload']['choice'] not in self.supported_choices
                or snapshot['context']['execution_mode'] == 'offline_fixture'
                or record['audit'].get('reading', {}).get('source_mode') != 'formal'
                or row['output'] != record['result'] or row['output_sha256'] != record['result_sha256']):
            raise TaskConflict('Government submission requires its saved completed formal-source supported branch')
        request = SubmissionRequest(identity, deepcopy(record['result']), record['result_sha256'],
            self.binding_id, self.macro_version)
        if row['submission'] is not None and row['submission'] != {
                'binding_id': self.binding_id, 'macro_version': self.macro_version, 'request_id': identity.request_id}:
            raise TaskConflict('Government task already belongs to another native submission')
        return request, record, snapshot, row

    def _check_request(self, request):
        actual, record, snapshot, _ = self._original(request.identity)
        if request != actual:
            raise TaskConflict('Government transport changes the original output, task or binding')
        return record, snapshot

    def _revalidate(self, request):
        record, snapshot = self._check_request(request)
        if self.callbacks.validate_submit(deepcopy(request), deepcopy(record), deepcopy(snapshot)) is not True:
            raise TaskConflict('Government submission requires current facts, business gates and submit authority')
        # Original TaskSubmission's successful revalidation protocol returns None.

    def _submit(self, request):
        self._check_request(request)
        return self.callbacks.submit(deepcopy(request))

    def _query(self, request):
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Government query requires current own receipt-read authority')
        return self.callbacks.query(deepcopy(request))

    def _validate_receipt(self, request, raw):
        self._check_request(request)
        receipt = self.callbacks.validate_receipt(deepcopy(request), deepcopy(raw))
        if not isinstance(receipt, dict) or receipt.get('original_receipt') != raw:
            raise TaskConflict('Government receipt must preserve the actual original application reply')
        return receipt

    def execute(self, identity):
        """Explicitly submit once, or query an already uncertain original request."""
        _, _, _, row = self._original(identity)
        if row['state'] in {'waiting_receipt', 'receipt_unknown', 'reconciled'}:
            return self.recover(identity)
        return self._submission.execute(identity)

    def recover(self, identity):
        """Query the original identity; never submit or rerun the action."""
        request, _, _, row = self._original(identity)
        if row['state'] == 'reconciled' or self.callbacks.query is None:
            if self.callbacks.validate_query(deepcopy(request)) is not True:
                raise TaskConflict('Reading Government receipt state requires current own authorization')
        return self._submission.recover(identity)

    def capabilities(self):
        self._check_binding()
        choices = self.registry.get(self.ACTION_ID).contract.choices
        return {'schema_version': self.VERSION, 'action_id': self.ACTION_ID,
            'configuration': deepcopy(self._declared), 'configuration_sha256': task_digest(self._declared),
            'submit': {choice: 'configured_unverified' if choice in self.supported_choices else 'unbound'
                for choice in choices},
            'query': 'configured_unverified' if self.callbacks.query is not None else 'unavailable',
            'limitations': ['Application must provide actual endpoints, current source/authorization guard and business validation.',
                'Configuration does not prove a reachable endpoint or native execution.',
                'Request disposition does not prove case registration, assignments, actual disclosure/delivery, signed decisions, permit effect, measures, issue closure, policy publication or cleared obligations.']}

    def read_receipt(self, identity):
        """Read a confirmed original receipt under current authority; no transport."""
        request, record, _, row = self._original(identity)
        if row['state'] != 'reconciled' or row['receipt'] is None:
            raise TaskConflict('Government receipt has not been confirmed for the original task')
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading saved Government receipt requires current own receipt-read authority')
        receipt = self._submission._receipt(request, deepcopy(row['receipt']['original_receipt']))
        if receipt != row['receipt']:
            raise TaskConflict('Saved Government receipt differs from its original protocol evidence')
        if self.worker.store.get(identity) != row:
            raise TaskConflict('Original Government task changed during authorized receipt reading')
        self._check_binding()
        return {'schema_version': self.RECEIPT_SCHEMA, 'identity': request.identity.as_dict(),
            'record_sha256': record['record_sha256'], 'task_sha256': task_digest(row),
            'binding_configuration_sha256': task_digest(self._declared),
            'receipt': deepcopy(receipt), 'receipt_sha256': task_digest(receipt)}
