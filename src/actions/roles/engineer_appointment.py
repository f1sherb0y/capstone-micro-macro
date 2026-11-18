"""ENGINEER-A03 checks professional scope and original independence evidence."""
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.engineer_appointment_objects import (
    EngineerAcceptanceView, EngineerAppointmentView, EngineerConflictView, EngineerIndependenceCheckView,
)
from src.actions.contracts.engineer_objects import (
    EngineerAuthoredTargetView, EngineerIndependenceRequirementView, EngineerIntakeCapabilityView,
    EngineerOrganizationRelationsView, EngineerQualificationView, EngineerResourceCalendarView,
    EngineerServiceMethodView, EngineerServiceTermsView, EngineerWorkProfileView,
)
from src.actions.roles.architect_appointment import confirm_appointment
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def confirm_engineer_appointment(context, action_input, reading):
    def professional(appointment, terms, request, calendar, read, current, evidence, completed, amendment, questions):
        if not isinstance(terms, EngineerServiceTermsView) or not isinstance(calendar, EngineerResourceCalendarView):
            _unsupported('engineer-appointment-professional-projections')
        capability = read(appointment.capability_ref, EngineerIntakeCapabilityView)
        if capability.organization_id != reading.organization_id:
            raise ValueError('Appointment uses another organization capability')
        if not current(capability.effective_window): _needs('current_engineer_appointment_capability')
        disciplines = set(_known(terms.discipline_codes, 'accepted_engineer_disciplines'))
        function = _known(terms.function_code, 'accepted_engineer_function')
        if function not in {'design', 'independent_review', 'technical_support', 'contract_engineer'}:
            _unsupported('engineer-appointment-function-domain')
        if (not disciplines <= set(_known(capability.discipline_codes, 'current_engineer_disciplines'))
                or function not in _known(capability.function_codes, 'current_engineer_functions')
                or not set(_known(terms.requested_uses, 'accepted_engineer_uses')) <= set(_known(capability.allowed_uses, 'current_engineer_uses'))
                or not set(_known(terms.responsibility_codes, 'accepted_engineer_responsibilities')) <= set(_known(capability.responsibility_codes, 'current_engineer_responsibilities'))):
            return amendment('Current professional scope does not cover the accepted discipline, function, use or responsibility')
        if capability.qualification_coverage != 'complete': _needs('complete_engineer_appointment_qualifications')
        region, service = _known(terms.region_id, 'accepted_engineer_region'), _known(terms.service_code, 'accepted_engineer_service')
        qualifications = [read(ref, EngineerQualificationView) for ref in capability.qualification_refs]
        for row in qualifications:
            if row.organization_id != reading.organization_id: raise ValueError('Qualification belongs to another organization')
        for code in _known(terms.required_qualification_codes, 'accepted_engineer_qualifications'):
            matching = [row for row in qualifications if row.code == code and current(row.effective_window)
                and region in row.region_ids and service in row.service_codes and disciplines <= set(row.discipline_codes)
                and function in row.function_codes]
            if not any(_known(row.standing, 'current_engineer_qualification_standing') for row in matching):
                return amendment('Current qualification does not cover the exact accepted professional function')
        for ref in _known(terms.required_method_refs, 'accepted_engineer_methods'):
            method = read(ref, EngineerServiceMethodView)
            if (not current(method.effective_window) or not disciplines <= set(method.discipline_codes)
                    or region not in method.region_ids or service not in method.service_codes):
                _unsupported('engineer-appointment-professional-method-domain')
        if terms.work_profile_ref is not None:
            profile = read(terms.work_profile_ref, EngineerWorkProfileView)
            if not disciplines <= set(profile.discipline_codes): _unsupported('engineer-appointment-work-discipline-domain')
        resource_kind = profile.resource_kind if terms.work_profile_ref is not None else None
        eligible = [row for row in calendar.resources if (resource_kind is None or row.resource_kind == resource_kind)
                    and _known(row.region_id, 'current_engineer_resource_region') == region
                    and disciplines <= set(_known(row.discipline_codes, 'current_resource_disciplines'))
                    and _known(row.suitable, 'current_resource_suitability')]
        allowed_keys = {row.resource_ref.key() for row in eligible}
        check_ref = action_input.independence_check_ref
        if check_ref != appointment.independence_check_ref:
            _needs('exact_original_appointment_independence_check')
        requirement_ref = terms.independence_requirement_ref
        if requirement_ref is None:
            if function == 'independent_review' or check_ref is not None:
                _needs('accepted_independent_review_template')
            return allowed_keys
        if check_ref is None: _needs('required_appointment_independence_check')
        check = read(check_ref, EngineerIndependenceCheckView)
        if (check.organization_id != reading.organization_id or check.appointment_ref != appointment.ref
                or check.accepted_terms_ref != terms.ref or check.requirement_ref != requirement_ref or check.scope != terms.scope):
            raise ValueError('Independence check changes the original organization, appointment, terms or requirement')
        if check.as_of != context.business_time or not current(check.effective_window):
            _needs('current_original_independence_check')
        authority = read(check.authority_ref, Authorization)
        assignment = read(check.author_function_ref, RoleAssignment)
        evidence(authority.basis_refs + assignment.basis_refs)
        if (authority.organization_id != reading.organization_id or authority.actor_id != check.author_actor_id
                or authority.function_ref != check.author_function_ref or assignment.role != 'Engineer'
                or 'ENGINEER-A03' not in authority.action_ids or not current(authority.validity)
                or not any(scope_covers(s, terms.scope) for s in authority.scopes)
                or not {ref.key() for ref in check.evidence_refs} <= {ref.key() for ref in authority.readable_refs}):
            _needs('authorized_original_independence_check')
        requirement = read(requirement_ref, EngineerIndependenceRequirementView)
        if requirement.request_ref != request.ref or requirement.scope != terms.scope:
            raise ValueError('Independence template belongs to another request or scope')
        if not current(requirement.effective_window): _needs('current_original_independence_template')
        if requirement.template_code not in {'separate_organization_and_personnel_v1', 'separate_personnel_v1'}:
            _unsupported('engineer-appointment-independence-template')
        relations = read(requirement.relations_ref, EngineerOrganizationRelationsView)
        if relations.organization_id != reading.organization_id: raise ValueError('Relations belong to another organization')
        if relations.as_of != context.business_time or relations.coverage != 'complete':
            _needs('complete_current_engineer_relations')
        related = {reading.organization_id, *_known(relations.related_organization_ids, 'original_related_organizations')}
        checked_keys = allowed_keys
        if appointment.reservation_ref is not None:
            from src.actions.contracts.architect_appointment_objects import ArchitectReservationView
            reservation = read(appointment.reservation_ref, ArchitectReservationView)
            checked_keys = {row.resource_ref.key() for row in reservation.allocations}
        unique_identities(check.checked_resource_refs)
        if {ref.key() for ref in check.checked_resource_refs} != checked_keys:
            _needs('complete_original_independence_resource_set')
        checked_resources = [row for row in calendar.resources if row.resource_ref.key() in checked_keys]
        if {row.resource_ref.key() for row in checked_resources} != checked_keys:
            _needs('original_independence_resources_in_current_calendar')
        personnel = {person for row in checked_resources for person in _known(row.personnel_ids, 'original_resource_personnel')}
        expected, unknown = {}, False
        unique_identities(requirement.target_refs)
        for ref in requirement.target_refs:
            target = read(ref, EngineerAuthoredTargetView)
            if target.scope != terms.scope: raise ValueError('Independence target changes original scope')
            if target.author_organization_ids.state == 'known':
                shared = set(target.author_organization_ids.value) & related
                if requirement.template_code == 'separate_organization_and_personnel_v1' and shared:
                    expected[(ref.key(), 'organization')] = shared
            else: unknown = True
            if target.author_personnel_ids.state == 'known':
                shared = set(target.author_personnel_ids.value) & personnel
                if shared: expected[(ref.key(), 'personnel')] = shared
            else: unknown = True
        actual = {}
        unique_identities(check.conflict_refs)
        for ref in check.conflict_refs:
            conflict = read(ref, EngineerConflictView)
            if (conflict.organization_id != reading.organization_id or conflict.appointment_ref != appointment.ref
                    or conflict.requirement_ref != requirement.ref or conflict.scope != terms.scope
                    or not current(conflict.effective_window)):
                raise ValueError('Conflict record changes original appointment, requirement or scope')
            key = (conflict.target_ref.key(), conflict.kind)
            if key in actual or len(set(conflict.conflicting_ids)) != len(conflict.conflicting_ids):
                raise ValueError('Conflict identity or actor repeated')
            actual[key] = set(conflict.conflicting_ids)
        if actual != expected:
            _needs('exact_sourced_independence_conflict_records')
        if expected:
            return completed('disclose_conflict', 'Original organization or personnel relationships conflict with this independence template',
                conflict_refs=check.conflict_refs, questions=questions())
        if unknown: _needs('complete_original_independence_authors')
        return allowed_keys

    return confirm_appointment(context, action_input, reading, role='Engineer',
        appointment_schema=EngineerAppointmentView, acceptance_schema=EngineerAcceptanceView,
        reservation_field='reservation_ref', check_professional=professional)
