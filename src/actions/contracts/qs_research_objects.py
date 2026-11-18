"""Versioned preliminary comparison inputs and original bounded-research records."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import (
    CostSource, QSCostBriefView, QSCostOptionView, QSCostComparisonBasisView,
    QSCostCalculationView, QSCostScopeView, QSCostPriceView, QSQuantityBasisView,
)
from src.actions.contracts.qs_bid_objects import QSCostAdjustment, QSBidCriterion
from src.actions.contracts.service_objects import ServiceUse, ServiceClockView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.pricing import decimal_fraction


class QSResearchDimension(StrictRecord):
    code: TextId
    value: ValueState[TextId]


class QSResearchOptionView(QSCostOptionView):
    comparison_dimensions: list[QSResearchDimension] = Field(default_factory=list)


class QSResearchBasisView(QSCostComparisonBasisView):
    comparison_profile_ref: ref_type('ComparisonProfile') | None = None


class QSResearchAuthorityView(CostSource):
    ref: ref_type('Authority')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    delegate_actor_id: TextId
    delegate_organization_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    client_actor_id: TextId
    client_organization_id: TextId
    client_function_ref: ref_type('FunctionAssignment')
    client_authority_ref: ref_type('Authorization')
    client_action_id: Literal['OWN-A02', 'OWN-A04']
    allowed_uses: list[ServiceUse]
    allowed_purposes: list[Literal['preparation', 'investigation', 'service_delivery']] = Field(default_factory=list)
    granted_at: TimePoint
    permission: ValueState[bool]


class QSResearchTaskView(CostSource):
    ref: ref_type('Task')
    brief_ref: ref_type('Brief')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    option_refs: list[ref_type('DesignOption')]
    assessment_refs: list[ref_type('Assessment')]
    cost_plan_refs: list[ref_type('CostPlan')]
    comparison_basis_ref: ref_type('ComparisonBasis')
    expenditure_limit_ref: ref_type('ResearchLimit')
    request_profile_ref: ref_type('ResearchRequestProfile') | None
    question_refs: list[ref_type('EvidenceTarget')]
    status: Literal['authorized', 'waiting', 'closed']


class QSResearchAssessmentView(CostSource):
    ref: ref_type('Assessment')
    brief_ref: ref_type('Brief')
    option_ref: ref_type('DesignOption')
    status: Literal['ok', 'failed', 'unsupported']
    finding: Literal['compatible', 'conflict', 'uncovered']
    covered_scope_keys: list[TextId]
    allowed_uses: list[ServiceUse]
    limitations: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class QSSavedCostLine(StrictRecord):
    line_key: TextId
    covered_scope: ScopeRef
    cost_component_ref: ref_type('CostComponent')
    quantity: ValueState[Measured]
    price_ref: ref_type('Price') | None
    amount: ValueState[Money]
    basis_refs: list[ref_type('Evidence')]
    calculation_ref: ref_type('MethodResult') | None
    predecessor_line_keys: list[TextId]


class QSResearchQuestion(StrictRecord):
    scope: ScopeRef
    target_refs: list[ref_type('EvidenceTarget')]
    question: str
    recipient_ids: list[TextId]
    evidence_refs: list[ref_type('Evidence')]
    blocking_uses: list[ServiceUse]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSSavedCostDraft(StrictRecord):
    option_ref: ref_type('DesignOption')
    cost_scope_ref: ref_type('CostScope')
    comparison_basis_ref: ref_type('ComparisonBasis')
    quantity_schedule_ref: ref_type('QuantitySchedule') | None
    lines: list[QSSavedCostLine]
    calculation_ref: ref_type('MethodResult') | None
    known_subtotal: ValueState[Money]
    complete_total: Money | None
    missing_items: list[QSResearchQuestion]


class QSResearchCostPlanView(CostSource):
    ref: ref_type('CostPlan')
    brief_ref: ref_type('Brief')
    draft: QSSavedCostDraft
    coverage_keys: list[TextId]
    comparison_dimensions: list[QSResearchDimension]
    uncertainty: ValueState[Measured]
    status: Literal['submitted', 'draft', 'withdrawn']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A04']

    @model_validator(mode='after')
    def original_cost_lines(self):
        if len({r.line_key for r in self.draft.lines})!=len(self.draft.lines):raise ValueError('Saved cost plan repeats a line')
        if len(set(self.coverage_keys))!=len(self.coverage_keys):raise ValueError('Saved cost plan repeats physical coverage')
        if self.draft.complete_total is not None and (self.draft.missing_items or self.draft.calculation_ref is None):
            raise ValueError('Incomplete saved cost plan cannot claim a full total')
        return self


class QSResearchProfileView(CostSource):
    ref: ref_type('ComparisonProfile')
    task_ref: ref_type('Task')
    comparison_basis_ref: ref_type('ComparisonBasis')
    required_scope_keys: Annotated[list[TextId], Field(min_length=1)]
    required_dimensions: list[QSResearchDimension]
    normalization_basis_refs: list[ref_type('CostNormalization')]
    normalization_result_ref: ref_type('MethodResult') | None
    ranking_result_ref: ref_type('MethodResult') | None
    criteria: list[QSBidCriterion]
    missing_policy: Literal['request_research', 'report']
    selected_plan_refs: list[ref_type('CostPlan')] = Field(default_factory=list)

    @model_validator(mode='after')
    def selected_dimensions(self):
        if len({r.code for r in self.required_dimensions})!=len(self.required_dimensions):raise ValueError('Required comparison dimension repeated')
        if len({r.metric for r in self.criteria})!=len(self.criteria):raise ValueError('Comparison criterion repeated')
        unique_refs(self.normalization_basis_refs)
        unique_refs(self.selected_plan_refs)
        return self


class QSResearchExpenseView(CostSource):
    ref: ref_type('ResearchExpense')
    task_ref: ref_type('Task')
    cost_fact_ref: ref_type('ResearchCostFact')
    amount: Money
    effort: Measured
    status: Literal['committed', 'incurred']


class QSResearchCostFactView(CostSource):
    ref: ref_type('ResearchCostFact')
    task_ref: ref_type('Task')
    organization_id: TextId
    amount: Money
    effort: Measured
    status: Literal['committed', 'incurred']


class QSResearchLimitView(CostSource):
    ref: ref_type('ResearchLimit')
    task_ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    budget_cap: Money
    effort_cap: Measured
    expense_refs: list[ref_type('ResearchExpense')]
    status: Literal['active', 'exhausted', 'declined']
    as_of: TimePoint


class QSResearchRequestView(CostSource):
    ref: ref_type('ResearchRequestProfile')
    task_ref: ref_type('Task')
    purpose: Literal['preparation', 'investigation', 'service_delivery']
    input_refs: list[ref_type('BusinessObject')]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    incremental_budget: ValueState[Money]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]


class QSResearchReferenceView(CostSource):
    """Readable request input or task-bound work, requirement and dependency."""
    ref: Reference
    task_ref: ref_type('Task') | None = None


class QSResearchRequestQuestion(StrictRecord):
    scope: ScopeRef
    target_refs: list[ref_type('EvidenceTarget')]
    question: TextId
    recipient_ids: list[TextId]
    evidence_refs: list[ref_type('Evidence')]
    blocking_uses: list[ServiceUse]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSResearchTaskRegistrationView(CostSource):
    """Actual supplemental-task intake and independently confirmed work limits."""
    ref: ref_type('QSResearchTaskRegistration')
    run_id: TextId
    proposer_organization_id: TextId
    planner_organization_id: TextId
    planner_actor_id: TextId
    planner_function_ref: ref_type('FunctionAssignment')
    task_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    record_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    result_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    source_reading_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    request: QSResearchRequestView
    request_payload_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    questions: list[QSResearchRequestQuestion]
    research_authority_ref: ref_type('Authority')
    research_limit_ref: ref_type('ResearchLimit')
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    planning_task_ref: ref_type('Task')
    planning_task_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    authorized_budget: Money
    authorized_effort: Measured
    continuation_evidence_ref: ref_type('Evidence')
    continuation_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    confirmed_at: TimePoint | None
    registered_at: TimePoint | None


class QSResearchGapView(CostSource):
    ref: ref_type('EvidenceTarget')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    option_ref: ref_type('DesignOption') | None
    issue: Literal['cost_plan', 'assessment', 'comparison', 'ranking']
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: Annotated[list[ServiceUse], Field(min_length=1)]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSResearchResponseView(CostSource):
    ref: ref_type('ResponseRequirement')
    task_ref: ref_type('Task')
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


class QSResearchNormalizationView(CostSource):
    ref: ref_type('CostNormalization')
    plan_ref: ref_type('CostPlan')
    comparison_basis_ref: ref_type('ComparisonBasis')
    original_amount: Money
    target_currency: TextId
    fx_rate: ValueState[DecimalString]
    fx_basis_ref: ref_type('Evidence')
    adjustments: list[QSCostAdjustment]
    difference_keys: list[TextId]
    target_scope_keys: list[TextId] | None = None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A13']


class QSResearchNormalizedCost(StrictRecord):
    plan_ref: ref_type('CostPlan')
    amount: Money


class QSResearchCalculationView(CostSource):
    ref: ref_type('MethodResult')
    kind: Literal['normalization', 'ranking']
    method_ref: ref_type('Method')
    task_ref: ref_type('Task')
    profile_ref: ref_type('ComparisonProfile')
    comparison_basis_ref: ref_type('ComparisonBasis')
    plan_refs: list[ref_type('CostPlan')]
    normalization_basis_refs: list[ref_type('CostNormalization')]
    status: Literal['ok', 'failed', 'unsupported']
    normalized_costs: list[QSResearchNormalizedCost]
    ranked_groups: list[list[ref_type('DesignOption')]]
    calculated_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A13']


class QSResearchMethodProjection(StrictRecord):
    """Preserve original MethodResult identities while accepting its closed role schema."""
    ref: ref_type('MethodResult')
    cost: QSCostCalculationView | None = None
    comparison: QSResearchCalculationView | None = None

    @model_validator(mode='before')
    @classmethod
    def compatible_original(cls,value):
        if isinstance(value,dict) and 'method_ref' in value:
            field='cost' if value.get('author_action_id')=='QS-A04' else 'comparison'
            return {'ref':value['ref'],field:value}
        return value

    @model_validator(mode='after')
    def one_original_result(self):
        rows=[r for r in (self.cost,self.comparison) if r is not None]
        if len(rows)!=1 or rows[0].ref!=self.ref:raise ValueError('Method projection must preserve one original result identity')
        return self


def qs_research_schemas():
    registry=common_projection_schemas()
    for kind,schema in {
        'Brief':QSCostBriefView,'DesignOption':QSResearchOptionView,'ComparisonBasis':QSResearchBasisView,
        'Authority':QSResearchAuthorityView,'Task':QSResearchTaskView,'Assessment':QSResearchAssessmentView,
        'CostPlan':QSResearchCostPlanView,'ComparisonProfile':QSResearchProfileView,'ResearchLimit':QSResearchLimitView,
        'ResearchExpense':QSResearchExpenseView,'ResearchCostFact':QSResearchCostFactView,'ResearchRequestProfile':QSResearchRequestView,
        'EvidenceTarget':QSResearchGapView,'ResponseRequirement':QSResearchResponseView,
        'CostNormalization':QSResearchNormalizationView,'MethodResult':QSResearchMethodProjection,
        'CostScope':QSCostScopeView,'Price':QSCostPriceView,'QuantityBasis':QSQuantityBasisView,
        'ClockProfile':ServiceClockView,'OwnerCase':ServiceScopeCaseView,'Project':ServiceScopeProjectView,'WorkScope':ServiceWorkScopeView,
    }.items():registry.register_kind(kind,schema,str)
    for kind in ('BusinessObject', 'DeliverableRequirement', 'Dependency', 'WorkProfile'):
        registry.register_kind(kind, QSResearchReferenceView, str)
    return registry
