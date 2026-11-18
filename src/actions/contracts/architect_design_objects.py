"""Finite design catalog and received author work, with engagement-wide limits."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource, QSCostBriefView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchOptionView, ArchitectResearchAssessmentView, ArchitectResearchScopeView,
    ArchitectResearchMethodView, ArchitectResearchGapView,
)
from src.actions.contracts.qs_research_objects import QSResearchCostPlanView
from src.actions.contracts.architect_appointment_objects import ArchitectAppointmentView
from src.actions.contracts.architect_planning_objects import ArchitectPlanningWorkFactView
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas
from src.actions.contracts.architect_review_objects import Digest
from src.methods.architect_area import ArchitectAreaInput, ArchitectAreaReport


class ArchitectDesignVariable(StrictRecord):
    variable_ref: ref_type('DesignVariable')
    value: ValueState[Measured] | ValueState[ref_type('CatalogOption')]
    source_refs: list[ref_type('Evidence')]


class ArchitectDesignGroup(StrictRecord):
    scope: ScopeRef
    coverage_ref: ref_type('ComponentCoverage')
    function_ref: ref_type('FunctionType')
    system_option: ValueState[ref_type('SystemOption')]
    interface_refs: list[ref_type('Interface')]


class ArchitectDesignDraft(StrictRecord):
    brief_ref: ref_type('Brief')
    scope: ScopeRef
    design_profile_ref: ref_type('DesignProfile')
    parent_option_ref: ref_type('DesignOption') | None
    relation: Literal['original', 'revision', 'alternative']
    variables: list[ArchitectDesignVariable]
    component_groups: list[ArchitectDesignGroup]
    basis_refs: list[ref_type('Evidence')]
    method_result_refs: list[ref_type('MethodResult')]
    unresolved_questions: list[ArchitectOpportunityQuestion]


class ArchitectDesignTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    appointment_ref: ref_type('Appointment')
    brief_ref: ref_type('Brief')
    design_profile_ref: ref_type('DesignProfile')
    choice: Literal['produce', 'compare', 'request_inputs']
    requested_use: ServiceUse
    drafts: list[ArchitectDesignDraft]
    available_option_refs: list[ref_type('DesignOption')]
    professional_refs: list[ref_type('Assessment')]
    cost_refs: list[ref_type('CostPlan')]
    method_result_refs: list[ref_type('MethodResult')]
    work_fact_refs: list[ref_type('WorkFact')]
    required_effort: Measured
    required_input_refs: list[Reference]
    question_refs: list[ref_type('EvidenceTarget')]
    design_limit_ref: ref_type('DesignLimit')
    status: Literal['authorized', 'waiting', 'closed']


class ArchitectDesignRegistrationView(CostSource):
    """Actual native registration retaining one complete original authored draft."""
    ref: ref_type('DesignRegistration')
    run_id: TextId
    organization_id: TextId
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    source_task_ref: ref_type('Task')
    draft_index: Annotated[int, Field(ge=0)]
    draft: ArchitectDesignDraft
    option_ref: ref_type('DesignOption')
    option_sha256: Digest | None
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    authored_at: TimePoint
    registered_at: TimePoint | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ArchitectChangeTaskRegistrationView(CostSource):
    """Observed A09 proposal intake and its independently authorized A05 task."""
    ref: ref_type('ArchitectChangeTaskRegistration')
    run_id: TextId
    proposer_organization_id: TextId
    designer_organization_id: TextId
    designer_actor_id: TextId
    designer_function_ref: ref_type('FunctionAssignment')
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    proposal_sha256: Digest
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    prior_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    instruction_ref: ref_type('Instruction') | None
    parent_option_ref: ref_type('DesignOption')
    parent_option_sha256: Digest
    design_task_ref: ref_type('Task')
    design_task_sha256: Digest
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    registered_at: TimePoint | None


class ArchitectDesignProfileView(CostSource):
    ref: ref_type('DesignProfile')
    object_type: TextId
    region_id: TextId
    allowed_uses: list[TextId]
    supported: ValueState[bool]
    permitted_method_refs: list[ref_type('Method')]
    required_variable_refs: list[ref_type('DesignVariable')]
    variable_refs: list[ref_type('DesignVariable')]
    coverage_refs: list[ref_type('ComponentCoverage')]
    required_area_method: bool
    incompatible_pairs: list[tuple[Reference, Reference]]


class ArchitectDesignVariableView(CostSource):
    ref: ref_type('DesignVariable')
    design_profile_ref: ref_type('DesignProfile')
    value_kind: Literal['measured', 'catalog']
    unit: TextId | None
    minimum: Measured | None
    maximum: Measured | None
    step: Measured | None
    catalog_option_refs: list[ref_type('CatalogOption')]
    allow_unknown: bool


class ArchitectDesignCoverageView(CostSource):
    ref: ref_type('ComponentCoverage')
    design_profile_ref: ref_type('DesignProfile')
    physical_keys: Annotated[list[TextId], Field(min_length=1)]
    floor_keys: list[TextId]
    function_refs: list[ref_type('FunctionType')]
    system_option_refs: list[ref_type('SystemOption')]
    interface_refs: list[ref_type('Interface')]


class ArchitectDesignLimitView(CostSource):
    ref: ref_type('DesignLimit')
    appointment_ref: ref_type('Appointment')
    option_refs: list[ref_type('DesignOption')]
    work_fact_refs: list[ref_type('WorkFact')]
    revision_count: Annotated[int, Field(ge=0)]
    version_branch_count: Annotated[int, Field(ge=0)]
    maximum_candidates: Annotated[int, Field(ge=0)]
    maximum_revisions: Annotated[int, Field(ge=0)]
    maximum_versions_branches: Annotated[int, Field(ge=0)]
    maximum_effort: Measured
    maximum_cost: Money
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    prior_submission_ref: ref_type('Submission') | None


class ArchitectDesignSubmissionView(CostSource):
    """Actual A05 registration query; an accepted transport receipt alone is insufficient."""
    ref: ref_type('Submission')
    run_id: TextId
    organization_id: TextId
    source_task_ref: ref_type('Task')
    appointment_ref: ref_type('Appointment')
    brief_ref: ref_type('Brief')
    design_profile_ref: ref_type('DesignProfile')
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    payload_sha256: Digest
    command_id: TextId
    business_key: TextId
    drafts: Annotated[list[ArchitectDesignDraft], Field(min_length=1)]
    registration_refs: list[ref_type('DesignRegistration')]
    queried_at: TimePoint
    status: Literal['pending', 'unknown', 'registered', 'rejected', 'confirmed_uncommitted']


class ArchitectDesignAreaPreparation(StrictRecord):
    """Explicit original draft mapping and its predeclared result target."""
    calculation_ref: ref_type('MethodResult')
    draft_index: Annotated[int, Field(ge=0)]
    input: ArchitectAreaInput
    area_variable_refs: dict[TextId, ref_type('DesignVariable')]
    floor_count_variable_refs: dict[TextId, ref_type('DesignVariable')]


class ArchitectDesignAreaResultView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    design_profile_ref: ref_type('DesignProfile')
    draft_index: Annotated[int, Field(ge=0)]
    method_ref: ref_type('Method')
    status: Literal['ok', 'failed', 'unsupported']
    executed_at: TimePoint
    input: ArchitectAreaInput
    report: ArchitectAreaReport
    area_variable_refs: dict[TextId, ref_type('DesignVariable')]
    floor_count_variable_refs: dict[TextId, ref_type('DesignVariable')]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ArchitectDesignReferenceView(CostSource):
    ref: Reference
    design_profile_ref: ref_type('DesignProfile')


def architect_design_schemas():
    return service_intake_schemas(overrides={
        'Brief': QSCostBriefView, 'Task': ArchitectDesignTaskView, 'DesignProfile': ArchitectDesignProfileView,
        'Appointment': ArchitectAppointmentView, 'DesignVariable': ArchitectDesignVariableView,
        'ComponentCoverage': ArchitectDesignCoverageView, 'DesignLimit': ArchitectDesignLimitView,
        'Submission': ArchitectDesignSubmissionView,
        'MethodResult': ArchitectDesignAreaResultView, 'DesignOption': ArchitectResearchOptionView,
        'DesignRegistration': ArchitectDesignRegistrationView,
        'ArchitectChangeTaskRegistration': ArchitectChangeTaskRegistrationView,
        'Assessment': ArchitectResearchAssessmentView, 'CostPlan': QSResearchCostPlanView,
        'ComparisonScope': ArchitectResearchScopeView, 'ComparisonMethod': ArchitectResearchMethodView,
        'EvidenceTarget': ArchitectResearchGapView, 'WorkFact': ArchitectPlanningWorkFactView,
        **{kind: ArchitectDesignReferenceView for kind in ('CatalogOption', 'FunctionType', 'SystemOption', 'Interface')},
    })
