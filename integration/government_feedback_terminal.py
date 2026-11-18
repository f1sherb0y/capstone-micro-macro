"""Reconcile the original business execution result without replaying A12 or fabricating output."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import ResumeCondition
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_feedback_execution_query import EXECUTION_CODE, check_feedback_execution
from src.coordination.tasks import TaskConflict


def reconcile_government_feedback_execution(*, identity, signal, reader, dispatcher, validate_relation):
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    store = reader.snapshots.store
    if (identity.action_id != 'GOV-A12' or identity.role != 'Government' or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Feedback execution reconciliation changes original run/action/recipient')
    events = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(events) != 1:
        raise TaskConflict('Feedback execution reconciliation requires original persisted feedback')
    projected = dispatcher.project_signal(deepcopy(events[0]))
    if not observation_signal_matches(events[0], projected, expected=signal):
        raise TaskConflict('Feedback execution reconciliation replaces persisted feedback projection')
    source = store.get(identity)
    if (source['state'] not in {'waiting_input', 'wait_resolved'} or len(source['conditions']) != 1
            or store.continuation(identity) is not None):
        raise TaskConflict('Feedback execution reconciliation requires original unresolved/resolved wait without successor')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    if condition.condition_code != EXECUTION_CODE or not dispatcher.journal._matches(condition, signal):
        raise TaskConflict('Feedback execution reconciliation changes original execution wait or matching signal')
    check = ConditionCheck(deepcopy(source), condition, signal)
    selected = reader(check, execution_terminal=True)
    try:
        state, resolution = check_feedback_execution(check, selected, validate_relation, terminal=True)
        if state != 'ready':
            return dict(status='waiting', source=identity.as_dict())
        selected.reading.recheck()
        reader._check()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if previous['resolution']['query']['execution'] != resolution['query']['execution']:
                raise TaskConflict('Feedback execution reconciliation rewrites archived actual result')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        selected.reading.recheck()
        reader._check()
