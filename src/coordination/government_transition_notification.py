"""Observed completion of notifications for an original GOV-A09 formal change."""
from src.actions.contracts.common import ref_type
from src.actions.contracts.government_transition_objects import GovTransitionDecisionView
from src.coordination.government_decision_notification import (
    GovernmentDecisionNotificationCompletionRecord, GovernmentDecisionNotificationSnapshot,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


NOTIFICATION_CODE = 'government-transition-recorded-change-notification-continuation'


class GovernmentTransitionNotificationCompletionRecord(GovernmentDecisionNotificationCompletionRecord):
    prior_decision_ref: ref_type('Decision')
    decision: GovTransitionDecisionView


class GovernmentTransitionNotificationSnapshot(GovernmentDecisionNotificationSnapshot):
    prior_decision_ref: ref_type('Decision')
    decision: GovTransitionDecisionView


def government_original_transition_notification_profile(read_current, validate_relation):
    """Formal changes can only finish through explicit actual-delivery reconciliation."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Change notification requires actual guarded sources and native validation')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A09' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != NOTIFICATION_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('Decision',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Change notification replaces original recorded change wait/run/agency')
        return 'waiting'

    return ConditionProfile('GOV-A09', NOTIFICATION_CODE, '1', frozenset({'dependency_change'}), evaluate)
