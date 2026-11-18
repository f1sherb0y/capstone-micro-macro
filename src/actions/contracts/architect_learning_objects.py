"""Private feedback, finite judgment choices and separately approved training."""
from typing import Literal

from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.architect_learning import ArchitectFeedbackRule, ArchitectFeedbackInput, ArchitectFeedbackReport, ArchitectTrainingInput, ArchitectTrainingReport


class ArchitectJudgmentChange(StrictRecord):
    dimension_ref: ref_type('JudgmentDimension')
    selected_value_ref: ref_type('JudgmentValue')
    explanation: TextId


class ArchitectLearningJudgment(StrictRecord):
    prior_strategy_ref: ref_type('Strategy')
    learning_profile_ref: ref_type('LearningProfile')
    evidence_refs: list[ref_type('Evidence')]
    changes: list[ArchitectJudgmentChange]


class ArchitectTrainingRequest(StrictRecord):
    scope: ScopeRef
    purpose: Literal['training']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    questions: list[ArchitectOpportunityQuestion]


class ArchitectLearningStrategyView(GovReviewAuthored):
    ref: ref_type('Strategy')
    organization_id: TextId
    learning_state_ref: ref_type('ArchitectLearningState')
    decision_profile_ref: ref_type('ArchitectLearningDecision')
    judgments: list[ArchitectJudgmentChange]
    effect: Literal['future_business_judgments_only']


