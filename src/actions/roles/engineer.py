"""Engineer A02 professional scope, personnel and template-based independence."""
from src.actions.contracts.engineer_objects import (
    EngineerAuthoredTargetView, EngineerIndependenceRequirementView,
    EngineerOrganizationRelationsView, EngineerQualificationView,
    EngineerServiceRequestView, EngineerServiceTermsView, EngineerIntakeCapabilityView,
    EngineerResourceCalendarView, EngineerServiceMethodView, EngineerWorkProfileView,
)
from src.actions.roles.service_intake import (
    ServiceIntakeGap, _needs, _unsupported, assess_professional_service,
)


def assess_service_request(context, action_input, reading):
    try:
        request = reading.resolve(action_input.request_ref)
        if not isinstance(request, EngineerServiceRequestView):
            _unsupported("engineer-service-projection:ServiceRequest")

        def check_method(method, terms, known):
            if not isinstance(method, EngineerServiceMethodView):
                _unsupported("engineer-method-discipline-projection")
            if not set(known(terms.discipline_codes, "service_disciplines")) <= set(method.discipline_codes):
                _unsupported("engineer-method-discipline-domain")

        def check_terms(terms, request, capability, calendar, read, current, clock, known):
            if (not isinstance(terms, EngineerServiceTermsView)
                    or not isinstance(capability, EngineerIntakeCapabilityView)
                    or not isinstance(calendar, EngineerResourceCalendarView)):
                _unsupported("engineer-professional-scope-projections")
            disciplines = set(known(terms.discipline_codes, "service_disciplines"))
            function = known(terms.function_code, "service_function")
            if function not in {"design", "independent_review", "technical_support", "contract_engineer"}:
                _unsupported("engineer-professional-function-domain")
            if (not disciplines <= set(known(capability.discipline_codes, "capability_disciplines"))
                    or function not in known(capability.function_codes, "capability_functions")):
                return "The requested discipline or professional function exceeds declared capability"
            region = known(terms.region_id, "service_region")
            service = known(terms.service_code, "service_code")
            qualifications = [read(ref, EngineerQualificationView) for ref in capability.qualification_refs]
            if capability.qualification_coverage != "complete":
                _needs("complete_engineer_qualification_coverage", [capability.ref])
            for item in qualifications:
                if item.organization_id != reading.organization_id:
                    raise ValueError("Qualification belongs to another professional organization")
                clock(item.effective_window.start)
            for code in known(terms.required_qualification_codes, "required_qualifications"):
                matches = [item for item in qualifications if item.code == code
                    and item.effective_window.contains(context.business_time)
                    and region in item.region_ids and service in item.service_codes
                    and disciplines <= set(item.discipline_codes) and function in item.function_codes]
                gaps, covered = [], False
                for item in matches:
                    try:
                        covered |= known(item.standing, "qualification_standing")
                    except ServiceIntakeGap as gap:
                        gaps.append(gap)
                if not covered:
                    if gaps:
                        raise gaps[0]
                    return "No current qualification covers the requested discipline and function"
            for ref in known(terms.required_method_refs, "required_service_methods"):
                check_method(read(ref, EngineerServiceMethodView), terms, known)
            if terms.work_profile_ref is not None:
                profile = read(terms.work_profile_ref, EngineerWorkProfileView)
                if not disciplines <= set(profile.discipline_codes):
                    _unsupported("engineer-work-profile-discipline-domain")
            required = terms.independence_requirement_ref
            if required != action_input.independence_requirement_ref:
                if action_input.independence_requirement_ref is None:
                    _needs("service_independence_requirement", [required] if required else [])
                raise ValueError("Independence requirement differs from the offered terms version")
            if required is None:
                if function == "independent_review":
                    _needs("independent_review_template", [terms.ref])
                return None
            requirement = read(required, EngineerIndependenceRequirementView)
            if requirement.request_ref != request.ref or requirement.scope != terms.scope:
                raise ValueError("Independence requirement differs from the exact request or scope")
            current(requirement.effective_window, "current_independence_requirement")
            if requirement.template_code not in {
                    "separate_organization_and_personnel_v1", "separate_personnel_v1"}:
                _unsupported("engineer-independence-template")
            relations = read(requirement.relations_ref, EngineerOrganizationRelationsView)
            if relations.organization_id != reading.organization_id:
                raise ValueError("Independence relations belong to another organization")
            clock(relations.as_of)
            if relations.as_of != context.business_time or relations.coverage != "complete":
                _needs("complete_current_organization_relations", [relations.ref])
            related = set(known(relations.related_organization_ids, "related_organizations"))
            related.add(reading.organization_id)
            for ref in requirement.target_refs:
                target = read(ref, EngineerAuthoredTargetView)
                if target.scope != terms.scope:
                    raise ValueError("Independence target differs from the exact service scope")
                authors = set(known(target.author_organization_ids, "target_author_organizations"))
                known(target.author_personnel_ids, "target_author_personnel")
                if requirement.template_code == "separate_organization_and_personnel_v1" and authors & related:
                    return "The provider has an author organization relationship prohibited by the independence template"
            return None

        def resource_allowed(resource, terms, read, known):
            if not set(known(terms.discipline_codes, "service_disciplines")) <= set(
                    known(resource.discipline_codes, "resource_disciplines")):
                return False
            if not known(resource.suitable, "resource_suitability"):
                return False
            people = set(known(resource.personnel_ids, "resource_personnel"))
            if terms.independence_requirement_ref is not None:
                requirement = read(terms.independence_requirement_ref, EngineerIndependenceRequirementView)
                for ref in requirement.target_refs:
                    target = read(ref, EngineerAuthoredTargetView)
                    if people & set(known(target.author_personnel_ids, "target_author_personnel")):
                        return False
            return True

        return assess_professional_service(
            context, action_input, reading, role_key="engineer",
            price_basis_ref=request.fee_basis_ref, accepted_field="terms_ref",
            check_terms=check_terms, check_fee_method=check_method, resource_allowed=resource_allowed,
        )
    except ServiceIntakeGap as gap:
        return gap.result
