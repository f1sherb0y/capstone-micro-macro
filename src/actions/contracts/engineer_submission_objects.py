"""Versioned deliverable submission proposals and independent release evidence."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Reference, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_objects import EngineerServiceTermsView
from src.actions.contracts.engineer_planning_objects import EngineerPlanningWorkFactView
from src.actions.contracts.engineer_design_objects import EngineerDesignDraft
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas

SubmissionChoice = Literal['submit', 'sign', 'release_for_use']
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class EngineerDesignRegistrationView(CostSource):
    """Actual registered artifact retaining the complete original professional draft."""
    ref: ref_type('EngineerDesignRegistration')
    run_id: TextId
    organization_id: TextId
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    draft: EngineerDesignDraft
    task_ref: ref_type('Task')
    appointment_ref: ref_type('Appointment')
    deliverable_ref: ref_type('Deliverable')
    deliverable_sha256: Digest | None
    deliverable_content_sha256: Digest | None
    dependency_refs: list[ref_type('Deliverable')]
    unresolved_issue_refs: list[ref_type('Issue')]
    registration_service_id: TextId
    registration_status: Literal['pending','unknown','registered','failed','rejected']
    authored_at: TimePoint
    registered_at: TimePoint | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class EngineerRevisionRegistrationView(EngineerDesignRegistrationView):
    """Actual A09 registration retaining its original issue and parent lineage."""
    ref: ref_type('EngineerRevisionRegistration')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    prior_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    change_basis_ref: ref_type('ChangeBasis')
    instruction_ref: ref_type('Instruction') | None


class EngineerSubmissionDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    task_ref: ref_type('Task')
    appointment_ref: ref_type('Appointment')
    discipline_codes: list[TextId]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
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


class EngineerSubmissionProfileView(CostSource):
    ref: ref_type('SubmissionProfile')
    deliverable_ref: ref_type('Deliverable')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    publication_authority_ref: ref_type('PublicationAuthority')
    choice: SubmissionChoice
    completion_check_refs: list[ref_type('MethodResult')]
    required_release_codes: list[TextId]
    required_signing_codes: list[TextId]
    signing_condition_kinds: dict[TextId, Literal['signing_authority', 'professional_check', 'qualification', 'independence']]
    recipient_refs: list[ref_type('PublicationRecipient')]
    command_id: TextId
    business_key: TextId
    operation_id: TextId
    submission_refs: list[ref_type('DeliverableSubmission')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    note: TextId


class EngineerPublicationAuthorityView(CostSource):
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


class EngineerTaskCompletionView(CostSource):
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


class EngineerSubmissionCheckView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    deliverable_ref: ref_type('Deliverable')
    content_sha256: Digest
    passed: ValueState[bool]
    purpose: Literal['compilation_complete']
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    executed_at: TimePoint


class EngineerSubmissionRecipientView(CostSource):
    ref: ref_type('PublicationRecipient')
    recipient_id: TextId
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    intake_action_id: TextId
    permitted_uses: list[ServiceUse]


class EngineerSubmissionIssueView(CostSource):
    ref: ref_type('Issue')
    deliverable_ref: ref_type('Deliverable')
    blocking_uses: list[ServiceUse]
    status: Literal['open', 'closed', 'unknown']


class EngineerSubmissionReleaseBasisView(CostSource):
    ref: ref_type('ReleaseBasis')
    deliverable_ref: ref_type('Deliverable')
    deliverable_content_sha256: Digest
    requested_use: ServiceUse
    code: TextId
    original_record_ref: Reference
    content_sha256: Digest


class EngineerSubmissionReleaseRecordView(CostSource):
    ref: Reference
    deliverable_content_sha256: Digest
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


class EngineerSubmissionSavedView(CostSource):
    ref: ref_type('DeliverableSubmission')
    choice: SubmissionChoice
    operation_id: TextId
    deliverable_ref: ref_type('Deliverable')
    organization_id: TextId
    command_id: TextId
    business_key: TextId
    payload_sha256: Digest
    status: Literal['committed', 'unknown', 'rejected', 'confirmed_uncommitted']


class EngineerSigningBasisView(CostSource):
    ref: ref_type('SigningBasis')
    deliverable_ref: ref_type('Deliverable')
    content_sha256: Digest
    appointment_ref: ref_type('Appointment')
    signer_organization_id: TextId
    signer_actor_id: TextId
    signer_function_ref: ref_type('FunctionAssignment')
    requested_use: ServiceUse
    discipline_codes: list[TextId]
    code: TextId
    original_record_ref: ref_type('SigningVerification')
    original_record_sha256: Digest


class EngineerSigningVerificationView(CostSource):
    ref: ref_type('SigningVerification')
    deliverable_ref: ref_type('Deliverable')
    content_sha256: Digest
    appointment_ref: ref_type('Appointment')
    signer_organization_id: TextId
    signer_actor_id: TextId
    signer_function_ref: ref_type('FunctionAssignment')
    requested_use: ServiceUse
    discipline_codes: list[TextId]
    code: TextId
    record_kind: Literal['signing_authority', 'professional_check', 'qualification', 'independence']
    satisfied: ValueState[bool]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    verified_at: TimePoint


def engineer_submission_schemas():
    return service_intake_schemas(overrides={
        'EngineerDesignRegistration': EngineerDesignRegistrationView,
        'EngineerRevisionRegistration': EngineerRevisionRegistrationView,
        'Appointment': EngineerAppointmentView, 'ServiceTerms': EngineerServiceTermsView,
        'SigningBasis': EngineerSigningBasisView, 'SigningVerification': EngineerSigningVerificationView,
        'Deliverable': EngineerSubmissionDeliverableView, 'SubmissionProfile': EngineerSubmissionProfileView,
        'PublicationAuthority': EngineerPublicationAuthorityView, 'TaskCompletion': EngineerTaskCompletionView,
        'MethodResult': EngineerSubmissionCheckView, 'WorkFact': EngineerPlanningWorkFactView,
        'PublicationRecipient': EngineerSubmissionRecipientView,
        'Issue': EngineerSubmissionIssueView, 'ReleaseBasis': EngineerSubmissionReleaseBasisView,
        'DeliverableSubmission': EngineerSubmissionSavedView,
        **{kind: EngineerSubmissionReleaseRecordView for kind in ('ReleaseVerification', 'Permission', 'ProfessionalReleaseCheck', 'OwnerUseDecision', 'ReleaseAuthorityRecord')},
    })
