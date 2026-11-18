"""Versioned deliverable submission proposals and independent release evidence."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Reference, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_planning_objects import ArchitectPlanningWorkFactView
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas
from src.actions.contracts.architect_integration_objects import ArchitectRegisteredIntegrationDraft


class ArchitectIntegrationRegistrationView(CostSource):
    """Actual registered artifact retaining the full original A06 draft."""
    ref: ref_type('IntegrationRegistration')
    run_id: TextId
    organization_id: TextId
    task_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    record_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    result_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    source_reading_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    draft: ArchitectRegisteredIntegrationDraft
    task_ref: ref_type('Task')
    deliverable_ref: ref_type('Deliverable')
    deliverable_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None
    deliverable_content_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None
    dependency_refs: list[ref_type('Deliverable')]
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    authored_at: TimePoint
    registered_at: TimePoint | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')

SubmissionChoice = Literal['submit', 'request_review', 'release_for_use']
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class ArchitectSubmissionDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    task_ref: ref_type('Task')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A05', 'ARCHITECT-A06']
    authored_at: TimePoint
    content_sha256: Digest
    submission_profile_ref: ref_type('SubmissionProfile')
    dependency_refs: list[ref_type('Deliverable')]
    unresolved_issue_refs: list[ref_type('Issue')]
    issue_coverage: Literal['complete', 'partial', 'unknown']
    intended_uses: list[ServiceUse]
    valid_for_uses: list[ServiceUse]
    invalidated_uses: list[ServiceUse]
    invalidation_evidence_refs: list[ref_type('Evidence')]
    status: Literal['compiled', 'draft', 'withdrawn']


class ArchitectSubmissionProfileView(CostSource):
    ref: ref_type('SubmissionProfile')
    deliverable_ref: ref_type('Deliverable')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    publication_authority_ref: ref_type('PublicationAuthority')
    choice: SubmissionChoice
    completion_check_refs: list[ref_type('MethodResult')]
    required_release_codes: list[TextId]
    recipient_refs: list[ref_type('PublicationRecipient')]
    command_id: TextId
    business_key: TextId
    operation_id: TextId
    submission_refs: list[ref_type('DeliverableSubmission')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    note: TextId


class ArchitectPublicationAuthorityView(CostSource):
    ref: ref_type('PublicationAuthority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    deliverable_ref: ref_type('Deliverable')
    permitted_choices: list[SubmissionChoice]
    permitted_uses: list[ServiceUse]
    recipient_ids: list[TextId]
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    granted_at: TimePoint


class ArchitectTaskCompletionView(CostSource):
    ref: ref_type('TaskCompletion')
    task_ref: ref_type('Task')
    organization_id: TextId
    deliverable_ref: ref_type('Deliverable')
    content_sha256: Digest
    required_effort: Measured
    work_fact_refs: list[ref_type('WorkFact')]
    check_refs: list[ref_type('MethodResult')]
    completed_at: TimePoint
    status: Literal['completed', 'unknown', 'failed']
    investment_coverage: Literal['complete', 'partial', 'unknown']


class ArchitectSubmissionCheckView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    deliverable_ref: ref_type('Deliverable')
    content_sha256: Digest
    passed: ValueState[bool]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    executed_at: TimePoint


class ArchitectSubmissionRecipientView(CostSource):
    ref: ref_type('PublicationRecipient')
    recipient_id: TextId
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    intake_action_id: TextId
    permitted_uses: list[ServiceUse]


class ArchitectSubmissionReviewView(CostSource):
    ref: ref_type('ReviewRequirement')
    deliverable_ref: ref_type('Deliverable')
    requested_use: ServiceUse
    recipient_ids: list[TextId]
    intake_action_ids: list[TextId]
    allow_unresolved_issues: bool


class ArchitectSubmissionIssueView(CostSource):
    ref: ref_type('Issue')
    deliverable_ref: ref_type('Deliverable')
    blocking_uses: list[ServiceUse]
    status: Literal['open', 'closed', 'unknown']


class ArchitectSubmissionReleaseBasisView(CostSource):
    ref: ref_type('ReleaseBasis')
    deliverable_ref: ref_type('Deliverable')
    requested_use: ServiceUse
    code: TextId
    original_record_ref: Reference
    content_sha256: Digest


class ArchitectSubmissionReleaseRecordView(CostSource):
    ref: Reference
    deliverable_ref: ref_type('Deliverable')
    requested_use: ServiceUse
    code: TextId
    record_kind: Literal['professional_check', 'regulatory_permission', 'owner_use', 'actor_authority', 'condition_satisfied']
    satisfied: ValueState[bool]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    verified_at: TimePoint


class ArchitectSubmissionSavedView(CostSource):
    ref: ref_type('DeliverableSubmission')
    deliverable_ref: ref_type('Deliverable')
    organization_id: TextId
    command_id: TextId
    business_key: TextId
    payload_sha256: Digest
    status: Literal['committed', 'unknown', 'rejected', 'confirmed_uncommitted']


def architect_submission_schemas():
    return service_intake_schemas(overrides={
        'Deliverable': ArchitectSubmissionDeliverableView, 'SubmissionProfile': ArchitectSubmissionProfileView,
        'IntegrationRegistration': ArchitectIntegrationRegistrationView,
        'PublicationAuthority': ArchitectPublicationAuthorityView, 'TaskCompletion': ArchitectTaskCompletionView,
        'MethodResult': ArchitectSubmissionCheckView, 'WorkFact': ArchitectPlanningWorkFactView,
        'PublicationRecipient': ArchitectSubmissionRecipientView, 'ReviewRequirement': ArchitectSubmissionReviewView,
        'Issue': ArchitectSubmissionIssueView, 'ReleaseBasis': ArchitectSubmissionReleaseBasisView,
        'DeliverableSubmission': ArchitectSubmissionSavedView,
        **{kind: ArchitectSubmissionReleaseRecordView for kind in ('ReleaseVerification', 'Permission', 'ProfessionalReleaseCheck', 'OwnerUseDecision', 'ReleaseAuthorityRecord')},
    })
