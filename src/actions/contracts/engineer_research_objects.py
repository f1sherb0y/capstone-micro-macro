"""Original finite engineering research and saved checks/assessments."""
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource, QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchAuthorityView, ArchitectResearchDecisionView, ArchitectResearchLimitView,
    ArchitectResearchRequestView, ArchitectResearchEstimateView, ArchitectResearchReferenceView,
)
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import (
    ServiceUse, ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView,
    ServiceScopeProjectView, ServiceWorkScopeView,
)
from src.methods.engineer_checks import EngineerInterfaceInput, EngineerInterfaceReport
from src.methods.engineer_research_estimates import EngineerResearchEstimateInput


class EngineerResearchAuthorityView(ArchitectResearchAuthorityView):
    allowed_discipline_codes: list[TextId]
    allowed_function_codes: list[TextId]
    independence_check_ref: ref_type('IndependenceCheck') | None
    independence_required: bool


class EngineerResearchDecisionView(ArchitectResearchDecisionView):
    action_id: Literal['ENGINEER-A02', 'ENGINEER-A03']
    choice: Literal['accept', 'decline', 'confirm', 'disclose_conflict', 'request_amendment']


class EngineerResearchCheckResultTarget(StrictRecord):
    check_spec_ref: ref_type('CheckSpec')
    calculation_ref: ref_type('MethodResult')


class EngineerResearchCheckPreparation(StrictRecord):
    """Original research check, reserved result and exact sourced input."""
    calculation_ref: ref_type('MethodResult')
    check_spec_ref: ref_type('CheckSpec')
    input: EngineerInterfaceInput


class EngineerResearchEstimatePreparation(StrictRecord):
    calculation_ref: ref_type('MethodResult')
    request_profile_ref: ref_type('ResearchRequestProfile')
    input: EngineerResearchEstimateInput


class EngineerResearchWorkEstimateBasis(StrictRecord):
    method_ref: ref_type('Method')
    allowed_discipline_codes: list[TextId]
    allowed_function_codes: list[TextId]
    allowed_purposes: list[Literal['investigation', 'preparation']]
    quantity: Measured
    effort_per_unit: Measured
    effort_quantity_unit: TextId
    cost_per_effort: Money
    cost_effort_unit: TextId
    fixed_cost: Money


class EngineerResearchWorkView(ArchitectResearchReferenceView):
    estimate_basis: EngineerResearchWorkEstimateBasis | None = None


class EngineerResearchTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    brief_ref: ref_type('Brief')
    discipline_code: TextId
    function_code: TextId
    option_refs: list[ref_type('DesignOption')]
    check_spec_refs: list[ref_type('CheckSpec')]
    input_evidence_refs: list[ref_type('Evidence')]
    available_assessment_refs: list[ref_type('Assessment')]
    method_result_refs: list[ref_type('MethodResult')]
    check_result_targets: list[EngineerResearchCheckResultTarget] = []
    expenditure_limit_ref: ref_type('ResearchLimit')
    comparison_scope_ref: ref_type('ComparisonScope') | None
    question_refs: list[ref_type('EvidenceTarget')]
    request_profile_ref: ref_type('ResearchRequestProfile') | None
    status: Literal['authorized', 'waiting', 'closed']
    missing_policy: Literal['report', 'request']


class EngineerResearchIndependenceView(CostSource):
    ref: ref_type('IndependenceCheck')
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    organization_id: TextId
    requirement_ref: ref_type('IndependenceRequirement')
    checked_resource_refs: list[ref_type('Resource')]
    conflict_refs: list[ref_type('ConflictOfInterest')]
    status: Literal['verified', 'unresolved', 'conflict']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class EngineerResearchTargetView(CostSource):
    ref: Reference
    brief_ref: ref_type('Brief')
    allowed_uses: list[ServiceUse]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class EngineerResearchScopeView(CostSource):
    ref: ref_type('ComparisonScope')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    target_refs: list[Reference]
    check_spec_refs: list[ref_type('CheckSpec')]


class EngineerResearchFactView(CostSource):
    ref: ref_type('EngineeringFact')
    target_ref: Reference
    engineering_scope_ref: ref_type('EngineeringScope')
    field_path: TextId
    value: ValueState[TextId]
    basis: Literal['observed', 'claimed', 'assumed']


