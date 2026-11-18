"""Original Engineer appointment and sourced independence checks."""
from typing import Literal

from src.actions.contracts.architect_appointment_objects import (
    ArchitectAcceptanceView, ArchitectAppointmentView, ArchitectRelationshipView, ArchitectReservationView,
)
from src.actions.contracts.common import Reference, ScopeRef, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.engineer_objects import (
    EngineerAuthoredTargetView, EngineerIndependenceRequirementView, EngineerIntakeCapabilityView,
    EngineerOrganizationRelationsView, EngineerQualificationView, EngineerResourceCalendarView,
    EngineerServiceMethodView, EngineerServiceRequestView, EngineerServiceTermsView, EngineerWorkProfileView,
)
from src.actions.contracts.service_objects import SourcedServiceProjection, service_intake_schemas


class EngineerAppointmentView(ArchitectAppointmentView):
    capability_ref: ref_type('Capability')
    independence_check_ref: ref_type('IndependenceCheck') | None


class EngineerAcceptanceView(ArchitectAcceptanceView):
    action_id: Literal['ENGINEER-A02']


class EngineerIndependenceCheckView(SourcedServiceProjection):
    ref: ref_type('IndependenceCheck')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    requirement_ref: ref_type('IndependenceRequirement')
    scope: ScopeRef
    checked_resource_refs: list[ref_type('Resource')]
    conflict_refs: list[ref_type('ConflictOfInterest')]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    as_of: TimePoint
    effective_window: TimeWindow


class EngineerConflictView(SourcedServiceProjection):
    ref: ref_type('ConflictOfInterest')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    requirement_ref: ref_type('IndependenceRequirement')
    scope: ScopeRef
    target_ref: Reference
    kind: Literal['organization', 'personnel']
    conflicting_ids: list[TextId]
    effective_window: TimeWindow


def engineer_appointment_schemas():
    return service_intake_schemas(overrides={
        'Appointment': EngineerAppointmentView, 'RecordedDecision': EngineerAcceptanceView,
        'ResourceReservation': ArchitectReservationView, 'ServiceRelationship': ArchitectRelationshipView,
        'ServiceRequest': EngineerServiceRequestView, 'ServiceTerms': EngineerServiceTermsView,
        'Capability': EngineerIntakeCapabilityView, 'Qualification': EngineerQualificationView,
        'ResourceCalendar': EngineerResourceCalendarView, 'Method': EngineerServiceMethodView,
        'WorkProfile': EngineerWorkProfileView, 'IndependenceRequirement': EngineerIndependenceRequirementView,
        'OrganizationRelations': EngineerOrganizationRelationsView, 'Deliverable': EngineerAuthoredTargetView,
        'DesignOption': EngineerAuthoredTargetView, 'Brief': EngineerAuthoredTargetView,
        'IndependenceCheck': EngineerIndependenceCheckView, 'ConflictOfInterest': EngineerConflictView,
    })
