"""Actual asset rights and receipts, separate from proposed revenue and use."""
from typing import Literal

from src.actions.contracts.common import Money, Reference, ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_design_objects import OwnerDesignScopeChoice
from src.actions.contracts.owner_objects import OwnerDemandObservationView, OwnerObservationSourceView
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_review_objects import Digest


class OwnerAssetView(CostSource):
    ref: ref_type('Asset')
    physical_asset_key: TextId
    legal_owner_id: TextId
    available_scope: ScopeRef
    status: Literal['planned','physical_only','partly_available','available','disposed']
    right_refs: list[ref_type('AssetRight')]
    market_refs: list[ref_type('DemandObservation')]
    transaction_refs: list[ref_type('AssetTransaction')]
    receipt_refs: list[ref_type('ReceiptEvidence')]
    mechanism_ref: ref_type('AssetOperationMechanism')
    execution_refs: list[ref_type('AssetOperationExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    producer: Literal['core']


class OwnerAssetOperationProfileView(CostSource):
    ref: ref_type('AssetOperationProfile')
    asset_ref: ref_type('Asset')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    choice: Literal['hold','offer_sale','offer_lease','operate','transfer','reconcile_receipt']
    business_key: TextId
    scope_choice: OwnerDesignScopeChoice
    terms_ref: ref_type('AssetTransactionTerms') | None
    revenue_forecast: ValueState[Money]
    forecast_ref: ref_type('AssetRevenueForecast') | None
    service_plan_ref: ref_type('ServicePlan') | None
    selected_receipt_refs: list[ref_type('ReceiptEvidence')]
    beneficiary_id: TextId | None
    note: TextId


class OwnerAssetRightView(GovReviewAuthored):
    ref: ref_type('AssetRight')
    asset_ref: ref_type('Asset')
    holder_id: TextId
    delegate_id: TextId | None
    permitted_choices: list[TextId]
    permitted: ValueState[bool]
    kind: Literal['title','delegation','disposition','use']


class OwnerAssetMechanismView(CostSource):
    ref: ref_type('AssetOperationMechanism')
    asset_ref: ref_type('Asset')
    permitted_choices: list[TextId]
    supported: ValueState[bool]
    counterparty_mode: Literal['modeled','external','internal','uncovered']
    counterparty_refs: list[ref_type('Organization')]
    external_mechanism_ref: ref_type('ExternalAssetMechanism') | None
    funding_boundary_refs: list[ref_type('BoundaryFundingSource')]
    purpose: Literal['investment_return','own_use','public_service']


class OwnerExternalAssetMechanismView(CostSource):
    ref: ref_type('ExternalAssetMechanism')
    mechanism_ref: ref_type('AssetOperationMechanism')
    supported: ValueState[bool]
    source_kind: Literal['external_data','declared_scenario_process']
    counterparty_refs: list[ref_type('Organization')]
    funding_boundary_refs: list[ref_type('BoundaryFundingSource')]


class OwnerBoundaryFundingView(CostSource):
    ref: ref_type('BoundaryFundingSource')
    physical_source_key: TextId
    currency: TextId
    mode: Literal['finite_aggregate','external_funding','existing_entity_funds','uncovered']
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    producer: Literal['core']


class OwnerAssetTermsView(GovReviewAuthored):
    ref: ref_type('AssetTransactionTerms')
    asset_ref: ref_type('Asset')
    mechanism_ref: ref_type('AssetOperationMechanism')
    choice: Literal['offer_sale','offer_lease','transfer']
    beneficiary_id: TextId
    counterparty_ref: ref_type('Organization') | None
    price: ValueState[Money]
    period_ref: ref_type('TimeWindow') | None
    condition_refs: list[ref_type('Requirement')]
    status: Literal['proposal','pending','agreed','withdrawn']


class OwnerAssetConditionView(GovReviewAuthored):
    ref: ref_type('Requirement')
    asset_ref: ref_type('Asset')
    purpose: Literal['use','disposition','receipt']
    permitted: ValueState[bool]
    satisfied: ValueState[bool]


class OwnerAssetForecastView(GovReviewAuthored):
    ref: ref_type('AssetRevenueForecast')
    asset_ref: ref_type('Asset')
    terms_ref: ref_type('AssetTransactionTerms')
    amount: ValueState[Money]
    classification: Literal['forecast_only']
    basis_kind: Literal['declared_scenario_assumption','external_forecast']
    source_refs: list[Reference]


class OwnerAssetServicePlanView(GovReviewAuthored):
    ref: ref_type('ServicePlan')
    asset_ref: ref_type('Asset')
    mechanism_ref: ref_type('AssetOperationMechanism')
    purpose: Literal['investment_return','own_use','public_service']
    task_refs: list[ref_type('Task')]
    condition_refs: list[ref_type('Requirement')]
    funding_boundary_refs: list[ref_type('BoundaryFundingSource')]
    effect: Literal['plan_only']
    status: Literal['proposed','pending','approved','withdrawn']


class OwnerAssetServiceTaskView(GovReviewAuthored):
    ref: ref_type('Task')
    plan_ref: ref_type('ServicePlan')
    permitted: ValueState[bool]
    status: Literal['planned','released','working','completed','cancelled']


class OwnerAssetTransactionView(CostSource):
    ref: ref_type('AssetTransaction')
    asset_ref: ref_type('Asset')
    physical_transaction_key: TextId
    mechanism_ref: ref_type('AssetOperationMechanism')
    terms_ref: ref_type('AssetTransactionTerms')
    beneficiary_id: TextId
    payer_id: TextId
    currency: TextId
    funding_boundary_ref: ref_type('BoundaryFundingSource')
    obligation_refs: list[ref_type('Obligation')]
    status: Literal['pending','effective','cancelled','settled']
    producer: Literal['core']


class OwnerExternalReceiptBasisView(CostSource):
    ref: ref_type('ExternalReceiptBasis')
    asset_ref: ref_type('Asset')
    beneficiary_id: TextId
    payer_id: TextId
    kind: Literal['grant','external_receipt','service_receipt']
    funding_boundary_ref: ref_type('BoundaryFundingSource')
    producer: Literal['core']


class OwnerAssetReceiptView(CostSource):
    ref: ref_type('ReceiptEvidence')
    asset_ref: ref_type('Asset')
    cash_receipt_ref: ref_type('CashReceipt')
    allocation_refs: list[ref_type('ReceiptAllocation')]
    producer: Literal['core']


class OwnerAssetCashReceiptView(CostSource):
    ref: ref_type('CashReceipt')
    run_id: TextId
    core_event_id: TextId
    payment_fragment_key: TextId
    account_ref: ref_type('Account')
    beneficiary_id: TextId
    payer_id: TextId
    amount: Money
    received_at: TimePoint
    restriction_refs: list[ref_type('FundingRestriction')]
    allocation_refs: list[ref_type('ReceiptAllocation')]
    allocation_history_complete: bool
    status: Literal['actual_received','pending','unknown','reversed']
    producer: Literal['core']


class OwnerAssetReceiptAllocationView(CostSource):
    ref: ref_type('ReceiptAllocation')
    cash_receipt_ref: ref_type('CashReceipt')
    physical_allocation_key: TextId
    asset_ref: ref_type('Asset')
    basis_ref: ref_type('AssetTransaction') | ref_type('ExternalReceiptBasis')
    obligation_ref: ref_type('Obligation') | None
    amount: Money
    producer: Literal['core']


class OwnerAssetAccountView(CostSource):
    ref: ref_type('Account')
    organization_id: TextId
    currency: TextId


class OwnerAssetRestrictionView(CostSource):
    ref: ref_type('FundingRestriction')
    cash_receipt_ref: ref_type('CashReceipt')
    beneficiary_id: TextId
    amount: Money
    permitted_purpose_refs: list[Reference]


class OwnerAssetExecutionView(CostSource):
    ref: ref_type('AssetOperationExecution')
    asset_ref: ref_type('Asset')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('AssetOperationProfile')
    profile_sha256: Digest
    status: Literal['pending','unknown','succeeded','failed','rejected']


def owner_asset_schemas():
    return contractor_bid_schemas({
        'Asset':OwnerAssetView,'AssetOperationProfile':OwnerAssetOperationProfileView,'AssetRight':OwnerAssetRightView,
        'AssetOperationMechanism':OwnerAssetMechanismView,'ExternalAssetMechanism':OwnerExternalAssetMechanismView,
        'BoundaryFundingSource':OwnerBoundaryFundingView,'AssetTransactionTerms':OwnerAssetTermsView,
        'Requirement':OwnerAssetConditionView,'AssetRevenueForecast':OwnerAssetForecastView,'ServicePlan':OwnerAssetServicePlanView,
        'Task':OwnerAssetServiceTaskView,'AssetTransaction':OwnerAssetTransactionView,'ExternalReceiptBasis':OwnerExternalReceiptBasisView,
        'ReceiptEvidence':OwnerAssetReceiptView,'CashReceipt':OwnerAssetCashReceiptView,'ReceiptAllocation':OwnerAssetReceiptAllocationView,
        'Account':OwnerAssetAccountView,'FundingRestriction':OwnerAssetRestrictionView,'AssetOperationExecution':OwnerAssetExecutionView,
        'DemandObservation':OwnerDemandObservationView,'Observation':OwnerObservationSourceView,'Obligation':OwnerPaymentObligationView,
    })
