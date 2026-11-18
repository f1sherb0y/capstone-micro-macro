"""Shared durable bank submission boundary for explicitly supported native bindings."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable

from integration.bank_intake_results import BankIntakeResultWorker
from integration.module_host import module_factory_descriptor
from integration.task_submission import SubmissionRequest, TaskSubmission
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest, _text


@dataclass(frozen=True)
class BankSubmissionCallbacks:
    """Application supplies actual transport and current submit/receipt-read checks.

    validate_submit(request, record, snapshot) and validate_query(request)
    return True only on current authorization and actual source verification.
    validate_receipt(request, raw) preserves the original native reply in the
    exact TaskSubmission receipt envelope. query(request) is read-only.
    """
    submit: Callable
    validate_submit: Callable
    validate_query: Callable
    validate_receipt: Callable
    query: Callable | None = None

    def __post_init__(self):
        if (not all(callable(getattr(self, item.name)) for item in fields(self) if item.name != 'query')
                or self.query is not None and not callable(self.query)):
            raise ValueError('Bank decision binding requires actual transport and explicit current validators')


class BankResultSubmission:
    """Submit an original formal bank decision once through an application binding.

    A supported completed choice is a local decision, never a native record.
    Native accepted/rejected disposition belongs to that exact submission; it
    does not create a loan or convert missing/technical results into rejection.
    Construction pins configuration only. execute/recover are explicit calls,
    separate from role_contract, which remains a local decision entry point.
    """
    VERSION = None
    ACTION_ID = None
    METADATA_PREFIX = None
    RECEIPT_SCHEMA = None
    RECEIPT_LIMITATION = None

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks):
        if (not isinstance(worker, BankIntakeResultWorker) or worker.ACTION_ID != self.ACTION_ID
                or (self.ACTION_ID, worker.RESULT_TABLE, self.VERSION, self.METADATA_PREFIX, self.RECEIPT_SCHEMA) not in {
                    ('BANK-A01', 'bank_strategy_results', 'bank-strategy-submission.v1', 'bank_strategy_submission:', 'bank-strategy-saved-receipt.v1'),
                    ('BANK-A02', 'bank_intake_results', 'bank-intake-submission.v1', 'bank_intake_submission:', 'bank-intake-saved-receipt.v1'),
                    ('BANK-A03', 'bank_credit_results', 'bank-credit-submission.v1', 'bank_credit_submission:', 'bank-credit-saved-receipt.v1'),
                    ('BANK-A04', 'bank_quote_results', 'bank-quote-submission.v1', 'bank_quote_submission:', 'bank-quote-saved-receipt.v1'),
                    ('BANK-A05', 'bank_arrangement_results', 'bank-arrangement-submission.v1', 'bank_arrangement_submission:', 'bank-arrangement-saved-receipt.v1'),
                    ('BANK-A06', 'bank_draw_results', 'bank-draw-submission.v1', 'bank_draw_submission:', 'bank-draw-saved-receipt.v1'),
                    ('BANK-A07', 'bank_execution_results', 'bank-execution-submission.v1', 'bank_execution_submission:', 'bank-execution-saved-receipt.v1'),
                    ('BANK-A08', 'bank_monitoring_results', 'bank-monitoring-submission.v1', 'bank_monitoring_submission:', 'bank-monitoring-saved-receipt.v1'),
                    ('BANK-A09', 'bank_debt_results', 'bank-debt-submission.v1', 'bank_debt_submission:', 'bank-debt-saved-receipt.v1'),
                    ('BANK-A10', 'bank_resolution_results', 'bank-resolution-submission.v1', 'bank_resolution_submission:', 'bank-resolution-saved-receipt.v1'),
                    ('BANK-A11', 'bank_closeout_results', 'bank-closeout-submission.v1', 'bank_closeout_submission:', 'bank-closeout-saved-receipt.v1'),
                    ('BANK-A12', 'bank_learning_results', 'bank-learning-submission.v1', 'bank_learning_submission:', 'bank-learning-saved-receipt.v1'),
                    ('BANK-A13', 'bank_advice_results', 'bank-advice-submission.v1', 'bank_advice_submission:', 'bank-advice-saved-receipt.v1')}
                or worker.store.path is None
                or worker.ROLE != 'Bank' or not isinstance(callbacks, BankSubmissionCallbacks)):
            raise ValueError('Bank decision submission requires its original action worker and actual host callbacks')
        for value in (binding_id, binding_version, macro_version):
            _text(value)
        choices = frozenset(supported_choices)
        registration = worker.registry.get(self.ACTION_ID)
        if not choices or not choices <= set(registration.contract.choices):
            raise ValueError('Bank binding must explicitly select supported original contract branches')
        self.worker, self.callbacks = worker, callbacks
        self.binding_id, self.binding_version, self.macro_version = binding_id, binding_version, macro_version
        self.supported_choices = choices
        self._declared = self._configuration()
        self._key = self.METADATA_PREFIX + binding_id
        with worker.store._transaction():
            previous = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if previous is None:
                worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(previous[0]) != self._declared:
                raise TaskConflict('Bank decision native binding changed; no silent restart migration')
        self._submission = TaskSubmission(worker.store, binding_id=binding_id, macro_version=macro_version,
            action_ids={self.ACTION_ID}, submit=self._submit, query=self._query if callbacks.query is not None else None,
            revalidate=self._revalidate, validate_receipt=self._validate_receipt)

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.worker.store.run_id,
            'binding_id': self.binding_id, 'binding_version': self.binding_version,
            'macro_version': self.macro_version, 'action_id': self.ACTION_ID,
            'supported_choices': sorted(self.supported_choices),
            'callbacks': {item.name: module_factory_descriptor(getattr(self.callbacks, item.name), item.name)
                if getattr(self.callbacks, item.name) is not None else None for item in fields(self.callbacks)}}

    def _check_binding(self):
        if (self._configuration() != self._declared or self._submission.store is not self.worker.store
                or self._submission.binding_id != self.binding_id or self._submission.macro_version != self.macro_version
                or self._submission.action_ids != frozenset({self.ACTION_ID})):
            raise TaskConflict('Bank decision original native binding or journal changed')
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Bank decision original native binding evidence is missing or changed')

    def _original(self, identity):
        self._check_binding()
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != 'Bank' or identity.purpose != 'action':
            raise TaskConflict('Bank decision submission changes the original action, role or purpose')
        record = self.worker.get_record(identity)
        snapshot = self.worker.snapshots.get(identity)
        row = self.worker.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['result']['payload']['choice'] not in self.supported_choices
                or snapshot['context']['execution_mode'] == 'offline_fixture'
                or record['audit'].get('reading', {}).get('source_mode') != 'formal'
                or row['output'] != record['result'] or row['output_sha256'] != record['result_sha256']):
            raise TaskConflict('Native bank decision submission requires its saved completed formal-source supported branch')
        request = SubmissionRequest(identity, deepcopy(record['result']), record['result_sha256'],
            self.binding_id, self.macro_version)
        if row['submission'] is not None and row['submission'] != {
                'binding_id': self.binding_id, 'macro_version': self.macro_version, 'request_id': identity.request_id}:
            raise TaskConflict('Bank decision task already belongs to another native submission')
        return request, record, snapshot, row

    def _check_request(self, request):
        actual, record, snapshot, _ = self._original(request.identity)
        if request != actual:
            raise TaskConflict('Native bank decision transport changes original output, task or binding')
        return record, snapshot

    def _revalidate(self, request):
        record, snapshot = self._check_request(request)
        if self.callbacks.validate_submit(deepcopy(request), deepcopy(record), deepcopy(snapshot)) is not True:
            raise TaskConflict('Native bank decision submission requires current facts and submit authorization')
        # TaskSubmission's explicit revalidation protocol succeeds with None.

    def _submit(self, request):
        self._check_request(request)
        return self.callbacks.submit(deepcopy(request))

    def _query(self, request):
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Native bank decision query requires current own receipt-read authorization')
        return self.callbacks.query(deepcopy(request))

    def _validate_receipt(self, request, raw):
        self._check_request(request)
        receipt = self.callbacks.validate_receipt(deepcopy(request), deepcopy(raw))
        if not isinstance(receipt, dict) or receipt.get('original_receipt') != raw:
            raise TaskConflict('Native bank decision receipt must preserve the actual original macro reply')
        # Original TaskSubmission verifies the full correlated envelope.
        return receipt

    def execute(self, identity):
        """Explicit submit, or query an already uncertain original submission."""
        _, _, _, row = self._original(identity)
        if row['state'] in {'waiting_receipt', 'receipt_unknown', 'reconciled'}:
            return self.recover(identity)
        return self._submission.execute(identity)

    def recover(self, identity):
        """Query by the original request identity; never submit or rerun the action."""
        request, _, _, row = self._original(identity)
        if row['state'] == 'reconciled' or self.callbacks.query is None:
            if self.callbacks.validate_query(deepcopy(request)) is not True:
                raise TaskConflict('Reading native bank decision receipt state requires current own authorization')
        return self._submission.recover(identity)

    def capabilities(self):
        self._check_binding()
        choices = self.worker.registry.get(self.ACTION_ID).contract.choices
        return {'schema_version': self.VERSION, 'action_id': self.ACTION_ID,
            'configuration': deepcopy(self._declared), 'configuration_sha256': task_digest(self._declared),
            'submit': {choice: 'configured_unverified' if choice in self.supported_choices else 'unbound'
                for choice in choices},
            'query': 'configured_unverified' if self.callbacks.query is not None else 'unavailable',
            'limitations': ['Native application callbacks must provide the actual supported endpoint and original receipt.',
                'Configuration is not evidence of a reachable endpoint or completed native execution.',
                self.RECEIPT_LIMITATION]}

    def read_receipt(self, identity):
        """Read a currently authorized original receipt; never poll or resubmit."""
        request, record, _, row = self._original(identity)
        if row['state'] != 'reconciled' or row['receipt'] is None:
            raise TaskConflict('Native bank decision receipt has not been confirmed for the original task')
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading saved native bank decision receipt requires current own receipt-read authority')
        # Validate the saved envelope against the actual original raw reply,
        # using the same host protocol as live submission/query validation.
        receipt = self._submission._receipt(request, deepcopy(row['receipt']['original_receipt']))
        if receipt != row['receipt']:
            raise TaskConflict('Saved native bank decision receipt differs from its original protocol evidence')
        if self.worker.store.get(identity) != row:
            raise TaskConflict('Original bank decision task changed during authorized receipt reading')
        self._check_binding()
        return {'schema_version': self.RECEIPT_SCHEMA, 'identity': request.identity.as_dict(),
            'record_sha256': record['record_sha256'], 'task_sha256': task_digest(row),
            'binding_configuration_sha256': task_digest(self._declared),
            'receipt': deepcopy(receipt), 'receipt_sha256': task_digest(receipt)}
