"""Original commercial transition proposals retain resources, materials and debts."""
from typing import Literal

from src.actions.contracts.common import Measured, Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import ContractorBidCommitmentView, contractor_bid_schemas
from src.actions.contracts.contractor_execution_objects import ContractorInventoryView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.capacity import CapacityInput, CapacityReport, CapacityResource, CapacityCommitment, CapacityDemand
from src.methods.commercial_learning import CommercialLessonInput, CommercialLessonReport
from src.actions.contracts.contractor_monthly_strategy import MonthlyBidStrategyPolicy,MonthlyBidStrategyObservation


class CommercialContinuationStateView(CostSource):
    ref: ref_type('ContinuationState')
    organization_id: TextId
    run_id: TextId
    contract_refs: list[ref_type('Contract')]
    commitment_refs: list[ref_type('ResourceCommitment')]
    resource_calendar_ref: ref_type('ResourceCalendar') | None
    material_refs: list[ref_type('InventoryPosition')]
    obligation_refs: list[ref_type('Obligation')]
    observation_refs: list[ref_type('Observation')]
    work_record_refs: list[ref_type('OriginalWorkRecord')]
    document_refs: list[ref_type('ContinuationDocument')]
    responsibility_refs: list[ref_type('ContinuingResponsibility')]
    execution_refs: list[ref_type('ContinuationExecution')]
    applied_observation_refs: list[ref_type('Observation')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class CommercialContinuationProfileView(GovReviewAuthored):
    monthly_bid_policy_ref: ref_type('MonthlyBidStrategyPolicy') | None = None
    monthly_bid_observation_ref: ref_type('MonthlyBidStrategyObservation') | None = None
    ref: ref_type('ContinuationProfile')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    basis_ref: ref_type('ContinuationBasis')
    business_key: TextId
    choice: Literal['protect','suspend','resume','handover','exit','record_lesson']
    retain_resource_refs: list[ref_type('ResourceCommitment')]
    release_candidate_refs: list[ref_type('ResourceCommitment')]
    readiness_refs: list[ref_type('Verification')]
    transfer_plan_ref: ref_type('ContinuationTransferPlan') | None
    successor_acceptance_ref: ref_type('ContinuationAcceptance') | None = None
    party_consent_refs: list[ref_type('ContinuationConsent')] | None = None
    source_refs: list[ref_type('Observation')]
    learning_method_ref: ref_type('LearningMethod') | None
    lesson_assessment_ref: ref_type('CommercialLessonAssessment') | None
    note: TextId


class CommercialContinuationBasisView(GovReviewAuthored):
    ref: ref_type('ContinuationBasis')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    permitted: ValueState[bool]
    allowed_choices: list[TextId]
    contract_refs: list[ref_type('Contract')]
    protection_task_refs: list[ref_type('ProtectionTask')]
    material_plan_ref: ref_type('MaterialDispositionPlan')
    effect: Literal['proposal_then_actual_core_transition']


class CommercialTransitionContractView(GovReviewAuthored):
    ref: ref_type('Contract')
    party_organization_ids: list[TextId]
    transition_basis_refs: list[ref_type('ContinuationBasis')]
    status: Literal['effective','suspended','terminated','closed']


class CommercialCommitmentView(ContractorBidCommitmentView):
    physical_commitment_key: TextId
    release_rule_ref: ref_type('ResourceReleaseRule')
    status: Literal['held','released','consumed','unknown']
    as_of: TimePoint


class CommercialReleaseRuleView(GovReviewAuthored):
    ref: ref_type('ResourceReleaseRule')
    commitment_ref: ref_type('ResourceCommitment')
    organization_id: TextId
    permitted: ValueState[bool]
    allowed_choices: list[TextId]
    verified: ValueState[bool]
    effect: Literal['after_actual_transition_only']


class CommercialMaterialView(ContractorInventoryView):
    physical_position_key: TextId
    owner_organization_id: TextId
    custodian_organization_id: TextId
    right_ref: ref_type('AssetRight')
    status: Literal['stored','incorporated','returned','damaged','unknown']


class CommercialMaterialDisposition(StrictRecord):
    position_ref: ref_type('InventoryPosition')
    right_ref: ref_type('AssetRight')
    choice: Literal['preserve','retain_custody','return','handover','query_original']
    recipient_organization_id: TextId


class CommercialMaterialPlanView(GovReviewAuthored):
    ref: ref_type('MaterialDispositionPlan')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    items: list[CommercialMaterialDisposition]


class CommercialAssetRightView(GovReviewAuthored):
    ref: ref_type('AssetRight')
    position_ref: ref_type('InventoryPosition')
    owner_organization_id: TextId
    custodian_organization_id: TextId
    permitted_choices: list[TextId]
    allowed_recipient_organization_ids: list[TextId]
    permitted: ValueState[bool]


class CommercialProtectionTaskView(GovReviewAuthored):
    ref: ref_type('ProtectionTask')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    purpose: Literal['site_protection','material_custody','safety','unaffected_obligation']
    required_commitment_refs: list[ref_type('ResourceCommitment')]
    permitted: ValueState[bool]
    status: Literal['required','complete']


class CommercialResponsibilityView(GovReviewAuthored):
    ref: ref_type('ContinuingResponsibility')
    organization_id: TextId
    contract_ref: ref_type('Contract')
    required_commitment_refs: list[ref_type('ResourceCommitment')]
    status: Literal['open','disputed','complete']


class CommercialOriginalWorkView(GovReviewAuthored):
    ref: ref_type('OriginalWorkRecord')
    organization_id: TextId
    contract_ref: ref_type('Contract')
    physical_work_key: TextId
    execution_ref: ref_type('OriginalWorkExecution')
    completed_quantity: ValueState[Measured]
    remaining_quantity: ValueState[Measured]
    status: Literal['completed','unverified','defective','unknown']


class CommercialOriginalExecutionView(CostSource):
    ref: ref_type('OriginalWorkExecution')
    organization_id: TextId
    run_id: TextId
    work_record_ref: ref_type('OriginalWorkRecord')
    status: Literal['succeeded','unknown','pending','failed','rejected']
    as_of: TimePoint


class CommercialDocumentView(GovReviewAuthored):
    ref: ref_type('ContinuationDocument')
    organization_id: TextId
    original_author_id: TextId
    content_sha256: Digest
    licensed_recipient_organization_ids: list[TextId]


class CommercialSourceDigest(StrictRecord):
    source_ref: Reference
    source_sha256: Digest


class CommercialVerificationView(GovReviewAuthored):
    ref: ref_type('Verification')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    state_sha256: Digest
    family: Literal['resources','materials','design','permits','funding','safety']
    source_digests: list[CommercialSourceDigest]
    supported: ValueState[bool]
    ready: ValueState[bool]
    capacity_assessment_ref: ref_type('ContinuationCapacityAssessment') | None
    as_of: TimePoint


class CommercialCapacityAssessmentView(GovReviewAuthored):
    ref: ref_type('ContinuationCapacityAssessment')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    data: CapacityInput
    input_sha256: Digest
    report: CapacityReport | None
    executed_at: TimePoint
    status: Literal['ok','unknown','failed','unsupported']


class CommercialResumeCalendarView(GovReviewAuthored):
    ref: ref_type('ResourceCalendar')
    organization_id: TextId
    resources: list[CapacityResource]
    commitments: list[CapacityCommitment]
    authorized_new_demands: list[CapacityDemand]
    existing_work_commitment_refs: list[ref_type('ResourceCommitment')]
    actual_resource_keys: dict[TextId,TextId]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class CommercialLessonAssessmentView(GovReviewAuthored):
    ref: ref_type('CommercialLessonAssessment')
    organization_id: TextId
    learning_method_ref: ref_type('LearningMethod')
    data: CommercialLessonInput
    input_sha256: Digest
    report: CommercialLessonReport | None
    status: Literal['ok','unknown','failed','unsupported']


class CommercialTransferPlanView(GovReviewAuthored):
    ref: ref_type('ContinuationTransferPlan')
    organization_id: TextId
    state_ref: ref_type('ContinuationState')
    successor_organization_id: TextId
    work_record_refs: list[ref_type('OriginalWorkRecord')]
    material_refs: list[ref_type('InventoryPosition')]
    document_refs: list[ref_type('ContinuationDocument')]
    obligation_refs: list[ref_type('Obligation')]
    responsibility_refs: list[ref_type('ContinuingResponsibility')]
    acceptance_ref: ref_type('ContinuationAcceptance')
    consent_refs: list[ref_type('ContinuationConsent')]
    transfer_evidence_refs: list[ref_type('Evidence')]
    effect: Literal['successor_only_new_work_original_debts_retained']


class CommercialAcceptanceView(GovReviewAuthored):
    ref: ref_type('ContinuationAcceptance')
    plan_ref: ref_type('ContinuationTransferPlan')
    plan_sha256: Digest
    successor_organization_id: TextId
    accepted: ValueState[bool]
    as_of: TimePoint


class CommercialConsentView(GovReviewAuthored):
    ref: ref_type('ContinuationConsent')
    contract_ref: ref_type('Contract')
    plan_ref: ref_type('ContinuationTransferPlan')
    plan_sha256: Digest
    party_organization_id: TextId
    accepted: ValueState[bool]


class CommercialObservationView(GovReviewAuthored):
    ref: ref_type('Observation')
    recipient_organization_id: TextId
    event_key: TextId
    original_source_ref: Reference
    source_sha256: Digest
    observed_at: TimePoint
    received_at: TimePoint
    outcome_code: TextId
    verified: ValueState[bool]


class CommercialLearningMethodView(GovReviewAuthored):
    ref: ref_type('LearningMethod')
    organization_id: TextId
    calculation_method_ref: ref_type('Method')
    supported: ValueState[bool]
    outcome_catalog: dict[TextId,TextId]
    effect: Literal['future_private_lesson_only']


class CommercialExecutionView(CostSource):
    ref: ref_type('ContinuationExecution')
    organization_id: TextId
    run_id: TextId
    state_ref: ref_type('ContinuationState')
    business_key: TextId
    profile_ref: ref_type('ContinuationProfile')
    profile_sha256: Digest
    status: Literal['pending','unknown','succeeded','failed','rejected']


def commercial_continuation_types():
    return {'ContinuationState':CommercialContinuationStateView,'ContinuationProfile':CommercialContinuationProfileView,
        'ContinuationBasis':CommercialContinuationBasisView,'Contract':CommercialTransitionContractView,
        'ResourceCommitment':CommercialCommitmentView,'ResourceReleaseRule':CommercialReleaseRuleView,
        'InventoryPosition':CommercialMaterialView,'MaterialDispositionPlan':CommercialMaterialPlanView,
        'AssetRight':CommercialAssetRightView,'ProtectionTask':CommercialProtectionTaskView,
        'ContinuingResponsibility':CommercialResponsibilityView,'OriginalWorkRecord':CommercialOriginalWorkView,
        'OriginalWorkExecution':CommercialOriginalExecutionView,'ContinuationDocument':CommercialDocumentView,
        'Verification':CommercialVerificationView,'ContinuationCapacityAssessment':CommercialCapacityAssessmentView,
        'ContinuationTransferPlan':CommercialTransferPlanView,'ContinuationAcceptance':CommercialAcceptanceView,
        'ContinuationConsent':CommercialConsentView,'Observation':CommercialObservationView,
        'LearningMethod':CommercialLearningMethodView,'CommercialLessonAssessment':CommercialLessonAssessmentView,
        'ResourceCalendar':CommercialResumeCalendarView,'Obligation':OwnerPaymentObligationView,'ContinuationExecution':CommercialExecutionView}


def commercial_continuation_schemas(overrides=None):
    return contractor_bid_schemas({**commercial_continuation_types(),'MonthlyBidStrategyPolicy':MonthlyBidStrategyPolicy,
        'MonthlyBidStrategyObservation':MonthlyBidStrategyObservation,**(overrides or {})})
