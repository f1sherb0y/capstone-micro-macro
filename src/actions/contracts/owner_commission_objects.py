"""Closed host projections for OWN-A04 professional procurement.

These records describe received facts and proposed arrangements. Validation
does not appoint a consultant, accept for another party or reserve resources.
"""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow,
    ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_objects import SourcedOwnerProjection
from src.actions.contracts.owner_study_objects import StudyResourceLoad, unique_refs
from src.organization.models import Role


ProfessionalRole = Role
CommissionChoice = Literal['invite', 'clarify', 'accept', 'reject_all', 'retender', 'internal']


def unique_codes(values):
    if len(set(values)) != len(values):
        raise ValueError('Professional procurement repeats a declared code')


class CommissionOrganizationView(SourcedOwnerProjection):
    ref: ref_type('Organization')
    organization_id: TextId


class CommissionCaseView(SourcedOwnerProjection):
    ref: ref_type('OwnerCase')
    organization_id: TextId
    available_at: TimePoint
    status: Literal['active', 'closed']


class CommissionProjectView(SourcedOwnerProjection):
    ref: ref_type('Project')
    owner_organization_id: TextId
    available_at: TimePoint
    status: Literal['active', 'suspended', 'closed']


class CommissionWorkView(SourcedOwnerProjection):
    ref: ref_type('WorkScope')
    scope_ref: ScopeRef
    service_codes: Annotated[list[TextId], Field(min_length=1)]
    requested_uses: Annotated[list[TextId], Field(min_length=1)]
    responsibility_codes: Annotated[list[TextId], Field(min_length=1)]
    deliverable_refs: Annotated[list[ref_type('DeliverableRequirement')], Field(min_length=1)]
    effective_window: TimeWindow

    @model_validator(mode='after')
    def one_work_record(self):
        if self.ref not in self.scope_ref.coverage_refs:
            raise ValueError('Service work is outside its own declared scope')
        for values in (self.service_codes, self.requested_uses, self.responsibility_codes):
            unique_codes(values)
        unique_refs(self.deliverable_refs)
        return self


class CommissionDeliverableView(SourcedOwnerProjection):
    ref: ref_type('DeliverableRequirement')
    service_scope_ref: ref_type('ServiceScope')
    work_ref: ref_type('WorkScope')
    requested_use: TextId
    description: TextId


class CommissionServiceScopeView(SourcedOwnerProjection):
    ref: ref_type('ServiceScope')
    employer_organization_id: TextId
    scope_ref: ScopeRef
    region_id: TextId
    permitted_roles: Annotated[list[ProfessionalRole], Field(min_length=1)]
    service_codes: Annotated[list[TextId], Field(min_length=1)]
    requested_uses: Annotated[list[TextId], Field(min_length=1)]
    responsibility_codes: Annotated[list[TextId], Field(min_length=1)]
    required_qualification_codes: list[TextId]
    required_method_refs: list[ref_type('Method')]
    deliverable_refs: Annotated[list[ref_type('DeliverableRequirement')], Field(min_length=1)]
    window_ref: ref_type('TimeWindow')
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def bounded_service(self):
        if not self.scope_ref.coverage_refs:
            raise ValueError('Professional service requires explicitly bounded work')
        unique_refs(self.scope_ref.coverage_refs)
        unique_refs(self.deliverable_refs)
        unique_refs(self.required_method_refs)
        for values in (self.permitted_roles, self.service_codes, self.requested_uses,
                       self.responsibility_codes, self.required_qualification_codes):
            unique_codes(values)
        return self


class CommissionProviderView(SourcedOwnerProjection):
    ref: ref_type('EligibleProvider')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    capability_ref: ref_type('Capability')
    invitation_permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow
    status: Literal['active', 'withdrawn']


class CommissionCapabilityView(SourcedOwnerProjection):
    ref: ref_type('Capability')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    region_ids: ValueState[list[TextId]]
    service_codes: ValueState[list[TextId]]
    allowed_uses: ValueState[list[TextId]]
    responsibility_codes: ValueState[list[TextId]]
    qualification_refs: list[ref_type('Qualification')]
    qualification_coverage: Literal['complete', 'partial', 'unknown']
    method_refs: ValueState[list[ref_type('Method')]]
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_qualifications(self):
        unique_refs(self.qualification_refs)
        if self.method_refs.state == 'known':
            unique_refs(self.method_refs.value)
        return self


