"""Received appointments, independent acceptance and original resource reservations."""
import hashlib
import json
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.common import ScopeRef, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.contractor_objects import CommittedResource
from src.actions.contracts.service_objects import SourcedServiceProjection, service_intake_schemas


def service_terms_digest(terms):
    data = terms.model_dump(mode='json') if hasattr(terms, 'model_dump') else terms
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class ArchitectAppointmentView(SourcedServiceProjection):
    ref: ref_type('Appointment')
    scope: ScopeRef
    request_ref: ref_type('ServiceRequest')
    provider_id: TextId
    provider_organization_id: TextId
    client_id: TextId
    client_organization_id: TextId
    payer_id: TextId
    payer_organization_id: TextId
    relation: Literal['external', 'internal']
    terms_ref: ref_type('ServiceTerms')
    terms_digest: TextId
    acceptance_ref: ref_type('RecordedDecision') | None
    client_authority_ref: ref_type('Authority')
    payer_authority_ref: ref_type('Authority')
    capacity_ref: ref_type('ResourceCalendar')
    function_refs: list[ref_type('FunctionAssignment')]
    function_authority_refs: list[ref_type('Authorization')]
    reservation_ref: ref_type('ResourceReservation') | None
    amendment_target_refs: list[ref_type('EvidenceTarget')]
    compatibility: Literal['review', 'decline_incompatible']
    received_at: TimePoint
    effective_window: TimeWindow
    status: Literal['selected', 'active', 'withdrawn']
    service_relationship_ref: ref_type('ServiceRelationship') | None

    @model_validator(mode='after')
    def original_identity_sets(self):
        for refs in (self.function_refs, self.function_authority_refs, self.amendment_target_refs):
            unique_identities(refs)
        if self.status == 'active' and self.service_relationship_ref is None:
            raise ValueError('Active appointment needs its original service relationship')
        return self


class ArchitectAcceptanceView(SourcedServiceProjection):
    ref: ref_type('RecordedDecision')
    action_id: Literal['ARCHITECT-A02']
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    scope: ScopeRef
    request_ref: ref_type('ServiceRequest')
    accepted_terms_ref: ref_type('ServiceTerms')
    terms_digest: TextId
    choice: Literal['accept', 'decline']
    decided_at: TimePoint
    received_at: TimePoint


class ArchitectReservationView(SourcedServiceProjection):
    ref: ref_type('ResourceReservation')
    organization_id: TextId
    scope: ScopeRef
    appointment_ref: ref_type('Appointment')
    terms_ref: ref_type('ServiceTerms')
    allocations: list[CommittedResource]
    as_of: TimePoint
    effective_window: TimeWindow
    status: Literal['reserved', 'converted', 'released']
    relationship_ref: ref_type('ServiceRelationship') | None

    @model_validator(mode='after')
    def unique_original_occupancy(self):
        unique_identities([row.commitment_ref for row in self.allocations])
        if not self.allocations:
            raise ValueError('Reservation must reference actual original allocations')
        if self.status == 'converted' and self.relationship_ref is None:
            raise ValueError('Converted reservation needs its original relationship')
        return self


class ArchitectRelationshipView(SourcedServiceProjection):
    ref: ref_type('ServiceRelationship')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    accepted_terms_ref: ref_type('ServiceTerms')
    scope: ScopeRef
    function_refs: list[ref_type('FunctionAssignment')]
    commitment_refs: list[ref_type('ResourceCommitment')]
    effective_window: TimeWindow


def architect_appointment_schemas():
    return service_intake_schemas(overrides={
        'Appointment': ArchitectAppointmentView, 'RecordedDecision': ArchitectAcceptanceView,
        'ResourceReservation': ArchitectReservationView, 'ServiceRelationship': ArchitectRelationshipView,
    })
