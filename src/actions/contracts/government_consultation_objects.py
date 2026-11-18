"""Original consultation channels, disclosure authority and received opinion events."""
from typing import Literal

from src.actions.contracts.common import TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_objects import GovIntakeQuestion, GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.actions.contracts.government_review_objects import GovReviewAuthored, GovReviewSubmissionView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.government_consultation import ConsultationCoverageReport


class GovConsultationCaseView(GovSchedulingCaseView):
    consultation_refs: list[ref_type('Consultation')]


class GovConsultationRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    procedure_ref: ref_type('Procedure')
    authority_ref: ref_type('Authorization')
    applicability_basis_ref: ref_type('ApplicabilityBasis')
    disclosure_authority_ref: ref_type('Authority')
    recipient_refs: list[ref_type('ConsultationRecipient')]
    clock_rule_ref: ref_type('ClockRule')
    question_refs: list[ref_type('EvidenceTarget')]
    referral_recipient_ref: ref_type('RegulatoryRecipient') | None
    analysis_task_ref: ref_type('Task') | None
    analysis_result_ref: ref_type('MethodResult') | None
    choice: Literal['initiate', 'register_response', 'analyze', 'refer']
    modeled: bool


class GovConsultationApplicabilityView(GovReviewAuthored):
    ref: ref_type('ApplicabilityBasis')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    applicable: ValueState[bool]


class GovDisclosurePackageView(GovAdviceSource):
    ref: ref_type('DisclosurePackage')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    submission_sha256: Digest
    content_sha256: Digest
    disclosed_evidence_refs: list[ref_type('Evidence')]
    allowed_recipient_refs: list[ref_type('ConsultationRecipient')]
    status: Literal['authorized', 'draft', 'withdrawn']


class GovDisclosureAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    package_ref: ref_type('DisclosurePackage')
    content_sha256: Digest
    evidence_refs_allowed: list[ref_type('Evidence')]
    recipient_refs: list[ref_type('ConsultationRecipient')]
    referral_recipient_ref: ref_type('RegulatoryRecipient') | None
    permitted: ValueState[bool]
    question_recipient_refs: list[ref_type('RegulatoryRecipient')]


class GovConsultationRecipientView(GovAdviceSource):
    ref: ref_type('ConsultationRecipient')
    case_ref: ref_type('RegulatoryCase')
    procedure_ref: ref_type('Procedure')
    channel_key: TextId
    kind: Literal['department', 'public_channel']
    organization_id: TextId
    representative_actor_id: TextId
    representative_function_ref: ref_type('FunctionAssignment')
    response_action_id: TextId
    required: bool


class GovConsultationClockView(GovAdviceSource):
    ref: ref_type('ClockRule')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    procedure_ref: ref_type('Procedure')
    response_duration_ticks: int


class GovConsultationView(GovAdviceSource):
    ref: ref_type('Consultation')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    procedure_ref: ref_type('Procedure')
    disclosure_package_ref: ref_type('DisclosurePackage')
    content_sha256: Digest
    recipient_refs: list[ref_type('ConsultationRecipient')]
    clock_rule_ref: ref_type('ClockRule')
    delivery_refs: list[ref_type('ConsultationDelivery')]
    response_refs: list[ref_type('ConsultationResponse')]
    registered_event_ids: list[TextId]
    participation_refs: list[ref_type('ParticipationVerification')]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    status: Literal['active', 'withdrawn']


class GovConsultationDeliveryView(GovAdviceSource):
    ref: ref_type('ConsultationDelivery')
    consultation_ref: ref_type('Consultation')
    recipient_ref: ref_type('ConsultationRecipient')
    package_ref: ref_type('DisclosurePackage')
    content_sha256: Digest
    event_id: TextId
    delivered: ValueState[bool]
    delivered_at: TimePoint | None


class GovConsultationResponseView(GovReviewAuthored):
    ref: ref_type('ConsultationResponse')
    consultation_ref: ref_type('Consultation')
    recipient_ref: ref_type('ConsultationRecipient')
    package_ref: ref_type('DisclosurePackage')
    content_sha256: Digest
    event_id: TextId
    received_at: TimePoint
    response_kind: Literal['opinion', 'delivery_receipt']
    position: Literal['support', 'oppose', 'advice', 'unknown']
    status: Literal['received', 'unknown', 'failed']
    issue_question_refs: list[ref_type('EvidenceTarget')]


class GovParticipationView(GovReviewAuthored):
    ref: ref_type('ParticipationVerification')
    consultation_ref: ref_type('Consultation')
    recipient_ref: ref_type('ConsultationRecipient')
    rule_ref: ref_type('Rule')
    satisfied: ValueState[bool]
    started_at: TimePoint
    completed_at: TimePoint | None


class GovConsultationTaskView(GovAdviceSource):
    ref: ref_type('Task')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    consultation_ref: ref_type('Consultation')
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    status: Literal['authorized', 'waiting', 'closed']


class GovConsultationResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    consultation_ref: ref_type('Consultation')
    task_ref: ref_type('Task')
    rule_ref: ref_type('Rule')
    method_ref: ref_type('Method')
    input_sha256: Digest
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    report: ConsultationCoverageReport | None


class GovConsultationQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    case_ref: ref_type('RegulatoryCase')
    question: GovIntakeQuestion


class GovConsultationProcedureView(GovAdviceSource):
    ref: ref_type('Procedure')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    modeled: bool


def government_consultation_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovConsultationCaseView, 'Submission': GovReviewSubmissionView,
        'Rule': GovConsultationRuleView, 'Procedure': GovConsultationProcedureView,
        'ApplicabilityBasis': GovConsultationApplicabilityView, 'DisclosurePackage': GovDisclosurePackageView,
        'Authority': GovDisclosureAuthorityView, 'ConsultationRecipient': GovConsultationRecipientView,
        'ClockRule': GovConsultationClockView, 'Consultation': GovConsultationView,
        'ConsultationDelivery': GovConsultationDeliveryView, 'ConsultationResponse': GovConsultationResponseView,
        'ParticipationVerification': GovParticipationView, 'Task': GovConsultationTaskView,
        'MethodResult': GovConsultationResultView, 'EvidenceTarget': GovConsultationQuestionView,
        'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
        'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
