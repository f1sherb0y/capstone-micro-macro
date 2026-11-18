"""Received bid amendments and original submission identities; no business effects."""
from typing import Literal

from src.actions.contracts.common import Money, ScopeRef, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.contractor_bid_objects import ContractorBidAllocation, ContractorBidReferenceView, contractor_bid_schemas
from src.actions.contracts.qs_cost_objects import CostSource


class ContractorSavedBidDraft(StrictRecord):
    package_ref: ref_type('ProcurementPackage')
    scope_ref: ScopeRef
    price: Money
    cost_basis_refs: list[ref_type('CostBasis')]
    programme_ref: ref_type('ProgrammeProposal')
    terms_ref: ref_type('ContractTerms')
    exclusion_refs: list[ref_type('Requirement')]
    validity_ref: ref_type('TimeWindow')
    proposed_resources: list[ContractorBidAllocation]


class ContractorAmendmentBidView(CostSource):
    ref: ref_type('Bid')
    organization_id: TextId
    round_ref: ref_type('TenderRound')
    draft: ContractorSavedBidDraft
    submission_ref: ref_type('SubmissionExecution')
    reservation_refs: list[ref_type('ResourceReservation')]


class ContractorAmendmentRoundView(ContractorBidReferenceView):
    ref: ref_type('TenderRound')
    current_package_ref: ref_type('ProcurementPackage')
    amendment_rule_ref: ref_type('TenderAmendmentRule')


class ContractorRevisionPricingInput(StrictRecord):
    package_ref: ref_type('ProcurementPackage')
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    quantity_refs: list[ref_type('QuantityBasis')]
    cost_refs: list[ref_type('CostBasis')]
    capacity_ref: ref_type('ContractorCapacity')
    pricing_profile_ref: ref_type('ContractorPricingProfile')
    allowed_method_refs: list[ref_type('WorkMethod')]


class ContractorAmendmentAnswer(StrictRecord):
    question_ref: ref_type('ClarificationRequest')
    answer: str
    evidence_refs: list[ref_type('Evidence')]
    changed_requirement_refs: list[ref_type('Requirement')]


class ContractorAmendmentProfileView(CostSource):
    ref: ref_type('ContractorRevisionProfile')
    organization_id: TextId
    bid_ref: ref_type('Bid')
    authority_ref: ref_type('Authorization')
    choice: Literal['explain', 'revise', 'maintain', 'withdraw']
    note: TextId
    acknowledged_requirement_refs: list[ref_type('Requirement')]
    answers: list[ContractorAmendmentAnswer]
    revision_input: ContractorRevisionPricingInput | None


class ContractorAmendmentRuleView(CostSource):
    ref: ref_type('TenderAmendmentRule')
    organization_id: TextId
    prior_package_ref: ref_type('ProcurementPackage')
    current_package_ref: ref_type('ProcurementPackage')
    prior_round_ref: ref_type('TenderRound')
    current_round_ref: ref_type('TenderRound')
    notice_received_at: TimePoint
    changed_requirement_refs: list[ref_type('Requirement')]
    profile_ref: ref_type('ContractorRevisionProfile')
    action_window_refs: dict[Literal['explain', 'revise', 'maintain', 'withdraw'], ref_type('TimeWindow')]
    dispositions: dict[Literal['explain', 'revise', 'maintain', 'withdraw'], Literal['allowed', 'refused', 'pending']]
    disposition_basis_ref: ref_type('Evidence')
    maintain_prior_version_allowed: bool


class ContractorAmendmentQuestionView(CostSource):
    ref: ref_type('ClarificationRequest')
    organization_id: TextId
    bid_ref: ref_type('Bid')
    package_ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    requires_revision: bool
    requirement_refs: list[ref_type('Requirement')]
    answer_window_ref: ref_type('TimeWindow')


class ContractorAmendmentSubmissionView(CostSource):
    ref: ref_type('SubmissionExecution')
    organization_id: TextId
    bid_ref: ref_type('Bid')
    package_ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    command_id: TextId
    status: Literal['accepted', 'rejected', 'pending', 'unknown', 'failed', 'not_submitted']
    result_basis_ref: ref_type('Evidence')


class ContractorAmendmentReservationView(CostSource):
    ref: ref_type('ResourceReservation')
    organization_id: TextId
    bid_ref: ref_type('Bid')
    round_ref: ref_type('TenderRound')
    resource_ref: ref_type('ResourcePool')
    reservation_kind: Literal['temporary_bid', 'contract']
    contract_ref: ref_type('Contract') | None
    status: Literal['held', 'release_pending', 'released', 'converted']
    release_basis_ref: ref_type('Evidence')


def contractor_amendment_schemas():
    return contractor_bid_schemas({
        'Bid': ContractorAmendmentBidView,
        'TenderRound': ContractorAmendmentRoundView,
        'TenderAmendmentRule': ContractorAmendmentRuleView,
        'ContractorRevisionProfile': ContractorAmendmentProfileView,
        'ClarificationRequest': ContractorAmendmentQuestionView,
        'SubmissionExecution': ContractorAmendmentSubmissionView,
        'ResourceReservation': ContractorAmendmentReservationView,
    })
