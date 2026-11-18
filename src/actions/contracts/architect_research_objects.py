"""Finite research inputs, independent acceptance and versioned comparison facts."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource, QSCostBriefView
from src.actions.contracts.qs_research_objects import (
    QSResearchAuthorityView, QSResearchExpenseView, QSResearchCostFactView,
    QSResearchLimitView, QSResearchCostPlanView, QSResearchDimension,
)
from src.methods.architect_research_estimates import ArchitectResearchEstimateInput
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import (
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView,
    ServiceScopeProjectView, ServiceWorkScopeView,
)


class ArchitectResearchAuthorityView(QSResearchAuthorityView):
    service_request_ref: ref_type('ServiceRequest')
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    terms_digest: TextId
    acceptance_ref: ref_type('RecordedDecision')
    confirmation_ref: ref_type('RecordedDecision')
    allowed_recipient_ids: list[TextId]
    allowed_input_refs: list[Reference]


class ArchitectResearchDecisionView(CostSource):
    ref: ref_type('RecordedDecision')
    action_id: Literal['ARCHITECT-A02', 'ARCHITECT-A03']
    choice: Literal['accept', 'decline', 'confirm', 'request_amendment', 'decline_incompatible']
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    service_request_ref: ref_type('ServiceRequest')
    appointment_ref: ref_type('Appointment') | None
    accepted_terms_ref: ref_type('ServiceTerms')
    terms_digest: TextId
    decided_at: TimePoint


class ArchitectResearchTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    brief_ref: ref_type('Brief')
    design_profile_ref: ref_type('DesignProfile')
    available_option_refs: list[ref_type('DesignOption')]
    professional_refs: list[ref_type('Assessment')]
    cost_refs: list[ref_type('CostPlan')]
    expenditure_limit_ref: ref_type('ResearchLimit')
    comparison_scope_ref: ref_type('ComparisonScope')
    comparison_method_ref: ref_type('ComparisonMethod') | None
    question_refs: list[ref_type('EvidenceTarget')]
    request_profile_ref: ref_type('ResearchRequestProfile') | None
    status: Literal['authorized', 'waiting', 'closed']


class ArchitectResearchProfileView(CostSource):
    ref: ref_type('DesignProfile')
    allowed_uses: list[TextId]
    object_types: list[TextId]
    region_ids: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ArchitectResearchMetric(StrictRecord):
    code: TextId
    value: ValueState[Measured]


class ArchitectResearchOptionView(CostSource):
    ref: ref_type('DesignOption')
    brief_ref: ref_type('Brief')
    design_profile_ref: ref_type('DesignProfile')
    task_ref: ref_type('Task')
    object_type: TextId
    region_id: TextId
    allowed_uses: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    compilation_status: Literal['completed', 'incomplete', 'failed', 'unsupported']
    dimensions: list[QSResearchDimension]
    metrics: list[ArchitectResearchMetric]
    unresolved_questions: list[ArchitectOpportunityQuestion]
    limitations: list[TextId]


class ArchitectResearchAssessmentView(CostSource):
    ref: ref_type('Assessment')
    brief_ref: ref_type('Brief')
    option_ref: ref_type('DesignOption')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    allowed_uses: list[TextId]
    finding: Literal['compatible', 'conflict', 'unknown', 'not_applicable']
    status: Literal['ok', 'failed', 'unsupported']
    comparison_scope_ref: ref_type('ComparisonScope')
    coverage_keys: list[TextId]
    metrics: list[ArchitectResearchMetric]
    limitations: list[TextId]


class ArchitectResearchScopeView(CostSource):
    ref: ref_type('ComparisonScope')
    task_ref: ref_type('Task')
    brief_ref: ref_type('Brief')
    required_dimensions: list[QSResearchDimension]
    required_professional_coverage_keys: list[TextId]
    require_costs: bool
    missing_policy: Literal['report', 'request']

    @model_validator(mode='after')
    def unique_dimensions(self):
        if len({row.code for row in self.required_dimensions}) != len(self.required_dimensions):
            raise ValueError('Comparison repeats a required dimension')
        if len(set(self.required_professional_coverage_keys)) != len(self.required_professional_coverage_keys):
            raise ValueError('Comparison repeats professional coverage')
        return self


class ArchitectResearchCriterion(StrictRecord):
    code: TextId
    source: Literal['option', 'professional', 'cost']
    unit: TextId
    direction: Literal['minimize', 'maximize']


class ArchitectResearchMethodView(CostSource):
    ref: ref_type('ComparisonMethod')
    task_ref: ref_type('Task')
    comparison_scope_ref: ref_type('ComparisonScope')
    method_ref: ref_type('Method')
    criteria: Annotated[list[ArchitectResearchCriterion], Field(min_length=1)]
    allowed_uses: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ArchitectResearchGapView(CostSource):
    ref: ref_type('EvidenceTarget')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    option_ref: ref_type('DesignOption') | None
    question: ArchitectOpportunityQuestion


class ArchitectResearchRequestView(CostSource):
    ref: ref_type('ResearchRequestProfile')
    task_ref: ref_type('Task')
    purpose: Literal['investigation', 'preparation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    incremental_cost: ValueState[Money]
    estimate_ref: ref_type('MethodResult') | None


class ArchitectResearchEstimateView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    request_profile_ref: ref_type('ResearchRequestProfile')
    input_refs: list[Reference]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    incremental_cost: ValueState[Money]
    status: Literal['ok', 'failed', 'unsupported']
    method_ref: ref_type('Method')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ArchitectResearchEstimateMethodView(CostSource):
    ref: ref_type('Method')
    purpose: Literal['bounded_research_estimate']
    design_profile_ref: ref_type('DesignProfile')
    allowed_purposes: list[Literal['investigation', 'preparation']]


class ArchitectResearchReferenceView(CostSource):
    ref: Reference
    task_ref: ref_type('Task')


class ArchitectResearchEstimatePreparation(StrictRecord):
    calculation_ref: ref_type('MethodResult')
    request_profile_ref: ref_type('ResearchRequestProfile')
    input: ArchitectResearchEstimateInput


class ArchitectResearchWorkEstimateBasis(StrictRecord):
    method_ref: ref_type('Method')
    allowed_object_types: list[TextId]
    allowed_region_ids: list[TextId]
    allowed_purposes: list[Literal['investigation', 'preparation']]
    quantity: Measured
    effort_per_unit: Measured
    effort_quantity_unit: TextId
    cost_per_effort: Money
    cost_effort_unit: TextId
    fixed_cost: Money


class ArchitectResearchWorkView(ArchitectResearchReferenceView):
    estimate_basis: ArchitectResearchWorkEstimateBasis | None = None


class ArchitectResearchLimitView(QSResearchLimitView):
    deadline: TimePoint | None = None


def architect_research_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Brief': QSCostBriefView, 'Authority': ArchitectResearchAuthorityView, 'Task': ArchitectResearchTaskView,
        'RecordedDecision': ArchitectResearchDecisionView, 'DesignProfile': ArchitectResearchProfileView,
        'DesignOption': ArchitectResearchOptionView, 'Assessment': ArchitectResearchAssessmentView,
        'CostPlan': QSResearchCostPlanView, 'ResearchLimit': ArchitectResearchLimitView,
        'ResearchExpense': QSResearchExpenseView, 'ResearchCostFact': QSResearchCostFactView,
        'ComparisonScope': ArchitectResearchScopeView, 'ComparisonMethod': ArchitectResearchMethodView,
        'EvidenceTarget': ArchitectResearchGapView, 'ResearchRequestProfile': ArchitectResearchRequestView,
        'MethodResult': ArchitectResearchEstimateView, 'Method': ArchitectResearchEstimateMethodView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    registry.register_kind('WorkProfile', ArchitectResearchWorkView, str)
    for kind in ('ResponseRequirement', 'DeliverableRequirement', 'Dependency'):
        registry.register_kind(kind, ArchitectResearchReferenceView, str)
    return registry
