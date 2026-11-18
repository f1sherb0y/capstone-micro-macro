"""Assemble original OWN-A14 asset proposals and receipt queries without creating revenue."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_asset_objects import (
    OwnerAssetAccountView, OwnerAssetCashReceiptView, OwnerAssetConditionView,
    OwnerAssetExecutionView, OwnerAssetForecastView, OwnerAssetMechanismView,
    OwnerAssetOperationProfileView, OwnerAssetReceiptAllocationView, OwnerAssetReceiptView,
    OwnerAssetRestrictionView, OwnerAssetRightView, OwnerAssetServicePlanView,
    OwnerAssetTermsView, OwnerAssetTransactionView, OwnerAssetView,
    OwnerDemandObservationView, owner_asset_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerAsset(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A14'


class OwnerAssetActionAssembler(OwnerObservationActionAssembler):
    """Keep actual title holders, delegated actors, transactions and receipts.

    Applications hold their current source/authorization guard. The processor
    evaluates rights, supported mechanisms, availability and cash reconciliation.
    Assembly creates no revenue, transaction, stock, use right or cash movement.
    """
    ACTION_ID = 'OWN-A14'
    SOURCE_SCHEMAS = staticmethod(owner_asset_schemas)

    def build(self, context, *, asset_ref, right_refs, operating_profile_ref,
            market_refs, transaction_refs, receipt_refs):
        return self._prepare_supplied_snapshot(context,
            input_values={'asset_ref': asset_ref, 'right_refs': right_refs,
                'operating_profile_ref': operating_profile_ref, 'market_refs': market_refs,
                'transaction_refs': transaction_refs, 'receipt_refs': receipt_refs},
            prepared_type=PreparedOwnerAsset, validate_sources=self._validate_asset_sources)

    @staticmethod
    def _validate_asset_sources(action_input, *, context, reading):
        validate_owner_asset_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_asset_sources(action_input, *, context, organization_id, sources):
    """Check original identities while keeping legal ownership and delegation distinct."""
    asset = sources.get(action_input.asset_ref.key())
    profile = sources.get(action_input.operating_profile_ref.key())
    if (not isinstance(asset, OwnerAssetView) or not isinstance(profile, OwnerAssetOperationProfileView)
            or profile.asset_ref.key() != asset.ref.key() or profile.organization_id != organization_id
            or profile.actor_id != context.actor_id or profile.function_ref.key() != context.function_ref.key()
            or profile.authority_ref.key() not in {ref.key() for ref in context.authorization_refs}
            or profile.scope != context.scope):
        raise TaskConflict('Owner asset operation changes the original asset, profile owner, actor or authority')

    def asset_source(ref, schema, *, required=False):
        source = sources.get(ref.key())
        if source is None and not required:
            return None
        if not isinstance(source, schema) or source.asset_ref.key() != asset.ref.key():
            raise TaskConflict('Owner asset source substitutes another original asset or projection')
        return source

    for refs, schema in ((action_input.right_refs, OwnerAssetRightView),
            (action_input.transaction_refs, OwnerAssetTransactionView),
            (action_input.receipt_refs, OwnerAssetReceiptView)):
        unique_refs(refs)
        for ref in refs:
            asset_source(ref, schema, required=True)
    unique_refs(action_input.market_refs)
    for ref in action_input.market_refs:
        if not isinstance(sources.get(ref.key()), OwnerDemandObservationView):
            raise TaskConflict('Owner asset operation changes an original demand observation projection')
    mechanism = asset_source(asset.mechanism_ref, OwnerAssetMechanismView)
    for ref in profile.scope_choice.condition_refs:
        asset_source(ref, OwnerAssetConditionView)
    terms = asset_source(profile.terms_ref, OwnerAssetTermsView) if profile.terms_ref is not None else None
    plan = asset_source(profile.service_plan_ref, OwnerAssetServicePlanView) if profile.service_plan_ref is not None else None
    for source in (terms, plan):
        if source is not None and mechanism is not None and source.mechanism_ref.key() != mechanism.ref.key():
            raise TaskConflict('Owner asset proposal changes its original operation mechanism')
    if profile.forecast_ref is not None:
        forecast = asset_source(profile.forecast_ref, OwnerAssetForecastView)
        if forecast is not None and terms is not None and forecast.terms_ref.key() != terms.ref.key():
            raise TaskConflict('Owner asset forecast changes the original proposed terms')
    for ref in asset.execution_refs:
        execution = sources.get(ref.key())
        if execution is not None and (not isinstance(execution, OwnerAssetExecutionView)
                or (execution.asset_ref.kind, execution.asset_ref.id) != (asset.ref.kind, asset.ref.id)
                or execution.organization_id != organization_id or execution.run_id != context.run_id):
            raise TaskConflict('Owner asset history changes the original physical asset, organization or run')
        if execution is not None and execution.business_key == profile.business_key:
            original = sources.get(execution.profile_ref.key())
            if original is not None and (not isinstance(original, OwnerAssetOperationProfileView)
                    or original.asset_ref != execution.asset_ref or original.organization_id != execution.organization_id
                    or original.scope != execution.scope or original.business_key != execution.business_key):
                raise TaskConflict('Owner asset execution changes its original operation profile asset or scope')
    for ref in action_input.receipt_refs:
        receipt = sources[ref.key()]
        cash = sources.get(receipt.cash_receipt_ref.key())
        if cash is not None:
            if not isinstance(cash, OwnerAssetCashReceiptView) or cash.run_id != context.run_id:
                raise TaskConflict('Owner asset receipt substitutes another run or cash receipt projection')
            account = sources.get(cash.account_ref.key())
            if account is not None and (not isinstance(account, OwnerAssetAccountView)
                    or account.organization_id != cash.beneficiary_id or account.currency != cash.amount.currency):
                raise TaskConflict('Owner asset cash changes its original beneficiary account or currency')
            for restriction_ref in cash.restriction_refs:
                restriction = sources.get(restriction_ref.key())
                if restriction is not None and (not isinstance(restriction, OwnerAssetRestrictionView)
                        or restriction.cash_receipt_ref.key() != cash.ref.key()
                        or restriction.beneficiary_id != cash.beneficiary_id):
                    raise TaskConflict('Owner asset restriction changes its original cash receipt or beneficiary')
        for allocation_ref in receipt.allocation_refs:
            allocation = asset_source(allocation_ref, OwnerAssetReceiptAllocationView)
            if allocation is not None and allocation.cash_receipt_ref.key() != receipt.cash_receipt_ref.key():
                raise TaskConflict('Owner asset allocation changes its original cash receipt')
    # Actual receipt status, complete allocations, payer/funding restrictions,
    # legal rights and forecasts remain distinct original processor checks.
