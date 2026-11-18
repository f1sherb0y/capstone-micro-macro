"""Read-only Engineer intake facts; qualifications and relations need evidence."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_objects import ResourceCapacity
from src.actions.contracts.service_objects import (
    SourcedServiceProjection, ServiceRequestView, ServiceTermsView,
    ServiceIntakeCapabilityView, ServiceQualificationView, ServiceResourceCalendarView,
    ServiceMethodView, ServiceWorkProfileView, service_intake_schemas,
)


class EngineerServiceRequestView(ServiceRequestView):
    fee_basis_ref: ref_type("FeeBasis")


class EngineerServiceTermsView(ServiceTermsView):
    discipline_codes: ValueState[Annotated[list[TextId], Field(min_length=1)]]
    function_code: ValueState[TextId]
    independence_requirement_ref: ref_type("IndependenceRequirement") | None


class EngineerIntakeCapabilityView(ServiceIntakeCapabilityView):
    discipline_codes: ValueState[list[TextId]]
    function_codes: ValueState[list[TextId]]


class EngineerQualificationView(ServiceQualificationView):
    discipline_codes: list[TextId]
    function_codes: list[TextId]


class EngineerResourceCapacity(ResourceCapacity):
    discipline_codes: ValueState[list[TextId]]
    suitable: ValueState[bool]
    personnel_ids: ValueState[Annotated[list[TextId], Field(min_length=1)]]


class EngineerResourceCalendarView(ServiceResourceCalendarView):
    resources: list[EngineerResourceCapacity]

    @model_validator(mode="after")
    def personnel_counted_once(self):
        seen = set()
        for resource in self.resources:
            if resource.personnel_ids.state == "known":
                people = resource.personnel_ids.value
                if len(set(people)) != len(people) or seen.intersection(people):
                    raise ValueError("Personnel counted more than once in the resource calendar")
                seen.update(people)
        return self


class EngineerServiceMethodView(ServiceMethodView):
    discipline_codes: list[TextId]


class EngineerWorkProfileView(ServiceWorkProfileView):
    discipline_codes: list[TextId]


class EngineerIndependenceRequirementView(SourcedServiceProjection):
    ref: ref_type("IndependenceRequirement")
    request_ref: ref_type("ServiceRequest")
    scope: ScopeRef
    target_refs: Annotated[
        list[ref_type("Deliverable") | ref_type("DesignOption") | ref_type("Brief")],
        Field(min_length=1),
    ]
    template_code: TextId
    relations_ref: ref_type("OrganizationRelations")
    effective_window: TimeWindow


class EngineerOrganizationRelationsView(SourcedServiceProjection):
    ref: ref_type("OrganizationRelations")
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    related_organization_ids: ValueState[list[TextId]]


class EngineerAuthoredTargetView(SourcedServiceProjection):
    ref: ref_type("Deliverable") | ref_type("DesignOption") | ref_type("Brief")
    scope: ScopeRef
    author_organization_ids: ValueState[Annotated[list[TextId], Field(min_length=1)]]
    author_personnel_ids: ValueState[Annotated[list[TextId], Field(min_length=1)]]


def engineer_intake_schemas():
    return service_intake_schemas({
        "ServiceRequest": EngineerServiceRequestView,
        "ServiceTerms": EngineerServiceTermsView,
        "Capability": EngineerIntakeCapabilityView,
        "Qualification": EngineerQualificationView,
        "ResourceCalendar": EngineerResourceCalendarView,
        "Method": EngineerServiceMethodView,
        "WorkProfile": EngineerWorkProfileView,
        "IndependenceRequirement": EngineerIndependenceRequirementView,
        "OrganizationRelations": EngineerOrganizationRelationsView,
        "Deliverable": EngineerAuthoredTargetView,
        "DesignOption": EngineerAuthoredTargetView,
        "Brief": EngineerAuthoredTargetView,
    })
