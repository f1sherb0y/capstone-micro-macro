"""Durable Owner submission boundary for explicitly supplied application endpoints."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.task_submission import SubmissionRequest, TaskSubmission
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest, _text


@dataclass(frozen=True)
class OwnerSubmissionCallbacks:
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
            raise ValueError('Owner submission requires actual transport and explicit current validators')


# Only original Owner action/table/schema combinations can reach transport.
_ACTIONS = {
    'OWN-A01': 'observation', 'OWN-A02': 'study', 'OWN-A03': 'investment',
    'OWN-A04': 'commission', 'OWN-A05': 'financing', 'OWN-A06': 'payment',
    'OWN-A07': 'design', 'OWN-A08': 'regulatory', 'OWN-A09': 'tender',
    'OWN-A10': 'award', 'OWN-A11': 'contract', 'OWN-A12': 'closeout',
    'OWN-A13': 'continuation', 'OWN-A14': 'asset', 'OWN-A15': 'operating',
    'OWN-A16': 'proposal',
}


class OwnerResultSubmission:
    """Submit an original formal result once through its actual application route.

    Native acceptance confirms the original request's disposition only. Case,
    contract, right, obligation, cash, release and private policy effects need
    their independent native evidence. Construction pins configuration without
    transport; execute/recover/read_receipt are explicit application calls.
    """
    VERSION = 'owner-result-submission.v1'

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks):
        if (not isinstance(worker, OwnerObservationResultWorker) or worker.ACTION_ID not in _ACTIONS
                or worker.ROLE != 'Owner' or worker.store.path is None
                or not isinstance(callbacks, OwnerSubmissionCallbacks)):
            raise ValueError('Owner submission requires its original persistent result worker and actual callbacks')
        module = _ACTIONS[worker.ACTION_ID]
        if worker.RESULT_TABLE != 'owner_' + module + '_results' or worker.SCHEMA != 'owner-' + module + '-result.v1':
            raise ValueError('Owner submission changes the closed original action/table/schema relation')
        for value in (binding_id, binding_version, macro_version):
            _text(value)
        choices = frozenset(supported_choices)
        registration = worker.registry.get(worker.ACTION_ID)
        if (registration.role != 'Owner' or not registration.implemented or registration.skill is None
                or not choices or not choices <= set(registration.contract.choices)):
            raise ValueError('Owner binding must select supported original implemented contract branches')
        self.ACTION_ID = worker.ACTION_ID
        self.RECEIPT_SCHEMA = 'owner-' + module + '-saved-receipt.v1'
        self.worker, self.callbacks = worker, callbacks
        self.binding_id, self.binding_version, self.macro_version = binding_id, binding_version, macro_version
        self.supported_choices = choices
        self._declared = self._configuration()
        self._key = 'owner_' + module + '_submission:' + binding_id
        with worker.store._transaction():
            previous = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if previous is None:
                worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(previous[0]) != self._declared:
                raise TaskConflict('Owner native submission binding changed; no silent restart migration')
        self._submission = TaskSubmission(worker.store, binding_id=binding_id, macro_version=macro_version,
            action_ids={self.ACTION_ID}, submit=self._submit, query=self._query if callbacks.query is not None else None,
            revalidate=self._revalidate, validate_receipt=self._validate_receipt)

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.worker.store.run_id,
            'binding_id': self.binding_id, 'binding_version': self.binding_version,
            'macro_version': self.macro_version, 'action_id': self.ACTION_ID,
            'result_table': self.worker.RESULT_TABLE, 'result_schema': self.worker.SCHEMA,
            'receipt_schema': self.RECEIPT_SCHEMA, 'supported_choices': sorted(self.supported_choices),
            'callbacks': {item.name: module_factory_descriptor(getattr(self.callbacks, item.name), item.name)
                if getattr(self.callbacks, item.name) is not None else None for item in fields(self.callbacks)}}

    def _check_binding(self):
        if (self._configuration() != self._declared or self.worker.ACTION_ID != self.ACTION_ID
                or self.worker.ROLE != 'Owner' or self.worker.snapshots.store is not self.worker.store
                or self._submission.store is not self.worker.store or self._submission.binding_id != self.binding_id
                or self._submission.macro_version != self.macro_version
                or self._submission.action_ids != frozenset({self.ACTION_ID})):
            raise TaskConflict('Owner original submission binding, result worker or journal changed')
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Owner original submission binding evidence is missing or changed')

    def _original(self, identity):
        self._check_binding()
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != 'Owner' or identity.purpose != 'action':
            raise TaskConflict('Owner submission changes the original action, role or purpose')
        record = self.worker.get_record(identity)
        snapshot = self.worker.snapshots.get(identity)
        row = self.worker.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['result']['payload']['choice'] not in self.supported_choices
                or snapshot['context']['execution_mode'] == 'offline_fixture'
                or record['audit'].get('reading', {}).get('source_mode') != 'formal'
                or row['output'] != record['result'] or row['output_sha256'] != record['result_sha256']):
            raise TaskConflict('Owner submission requires its saved completed formal-source supported branch')
        request = SubmissionRequest(identity, deepcopy(record['result']), record['result_sha256'],
            self.binding_id, self.macro_version)
        if row['submission'] is not None and row['submission'] != {
                'binding_id': self.binding_id, 'macro_version': self.macro_version, 'request_id': identity.request_id}:
            raise TaskConflict('Owner task already belongs to another native submission')
        return request, record, snapshot, row

    def _check_request(self, request):
        actual, record, snapshot, _ = self._original(request.identity)
        if request != actual:
            raise TaskConflict('Owner transport changes the original output, task or binding')
        return record, snapshot

    def _revalidate(self, request):
        record, snapshot = self._check_request(request)
        if self.callbacks.validate_submit(deepcopy(request), deepcopy(record), deepcopy(snapshot)) is not True:
            raise TaskConflict('Owner submission requires current facts, business gates and submit authority')
        # Original TaskSubmission's successful revalidation protocol returns None.

    def _submit(self, request):
        self._check_request(request)
        return self.callbacks.submit(deepcopy(request))

    def _query(self, request):
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Owner query requires current own receipt-read authority')
        return self.callbacks.query(deepcopy(request))

    def _validate_receipt(self, request, raw):
        self._check_request(request)
        receipt = self.callbacks.validate_receipt(deepcopy(request), deepcopy(raw))
        if not isinstance(receipt, dict) or receipt.get('original_receipt') != raw:
            raise TaskConflict('Owner receipt must preserve the actual original application reply')
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
                raise TaskConflict('Reading Owner receipt state requires current own authorization')
        return self._submission.recover(identity)

    def capabilities(self):
        self._check_binding()
        choices = self.worker.registry.get(self.ACTION_ID).contract.choices
        return {'schema_version': self.VERSION, 'action_id': self.ACTION_ID,
            'configuration': deepcopy(self._declared), 'configuration_sha256': task_digest(self._declared),
            'submit': {choice: 'configured_unverified' if choice in self.supported_choices else 'unbound'
                for choice in choices},
            'query': 'configured_unverified' if self.callbacks.query is not None else 'unavailable',
            'limitations': ['Application must provide actual endpoints, current source/authorization guard and business validation.',
                'Configuration does not prove a reachable endpoint or native execution.',
                'Request disposition does not prove business effects, actual cash or released obligations.']}

    def read_receipt(self, identity):
        """Read a confirmed original receipt under current authority; no transport."""
        request, record, _, row = self._original(identity)
        if row['state'] != 'reconciled' or row['receipt'] is None:
            raise TaskConflict('Owner receipt has not been confirmed for the original task')
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading saved Owner receipt requires current own receipt-read authority')
        receipt = self._submission._receipt(request, deepcopy(row['receipt']['original_receipt']))
        if receipt != row['receipt']:
            raise TaskConflict('Saved Owner receipt differs from its original protocol evidence')
        if self.worker.store.get(identity) != row:
            raise TaskConflict('Original Owner task changed during authorized receipt reading')
        self._check_binding()
        return {'schema_version': self.RECEIPT_SCHEMA, 'identity': request.identity.as_dict(),
            'record_sha256': record['record_sha256'], 'task_sha256': task_digest(row),
            'binding_configuration_sha256': task_digest(self._declared),
            'receipt': deepcopy(receipt), 'receipt_sha256': task_digest(receipt)}
