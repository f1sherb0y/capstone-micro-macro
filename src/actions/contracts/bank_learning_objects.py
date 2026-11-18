"""Private learned outcomes retain immutable original information and future strategy."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView
from src.actions.contracts.bank_strategy_objects import LendingStrategyView
from src.methods.bank_learning import BankLearningInput, BankLearningReport


class BankLearningOrganizationView(ServiceScopeOrganizationView):
    learning_state_ref: ref_type('BankLearningState')


class BankLearningCaseView(ServiceScopeCaseView):
    learning_state_ref: ref_type('BankLearningState')


class BankLearningProjectView(ServiceScopeProjectView):
    learning_state_ref: ref_type('BankLearningState')


class BankLearningStateView(CostSource):
    ref: ref_type('BankLearningState')
    organization_id: TextId
    profile_ref: ref_type('BankLearningProfile')
    observation_refs: list[ref_type('Observation')]
    judgment_refs: list[ref_type('BankJudgment')]
    outcome_refs: list[ref_type('VerifiedOutcome')]
    allowed_strategy_refs: list[ref_type('LendingStrategyProfile')]
    execution_refs: list[ref_type('BankLearningExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class BankLearningProfileView(CostSource):
    ref: ref_type('BankLearningProfile')
    organization_id: TextId
    state_ref: ref_type('BankLearningState')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['retain_judgment','record_lesson','revise_strategy']
    business_key: TextId
    source_refs: list[ref_type('Observation')]
    assessment_ref: ref_type('BankLearningAssessment') | None
    strategy_ref: ref_type('LendingStrategyProfile') | None
    note: TextId


class BankLearningObservationView(GovReviewAuthored):
    ref: ref_type('Observation')
    recipient_organization_id: TextId
    event_id: TextId
    outcome_ref: ref_type('VerifiedOutcome')
    observed_at: TimePoint
    learned_at: TimePoint
    measure: ValueState[Measured] | None = None


class BankJudgmentView(GovReviewAuthored):
    ref: ref_type('BankJudgment')
    lender_id: TextId
    dimension_ref: ref_type('RiskDimension')
    event_code: TextId
    evaluation_window: TimeWindow
    predicted_probability: ValueState[DecimalString]
    information_refs: list[ref_type('BankInformation')]
    information_sha256: list[Digest]
    classification: Literal['immutable_original_prediction']


class BankHistoricalInformationView(CostSource):
    ref: ref_type('BankInformation')
    recipient_organization_id: TextId
    known_at: TimePoint
    content_sha256: Digest
    classification: Literal['immutable_original_information']


class BankVerifiedOutcomeView(GovReviewAuthored):
    ref: ref_type('VerifiedOutcome')
    lender_id: TextId
    judgment_ref: ref_type('BankJudgment')
    judgment_sha256: Digest
    dimension_ref: ref_type('RiskDimension')
    event_code: TextId
    evaluation_window: TimeWindow
    physical_outcome_key: TextId
    occurred: ValueState[bool]
    status: Literal['verified','immature','unknown','failed','unsupported']


class BankLearningDimensionView(CostSource):
    ref: ref_type('RiskDimension')
    lender_id: TextId
    event_code: TextId


class BankLearningMethodView(GovReviewAuthored):
    ref: ref_type('LearningMethod')
    lender_id: TextId
    calculation_method_ref: ref_type('Method')
    dimension_refs: list[ref_type('RiskDimension')]
    supported: ValueState[bool]
    policy_rule_refs: list[ref_type('BankLearningPolicyRule')]


class BankLearningPolicyRuleView(GovReviewAuthored):
    ref: ref_type('BankLearningPolicyRule')
    lender_id: TextId
    learning_method_ref: ref_type('LearningMethod')
    strategy_ref: ref_type('LendingStrategyProfile')
    strategy_sha256: Digest
    dimension_ref: ref_type('RiskDimension')
    minimum_samples: int
    maximum_mean_squared_error: DecimalString
    permitted: ValueState[bool]
    effect: Literal['future_strategy_only']


class BankLearningAssessmentView(GovReviewAuthored):
    ref: ref_type('BankLearningAssessment')
    lender_id: TextId
    learning_method_ref: ref_type('LearningMethod')
    data: BankLearningInput
    input_sha256: Digest
    report: BankLearningReport | None
    status: Literal['ok','unknown','failed','unsupported']


class BankLearningExecutionView(CostSource):
    ref: ref_type('BankLearningExecution')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('BankLearningProfile')
    profile_sha256: Digest
    applied_outcome_refs: list[ref_type('VerifiedOutcome')]
    status: Literal['pending','unknown','succeeded','failed','rejected']


def bank_learning_schemas():
    return contractor_bid_schemas({
        'Organization':BankLearningOrganizationView,'OwnerCase':BankLearningCaseView,'Project':BankLearningProjectView,
        'BankLearningState':BankLearningStateView,'BankLearningProfile':BankLearningProfileView,
        'Observation':BankLearningObservationView,'BankJudgment':BankJudgmentView,'BankInformation':BankHistoricalInformationView,
        'VerifiedOutcome':BankVerifiedOutcomeView,'RiskDimension':BankLearningDimensionView,
        'LearningMethod':BankLearningMethodView,'BankLearningPolicyRule':BankLearningPolicyRuleView,
        'BankLearningAssessment':BankLearningAssessmentView,'BankLearningExecution':BankLearningExecutionView,
        'LendingStrategyProfile':LendingStrategyView,
    })
