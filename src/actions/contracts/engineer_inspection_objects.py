"""Authorized visible site inspection, planning and remote technical support."""
from typing import Literal
from pydantic import model_serializer

from src.actions.contracts.common import Measured, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_objects import EngineerServiceTermsView
from src.actions.contracts.engineer_planning_objects import (
    EngineerPlanningCalendarView, EngineerPlanningQualificationView, EngineerPlanningEstimateView,
    EngineerPlanningWorkFactView, EngineerPlanningAllocationView, EngineerPlanningToolDemand,
)
from src.actions.contracts.qs_appointment_objects import QSTaskResourceShare
from src.actions.contracts.service_objects import ServiceUse, ServiceWorkProfileView, service_intake_schemas
from src.methods.engineer_checks import EngineerInterfaceInput, EngineerInterfaceReport
from src.actions.contracts.engineer_submission_objects import EngineerRevisionRegistrationView, EngineerSubmissionDeliverableView


class EngineerInspectionCheckPreparation(StrictRecord):
    """Original observation/spec, reserved result and exact sourced code input."""
    calculation_ref: ref_type('MethodResult')
    check_spec_ref: ref_type('CheckSpec')
    observation_ref: ref_type('Observation')
    input: EngineerInterfaceInput


class EngineerInspectionTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    appointment_ref: ref_type('Appointment')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    discipline_code: TextId
    function_code: TextId
    requested_use: ServiceUse
    choice: Literal['plan_inspection', 'report', 'respond', 'request_test']
    observation_method_ref: ref_type('Method')
    received_observation_refs: list[ref_type('Observation')]
    received_query_refs: list[ref_type('Issue')]
    engineering_scope_refs: list[ref_type('EngineeringScope')]
    check_spec_refs: list[ref_type('CheckSpec')]
    work_profile_ref: ref_type('WorkProfile') | None
    estimate_ref: ref_type('WorkEstimate') | None
    work_fact_refs: list[ref_type('WorkFact')]
    work_fact_coverage: Literal['complete', 'partial', 'unknown']
    resource_calendar_ref: ref_type('ResourceCalendar') | None
    resource_shares: list[QSTaskResourceShare]
    tool_demands: list[EngineerPlanningToolDemand]
    planned_window: TimeWindow
    dependency_refs: list[ref_type('Dependency')]
    access_dependency_ref: ref_type('Dependency') | None
    existing_allocation_ref: ref_type('ResourceAllocation') | None
    question_refs: list[ref_type('EvidenceTarget')]
    test_method_ref: ref_type('Method') | None
    response_issue_ref: ref_type('Issue') | None
    note: TextId
    status: Literal['authorized', 'waiting', 'closed']


class EngineerInspectionDesignView(CostSource):
    ref: ref_type('Deliverable')
    content_sha256: Digest
    discipline_codes: list[TextId]
    valid_for_uses: list[ServiceUse]
    invalidated_uses: list[ServiceUse]
    status: Literal['compiled', 'draft', 'withdrawn']
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint


class EngineerInspectionMethodView(CostSource):
    ref: ref_type('Method')
    purpose: Literal['observation', 'test']
    supported: ValueState[bool]
    requires_site_access: bool
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    region_ids: list[TextId]
    object_types: list[TextId]
    allowed_uses: list[ServiceUse]
    permitted_executor_organization_ids: list[TextId]


class EngineerInspectionAccessView(CostSource):
    ref: ref_type('SiteAccess')
    task_ref: ref_type('Task')
    executor_organization_ids: list[TextId]
    allowed: ValueState[bool]
    engineering_scope_refs: list[ref_type('EngineeringScope')]


class EngineerInspectionScopeView(CostSource):
    ref: ref_type('EngineeringScope')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    discipline_code: TextId
    physical_keys: list[TextId]


class EngineerInspectionSpecView(CostSource):
    ref: ref_type('CheckSpec')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    engineering_scope_ref: ref_type('EngineeringScope')
    evaluation_method_ref: ref_type('Method') | None
    requested_check: TextId
    expected_code: ValueState[TextId]
    observation_ref: ref_type('Observation') | None
    issue_refs: list[ref_type('Issue')]


