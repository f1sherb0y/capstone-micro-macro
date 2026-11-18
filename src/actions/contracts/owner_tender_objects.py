"""Original owner procurement preparation, published rounds and bounded decisions."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, Measured, Reference, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.qs_bid_objects import QSBidCriterion
from src.actions.contracts.service_objects import (
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView,
)


TenderChoice = Literal['publish_package', 'invite', 'clarify', 'revise_package', 'evaluate', 'negotiate', 'cancel_round', 'retender']


class TenderQuestion(StrictRecord):
    local_key: TextId
    subject_ref: Reference
    issue_ref: ref_type('Issue') | None
    request: TextId
    requirement_refs: list[ref_type('Requirement')]
    evidence_refs: list[ref_type('Evidence')]


class TenderRevision(StrictRecord):
    prior_package_ref: ref_type('ProcurementPackage')
    requirement_refs: list[ref_type('Requirement')]
    scope_ref: ScopeRef
    submission_window_ref: ref_type('TimeWindow')
    evaluation_profile_ref: ref_type('TenderEvaluationProfile')
    basis_refs: list[ref_type('Evidence')]


class OwnerTenderProcedureView(CostSource):
    ref: ref_type('ProcurementProcedure')
    owner_organization_id: TextId
    authority_ref: ref_type('Authorization')
    required_technical_submission_refs: list[ref_type('DeliverableSubmission')]
    requirement_refs: list[ref_type('Requirement')]
    quantity_required: bool
    quantity_basis_ref: ref_type('QuantityBasis') | None
    evaluation_profile_ref: ref_type('TenderEvaluationProfile')
    submission_window_ref: ref_type('TimeWindow')
    publication_permission: ValueState[bool]
    publication_mode: Literal['open', 'invitation']
    minimum_authorized_budget: ValueState[Money]


class OwnerTenderProfileView(CostSource):
    ref: ref_type('TenderEvaluationProfile')
    owner_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    package_ref: ref_type('ProcurementPackage') | None
    procedure_ref: ref_type('ProcurementProcedure')
    choice_order: Annotated[list[TenderChoice], Field(min_length=1)]
    criteria: list[QSBidCriterion]
    invitation_bidder_refs: list[ref_type('EligibleBidder')]
    selected_round_ref: ref_type('TenderRound') | None
    clarification_ref: ref_type('TenderClarificationPlan') | None
    negotiation_bid_ref: ref_type('Bid') | None
    negotiation_questions: list[TenderQuestion]
    transition_ref: ref_type('TenderTransition') | None
    tie_policy: Literal['retain_equal_groups_require_explicit_award_choice']

    @model_validator(mode='after')
    def explicit_order(self):
        if len(set(self.choice_order)) != len(self.choice_order): raise ValueError('Tender strategy repeats a choice')
        unique_refs(self.invitation_bidder_refs)
        return self


class OwnerTenderPackageView(CostSource):
    ref: ref_type('ProcurementPackage')
    owner_organization_id: TextId
    owner_actor_id: TextId
    authority_ref: ref_type('Authorization')
    procedure_ref: ref_type('ProcurementProcedure')
    evaluation_profile_ref: ref_type('TenderEvaluationProfile')
    requirement_refs: list[ref_type('Requirement')]
    round_refs: list[ref_type('TenderRound')]
    bidder_refs: list[ref_type('EligibleBidder')]
    status: Literal['published', 'superseded', 'closed']


class OwnerTenderRoundView(CostSource):
    ref: ref_type('TenderRound')
    package_ref: ref_type('ProcurementPackage')
    owner_organization_id: TextId
    evaluation_profile_ref: ref_type('TenderEvaluationProfile')
    bid_refs: list[ref_type('Bid')]
    status: Literal['open', 'closed_for_bids', 'stopped_for_award', 'awarded', 'cancelled']
    accepts_new_bids: bool
    accepts_awards: bool
    pending_selection_refs: list[ref_type('TenderSelection')]
    reservation_refs: list[ref_type('ResourceReservation')]
    established_contract_refs: list[ref_type('Contract')]


class OwnerEligibleBidderView(CostSource):
    ref: ref_type('EligibleBidder')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    invitation_permission: ValueState[bool]
    eligibility: ValueState[bool]
    eligibility_rule_refs: list[ref_type('Requirement')]
    status: Literal['active', 'withdrawn']


class OwnerTenderBidView(CostSource):
    ref: ref_type('Bid')
    package_ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    bidder_ref: ref_type('EligibleBidder')
    bidder_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['CONTRACTOR-A02', 'CONTRACTOR-A03', 'SUPPLIER-A03']
    status: Literal['submitted', 'withdrawn']
    submitted_at: TimePoint
    compliance: ValueState[bool]
    compliance_rule_refs: list[ref_type('Requirement')]
    total_price: ValueState[Money]
    risk: ValueState[Measured]
    pricing_basis_ref: ref_type('PricingBasis')


class OwnerTenderFundingCommitment(StrictRecord):
    ref: ref_type('FundingCommitment')
    amount: Money


class OwnerTenderFundingView(CostSource):
    ref: ref_type('FundingPosition')
    owner_organization_id: TextId
    authority_ref: ref_type('Authorization')
    as_of: TimePoint
    authorized_limit: ValueState[Money]
    kind: Literal['authorized_procurement_budget', 'forecast']
    coverage: Literal['complete', 'partial', 'unknown']
    prior_commitments: list[OwnerTenderFundingCommitment]


class OwnerTenderFundingCommitmentView(CostSource):
    ref: ref_type('FundingCommitment')
    owner_organization_id: TextId
    procedure_ref: ref_type('ProcurementProcedure')
    amount: Money
    status: Literal['reserved', 'committed']


class OwnerTenderNotificationView(CostSource):
    ref: ref_type('NotificationPlan')
    package_ref: ref_type('ProcurementPackage')
    round_refs: list[ref_type('TenderRound')]
    recipient_ids: list[TextId]
    authority_ref: ref_type('Authorization')


class OwnerTenderSubmissionView(CostSource):
    ref: ref_type('DeliverableSubmission')
    status: Literal['submitted', 'accepted', 'draft', 'withdrawn']
    allowed_uses: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    readiness: ValueState[bool]


class OwnerTenderReferenceView(CostSource):
    ref: Reference
    procedure_ref: ref_type('ProcurementProcedure')
    permission: ValueState[bool]
    allowed_recipient_ids: list[TextId] = Field(default_factory=list)
    required_public_recipient_ids: list[TextId] = Field(default_factory=list)


class OwnerTenderClarificationView(CostSource):
    ref: ref_type('TenderClarificationPlan')
    package_ref: ref_type('ProcurementPackage')
    bid_ref: ref_type('Bid') | None
    request_refs: list[ref_type('ClarificationRequest')]
    responses: list[TenderQuestion]
    permitted_recipient_ids: list[TextId]
    actual_recipient_ids: list[TextId]
    publication_rule_ref: ref_type('Requirement')
    contains_competitor_private_data: bool


class OwnerTenderTransitionView(CostSource):
    ref: ref_type('TenderTransition')
    prior_package_ref: ref_type('ProcurementPackage')
    authority_ref: ref_type('Authorization')
    operation: Literal['revise_package', 'retender', 'cancel_round']
    relation: Literal['replacement', 'continuation', 'legal_parallel']
    replaced_round_refs: list[ref_type('TenderRound')]
    notify_bidder_ids: list[TextId]
    notification_plan_ref: ref_type('NotificationPlan')
    stop_accepting_bids: bool
    stop_awards: bool
    effective_at: TimePoint
    pending_selection_refs: list[ref_type('TenderSelection')]
    reservation_refs: list[ref_type('ResourceReservation')]
    reservation_handling: Literal['retain_pending_authorized_release', 'original_release_basis']
    release_basis_refs: list[ref_type('Requirement')]
    preserve_contract_refs: list[ref_type('Contract')]
    late_acceptance_rule_ref: ref_type('Requirement')
    parallel_permission_ref: ref_type('Requirement') | None
    revision: TenderRevision | None


def owner_tender_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'ProcurementProcedure': OwnerTenderProcedureView, 'TenderEvaluationProfile': OwnerTenderProfileView,
        'ProcurementPackage': OwnerTenderPackageView, 'TenderRound': OwnerTenderRoundView,
        'EligibleBidder': OwnerEligibleBidderView, 'Bid': OwnerTenderBidView, 'FundingPosition': OwnerTenderFundingView,
        'DeliverableSubmission': OwnerTenderSubmissionView, 'TenderClarificationPlan': OwnerTenderClarificationView,
        'TenderTransition': OwnerTenderTransitionView, 'ClockProfile': ServiceClockView,
        'NotificationPlan': OwnerTenderNotificationView, 'FundingCommitment': OwnerTenderFundingCommitmentView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items(): registry.register_kind(kind, schema, str)
    for kind in ('Requirement', 'QuantityBasis', 'PricingBasis', 'Issue', 'ClarificationRequest', 'TenderSelection',
                 'ResourceReservation', 'Contract'):
        registry.register_kind(kind, OwnerTenderReferenceView, str)
    return registry
