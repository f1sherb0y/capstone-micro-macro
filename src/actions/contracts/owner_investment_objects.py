"""Closed sourced projections for OWN-A03 comparison and bounded authority."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from src.actions.contracts.common import Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_objects import OwnerCaseView, OwnerObjectiveView, OwnerOrganizationView, SourcedOwnerProjection
from src.actions.contracts.owner_proposal_objects import ProposalPriorBriefView
from src.actions.contracts.owner_study_objects import StudyScopeChoice, StudyResourceLoad, unique_refs
from src.methods.owner_investment import OptionCriterion


class InvestmentCaseView(OwnerCaseView):
    comparison_refs: list[ref_type('OptionComparison')]
    brief_refs: list[ref_type('OwnerBrief')]
    issue_refs: list[ref_type('Issue')]

    @model_validator(mode='after')
    def unique_associations(self):
        for rows in (self.comparison_refs, self.brief_refs, self.issue_refs): unique_refs(rows)
        return self


class InvestmentObjectiveView(OwnerObjectiveView):
    criteria: ValueState[Annotated[list[OptionCriterion], Field(min_length=1, max_length=32)]]


class InvestmentFundingLine(StrictRecord):
    window_ref: ref_type('TimeWindow')
    source_ref: ref_type('FundingSource')
    available: ValueState[Money]
    planned_use: ValueState[Money]
    restriction_refs: list[ref_type('FundingRestriction')]


class InvestmentIssueView(SourcedOwnerProjection):
    ref: ref_type('Issue')
    case_ref: ref_type('OwnerCase')
    comparison_ref: ref_type('OptionComparison')
    option_refs: list[ref_type('ProjectOption')]
    scope: ScopeRef
    remedy: Literal['revise', 'study_more']
    status: Literal['unresolved', 'resolved']
    available_at: TimePoint
    effective_window: TimeWindow


class InvestmentComparisonView(SourcedOwnerProjection):
    ref: ref_type('OptionComparison')
    organization_id: TextId
    case_ref: ref_type('OwnerCase')
    objective_ref: ref_type('OwnerObjective')
    scope: ScopeRef
    option_refs: Annotated[list[ref_type('ProjectOption')], Field(min_length=1, max_length=64)]
    non_build_option_refs: Annotated[list[ref_type('ProjectOption')], Field(min_length=1)]
    issue_refs: list[ref_type('Issue')]
    required_analysis_codes: Annotated[list[TextId], Field(min_length=1)]
    status: Literal['comparable', 'not_comparable']
    algorithm_code: TextId
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_options(self):
        for rows in (self.option_refs, self.non_build_option_refs, self.issue_refs): unique_refs(rows)
        if not set(self.non_build_option_refs) <= set(self.option_refs): raise ValueError('Baseline is outside comparison')
        if len(set(self.required_analysis_codes)) != len(self.required_analysis_codes): raise ValueError('Required analysis code repeated')
        return self


ResearchDigest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class InvestmentResearchOptionLink(StrictRecord):
    research_option_ref: ref_type('DesignOption')
    investment_option_ref: ref_type('ProjectOption')


class InvestmentResearchReceiptView(SourcedOwnerProjection):
    """Actual received preliminary report; no investment forecast is inferred."""
    ref: ref_type('ResearchComparisonReceipt')
    run_id: TextId
    recipient_organization_id: TextId
    author_organization_id: TextId
    case_ref: ref_type('OwnerCase')
    comparison_ref: ref_type('OptionComparison')
    source_task_sha256: ResearchDigest
    source_record_sha256: ResearchDigest
    source_result_sha256: ResearchDigest
    source_reading_sha256: ResearchDigest
    report: dict
    option_links: Annotated[list[InvestmentResearchOptionLink], Field(min_length=1)]
    available_at: TimePoint
    effective_window: TimeWindow


class InvestmentMetricBounds(StrictRecord):
    lower: Measured
    upper: Measured


class InvestmentForecastMetric(StrictRecord):
    code: TextId
    value: ValueState[InvestmentMetricBounds]


class InvestmentAnalysisView(SourcedOwnerProjection):
    ref: ref_type('OptionAnalysis')
    organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    authority_action_id: TextId
    qualified: ValueState[bool]
    option_ref: ref_type('ProjectOption')
    brief_ref: ref_type('OwnerBrief')
    objective_ref: ref_type('OwnerObjective')
    analysis_code: TextId
    metrics: list[InvestmentForecastMetric]
    status: Literal['final', 'draft', 'withdrawn']
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_metrics(self):
        if len({row.code for row in self.metrics}) != len(self.metrics): raise ValueError('Analysis metric repeated')
        return self


class InvestmentConditionView(SourcedOwnerProjection):
    ref: ref_type('Requirement')
    organization_id: TextId
    responsible_id: TextId
    case_ref: ref_type('OwnerCase')
    option_ref: ref_type('ProjectOption')
    scope: ScopeRef
    condition_code: TextId
    verification: Literal['met', 'unmet', 'unknown']
    verification_evidence_refs: list[ref_type('Evidence')]
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId
    verified_at: TimePoint
    effective_window: TimeWindow


class InvestmentWorkView(SourcedOwnerProjection):
    ref: ref_type('WorkScope')
    case_ref: ref_type('OwnerCase')
    option_ref: ref_type('ProjectOption')
    permitted_choices: list[Literal['authorize_preparation', 'invest']]
    effective_window: TimeWindow


class InvestmentCashUse(StrictRecord):
    local_key: TextId
    source_ref: ref_type('FundingSource')
    window_ref: ref_type('TimeWindow')
    amount: ValueState[Money]


class InvestmentAllocation(StrictRecord):
    resource_ref: ref_type('ResourcePool')
    window_ref: ref_type('TimeWindow')
    quantity: ValueState[Measured]


class InvestmentPlanView(SourcedOwnerProjection):
    ref: ref_type('InvestmentPlan')
    organization_id: TextId
    case_ref: ref_type('OwnerCase')
    option_ref: ref_type('ProjectOption')
    choice: Literal['authorize_preparation', 'invest']
    scope: StudyScopeChoice
    cash_uses: list[InvestmentCashUse]
    cost_analysis_ref: ref_type('OptionAnalysis')
    incurred_cost: ValueState[Money]
    expenditure_cap: ValueState[Money]
    allocations: Annotated[list[InvestmentAllocation], Field(min_length=1)]
    required_condition_refs: list[ref_type('Requirement')]
    authority_ref: ref_type('Authorization')
    permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_plan(self):
        unique_refs(self.required_condition_refs)
        if len({row.local_key for row in self.cash_uses}) != len(self.cash_uses): raise ValueError('Proposed cash use repeated')
        return self


class InvestmentOptionView(SourcedOwnerProjection):
    ref: ref_type('ProjectOption')
    organization_id: TextId
    case_ref: ref_type('OwnerCase')
    comparison_ref: ref_type('OptionComparison')
    objective_ref: ref_type('OwnerObjective')
    brief_ref: ref_type('OwnerBrief')
    intervention: Literal['new_build', 'alter', 'extend', 'non_build']
    analysis_refs: Annotated[list[ref_type('OptionAnalysis')], Field(min_length=1)]
    condition_refs: list[ref_type('Requirement')]
    issue_refs: list[ref_type('Issue')]
    preparation_plan_ref: ref_type('InvestmentPlan') | None
    investment_plan_ref: ref_type('InvestmentPlan') | None
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_sources(self):
        for rows in (self.analysis_refs, self.condition_refs, self.issue_refs): unique_refs(rows)
        return self


class InvestmentRegistrationView(SourcedOwnerProjection):
    ref: ref_type('ProjectRegistrationProfile')
    organization_id: TextId
    case_ref: ref_type('OwnerCase')
    comparison_ref: ref_type('OptionComparison')
    policy: ValueState[Literal['evaluate', 'prepare_only', 'reject', 'revise', 'study_more', 'defer']]
    on_infeasible: ValueState[Literal['reject', 'revise', 'study_more', 'defer']]
    followup_issue_refs: list[ref_type('Issue')]
    followup_option_refs: list[ref_type('ProjectOption')]
    permitted_scope: ScopeRef
    registration_code: TextId
    required_investment_condition_codes: Annotated[list[TextId], Field(min_length=1)]
    available_at: TimePoint
    effective_window: TimeWindow


class InvestmentFundingRelease(StrictRecord):
    ref: ref_type('FundingRelease')
    time: TimePoint
    amount: ValueState[Money]
    state: Literal['committed', 'forecast', 'cancelled', 'received']
    arrangement_ref: ref_type('FinanceArrangement') | None
    condition_refs: list[ref_type('Requirement')]
    available_at: TimePoint


class InvestmentFinanceView(SourcedOwnerProjection):
    ref: ref_type('FinanceArrangement')
    borrower_organization_id: TextId
    source_ref: ref_type('FundingSource')
    status: Literal['active', 'suspended', 'expired']
    undrawn_amount: ValueState[Money]
    condition_refs: list[ref_type('Requirement')]
    effective_window: TimeWindow


class InvestmentFundingSourceView(SourcedOwnerProjection):
    ref: ref_type('FundingSource')
    organization_id: TextId
    actual_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    deduction_policy: ValueState[Literal['actual_less_restrictions_only']]
    releases: list[InvestmentFundingRelease]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def unique_releases(self):
        unique_refs([row.ref for row in self.releases])
        return self


class InvestmentFundingRestrictionView(SourcedOwnerProjection):
    ref: ref_type('FundingRestriction')
    source_ref: ref_type('FundingSource')
    organization_id: TextId
    permitted_scope: ScopeRef
    permitted: ValueState[bool]
    effective_window: TimeWindow


class InvestmentObligationView(SourcedOwnerProjection):
    ref: ref_type('Obligation')
    debtor_organization_id: TextId
    source_ref: ref_type('FundingSource')
    origin_ref: ref_type('OwnerCase') | ref_type('Project')
    actual_due: ValueState[Money]
    actual_paid: ValueState[Money]
    due_at: TimePoint
    as_of: TimePoint


class InvestmentPortfolioView(SourcedOwnerProjection):
    ref: ref_type('OwnerPortfolio')
    organization_id: TextId
    source_refs: Annotated[list[ref_type('FundingSource')], Field(min_length=1)]
    obligation_refs: list[ref_type('Obligation')]
    funding_lines: list[InvestmentFundingLine]
    resource_refs: list[ref_type('ResourcePool')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def unique_inventory(self):
        for rows in (self.source_refs, self.obligation_refs, self.resource_refs): unique_refs(rows)
        keys = [(row.source_ref.kind, row.source_ref.id, row.window_ref.kind, row.window_ref.id) for row in self.funding_lines]
        if len(set(keys)) != len(keys): raise ValueError('Funding period repeated across versions')
        return self


class InvestmentResourceView(SourcedOwnerProjection):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    total: ValueState[Measured]
    commitments: list[StudyResourceLoad]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    effective_window: TimeWindow

    @model_validator(mode='after')
    def physical_commitments(self):
        unique_refs([row.ref for row in self.commitments])
        return self


def owner_investment_schemas():
    registry = common_projection_schemas()
    for kind, schema in (('Organization', OwnerOrganizationView), ('OwnerCase', InvestmentCaseView),
        ('OwnerObjective', InvestmentObjectiveView), ('OwnerBrief', ProposalPriorBriefView), ('OptionComparison', InvestmentComparisonView),
        ('ResearchComparisonReceipt', InvestmentResearchReceiptView),
        ('ProjectOption', InvestmentOptionView), ('OptionAnalysis', InvestmentAnalysisView), ('InvestmentPlan', InvestmentPlanView),
        ('ProjectRegistrationProfile', InvestmentRegistrationView), ('OwnerPortfolio', InvestmentPortfolioView),
        ('FundingSource', InvestmentFundingSourceView), ('FundingRestriction', InvestmentFundingRestrictionView),
        ('FinanceArrangement', InvestmentFinanceView),
        ('Obligation', InvestmentObligationView), ('ResourcePool', InvestmentResourceView), ('Issue', InvestmentIssueView),
        ('Requirement', InvestmentConditionView), ('WorkScope', InvestmentWorkView)):
        registry.register_kind(kind, schema, str)
    return registry
