"""Archive actual same-business A12 execution without replaying private learning."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import ResumeCondition
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.architect_learning_execution_query import EXECUTION_CODE, check_learning_execution
from src.coordination.architect_learning_applied_feedback import APPLIED_CODE, check_applied_feedback
from src.coordination.tasks import TaskConflict


def reconcile_architect_learning_execution(*, identity, signal, reader, dispatcher, validate_relation):
    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=EXECUTION_CODE, checker=check_learning_execution,
        reader_options={'execution_terminal': True}, proof=lambda resolution: resolution['query']['execution'])


def reconcile_architect_applied_feedback(*, identity, signal, reader, dispatcher, validate_relation):
    def application_proof(resolution):
        query = resolution['query']
        return (set(query['event_keys']), {tuple(sorted(ref.items())) for ref in query['application_execution_refs']})

    return _reconcile_learning_wait(identity=identity, signal=signal, reader=reader, dispatcher=dispatcher,
        validate_relation=validate_relation, condition_code=APPLIED_CODE, checker=check_applied_feedback,
        reader_options={'feedback_terminal': True}, proof=application_proof)


def _reconcile_learning_wait(*, identity, signal, reader, dispatcher, validate_relation,
        condition_code, checker, reader_options, proof, action_id='ARCHITECT-A12', role='Architect'):
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    store = reader.snapshots.store
    if (identity.action_id != action_id or identity.role != role or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Learning execution reconciliation changes original run/action/private recipient')
    events = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(events) != 1:
        raise TaskConflict('Learning execution reconciliation requires original persisted observation')
    projected = dispatcher.project_signal(deepcopy(events[0]))
    if not observation_signal_matches(events[0], projected, expected=signal):
        raise TaskConflict('Learning execution reconciliation replaces persisted observation projection')
    source = store.get(identity)
    if (source['state'] not in {'waiting_input', 'wait_resolved'} or len(source['conditions']) != 1
            or store.continuation(identity) is not None):
        raise TaskConflict('Learning execution reconciliation requires original wait without successor')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    if condition.condition_code != condition_code or not dispatcher.journal._matches(condition, signal):
        raise TaskConflict('Learning execution reconciliation changes original execution wait or matching signal')
    check = ConditionCheck(deepcopy(source), condition, signal)
    selected = reader(check, **reader_options)
    try:
        state, resolution = checker(check, selected, validate_relation, terminal=True)
        if state != 'ready':
            return dict(status='waiting', source=identity.as_dict())
        selected.reading.recheck()
        reader._check()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if proof(previous['resolution']) != proof(resolution):
                raise TaskConflict('Learning execution reconciliation rewrites archived actual disposition')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        selected.reading.recheck()
        reader._check()
