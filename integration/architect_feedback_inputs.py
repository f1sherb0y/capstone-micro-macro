"""Explicitly link own persisted architect feedback to a new authorized invocation."""
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import re

import importlib

from integration.architect_role_contract_host import _ACTIONS, _build_input
from integration.architect_submission import _worker_metadata
from integration.architect_submission_feedback import ArchitectSubmissionFeedback
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


@dataclass(frozen=True)
class PreparedArchitectFeedbackInput:
    identity: TaskIdentity
    prepared: object
    provenance: dict


class ArchitectFeedbackInputAssembler:
    """Prepare and register one explicit input; never run or submit it.

    The application supplies read_guard(context) and validate_current, which
    verifies the actual feedback/current-input business relation. Feedback is
    historical evidence, not a replacement for independently supplied sources.
    The original snapshot helper commits task, input and provenance together.
    Cross-scope case/project relations require actual application validation;
    no design acceptance, permission, use release, fee, cash or applied learning
    is inferred from a receipt. All actions retain original snapshot registration.
    """
    VERSION = 'architect-feedback-input.v2'

    def __init__(self, *, assembler, worker, feedback, version, read_guard, validate_current, action_id=None):
        action_id = action_id if action_id is not None else getattr(worker, 'ACTION_ID', None)
        registry, _, _ = _worker_metadata(worker, action_id)
        module, name = _ACTIONS[action_id]
        assembler_type = getattr(
            importlib.import_module('integration.architect_' + module + '_actions'),
            'Architect' + name + 'ActionAssembler')
        if (not isinstance(assembler, assembler_type) or assembler.ACTION_ID != action_id or assembler.source_mode != 'formal'
                or not isinstance(feedback, ArchitectSubmissionFeedback)
                or worker.store is not feedback.host.store or worker.snapshots.store is not worker.store
                or assembler.registry is not registry or registry is not feedback.host.registry
                or assembler.organizations.run_id != worker.store.run_id
                or not isinstance(version, str) or not version.strip()
                or not callable(read_guard) or not callable(validate_current)):
            raise ValueError('Architect feedback inputs require original formal assembler, journal and validators')
        self.ACTION_ID, self.registry = action_id, registry
        self.assembler, self.worker, self.feedback = assembler, worker, feedback
        self.version, self.read_guard, self.validate_current = version, read_guard, validate_current
        self._components = (assembler, worker, feedback, assembler.registry, assembler.organizations,
            self._view().provider, worker.store, worker.snapshots)
        self._declared = self._configuration()
        self._key = 'architect_feedback_inputs:' + feedback.host.configuration.host_id + ':' + self.ACTION_ID
        with worker.store._transaction():
            prior = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original feedback-input configuration changed; explicit review required')

    def _view(self):
        return self.assembler._views

    def _identity(self, prepared):
        return self.worker._prepared_identity(prepared, request_id=prepared.context.operation_id, purpose='action')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'version': self.version, 'action_id': self.ACTION_ID,
            'feedback_sha256': task_digest(self.feedback._declared),
            'macro_version': self._view().macro_version, 'policy_version': self.assembler.policy_version,
            'model_version': self.assembler.model_version, 'client_version': self.worker.client_version,
            'code': module_factory_descriptor(type(self).prepare_and_register, self.VERSION),
            'assembler': module_factory_descriptor(self.assembler.build, self.ACTION_ID),
            'read_guard': module_factory_descriptor(self.read_guard, 'read_guard'),
            'validate_current': module_factory_descriptor(self.validate_current, 'validate_current')}

    def _check(self):
        self.feedback._check()
        components = (self.assembler, self.worker, self.feedback, self.assembler.registry,
            self.assembler.organizations, self._view().provider, self.worker.store, self.worker.snapshots)
        if (any(actual is not original for actual, original in zip(components, self._components))
                or self.assembler.source_mode != 'formal' or _worker_metadata(self.worker, self.ACTION_ID)[0] is not self.assembler.registry
                or self.worker.snapshots.store is not self.worker.store
                or self._configuration() != self._declared):
            raise TaskConflict('Architect feedback input substituted original components or configuration')
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Architect feedback input configuration evidence changed')

    def _selected_records(self, prepared, selected_hashes):
        """Revalidate original feedback under the caller's current source guard."""
        context, reading, supplied = prepared.context, prepared.reading, prepared.action_input
        if (not isinstance(selected_hashes, (list, tuple)) or not selected_hashes
                or any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None
                    for value in selected_hashes)
                or list(selected_hashes) != sorted(set(selected_hashes))):
            raise TaskConflict('Architect feedback provenance requires original sorted unique saved hashes')
        records = self.feedback.read(context=context, reading=reading)
        by_hash = {record['record_sha256']: record for record in records}
        if len(by_hash) != len(records) or not set(selected_hashes) <= set(by_hash):
            raise TaskConflict('Selected architect feedback is missing, duplicated or outside current authority')
        selected = [by_hash[value] for value in selected_hashes]
        receipts = []
        for record in selected:
            original = TaskIdentity(**record['identity'])
            snapshot = self.feedback.host.workers[original.action_id].snapshots.get(original)
            prior = ActionContext.model_validate(snapshot['context'])
            observed = ActionContext.model_validate(record['context'])
            # The mandatory validate_current below checks the actual source
            # relation between saved feedback scope and this new input scope.
            if (context.business_time.clock_ref != observed.business_time.clock_ref
                    or context.business_time.offset < observed.business_time.offset
                    or context.operation_id == prior.operation_id or context.task_ref.key() == prior.task_ref.key()
                    or context.read_token == prior.read_token):
                raise TaskConflict('Feedback input requires a new invocation/read token and current original clock')
            receipt = self.feedback.host.read_receipt(original)
            if task_digest(receipt) != task_digest(record['receipt']):
                raise TaskConflict('Selected feedback changed its original confirmed receipt')
            receipts.append((original, receipt))
            for source in record['sources']:
                current = reading.resolve(Reference.model_validate(source['ref'])).model_dump(mode='json')
                if task_digest(current) != task_digest(source['projection']):
                    raise TaskConflict('Feedback source changes its original currently authorized projection')
            for evidence in record['source_evidence']:
                current = reading.resolve(Reference.model_validate(evidence['ref'])).model_dump(mode='json')
                if task_digest(current) != task_digest(evidence):
                    raise TaskConflict('Feedback evidence changes its original currently authorized source')
        if self.validate_current(context=context.model_copy(deep=True), action_input=supplied.model_copy(deep=True),
                records=deepcopy(selected), reading=reading) is not True:
            raise TaskConflict('Architect feedback requires actual source/current-input relation validation')
        return selected, receipts

    def prepare_and_register(self, *, context, action_input, feedback_sha256s):
        """Select saved record hashes explicitly and preserve the complete input.

        Repeating the same relation is idempotent. A different relation, or
        attaching new provenance to an already started task, is rejected.
        """
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.worker.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode == 'offline_fixture'
                or not isinstance(feedback_sha256s, (list, tuple)) or not feedback_sha256s
                or any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None
                    for value in feedback_sha256s)
                or len(set(feedback_sha256s)) != len(feedback_sha256s)):
            raise ValueError('Architect feedback input requires its explicit current action and unique saved feedback hashes')
        selected_hashes = sorted(feedback_sha256s)
        supplied = self.registry.get(self.ACTION_ID).contract.validate_input(action_input)
        values = supplied.model_dump(mode='json')
        with self.read_guard(context.model_copy(deep=True)):
            prepared = _build_input(self.assembler, context, values)
            if prepared.action_input.model_dump(mode='json') != values:
                raise TaskConflict('Feedback input assembly changes the complete original supplied input')
            reading = prepared.reading
            selected, receipts = self._selected_records(prepared, selected_hashes)
            for original, receipt in receipts:
                if task_digest(self.feedback.host.read_receipt(original)) != task_digest(receipt):
                    raise TaskConflict('Original receipt changed during feedback input validation')
            reading.recheck()
            self._check()
            prepared = replace(prepared, reading_sha256=task_digest(reading.evidence()))
            identity = self._identity(prepared)
            if any(identity.key == original.key for original, _ in receipts):
                raise TaskConflict('Architect feedback cannot replace its original invocation')
            if prepared.action_input.model_dump(mode='json') != values or prepared.context != context:
                raise TaskConflict('Architect feedback validation changed the supplied input or context')
            provenance = {'schema_version': self.VERSION, 'identity': identity.as_dict(),
                'configuration_sha256': task_digest(self._declared), 'feedback_sha256s': selected_hashes,
                'source_reading_sha256': prepared.reading_sha256}
            provenance['record_sha256'] = task_digest(provenance)
            snapshots = self.worker.snapshots
            snapshot = snapshots._record(identity, values, context.model_dump(mode='json'))
            key = 'architect_feedback_input:' + identity.key
            # Reuse original registration primitives in one transaction; a
            # crash cannot expose a new task without its feedback provenance.
            with self.worker.store._transaction():
                saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                task = self.worker.store._read(identity)
                if saved is not None:
                    if task is None or json.loads(saved[0]) != provenance:
                        raise TaskConflict('Original architect feedback input relation cannot be replaced')
                elif task is not None and (task['revision'] != 0 or task['state'] != 'waiting_input'
                        or task['conditions'] or task['output'] is not None):
                    raise TaskConflict('Cannot attach new feedback provenance to an already started architect invocation')
                snapshots._save_in_transaction(identity, snapshot)
                if saved is None:
                    self.worker.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(provenance)))
            return PreparedArchitectFeedbackInput(identity, prepared, deepcopy(provenance))

    def check_registration(self, linked):
        """Recheck the original prepared relation before the worker executes.

        The caller holds read_guard(context); the worker still owns its normal
        current invocation validation and claim-once execution boundary.
        """
        self._check()
        if not isinstance(linked, PreparedArchitectFeedbackInput):
            raise ValueError('Architect feedback execution requires its original linked prepared input')
        prepared = linked.prepared
        identity = self._identity(prepared)
        provenance = linked.provenance
        if (identity != linked.identity or provenance.get('identity') != identity.as_dict()
                or provenance.get('configuration_sha256') != task_digest(self._declared)
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or provenance.get('source_reading_sha256') != prepared.reading_sha256
                or provenance.get('record_sha256') != task_digest({k: v for k, v in provenance.items() if k != 'record_sha256'})):
            raise TaskConflict('Architect feedback prepared invocation or original provenance changed')
        # Preparation-time feedback approval must remain valid at execution.
        _, receipts = self._selected_records(prepared, provenance.get('feedback_sha256s'))
        for original, receipt in receipts:
            if task_digest(self.feedback.host.read_receipt(original)) != task_digest(receipt):
                raise TaskConflict('Original receipt changed during execution-time feedback validation')
        current_identity = self._identity(prepared)
        if (current_identity != identity
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
            raise TaskConflict('Architect feedback validation changed original prepared input or reading')
        prepared.reading.recheck()
        self._check()
        with self.worker.store._lock:
            saved = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?',
                ('architect_feedback_input:' + identity.key,)).fetchone()
            if saved is None or json.loads(saved[0]) != provenance or self.worker.store._read(identity) is None:
                raise TaskConflict('Architect feedback invocation lacks its original registered relation')
        return identity
