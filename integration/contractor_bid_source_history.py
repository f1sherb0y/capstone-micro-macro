"""Private original A02 read witnesses, separate from formal bid receipts.

The writer is called inside the original result transaction. Historical reads
use current own authority and never rebuild sources from a changed project.
"""
from copy import deepcopy
import json

from src.actions.contracts.common import ActionContext, Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.organization.registry import scope_covers


PREFIX = 'contractor_bid_source_history:'
SCHEMA = 'contractor-bid-source-history.v1'


def save_bid_source_history(worker, identity, record, prepared, snapshot):
    """Caller owns the original result transaction; do not commit separately."""
    if worker.ACTION_ID != 'CONTRACTOR-A02' or worker.RESULT_TABLE != 'contractor_bid_results':
        raise TaskConflict('Only the original A02 worker may retain bid source history')
    actual_audit = prepared.runner.audit_records[-1]
    witness = actual_audit.source_reading_evidence
    audit = record['audit']['reading']
    if (not isinstance(witness, list) or actual_audit.as_dict() != record['audit']
            or task_digest(witness) != audit.get('sha256')):
        raise TaskConflict('Bid source history differs from its actual original audit reading')
    body = {'schema_version': SCHEMA, 'identity': identity.as_dict(),
            'snapshot_sha256': snapshot['snapshot_sha256'], 'result_sha256': record['result_sha256'],
            'source_record_sha256': record['record_sha256'], 'source_mode': audit.get('source_mode'),
            'audit_reading_sha256': task_digest(audit), 'source_reading_sha256': task_digest(witness),
            'source_reading': witness}
    body['record_sha256'] = task_digest(body)
    key = PREFIX + identity.key
    previous = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    if previous is not None:
        if json.loads(previous[0]) != body:
            raise TaskConflict('Original bid source witness already differs; it cannot be replaced')
        return
    worker.store._db.execute('INSERT INTO metadata(key,value) VALUES (?,?)', (key, canonical(body)))


def read_bid_source_history(worker, identity, *, current_context, organizations):
    """Return authorized original projections, or an explicit missing witness.

    This is own private history, not accepted submission/selection evidence.
    Formal callers must independently authenticate the actual native event.
    """
    identity = TaskIdentity(**identity.as_dict())
    context = ActionContext.model_validate(current_context).model_copy(deep=True)
    if (worker.ACTION_ID != 'CONTRACTOR-A02' or identity.action_id != 'CONTRACTOR-A02'
            or identity.role != 'Contractor' or identity.purpose != 'action'
            or worker.store.run_id != identity.run_id or context.run_id != identity.run_id
            or organizations.run_id != identity.run_id
            or worker.registry.get(context.contract_ref.id).role != 'Contractor'):
        raise TaskConflict('Bid source history requires its original run and own Contractor action')
    with worker.store._lock:
        grants = organizations.grants(context, context.contract_ref.id, 'Contractor')
        if any(g.organization_id != identity.organization_id for g in grants):
            raise TaskConflict('Bid source history requires its own original organization')
        # This validation reads original task/contract/audit evidence only.
        saved = worker.get_record(identity)
        if saved is None:
            return {'status': 'unknown', 'identity': identity.as_dict(), 'reason': 'no_original_saved_result'}
        snapshot = worker.snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        original_grants = organizations.grants(original, 'CONTRACTOR-A02', 'Contractor')
        if (any(g.organization_id != identity.organization_id for g in [*grants, *original_grants])
                or not scope_covers(context.scope, original.scope)
                or context.business_time.clock_ref != original.business_time.clock_ref
                or context.business_time.offset < original.business_time.offset):
            raise TaskConflict('Bid source history substitutes original firm, scope or business chronology')
        raw = worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (PREFIX + identity.key,)).fetchone()
        if raw is None:
            return {'status': 'unknown', 'identity': identity.as_dict(),
                    'reason': 'no_original_source_witness', 'result_sha256': saved['result_sha256']}
        witness = json.loads(raw[0])
        if (witness.get('schema_version') != SCHEMA or witness.get('identity') != identity.as_dict()
                or witness.get('record_sha256') != task_digest({k: v for k, v in witness.items() if k != 'record_sha256'})
                or witness.get('snapshot_sha256') != snapshot['snapshot_sha256']
                or witness.get('source_record_sha256') != saved['record_sha256']
                or witness.get('result_sha256') != saved['result_sha256']
                or witness.get('audit_reading_sha256') != task_digest(saved['audit']['reading'])
                or witness.get('source_mode') != saved['audit']['reading'].get('source_mode')
                or witness.get('source_reading_sha256') != task_digest(witness.get('source_reading'))
                or witness['source_reading_sha256'] != saved['audit']['reading'].get('sha256')):
            raise TaskConflict('Bid source history lost its exact original witness, audit or result')
        current_readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
        original_readable = {r.key() for g in original_grants for r in g.readable_refs} & {r.key() for r in original.visible_refs}
        references = [Reference.model_validate(row['ref']).key() for row in witness['source_reading']]
        if (len(references) != len(set(references))
                or not set(references) <= current_readable & original_readable):
            raise TaskConflict('Bid source history exceeds original or current private source permissions')
        return {'status': 'saved', 'identity': identity.as_dict(), 'witness': deepcopy(witness),
                'task_state': worker.store.get(identity)['state'], 'result_kind': saved['result']['kind'],
                'formal_effect': 'not_proven_by_private_source_history'}
