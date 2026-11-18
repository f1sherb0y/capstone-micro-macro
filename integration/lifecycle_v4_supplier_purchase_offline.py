"""Plan or explicitly evaluate synthetic V4 upstream delivery reconciliation."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings
from integration.supplier_planning_production_fixture_sources import (
    SupplierPlanningProductionFixtureSettings, check_planning_connection_selection,
    check_planning_connection_provenance,
)
from integration.supplier_planning_handoff import supplier_planning_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Known, Reference
from src.actions.contracts.supplier_execution_objects import (
    SupplierExecutionTaskView, SupplierExecutionProfileView, SupplierExecutionOrderView,
    SupplierGoodsReceiptRuleView, SupplierExternalDeliveryView, SupplierGoodsReceiptView,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_production_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_planning_production_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 purchase reconciliation requires one explicitly synthetic input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierPlanningProductionFixtureSettings if linked else SupplierProductionFixtureSettings).model_validate(settings.source_settings)
    if linked:
        check_planning_connection_selection(request=request, settings=settings, source=source)
    elif settings.planning_inputs is not None:
        raise ValueError('Standalone purchase reconciliation cannot declare a planning connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A06' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'reconcile_upstream'
            or context.contract_ref.id != 'SUPPLIER-A06' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A06'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-production-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A06' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'order_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or projection.get('run_id') != context.run_id or projection.get('read_token') != context.read_token
            or projection.get('business_time') != context.business_time.model_dump(mode='json')
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 purchase reconciliation changes original action, source or snapshot')
    source_ids = [value for org in source.organization_snapshot.organizations for value in org.source_ids]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError('V4 purchase reconciliation aliases independent organization sources')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or [ref.key() for ref in context.visible_refs] != [Reference.model_validate(row['ref']).key() for row in rows]:
        raise ValueError('V4 purchase reconciliation changes complete visible source identities')
    schemas = supplier_planning_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline purchase evidence must declare its synthetic origin')

    def read(ref, schema):
        return schema.model_validate(originals[Reference.model_validate(ref).key()])

    inputs, setup = request.action_input, request.action_input['execution_setup']
    task = read(inputs['task_ref'], SupplierExecutionTaskView)
    profile = read(task.profile_ref.model_dump(mode='json'), SupplierExecutionProfileView)
    if (task.ref.model_dump(mode='json') != step['expected_task_ref'] or task.mode != 'purchase'
            or task.organization_id != projection['organization_id'] or task.scope != context.scope
            or task.history_coverage != 'complete' or task.as_of != context.business_time
            or task.production_method_ref is not None or setup.get('kind') != 'purchase'
            or task.purchase_order_ref is None or task.purchase_order_ref.model_dump(mode='json') != setup['purchase_order_ref']
            or profile.task_ref != task.ref or profile.organization_id != task.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'reconcile_upstream' or profile.inputs or profile.resources):
        raise ValueError('V4 purchase reconciliation requires its original purchase task and authorized profile')
    for name in ('prior_execution_refs', 'upstream_delivery_refs'):
        refs = [Reference.model_validate(ref).key() for ref in inputs[name]]
        if len(set(refs)) != len(refs) or refs != [ref.key() for ref in getattr(task, name)]:
            raise ValueError('V4 purchase reconciliation changes complete original task history')
    if not inputs['upstream_delivery_refs'] or inputs['upstream_delivery_refs'] != step['expected_delivery_refs']:
        raise ValueError('V4 purchase reconciliation requires explicitly selected original deliveries')
    order = read(setup['purchase_order_ref'], SupplierExecutionOrderView)
    rule = read(setup['receipt_rule_ref'], SupplierGoodsReceiptRuleView)
    if (order.ref.model_dump(mode='json') != step['expected_order_ref'] or order.buyer_id != task.organization_id
            or order.supplier_id == order.buyer_id or order.history_coverage != 'complete' or order.as_of != context.business_time
            or not isinstance(order.effective, Known) or order.effective.value is not True
            or rule.order_ref != order.ref or rule.buyer_id != order.buyer_id
            or not isinstance(rule.permitted, Known) or rule.permitted.value is not True
            or not isinstance(rule.supported, Known) or rule.supported.value is not True
            or not {ref.key() for ref in task.upstream_delivery_refs} <= {ref.key() for ref in order.delivery_refs}):
        raise ValueError('V4 purchase reconciliation changes independent upstream order or receipt rule')
    for ref in inputs['upstream_delivery_refs']:
        delivery = read(ref, SupplierExternalDeliveryView)
        if delivery.order_ref != order.ref or delivery.buyer_id != order.buyer_id or delivery.supplier_id != order.supplier_id:
            raise ValueError('V4 purchase delivery changes original order or parties')
        for receipt_ref in delivery.receipt_refs:
            receipt = read(receipt_ref.model_dump(mode='json'), SupplierGoodsReceiptView)
            if receipt.delivery_ref != delivery.ref or receipt.order_ref != order.ref or receipt.buyer_id != order.buyer_id:
                raise ValueError('V4 purchase receipt changes original delivery or buyer')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_purchase_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 purchase execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 purchase execution requires declared new directory and exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-purchase-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A06', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_task_ref': deepcopy(step['expected_task_ref']), 'expected_order_ref': deepcopy(step['expected_order_ref']),
        'expected_delivery_refs': deepcopy(step['expected_delivery_refs']), 'real_model_calls': 0,
        'source_planning_selection': deepcopy(configuration['settings'].get('planning_inputs')),
        'limitations': ['Synthetic reconciliation of explicitly supplied original upstream delivery/receipt history.',
            'No order, goods receipt, inventory movement or procurement effect is created.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-purchase-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V4 purchase input changed or journal exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A06', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A06'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_execution_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'reconcile_upstream'
                or result['payload']['delivery_refs'] != step['expected_delivery_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 purchase result changes original delivery selection, provenance or local-only state')
        if configuration['settings'].get('planning_inputs') is not None:
            source = SupplierPlanningProductionFixtureSettings.model_validate(configuration['settings']['source_settings'])
            check_planning_connection_provenance(request=RoleContractInvocation.model_validate(request), source=source, evidence=evidence)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original purchase input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result)}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_supplier_purchase_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
