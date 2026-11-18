"""Original A01 market tracking can recommend a bounded next private quote margin."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.supplier_monthly_prices import SupplierPriceMonitorPolicy,SupplierPriceMonitorObservation,SupplierPriceMonitorJudgment


def analyze_monthly_prices(context,action_input,reading,*,profile,market_refs):
    policy=reading.resolve(profile.monthly_price_policy_ref);observation=reading.resolve(profile.monthly_price_observation_ref)
    if not isinstance(policy,SupplierPriceMonitorPolicy) or not isinstance(observation,SupplierPriceMonitorObservation):raise ValueError('Typed price-monitor sources required')
    if (policy.organization_id!=reading.organization_id or observation.organization_id!=reading.organization_id
            or policy.scope!=context.scope or observation.scope!=context.scope or observation.as_of!=context.business_time
            or policy.authority_ref not in context.authorization_refs or not policy.effective_window.contains(context.business_time)
            or action_input.inquiry_refs or market_refs!=action_input.market_refs or len(market_refs)!=1):
        raise ValueError('Monthly monitoring changes original scope, authority, current time or received market observation')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or (source.effective_window is not None and not source.effective_window.contains(context.business_time)):
            raise ValueError('Current original price-monitor evidence required')
    current=Decimal(observation.material_index.value);threshold=Decimal(policy.material_index_threshold.value)
    base=Decimal(policy.base_markup_rate);surcharge=Decimal(policy.risk_surcharge_rate)
    for measure in (observation.material_index,policy.material_index_threshold):
        reading.resolve(measure.basis_ref)
        if measure.unit!='index' or not Decimal(measure.value).is_finite() or Decimal(measure.value)<=0:raise ValueError('Global index is not a monetary material price')
    if any(not n.is_finite() or n<0 or n>1 for n in (base,surcharge)) or base+surcharge>1:raise ValueError('Finite bounded private pricing policy required')
    quote=observation.current_original_quote
    if quote['identity']['organization_id']!=reading.organization_id or quote['identity']['action_id']!='SUPPLIER-A03' or quote['tick']!=context.business_time.offset:
        raise ValueError('Price monitoring changes original current own computed quote')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(h['micro_identity']['organization_id']!=reading.organization_id
            or h['micro_identity']['action_id']!='SUPPLIER-A01' or h['operation']!='monitor_material_prices'
            or not h['participated'] or not 0<h['tick']<context.business_time.offset for h in history):
        raise ValueError('Monthly price monitoring borrows another firm, operation or future result')
    previous=history[-1]['price_analysis']['current_original_quote'] if history else None
    if previous is not None and (previous['currency']!=quote['currency'] or previous['priced_product_scope']!=quote['priced_product_scope']):
        raise ValueError('Cannot compare different products, units, destinations or currencies')
    change=None if previous is None else str(Decimal(quote['total_price'])-Decimal(previous['total_price']))
    risk=current>threshold;markup=base+(surcharge if risk else 0)
    interpretation=('Recommend the authorized risk surcharge on the next private quote.' if risk else 'Keep the independently declared base markup on the next private quote.')
    interpretation+=' The global dimensionless index changes margin policy, never the independent original unit costs or a purported market transaction price.'
    reading.recheck()
    return SupplierPriceMonitorJudgment(material_index=observation.material_index,threshold=policy.material_index_threshold,
        price_risk_above_threshold=risk,next_markup_rate=str(markup),current_original_quote=quote,change_from_previous_quote=change,
        consumed_event_ids=[h['event_id'] for h in history],consumed_monitor_result_sha256=[h['micro_result_sha256'] for h in history],interpretation=interpretation)
