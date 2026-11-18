"""Scoped architectural review requests, saved checks and original comments."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class ArchitectReviewTargetView(CostSource):
    ref: ref_type('Deliverable')
    content_sha256: Digest
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A05', 'ARCHITECT-A06']
    authored_at: TimePoint
    author_personnel_ids: Annotated[list[TextId], Field(min_length=1)]
    unresolved_issue_refs: list[ref_type('Issue')]
    issue_coverage: Literal['complete', 'partial', 'unknown']
    reviewable_uses: list[ServiceUse]


class ArchitectReviewRequestView(CostSource):
    ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    requested_use: ServiceUse
    choice: Literal['review', 'respond', 'propose_revision']
    required_check_refs: list[ref_type('CheckSpec')]
    received_check_result_refs: list[ref_type('MethodResult')]
    comment_refs: list[ref_type('ReviewComment')]
    independence_rule: Literal['author_response', 'no_requirement', 'different_personnel', 'unrelated_organization_and_personnel']
    reviewer_personnel_ids: Annotated[list[TextId], Field(min_length=1)]
    response_comment_ref: ref_type('ReviewComment') | None
    question_refs: list[ref_type('EvidenceTarget')]
    explanation: TextId
    status: Literal['authorized', 'withdrawn']
    author_response_ref: ref_type('ArchitectAuthorReviewResponse') | None = None


class ArchitectReviewTaskRegistrationView(CostSource):
    """Actual review intake retaining the original A07 request identity."""
    ref: ref_type('ArchitectReviewTaskRegistration')
    run_id: TextId
    requester_organization_id: TextId
    reviewer_organization_id: TextId
    reviewer_actor_id: TextId
    reviewer_function_ref: ref_type('FunctionAssignment')
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    submission_command_id: TextId
    submission_business_key: TextId
    review_requirement_ref: ref_type('ReviewRequirement')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    requested_use: ServiceUse
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    selected_recipient_id: TextId
    unresolved_issue_refs: list[ref_type('Issue')]
    review_request_ref: ref_type('ReviewRequest')
    review_request_sha256: Digest | None
    review_target_sha256: Digest | None
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    registered_at: TimePoint | None


class ArchitectReviewSpecView(CostSource):
    ref: ref_type('CheckSpec')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    requested_use: ServiceUse
    method_ref: ref_type('Method') | None
    question_refs: list[ref_type('EvidenceTarget')]


class ArchitectReviewMethodView(CostSource):
    ref: ref_type('Method')
    check_spec_ref: ref_type('CheckSpec')
    target_ref: ref_type('Deliverable')
    requested_use: ServiceUse
    supported: ValueState[bool]
    purpose: Literal['architectural_scoped_check']
    permitted_verifier_ids: list[TextId]


class ArchitectReviewCheckView(CostSource):
    ref: ref_type('MethodResult')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    check_spec_ref: ref_type('CheckSpec')
    method_ref: ref_type('Method')
    requested_use: ServiceUse
    passed: ValueState[bool]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    unresolved_issue_refs: list[ref_type('Issue')]
    executed_at: TimePoint
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A08']


class ArchitectReviewCommentView(CostSource):
    """Received peer comment; legacy response fields never supply author output."""
    ref: ref_type('ReviewComment')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint
    response: TextId
    response_basis_refs: list[ref_type('Evidence')]
    response_changes_content: bool
    status: Literal['received', 'withdrawn']


class ArchitectAuthorReviewResponseView(CostSource):
    """Author-owned response draft, separate from the received peer comment."""
    ref: ref_type('ArchitectAuthorReviewResponse')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    target_content_sha256: Digest
    comment_ref: ref_type('ReviewComment')
    comment_sha256: Digest
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A08']
    authored_at: TimePoint
    response: TextId
    response_basis_refs: list[ref_type('Evidence')]
    response_changes_content: bool
    status: Literal['prepared', 'withdrawn']


class ArchitectRegisteredReviewOpinion(StrictRecord):
    target_ref: ref_type('Deliverable')
    review_request_ref: ref_type('ReviewRequest')
    check_result_refs: list[ref_type('MethodResult')]
    opinion: Literal['support', 'limited_support', 'revise', 'undetermined']
    requested_use: ServiceUse
    unresolved_issue_refs: list[ref_type('Issue')]
    explanation: TextId


class ArchitectReviewOpinionReceiptView(CostSource):
    """Actual author receipt retaining the original full reviewer opinion."""
    ref: ref_type('ArchitectReviewOpinionReceipt')
    run_id: TextId
    reviewer_organization_id: TextId
    author_organization_id: TextId
    author_actor_id: TextId
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    opinion: ArchitectRegisteredReviewOpinion
    opinion_content_sha256: Digest
    target_content_sha256: Digest
    author_review_request_ref: ref_type('ReviewRequest')
    comment_ref: ref_type('ReviewComment')
    comment_sha256: Digest | None
    receipt_service_id: TextId
    reception_status: Literal['pending', 'unknown', 'received', 'failed', 'rejected']
    received_at: TimePoint | None


class ArchitectReviewIndependenceView(CostSource):
    ref: ref_type('IndependenceCheck')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    reviewer_organization_id: TextId
    reviewer_actor_id: TextId
    reviewer_personnel_ids: list[TextId]
    author_organization_id: TextId
    author_personnel_ids: list[TextId]
    related_organization_ids: ValueState[list[TextId]]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    verifier_organization_id: TextId
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId
    verified_at: TimePoint


class ArchitectReviewIssueView(CostSource):
    ref: ref_type('Issue')
    target_ref: ref_type('Deliverable')
    blocking_uses: list[ServiceUse]
    status: Literal['open', 'unknown', 'closed']


class ArchitectReviewQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    question: ArchitectOpportunityQuestion


def architect_review_schemas():
    return service_intake_schemas(overrides={
        'Deliverable': ArchitectReviewTargetView, 'ReviewRequest': ArchitectReviewRequestView,
        'ArchitectReviewTaskRegistration': ArchitectReviewTaskRegistrationView,
        'ArchitectReviewOpinionReceipt': ArchitectReviewOpinionReceiptView,
        'ArchitectAuthorReviewResponse': ArchitectAuthorReviewResponseView,
        'CheckSpec': ArchitectReviewSpecView, 'Method': ArchitectReviewMethodView,
        'MethodResult': ArchitectReviewCheckView, 'ReviewComment': ArchitectReviewCommentView,
        'IndependenceCheck': ArchitectReviewIndependenceView, 'Issue': ArchitectReviewIssueView,
        'EvidenceTarget': ArchitectReviewQuestionView,
    })
