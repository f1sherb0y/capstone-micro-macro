"""Current private Government read authority, retaining original execution facts."""
import json

from src.actions.contracts.common import ActionContext, Reference
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.registry import AccessDenied


_TABLES = {'GOV-A02':'government_intake_results', 'GOV-A04':'government_review_results',
           'GOV-A07':'government_decision_results', 'GOV-A12':'government_feedback_results'}


def authorize_government_history(assembly, identity, *, organizations, tick, saved=None):
    """Check original saved sources against grants at the actual current read time."""
    identity = identity if isinstance(identity, TaskIdentity) else TaskIdentity(**identity)
    client = assembly.client
    if (organizations is None or type(tick) is not int or tick != assembly.engine.current_tick
            or identity.run_id != client.run_id or identity.role != 'Government'
            or identity.purpose != 'action' or identity.action_id not in _TABLES
            or client.organization_roles.get(identity.organization_id) != 'Government'):
        raise TaskConflict('Government history requires its original identity, current clock and organization authority')
    if saved is None:
        with client.tasks._lock:
            row = client.tasks._db.execute('SELECT record FROM '+_TABLES[identity.action_id]+' WHERE task_key=?',
                (identity.key,)).fetchone()
        saved = None if row is None else json.loads(row[0])
    snapshot = InvocationSnapshotStore(client.tasks).get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    task = client.tasks.get(identity)
    if (saved is None or tick < context.business_time.offset
            or context.run_id != identity.run_id or context.contract_ref.id != identity.action_id
            or saved['identity'] != identity.as_dict() or snapshot['identity'] != identity.as_dict()
            or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or saved['record_sha256'] != task_digest({k:v for k,v in saved.items() if k!='record_sha256'})
            or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or saved['result']['kind'] != 'completed' or task['state'] != 'output_formed'
            or task['output'] != saved['result'] or task['output_sha256'] != saved['result_sha256']):
        raise TaskConflict('Government history changes its original task, snapshot, result or private sources')
    current = context.model_copy(update={
        'business_time':context.business_time.model_copy(update={'offset':tick})}, deep=True)
    grants = organizations.grants(current, identity.action_id, 'Government')
    readable = {ref.key() for grant in grants for ref in grant.readable_refs} & {
        ref.key() for ref in context.visible_refs}
    if (not grants or any(grant.organization_id != identity.organization_id for grant in grants)
            or any(Reference.model_validate(row['ref']).key() not in readable for row in saved['source_reading'])):
        raise AccessDenied('Government history lost current permission for original private sources')
    return saved
