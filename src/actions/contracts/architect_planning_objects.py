"""Authorized architect task planning and original investment slices."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_appointment_objects import ArchitectAppointmentView
from src.actions.contracts.qs_appointment_objects import QSAllocationView, QSResourceView, QSWorkPlanView, QSTaskResourceShare
from src.actions.contracts.contractor_objects import CommittedResource
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceQualificationView, ServiceResourceCalendarView, ServiceWorkProfileView, ServiceUse, service_intake_schemas


class ArchitectPlanningProfileView(ServiceWorkProfileView):
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    appointment_ref: ref_type('Appointment')
    task_refs: list[ref_type('Task')]
    prior_plan_ref: ref_type('WorkPlan') | None
    reservation_refs: list[ref_type('ResourceReservation')]
    question_target_refs: list[ref_type('EvidenceTarget')]
    note: TextId


class ArchitectPlanningResourceView(QSResourceView):
    function_codes: list[TextId]
    qualification_refs: list[ref_type('Qualification')]


class ArchitectPlanningCalendarView(ServiceResourceCalendarView):
    resources: list[ArchitectPlanningResourceView]


class ArchitectPlanningQualificationView(ServiceQualificationView):
    personnel_ids: list[TextId]
    function_codes: list[TextId]


class ArchitectPlanningTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    authority_ref: ref_type('Authorization')
    function_ref: ref_type('FunctionAssignment')
    function_code: TextId
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


class ArchitectInvestigationTaskRegistrationView(CostSource):
    """Observed research request intake, continuation confirmation and A04 task."""
    ref: ref_type('ArchitectInvestigationTaskRegistration')
    run_id: TextId
    proposer_organization_id: TextId
    planner_organization_id: TextId
    planner_actor_id: TextId
    planner_function_ref: ref_type('FunctionAssignment')
    task_sha256: Digest
    record_sha256: Digest
    result_sha256: Digest
    source_reading_sha256: Digest
    source_task_ref: ref_type('Task')
    request_profile_ref: ref_type('ResearchRequestProfile')
    request_profile_sha256: Digest
    request_payload_sha256: Digest
    research_authority_ref: ref_type('Authority')
    research_limit_ref: ref_type('ResearchLimit')
    purpose: Literal['investigation', 'preparation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    source_work_profile_ref: ref_type('WorkProfile') | None
    source_dependency_refs: list[ref_type('Dependency')]
    questions: list[ArchitectOpportunityQuestion]
    effort_estimate: ValueState[Measured]
    incremental_cost: ValueState[Money]
    desired_window: ValueState[TimeWindow]
    planning_task_ref: ref_type('Task')
    planning_task_sha256: Digest
    continuation_evidence_ref: ref_type('Evidence')
    continuation_sha256: Digest
    registration_service_id: TextId
    registration_status: Literal['pending', 'unknown', 'registered', 'failed', 'rejected']
    confirmed_at: TimePoint | None
    registered_at: TimePoint | None


class ArchitectPlanningEstimateView(CostSource):
    ref: ref_type('WorkEstimate')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    method: Literal['constant_capacity_over_half_open_window_v1']
    effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded', 'unknown', 'failed']


class ArchitectPlanningWorkFactView(CostSource):
    ref: ref_type('WorkFact')
    task_ref: ref_type('Task')
    organization_id: TextId
    investment_key: TextId
    effort: Measured
    internal_cost: Money
    window: TimeWindow
    status: Literal['committed', 'unknown', 'failed']


class ArchitectPlanningDependencyView(CostSource):
    ref: ref_type('Dependency')
    task_ref: ref_type('Task')
    deliverable_ref: ref_type('Deliverable') | None
    predecessor_task_ref: ref_type('Task') | None
    required_use: ServiceUse
    satisfied: ValueState[bool]
    as_of: TimePoint


class ArchitectPlanningDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    allowed_uses: list[ServiceUse]
    status: Literal['available', 'unavailable', 'unknown']
    invalidated_uses: list[ServiceUse]


class ArchitectPlanningAllocationView(QSAllocationView):
    work_fact_refs: list[ref_type('WorkFact')]


class ArchitectPlanningReservationItem(StrictRecord):
    task_ref: ref_type('Task')
    commitment: CommittedResource


class ArchitectPlanningReservationView(CostSource):
    ref: ref_type('ResourceReservation')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    items: list[ArchitectPlanningReservationItem]
    status: Literal['reserved', 'converted', 'released']
    as_of: TimePoint


def architect_planning_schemas():
    return service_intake_schemas(overrides={
        'Appointment': ArchitectAppointmentView, 'WorkProfile': ArchitectPlanningProfileView,
        'ResourceCalendar': ArchitectPlanningCalendarView, 'Task': ArchitectPlanningTaskView,
        'WorkEstimate': ArchitectPlanningEstimateView, 'WorkFact': ArchitectPlanningWorkFactView,
        'Dependency': ArchitectPlanningDependencyView, 'Deliverable': ArchitectPlanningDeliverableView,
        'ResourceAllocation': ArchitectPlanningAllocationView, 'ResourceReservation': ArchitectPlanningReservationView,
        'ArchitectInvestigationTaskRegistration': ArchitectInvestigationTaskRegistrationView,
        'WorkPlan': QSWorkPlanView,
        'Qualification': ArchitectPlanningQualificationView,
    })