class CommissionQualificationView(SourcedOwnerProjection):
    ref: ref_type('Qualification')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    code: TextId
    region_ids: Annotated[list[TextId], Field(min_length=1)]
    service_codes: Annotated[list[TextId], Field(min_length=1)]
    standing: ValueState[bool]
    verified_at: TimePoint
    effective_window: TimeWindow


class CommissionMethodView(SourcedOwnerProjection):
    ref: ref_type('Method')
    purpose: Literal['service_support']
    region_ids: list[TextId]
    service_codes: list[TextId]
    permitted_roles: list[ProfessionalRole]
    allowed_uses: list[TextId]
    available_at: TimePoint
    effective_window: TimeWindow


class CommissionTermsView(SourcedOwnerProjection):
    ref: ref_type('ContractTerms')
    service_scope_ref: ref_type('ServiceScope')
    scope_ref: ScopeRef
    employer_organization_id: TextId
    provider_organization_id: TextId
    payer_organization_id: TextId
    payer_actor_id: TextId
    payer_function_ref: ref_type('FunctionAssignment')
    payer_authority_ref: ref_type('Authorization')
    payer_authority_action_id: TextId
    fee: ValueState[Money]
    service_codes: ValueState[list[TextId]]
    requested_uses: ValueState[list[TextId]]
    responsibility_codes: ValueState[list[TextId]]
    deliverable_refs: list[ref_type('DeliverableRequirement')]
    window_ref: ref_type('TimeWindow')
    condition_refs: list[ref_type('Requirement')]
    authority_limits: ValueState[list[TextId]]
    status: Literal['offered', 'withdrawn']
    issued_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def strict_terms(self):
        if self.fee.state == 'known' and Decimal(self.fee.value.value) < 0:
            raise ValueError('Professional service fee cannot be negative')
        for refs in (self.deliverable_refs, self.condition_refs):
            unique_refs(refs)
        for state in (self.service_codes, self.requested_uses, self.responsibility_codes, self.authority_limits):
            if state.state == 'known':
                unique_codes(state.value)
        return self


class CommissionOfferView(SourcedOwnerProjection):
    ref: ref_type('ServiceOffer')
    provider_ref: ref_type('EligibleProvider')
    service_scope_ref: ref_type('ServiceScope')
    terms_ref: ref_type('ContractTerms')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    authority_action_id: TextId
    priority: ValueState[int]
    received_at: TimePoint
    effective_window: TimeWindow
    status: Literal['offered', 'withdrawn']


class CommissionConditionView(SourcedOwnerProjection):
    ref: ref_type('Requirement')
    service_scope_ref: ref_type('ServiceScope')
    terms_ref: ref_type('ContractTerms') | None
    scope_ref: ScopeRef
    permitted: ValueState[bool]
    verified_at: TimePoint
    effective_window: TimeWindow


class CommissionIssueView(SourcedOwnerProjection):
    ref: ref_type('Issue')
    service_scope_ref: ref_type('ServiceScope')
    scope_ref: ScopeRef
    provider_refs: Annotated[list[ref_type('EligibleProvider')], Field(min_length=1)]
    offer_refs: list[ref_type('ServiceOffer')]
    question: TextId
    status: Literal['unresolved', 'resolved']
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_recipients(self):
        unique_refs(self.provider_refs)
        unique_refs(self.offer_refs)
        return self


class CommissionProposedTask(StrictRecord):
    kind: Literal['proposed']
    local_key: TextId
    scope_ref: ScopeRef


class CommissionExistingTask(StrictRecord):
    kind: Literal['existing']
    task_ref: ref_type('Task')


class CommissionTaskView(SourcedOwnerProjection):
    ref: ref_type('Task')
    organization_id: TextId
    service_scope_ref: ref_type('ServiceScope')
    scope_ref: ScopeRef
    status: Literal['active', 'completed', 'cancelled']
    available_at: TimePoint
    effective_window: TimeWindow


