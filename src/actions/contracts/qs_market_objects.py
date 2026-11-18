"""Authorized opportunity and original price-source metadata for QS-A01."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.professional_outreach import ProfessionalOutreachLimits,ProfessionalOutreachObservation
from src.actions.contracts.qs_monthly_cost_market import MonthlyCostPolicy,MonthlyCostObservation
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.qs_research_objects import QSResearchQuestion
from src.actions.contracts.service_objects import (
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView,
    ServiceScopeProjectView, ServiceWorkScopeView,
)


class QSMarketStrategyView(CostSource):
    outreach_limits: ProfessionalOutreachLimits | None = None
    monthly_cost_policy_ref: ref_type('MonthlyCostPolicy') | None = None
    monthly_cost_observation_ref: ref_type('MonthlyCostObservation') | None = None
    ref: ref_type('Strategy')
    organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    choice_order: Annotated[list[Literal['track', 'express_interest', 'prepare', 'register_source', 'ignore']], Field(min_length=1)]
    opportunity_order: list[ref_type('Opportunity')]
    source_order: list[ref_type('PriceSource')]
    preparation_ref: ref_type('ResearchRequestProfile') | None
    ignore_reason: TextId

    @model_validator(mode='after')
    def unique_candidates(self):
        unique_refs(self.opportunity_order); unique_refs(self.source_order)
        if len(set(self.choice_order)) != len(self.choice_order):
            raise ValueError('Market strategy repeats a choice')
        return self


class QSMarketOpportunityView(CostSource):
    ref: ref_type('Opportunity')
    recipient_ids: list[TextId]
    permission: ValueState[bool]
    strategy_refs: list[ref_type('Strategy')]
    status: Literal['open', 'closed', 'withdrawn']
    trigger_ref: ref_type('Trigger') | None
    inviting_actor_id: TextId | None
    interest_permission: ValueState[bool]


class QSMarketTriggerView(CostSource):
    ref: ref_type('Trigger')
    opportunity_ref: ref_type('Opportunity')
    recipient_ids: list[TextId]
    status: Literal['active', 'closed']


class QSMarketPriceSourceView(CostSource):
    ref: ref_type('PriceSource')
    recipient_ids: list[TextId]
    permission: ValueState[bool]
    confidentiality: Literal['public', 'authorized_private', 'competitor_secret', 'unauthorized']
    source_kind: Literal['quote', 'index', 'market_commentary']
    observation_ref: ref_type('Evidence') | None
    applicability: ValueState['QSMarketApplicability']
    limitations: list[TextId]


class QSMarketApplicability(CostSource):
    ref: ref_type('PriceApplicability')
    price_source_ref: ref_type('PriceSource')
    price_time: TimePoint
    region_ref: ref_type('Region')
    delivery_scope_ref: ref_type('DeliveryScope')
    measurement_rule_ref: ref_type('MeasurementRule')
    included_scope_refs: Annotated[list[ref_type('CostScope')], Field(min_length=1)]
    excluded_scope_refs: list[ref_type('CostScope')]

    @model_validator(mode='after')
    def original_coverage(self):
        unique_refs([*self.included_scope_refs, *self.excluded_scope_refs])
        return self


class QSMarketRequestView(CostSource):
    ref: ref_type('ResearchRequestProfile')
    strategy_ref: ref_type('Strategy')
    purpose: Literal['preparation', 'investigation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    questions: list[QSResearchQuestion]
    estimated_cost: ValueState[Money]


class QSMarketResearchAuthorityView(CostSource):
    ref: ref_type('Authority')
    organization_id: TextId
    delegate_actor_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    strategy_ref: ref_type('Strategy')
    request_profile_ref: ref_type('ResearchRequestProfile')
    permission: ValueState[bool]
    allowed_purposes: list[Literal['preparation', 'investigation']]
    allowed_input_refs: list[Reference]
    question_recipient_ids: list[TextId]
    remaining_budget: ValueState[Money]
    remaining_effort: ValueState[Measured]
    as_of: TimePoint


QSMarketPriceSourceView.model_rebuild()


class QSMarketReferenceView(CostSource):
    ref: Reference


def qs_market_schemas():
    registry = common_projection_schemas()
    registry.register_kind('OutreachObservation',ProfessionalOutreachObservation,str)
    registry.register_kind('MonthlyCostPolicy',MonthlyCostPolicy,str)
    registry.register_kind('MonthlyCostObservation',MonthlyCostObservation,str)
    for kind, schema in {
        'Strategy': QSMarketStrategyView, 'Opportunity': QSMarketOpportunityView,
        'Trigger': QSMarketTriggerView, 'PriceSource': QSMarketPriceSourceView,
        'PriceApplicability': QSMarketApplicability, 'ResearchRequestProfile': QSMarketRequestView,
        'Authority': QSMarketResearchAuthorityView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    for kind in ('Region', 'DeliveryScope', 'MeasurementRule', 'CostScope', 'DeliverableRequirement',
                 'WorkProfile', 'Dependency', 'EvidenceTarget', 'ResponseRequirement'):
        registry.register_kind(kind, QSMarketReferenceView, str)
    return registry
