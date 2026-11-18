"""Qualification evidence is independent of private experience and training."""
from typing import Literal

from src.actions.contracts import architect_learning_objects as shared
from src.actions.contracts.common import TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored


class EngineerLearningStrategyView(shared.ArchitectLearningStrategyView):
    learning_state_ref: ref_type('EngineerLearningState')
    decision_profile_ref: ref_type('EngineerLearningDecision')


class EngineerLearningStateView(shared.ArchitectLearningStateView):
    ref: ref_type('EngineerLearningState')
    qualification_refs: list[ref_type('Qualification')]
    applied_qualification_event_refs: list[ref_type('QualificationEvent')]
    execution_refs: list[ref_type('EngineerLearningExecution')]


class EngineerLearningDecisionView(shared.ArchitectLearningDecisionView):
    ref: ref_type('EngineerLearningDecision')
    choice: Literal['record_feedback','update_judgment','propose_training','request_qualification_update']
    assessment_ref: ref_type('EngineerLearningAssessment') | None
    qualification_ref: ref_type('Qualification') | None
    qualification_update_basis_ref: ref_type('QualificationUpdateBasis') | None


class EngineerLearningAssessmentView(shared.ArchitectLearningAssessmentView):
    ref: ref_type('EngineerLearningAssessment')


class EngineerLearningExecutionView(shared.ArchitectLearningExecutionView):
    ref: ref_type('EngineerLearningExecution')
    decision_ref: ref_type('EngineerLearningDecision')


class EngineerTrainingTaskView(shared.ArchitectTrainingTaskView):
    """Actual task registration preserves the original Engineer proposal identity."""
    decision_ref: ref_type('EngineerLearningDecision')


class EngineerExperienceDimensionView(shared.ArchitectLearningDimensionView):
    purpose: Literal['risk_judgment','cooperation','service_scope','professional_experience','quotation']


class EngineerQualificationView(GovReviewAuthored):
    ref: ref_type('Qualification')
    organization_id: TextId
    issuer_organization_id: TextId
    credential_key: TextId
    personnel_ids: list[TextId]
    discipline_codes: list[TextId]
    region_ids: list[TextId]
    service_codes: list[TextId]
    validity: TimeWindow
    standing: ValueState[bool]
    status: Literal['current','expired','suspended','revoked','unknown']
    event_refs: list[ref_type('QualificationEvent')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class EngineerQualificationEventView(GovReviewAuthored):
    ref: ref_type('QualificationEvent')
    qualification_ref: ref_type('Qualification')
    organization_id: TextId
    issuer_organization_id: TextId
    credential_key: TextId
    event_key: TextId
    kind: Literal['issuance','renewal','scope_amendment','suspension','revocation','status_confirmation']
    occurred_at: TimePoint
    effective_at: TimePoint
    received_at: TimePoint
    verified: ValueState[bool]
    status: Literal['verified','unknown','failed']
    next_validity: TimeWindow | None
    next_discipline_codes: list[TextId]
    next_region_ids: list[TextId]
    next_service_codes: list[TextId]


class EngineerQualificationUpdateBasisView(GovReviewAuthored):
    ref: ref_type('QualificationUpdateBasis')
    qualification_ref: ref_type('Qualification')
    qualification_event_ref: ref_type('QualificationEvent')
    organization_id: TextId
    issuer_organization_id: TextId
    credential_key: TextId
    allowed_event_kind: Literal['issuance','renewal','scope_amendment','suspension','revocation','status_confirmation']
    permitted: ValueState[bool]
    verification_service_id: TextId
    effect: Literal['qualification_verification_request_only']


class EngineerQualificationVerificationView(GovReviewAuthored):
    """Actual issuer-service verification of one saved qualification request."""
    ref: ref_type('QualificationVerification')
    organization_id: TextId
    run_id: TextId
    issuer_organization_id: TextId
    verification_service_id: TextId
    task_sha256: TextId
    record_sha256: TextId
    decision_ref: ref_type('EngineerLearningDecision')
    decision_sha256: TextId
    business_key: TextId
    qualification_ref: ref_type('Qualification')
    qualification_event_ref: ref_type('QualificationEvent')
    qualification_event_sha256: TextId
    update_basis_ref: ref_type('QualificationUpdateBasis')
    request_evidence_refs: list[ref_type('Evidence')]
    status: Literal['pending','unknown','verified','failed','rejected']


def engineer_learning_types():
    return {**shared.architect_learning_types(),
        'Strategy':EngineerLearningStrategyView,'ArchitectLearningState':EngineerLearningStateView,
        'ArchitectLearningDecision':EngineerLearningDecisionView,'ArchitectLearningAssessment':EngineerLearningAssessmentView,
        'ArchitectLearningExecution':EngineerLearningExecutionView,'JudgmentDimension':EngineerExperienceDimensionView,
        'Qualification':EngineerQualificationView,'QualificationEvent':EngineerQualificationEventView,
        'QualificationUpdateBasis':EngineerQualificationUpdateBasisView,
        'TrainingTask':EngineerTrainingTaskView,
        'QualificationVerification':EngineerQualificationVerificationView,
    }


def engineer_learning_schemas():
    names={'ArchitectLearningState':'EngineerLearningState','ArchitectLearningDecision':'EngineerLearningDecision',
        'ArchitectLearningAssessment':'EngineerLearningAssessment','ArchitectLearningExecution':'EngineerLearningExecution'}
    return contractor_bid_schemas({names.get(kind,kind):model for kind,model in engineer_learning_types().items()})
