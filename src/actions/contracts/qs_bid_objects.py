"""Original same-round bids, cost adjustments, checks and exclusion authority."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDocumentView, QSProcurementGapView, QSProcurementResponseView, QSProcurementRoundView,
)
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView


class QSBidRoundView(QSProcurementRoundView):
    document_ref: ref_type('ProcurementDocument')
    bid_refs: list[ref_type('Bid')]
    clarification_refs: list[ref_type('Clarification')]


class QSBidView(CostSource):
    ref: ref_type('Bid')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    bidder_id: TextId
    bidder_organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    submission_action_id: Literal['CONTRACTOR-A02', 'CONTRACTOR-A03', 'SUPPLIER-A03']
    status: Literal['submitted', 'withdrawn']
    submitted_at: TimePoint
    price: ValueState[Money]
    region_id: TextId
    price_time: TimePoint
    included_scope_keys: list[TextId]
    eligibility_ref: ref_type('EligibilityAssessment') | None
    normalization_basis_ref: ref_type('NormalizationBasis') | None


class QSBidEligibilityView(CostSource):
    ref: ref_type('EligibilityAssessment')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    bid_ref: ref_type('Bid')
    rule_refs: list[ref_type('EvaluationRule')]
    status: Literal['ok', 'failed', 'unsupported']
    qualified: ValueState[bool]
    compliant: ValueState[bool]
    risk: ValueState[Measured]
    checked_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class QSBidClarificationView(CostSource):
    ref: ref_type('Clarification')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    bid_ref: ref_type('Bid')
    question_ref: ref_type('EvidenceTarget')
    response_author_id: TextId
    response_authority_ref: ref_type('Authorization')
    response_function_ref: ref_type('FunctionAssignment')
    response_action_id: Literal['CONTRACTOR-A03', 'SUPPLIER-A03']
    assessment_ref: ref_type('EligibilityAssessment') | None
    normalization_basis_ref: ref_type('NormalizationBasis') | None
    # Clarifications explain the saved bid; repricing requires a new Bid version.
    confirms_original_price: bool


class QSBidGapView(QSProcurementGapView):
    issue: Literal['eligibility', 'pricing', 'clarification']
    document_ref: ref_type('ProcurementDocument')
    bid_ref: ref_type('Bid') | None


class QSCostAdjustment(StrictRecord):
    difference_key: TextId
    amount: Money


class QSBidNormalizationBasisView(CostSource):
    ref: ref_type('NormalizationBasis')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    bid_ref: ref_type('Bid')
    original_price: Money
    target_currency: TextId
    target_region_id: TextId
    target_price_time: TimePoint
    target_scope_keys: list[TextId]
    fx_rate: ValueState[DecimalString]
    fx_basis_ref: ref_type('Evidence')
    adjustments: list[QSCostAdjustment]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A06']


class QSBidCriterion(StrictRecord):
    metric: Literal['price', 'risk']
    weight: DecimalString
    scale: DecimalString
    unit: TextId
    basis_ref: ref_type('Evidence')


class QSBidEvaluationProfileView(CostSource):
    ref: ref_type('EvaluationProfile')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    currency: TextId
    region_id: TextId
    price_time: TimePoint
    required_scope_keys: list[TextId]
    rule_refs: Annotated[list[ref_type('EvaluationRule')], Field(min_length=1)]
    question_refs: list[ref_type('EvidenceTarget')]
    on_unknown: Literal['clarify', 'report']
    normalization_result_ref: ref_type('MethodResult') | None
    ranking_result_ref: ref_type('MethodResult') | None
    criteria: list[QSBidCriterion]
    exclusion_bid_ref: ref_type('Bid') | None
    exclusion_rule_ref: ref_type('EvaluationRule') | None
    exclusion_authority_ref: ref_type('Authority') | None

    @model_validator(mode='after')
    def original_rule_set(self):
        unique_refs(self.rule_refs); unique_refs(self.question_refs)
        if len({r.metric for r in self.criteria}) != len(self.criteria): raise ValueError('Bid comparison criterion repeated')
        return self


class QSBidEvaluationRuleView(CostSource):
    ref: ref_type('EvaluationRule')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    predicate: Literal['qualification', 'compliance', 'withdrawal']
    consequence: Literal['recommend_exclusion', 'clarify']


class QSBidSavedValue(StrictRecord):
    bid_ref: ref_type('Bid')
    normalized_price: Money


class QSBidMethodResultView(CostSource):
    ref: ref_type('MethodResult')
    kind: Literal['normalization', 'ranking']
    method_ref: ref_type('Method')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    profile_ref: ref_type('EvaluationProfile')
    bid_refs: list[ref_type('Bid')]
    basis_refs: list[ref_type('NormalizationBasis')]
    status: Literal['ok', 'failed', 'unsupported']
    prices: list[QSBidSavedValue]
    ranked_groups: list[list[ref_type('Bid')]]
    calculated_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A06']

    @model_validator(mode='after')
    def original_method_inputs(self):
        unique_refs(self.bid_refs); unique_refs(self.basis_refs)
        unique_refs([r.bid_ref for r in self.prices]); unique_refs([r for group in self.ranked_groups for r in group])
        if self.status != 'ok' and (self.prices or self.ranked_groups): raise ValueError('Failed bid calculation cannot supply successful results')
        if self.kind == 'normalization' and self.ranked_groups: raise ValueError('Normalization does not grant a ranking')
        if self.kind == 'ranking' and self.prices: raise ValueError('Ranking must reuse the original normalization result')
        return self


class QSBidExclusionAuthorityView(CostSource):
    ref: ref_type('Authority')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    bid_ref: ref_type('Bid')
    rule_ref: ref_type('EvaluationRule')
    delegate_actor_id: TextId
    delegate_organization_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    buyer_authority_ref: ref_type('Authorization')
    buyer_function_ref: ref_type('FunctionAssignment')
    granted_at: TimePoint
    permission: ValueState[bool]


def qs_bid_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'ProcurementRound': QSBidRoundView, 'ProcurementDocument': QSProcurementDocumentView,
        'Bid': QSBidView, 'Clarification': QSBidClarificationView, 'EvaluationProfile': QSBidEvaluationProfileView,
        'EvaluationRule': QSBidEvaluationRuleView, 'EligibilityAssessment': QSBidEligibilityView,
        'NormalizationBasis': QSBidNormalizationBasisView, 'MethodResult': QSBidMethodResultView,
        'EvidenceTarget': QSBidGapView, 'ResponseRequirement': QSProcurementResponseView,
        'Authority': QSBidExclusionAuthorityView, 'ClockProfile': ServiceClockView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items(): registry.register_kind(kind, schema, str)
    return registry