class ArchitectLearningStateView(CostSource):
    ref: ref_type('ArchitectLearningState')
    organization_id: TextId
    strategy_ref: ref_type('Strategy')
    capability_ref: ref_type('Capability')
    learning_profile_ref: ref_type('LearningProfile') | None
    received_feedback_refs: list[ref_type('Feedback')]
    applied_feedback_refs: list[ref_type('Feedback')]
    execution_refs: list[ref_type('ArchitectLearningExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class ArchitectLearningDecisionView(GovReviewAuthored):
    monthly_client_task_ref: ref_type('ClientRelationshipTask') | None = None
    monthly_client_observation_ref: ref_type('ClientRelationshipObservation') | None = None
    monthly_portfolio_policy_ref: ref_type('MonthlyPortfolioPolicy') | None = None
    monthly_portfolio_observation_ref: ref_type('MonthlyPortfolioObservation') | None = None
    monthly_method_policy_ref: ref_type('MonthlyMethodPolicy') | None = None
    monthly_method_observation_ref: ref_type('MonthlyMethodObservation') | None = None
    ref: ref_type('ArchitectLearningDecision')
    strategy_ref: ref_type('Strategy')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    business_key: TextId
    choice: Literal['record_feedback','update_judgment','propose_training']
    feedback_refs: list[ref_type('Feedback')]
    interpretation: TextId
    assessment_ref: ref_type('ArchitectLearningAssessment') | None
    training_profile_ref: ref_type('TrainingRequestProfile') | None


class ArchitectLearningCapabilityView(GovReviewAuthored):
    ref: ref_type('Capability')
    organization_id: TextId
    verified_capability_codes: list[TextId]
    qualification_refs: list[ref_type('Qualification')]
    status: Literal['current','unknown']


class ArchitectFeedbackOutcome(StrictRecord):
    dimension_ref: ref_type('JudgmentDimension')
    outcome_code: TextId


class ArchitectFeedbackEvent(StrictRecord):
    event_key: TextId
    subject_ref: Reference
    subject_sha256: Digest
    occurred_at: TimePoint
    kind: Literal['review','performance','fees','use','market']
    outcomes: list[ArchitectFeedbackOutcome]


class ArchitectLearningFeedbackView(GovReviewAuthored):
    ref: ref_type('Feedback')
    recipient_organization_id: TextId
    received_at: TimePoint
    event: ArchitectFeedbackEvent
    event_sha256: Digest
    verified: ValueState[bool]
    status: Literal['verified','unverified','unknown','failed']


class ArchitectLearningProfileView(GovReviewAuthored):
    ref: ref_type('LearningProfile')
    organization_id: TextId
    strategy_ref: ref_type('Strategy')
    enabled: ValueState[bool]
    calculation_method_ref: ref_type('Method')
    dimension_refs: list[ref_type('JudgmentDimension')]
    rule_refs: list[ref_type('LearningRule')]
    training_profile_refs: list[ref_type('TrainingRequestProfile')]
    effect: Literal['future_judgments_and_training_proposals_only']


class ArchitectLearningDimensionView(GovReviewAuthored):
    ref: ref_type('JudgmentDimension')
    organization_id: TextId
    learning_profile_ref: ref_type('LearningProfile')
    value_refs: list[ref_type('JudgmentValue')]
    outcome_codes: list[TextId]
    purpose: Literal['service_direction','quotation','cooperation','design_experience']


class ArchitectLearningValueView(GovReviewAuthored):
    ref: ref_type('JudgmentValue')
    organization_id: TextId
    dimension_ref: ref_type('JudgmentDimension')
    description: TextId
    effect: Literal['future_private_judgment_only']


class ArchitectLearningRuleView(GovReviewAuthored):
    ref: ref_type('LearningRule')
    organization_id: TextId
    learning_profile_ref: ref_type('LearningProfile')
    rule: ArchitectFeedbackRule
    explanation: TextId


class ArchitectLearningAssessmentView(GovReviewAuthored):
    ref: ref_type('ArchitectLearningAssessment')
    organization_id: TextId
    strategy_ref: ref_type('Strategy')
    learning_profile_ref: ref_type('LearningProfile')
    data: ArchitectFeedbackInput
    input_sha256: Digest
    report: ArchitectFeedbackReport | None
    status: Literal['ok','unknown','failed','unsupported']


class ArchitectTrainingProfileView(GovReviewAuthored):
    ref: ref_type('TrainingRequestProfile')
    organization_id: TextId
    learning_profile_ref: ref_type('LearningProfile')
    capability_ref: ref_type('Capability')
    request: ArchitectTrainingRequest
    authority_ref: ref_type('Authority')
    estimate_ref: ref_type('TrainingEstimate')


class ArchitectTrainingWorkView(GovReviewAuthored):
    ref: ref_type('WorkProfile')
    organization_id: TextId
    training_profile_ref: ref_type('TrainingRequestProfile')
    calculation_method_ref: ref_type('Method')
    data: ArchitectTrainingInput
    supported: ValueState[bool]


class ArchitectTrainingEstimateView(GovReviewAuthored):
    ref: ref_type('TrainingEstimate')
    organization_id: TextId
    work_profile_ref: ref_type('WorkProfile')
    input_sha256: Digest
    report: ArchitectTrainingReport | None
    executed_at: TimePoint
    status: Literal['ok','unknown','failed','unsupported']


class ArchitectTrainingAuthorityView(GovReviewAuthored):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    training_profile_ref: ref_type('TrainingRequestProfile')
    capability_ref: ref_type('Capability')
    permitted: ValueState[bool]
    allowed_input_refs: list[Reference]
    allowed_participant_ids: list[TextId]
    allowed_output_requirement_refs: list[ref_type('DeliverableRequirement')]
    budget_limit: Money
    actual_spent: Money
    reserved_cost: Money
    available_effort: Measured
    allowed_window: TimeWindow
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class ArchitectTrainingRequirementView(GovReviewAuthored):
    ref: ref_type('DeliverableRequirement')
    organization_id: TextId
    training_profile_ref: ref_type('TrainingRequestProfile')
    measurable_criterion: TextId
    independent_verifier_id: TextId
    requested_use: Literal['capability_evaluation_only']


class ArchitectTrainingDependencyView(CostSource):
    ref: ref_type('Dependency')
    training_profile_ref: ref_type('TrainingRequestProfile')
    satisfied: ValueState[bool]


class ArchitectLearningExecutionView(CostSource):
    ref: ref_type('ArchitectLearningExecution')
    organization_id: TextId
    run_id: TextId
    strategy_ref: ref_type('Strategy')
    business_key: TextId
    decision_ref: ref_type('ArchitectLearningDecision')
    decision_sha256: Digest
    status: Literal['pending','unknown','succeeded','failed','rejected']


class ArchitectTrainingTaskView(GovReviewAuthored):
    """Actual task registration linked to one original private training proposal."""
    ref: ref_type('TrainingTask')
    organization_id: TextId
    run_id: TextId
    task_sha256: TextId
    record_sha256: TextId
    decision_ref: ref_type('ArchitectLearningDecision')
    decision_sha256: TextId
    business_key: TextId
    training_profile_ref: ref_type('TrainingRequestProfile')
    estimate_ref: ref_type('TrainingEstimate')
    request: ArchitectTrainingRequest
    registration_status: Literal['pending','unknown','registered','rejected']
    execution_status: Literal['not_started','unknown','running','completed','failed','cancelled']


def architect_learning_types():
    from src.actions.contracts.architect_client_relationship import ClientRelationshipTask, ClientRelationshipObservation
    from src.actions.contracts.architect_monthly_portfolio import MonthlyPortfolioPolicy, MonthlyPortfolioObservation
    from src.actions.contracts.professional_monthly_methods import MonthlyMethodPolicy, MonthlyMethodObservation
    return {
        'ClientRelationshipTask':ClientRelationshipTask,'ClientRelationshipObservation':ClientRelationshipObservation,
        'MonthlyPortfolioPolicy':MonthlyPortfolioPolicy,'MonthlyPortfolioObservation':MonthlyPortfolioObservation,
        'MonthlyMethodPolicy':MonthlyMethodPolicy,'MonthlyMethodObservation':MonthlyMethodObservation,
        'Strategy':ArchitectLearningStrategyView,'ArchitectLearningState':ArchitectLearningStateView,
        'ArchitectLearningDecision':ArchitectLearningDecisionView,'Capability':ArchitectLearningCapabilityView,
        'Feedback':ArchitectLearningFeedbackView,'LearningProfile':ArchitectLearningProfileView,
        'JudgmentDimension':ArchitectLearningDimensionView,'JudgmentValue':ArchitectLearningValueView,
        'LearningRule':ArchitectLearningRuleView,'ArchitectLearningAssessment':ArchitectLearningAssessmentView,
        'TrainingRequestProfile':ArchitectTrainingProfileView,'WorkProfile':ArchitectTrainingWorkView,
        'TrainingEstimate':ArchitectTrainingEstimateView,'Authority':ArchitectTrainingAuthorityView,
        'DeliverableRequirement':ArchitectTrainingRequirementView,'Dependency':ArchitectTrainingDependencyView,
        'ArchitectLearningExecution':ArchitectLearningExecutionView,
        'TrainingTask':ArchitectTrainingTaskView,
    }


def architect_learning_schemas():
    return contractor_bid_schemas(architect_learning_types())
