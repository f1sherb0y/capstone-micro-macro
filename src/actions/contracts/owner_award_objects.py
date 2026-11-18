"""Original award terms, independent decisions and current owner commitments."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.owner_tender_objects import OwnerTenderRoundView
from src.actions.contracts.service_objects import (
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView,
)
from src.methods.capacity import CapacityDemand, CapacityResource, CapacityCommitment


class OwnerAwardRoundView(OwnerTenderRoundView):
    offer_refs: list[ref_type('Offer')]


class OwnerAwardOfferView(CostSource):
    ref: ref_type('Offer')
    round_ref: ref_type('TenderRound')
    package_ref: ref_type('ProcurementPackage')
    owner_organization_id: TextId
    counterparty_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['CONTRACTOR-A02', 'CONTRACTOR-A03', 'CONTRACTOR-A04', 'SUPPLIER-A03', 'SUPPLIER-A04']
    final_terms_ref: ref_type('ContractTerms')
    condition_refs: list[ref_type('Requirement')]
    status: Literal['offered', 'withdrawn', 'superseded']


class OwnerAwardTermsView(CostSource):
    ref: ref_type('ContractTerms')
    offer_ref: ref_type('Offer')
    round_ref: ref_type('TenderRound')
    owner_organization_id: TextId
    counterparty_organization_id: TextId
    required_party_ids: list[TextId]
    contract_template_ref: ref_type('ContractTemplate')
    total_price: Money
    scope_keys: Annotated[list[TextId], Field(min_length=1)]
    work_window: TimeWindow
    clause_refs: Annotated[list[ref_type('ContractClause')], Field(min_length=1)]
    condition_refs: list[ref_type('Requirement')]
    owner_resource_demands: list[CapacityDemand]
    stage: Literal['award', 'signature', 'effectiveness']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


def award_agreement_digest(terms):
    fields = ('ref', 'scope', 'offer_ref', 'round_ref', 'owner_organization_id', 'counterparty_organization_id',
              'required_party_ids', 'contract_template_ref', 'total_price', 'scope_keys', 'work_window', 'clause_refs',
              'condition_refs', 'owner_resource_demands', 'stage')
    raw = terms.model_dump(mode='json')
    return hashlib.sha256(json.dumps({field: raw[field] for field in fields}, sort_keys=True,
                                   separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class OwnerAwardAcceptanceView(CostSource):
    ref: ref_type('PartyAcceptance')
    run_id: TextId
    offer_ref: ref_type('Offer')
    round_ref: ref_type('TenderRound')
    terms_ref: ref_type('ContractTerms')
    party_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    agreement_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    choice: Literal['accept', 'reject', 'revise']
    status: Literal['active', 'withdrawn']
    decided_at: TimePoint


class OwnerAwardConditionView(CostSource):
    ref: ref_type('Requirement')
    offer_ref: ref_type('Offer')
    terms_ref: ref_type('ContractTerms')
    kind: Literal['counterparty_acceptance', 'signature', 'effectiveness', 'professional', 'funding', 'resource', 'other']
    verification: ValueState[bool]
    verifier_actor_id: TextId
    verifier_function_ref: ref_type('FunctionAssignment')
    verifier_authority_ref: ref_type('Authorization')
    verifier_action_id: TextId


class OwnerAwardPolicyView(CostSource):
    ref: ref_type('ContractFormationProfile')
    owner_organization_id: TextId
    authority_ref: ref_type('Authorization')
    offer_ref: ref_type('Offer')
    terms_ref: ref_type('ContractTerms')
    choice_order: Annotated[list[Literal['accept', 'revise', 'reject']], Field(min_length=1)]
    requested_change_refs: list[ref_type('ContractChangeRequest')]
    pending_party_condition_refs: list[ref_type('Requirement')]
    allow_owner_acceptance_pending_other_parties: bool
    reject_reason: TextId


class OwnerAwardFundingUse(StrictRecord):
    ref: ref_type('FundingCommitment')
    amount: Money


class OwnerAwardSnapshotView(CostSource):
    ref: ref_type('CommitmentSnapshot')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    formation_profile_ref: ref_type('ContractFormationProfile')
    authorized_budget: ValueState[Money]
    funding_uses: list[OwnerAwardFundingUse]
    resources: list[CapacityResource]
    resource_commitments: list[CapacityCommitment]
    allocation_refs: list[ref_type('ContractAllocation')]
    counterparty_capacity_condition_ref: ref_type('Requirement') | None


class OwnerAwardCommitmentView(CostSource):
    ref: Reference
    owner_organization_id: TextId
    amount: Money | None
    resource_ref: Reference | None
    quantity: Measured | None
    window: TimeWindow | None


class OwnerAwardAllocationView(CostSource):
    ref: ref_type('ContractAllocation')
    owner_organization_id: TextId
    round_ref: ref_type('TenderRound')
    scope_keys: list[TextId]
    contract_ref: ref_type('Contract')
    status: Literal['effective', 'released']
    release_basis_ref: ref_type('Requirement') | None


class OwnerAwardReferenceView(CostSource):
    ref: Reference
    offer_ref: ref_type('Offer')
    terms_ref: ref_type('ContractTerms')
    permission: ValueState[bool]


class OwnerAwardTemplateView(OwnerAwardReferenceView):
    ref: ref_type('ContractTemplate')
    required_owner_resource_kinds: list[TextId]
    required_condition_refs: list[ref_type('Requirement')]
    required_stage: Literal['award', 'signature', 'effectiveness']
    counterparty_capacity_required: bool


def owner_award_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'TenderRound': OwnerAwardRoundView, 'Offer': OwnerAwardOfferView, 'ContractTerms': OwnerAwardTermsView,
        'PartyAcceptance': OwnerAwardAcceptanceView, 'Requirement': OwnerAwardConditionView,
        'CommitmentSnapshot': OwnerAwardSnapshotView, 'ContractFormationProfile': OwnerAwardPolicyView,
        'ContractAllocation': OwnerAwardAllocationView, 'FundingCommitment': OwnerAwardCommitmentView,
        'ResourceCommitment': OwnerAwardCommitmentView, 'ClockProfile': ServiceClockView,
        'ContractTemplate': OwnerAwardTemplateView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items(): registry.register_kind(kind, schema, str)
    for kind in ('ContractClause', 'ContractChangeRequest', 'Contract', 'Resource', 'ResourcePool'):
        registry.register_kind(kind, OwnerAwardReferenceView, str)
    return registry
