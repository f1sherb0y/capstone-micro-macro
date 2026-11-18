"""OWN-A14 asset proposals and actual receipt queries do not create revenue."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.owner_asset_objects import (
    OwnerAssetView, OwnerAssetOperationProfileView, OwnerAssetRightView, OwnerAssetMechanismView,
    OwnerExternalAssetMechanismView, OwnerBoundaryFundingView, OwnerAssetTermsView,
    OwnerAssetConditionView, OwnerAssetForecastView, OwnerAssetServicePlanView, OwnerAssetServiceTaskView,
    OwnerAssetTransactionView, OwnerExternalReceiptBasisView, OwnerAssetReceiptView,
    OwnerAssetCashReceiptView, OwnerAssetReceiptAllocationView, OwnerAssetAccountView,
    OwnerAssetRestrictionView, OwnerAssetExecutionView, OwnerDemandObservationView, OwnerPaymentObligationView,
)
from src.actions.contracts.service_objects import ServiceScopeOrganizationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_asset_operation(context, action_input, reading):
    now, owner, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-asset-clock-alignment')

    def evidence(refs):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('owner-asset-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('owner-asset-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Asset operation expands original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_asset_operation_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_asset_operation_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def overlaps(left,right):
        if left.kind!=right.kind or (left.ref.kind,left.ref.id)!=(right.ref.kind,right.ref.id):
            return False
        left_refs={key[:2] for key in keys(left.coverage_refs)}
        right_refs={key[:2] for key in keys(right.coverage_refs)}
        return not left_refs or not right_refs or bool(left_refs&right_refs)

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'OWN':'Owner','BANK':'Bank','GOV':'Government','CONTRACTOR':'Contractor','SUPPLIER':'Supplier',
               'QS':'QS','ARCHITECT':'Architect','ENGINEER':'Engineer'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Asset source substitutes original author/function/party/action authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_asset_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Asset source precedes original author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def money(value,currency=None):
        evidence([value.basis_ref]);amount=decimal_fraction(value.value)
        if amount<0 or currency is not None and value.currency!=currency:
            raise ValueError('Asset operation changes original currency or creates negative money')
        return amount

    def conditions(refs):
        for ref in refs:
            condition=read(ref,OwnerAssetConditionView,linked=True);author(condition)
            if condition.asset_ref!=asset.ref or not scope_covers(condition.scope,target):
                raise ValueError('Asset condition substitutes original asset or applicable scope')
            if not true(condition.permitted) or not true(condition.satisfied): _needs('independent_original_asset_use_or_disposition_condition',[ref])
        keys(refs)

    def funding(refs):
        seen=set();keys(refs)
        for ref in refs:
            source=read(ref,OwnerBoundaryFundingView,linked=True);clock(source.as_of)
            if source.physical_source_key in seen: raise ValueError('Asset mechanism aliases a shared physical buyer funding source')
            seen.add(source.physical_source_key)
            if source.mode=='uncovered': _unsupported('asset-boundary-funding-uncovered')
            if source.as_of!=now or source.coverage!='complete': _needs('current_complete_shared_asset_boundary_funding',[ref])

    def mechanism():
        row=read(asset.mechanism_ref,OwnerAssetMechanismView,linked=True)
        if row.asset_ref!=asset.ref: raise ValueError('Asset mechanism belongs to another asset')
        if row.counterparty_mode=='uncovered' or isinstance(row.supported,Known) and row.supported.value is False:
            _unsupported('asset-operation-mechanism-uncovered')
        if not true(row.supported) or profile.choice not in row.permitted_choices: _needs('explicit_supported_asset_operation_mechanism')
        for ref in row.counterparty_refs: read(ref,ServiceScopeOrganizationView,linked=True)
        if row.counterparty_mode=='modeled' and not row.counterparty_refs: _needs('explicit_actual_asset_counterparties')
        if row.counterparty_mode=='external':
            if row.external_mechanism_ref is None: _needs('explicit_external_asset_counterparty_process')
            external=read(row.external_mechanism_ref,OwnerExternalAssetMechanismView,linked=True)
            if external.mechanism_ref!=row.ref or not true(external.supported): _unsupported('external-asset-mechanism-uncovered')
            if keys(external.counterparty_refs)!=keys(row.counterparty_refs) or keys(external.funding_boundary_refs)!=keys(row.funding_boundary_refs):
                raise ValueError('External mechanism substitutes original counterparties/shared funding boundary')
        if row.counterparty_mode=='internal' and profile.choice in {'offer_sale','offer_lease','transfer'}:
            _unsupported('asset-transaction-external-counterparty-uncovered')
        if profile.choice in {'offer_sale','offer_lease','transfer'} and not row.funding_boundary_refs:
            _needs('declared_shared_transaction_funding_boundary')
        funding(row.funding_boundary_refs)
        return row

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'scope':profile.scope_choice.model_dump(mode='python'),
            **fields,'note':profile.note+' Proposal/query only. Forecast, effective transaction, receivable, actual cash and actual use/fulfillment remain separate. Asset resale does not create stock; hold does not create rent. Shared buyer funding is referenced, never copied per project. Cash belongs to the original beneficiary/account with original currency and restrictions; debt payment remains separately authorized. No revenue, demand reduction or cash mutation occurs here.'}}

    try:
        asset=read(action_input.asset_ref,OwnerAssetView,linked=True)
        profile=read(action_input.operating_profile_ref,OwnerAssetOperationProfileView)
        if (profile.asset_ref!=asset.ref or profile.organization_id!=owner or profile.actor_id!=context.actor_id
                or profile.function_ref!=context.function_ref or profile.authority_ref not in context.authorization_refs
                or profile.scope!=scope or not scope_covers(asset.scope,scope)):
            raise ValueError('Asset operation changes original actor/asset/organization/scope/authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,owner,'OWN-A14',now,scope)
        clock(asset.as_of)
        if asset.as_of!=now or asset.coverage!='complete': _needs('complete_current_original_asset_right_and_transaction_history')
        for field in ('right_refs','market_refs','transaction_refs','receipt_refs'):
            if keys(getattr(action_input,field))!=keys(getattr(asset,field)): _needs('complete_original_asset_'+field)
        target=profile.scope_choice.scope_ref
        if not profile.scope_choice.basis_refs or not scope_covers(scope,target): raise ValueError('Asset choice lacks original scoped basis')
        evidence(profile.scope_choice.basis_refs);conditions(profile.scope_choice.condition_refs)
        permitted=False
        for ref in action_input.right_refs:
            right=read(ref,OwnerAssetRightView,historic=True,linked=True)
            if right.asset_ref!=asset.ref: raise ValueError('Asset right belongs to another original asset')
            if not overlaps(right.scope,target):
                continue
            right=read(ref,OwnerAssetRightView,linked=True);author(right)
            if right.kind in {'title','delegation'} and (right.holder_id!=asset.legal_owner_id or right.author_organization_id!=asset.legal_owner_id):
                raise ValueError('Asset title/delegation lacks actual legal owner authority')
            if right.kind=='disposition' and profile.choice in {'offer_sale','offer_lease','transfer'}:
                if right.author_organization_id!=right.holder_id or profile.choice not in right.permitted_choices or not true(right.permitted):
                    _needs('all_actual_encumbrance_holder_disposition_permissions',[ref])
            if (scope_covers(right.scope,target) and profile.choice in right.permitted_choices and true(right.permitted)
                    and owner in {right.holder_id,right.delegate_id}):
                if right.kind=='use' and right.author_organization_id!=asset.legal_owner_id:
                    raise ValueError('Asset use right lacks original actual title holder permission')
                permitted=True
        if not permitted: _needs('current_original_owner_or_delegated_asset_choice_right')
        for ref in action_input.market_refs:
            observation=read(ref,OwnerDemandObservationView,linked=True);clock(observation.observed_at);clock(observation.learned_at)
            if observation.observed_at.offset>observation.learned_at.offset or observation.learned_at.offset>now.offset:
                raise ValueError('Asset choice uses future or not yet learned demand information')
        keys(asset.execution_refs);business=set()
        for ref in asset.execution_refs:
            execution=read(ref,OwnerAssetExecutionView,historic=True,linked=True)
            if execution.asset_ref.id!=asset.ref.id or execution.organization_id!=owner or execution.run_id!=context.run_id or execution.business_key in business:
                raise ValueError('Asset operation history repeats or changes original asset/run/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,OwnerAssetOperationProfileView,historic=True,linked=True)
                metadata={'ref','asset_ref','available_at','effective_window'}
                if (original.asset_ref!=execution.asset_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Asset operation changes original content under existing business identity')
                reading.recheck()
                return {'kind':'deferred','reason_code':'query_original_asset_operation','resume_condition':{
                    'trigger':'dependency_change','object_refs':[execution.ref],'earliest_time':None,'condition_code':'query_original_asset_operation'}}
        if profile.choice=='hold': return complete()
        if profile.choice in {'offer_sale','offer_lease','transfer','operate'}:
            if asset.status not in {'partly_available','available'} or not scope_covers(asset.available_scope,target):
                _needs('actual_current_asset_scope_available_for_requested_use')
            selected_mechanism=mechanism()
        if profile.choice in {'offer_sale','offer_lease','transfer'}:
            if profile.terms_ref is None: _needs('original_specific_asset_transaction_terms')
            terms=read(profile.terms_ref,OwnerAssetTermsView,linked=True);author(terms)
            if (terms.asset_ref!=asset.ref or terms.mechanism_ref!=selected_mechanism.ref or terms.choice!=profile.choice
                    or terms.scope!=target or terms.author_organization_id!=owner or terms.status=='withdrawn'):
                raise ValueError('Asset proposal substitutes original terms/asset/mechanism/scope/author')
            if terms.counterparty_ref is not None and terms.counterparty_ref.key() not in keys(selected_mechanism.counterparty_refs):
                raise ValueError('Asset terms invent counterparties outside declared mechanism')
            if profile.choice=='offer_lease':
                if terms.period_ref is None: _needs('original_lease_period')
                period=read(terms.period_ref,TimeWindow);clock(period.start);clock(period.end)
                if period.start.offset<now.offset: raise ValueError('New lease proposal starts before original request')
            conditions(terms.condition_refs)
            if isinstance(terms.price,Known): money(terms.price.value)
            if profile.revenue_forecast.state not in {'known','unknown'}: _unsupported('asset-revenue-forecast-applicability')
            if isinstance(profile.revenue_forecast,Known):
                money(profile.revenue_forecast.value)
                if profile.forecast_ref is None: _needs('explicit_original_revenue_forecast_assumption')
                forecast=read(profile.forecast_ref,OwnerAssetForecastView,linked=True);grant=author(forecast)
                if forecast.asset_ref!=asset.ref or forecast.terms_ref!=terms.ref or forecast.amount!=profile.revenue_forecast:
                    raise ValueError('Asset forecast changes original terms or declared forecast')
                if not {asset.ref.key(),terms.ref.key()}<=keys(forecast.source_refs) or not keys(forecast.source_refs)<=keys(grant.readable_refs):
                    raise ValueError('Asset forecast lacks original asset/terms/source read rights')
                if isinstance(terms.price,Known) and terms.price.value.currency!=forecast.amount.value.currency:
                    raise ValueError('Asset forecast invents currency conversion')
                for source_ref in forecast.source_refs:
                    source=reading.resolve(source_ref)
                    if hasattr(source,'available_at'):
                        clock(source.available_at)
                        if source.available_at.offset>forecast.authored_at.offset: raise ValueError('Asset forecast precedes original source availability')
            return complete(terms_ref=terms.ref,revenue_forecast=profile.revenue_forecast)
        if profile.choice=='operate':
            if profile.service_plan_ref is None: _needs('original_supported_asset_service_plan')
            plan=read(profile.service_plan_ref,OwnerAssetServicePlanView,linked=True);author(plan)
            if (plan.asset_ref!=asset.ref or plan.mechanism_ref!=selected_mechanism.ref or plan.scope!=target
                    or plan.author_organization_id!=owner or plan.purpose!=selected_mechanism.purpose or plan.status=='withdrawn'
                    or keys(plan.funding_boundary_refs)!=keys(selected_mechanism.funding_boundary_refs) or not plan.task_refs):
                raise ValueError('Asset operation substitutes original service mechanism/purpose/funding/tasks')
            conditions(plan.condition_refs);keys(plan.task_refs)
            for ref in plan.task_refs:
                task=read(ref,OwnerAssetServiceTaskView,linked=True);author(task)
                if task.plan_ref!=plan.ref or not scope_covers(target,task.scope) or not true(task.permitted) or task.status in {'completed','cancelled'}:
                    _needs('actual_authorized_asset_service_task',[ref])
            return complete(service_plan_ref=plan.ref)

        if profile.choice!='reconcile_receipt' or not profile.selected_receipt_refs or profile.beneficiary_id is None:
            _needs('original_actual_receipts_and_legal_beneficiary')
        if not keys(profile.selected_receipt_refs)<=keys(asset.receipt_refs): raise ValueError('Reconciliation invents receipts outside original asset history')
        transactions={};physical_transactions=set()
        for ref in asset.transaction_refs:
            transaction=read(ref,OwnerAssetTransactionView,historic=True,linked=True)
            if transaction.asset_ref!=asset.ref or transaction.physical_transaction_key in physical_transactions:
                raise ValueError('Asset receipt aliases or substitutes original actual transaction')
            physical_transactions.add(transaction.physical_transaction_key);transactions[ref.key()]=transaction
        cash_records={};events={};fragments={};selected_allocations=set()
        for ref in profile.selected_receipt_refs:
            receipt=read(ref,OwnerAssetReceiptView,historic=True,linked=True)
            if receipt.asset_ref!=asset.ref or not receipt.allocation_refs: raise ValueError('Receipt lacks original actual asset allocation')
            cash=read(receipt.cash_receipt_ref,OwnerAssetCashReceiptView,historic=True,linked=True);clock(cash.received_at)
            if (cash.run_id!=context.run_id or cash.status!='actual_received' or cash.received_at.offset>now.offset
                    or cash.received_at.offset>cash.available_at.offset
                    or cash.beneficiary_id!=profile.beneficiary_id or not cash.allocation_history_complete):
                _needs('original_actual_received_cash_and_complete_allocation_history',[cash.ref])
            if cash.core_event_id in events and events[cash.core_event_id]!=cash.ref.key() or cash.payment_fragment_key in fragments and fragments[cash.payment_fragment_key]!=cash.ref.key():
                raise ValueError('Cash receipt aliases same original actual payment fragment/event')
            events[cash.core_event_id]=cash.ref.key();fragments[cash.payment_fragment_key]=cash.ref.key()
            if cash.ref.key() not in cash_records:
                account=read(cash.account_ref,OwnerAssetAccountView,linked=True)
                if account.organization_id!=cash.beneficiary_id or account.currency!=cash.amount.currency:
                    raise ValueError('Actual asset cash belongs to another account/entity/currency')
                actual=money(cash.amount);total=Fraction(0);physical=set();keys(cash.allocation_refs)
                if actual<=0: raise ValueError('Actual received cash must be positive')
                for allocation_ref in cash.allocation_refs:
                    allocation=read(allocation_ref,OwnerAssetReceiptAllocationView,historic=True,linked=True)
                    if allocation.cash_receipt_ref!=cash.ref or allocation.physical_allocation_key in physical:
                        raise ValueError('Cash allocation duplicates or substitutes original actual fragment')
                    physical.add(allocation.physical_allocation_key);total+=money(allocation.amount,cash.amount.currency)
                if total>actual: raise ValueError('Receipt allocations exceed actual original cash')
                keys(cash.restriction_refs)
                for restriction_ref in cash.restriction_refs:
                    restriction=read(restriction_ref,OwnerAssetRestrictionView,historic=True,linked=True)
                    if restriction.cash_receipt_ref!=cash.ref or restriction.beneficiary_id!=cash.beneficiary_id:
                        raise ValueError('Cash restriction belongs to another original receipt or beneficiary')
                    if money(restriction.amount,cash.amount.currency)>actual:
                        raise ValueError('Restriction exceeds actual original receipt')
                cash_records[cash.ref.key()]=cash
            if not keys(receipt.allocation_refs)<=keys(cash.allocation_refs): raise ValueError('Receipt invents actual payment allocations')
            for allocation_ref in receipt.allocation_refs:
                if allocation_ref.key() in selected_allocations: raise ValueError('Receipt presentation repeats same actual allocation')
                selected_allocations.add(allocation_ref.key())
                allocation=read(allocation_ref,OwnerAssetReceiptAllocationView,historic=True,linked=True)
                if allocation.asset_ref!=asset.ref: raise ValueError('Receipt allocation belongs to another original asset')
                if allocation.basis_ref.kind=='AssetTransaction':
                    if allocation.basis_ref.key() not in transactions: raise ValueError('Asset receipt omits original transaction')
                    basis=transactions[allocation.basis_ref.key()]
                    if basis.status not in {'effective','settled'} or basis.currency!=cash.amount.currency:
                        raise ValueError('Forecast/pending transaction cannot prove actual received asset cash')
                    if allocation.obligation_ref is not None and allocation.obligation_ref.key() not in keys(basis.obligation_refs):
                        raise ValueError('Receipt substitutes original transaction obligation')
                else:
                    basis=read(allocation.basis_ref,OwnerExternalReceiptBasisView,historic=True,linked=True)
                    if basis.asset_ref!=asset.ref: raise ValueError('External receipt basis belongs to another asset')
                if basis.beneficiary_id!=cash.beneficiary_id or basis.payer_id!=cash.payer_id:
                    raise ValueError('Receipt replaces actual original payer or beneficiary')
                boundary=read(basis.funding_boundary_ref,OwnerBoundaryFundingView,linked=True)
                if boundary.currency!=cash.amount.currency: raise ValueError('Receipt invents cross-currency funding path')
                if allocation.obligation_ref is not None:
                    obligation=read(allocation.obligation_ref,OwnerPaymentObligationView,linked=True)
                    if obligation.payee_id!=cash.beneficiary_id or obligation.debtor_id!=cash.payer_id:
                        raise ValueError('Receipt substitutes original legal debt parties')
        return complete(receipt_refs=profile.selected_receipt_refs,beneficiary_id=profile.beneficiary_id)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
