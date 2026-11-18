"""Durable Contractor submission boundary for explicitly supplied application endpoints."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.commercial_worker import CommercialTaskWorker
from integration.task_submission import SubmissionRequest, TaskSubmission
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest, _text


@dataclass(frozen=True)
class ContractorSubmissionCallbacks:
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
            raise ValueError('Contractor submission requires actual transport and explicit current validators')


# Only original Contractor action/table/schema combinations can reach transport.
_ACTIONS = {
    'CONTRACTOR-A01': 'screening', 'CONTRACTOR-A02': 'bid',
    'CONTRACTOR-A03': 'amendment', 'CONTRACTOR-A04': 'formation',
    'CONTRACTOR-A05': 'planning', 'CONTRACTOR-A06': 'readiness',
    'CONTRACTOR-A07': 'execution', 'CONTRACTOR-A08': 'quality',
    'CONTRACTOR-A09': 'claim', 'CONTRACTOR-A10': 'payment',
    'CONTRACTOR-A11': 'closeout', 'CONTRACTOR-A12': 'commercial',
    'CONTRACTOR-A13': 'advice',
}


def _worker_metadata(worker, action_id):
    if action_id not in _ACTIONS:
        raise ValueError('Contractor submission requires an explicit supported action')
    if action_id == 'CONTRACTOR-A12':
        if not isinstance(worker, CommercialTaskWorker):
            raise ValueError('Contractor A12 requires its existing commercial worker')
        return worker.assembler.registry, 'commercial_action_results', worker.SCHEMA
    if (not isinstance(worker, ContractorBidResultWorker) or worker.ACTION_ID != action_id
            or worker.ROLE != 'Contractor'):
        raise ValueError('Contractor submission requires its original action result worker')
    return worker.registry, worker.RESULT_TABLE, worker.SCHEMA


class ContractorResultSubmission:
    """Submit an original formal result once through its actual application route.

    Native acceptance confirms the original request's disposition only. Contract,
    release, physical work, obligation, cash and private policy effects need
    their independent native evidence. Construction pins configuration without
    transport; execute/recover/read_receipt are explicit application calls.
    """
    VERSION = 'contractor-result-submission.v1'

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks,
            action_id=None):
        action_id = action_id if action_id is not None else getattr(worker, 'ACTION_ID', None)
        registry, table, schema = _worker_metadata(worker, action_id)
        if (worker.store.path is None or worker.snapshots.store is not worker.store
                or not isinstance(callbacks, ContractorSubmissionCallbacks)):
            raise ValueError('Contractor submission requires its original persistent worker and actual callbacks')
        module = _ACTIONS[action_id]
        expected = ('commercial_action_results', 'commercial-worker-result.v1') if action_id == 'CONTRACTOR-A12' else (
            'contractor_' + module + '_results', 'contractor-' + module + '-result.v1')
        if (table, schema) != expected:
            raise ValueError('Contractor submission changes the closed original action/table/schema relation')
        self.registry, self.RESULT_TABLE, self.RESULT_SCHEMA = registry, table, schema
        for value in (binding_id, binding_version, macro_version):
            _text(value)
        choices = frozenset(supported_choices)
        registration = registry.get(action_id)
        if (registration.role != 'Contractor' or not registration.implemented or registration.skill is None
                or not choices or not choices <= set(registration.contract.choices)):
            raise ValueError('Contractor binding must select supported original implemented contract branches')
        self.ACTION_ID = action_id
        self.RECEIPT_SCHEMA = 'contractor-' + module + '-saved-receipt.v1'
        self.worker, self.callbacks = worker, callbacks
        self._original_components = (worker, worker.store, worker.snapshots, registry, callbacks)
        self.binding_id, self.binding_version, self.macro_version = binding_id, binding_version, macro_version
        self.supported_choices = choices
        self._declared = self._configuration()
        self._key = 'contractor_' + module + '_submission:' + binding_id
        with worker.store._transaction():
            previous = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if previous is None:
                worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(previous[0]) != self._declared:
                raise TaskConflict('Contractor native submission binding changed; no silent restart migration')
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
            raise TaskConflict('Contractor original submission components changed')
        if (self._configuration() != self._declared
                or _worker_metadata(self.worker, self.ACTION_ID) != (self.registry, self.RESULT_TABLE, self.RESULT_SCHEMA)
                or self.worker.snapshots.store is not self.worker.store
                or self._submission.store is not self.worker.store or self._submission.binding_id != self.binding_id
                or self._submission.macro_version != self.macro_version
                or self._submission.action_ids != frozenset({self.ACTION_ID})):
            raise TaskConflict('Contractor original submission binding, result worker or journal changed')
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Contractor original submission binding evidence is missing or changed')

    def _original(self, identity):
        self._check_binding()
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != 'Contractor' or identity.purpose != 'action':
            raise TaskConflict('Contractor submission changes the original action, role or purpose')
        record = self.worker._saved(identity) if self.ACTION_ID == 'CONTRACTOR-A12' else self.worker.get_record(identity)
        snapshot = self.worker.snapshots.get(identity)
        row = self.worker.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['result']['payload']['choice'] not in self.supported_choices
                or snapshot['context']['execution_mode'] == 'offline_fixture'
                or record['audit'].get('reading', {}).get('source_mode') != 'formal'
                or row['output'] != record['result'] or row['output_sha256'] != record['result_sha256']):
            raise TaskConflict('Contractor submission requires its saved completed formal-source supported branch')
        request = SubmissionRequest(identity, deepcopy(record['result']), record['result_sha256'],
            self.binding_id, self.macro_version)
        if row['submission'] is not None and row['submission'] != {
                'binding_id': self.binding_id, 'macro_version': self.macro_version, 'request_id': identity.request_id}:
            raise TaskConflict('Contractor task already belongs to another native submission')
        return request, record, snapshot, row

    def _check_request(self, request):
        actual, record, snapshot, _ = self._original(request.identity)
        if request != actual:
            raise TaskConflict('Contractor transport changes the original output, task or binding')
        return record, snapshot

    def _revalidate(self, request):
        record, snapshot = self._check_request(request)
        if self.callbacks.validate_submit(deepcopy(request), deepcopy(record), deepcopy(snapshot)) is not True:
            raise TaskConflict('Contractor submission requires current facts, business gates and submit authority')
        # Original TaskSubmission's successful revalidation protocol returns None.

    def _submit(self, request):
        self._check_request(request)
        return self.callbacks.submit(deepcopy(request))

    def _query(self, request):
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Contractor query requires current own receipt-read authority')
        return self.callbacks.query(deepcopy(request))

    def _validate_receipt(self, request, raw):
        self._check_request(request)
        receipt = self.callbacks.validate_receipt(deepcopy(request), deepcopy(raw))
        if not isinstance(receipt, dict) or receipt.get('original_receipt') != raw:
            raise TaskConflict('Contractor receipt must preserve the actual original application reply')
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
                raise TaskConflict('Reading Contractor receipt state requires current own authorization')
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
                'Request disposition does not prove business effects, actual cash or released obligations.']}

    def read_receipt(self, identity):
        """Read a confirmed original receipt under current authority; no transport."""
        request, record, _, row = self._original(identity)
        if row['state'] != 'reconciled' or row['receipt'] is None:
            raise TaskConflict('Contractor receipt has not been confirmed for the original task')
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading saved Contractor receipt requires current own receipt-read authority')
        receipt = self._submission._receipt(request, deepcopy(row['receipt']['original_receipt']))
        if receipt != row['receipt']:
            raise TaskConflict('Saved Contractor receipt differs from its original protocol evidence')
        if self.worker.store.get(identity) != row:
            raise TaskConflict('Original Contractor task changed during authorized receipt reading')
        self._check_binding()
        return {'schema_version': self.RECEIPT_SCHEMA, 'identity': request.identity.as_dict(),
            'record_sha256': record['record_sha256'], 'task_sha256': task_digest(row),
            'binding_configuration_sha256': task_digest(self._declared),
            'receipt': deepcopy(receipt), 'receipt_sha256': task_digest(receipt)}
