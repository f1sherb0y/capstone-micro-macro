"""ARCHITECT-A03 confirms original compatible acceptance without side effects."""
from fractions import Fraction

from src.actions.contracts.architect_appointment_objects import (
    ArchitectAcceptanceView, ArchitectAppointmentView, ArchitectRelationshipView,
    ArchitectReservationView, service_terms_digest,
)
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceCommissionAuthorityView, ServiceRequestView,
    ServiceResourceCalendarView, ServiceResponseRequirementView, ServiceTermsView, ServiceWorkProfileView,
)
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def confirm_appointment(context, action_input, reading, *, role='Architect',
                        appointment_schema=ArchitectAppointmentView, acceptance_schema=ArchitectAcceptanceView,
                        reservation_field='existing_reservation_ref', check_professional=None,
                        plan_tasks=None, continue_active=False):
    now, organization = context.business_time, reading.organization_id
    action_id = {'Architect': 'ARCHITECT-A03', 'Engineer': 'ENGINEER-A03', 'QS': 'QS-A03'}[role]
    sources = {}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('architect-appointment-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('architect-appointment-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now):
                    _needs('current_appointment_evidence', [ref])

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'architect-appointment-projection:{ref.kind}')
        evidence(getattr(row, 'evidence_refs', []))
        sources[ref.key()] = ref
        return row

    def current(window):
        clock(window.start)
        return window.contains(now)

    def received(point):
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_appointment_information')

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope, 'note': note, **fields}}

    def amendment_questions():
        questions = []
        for ref in appointment.amendment_target_refs:
            row = read(ref, ServiceClarificationTargetView)
            response = read(row.response_requirement_ref, ServiceResponseRequirementView)
            if (row.request_ref != request.ref or row.scope != action_input.scope
                    or response.request_ref != request.ref or response.scope != action_input.scope
                    or not row.recipient_ids or not set(row.recipient_ids) <= set(response.recipient_ids)
                    or not set(row.recipient_ids) <= {request.client_id, request.payer_id}):
                raise ValueError('Amendment question changes original scope, request or recipients')
            questions.append({'scope': row.scope, 'target_refs': [row.ref], 'question': row.question,
                'recipient_ids': row.recipient_ids, 'evidence_refs': row.evidence_refs,
                'blocking_uses': row.blocking_uses, 'response_requirement_ref': row.response_requirement_ref})
        if not questions:
            _needs('registered_appointment_amendment_questions')
        return questions

    def amendment(note):
        return completed('request_amendment', note, questions=amendment_questions())

    def actor_authority(ref, actor, org, function, action, point):
        grant = read(ref, Authorization)
        assignment = read(function, RoleAssignment)
        evidence(grant.basis_refs + assignment.basis_refs)
        clock(grant.validity.start)
        return (grant.actor_id == actor and grant.organization_id == org and grant.function_ref == function
                and assignment.role == role and action in grant.action_ids and grant.validity.contains(point)
                and any(scope_covers(s, action_input.scope) for s in grant.scopes))

    try:
        appointment = read(action_input.appointment_ref, appointment_schema)
        terms = read(action_input.accepted_terms_ref, ServiceTermsView)
        request = read(appointment.request_ref, ServiceRequestView)
        if (appointment.scope != action_input.scope or terms.scope != action_input.scope
                or request.scope != action_input.scope or appointment.provider_id != context.actor_id
                or appointment.provider_organization_id != organization or request.provider_id != context.actor_id
                or request.provider_organization_id != organization or terms.provider_id != context.actor_id
                or not scope_covers(context.scope, action_input.scope)):
            raise ValueError('Appointment changes the provider, original request or authorized scope')
        received(appointment.received_at)
        received(request.received_at)
        received(terms.issued_at)
        if (terms.request_ref != request.ref or appointment.client_id != request.client_id
                or appointment.client_organization_id != request.client_organization_id
                or appointment.payer_id != request.payer_id or appointment.payer_organization_id != request.payer_organization_id
                or terms.client_id != request.client_id or terms.payer_id != request.payer_id
                or appointment.client_authority_ref != request.client_authority_ref
                or appointment.payer_authority_ref != request.payer_authority_ref
                or terms.relation != appointment.relation):
            raise ValueError('Appointment replaces the independently accepted client, payer or relation')
        if appointment.status == 'withdrawn' or appointment.compatibility == 'decline_incompatible':
            if role != 'Architect':
                return amendment('Original appointment is withdrawn or incompatible; request a compatible authorized appointment')
            return completed('decline_incompatible', 'The original appointment is withdrawn or explicitly incompatible',
                             reason='Original authorized appointment is withdrawn or incompatible')
        if appointment.terms_ref != terms.ref or appointment.terms_digest != service_terms_digest(terms):
            return amendment('Appointment terms differ from the original independently accepted version')
        if appointment.acceptance_ref is None:
            _needs('received_independent_provider_acceptance')
        acceptance = read(appointment.acceptance_ref, acceptance_schema)
        received(acceptance.decided_at); received(acceptance.received_at)
        if acceptance.decided_at.offset > acceptance.received_at.offset:
            raise ValueError('Acceptance receipt precedes its original decision')
        if terms.issued_at.offset > acceptance.decided_at.offset or not terms.effective_window.contains(acceptance.decided_at):
            return amendment('Provider acceptance was not within the original issued terms validity')
        if (acceptance.actor_id != context.actor_id or acceptance.organization_id != organization
                or acceptance.scope != action_input.scope or acceptance.request_ref != request.ref):
            raise ValueError('Appointment borrows another provider acceptance or request')
        if acceptance.choice != 'accept':
            if role != 'Architect':
                return amendment('Original provider decision did not accept this appointment')
            return completed('decline_incompatible', 'The provider has not accepted this original service', reason='Original provider decision declined')
        if (acceptance.accepted_terms_ref != terms.ref or acceptance.terms_digest != service_terms_digest(terms)):
            return amendment('Received provider acceptance covers another service terms version')
        if not actor_authority(acceptance.authority_ref, acceptance.actor_id, organization,
                               acceptance.function_ref, acceptance.action_id, acceptance.decided_at):
            _needs('authorized_independent_provider_acceptance')
        acceptance_grant = read(acceptance.authority_ref, Authorization)
        if not {r.key() for r in acceptance.evidence_refs} <= {r.key() for r in acceptance_grant.readable_refs}:
            _needs('authorized_original_acceptance_evidence')

        unique_identities(action_input.function_refs)
        if not action_input.function_refs or set(action_input.function_refs) != set(appointment.function_refs):
            _needs('complete_original_appointment_functions', appointment.function_refs)
        grants = [read(ref, Authorization) for ref in appointment.function_authority_refs]
        for function in action_input.function_refs:
            matched = [g for g in grants if g.function_ref == function]
            if not matched or not any(actor_authority(g.ref, context.actor_id, organization, function,
                    action_id, now) for g in matched):
                _needs('authorized_appointment_function', [function])

        # An existing relationship is reconciled along its original identity, without creating occupancy again.
        if appointment.status == 'active':
            relationship = read(appointment.service_relationship_ref, ArchitectRelationshipView)
            if (relationship.organization_id != organization or relationship.appointment_ref != appointment.ref
                    or relationship.accepted_terms_ref != terms.ref or relationship.scope != action_input.scope
                    or set(relationship.function_refs) != set(action_input.function_refs)):
                raise ValueError('Active relationship changes original appointment or accepted terms')
            if not current(relationship.effective_window):
                _needs('current_original_service_relationship')
            if not continue_active or not action_input.task_refs:
                _needs('reconcile_existing_service_relationship', [relationship.ref])

        received(terms.issued_at)
        if appointment.status != 'active' and (not (current(appointment.effective_window) and current(terms.effective_window)
                and current(request.effective_window)) or terms.status == 'withdrawn' or request.status == 'withdrawn'):
            return amendment('Appointment or accepted terms are no longer applicable; request current original terms')
        service = _known(terms.service_code, 'accepted_service_code')
        authorities = (
            (appointment.client_authority_ref, request.client_id, request.client_organization_id,
             'internal_service' if appointment.relation == 'internal' else 'commission_service'),
            (appointment.payer_authority_ref, request.payer_id, request.payer_organization_id,
             'internal_service' if appointment.relation == 'internal' else 'authorize_payment'),
        ) if appointment.status != 'active' else ()
        for ref, actor, org, purpose in authorities:
            authority = read(ref, ServiceCommissionAuthorityView)
            if (authority.actor_id != actor or authority.organization_id != org or purpose not in authority.purposes
                    or service not in authority.service_codes or not current(authority.validity)
                    or not any(scope_covers(s, action_input.scope) for s in authority.scopes)):
                _needs('current_client_or_payer_appointment_authority', [ref])
        if appointment.relation == 'internal' and (request.client_organization_id != organization
                or request.payer_organization_id != organization):
            raise ValueError('Internal appointment uses another organization as client or payer')
        if appointment.relation == 'internal' and decimal_fraction(_known(terms.fee, 'internal_service_fee').value) != 0:
            raise ValueError('Internal appointment cannot create a service fee to the same organization')

        calendar = read(appointment.capacity_ref, ServiceResourceCalendarView)
        if calendar.organization_id != organization or calendar.as_of != now or calendar.coverage != 'complete':
            _needs('complete_current_original_resource_calendar', [calendar.ref])
        allowed_resource_keys = None
        if check_professional is not None:
            professional = check_professional(appointment, terms, request, calendar, read, current,
                                              evidence, completed, amendment, amendment_questions)
            if isinstance(professional, dict):
                return professional
            allowed_resource_keys = professional
        if plan_tasks is not None:
            return plan_tasks(appointment, terms, request, calendar, read, current, evidence, completed, amendment)
        if terms.work_profile_ref is None:
            _needs('accepted_service_work_profile')
        profile = read(terms.work_profile_ref, ServiceWorkProfileView)
        if not current(profile.effective_window):
            _needs('current_original_work_profile')
        region = _known(terms.region_id, 'accepted_service_region')
        window = _known(terms.desired_window, 'accepted_work_window')
        effort = _known(terms.effort_estimate, 'accepted_work_effort')
        clock(window.start)
        if (profile.method != 'constant_capacity_over_half_open_window_v1' or profile.clock_ref != now.clock_ref
                or window.bounds != 'closed_open' or window.start.offset >= window.end.offset
                or effort.unit != profile.effort_unit or region not in profile.region_ids
                or service not in profile.service_codes or _known(terms.object_type, 'accepted_object_type') not in profile.object_types):
            _unsupported('architect-appointment-work-domain')
        if window.start.offset < now.offset:
            return amendment('The originally accepted work window has already started; request an explicit revised schedule')
        if not (profile.effective_window.start.offset <= window.start.offset
                and window.end.offset <= profile.effective_window.end.offset):
            return amendment('The work profile does not cover the whole accepted work window')
        demand = decimal_fraction(effort.value) / decimal_fraction(profile.effort_per_capacity_tick) / (window.end.offset - window.start.offset)
        evidence([effort.basis_ref])
        resources = {row.resource_ref.key(): row for row in calendar.resources}
        commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
        for item in calendar.commitments:
            if item.resource_ref.key() not in resources:
                raise ValueError('Complete current calendar omits the original committed resource version')
        reservation = None
        reservation_ref = getattr(action_input, reservation_field)
        if reservation_ref != appointment.reservation_ref:
            _needs('exact_original_appointment_reservation')
        if reservation_ref is not None:
            reservation = read(reservation_ref, ArchitectReservationView)
            if (reservation.organization_id != organization or reservation.scope != action_input.scope
                    or reservation.appointment_ref != appointment.ref or reservation.terms_ref != terms.ref):
                raise ValueError('Reservation belongs to another organization, appointment or terms version')
            if reservation.as_of != now:
                _needs('current_original_appointment_reservation')
            if reservation.status == 'converted':
                _needs('reconcile_converted_original_reservation', [reservation.relationship_ref])
            if reservation.status == 'released' or not current(reservation.effective_window):
                return amendment('Original reservation is released or no longer applicable; request explicit resource reassessment')
            for allocation in reservation.allocations:
                original = commitments.get(allocation.commitment_ref.key())
                if original != allocation:
                    _needs('exact_original_reserved_occupancy', [allocation.commitment_ref])
                resource = resources.get(allocation.resource_ref.key())
                if (resource is None or resource.resource_kind != profile.resource_kind
                        or (allowed_resource_keys is not None and resource.resource_ref.key() not in allowed_resource_keys)
                        or _known(resource.region_id, 'reserved_resource_region') != region
                        or allocation.window != window or allocation.quantity.unit != profile.capacity_unit):
                    return amendment('Original reserved resource does not cover accepted location, unit and work window')
            reserved = sum((decimal_fraction(a.quantity.value) for a in reservation.allocations), Fraction())
            if reserved != demand:
                return amendment('Original reserved quantity does not match accepted work demand')

        occupied = list(calendar.commitments)
        if reservation is not None:
            reserved_ids = {a.commitment_ref.key() for a in reservation.allocations}
            occupied = [row for row in occupied if row.commitment_ref.key() not in reserved_ids]
        # Each reserved allocation is checked on its own physical resource; pooling cannot hide an overloaded reservation.
        demands = [(None, demand)] if reservation is None else [(a.resource_ref.key(), decimal_fraction(a.quantity.value)) for a in reservation.allocations]
        for resource_key, amount in demands:
            chosen = [r for r in calendar.resources if (resource_key is None or r.resource_ref.key() == resource_key)
                      and (allowed_resource_keys is None or r.resource_ref.key() in allowed_resource_keys)]
            quantities = []
            for row in chosen:
                quantity = _known(row.total, 'actual_current_resource_capacity')
                evidence([quantity.basis_ref])
                quantities.append({'resource_ref': row.resource_ref, 'resource_kind': row.resource_kind,
                    'region_id': _known(row.region_id, 'actual_resource_region'), 'total': quantity,
                    'effective_window': row.effective_window})
            selected_keys = {r.resource_ref.key() for r in chosen}
            relevant = [r for r in occupied if r.resource_ref.key() in selected_keys]
            for row in relevant:
                evidence([row.quantity.basis_ref])
            result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref,
                demands=[{'resource_kind': profile.resource_kind, 'region_id': region, 'unit': profile.capacity_unit,
                    'amount': ExactAmount(numerator=amount.numerator, denominator=amount.denominator), 'window': window,
                    'basis_refs': [effort.basis_ref]}], resources=quantities,
                commitments=[row.model_dump(mode='python') for row in relevant], source_refs=list(sources.values())))
            if result.kind != 'ok':
                if result.kind == 'invalid_input':
                    _unsupported('architect-appointment-capacity-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information': raw['requested_refs'] = []
                raise ObservationGap(raw)
            if not result.value.feasible:
                return amendment('Current original shared calendar cannot honor this accepted appointment')
        return completed('confirm', 'Confirm compatibility with independent same-version acceptance and current resources; formal relationship and reservation conversion remain host operations',
                         appointment_ref=appointment.ref, accepted_terms_ref=terms.ref)
    except ObservationGap as gap:
        return gap.result
