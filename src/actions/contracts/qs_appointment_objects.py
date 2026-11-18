"""Received QS appointments, authorized tasks and original allocation identities."""
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.architect_appointment_objects import (
    ArchitectAcceptanceView, ArchitectAppointmentView, ArchitectRelationshipView, ArchitectReservationView,
)
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_objects import CommittedResource, ResourceCapacity
from src.actions.contracts.qs_objects import QSConflictCheckView
from src.actions.contracts.qs_research_objects import QSResearchTaskRegistrationView
from src.actions.contracts.service_objects import SourcedServiceProjection, ServiceResourceCalendarView, service_intake_schemas
from src.methods.pricing import decimal_fraction


class QSAppointmentView(ArchitectAppointmentView):
    capability_ref: ref_type('Capability')
    conflict_check_ref: ref_type('ConflictCheck')
    task_refs: list[ref_type('Task')]
    existing_allocation_refs: list[ref_type('ResourceAllocation')]
    prior_plan_ref: ref_type('WorkPlan') | None


class QSAcceptanceView(ArchitectAcceptanceView):
    action_id: Literal['QS-A02']


class QSAppointmentConflictView(QSConflictCheckView):
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')


class QSResourceView(ResourceCapacity):
    personnel_ids: ValueState[list[TextId]]
    suitable: ValueState[bool]


class QSTaskCalendarView(ServiceResourceCalendarView):
    resources: list[QSResourceView]

    @model_validator(mode='after')
    def one_real_person(self):
        people = []
        for row in self.resources:
            if row.personnel_ids.state == 'known': people.extend(row.personnel_ids.value)
        if len(set(people)) != len(people): raise ValueError('QS personnel counted more than once')
        return self


class QSTaskResourceShare(StrictRecord):
    resource_ref: ref_type('Resource')
    share: DecimalString


class QSTaskView(SourcedServiceProjection):
    ref: ref_type('Task')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    scope: ScopeRef
    function_ref: ref_type('FunctionAssignment')
    function_code: TextId
    authority_ref: ref_type('Authorization')
    work_profile_ref: ref_type('WorkProfile')
    total_effort: Measured
    remaining_effort: ValueState[Measured]
    planned_window: TimeWindow
    resource_shares: list[QSTaskResourceShare]
    dependency_refs: list[ref_type('Dependency')]
    existing_allocation_ref: ref_type('ResourceAllocation') | None
    as_of: TimePoint
    status: Literal['authorized', 'waiting', 'complete', 'cancelled']

    @model_validator(mode='after')
    def finite_original_task(self):
        unique_identities([row.resource_ref for row in self.resource_shares])
        unique_identities(self.dependency_refs)
        if (not self.resource_shares or any(decimal_fraction(row.share) <= 0 for row in self.resource_shares)
                or sum(decimal_fraction(row.share) for row in self.resource_shares) != 1):
            raise ValueError('Task resource shares must be positive and conserve the whole effort')
        if decimal_fraction(self.total_effort.value) <= 0: raise ValueError('Task total effort must be positive')
        if self.remaining_effort.state == 'known':
            remaining = self.remaining_effort.value
            if (remaining.unit != self.total_effort.unit or decimal_fraction(remaining.value) <= 0
                    or decimal_fraction(remaining.value) > decimal_fraction(self.total_effort.value)):
                raise ValueError('Remaining effort must be positive and no larger than the original task')
        return self


class QSAllocationView(SourcedServiceProjection):
    ref: ref_type('ResourceAllocation')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    task_ref: ref_type('Task')
    scope: ScopeRef
    work_plan_ref: ref_type('WorkPlan')
    commitments: list[CommittedResource]
    status: Literal['active', 'released']
    as_of: TimePoint


class QSWorkPlanView(SourcedServiceProjection):
    ref: ref_type('WorkPlan')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    scope: ScopeRef
    task_refs: list[ref_type('Task')]
    allocation_refs: list[ref_type('ResourceAllocation')]
    authority_ref: ref_type('Authorization')
    status: Literal['authorized', 'withdrawn']


class QSTaskDependencyView(SourcedServiceProjection):
    ref: ref_type('Dependency')
    scope: ScopeRef
    task_ref: ref_type('Task')
    satisfied: ValueState[bool]
    as_of: TimePoint


def qs_appointment_schemas():
    return service_intake_schemas(overrides={
        'Appointment': QSAppointmentView, 'RecordedDecision': QSAcceptanceView,
        'ResourceReservation': ArchitectReservationView, 'ServiceRelationship': ArchitectRelationshipView,
        'ResourceCalendar': QSTaskCalendarView, 'ConflictCheck': QSAppointmentConflictView,
        'Task': QSTaskView, 'ResourceAllocation': QSAllocationView, 'WorkPlan': QSWorkPlanView,
        'Dependency': QSTaskDependencyView,
        'QSResearchTaskRegistration': QSResearchTaskRegistrationView,
    })
