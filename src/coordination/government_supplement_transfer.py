"""Evidence supplied by actual intake when revised materials require a new case."""
from typing import Literal

from pydantic import Field

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


NEW_CASE_CODE = 'government_supplement_requires_new_case'


class GovernmentSupplementTransferRecord(StrictRecord):
    transfer_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    original_case_ref: ref_type('RegulatoryCase')
    revision_basis_ref: ref_type('RevisionBasis')
    revised_submission_ref: ref_type('Submission')
    revised_content_sha256: Digest
    new_case: GovSchedulingCaseView
    received_submission: GovReviewSubmissionView
    received_at: TimePoint
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    action_id: Literal['GOV-A02']
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)


def government_original_supplement_transfer_profile(read_current, validate_relation):
    """Keep this wait pending until explicit native transfer reconciliation.

    New-case intake has its own task/receipt. A same-case continuation cannot
    stand in for intake or terminally resolve this wait.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplement transfer requires actual guarded sources and native validation')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A06' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != NEW_CASE_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('RegulatoryCase', 'RevisionBasis', 'Submission')
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Supplement transfer replaces original new-case wait/run/agency')
        return 'waiting'

    return ConditionProfile('GOV-A06', NEW_CASE_CODE, '1', frozenset({'dependency_change'}), evaluate)
