"""Read an actual saved Owner wait; never recompute historical method outputs."""
from copy import deepcopy
from dataclasses import replace
import json

from integration.contractor_closeout_recovery_reader import ContractorCloseoutRecoveryReader
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.coordination.owner_saved_wait_conditions import read_owner_saved_wait


class OwnerSavedWaitRecoveryReader(ContractorCloseoutRecoveryReader):
    """Pin the result table and immutable original sources to the same journal.

    Subclasses declare an actual result worker and action-specific condition.
    Reading an existing row neither creates a result table nor executes a worker.
    The current authorization must independently expose all original sources.
    Native relation validation still authenticates the original/current facts.
    """
    RESULT_WORKER_TYPE = None
    VALIDATE_ORIGINAL_SOURCES = None

    def _components(self):
        return (*super()._components(), self.RESULT_WORKER_TYPE,
            self.assembler.registry.get(self.ACTION_ID).contract, self.VALIDATE_ORIGINAL_SOURCES)

    def _configuration(self):
        result = super()._configuration()
        worker = self.RESULT_WORKER_TYPE
        result['original_result'] = dict(table=worker.RESULT_TABLE, schema_version=worker.SCHEMA,
            validate=module_factory_descriptor(worker.validate_saved_record, 'validate_saved_original_wait'),
            validate_sources=module_factory_descriptor(self.VALIDATE_ORIGINAL_SOURCES, 'validate_original_sources'),
            read=module_factory_descriptor(type(self)._read_original_record, 'read_saved_original_wait'))
        result['condition_profile'] = module_factory_descriptor(self.PROFILE_FACTORY, 'condition_profile')
        result['original_wait_checks'] = module_factory_descriptor(read_owner_saved_wait, 'original_wait_checks')
        result['method_registry_digest'] = (self.assembler.methods.content_digest
            if self.assembler.methods is not None else None)
        return result

    def _read_original_record(self, check):
        identity = TaskIdentity(**check.source['identity'])
        store, worker = self.snapshots.store, self.RESULT_WORKER_TYPE
        if worker.ACTION_ID != self.ACTION_ID or worker.ROLE != self.ROLE:
            raise TaskConflict('Owner recovery substitutes its original result table/action')
        with store._lock:
            task = store.get(identity)
            if (task != check.source or task['state'] != 'waiting_input'
                    or store.continuation(identity) is not None):
                raise TaskConflict('Owner recovery requires its unchanged pending original task')
            if store._db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                    ('table', worker.RESULT_TABLE)).fetchone() is None:
                raise TaskConflict('Owner recovery has no original persisted result table')
            row = store._db.execute(f'SELECT record FROM {worker.RESULT_TABLE} WHERE task_key=?',
                (identity.key,)).fetchone()
            if row is None:
                raise TaskConflict('Owner recovery has no original persisted result and method audit')
            record = json.loads(row[0])
            snapshot = worker.validate_saved_record(identity, record,
                registry=self.assembler.registry, snapshots=self.snapshots)
            if (record['result'].get('kind') != 'deferred'
                    or record['result']['resume_condition'] != check.condition.model_dump(mode='json')
                    or task['revision'] <= record['attempt_revision']
                    or task['conditions'] != [check.condition.model_dump(mode='json')]):
                raise TaskConflict('Owner recovery changes the actual saved original wait')
            original = ActionContext.model_validate(snapshot['context'])
            sources, originals = record['source_reading'], {}
            if not isinstance(sources, list) or task_digest(sources) != record['source_reading_sha256']:
                raise TaskConflict('Owner recovery changes original saved source contents')
            visible = {ref.key() for ref in original.visible_refs}
            schemas = worker.SOURCE_SCHEMAS()
            for source in sources:
                if not isinstance(source, dict) or set(source) != {'ref', 'projection'}:
                    raise TaskConflict('Owner recovery changes the closed original source schema')
                ref = Reference.model_validate(source['ref'])
                if ref.key() in originals or ref.key() not in visible:
                    raise TaskConflict('Owner recovery duplicates or adds unauthorized historical sources')
                originals[ref.key()] = schemas.validate_projection(ref, source['projection'])
            values = self.assembler.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
            if not {ref.key() for ref in walk_references(values)} <= set(originals):
                raise TaskConflict('Owner recovery lacks its complete original input source snapshot')
            self.VALIDATE_ORIGINAL_SOURCES(values, context=original,
                organization_id=identity.organization_id, sources=originals)
            if (record['audit']['reading'].get('source_mode') != 'formal'
                    or record['audit'].get('method_registry_digest') != identity.versions['method']):
                raise TaskConflict('Owner formal recovery cannot adopt a fixture result')
            return deepcopy(record)

    def __call__(self, check, *, history_terminal=False):
        if history_terminal:
            raise ValueError('Owner planning waits require a new current judgment, without terminal archival')
        self._check()
        record = self._read_original_record(check)
        selected = super().__call__(check, history_terminal=False)
        try:
            for source in record['source_reading']:
                ref = Reference.model_validate(source['ref'])
                if selected.reading.resolve(ref).model_dump(mode='json') != source['projection']:
                    raise TaskConflict('Owner recovery rewrites a saved immutable original source')
            if self._read_original_record(check) != record:
                raise TaskConflict('Owner original result changed during current source assembly')
            return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract,
                original_record=record)
        finally:
            selected.reading.recheck()
            self._check()
