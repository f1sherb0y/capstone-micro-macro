"""Immutable original QS forecasts and received, lawfully usable cost outcomes."""
from typing import Literal

from src.actions.contracts import architect_learning_objects as shared
from src.actions.contracts.common import Money, Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.methods.qs_learning import QSForecastBasis, QSForecastComparisonInput, QSForecastComparisonReport


class QSLearningStrategyView(shared.ArchitectLearningStrategyView):
    learning_state_ref: ref_type('QSLearningState')
    decision_profile_ref: ref_type('QSLearningDecision')


class QSLearningStateView(shared.ArchitectLearningStateView):
    ref: ref_type('QSLearningState')
    forecast_refs: list[ref_type('CostPlan')]
    outcome_refs: list[ref_type('Outcome')]
    applied_error_pair_keys: list[TextId]
    execution_refs: list[ref_type('QSLearningExecution')]


class QSLearningDecisionView(shared.ArchitectLearningDecisionView):
    ref: ref_type('QSLearningDecision')
    choice: Literal['record_feedback','analyze_error','update_judgment','propose_training']
    forecast_ref: ref_type('CostPlan') | None
    outcome_ref: ref_type('Outcome') | None
    error_result_ref: ref_type('MethodResult') | None
    assessment_ref: ref_type('QSLearningAssessment') | None
    monthly_estimation_policy_ref: ref_type('MonthlyEstimationPolicy') | None = None
    monthly_estimation_observation_ref: ref_type('MonthlyEstimationObservation') | None = None


class QSLearningAssessmentView(shared.ArchitectLearningAssessmentView):
    ref: ref_type('QSLearningAssessment')


class QSLearningExecutionView(shared.ArchitectLearningExecutionView):
    ref: ref_type('QSLearningExecution')
    decision_ref: ref_type('QSLearningDecision')


class QSTrainingTaskView(GovReviewAuthored):
    """Actual task registration linked to one original private training proposal."""
    ref: ref_type('TrainingTask')
    organization_id: TextId
    run_id: TextId
    task_sha256: TextId
    record_sha256: TextId
    decision_ref: ref_type('QSLearningDecision')
    decision_sha256: TextId
    business_key: TextId
    training_profile_ref: ref_type('TrainingRequestProfile')
    estimate_ref: ref_type('TrainingEstimate')
    request: shared.ArchitectTrainingRequest
    registration_status: Literal['pending','unknown','registered','rejected']
    execution_status: Literal['not_started','unknown','running','completed','failed','cancelled']


class QSExperienceDimensionView(shared.ArchitectLearningDimensionView):
    purpose: Literal['estimation_assumptions','business_selection','cooperation','quotation','cost_experience']


class QSHistoricalCostPlanView(GovReviewAuthored):
    ref: ref_type('CostPlan')
    organization_id: TextId
    forecast_key: TextId
    information_refs: list[ref_type('ForecastInformation')]
    comparison_basis: QSForecastBasis
    predicted_total: ValueState[Money]
    frozen_at: TimePoint
    immutable_source_ref: ref_type('ForecastSnapshot')
    immutable_source_sha256: TextId


class QSFrozenForecastView(GovReviewAuthored):
    ref: ref_type('ForecastSnapshot')
    organization_id: TextId
    forecast_ref: ref_type('CostPlan')
    forecast_key: TextId
    information_refs: list[ref_type('ForecastInformation')]
    comparison_basis: QSForecastBasis
    predicted_total: ValueState[Money]
    frozen_at: TimePoint


class QSForecastInformationView(GovReviewAuthored):
    ref: ref_type('ForecastInformation')
    organization_id: TextId
    forecast_ref: ref_type('CostPlan')
    original_source_ref: Reference
    original_source_sha256: TextId
    received_at: TimePoint


class QSOriginalOutcomeFacts(StrictRecord):
    provider_organization_id: TextId
    event_key: TextId
    forecast_key: TextId
    forecast_ref: ref_type('CostPlan')
    forecast_sha256: TextId
    actual_total: ValueState[Money]
    comparison_basis: QSForecastBasis
    occurred_at: TimePoint


class QSReceivedOutcomeView(GovReviewAuthored, QSOriginalOutcomeFacts):
    ref: ref_type('Outcome')
    recipient_organization_id: TextId
    received_at: TimePoint
    access_basis_ref: ref_type('OutcomeAccess')
    verified: ValueState[bool]
    status: Literal['verified','immature','unknown','failed']


class QSOutcomeAccessView(GovReviewAuthored):
    ref: ref_type('OutcomeAccess')
    outcome_ref: ref_type('Outcome')
    provider_organization_id: TextId
    recipient_organization_id: TextId
    permitted: ValueState[bool]
    use: Literal['private_estimation_learning_only']


class QSComparisonResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    organization_id: TextId
    method_ref: ref_type('Method')
    data: QSForecastComparisonInput
    input_sha256: TextId
    report: QSForecastComparisonReport | None
    executed_at: TimePoint
    status: Literal['ok','unknown','failed','unsupported']


def qs_learning_types():
    from src.actions.contracts.qs_monthly_estimation import MonthlyEstimationPolicy, MonthlyEstimationObservation
    return {**shared.architect_learning_types(),
        'MonthlyEstimationPolicy':MonthlyEstimationPolicy,'MonthlyEstimationObservation':MonthlyEstimationObservation,
        'Strategy':QSLearningStrategyView,'ArchitectLearningState':QSLearningStateView,
        'ArchitectLearningDecision':QSLearningDecisionView,'ArchitectLearningAssessment':QSLearningAssessmentView,
        'ArchitectLearningExecution':QSLearningExecutionView,'JudgmentDimension':QSExperienceDimensionView,
        'CostPlan':QSHistoricalCostPlanView,'ForecastSnapshot':QSFrozenForecastView,
        'ForecastInformation':QSForecastInformationView,'Outcome':QSReceivedOutcomeView,
        'OutcomeAccess':QSOutcomeAccessView,'MethodResult':QSComparisonResultView,
        'TrainingTask':QSTrainingTaskView,
    }


def qs_learning_schemas():
    names={'ArchitectLearningState':'QSLearningState','ArchitectLearningDecision':'QSLearningDecision',
        'ArchitectLearningAssessment':'QSLearningAssessment','ArchitectLearningExecution':'QSLearningExecution'}
    return contractor_bid_schemas({names.get(kind,kind):model for kind,model in qs_learning_types().items()})
