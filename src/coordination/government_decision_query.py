"""Actual original-command lookup evidence, supplied by the formal signing endpoint."""
from typing import Literal

from pydantic import Field, model_validator

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type


class GovernmentDecisionQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    command_ref: ref_type('DecisionCommand')
    operation_id: TextId
    business_key: TextId
    draft_sha256: Digest
    queried_at: TimePoint
    result: Literal['absent', 'present', 'unknown']
    official_decision_ref: ref_type('Decision') | None
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def actual_result(self):
        if (self.result == 'present') != (self.official_decision_ref is not None):
            raise ValueError('Formal decision lookup must bind its found fact and retain absence/uncertainty')
        if len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError('Formal decision lookup repeats actual evidence')
        return self
