"""Actual delivery completion supplied by the native decision notification service."""
from pydantic import Field, model_validator

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_decision_objects import GovFormalDecisionView, GovDecisionNotificationView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


NOTIFICATION_CODE = 'government_decision_recorded_resume_notification_without_resubmission'


class GovernmentDecisionNotificationSnapshot(StrictRecord):
    """Current native signed fact and complete notification history, including an empty history."""
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    decision: GovFormalDecisionView
    notifications: list[GovDecisionNotificationView]
    as_of: TimePoint
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def exact_history(self):
        keys = [row.ref.key() for row in self.notifications]
        if (len(set(keys)) != len(keys)
                or len({ref.key() for ref in self.decision.notification_refs}) != len(self.decision.notification_refs)
                or set(keys) != {ref.key() for ref in self.decision.notification_refs}
                or any(row.decision_ref != self.decision.ref for row in self.notifications)
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Decision notification snapshot replaces or duplicates actual history')
        return self


class GovernmentDecisionNotificationCompletionRecord(StrictRecord):
    completion_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    decision: GovFormalDecisionView
    notifications: list[GovDecisionNotificationView] = Field(min_length=1)
    completed_at: TimePoint
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def exact_history(self):
        keys = [row.ref.key() for row in self.notifications]
        if (len(set(keys)) != len(keys)
                or len({ref.key() for ref in self.decision.notification_refs}) != len(self.decision.notification_refs)
                or set(keys) != {ref.key() for ref in self.decision.notification_refs}
                or any(row.decision_ref != self.decision.ref for row in self.notifications)
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Decision delivery completion replaces or duplicates its actual notification history')
        return self


def government_original_decision_notification_profile(read_current, validate_relation):
    """Only explicit native delivery reconciliation can close this wait."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Decision delivery requires actual guarded sources and native validation')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A07' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != NOTIFICATION_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('Decision',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Decision delivery replaces its original recorded-decision wait')
        return 'waiting'

    return ConditionProfile('GOV-A07', NOTIFICATION_CODE, '1', frozenset({'dependency_change'}), evaluate)
