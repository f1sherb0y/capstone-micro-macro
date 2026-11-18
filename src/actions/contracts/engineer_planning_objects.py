"""Authorized engineering task planning and original investment slices."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Money, DecimalString, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.qs_appointment_objects import QSAllocationView, QSResourceView, QSWorkPlanView, QSTaskResourceShare
from src.actions.contracts.contractor_objects import CommittedResource
from src.actions.contracts.architect_planning_objects import ArchitectInvestigationTaskRegistrationView
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.engineer_objects import EngineerServiceTermsView, EngineerIndependenceRequirementView, EngineerOrganizationRelationsView, EngineerAuthoredTargetView
from src.actions.contracts.engineer_appointment_objects import EngineerIndependenceCheckView, EngineerConflictView
from src.actions.contracts.service_objects import ServiceClarificationTargetView, ServiceQualificationView, ServiceResourceCalendarView, ServiceWorkProfileView, ServiceUse, service_intake_schemas


class EngineerPlanningQuestionTargetView(ServiceClarificationTargetView):
    executor_organization_ids: list[TextId]
    task_refs: list[ref_type('Task')]


class EngineerPlanningProfileView(ServiceWorkProfileView):
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    appointment_ref: ref_type('Appointment')
    task_refs: list[ref_type('Task')]
    prior_plan_ref: ref_type('WorkPlan') | None
    reservation_refs: list[ref_type('ResourceReservation')]
    question_target_refs: list[ref_type('EvidenceTarget')]
    observation_method_ref: ref_type('Method') | None
    discipline_codes: list[TextId]
    note: TextId


class EngineerPlanningResourceView(QSResourceView):
    asset_role: Literal['personnel', 'equipment']
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    qualification_refs: list[ref_type('Qualification')]


class EngineerPlanningCalendarView(ServiceResourceCalendarView):
    resources: list[EngineerPlanningResourceView]


class EngineerPlanningQualificationView(ServiceQualificationView):
    discipline_codes: list[TextId]
    personnel_ids: list[TextId]
    function_codes: list[TextId]


class EngineerPlanningToolDemand(StrictRecord):
    resource_ref: ref_type('Resource')
    capacity: Measured


class EngineerPlanningAccessView(CostSource):
    ref: ref_type('SiteAccess')
    organization_id: TextId
    task_ref: ref_type('Task')
    allowed: ValueState[bool]


class EngineerPlanningObservationMethodView(CostSource):
    ref: ref_type('Method')
    purpose: Literal['investigation', 'observation', 'test']
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    region_ids: list[TextId]
    executor_organization_ids: list[TextId]
    executor_authority_refs: list[ref_type('Authorization')]
    target_refs: list[ref_type('EvidenceTarget')]


class EngineerPlanningTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    authority_ref: ref_type('Authorization')
    function_ref: ref_type('FunctionAssignment')
    function_code: TextId
    discipline_codes: list[TextId]
    tool_demands: list[EngineerPlanningToolDemand]
    access_ref: ref_type('SiteAccess') | None
    work_profile_ref: ref_type('WorkProfile')
    estimate_ref: ref_type('WorkEstimate')
    remaining_effort: ValueState[Measured]
    work_fact_refs: list[ref_type('WorkFact')]
    work_fact_coverage: Literal['complete', 'partial', 'unknown']
    planned_window: TimeWindow
    resource_shares: Annotated[list[QSTaskResourceShare], Field(min_length=1)]
    dependency_refs: list[ref_type('Dependency')]
    existing_allocation_ref: ref_type('ResourceAllocation') | None
    as_of: TimePoint
    status: Literal['authorized', 'waiting', 'complete', 'cancelled', 'paused']


class EngineerInvestigationTaskRegistrationView(ArchitectInvestigationTaskRegistrationView):
    """Actual Engineer intake preserving original discipline and function."""
    ref: ref_type('EngineerInvestigationTaskRegistration')
    discipline_code: TextId
    function_code: TextId


class EngineerPlanningEstimateView(CostSource):
    ref: ref_type('WorkEstimate')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    method: Literal['constant_capacity_over_half_open_window_v1']
    effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded', 'unknown', 'failed']


class EngineerPlanningWorkFactView(CostSource):
    ref: ref_type('WorkFact')
    task_ref: ref_type('Task')
    organization_id: TextId
    investment_key: TextId
    effort: Measured
    internal_cost: Money
    window: TimeWindow
    status: Literal['committed', 'unknown', 'failed']


class EngineerPlanningDependencyView(CostSource):
    ref: ref_type('Dependency')
    input_evidence_refs: list[ref_type('Evidence')]
    task_ref: ref_type('Task')
    deliverable_ref: ref_type('Deliverable') | None
    predecessor_task_ref: ref_type('Task') | None
    required_use: ServiceUse
    satisfied: ValueState[bool]
    as_of: TimePoint


class EngineerPlanningDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    author_organization_ids: ValueState[list[TextId]]
    author_personnel_ids: ValueState[list[TextId]]
    allowed_uses: list[ServiceUse]
    status: Literal['available', 'unavailable', 'unknown']
    invalidated_uses: list[ServiceUse]


class EngineerPlanningAllocationView(QSAllocationView):
    work_fact_refs: list[ref_type('WorkFact')]


class EngineerPlanningReservationItem(StrictRecord):
    task_ref: ref_type('Task')
    commitment: CommittedResource


class EngineerPlanningReservationView(CostSource):
    ref: ref_type('ResourceReservation')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    items: list[EngineerPlanningReservationItem]
    status: Literal['reserved', 'converted', 'released']
    as_of: TimePoint


def engineer_planning_schemas():
    return service_intake_schemas(overrides={
        'ServiceTerms': EngineerServiceTermsView,
        'EvidenceTarget': EngineerPlanningQuestionTargetView,
        'SiteAccess': EngineerPlanningAccessView, 'Method': EngineerPlanningObservationMethodView,
        'IndependenceCheck': EngineerIndependenceCheckView, 'ConflictOfInterest': EngineerConflictView,
        'IndependenceRequirement': EngineerIndependenceRequirementView,
        'OrganizationRelations': EngineerOrganizationRelationsView,
        'DesignOption': EngineerAuthoredTargetView, 'Brief': EngineerAuthoredTargetView,
        'Appointment': EngineerAppointmentView, 'WorkProfile': EngineerPlanningProfileView,
        'ResourceCalendar': EngineerPlanningCalendarView, 'Task': EngineerPlanningTaskView,
        'WorkEstimate': EngineerPlanningEstimateView, 'WorkFact': EngineerPlanningWorkFactView,
        'Dependency': EngineerPlanningDependencyView, 'Deliverable': EngineerPlanningDeliverableView,
        'ResourceAllocation': EngineerPlanningAllocationView, 'ResourceReservation': EngineerPlanningReservationView,
        'EngineerInvestigationTaskRegistration': EngineerInvestigationTaskRegistrationView,
        'WorkPlan': QSWorkPlanView,
        'Qualification': EngineerPlanningQualificationView,
    })
