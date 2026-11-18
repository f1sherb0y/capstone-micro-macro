"""Plan or explicitly evaluate saved A05 planning through A06 purchase reconciliation."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.lifecycle_v4_planning_registration import PlanningConnectionSeed, bind_v4_planning_registration
from integration.lifecycle_v4_supplier_planning_offline import _prepare as prepare_planning, run_v4_supplier_planning_offline
from integration.lifecycle_v4_supplier_purchase_offline import run_v4_supplier_purchase_offline
from integration.lifecycle_v4_logistics_connection import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.sessions import atomic_json
from integration.supplier_planning_production_fixture_sources import DeclaredFormedPurchaseTask
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def run_v4_purchase_chain_offline(*, seed_path, output_directory, execute=False):
    """Use supplied observations and original hosts; create no upstream native facts."""
    if type(execute) is not bool:
        raise ValueError('Purchase chain execution selection must be an explicit boolean')
    seed_file = _read(seed_path)
    seed = PlanningConnectionSeed.model_validate(seed_file[2])
    planning_file = prepare_planning(seed.planning_input_path)
    purchase_file = _read(seed.production_input_path)
    if planning_file[1] != seed.planning_input_sha256 or purchase_file[1] != seed.production_input_sha256:
        raise ValueError('Purchase chain changes original planning or pending purchase input')
    case = purchase_file[2]
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('Purchase chain requires one explicit original synthetic pending input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    source = SupplierProductionFixtureSettings.model_validate(settings.source_settings)
    planning_request = RoleContractInvocation.model_validate(planning_file[3])
    context, original = request.context, planning_request.context
    if (step.get('action_id') != 'SUPPLIER-A06' or step.get('host') != 'integration.supplier_role_contract_host:build_role_host'
            or step.get('operation_id') != context.operation_id or step.get('expected_kind') != 'completed'
            or step.get('expected_choice') != 'reconcile_upstream' or settings.action_id != 'SUPPLIER-A06'
            or context.contract_ref.id != 'SUPPLIER-A06' or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or context.run_id != case['run_id']
            or context.run_id != original.run_id or context.scope != original.scope
            or context.operation_id == original.operation_id
            or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or seed.relation.run_id != context.run_id or seed.relation.scope != context.scope
            or settings.source_factory != 'integration.supplier_production_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-production-fixture-sources.v1'
            or any(getattr(settings, field) is not None for field in (
                'feedback_inputs', 'order_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))):
        raise ValueError('Purchase chain changes original action, authority, source selection or chronology')
    selected = Reference.model_validate(request.action_input['task_ref'])
    formed = [row for row in seed.tasks if row.task.ref.key() == selected.key()]
    if len(formed) != 1 or not isinstance(formed[0], DeclaredFormedPurchaseTask):
        raise ValueError('Purchase chain must select an independently registered original purchase task')
    formed = formed[0]
    setup = request.action_input['execution_setup']
    if (setup.get('kind') != 'purchase'
            or setup.get('purchase_order_ref') != formed.upstream_order.ref.model_dump(mode='json')
            or setup.get('receipt_rule_ref') != formed.receipt_rule.ref.model_dump(mode='json')
            or step.get('expected_task_ref') != formed.task.ref.model_dump(mode='json')
            or step.get('expected_order_ref') != formed.upstream_order.ref.model_dump(mode='json')
            or step.get('expected_delivery_refs') != request.action_input['upstream_delivery_refs']
            or not step['expected_delivery_refs']):
        raise ValueError('Purchase chain changes original task, upstream order, receipt rule or delivery selection')
    projected = {Reference.model_validate(row['ref']).key(): row['value'] for row in source.source_projection['objects']}
    visible = {ref.key() for ref in context.visible_refs}
    pending = {seed.relation.ref.key(), seed.formation_record.ref.key()}
    if (len(projected) != len(source.source_projection['objects']) or len(visible) != len(context.visible_refs)
            or visible - set(projected) != pending or not set(projected) <= visible
            or projected.get(formed.task.ref.key()) != formed.task.model_dump(mode='json')
            or projected.get(formed.upstream_order.ref.key()) != formed.upstream_order.model_dump(mode='json')
            or projected.get(formed.receipt_rule.ref.key()) != formed.receipt_rule.model_dump(mode='json')):
        raise ValueError('Purchase chain changes independently supplied sources or reserved binding references')
    directory = Path(output_directory).resolve()
    planning_directory = Path(planning_file[2]['steps'][0]['output_directory']).resolve()
    purchase_directory = Path(step['output_directory']).resolve()
    roots = (directory, planning_directory, purchase_directory)
    if (len(set(roots)) != len(roots)
            or any(first in second.parents for first in roots for second in roots if first != second)
            or Path(planning_file[4]['settings']['source_settings']['journal_path']).resolve() != planning_directory / 'journal.sqlite'
            or Path(source.journal_path).resolve() != purchase_directory / 'journal.sqlite'):
        raise ValueError('Purchase chain requires separate declared stage directories and exact journal paths')
    if execute and any(root.exists() for root in roots):
        raise FileExistsError('Purchase chain needs new stages; existing journals or attempts require review')
    plan = {'schema_version': 'lifecycle-v4-purchase-chain-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': context.run_id, 'mode': 'execute_offline' if execute else 'plan_only', 'real_model_calls': 0,
        'inputs': [{'path': str(row[0]), 'sha256': row[1]} for row in (seed_file, planning_file, purchase_file)],
        'stages': [{'action_id': 'SUPPLIER-A05', 'output_directory': str(planning_directory)},
            {'kind': 'bind_original_planning', 'output_directory': str(directory / 'planning-binding')},
            {'action_id': 'SUPPLIER-A06', 'choice': 'reconcile_upstream', 'output_directory': str(purchase_directory)}],
        'expected_delivery_refs': deepcopy(step['expected_delivery_refs']),
        'limitations': ['Local synthetic planning-to-purchase-reconciliation path only.',
            'Independent upstream order, delivery, inspection, receipt and native task formation are supplied declarations; no procurement, stock or actual effects proven.']}
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'plan.json', plan)
    atomic_json(directory / 'seed-input.json', seed_file[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-purchase-chain-attempt.v1', 'status': 'started',
        'stage': 'supplier_planning', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    derived_inputs = []

    def track(path):
        item = _read(path)
        derived_inputs.append({'path': str(item[0]), 'sha256': item[1]})
        return item

    def unchanged():
        if any(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']
                for row in [*plan['inputs'], *derived_inputs]):
            raise ValueError('Purchase chain original or derived inputs changed; no replay')

    try:
        unchanged()
        planning = run_v4_supplier_planning_offline(case_path=planning_file[0], output_directory=planning_directory, execute=True)
        planning_result = track(planning_directory / 'supplier' / 'result.json')
        attempt = {**attempt, 'stage': 'bind_original_planning'}
        atomic_json(directory / 'attempt.json', attempt)
        unchanged()
        binding = bind_v4_planning_registration(seed_path=seed_file[0], planning_result_path=planning_result[0],
            output_directory=directory / 'planning-binding')
        connected = track(binding['production_input_path'])
        for name in ('registration.json', 'binding.json', 'assembly/assembly.json'):
            track(directory / 'planning-binding' / name)
        attempt = {**attempt, 'stage': 'supplier_purchase_reconciliation'}
        atomic_json(directory / 'attempt.json', attempt)
        unchanged()
        if purchase_directory.exists():
            raise FileExistsError('Purchase stage appeared during original plan binding; no replay')
        purchase = run_v4_supplier_purchase_offline(case_path=connected[0], output_directory=purchase_directory, execute=True)
        purchase_result = track(purchase_directory / 'supplier' / 'result.json')
        unchanged()
        summary = {**plan, 'mode': 'executed_offline', 'status': 'local_path_completed',
            'planning_identity': deepcopy(planning['identity']), 'purchase_identity': deepcopy(purchase['identity']),
            'result': deepcopy(purchase_result[2]['result']), 'binding_sha256': task_digest(binding),
            'derived_inputs': deepcopy(derived_inputs),
            'outputs': [{'path': str(row[0]), 'sha256': row[1]} for row in (planning_result, purchase_result)]}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_purchase_chain_offline(seed_path=args.seed, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
