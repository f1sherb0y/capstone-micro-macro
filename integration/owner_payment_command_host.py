"""Durable per-command transport for an explicitly registration-only payment route."""
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.owner_payment_submission import OwnerPaymentSubmission
from integration.task_submission import TaskSubmission
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest, _text


@dataclass(frozen=True)
class OwnerPaymentCommandCallbacks:
    """Actual single-command endpoints and independent current validators.

    submit/query receive the original child SubmissionRequest; its output
    retains the full original payment line and component allocations.
    validate_submit(child, parent_record, parent_snapshot) confirms current
    command authority, actual cash/reservations and prior execution business
    gates. validate_query(child) independently checks current own receipt-read
    access. validate_receipt(child, raw) authenticates command/business identity
    and returns TaskSubmission's correlated envelope preserving raw exactly.
    validate_group(parent, record, snapshot, receipt, payment_plan) confirms the
    actual parent endpoint registers only: it never sends any child payment.
    """
    submit: Callable
    query: Callable
    validate_submit: Callable
    validate_query: Callable
    validate_receipt: Callable
    validate_group: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('Native payment commands require actual submit/query and explicit current validators')


class OwnerPaymentCommandHost:
    """Register one original group, then submit each exact child at most once.

    This host is opt-in for an application's declared registration-only route.
    It must not wrap an aggregate endpoint that already executes the payments.
    It uses the original TaskStore for technical command states and immutable
    business claims; it writes no financial ledger. Actual execution and cash
    remain the supplied application's responsibility and independent evidence.
    """
    VERSION = 'owner-payment-command-host.v1'
    COMMAND_SCHEMA = 'owner-payment-native-command.v1'

    def __init__(self, *, submission: OwnerPaymentSubmission, command_binding_id,
            command_binding_version, callbacks: OwnerPaymentCommandCallbacks, read_guard):
        if (not isinstance(submission, OwnerPaymentSubmission)
                or not isinstance(callbacks, OwnerPaymentCommandCallbacks) or not callable(read_guard)):
            raise ValueError('Command host requires original formal payment submission, actual callbacks and current source guard')
        _text(command_binding_id); _text(command_binding_version)
        self.submission, self.store = submission, submission.worker.store
        self.command_binding_id, self.command_binding_version = command_binding_id, command_binding_version
        self.callbacks, self.read_guard = callbacks, read_guard
        self._original_components = (submission, self.store, callbacks, read_guard)
        self._declared = self._configuration()
        self._key = 'owner_payment_command_host:' + command_binding_id
        with self.store._transaction():
            previous = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if previous is None:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(previous[0]) != self._declared:
                raise TaskConflict('Native payment command configuration changed; no silent migration or replay')
        self._transport = TaskSubmission(self.store, binding_id=command_binding_id,
            macro_version=submission.macro_version, action_ids={'OWN-A06'}, submit=self._submit,
            query=self._query, revalidate=self._revalidate, validate_receipt=self._validate_receipt)

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.store.run_id,
            'command_binding_id': self.command_binding_id, 'command_binding_version': self.command_binding_version,
            'parent_configuration': self.submission._configuration(),
            'host': module_factory_descriptor(type(self).submit, self.VERSION),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard'),
            'callbacks': {field.name: module_factory_descriptor(getattr(self.callbacks, field.name), field.name)
                for field in fields(self.callbacks)}}

    def _check(self):
        if (any(current is not original for current, original in zip((self.submission, self.store,
                self.callbacks, self.read_guard), self._original_components))
                or self.submission.worker.store is not self.store or self._configuration() != self._declared
                or self._transport.store is not self.store or self._transport.binding_id != self.command_binding_id
                or self._transport.macro_version != self.submission.macro_version
                or self._transport.action_ids != frozenset({'OWN-A06'})):
            raise TaskConflict('Native command host replaced original journal, parent route or callbacks')
        self.submission._check_binding()
        with self.store._lock:
            saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Native command host configuration evidence changed')

    def _group(self, identity):
        self._check()
        request, record, snapshot, row = self.submission._original(identity)
        if self.submission.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading original payment group requires current own receipt authority')
        if row['state'] != 'reconciled' or row['receipt']['disposition'] != 'accepted':
            raise TaskConflict('Native commands require an independently confirmed accepted group registration')
        receipt = self.submission.read_receipt(identity)['receipt']
        plan = self.submission._payment_plan(record, snapshot)
        if self.callbacks.validate_group(deepcopy(request), deepcopy(record), deepcopy(snapshot),
                deepcopy(receipt), deepcopy(plan)) is not True:
            raise TaskConflict('Actual group registration is not verified registration-only; no child payment may be sent')
        self.submission._check_request(request)
        return request, record, snapshot, receipt, plan

    def _commands(self, request, record, receipt, plan):
        commands = []
        for index, line in enumerate(plan['lines']):
            # A second action request cannot repeat payment under the same
            # original authority, even if available cash changed its partial sum.
            business_key = task_digest({'purpose': self.COMMAND_SCHEMA, 'run_id': request.identity.run_id,
                'organization_id': request.identity.organization_id, 'authorization_ref': plan['authorization_ref'],
                'account_ref': plan['account_ref'], 'obligation_ref': line['obligation_ref'],
                'beneficiary_id': line['payee_id'], 'operation': plan['choice']})
            command_id = task_digest({'parent_identity': request.identity.as_dict(),
                'command_binding_id': self.command_binding_id, 'line_index': index})
            output = {'schema_version': self.COMMAND_SCHEMA, 'command_id': command_id,
                'business_key': business_key, 'line_index': index,
                'source_identity': request.identity.as_dict(), 'source_record_sha256': record['record_sha256'],
                'source_result_sha256': request.output_sha256, 'source_reading_sha256': record['source_reading_sha256'],
                'group_receipt': deepcopy(receipt), 'operation': plan['choice'],
                'authorization_ref': deepcopy(plan['authorization_ref']), 'account_ref': deepcopy(plan['account_ref']),
                'line': deepcopy(line)}
            child = TaskIdentity(run_id=request.identity.run_id, organization_id=request.identity.organization_id,
                role='Owner', action_id='OWN-A06', request_id=command_id, purpose='owner_payment_native_command',
                input_sha256=task_digest(output), context_sha256=request.identity.context_sha256,
                versions=deepcopy(request.identity.versions))
            commands.append((child, output))
        return commands

    def _prepare(self, identity):
        request, record, _, receipt, plan = self._group(identity)
        commands = self._commands(request, record, receipt, plan)
        declared = self._group_declaration(request, record, receipt, commands)
        group_key = self._key + ':group:' + request.identity.key
        # Prepare every child and every business claim atomically. No transport
        # occurs inside this transaction, and a crash cannot leave a half group.
        with self.store._transaction():
            parent_row = self.store._read(request.identity)
            if parent_row['state'] != 'reconciled' or parent_row['receipt'] != receipt:
                raise TaskConflict('Original accepted registration changed before command preparation')
            previous = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (group_key,)).fetchone()
            new_group = previous is None
            if new_group:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (group_key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Original native payment group changed its commands, source or registration receipt')
            for child, output in commands:
                claim_key = 'owner_payment_command_business:' + output['business_key']
                claim = {'identity': child.as_dict(), 'output_sha256': task_digest(output)}
                previous = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (claim_key,)).fetchone()
                if previous is None:
                    if not new_group:
                        raise TaskConflict('Original command business-ownership evidence is missing')
                    self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (claim_key, canonical(claim)))
                elif new_group or json.loads(previous[0]) != claim:
                    raise TaskConflict('Original authority/business payment is already claimed by another command')
                row = self.store._read(child)
                if row is None and not new_group or row is not None and new_group:
                    raise TaskConflict('Native group lost original child history or attempted to recreate an existing command')
                if new_group:
                    row = self.store._ensure_in_transaction(child)
                    row.update(state='output_formed', revision=row['revision'] + 1,
                        output=deepcopy(output), output_sha256=task_digest(output), conditions=[])
                    self.store._write(child, row, 'original_native_command_prepared')
                elif (row['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                        or row['output'] != output or row['output_sha256'] != task_digest(output)):
                    raise TaskConflict('Saved native child changed its original planned command')
        return commands

    @staticmethod
    def _group_declaration(request, record, receipt, commands):
        return {'schema_version': 'owner-payment-command-group.v1', 'parent_identity': request.identity.as_dict(),
            'source_record_sha256': record['record_sha256'], 'group_receipt_sha256': task_digest(receipt),
            'commands': [{'identity': child.as_dict(), 'output_sha256': task_digest(output)} for child, output in commands]}

    def _child(self, request):
        self._check()
        if request.identity.purpose != 'owner_payment_native_command':
            raise TaskConflict('Command transport cannot consume an original action or another technical task')
        parent = TaskIdentity(**request.output['source_identity'])
        original, record, snapshot, receipt, plan = self._group(parent)
        expected = self._commands(original, record, receipt, plan)
        if not any(child == request.identity and output == request.output for child, output in expected):
            raise TaskConflict('Child transport changed original group, account, partial allocation or command identity')
        if request.binding_id != self.command_binding_id or request.macro_version != self.submission.macro_version:
            raise TaskConflict('Native command transport substituted its actual endpoint binding')
        with self.store._lock:
            group_key = self._key + ':group:' + original.identity.key
            group = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (group_key,)).fetchone()
            claim = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                ('owner_payment_command_business:' + request.output['business_key'],)).fetchone()
            if (group is None or json.loads(group[0]) != self._group_declaration(original, record, receipt, expected)
                    or claim is None or json.loads(claim[0]) != {
                        'identity': request.identity.as_dict(), 'output_sha256': request.output_sha256}):
                raise TaskConflict('Native command lost its immutable original group or business ownership')
        return record, snapshot

    def _revalidate(self, request):
        record, snapshot = self._child(request)
        if self.callbacks.validate_submit(deepcopy(request), deepcopy(record), deepcopy(snapshot)) is not True:
            raise TaskConflict('Native child requires current actual cash, reservations and command submit authority')

    def _submit(self, request):
        self._child(request)
        return self.callbacks.submit(deepcopy(request))

    def _query(self, request):
        self._child(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Native command query requires independent current own receipt-read access')
        return self.callbacks.query(deepcopy(request))

    def _validate_receipt(self, request, raw):
        self._child(request)
        receipt = self.callbacks.validate_receipt(deepcopy(request), deepcopy(raw))
        if not isinstance(receipt, dict) or receipt.get('original_receipt') != raw:
            raise TaskConflict('Native command receipt must preserve its original actual application reply')
        return receipt

    def _read_command(self, child):
        row = self.store.get(child)
        request = self._transport._request(child, row)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading command state requires current own receipt-read access')
        if row['state'] == 'reconciled':
            checked = self._transport._receipt(request, deepcopy(row['receipt']['original_receipt']))
            if checked != row['receipt']:
                raise TaskConflict('Saved child receipt changed its original authenticated evidence')
        if self.store.get(child) != row:
            raise TaskConflict('Original native command changed during authorized state reading')
        return row

    def _summary(self, identity, commands):
        request, _, _, _ = self.submission._original(identity)
        if self.submission.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading native payment progress requires current own parent receipt authority')
        rows = [deepcopy(self._read_command(child)) for child, _ in commands]
        self._check()
        return {'schema_version': self.VERSION, 'source_identity': identity.as_dict(),
            'configuration_sha256': task_digest(self._declared), 'parent_task': self.store.get(identity),
            'commands': rows, 'command_receipts_confirmed': bool(rows) and all(row['state'] == 'reconciled' for row in rows),
            'limitations': ['Command acceptance/rejection is separate from actual execution and native cash/debt reconciliation.']}

    def submit(self, identity):
        """Explicitly register the group and send untouched commands in original order.

        Existing uncertain children are queried first. If any remain unknown,
        stop before starting another child. A concurrent writer losing a revision
        check cannot send a duplicate. Each untouched child gets fresh validation.
        """
        identity = TaskIdentity(**identity.as_dict())
        with self.read_guard(identity):
            self._check()
            row = self.submission.execute(identity)
            if row['state'] != 'reconciled' or row['receipt']['disposition'] != 'accepted':
                return self._summary(identity, [])
            commands = self._prepare(identity)
            for child, _ in commands:
                row = self._read_command(child)
                if row['state'] in {'waiting_receipt', 'receipt_unknown'}:
                    row = self._transport.recover(child)
                    if row['state'] != 'reconciled':
                        return self._summary(identity, commands)
            for child, _ in commands:
                row = self._read_command(child)
                if row['state'] == 'output_formed':
                    row = self._transport.execute(child)
                    if row['state'] != 'reconciled':
                        break
            return self._summary(identity, commands)

    def recover(self, identity):
        """Query uncertainty only; never register a group or send an untouched child.

        An accepted group interrupted before local preparation may have its
        deterministic technical child rows prepared here, without any transport.
        """
        identity = TaskIdentity(**identity.as_dict())
        with self.read_guard(identity):
            self._check()
            request, _, _, row = self.submission._original(identity)
            if self.submission.callbacks.validate_query(deepcopy(request)) is not True:
                raise TaskConflict('Recovering original payment group requires current own receipt-read authority')
            if row['submission'] is None:
                return self._summary(identity, [])
            row = self.submission.recover(identity)
            if row['state'] != 'reconciled' or row['receipt']['disposition'] != 'accepted':
                return self._summary(identity, [])
            commands = self._prepare(identity)
            for child, _ in commands:
                if self._read_command(child)['state'] in {'waiting_receipt', 'receipt_unknown'}:
                    self._transport.recover(child)
            return self._summary(identity, commands)

    def read_progress(self, identity):
        """Read original existing command rows; no transport or preparation writes."""
        identity = TaskIdentity(**identity.as_dict())
        with self.read_guard(identity):
            return self._read_progress_guarded(identity)

    def _read_progress_guarded(self, identity):
        """Internal read; caller holds this host's original read_guard(identity).

        Keep all original query, journal and receipt checks. This helper only
        avoids acquiring the same potentially non-reentrant source lock twice.
        """
        identity = TaskIdentity(**identity.as_dict())
        self._check()
        request, record, _, row = self.submission._original(identity)
        if self.submission.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Reading native command progress requires current own group receipt authority')
        with self.store._lock:
            group = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
                (self._key + ':group:' + identity.key,)).fetchone()
        if group is None:
            return self._summary(identity, [])
        request, record, _, receipt, plan = self._group(identity)
        commands = self._commands(request, record, receipt, plan)
        if json.loads(group[0]) != self._group_declaration(request, record, receipt, commands):
            raise TaskConflict('Saved native command progress changed its original group declaration')
        for child, _ in commands:
            child_row = self.store.get(child)
            self._child(self._transport._request(child, child_row))
        return self._summary(identity, commands)
