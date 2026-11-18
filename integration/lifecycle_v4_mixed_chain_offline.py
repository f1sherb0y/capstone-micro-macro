"""Plan or explicitly evaluate one split plan and its independent A06 selections."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.lifecycle_v4_logistics_connection import _read
from integration.lifecycle_v4_planning_registration import PlanningConnectionSeed, bind_v4_planning_registration
from integration.lifecycle_v4_supplier_planning_offline import _prepare as prepare_planning, run_v4_supplier_planning_offline
from integration.lifecycle_v4_supplier_production_offline import run_v4_supplier_production_offline
from integration.lifecycle_v4_supplier_purchase_offline import run_v4_supplier_purchase_offline
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.sessions import atomic_json
from integration.supplier_planning_production_fixture_sources import DeclaredFormedProductionTask, DeclaredFormedPurchaseTask
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from src.actions.contracts.common import Reference


def _stage(seed, pending_file, planning_request, label):
    case = pending_file[2]
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('Mixed chain requires explicit original one-step pending inputs')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    source = SupplierProductionFixtureSettings.model_validate(settings.source_settings)
    context, original = request.context, planning_request.context
    choice = 'execute' if label == 'production' else 'reconcile_upstream'
    if (step.get('action_id') != 'SUPPLIER-A06' or step.get('host') != 'integration.supplier_role_contract_host:build_role_host'
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != choice
            or step.get('operation_id') != context.operation_id or settings.action_id != 'SUPPLIER-A06'
            or context.contract_ref.id != 'SUPPLIER-A06' or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or context.run_id != case['run_id']
            or context.run_id != original.run_id or context.scope != original.scope
            or source.organization_snapshot.run_id != context.run_id or source.allow_saved_recovery
            or any(source.source_projection.get(field) != context.model_dump(mode='json')[field]
                for field in ('run_id', 'read_token', 'business_time'))
            or source.source_projection.get('macro_version') != settings.macro_version
            or context.operation_id == original.operation_id
            or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or seed.relation.run_id != context.run_id or seed.relation.scope != context.scope
            or settings.source_factory != 'integration.supplier_production_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-production-fixture-sources.v1'
            or any(getattr(settings, field) is not None for field in (
                'feedback_inputs', 'order_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))):
        raise ValueError('Mixed chain changes original action, authority, source or chronology')
    selected = Reference.model_validate(request.action_input['task_ref'])
    matches = [row for row in seed.tasks if row.task.ref.key() == selected.key()]
    schema = DeclaredFormedProductionTask if label == 'production' else DeclaredFormedPurchaseTask
    if len(matches) != 1 or not isinstance(matches[0], schema):
        raise ValueError('Mixed chain changes the selected native task mode')
    formed = matches[0]
    setup = request.action_input['execution_setup']
    if step.get('expected_task_ref') != formed.task.ref.model_dump(mode='json'):
        raise ValueError('Mixed chain changes original expected task identity')
    if label == 'production':
        if (formed.task.mode != 'manufacture' or setup.get('kind') != 'production'
                or setup.get('release_ref') != formed.release.ref.model_dump(mode='json')
                or setup.get('method_ref') != formed.method.ref.model_dump(mode='json')):
            raise ValueError('Mixed chain changes original manufacture release or method')
    elif (setup.get('kind') != 'purchase'
            or setup.get('purchase_order_ref') != formed.upstream_order.ref.model_dump(mode='json')
            or setup.get('receipt_rule_ref') != formed.receipt_rule.ref.model_dump(mode='json')
            or step.get('expected_order_ref') != formed.upstream_order.ref.model_dump(mode='json')
            or step.get('expected_delivery_refs') != request.action_input['upstream_delivery_refs']
            or not step['expected_delivery_refs']):
        raise ValueError('Mixed chain changes original upstream order, receipt rule or deliveries')
    rows = {Reference.model_validate(row['ref']).key(): row['value'] for row in source.source_projection['objects']}
    visible = {ref.key() for ref in context.visible_refs}
    if (len(rows) != len(source.source_projection['objects']) or len(visible) != len(context.visible_refs)
            or visible - set(rows) != {seed.relation.ref.key(), seed.formation_record.ref.key()}
            or not set(rows) <= visible
            or any(rows.get(row.task.ref.key()) != row.task.model_dump(mode='json') for row in seed.tasks)):
        raise ValueError('Mixed chain omits complete native tasks or changes pending binding authority')
    directory = Path(step['output_directory']).resolve()
    if Path(source.journal_path).resolve() != directory / 'journal.sqlite':
        raise ValueError('Mixed chain changes declared selected stage journal')
    return request, rows, directory, selected.key()


def run_v4_mixed_chain_offline(*, production_seed_path, purchase_seed_path, output_directory, execute=False):
    """Save A05 once and bind each complete formation before its selected A06 host."""
    if type(execute) is not bool:
        raise ValueError('Mixed chain execution selection must be an explicit boolean')
    seed_files = [_read(path) for path in (production_seed_path, purchase_seed_path)]
    seeds = [PlanningConnectionSeed.model_validate(row[2]) for row in seed_files]
    first, second = seeds
    if (Path(first.planning_input_path).resolve() != Path(second.planning_input_path).resolve()
            or first.planning_input_sha256 != second.planning_input_sha256
            or first.model_dump(mode='json', exclude={'production_input_path', 'production_input_sha256'}) !=
                second.model_dump(mode='json', exclude={'production_input_path', 'production_input_sha256'})):
        raise ValueError('Mixed chain selections must preserve identical complete original plan registration')
    planning_file = prepare_planning(first.planning_input_path)
    pending_files = [_read(seed.production_input_path) for seed in seeds]
    if (planning_file[1] != first.planning_input_sha256
            or any(row[1] != seed.production_input_sha256 for row, seed in zip(pending_files, seeds))):
        raise ValueError('Mixed chain changes declared original input SHA')
    planning_step = planning_file[2]['steps'][0]
    planning_request = RoleContractInvocation.model_validate(planning_file[3])
    if (planning_step['expected_choice'] != 'split_plan'
            or [row.planned_task.model_dump(mode='json') for row in first.formation_record.lines] != planning_step['expected_tasks']):
        raise ValueError('Mixed chain requires the exact original complete split plan')
    stages = [_stage(seed, row, planning_request, label)
        for seed, row, label in zip(seeds, pending_files, ('production', 'purchase'))]
    selected_keys = [row[3] for row in stages]
    if (len(set(selected_keys)) != 2 or set(selected_keys) != {row.task.ref.key() for row in first.tasks}
            or stages[0][0].context.operation_id == stages[1][0].context.operation_id
            or stages[0][0].context.business_time != stages[1][0].context.business_time):
        raise ValueError('Mixed chain requires distinct selections covering all registered tasks at one original read time')
    # Both stage snapshots must retain the same declared business objects.
    business_rows = [{key: value for key, value in row[1].items() if key[0] != 'Authorization'} for row in stages]
    if business_rows[0] != business_rows[1]:
        raise ValueError('Mixed chain stages disagree about their complete independent native sources')
    directory = Path(output_directory).resolve()
    planning_directory = Path(planning_step['output_directory']).resolve()
    roots = (directory, planning_directory, stages[0][2], stages[1][2])
    if (len(set(roots)) != len(roots)
            or any(first in second.parents for first in roots for second in roots if first != second)
            or Path(planning_file[4]['settings']['source_settings']['journal_path']).resolve() != planning_directory / 'journal.sqlite'):
        raise ValueError('Mixed chain requires separate declared stage directories and exact journals')
    if execute and any(root.exists() for root in roots):
        raise FileExistsError('Mixed chain needs new stages; existing attempts or journals require review')
    plan = {'schema_version': 'lifecycle-v4-mixed-chain-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': planning_request.context.run_id, 'mode': 'execute_offline' if execute else 'plan_only', 'real_model_calls': 0,
        'inputs': [{'path': str(row[0]), 'sha256': row[1]} for row in (*seed_files, planning_file, *pending_files)],
        'stages': [{'action_id': 'SUPPLIER-A05', 'choice': 'split_plan', 'output_directory': str(planning_directory)}],
        'limitations': ['Local complete two-task synthetic mixed planning path only.',
            'Native task/release/order/delivery/receipt observations are independent supplied declarations; physical effects and further delivery chain remain unproven.']}
    for label, stage in zip(('production', 'purchase'), stages):
        plan['stages'].extend([{'kind': 'bind_original_planning', 'output_directory': str(directory / (label + '-binding'))},
            {'action_id': 'SUPPLIER-A06', 'choice': 'execute' if label == 'production' else 'reconcile_upstream',
                'output_directory': str(stage[2])}])
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-mixed-chain-attempt.v1', 'status': 'started',
        'stage': 'supplier_planning', 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    derived_inputs, outputs, identities = [], [], []

    def track(path):
        row = _read(path)
        derived_inputs.append({'path': str(row[0]), 'sha256': row[1]})
        return row

    def unchanged():
        if any(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']
                for row in [*plan['inputs'], *derived_inputs]):
            raise ValueError('Mixed chain original or derived inputs changed; no replay')

    try:
        unchanged()
        planning = run_v4_supplier_planning_offline(case_path=planning_file[0], output_directory=planning_directory, execute=True)
        planning_result = track(planning_directory / 'supplier' / 'result.json')
        outputs.append(derived_inputs[-1].copy())
        identities.append(deepcopy(planning['identity']))
        for label, seed_file, stage, runner in zip(('production', 'purchase'), seed_files, stages,
                (run_v4_supplier_production_offline, run_v4_supplier_purchase_offline)):
            attempt = {**attempt, 'stage': label + '_binding'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            binding_directory = directory / (label + '-binding')
            binding = bind_v4_planning_registration(seed_path=seed_file[0], planning_result_path=planning_result[0],
                output_directory=binding_directory)
            connected = track(binding['production_input_path'])
            for name in ('registration.json', 'binding.json', 'assembly/assembly.json'):
                track(binding_directory / name)
            attempt = {**attempt, 'stage': 'supplier_' + label}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if stage[2].exists():
                raise FileExistsError('Mixed selected stage appeared during binding; no replay')
            result = runner(case_path=connected[0], output_directory=stage[2], execute=True)
            track(stage[2] / 'supplier' / 'result.json')
            outputs.append(derived_inputs[-1].copy())
            identities.append(deepcopy(result['identity']))
            unchanged()
        summary = {**plan, 'mode': 'executed_offline', 'status': 'local_path_completed',
            'identities': identities, 'outputs': outputs, 'derived_inputs': deepcopy(derived_inputs)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-seed', required=True, type=Path)
    parser.add_argument('--purchase-seed', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_mixed_chain_offline(production_seed_path=args.production_seed, purchase_seed_path=args.purchase_seed,
        output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