class EngineerInspectionObservationView(CostSource):
    ref: ref_type('Observation')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    engineering_scope_ref: ref_type('EngineeringScope')
    observed_physical_keys: list[TextId]
    method_ref: ref_type('Method')
    check_spec_ref: ref_type('CheckSpec')
    observed_code: ValueState[TextId]
    check_result_ref: ref_type('MethodResult') | None
    access_ref: ref_type('SiteAccess') | None
    work_fact_refs: list[ref_type('WorkFact')]
    observed_window: TimeWindow
    status: Literal['executed', 'unknown', 'failed', 'unsupported']
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A08']


class EngineerInspectionResultView(CostSource):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    check_spec_ref: ref_type('CheckSpec')
    observation_ref: ref_type('Observation')
    method_ref: ref_type('Method')
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    result: EngineerInterfaceReport | None
    executed_at: TimePoint
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A08']


class EngineerInspectionIssueView(CostSource):
    ref: ref_type('Issue')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    engineering_scope_ref: ref_type('EngineeringScope')
    response_requirement_ref: ref_type('ResponseRequirement')
    sender_id: TextId
    authorized_responder_actor_ids: list[TextId]
    response: TextId | None
    response_basis_refs: list[ref_type('Evidence')]
    response_changes_design: bool
    status: Literal['received', 'open', 'unknown', 'closed']
    design_change_ref: ref_type('InspectionDesignChange') | None = None

    @model_serializer(mode='wrap')
    def preserve_original_query(self, handler):
        result = handler(self)
        if self.design_change_ref is None:
            result.pop('design_change_ref', None)
        return result


class EngineerInspectionDesignChangeView(CostSource):
    """Native A09 registration linkage; this projection does not execute or approve a design change."""
    ref: ref_type('InspectionDesignChange')
    run_id: TextId
    organization_id: TextId
    original_task_ref: ref_type('Task')
    current_task_ref: ref_type('Task')
    original_query_ref: ref_type('Issue')
    current_query_ref: ref_type('Issue')
    original_design_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    current_design_ref: ref_type('Deliverable')
    current_content_sha256: Digest
    registration: EngineerRevisionRegistrationView
    deliverable: EngineerSubmissionDeliverableView
    as_of: TimePoint
    status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']


class EngineerInspectionQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    task_ref: ref_type('Task')
    applicable_design_ref: ref_type('Deliverable')
    design_content_sha256: Digest
    question: ArchitectOpportunityQuestion


class EngineerInspectionDependencyView(CostSource):
    ref: ref_type('Dependency')
    task_ref: ref_type('Task')
    satisfied: ValueState[bool]
    purpose: Literal['site_access', 'input', 'predecessor']


def engineer_inspection_schemas():
    return service_intake_schemas(overrides={
        'Task': EngineerInspectionTaskView, 'Deliverable': EngineerInspectionDesignView,
        'Appointment': EngineerAppointmentView, 'ServiceTerms': EngineerServiceTermsView,
        'Method': EngineerInspectionMethodView, 'SiteAccess': EngineerInspectionAccessView,
        'EngineeringScope': EngineerInspectionScopeView, 'CheckSpec': EngineerInspectionSpecView,
        'Observation': EngineerInspectionObservationView, 'MethodResult': EngineerInspectionResultView,
        'Issue': EngineerInspectionIssueView, 'EvidenceTarget': EngineerInspectionQuestionView,
        'WorkProfile': ServiceWorkProfileView, 'WorkEstimate': EngineerPlanningEstimateView,
        'WorkFact': EngineerPlanningWorkFactView, 'ResourceCalendar': EngineerPlanningCalendarView,
        'Qualification': EngineerPlanningQualificationView, 'ResourceAllocation': EngineerPlanningAllocationView,
        'Dependency': EngineerInspectionDependencyView,
        'InspectionDesignChange': EngineerInspectionDesignChangeView,
    })
