"""Private owner operating proposals retain the current whole organization ledger."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, Money, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_commission_objects import CommissionAllocation
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.owner_learning import OwnerLearningInput, OwnerLearningReport


class OwnerOperatingPortfolioView(CostSource):
    ref: ref_type('OwnerPortfolio')
    organization_id: TextId
    project_refs: list[ref_type('Project')]
    obligation_refs: list[ref_type('Obligation')]
    observation_refs: list[ref_type('Observation')]
    resource_refs: list[ref_type('ResourcePool')]
    task_refs: list[ref_type('Task')]
    required_task_refs: list[ref_type('Task')]
    current_preference_ref: ref_type('OwnerPreferenceProfile')
    execution_refs: list[ref_type('OwnerOperatingExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    producer: Literal['core']


class OwnerOperatingProfileView(CostSource):
    ref: ref_type('OwnerOperatingProfile')
    organization_id: TextId
    portfolio_ref: ref_type('OwnerPortfolio')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['retain_policy','revise_preferences','revise_research_budget','rebalance_tasks']
    business_key: TextId
    basis_refs: list[ref_type('Observation')]
    preference_profile_ref: ref_type('OwnerPreferenceProfile') | None
    budget_authority_ref: ref_type('ResearchBudgetAuthority') | None
    proposed_limit: Money | None
    allocations: list[CommissionAllocation]
    allocation_task_refs: list[ref_type('Task')]
    replaced_commitment_refs: list[ref_type('ResourceCommitment')]
    allocation_revision_ref: ref_type('AllocationRevisionAuthority') | None
    note: TextId
    monthly_strategy_policy_ref: ref_type('MonthlyInvestmentPolicy') | None = None
    monthly_strategy_observation_ref: ref_type('MonthlyInvestmentObservation') | None = None


class OwnerOperatingProjectView(CostSource):
    ref: ref_type('Project')
    organization_id: TextId
    obligation_refs: list[ref_type('Obligation')]
    status: Literal['preparing','active','suspended','completed','terminated']


class OwnerOperatingObservationView(GovReviewAuthored):
    ref: ref_type('Observation')
    recipient_organization_id: TextId
    event_id: TextId
    observed_at: TimePoint
    kind: Literal['verified_outcome','market','incomplete_status','other']
    outcome_code: TextId | None
    dimension_codes: list[TextId]
    verified: ValueState[bool]


class OwnerOperatingPreferenceView(GovReviewAuthored):
    ref: ref_type('OwnerPreferenceProfile')
    organization_id: TextId
    prior_profile_ref: ref_type('OwnerPreferenceProfile') | None
    purpose: Literal['investment_return','own_use','public_service']
    scores: dict[TextId,DecimalString]
    basis_refs: list[ref_type('Observation')]
    requires_learning: bool
    learning_assessment_ref: ref_type('OwnerLearningAssessment') | None
    effect: Literal['future_preferences_only']


class OwnerLearningMethodView(GovReviewAuthored):
    ref: ref_type('LearningMethod')
    organization_id: TextId
    calculation_method_ref: ref_type('Method')
    supported: ValueState[bool]
    outcome_scores: dict[TextId,DecimalString]
    learning_rates: dict[TextId,DecimalString]


class OwnerLearningAssessmentView(GovReviewAuthored):
    ref: ref_type('OwnerLearningAssessment')
    organization_id: TextId
    prior_profile_ref: ref_type('OwnerPreferenceProfile')
    preference_profile_ref: ref_type('OwnerPreferenceProfile')
    learning_method_ref: ref_type('LearningMethod')
    data: OwnerLearningInput
    input_sha256: Digest
    report: OwnerLearningReport | None
    status: Literal['ok','unknown','failed','unsupported']


class OwnerResearchBudgetView(GovReviewAuthored):
    ref: ref_type('ResearchBudgetAuthority')
    organization_id: TextId
    currency: TextId
    maximum_limit: Money
    actual_spent: Money
    reserved: Money
    permitted: ValueState[bool]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class OwnerOperatingTaskView(GovReviewAuthored):
    ref: ref_type('Task')
    organization_id: TextId
    local_key: TextId
    permitted: ValueState[bool]
    obligation_refs: list[ref_type('Obligation')]
    resource_refs: list[ref_type('ResourcePool')]
    status: Literal['proposed','active','completed','cancelled']


class OwnerOperatingCommitmentView(CostSource):
    ref: ref_type('ResourceCommitment')
    organization_id: TextId
    resource_ref: ref_type('ResourcePool')
    task_ref: ref_type('Task')
    physical_commitment_key: TextId
    capacity_quantity: ValueState[Measured]
    window: TimeWindow
    status: Literal['held','released','unknown','consumed']
    as_of: TimePoint


class OwnerOperatingResourceView(CostSource):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    physical_pool_key: TextId
    region_id: TextId
    total: ValueState[Measured]
    commitment_refs: list[ref_type('ResourceCommitment')]
    permitted: ValueState[bool]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class OwnerAllocationRevisionView(GovReviewAuthored):
    ref: ref_type('AllocationRevisionAuthority')
    organization_id: TextId
    portfolio_ref: ref_type('OwnerPortfolio')
    commitment_refs: list[ref_type('ResourceCommitment')]
    task_refs: list[ref_type('Task')]
    permitted: ValueState[bool]
    mode: Literal['atomic_replace_only']


class OwnerOperatingExecutionView(CostSource):
    ref: ref_type('OwnerOperatingExecution')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('OwnerOperatingProfile')
    profile_sha256: Digest
    applied_observation_refs: list[ref_type('Observation')]
    status: Literal['pending','unknown','succeeded','failed','rejected']


def owner_operating_schemas():
    from src.actions.contracts.owner_monthly_strategy import MonthlyInvestmentPolicy, MonthlyInvestmentObservation
    return contractor_bid_schemas({
        'MonthlyInvestmentPolicy':MonthlyInvestmentPolicy,'MonthlyInvestmentObservation':MonthlyInvestmentObservation,
        'OwnerPortfolio':OwnerOperatingPortfolioView,'OwnerOperatingProfile':OwnerOperatingProfileView,
        'Project':OwnerOperatingProjectView,'Observation':OwnerOperatingObservationView,'OwnerPreferenceProfile':OwnerOperatingPreferenceView,
        'LearningMethod':OwnerLearningMethodView,'OwnerLearningAssessment':OwnerLearningAssessmentView,
        'ResearchBudgetAuthority':OwnerResearchBudgetView,'Task':OwnerOperatingTaskView,'ResourcePool':OwnerOperatingResourceView,
        'ResourceCommitment':OwnerOperatingCommitmentView,'AllocationRevisionAuthority':OwnerAllocationRevisionView,
        'OwnerOperatingExecution':OwnerOperatingExecutionView,'Obligation':OwnerPaymentObligationView,
    })
