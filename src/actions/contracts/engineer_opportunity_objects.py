"""Original opportunity, preparation estimates and internal delegation."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.professional_outreach import ProfessionalOutreachLimits,ProfessionalOutreachObservation
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.engineer_objects import EngineerResourceCalendarView, EngineerWorkProfileView
from src.actions.contracts.service_objects import (
    SourcedServiceProjection, ServiceUse,
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView,
    ServiceScopeProjectView, ServiceWorkScopeView,
)


class EngineerOpportunitySource(SourcedServiceProjection):
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow


class EngineerOpportunityQuestion(StrictRecord):
    scope: ScopeRef
    target_refs: list[ref_type('EvidenceTarget')]
    question: TextId
    recipient_ids: list[TextId]
    evidence_refs: list[ref_type('Evidence')]
    blocking_uses: list[ServiceUse]
    response_requirement_ref: ref_type('ResponseRequirement')


class EngineerOpportunityView(EngineerOpportunitySource):
    ref: ref_type('Opportunity')
    recipient_organization_ids: list[TextId]
    recipient_actor_ids: list[TextId]
    permission: ValueState[bool]
    source_verified: ValueState[bool]
    capability_refs: list[ref_type('Capability')]
    status: Literal['open', 'closed', 'withdrawn']
    region_id: ValueState[TextId]
    service_code: ValueState[TextId]
    object_type: ValueState[TextId]
    discipline_ref: ValueState[ref_type('Discipline')]
    function_code: ValueState[TextId]
    trigger_ref: ref_type('Trigger') | None
    inviting_actor_id: TextId | None
    interest_permission: ValueState[bool]
    clarification_recipient_ids: list[TextId]
    questions: list[EngineerOpportunityQuestion]


class EngineerOpportunityCapabilityView(EngineerOpportunitySource):
    outreach_limits: ProfessionalOutreachLimits | None = None
    ref: ref_type('Capability')
    organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    opportunity_ref: ref_type('Opportunity')
    capacity_ref: ref_type('ResourceCalendar')
    discipline_codes: ValueState[list[TextId]]
    function_codes: ValueState[list[TextId]]
    choice_order: Annotated[list[Literal['decline', 'track', 'express_interest', 'prepare', 'clarify']], Field(min_length=1)]
    preparation_ref: ref_type('PreparationRequestProfile') | None
    decline_reason: TextId

    @model_validator(mode='after')
    def unique_choices(self):
        if len(set(self.choice_order)) != len(self.choice_order):
            raise ValueError('Opportunity capability repeats a choice')
        return self


class EngineerOpportunityTriggerView(EngineerOpportunitySource):
    ref: ref_type('Trigger')
    opportunity_ref: ref_type('Opportunity')
    organization_id: TextId
    status: Literal['active', 'closed']


class EngineerPreparationRequestView(EngineerOpportunitySource):
    ref: ref_type('PreparationRequestProfile')
    opportunity_ref: ref_type('Opportunity')
    capability_ref: ref_type('Capability')
    purpose: Literal['preparation', 'investigation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    questions: list[EngineerOpportunityQuestion]
    estimated_cost: ValueState[Money]
    estimate_result_ref: ref_type('MethodResult') | None


class EngineerPreparationAuthorityView(EngineerOpportunitySource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    opportunity_ref: ref_type('Opportunity')
    request_profile_ref: ref_type('PreparationRequestProfile')
    permitted: ValueState[bool]
    allowed_purposes: list[Literal['preparation', 'investigation']]
    allowed_input_refs: list[Reference]
    allowed_recipient_ids: list[TextId]
    remaining_budget: ValueState[Money]
    remaining_effort: ValueState[Measured]
    as_of: TimePoint


class EngineerPreparationEstimateView(EngineerOpportunitySource):
    ref: ref_type('MethodResult')
    opportunity_ref: ref_type('Opportunity')
    request_profile_ref: ref_type('PreparationRequestProfile')
    work_profile_ref: ref_type('WorkProfile') | None
    discipline_ref: ref_type('Discipline')
    function_code: TextId
    method_ref: ref_type('Method')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    input_refs: list[Reference]
    execution_status: Literal['succeeded', 'failed', 'unsupported']
    executed_at: TimePoint
    estimated_cost: ValueState[Money]
    effort_estimate: ValueState[Measured]


class EngineerPreparationMethodView(EngineerOpportunitySource):
    ref: ref_type('Method')
    purpose: Literal['preparation_estimate']
    supported_region_ids: list[TextId]
    supported_service_codes: list[TextId]
    supported_object_types: list[TextId]
    supported_discipline_codes: list[TextId]
    supported_function_codes: list[TextId]


class EngineerOpportunityDisciplineView(EngineerOpportunitySource):
    ref: ref_type('Discipline')
    code: TextId


class EngineerOpportunityReferenceView(EngineerOpportunitySource):
    ref: Reference
    opportunity_ref: ref_type('Opportunity')


def engineer_opportunity_schemas():
    registry = common_projection_schemas()
    registry.register_kind('OutreachObservation',ProfessionalOutreachObservation,str)
    for kind, schema in {
        'Opportunity': EngineerOpportunityView, 'Capability': EngineerOpportunityCapabilityView,
        'Trigger': EngineerOpportunityTriggerView, 'PreparationRequestProfile': EngineerPreparationRequestView,
        'Authority': EngineerPreparationAuthorityView, 'MethodResult': EngineerPreparationEstimateView,
        'Method': EngineerPreparationMethodView, 'ResourceCalendar': EngineerResourceCalendarView,
        'WorkProfile': EngineerWorkProfileView, 'Discipline': EngineerOpportunityDisciplineView,
        'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    for kind in ('DeliverableRequirement', 'EvidenceTarget', 'ResponseRequirement', 'Dependency'):
        registry.register_kind(kind, EngineerOpportunityReferenceView, str)
    return registry
