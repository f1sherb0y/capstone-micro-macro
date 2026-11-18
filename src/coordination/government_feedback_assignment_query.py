"""Actual native query of the original A12 work assignment; supplied without API execution."""
from typing import Literal

from pydantic import Field, model_validator

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type


class GovernmentFeedbackAssignmentQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    assignment_ref: ref_type('ReviewAssignment')
    task_ref: ref_type('Task')
    queried_at: TimePoint
    result: Literal['effective', 'released', 'unknown']
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_evidence(self):
        if len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError('Assignment query duplicates actual observation evidence')
        return self
