"""Original scoped professional design inputs and finite parameter executions."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, ScopeRef, Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource, QSCostBriefView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.architect_design_objects import ArchitectDesignLimitView
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_objects import EngineerServiceTermsView
from src.actions.contracts.engineer_planning_objects import EngineerPlanningWorkFactView
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchCheckSpecView, EngineerResearchCheckResultView, EngineerResearchFactView,
    EngineerResearchGapView, EngineerResearchTargetView,
)
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas
from src.methods.engineer_parameters import EngineerParameterInput, EngineerParameterReport
from src.methods.engineer_checks import EngineerInterfaceInput


class EngineerDesignDraft(StrictRecord):
    brief_ref: ref_type('Brief')
    scope: ScopeRef
    engineering_profile_ref: ref_type('EngineeringProfile')
    parent_option_ref: ref_type('DesignOption') | None
    selected_parameter_refs: list[ref_type('ValidatedEngineeringParameter')]
    method_result_refs: list[ref_type('MethodResult')]
    evidence_refs: list[ref_type('Evidence')]
    interface_refs: list[ref_type('Interface')]
    quantity_basis_refs: list[ref_type('QuantityBasis')]
    unresolved_questions: list[ArchitectOpportunityQuestion]


class EngineerDesignSubmissionView(CostSource):
    """Actual original A05 registration query retaining command and complete production provenance."""
    ref: ref_type('Submission')
    run_id: TextId
    organization_id: TextId
    source_task_ref: ref_type('Task')
    appointment_ref: ref_type('Appointment')
    brief_ref: ref_type('Brief')
    engineering_profile_ref: ref_type('EngineeringProfile')
    task_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    record_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    result_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    source_reading_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    payload_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    command_id: TextId
    business_key: TextId
    draft: EngineerDesignDraft
    registration_refs: list[ref_type('EngineerDesignRegistration')]
    option_ref: ref_type('DesignOption') | None = None
    queried_at: TimePoint
    status: Literal['pending', 'unknown', 'registered', 'rejected', 'confirmed_uncommitted']


class EngineerDesignCheckResultTarget(StrictRecord):
    check_spec_ref: ref_type('CheckSpec')
    calculation_ref: ref_type('MethodResult')


class EngineerDesignTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    authority_ref: ref_type('Authorization')
    brief_ref: ref_type('Brief')
    engineering_profile_ref: ref_type('EngineeringProfile')
    discipline_code: TextId
    function_code: TextId
    requested_use: ServiceUse
    choice: Literal['produce', 'request_investigation', 'report_limit']
    draft: EngineerDesignDraft | None
    evidence_input_refs: list[ref_type('Evidence')]
    method_result_refs: list[ref_type('MethodResult')]
    check_spec_refs: list[ref_type('CheckSpec')]
    question_refs: list[ref_type('EvidenceTarget')]
    design_limit_ref: ref_type('DesignLimit')
    work_fact_refs: list[ref_type('WorkFact')]
    required_effort: Measured
    status: Literal['authorized', 'waiting', 'closed']
    check_result_targets: list[EngineerDesignCheckResultTarget] = []


class EngineerDesignProfileView(CostSource):
    ref: ref_type('EngineeringProfile')
    object_type: TextId
    region_id: TextId
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    allowed_uses: list[ServiceUse]
    supported: ValueState[bool]
    permitted_method_refs: list[ref_type('Method')]
    parameter_catalog_refs: list[ref_type('EngineeringParameterCatalog')]
    required_parameter_catalog_refs: list[ref_type('EngineeringParameterCatalog')]
    interface_refs: list[ref_type('Interface')]
    quantity_basis_refs: list[ref_type('QuantityBasis')]
    incompatible_pairs: list[tuple[ref_type('CatalogOption'), ref_type('CatalogOption')]]


class EngineerParameterCatalogView(CostSource):
    ref: ref_type('EngineeringParameterCatalog')
    engineering_profile_ref: ref_type('EngineeringProfile')
    discipline_code: TextId
    value_kind: Literal['measured', 'catalog']
    unit: TextId | None
    minimum: Measured | None
    maximum: Measured | None
    step: Measured | None
    option_refs: list[ref_type('CatalogOption')]
    gap_question_ref: ref_type('EvidenceTarget') | None


class EngineerValidatedParameterView(CostSource):
    ref: ref_type('ValidatedEngineeringParameter')
    task_ref: ref_type('Task')
    engineering_profile_ref: ref_type('EngineeringProfile')
    catalog_ref: ref_type('EngineeringParameterCatalog')
    value: ValueState[Measured] | ValueState[ref_type('CatalogOption')]
    source_refs: list[ref_type('Evidence')]
    validation_result_ref: ref_type('MethodResult')


class EngineerParameterResultView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    engineering_profile_ref: ref_type('EngineeringProfile')
    method_ref: ref_type('Method')
    executed_at: TimePoint
    status: Literal['ok', 'failed', 'unsupported', 'unknown']
    input: EngineerParameterInput
    result: EngineerParameterReport | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A05', 'ENGINEER-A09']


class EngineerDesignParameterPreparation(StrictRecord):
    """Predeclared result target and exact sourced parameter-method input."""
    calculation_ref: ref_type('MethodResult')
    input: EngineerParameterInput


class EngineerDesignCheckPreparation(StrictRecord):
    """Exact original check, declared result target and sourced interface input."""
    calculation_ref: ref_type('MethodResult')
    check_spec_ref: ref_type('CheckSpec')
    input: EngineerInterfaceInput


class EngineerDesignMethodProjection(StrictRecord):
    ref: ref_type('MethodResult')
    record: EngineerParameterResultView | EngineerResearchCheckResultView


class EngineerDesignMethodView(CostSource):
    ref: ref_type('Method')
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    region_ids: list[TextId]
    object_types: list[TextId]
    allowed_uses: list[ServiceUse]


class EngineerDesignReferenceView(CostSource):
    ref: Reference
    engineering_profile_ref: ref_type('EngineeringProfile')
    task_ref: ref_type('Task')
    parameter_refs: list[ref_type('ValidatedEngineeringParameter')]
    method_result_ref: ref_type('MethodResult') | None
    status: Literal['declared', 'calculated', 'unknown']


def engineer_design_schemas(overrides=None):
    # Registration objects import the professional draft, so load them after this module is initialized.
    from src.actions.contracts.engineer_submission_objects import EngineerDesignRegistrationView, EngineerSubmissionDeliverableView
    mappings = {
        'Brief': QSCostBriefView, 'Task': EngineerDesignTaskView, 'EngineeringProfile': EngineerDesignProfileView,
        'Appointment': EngineerAppointmentView, 'ServiceTerms': EngineerServiceTermsView,
        'EngineeringParameterCatalog': EngineerParameterCatalogView, 'ValidatedEngineeringParameter': EngineerValidatedParameterView,
        'MethodResult': EngineerDesignMethodProjection, 'Method': EngineerDesignMethodView,
        'DesignLimit': ArchitectDesignLimitView, 'WorkFact': EngineerPlanningWorkFactView,
        'EvidenceTarget': EngineerResearchGapView, 'DesignOption': EngineerResearchTargetView,
        'CheckSpec': EngineerResearchCheckSpecView, 'EngineeringFact': EngineerResearchFactView,
        'Submission': EngineerDesignSubmissionView, 'EngineerDesignRegistration': EngineerDesignRegistrationView,
        'Deliverable': EngineerSubmissionDeliverableView,
        **{kind: EngineerDesignReferenceView for kind in ('Interface', 'QuantityBasis', 'CatalogOption', 'EngineeringScope', 'Issue')},
    }
    mappings.update(overrides or {})
    return service_intake_schemas(overrides=mappings)
