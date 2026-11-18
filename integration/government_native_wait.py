"""Retain unresolved original regulatory work without a native acceptance."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def validate_pending_result(*, parent, worker, context, objects, source_sha256,
        row, result, conditions):
    identity = TaskIdentity(**row['identity'])
    saved = worker.get_record(identity)
    expected = {'kind': worker.WAIT_KIND, 'result_kind': result.get('kind'),
                'result_sha256': task_digest(result)}
    if result.get('kind') == 'needs_information':
        expected.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
    elif result.get('kind') == 'unsupported':
        expected['capability_ref'] = result['capability_ref']
    elif result.get('kind') == 'deferred':
        expected['resume_condition'] = result['resume_condition']
    else:
        raise TaskConflict('Regulatory wait requires its original unresolved business result')
    if (identity.action_id != worker.ACTION_ID or identity.role != 'Government'
            or identity.context_sha256 != task_digest(context.model_dump(mode='json'))
            or identity.run_id != context.run_id
            or row != worker.store.get(identity) or row['state'] != 'processing'
            or saved is None or saved['result'] != result
            or saved['attempt_revision'] != row['revision'] or conditions != [expected]
            or task_digest(objects) != source_sha256):
        raise TaskConflict('Regulatory wait changes its original task, result or current sources')
    grants = parent.organizations.grants(context, worker.ACTION_ID, 'Government')
    readable = {ref.key() for grant in grants for ref in grant.readable_refs} & {
        ref.key() for ref in context.visible_refs}
    schemas = worker.SOURCE_SCHEMAS()
    current = {task_digest(r['ref']): schemas.validate_projection(
        Reference.model_validate(r['ref']), r['value']).model_dump(mode='json') for r in objects}
    if (not grants or any(grant.organization_id != identity.organization_id for grant in grants)
            or any(Reference.model_validate(r['ref']).key() not in readable
                or current.get(task_digest(r['ref'])) != r['projection'] for r in saved['source_reading'])):
        raise TaskConflict('Regulatory wait lost its original authorized pending sources')
    return True


def completed_result_or_wait(*, parent, worker, identity, key, record, stage):
    """Keep the actual wait visible and stop before any dependent action."""
    task = worker.store.get(identity)
    if task['state'] == 'waiting_input':
        saved = worker.get_record(identity)
        if (saved is None or task['output'] is not None
                or saved['result']['kind'] not in {'needs_information', 'unsupported', 'deferred'}):
            raise TaskConflict('Regulatory pending task lost its original unresolved result')
        pending = {'stage': stage, 'identity': identity.as_dict(),
            'result_sha256': saved['result_sha256'], 'conditions': deepcopy(task['conditions'])}
        parent._save(key, {**record, 'state': 'waiting_input', 'pending': pending})
        raise TaskConflict('Original regulatory work is waiting_input; no native acceptance or automatic replay')
    return checked_result(worker, identity)
