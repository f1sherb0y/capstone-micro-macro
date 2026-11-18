"""Read an original QS evaluation outcome without rerunning or submitting work."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.registry import AccessDenied


def original_authorized_round(parent, identity, *, organization_id, tick, require_native_result=True):
    """Recheck original saved private sources at the actual current read time."""
    identity = identity if isinstance(identity, TaskIdentity) else TaskIdentity(**identity)
    parent._check()
    client, engine = parent.assembly.client, parent.assembly.engine
    if (identity.run_id != client.run_id or identity.organization_id != organization_id
            or identity.role != 'QS' or identity.action_id != 'QS-A06' or identity.purpose != 'action'
            or client.organization_roles.get(organization_id) != 'QS'
            or type(tick) is not int or tick != engine.current_tick
            or client.simulation_id != engine.simulation_id):
        raise TaskConflict('QS outcome query changes its original organization, action or current clock')
    plans = [p for p in parent.plans if p.organization_id == organization_id
        and task_digest(p.context.model_dump(mode='json')) == identity.context_sha256]
    if len(plans) != 1 or plans[0].tick > tick:
        raise TaskConflict('QS outcome query lacks its original evaluation plan at this read time')
    plan = plans[0]
    record = parent._record(plan)
    if record is None or record.get('identity') != identity.as_dict():
        raise TaskConflict('QS outcome query lacks its exact original completed round')
    if require_native_result:
        actual_identity, _ = parent._result(plan, record)
    else:
        review = checked_result(parent.worker, identity)
        if record['state']!='formed' or record['result_sha256']!=review['result_sha256']:
            raise TaskConflict('QS review changed its original finalized private result')
        actual_identity = identity
    snapshot = parent.worker.snapshots.get(identity)
    if (actual_identity != identity or snapshot['identity'] != identity.as_dict()
            or snapshot['context'] != plan.context.model_dump(mode='json')
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or any(snapshot['action_input'].get(k) != v for k,v in plan.action_input.items())
            or identity.request_id != 'qs-native-round:' + parent._key(plan)):
        raise TaskConflict('QS outcome query substitutes its original invocation or snapshot')
    current = plan.context.model_copy(update={
        'business_time':plan.context.business_time.model_copy(update={'offset':tick})}, deep=True)
    grants = parent.bindings.organizations.grants(current, 'QS-A06', 'QS')
    saved = checked_result(parent.worker, identity)
    readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in plan.context.visible_refs}
    if (not grants or any(g.organization_id != organization_id for g in grants)
            or any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading'])):
        raise AccessDenied('QS evaluation lost current permission for original private sources')
    return plan, record, saved


def matching_native_events(parent, plan):
    engine = parent.assembly.engine
    project = engine.projects.get(plan.project_id)
    if project is None:
        raise TaskConflict('QS outcome query lost its original native project')
    record = parent._record(plan)
    _,result = parent._result(plan,record)
    event_type = 'bid_evaluation_deferred' if result['payload']['choice']=='no_valid_bid' else 'bid_evaluation_completed'
    def matches(e):
        return e['event_type']==event_type and e['project_id']==plan.project_id and e['tick']==plan.tick
    local = [e for e in project.event_log if matches(e)]
    global_ = [e.model_dump(mode='json') for e in engine.events.events if matches(e.model_dump(mode='json'))]
    if (len(local)>1 or len(global_)>1 or
            {e['event_id']:task_digest(e) for e in local}!={e['event_id']:task_digest(e) for e in global_}):
        raise TaskConflict('QS outcome query requires matching original global and project evaluation events')
    return local


def query_qs_evaluation_outcome(parent, identity, *, organization_id, tick):
    from integration.qs_evaluation_learning import read_own_completed_evaluations
    with parent.bindings.read_guard():
        identity = identity if isinstance(identity, TaskIdentity) else TaskIdentity(**identity)
        plan, record, saved = original_authorized_round(parent, identity, organization_id=organization_id, tick=tick)
        events = matching_native_events(parent, plan)
        outcomes = read_own_completed_evaluations(parent, organization_id=organization_id,
            project_id=plan.project_id, tick=tick, include_current=True, evaluation_task_key=identity.key)
        if len(outcomes)>1 or bool(events)!=bool(outcomes):
            raise TaskConflict('QS outcome query cannot reconcile its original published evaluation')
        outcome = outcomes[0] if outcomes else None
        result = {'schema_version':'qs-native-evaluation-outcome-query.v1',
            'status':'unknown' if outcome is None else 'observed',
            'run_id':identity.run_id,'simulation_id':parent.assembly.client.simulation_id,
            'organization_id':organization_id,'queried_at_tick':tick,
            'original_decision_identity':identity.as_dict(),
            'original_native_request_id':record['native_request']['request_id'],
            'native_scope':{'project_id':plan.project_id,'tick':plan.tick},
            'micro_result_sha256':saved['result_sha256'],'native_outcome':deepcopy(outcome),
            'limits':['Absence is unknown and does not permit resubmission.',
                'Published scores and native preferred selection do not prove a signed contract, actual costs, cash or improved capability.',
                'Read-only query; no processor replay, new task, repaired source or advanced clock.']}
        result['query_sha256'] = task_digest(result)
        return result
