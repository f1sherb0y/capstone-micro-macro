"""Use actual prices and own supply results inside the existing A05 request mode."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.supplier_monthly_inventory import (
    SupplierInventoryPolicy, SupplierInventoryObservation, SupplierInventoryJudgment,
)


def analyze_inventory_review(context, reading, *, profile, mandate, inventory, capacity, request):
    policy = reading.resolve(profile.monthly_inventory_policy_ref)
    observation = reading.resolve(profile.monthly_inventory_observation_ref)
    org, now = reading.organization_id, context.business_time
    if not isinstance(policy, SupplierInventoryPolicy) or not isinstance(observation, SupplierInventoryObservation):
        raise ValueError('Inventory review requires typed policy and actual observations')
    if (policy.organization_id != org or observation.organization_id != org
            or policy.scope != context.scope or observation.scope != context.scope
            or context.scope.kind != 'organization' or context.scope.ref.id != org
            or observation.as_of != now or not policy.effective_window.contains(now)
            or policy.authority_ref != profile.authority_ref or policy.authority_ref not in context.authorization_refs):
        raise ValueError('Inventory review changes own organization, current scope, time or authority')
    if (profile.choice != 'request_quote' or mandate.order_ref is not None or mandate.order_line_refs
            or mandate.speculative_authority_ref is None or inventory.coverage != 'unknown' or inventory.lots
            or capacity.resource_coverage != 'unknown' or capacity.commitment_coverage != 'unknown'
            or capacity.resources or capacity.commitments
            or request['supplier_ids'] != profile.supplier_ids
            or request['required_lines'] != [line.model_dump(mode='python') for line in profile.required_lines]):
        raise ValueError('Review requires independent own-risk planning; actual orders and stock stay unknown')
    for ref in [*policy.evidence_refs, *observation.evidence_refs]:
        source = reading.resolve(ref)
        if not isinstance(source, EvidenceRecord) or source.content_hash is None or (
                source.effective_window is not None and not source.effective_window.contains(now)):
            raise ValueError('Inventory review requires current received evidence')
    def number(measure, unit, bounded=False):
        reading.resolve(measure.basis_ref)
        value = Decimal(measure.value)
        if measure.unit != unit or value < 0 or (bounded and value > 1):
            raise ValueError('Inventory review uses native indices, not inferred physical units')
        return value
    index = number(observation.material_index, 'index')
    threshold = number(policy.minimum_material_index, 'index')
    free = number(observation.native_free_ratio, 'ratio', True)
    limit = number(policy.minimum_free_ratio, 'ratio', True)
    availability_limit = number(policy.minimum_material_availability, 'ratio', True)
    delay_limit = number(policy.maximum_supply_delay_risk, 'ratio', True)
    history = observation.prior_own_outcomes
    if len({h['event_id'] for h in history}) != len(history):
        raise ValueError('Duplicate earlier inventory review')
    for h in history:
        identity = h['micro_identity']
        prior = SupplierInventoryJudgment.model_validate(h['review'])
        if (identity['organization_id'] != org or identity['run_id'] != context.run_id
                or identity['action_id'] != 'SUPPLIER-A05' or not 0 < h['tick'] < now.offset
                or h['participated'] != prior.participate
                or h['operation'] != (prior.operation if prior.participate else 'maintain_operations')
                or h['backup_request'] != prior.current_backup_request):
            raise ValueError('Earlier review is not the same own actual operation and request')
    supply = observation.actual_supply_outcomes
    if len({r['record_sha256'] for r in supply}) != len(supply):
        raise ValueError('Duplicate actual supply outcome')
    latest = {}
    for r in supply:
        if (r['organization_id'] != org or r['run_id'] != context.run_id or not 0 < r['tick'] < now.offset
                or r['scope'] != 'own_current_selected_supplier'
                or r['event_type'] not in {'supplier_selected', 'construction_progress_updated', 'supply_delay'}
                or r['formal_effects_created'] is not False):
            raise ValueError('Supply review borrowed foreign, future or detailed stock facts')
        state = r['native_state']
        availability, delay = Decimal(str(state['material_availability'])), Decimal(str(state['supply_delay_risk']))
        if not 0 <= availability <= 1 or not 0 <= delay <= 1:
            raise ValueError('Supply result is not a bounded native aggregate')
        # Selection itself is not a delivery result. Later original progress/delay
        # observations, including their exact event identities, drive this test.
        if r['event_type'] != 'supplier_selected':
            key = r['project_id']
            if key not in latest or (r['tick'], r['event_id']) > (latest[key]['tick'], latest[key]['event_id']):
                latest[key] = r
    risk = any(Decimal(str(r['native_state']['material_availability'])) < availability_limit
        or Decimal(str(r['native_state']['supply_delay_risk'])) > delay_limit for r in latest.values())
    count = sum(h['participated'] for h in history)
    price = index >= threshold
    participate = (price or risk) and free >= limit and count < policy.maximum_prior_reviews
    return SupplierInventoryJudgment(participate=participate, material_index=observation.material_index,
        material_index_gap=str(index-threshold), native_free_ratio=observation.native_free_ratio,
        price_triggered=price, supply_risk_triggered=risk, prior_actual_review_count=count,
        consumed_event_ids=[h['event_id'] for h in history] + [r['event_id'] for r in supply],
        consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],
        consumed_supply_record_sha256=[r['record_sha256'] for r in supply], current_backup_request=deepcopy(request),
        interpretation=('Review the authorized own-risk stocking inquiry plan.' if participate else
                        'Retain the stocking plan after current price, supply risk, capacity and prior-operation checks.') +
        ' Background planning only; no inquiry sent, physical stock moved, resources reserved or upstream order formed.')