class EngineerResearchCheckSpecView(CostSource):
    ref: ref_type('CheckSpec')
    brief_ref: ref_type('Brief')
    target_ref: ref_type('Brief') | ref_type('DesignOption')
    engineering_scope_ref: ref_type('EngineeringScope')
    discipline_code: TextId
    function_code: TextId
    allowed_uses: list[ServiceUse]
    requested_check: TextId
    method_ref: ref_type('Method') | None
    left_fact_ref: ref_type('EngineeringFact') | None
    right_fact_ref: ref_type('EngineeringFact') | None
    issue_refs: list[ref_type('Issue')]
    gap_question_ref: ref_type('EvidenceTarget') | None


class EngineerResearchCheckItem(StrictRecord):
    check_spec_ref: ref_type('CheckSpec')
    evidence_refs: list[ref_type('Evidence')]
    evidence_status: Literal['sufficient', 'missing', 'assumption_based']
    method_result_ref: ref_type('MethodResult') | None
    result: Literal['satisfied', 'conflict', 'undetermined', 'out_of_scope'] | None
    missing_field_paths: list[str]
    issue_refs: list[ref_type('Issue')]


class EngineerResearchAssessment(StrictRecord):
    target_ref: ref_type('Brief') | ref_type('DesignOption') | ref_type('Deliverable')
    task_ref: ref_type('Task')
    check_items: list[EngineerResearchCheckItem]
    opinion: Literal['support_limited_option', 'revise', 'investigate', 'reserve_interpretation']
    requested_use: ServiceUse
    uncovered_scope_refs: list[ref_type('EngineeringScope')]
    explanation: str


class EngineerResearchAssessmentView(CostSource):
    ref: ref_type('Assessment')
    assessment: EngineerResearchAssessment
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A13']


class EngineerResearchCheckResultView(CostSource):
    ref: ref_type('MethodResult')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    check_spec_ref: ref_type('CheckSpec')
    target_ref: Reference
    method_ref: ref_type('Method')
    status: Literal['ok', 'failed', 'unsupported']
    executed_at: TimePoint
    input_fact_refs: list[ref_type('EngineeringFact')]
    result: EngineerInterfaceReport | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A13']


class EngineerResearchEstimateView(ArchitectResearchEstimateView):
    executed_at: TimePoint


class EngineerResearchMethodProjection(StrictRecord):
    ref: ref_type('MethodResult')
    check: EngineerResearchCheckResultView | None = None
    estimate: EngineerResearchEstimateView | None = None

    @model_validator(mode='before')
    @classmethod
    def original_record(cls, value):
        if isinstance(value, dict) and 'ref' in value and 'check' not in value and 'estimate' not in value:
            return {'ref': value['ref'], 'check' if 'check_spec_ref' in value else 'estimate': value}
        return value

    @model_validator(mode='after')
    def one_result(self):
        values = [row for row in (self.check, self.estimate) if row is not None]
        if len(values) != 1 or values[0].ref != self.ref:
            raise ValueError('Method projection must preserve exactly one original result')
        return self


class EngineerResearchMethodView(CostSource):
    ref: ref_type('Method')
    purposes: list[Literal['synthetic_interface_code_equality', 'bounded_research_estimate']]
    allowed_discipline_codes: list[TextId]
    allowed_function_codes: list[TextId]


class EngineerResearchGapView(CostSource):
    ref: ref_type('EvidenceTarget')
    brief_ref: ref_type('Brief')
    task_ref: ref_type('Task')
    question: ArchitectOpportunityQuestion


def engineer_research_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Brief': QSCostBriefView, 'DesignOption': EngineerResearchTargetView,
        'Authority': EngineerResearchAuthorityView, 'RecordedDecision': EngineerResearchDecisionView,
        'Task': EngineerResearchTaskView, 'ResearchLimit': ArchitectResearchLimitView,
        'ResearchExpense': QSResearchExpenseView, 'ResearchCostFact': QSResearchCostFactView,
        'ComparisonScope': EngineerResearchScopeView, 'IndependenceCheck': EngineerResearchIndependenceView,
        'CheckSpec': EngineerResearchCheckSpecView, 'EngineeringFact': EngineerResearchFactView,
        'MethodResult': EngineerResearchMethodProjection, 'Method': EngineerResearchMethodView,
        'Assessment': EngineerResearchAssessmentView, 'EvidenceTarget': EngineerResearchGapView,
        'ResearchRequestProfile': ArchitectResearchRequestView, 'ClockProfile': ServiceClockView,
        'WorkProfile': EngineerResearchWorkView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items(): registry.register_kind(kind, schema, str)
    for kind in ('EngineeringScope', 'Issue', 'ResponseRequirement', 'Dependency',
                 'DeliverableRequirement', 'IndependenceRequirement', 'ConflictOfInterest', 'Resource'):
        registry.register_kind(kind, ArchitectResearchReferenceView, str)
    return registry
