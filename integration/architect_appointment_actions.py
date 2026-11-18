"""Assemble original Architect A03 appointments and independent acceptance sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_appointment_objects import (
    ArchitectAcceptanceView, ArchitectAppointmentView, ArchitectRelationshipView,
    ArchitectReservationView, architect_appointment_schemas,
)
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceRequestView, ServiceResourceCalendarView,
    ServiceResponseRequirementView, ServiceTermsView,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedArchitectAppointment(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A03'


class ArchitectAppointmentActionAssembler(ArchitectOpportunityActionAssembler):
    """Freeze original appointment identities without confirming or reserving work.

    The application holds its current source/authorization guard. Original
    processor checks independently recorded acceptance, exact terms digests,
    valid function authority, current commitments and all three choices. Older
    terms, decline records, released reservations and null reservations retain
    their original state. Assembly creates no relationship or resource occupancy.
    """
    ACTION_ID = 'ARCHITECT-A03'
    SOURCE_SCHEMAS = staticmethod(architect_appointment_schemas)

    def build(self, context, *, scope, appointment_ref, accepted_terms_ref, function_refs, existing_reservation_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'appointment_ref': appointment_ref, 'accepted_terms_ref': accepted_terms_ref,
            'function_refs': function_refs, 'existing_reservation_ref': existing_reservation_ref},
            prepared_type=PreparedArchitectAppointment, validate_sources=validate_architect_appointment_sources)

    def build_from_owner_commission(self, context, *, owner_decision, provider_decision,
            validate_mapping, **appointment_inputs):
        """Link independently saved parties to an actually received appointment.

        The caller holds the existing source guard and supplies the native
        appointment and acceptance. This creates neither party's acceptance.
        """
        from integration.owner_architect_commission_handoff import validate_owner_architect_commission

        prepared = self.build(context, **appointment_inputs)
        validate_owner_architect_commission(owner_decision, provider_decision,
            prepared=prepared, validate_mapping=validate_mapping)
        return prepared


def validate_architect_appointment_sources(action_input, *, context, organization_id, sources):
    """Check original parties and related sources without evaluating compatibility."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect appointment lacks its exact original concrete source')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Architect appointment input leaves its original authorized scope')
    unique_identities(action_input.function_refs)
    appointment = read(action_input.appointment_ref, ArchitectAppointmentView)
    terms = read(action_input.accepted_terms_ref, ServiceTermsView)
    if (appointment.provider_organization_id != organization_id or appointment.provider_id != context.actor_id
            or terms.provider_id != context.actor_id or appointment.scope != action_input.scope
            or terms.scope != action_input.scope or terms.request_ref.key() != appointment.request_ref.key()
            or terms.client_id != appointment.client_id or terms.payer_id != appointment.payer_id
            or terms.relation != appointment.relation):
        raise TaskConflict('Architect appointment changes original provider, request, parties or scope')
    if appointment.request_ref.key() in sources:
        request = read(appointment.request_ref, ServiceRequestView)
        if (request.scope != action_input.scope
                or any(getattr(request, name) != getattr(appointment, name) for name in (
                    'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
                    'payer_id', 'payer_organization_id', 'client_authority_ref', 'payer_authority_ref'))):
            raise TaskConflict('Architect appointment changes its original service request or parties')
    if appointment.acceptance_ref is not None and appointment.acceptance_ref.key() in sources:
        acceptance = read(appointment.acceptance_ref, ArchitectAcceptanceView)
        if (acceptance.actor_id != context.actor_id or acceptance.organization_id != organization_id
                or acceptance.scope != action_input.scope or acceptance.request_ref.key() != appointment.request_ref.key()):
            raise TaskConflict('Architect appointment borrows another provider acceptance or request')
        # Its original choice, accepted version and digest remain processor inputs.
    if appointment.capacity_ref.key() in sources:
        read(appointment.capacity_ref, ServiceResourceCalendarView)
    if action_input.existing_reservation_ref is not None:
        reservation = read(action_input.existing_reservation_ref, ArchitectReservationView)
        if (reservation.organization_id != organization_id or reservation.scope != action_input.scope
                or reservation.appointment_ref.key() != appointment.ref.key()):
            raise TaskConflict('Architect reservation changes its original organization, appointment or scope')
        # Preserve old terms and actual occupancy; never convert or release here.
    if appointment.service_relationship_ref is not None and appointment.service_relationship_ref.key() in sources:
        relationship = read(appointment.service_relationship_ref, ArchitectRelationshipView)
        if (relationship.organization_id != organization_id or relationship.scope != action_input.scope
                or relationship.appointment_ref.key() != appointment.ref.key()):
            raise TaskConflict('Architect service relationship changes its original organization, appointment or scope')
    for ref in appointment.amendment_target_refs:
        if ref.key() in sources:
            question = read(ref, ServiceClarificationTargetView)
            if question.request_ref.key() != appointment.request_ref.key() or question.scope != action_input.scope:
                raise TaskConflict('Architect amendment changes its original request or scope')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, ServiceResponseRequirementView)
                if response.request_ref.key() != appointment.request_ref.key() or response.scope != action_input.scope:
                    raise TaskConflict('Architect amendment response changes its original request or scope')
