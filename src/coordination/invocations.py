"""Immutable invocation snapshots share their task journal's run and transaction."""
from copy import deepcopy
import json

from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest


class InvocationSnapshotStore:
    """Persist original action inputs/contexts without adding domain ledger state.

    Root task creation and snapshot insertion commit together. A successor can
    recover its snapshots from the journal's already validated continuation
    link. Older root tasks without snapshots require explicit source recovery;
    no current input is substituted for a missing historical invocation.
    """
    SCHEMA = 'task-invocation.v1'

    def __init__(self, store):
        if not isinstance(store,TaskStore):
            raise ValueError('Invocation snapshots require their actual run-local task store')
        self.store = store
        with store._transaction():
            store._db.execute('CREATE TABLE IF NOT EXISTS invocation_snapshots (task_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _record(self, identity, action_input, context):
        identity = TaskIdentity(**identity.as_dict())
        if (identity.run_id != self.store.run_id or identity.organization_id not in self.store.organization_ids
                or not isinstance(action_input,dict) or not action_input or not isinstance(context,dict) or not context):
            raise TaskConflict('Invocation snapshot changes its run, recipient or transport records')
        # Preserve the exact JSON snapshots. Canonicalization rejects non-JSON
        # values and NaN rather than silently changing a historical schema.
        action_input, context = json.loads(canonical(action_input)), json.loads(canonical(context))
        contract = context.get('contract_ref')
        if (context.get('run_id') != identity.run_id or not isinstance(contract,dict)
                or contract.get('kind') != 'ActionContract' or contract.get('id') != identity.action_id
                or task_digest(action_input) != identity.input_sha256
                or task_digest(context) != identity.context_sha256):
            raise TaskConflict('Invocation snapshot differs from the original task input/context identity')
        record = {'schema_version':self.SCHEMA,'identity':identity.as_dict(),
                  'action_input':action_input,'context':context}
        record['snapshot_sha256'] = task_digest(record)
        return record

    def _validate(self, raw, identity):
        if not isinstance(raw,dict) or set(raw) != {'schema_version','identity','action_input','context','snapshot_sha256'}:
            raise TaskConflict('Stored invocation has missing or extra snapshot fields')
        if raw['identity'] != identity.as_dict() or raw != self._record(identity,raw['action_input'],raw['context']):
            raise TaskConflict('Stored invocation snapshot, schema or digest changed')
        return deepcopy(raw)

    def _save_in_transaction(self, identity, record):
        task = self.store._read(identity)
        saved = self.store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',(identity.key,)).fetchone()
        if saved is not None:
            if task is None:
                raise TaskConflict('Invocation snapshot is orphaned from its original task')
            original = self._validate(json.loads(saved[0]),identity)
            if original != record:
                raise TaskConflict('An original invocation snapshot cannot be replaced')
            return original
        if task is None and self.store._db.execute(
                'SELECT 1 FROM continuation_links WHERE source_key=? OR successor_key=?',
                (identity.key,identity.key)).fetchone():
            raise TaskConflict('Cannot recreate a missing continued task from an invocation snapshot')
        self.store._ensure_in_transaction(identity)
        self.store._db.execute('INSERT INTO invocation_snapshots VALUES (?,?)',(identity.key,canonical(record)))
        return deepcopy(record)

    def ensure(self, identity, *, action_input, context):
        """Persist a validated caller's exact snapshots and create its root task."""
        identity = TaskIdentity(**identity.as_dict())
        record = self._record(identity,action_input,context)
        with self.store._transaction():
            return self._save_in_transaction(identity,record)

    def get(self, identity):
        """Recover exact saved snapshots, including committed successor links."""
        identity = TaskIdentity(**identity.as_dict())
        with self.store._transaction():
            if self.store._read(identity) is None:
                raise TaskConflict('Invocation task has not been registered')
            saved = self.store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',(identity.key,)).fetchone()
            if saved is not None:
                return self._validate(json.loads(saved[0]),identity)
            linked = self.store._db.execute('SELECT record FROM continuation_links WHERE successor_key=?',(identity.key,)).fetchone()
            if linked is None:
                raise TaskConflict('Original root snapshot is missing; recover its actual source, never substitute current input')
            raw = json.loads(linked[0])
            if not isinstance(raw,dict) or not isinstance(raw.get('source'),dict):
                raise TaskConflict('Successor link lacks its original source identity')
            link = self.store.continuation(TaskIdentity(**raw['source']))
            if link is None or link['successor'] != identity.as_dict():
                raise TaskConflict('Invocation successor link changed or belongs to another task')
            record = self._record(identity,link['next_input'],link['next_context'])
            return self._save_in_transaction(identity,record)
