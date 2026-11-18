"""Original lawful case queues, review tasks and real reviewer occupancy."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_objects import GovCaseView, GovIntakeQuestion, GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_appointment_objects import QSTaskResourceShare
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.capacity import CapacityCommitment


class GovSchedulingCaseView(GovCaseView):
    available_at: TimePoint
    effective_window: TimeWindow
    jurisdiction_ref: ref_type('Jurisdiction')
    region_id: ValueState[TextId]
    queue_ref: ref_type('CaseQueue')
    task_refs: list[ref_type('Task')]
    status: Literal['accepted', 'awaiting_evidence', 'closed', 'withdrawn']


class GovQueueEntry(StrictRecord):
    case_ref: ref_type('RegulatoryCase')
    entered_at: TimePoint
    status: Literal['ready', 'assigned', 'awaiting_evidence', 'closed']


class GovCaseQueueView(GovAdviceSource):
    ref: ref_type('CaseQueue')
    organization_id: TextId
    ordering_rule_ref: ref_type('Rule')
    entries: list[GovQueueEntry]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint

    @model_validator(mode='after')
    def identities(self):
        unique_refs([row.case_ref for row in self.entries])
        return self


class GovQueueRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    queue_ref: ref_type('CaseQueue')
    ordering: Literal['fifo']
    allows_priority_exception: bool


class GovQueueProfileView(GovAdviceSource):
    ref: ref_type('QueueProfile')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    queue_ref: ref_type('CaseQueue')
    authority_ref: ref_type('Authorization')
    work_profile_ref: ref_type('WorkProfile')
    priority_basis_ref: ref_type('PriorityBasis') | None
    choice: Literal['assign', 'reprioritize', 'request_cooperation']
    question_refs: list[ref_type('EvidenceTarget')]
    note: TextId


class GovSchedulingWorkProfileView(GovAdviceSource):
    ref: ref_type('WorkProfile')
    organization_id: TextId
    effort_unit: TextId
    capacity_unit: TextId
    effort_per_capacity_tick: DecimalString
    method: Literal['constant_capacity_over_half_open_window_v1']
    maximum_assignment_ticks: Annotated[int, Field(gt=0)]


class GovSchedulingTaskView(GovAdviceSource):
    ref: ref_type('Task')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    authority_ref: ref_type('Authorization')
    function_ref: ref_type('FunctionAssignment')
    work_profile_ref: ref_type('WorkProfile')
    estimate_ref: ref_type('WorkEstimate')
    execution_action_id: Literal['GOV-A04', 'GOV-A05', 'GOV-A06', 'GOV-A08', 'GOV-A10', 'GOV-A11']
    function_code: TextId
    discipline_codes: Annotated[list[TextId], Field(min_length=1)]
    remaining_effort: ValueState[Measured]
    work_fact_refs: list[ref_type('WorkFact')]
    work_fact_coverage: Literal['complete', 'partial', 'unknown']
    planned_window: TimeWindow
    resource_shares: Annotated[list[QSTaskResourceShare], Field(min_length=1)]
    dependency_refs: list[ref_type('Dependency')]
    existing_assignment_ref: ref_type('ReviewAssignment') | None
    status: Literal['authorized', 'waiting', 'complete', 'cancelled']
    as_of: TimePoint


class GovSchedulingEstimateView(GovAdviceSource):
    ref: ref_type('WorkEstimate')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded', 'unknown', 'failed']
    method: Literal['constant_capacity_over_half_open_window_v1']


class GovSchedulingWorkFactView(GovAdviceSource):
    ref: ref_type('WorkFact')
    task_ref: ref_type('Task')
    organization_id: TextId
    investment_key: TextId
    effort: Measured
    window: TimeWindow
    status: Literal['committed', 'unknown', 'failed']


class GovSchedulingDependencyView(GovAdviceSource):
    ref: ref_type('Dependency')
    task_ref: ref_type('Task')
    satisfied: ValueState[bool]
    as_of: TimePoint


class GovReviewResourceView(GovAdviceSource):
    ref: ref_type('Resource')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    personnel_ids: ValueState[list[TextId]]
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    qualification_refs: list[ref_type('Qualification')]
    region_id: TextId
    total: Measured


class GovReviewQualificationView(GovAdviceSource):
    ref: ref_type('Qualification')
    organization_id: TextId
    personnel_ids: list[TextId]
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    region_id: TextId
    valid: ValueState[bool]


class GovReviewCalendarView(GovAdviceSource):
    ref: ref_type('ResourceCalendar')
    organization_id: TextId
    resources: list[GovReviewResourceView]
    commitments: list[CapacityCommitment]
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class GovReviewAssignmentView(GovAdviceSource):
    ref: ref_type('ReviewAssignment')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    resource_refs: list[ref_type('Resource')]
    commitment_refs: list[ref_type('ResourceCommitment')]
    window: TimeWindow
    status: Literal['effective', 'released']


class GovSchedulingPriorityView(GovAdviceSource):
    ref: ref_type('PriorityBasis')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    queue_ref: ref_type('CaseQueue')
    ordering_rule_ref: ref_type('Rule')
    authority_ref: ref_type('Authorization')
    priority_authority_ref: ref_type('Authority')
    bypassed_case_refs: list[ref_type('RegulatoryCase')]
    reason: TextId


class GovPriorityAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    case_ref: ref_type('RegulatoryCase')
    queue_ref: ref_type('CaseQueue')
    ordering_rule_ref: ref_type('Rule')
    permitted: ValueState[bool]


class GovSchedulingQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    case_ref: ref_type('RegulatoryCase')
    task_refs: list[ref_type('Task')]
    question: GovIntakeQuestion


def government_scheduling_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovSchedulingCaseView, 'CaseQueue': GovCaseQueueView, 'QueueProfile': GovQueueProfileView,
        'Rule': GovQueueRuleView, 'WorkProfile': GovSchedulingWorkProfileView, 'Task': GovSchedulingTaskView,
        'WorkEstimate': GovSchedulingEstimateView, 'WorkFact': GovSchedulingWorkFactView,
        'Dependency': GovSchedulingDependencyView, 'Resource': GovReviewResourceView,
        'ResourceCalendar': GovReviewCalendarView, 'Qualification': GovReviewQualificationView,
        'ReviewAssignment': GovReviewAssignmentView, 'PriorityBasis': GovSchedulingPriorityView,
        'Authority': GovPriorityAuthorityView,
        'EvidenceTarget': GovSchedulingQuestionView, 'RegulatoryRecipient': GovRecipientView,
        'ResponseRequirement': GovResponseRequirementView, 'Jurisdiction': GovJurisdictionView,
        'RegulatoryMatter': GovMatterView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    registry.register_kind('ResourceCommitment', CapacityCommitment, str, identity_field='commitment_ref')
    return registry
