"""Predeclare inventory-planning inputs; bind only actual native results at runtime."""
from copy import deepcopy
from pathlib import Path
from integration.supplier_reliability_development import build_bundle as planning_foundation
from integration.contractor_tender_development import _write, _write_launch_files
from integration.verify_tender_closed_loop import read
from integration.supplier_monthly_inventory import InventoryPlan
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from src.actions.contracts.common import Reference

HOOK = 'integration.supplier_monthly_inventory:configure_assembly'


def build_bundle(directory, *, run_id, material_price_index, supply_profile=None, ticks=None, random_seed=42):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    ticks = ticks if ticks is not None else (4 if supply_profile is not None else 2)
    if not isinstance(ticks, int) or ticks < 2 or ticks > 12:
        raise ValueError('Inventory scenario needs a bounded original 2-12 tick window')
    base = directory/'planning-foundation'
    planning_foundation(base, run_id=run_id, supply_reliability=0.9, ticks=ticks)
    monthly = read(base/'assembly-host.json')['settings']
    document = read(base/'reliability-input.json')
    kind_map = {'SupplyReliabilityPolicy': 'SupplierInventoryPolicy', 'SupplyReliabilityObservation': 'SupplierInventoryObservation'}
    def rename(value):
        if isinstance(value, list): return [rename(v) for v in value]
        if isinstance(value, dict): return {k: rename(v) for k, v in value.items()}
        if isinstance(value, str):
            if value in kind_map: return kind_map[value]
            if supply_profile is not None:
                for old, new in [('monthly-supplier-a', 'supply-a'), ('monthly-supplier-b', 'supply-b'), ('monthly-owner', 'supply-owner')]:
                    value = value.replace(old, new)
                value = value.replace('supply-a-actor', 'supply-a-execution-actor').replace('supply-b-actor', 'supply-b-execution-actor')
                value = value.replace('supply-owner-actor', 'supply-owner-execution-actor')
            return value.replace('-backup-review-', '-inventory-review-')
        return value
    document = rename(document); monthly['authority'] = rename(monthly['authority'])
    document['schema_version'] = 'supplier-monthly-inventory-input.v1'
    for plan in document['plans']:
        for r in plan['objects']:
            v = r['value']; kind = r['ref']['kind']
            if kind == 'SupplyPlanningProfile':
                v.pop('monthly_reliability_policy_ref'); v.pop('monthly_reliability_observation_ref')
                v['monthly_inventory_policy_ref'] = next(x['ref'] for x in plan['objects'] if x['ref']['kind'] == 'SupplierInventoryPolicy')
                v['monthly_inventory_observation_ref'] = plan['observation_ref']
            elif kind == 'SupplierInventoryPolicy':
                basis = v['evidence_refs'][0]
                measure = lambda value, unit: {'value': value, 'unit': unit, 'basis_ref': basis}
                r['value'] = {k: v[k] for k in ('ref', 'organization_id', 'scope', 'authority_ref', 'effective_window', 'evidence_refs')}
                r['value'].update(minimum_material_index=measure('100' if supply_profile is not None else '1.05', 'index'),
                    minimum_free_ratio=measure('0.2', 'ratio'), minimum_material_availability=measure('0.75', 'ratio'),
                    maximum_supply_delay_risk=measure('0.5', 'ratio'), maximum_prior_reviews=1)
            elif kind == 'SupplierInventoryObservation':
                r['value'] = {k: v[k] for k in ('ref', 'organization_id', 'scope', 'as_of', 'evidence_refs')}
                r['value'].update(material_index=None, native_free_ratio=None, prior_own_outcomes=None, actual_supply_outcomes=None)
        InventoryPlan.model_validate(plan)
        for row in plan['objects']:
            v = deepcopy(row['value'])
            if row['ref'] == plan['native_evidence_ref']: v['content_hash'] = '0'*64
            if row['ref'] == plan['observation_ref']:
                basis = plan['native_evidence_ref']
                v.update(material_index={'value': '0', 'unit': 'index', 'basis_ref': basis},
                    native_free_ratio={'value': '1', 'unit': 'ratio', 'basis_ref': basis},
                    prior_own_outcomes=[], actual_supply_outcomes=[])
            SupplierPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']), v)
    if supply_profile is None:
        macro = read(base/'macro-request.json'); native = read(base/'native-host.json')
        macro['macro_environment'] = {'material_price_index': material_price_index}
        supplier_settings = None
    else:
        from integration.verify_supply_fulfillment import build_inputs
        supply_base = directory/'supply-foundation'
        build_inputs(supply_base, run_id=run_id, profile=supply_profile, ticks=ticks)
        macro = read(supply_base/'macro-request.json'); macro['macro_environment'] = {'material_price_index': material_price_index}
        native = read(supply_base/'native-host.json')
        native['settings']['native_proposals'] = [r for r in native['settings']['native_proposals']
            if (r['role'], r['operation']) != ('Supplier', 'decide_monthly_operation')]
        native['settings']['native_decisions'] = [r for r in native['settings']['native_decisions']
            if (r['role'], r['decision_type']) != ('Supplier', 'monthly_enterprise_operation')]
        supplier_settings = read(supply_base/'assembly-host.json')['settings']['supplier']
        authority = supplier_settings['authority']
        snapshot = authority['organization_snapshot']
        for own in monthly['authority']['organization_snapshot']['organizations']:
            if own['organization_id'] == 'supply-owner': continue
            target, = [o for o in snapshot['organizations'] if o['organization_id'] == own['organization_id']]
            assert target['actor_id'] == own['actor_id']
            target['assignments'].extend(own['assignments'])
        snapshot['authorizations'].extend(monthly['authority']['organization_snapshot']['authorizations'])
        monthly['authority'] = deepcopy(authority)
    macro['random_seed'] = random_seed
    monthly.update(_write(directory, 'inventory-input.json', document))
    settings = monthly if supplier_settings is None else {'supplier': supplier_settings, 'monthly': monthly}
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1', 'settings': settings})
    _write(directory, 'native-host.json', native); _write(directory, 'macro-request.json', macro)
    _write_launch_files(directory, assembly_hook=HOOK, readme_override=__doc__)