class CommissionAllocation(StrictRecord):
    resource_ref: ref_type('ResourcePool')
    window_ref: ref_type('TimeWindow')
    quantity: Measured
    task_target: Annotated[CommissionProposedTask | CommissionExistingTask, Field(discriminator='kind')]

    @model_validator(mode='after')
    def positive_quantity(self):
        if Decimal(self.quantity.value) <= 0:
            raise ValueError('A proposed service allocation must be positive')
        return self


class CommissionResourceView(SourcedOwnerProjection):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    service_authority_ref: ref_type('Authorization') | None
    service_actor_id: TextId | None
    service_authority_action_id: TextId | None
    capability_ref: ref_type('Capability') | None
    purpose_codes: Annotated[list[Literal['management', 'internal_service']], Field(min_length=1)]
    region_id: TextId
    total: ValueState[Measured]
    commitments: list[StudyResourceLoad]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    effective_window: TimeWindow

    @model_validator(mode='after')
    def unique_loads(self):
        unique_refs([row.ref for row in self.commitments])
        unique_codes(self.purpose_codes)
        if self.total.state == 'known' and Decimal(self.total.value.value) < 0:
            raise ValueError('Service resource total cannot be negative')
        if 'internal_service' in self.purpose_codes and self.capability_ref is None:
            raise ValueError('Internal service resource needs a professional capability')
        if 'internal_service' in self.purpose_codes and any(value is None for value in (
                self.service_authority_ref, self.service_actor_id, self.service_authority_action_id)):
            raise ValueError('Internal service resource needs a distinct service authority')
        return self


class CommissionManagementView(SourcedOwnerProjection):
    ref: ref_type('ManagementCapacity')
    organization_id: TextId
    resource_refs: list[ref_type('ResourcePool')]
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']

    @model_validator(mode='after')
    def one_physical_pool(self):
        unique_refs(self.resource_refs)
        return self


class CommissionInternalPlanView(SourcedOwnerProjection):
    ref: ref_type('InternalServicePlan')
    organization_id: TextId
    service_scope_ref: ref_type('ServiceScope')
    allocations: Annotated[list[CommissionAllocation], Field(min_length=1)]
    available_at: TimePoint
    effective_window: TimeWindow


class CommissionProfileView(SourcedOwnerProjection):
    ref: ref_type('ProcurementProfile')
    organization_id: TextId
    scope_ref: ScopeRef
    service_scope_ref: ref_type('ServiceScope')
    policy: ValueState[CommissionChoice | Literal['evaluate', 'defer']]
    on_unavailable: ValueState[Literal['reject_all', 'retender', 'defer']]
    permitted_roles: Annotated[list[ProfessionalRole], Field(min_length=1)]
    fee_cap: ValueState[Money]
    invitation_provider_refs: list[ref_type('EligibleProvider')]
    clarification_issue_refs: list[ref_type('Issue')]
    management_allocations: list[CommissionAllocation]
    internal_plan_ref: ref_type('InternalServicePlan') | None
    required_condition_refs: list[ref_type('Requirement')]
    permitted_authority_codes: ValueState[list[TextId]]
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode='after')
    def explicit_policy(self):
        unique_codes(self.permitted_roles)
        for refs in (self.invitation_provider_refs, self.clarification_issue_refs, self.required_condition_refs):
            unique_refs(refs)
        if self.fee_cap.state == 'known' and Decimal(self.fee_cap.value.value) < 0:
            raise ValueError('Professional procurement fee cap cannot be negative')
        return self


def owner_commission_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ('Organization', CommissionOrganizationView), ('OwnerCase', CommissionCaseView),
        ('Project', CommissionProjectView), ('WorkScope', CommissionWorkView),
        ('ServiceScope', CommissionServiceScopeView), ('DeliverableRequirement', CommissionDeliverableView),
        ('EligibleProvider', CommissionProviderView), ('Capability', CommissionCapabilityView),
        ('Method', CommissionMethodView),
        ('Qualification', CommissionQualificationView), ('ContractTerms', CommissionTermsView),
        ('ServiceOffer', CommissionOfferView), ('Requirement', CommissionConditionView),
        ('Issue', CommissionIssueView), ('ResourcePool', CommissionResourceView),
        ('ManagementCapacity', CommissionManagementView), ('InternalServicePlan', CommissionInternalPlanView),
        ('ProcurementProfile', CommissionProfileView), ('Task', CommissionTaskView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
