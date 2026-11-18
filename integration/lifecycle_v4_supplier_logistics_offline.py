"""Plan or explicitly evaluate one synthetic V4 Supplier dispatch request."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_logistics_fixture_sources import SupplierLogisticsFixtureSettings
from integration.supplier_quality_logistics_fixture_sources import SupplierQualityLogisticsFixtureSettings
from integration.supplier_quality_handoff import supplier_quality_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_logistics_objects import (
    SupplierLogisticsOrderView, SupplierLogisticsProfileView, SupplierDispatchableView,
    SupplierShipmentSliceView, SupplierReceivingWindowView,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_logistics_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_quality_logistics_fixture_sources:build_sources'
_LINKED_VERSION = 'configured-supplier-quality-logistics-fixture-sources.v1'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 logistics request requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierQualityLogisticsFixtureSettings if linked else SupplierLogisticsFixtureSettings).model_validate(settings.source_settings)
    if linked:
        selection = settings.quality_inputs
        if (settings.source_version != _LINKED_VERSION or selection is None
                or set(selection.selections) != {request.context.operation_id}
                or selection.selections[request.context.operation_id].quality_identity.as_dict() != source.quality_history.identity.as_dict()
                or selection.selections[request.context.operation_id].basis_ref != source.registration.basis.ref):
            raise ValueError('V4 connected logistics requires the selected original A07 and independent release relation')
    elif settings.quality_inputs is not None:
        raise ValueError('V4 standalone logistics cannot silently declare a quality connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A08' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'dispatch'
            or context.contract_ref.id != 'SUPPLIER-A08' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A08'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-logistics-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A08' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'execution_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 logistics request alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 logistics request aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 logistics request alters complete original visible projection identities')
    schemas = supplier_quality_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline logistics evidence must declare its synthetic origin')
    inputs = request.action_input
    order = SupplierLogisticsOrderView.model_validate(originals[Reference.model_validate(inputs['order_ref']).key()])
    profile = SupplierLogisticsProfileView.model_validate(originals[Reference.model_validate(inputs['logistics_profile_ref']).key()])
    if (order.ref.model_dump(mode='json') != step['expected_order_ref']
            or order.supplier_id != projection['organization_id'] or order.scope != context.scope
            or order.coverage != 'complete' or order.as_of != context.business_time
            or profile.order_ref != order.ref or profile.organization_id != order.supplier_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'dispatch' or not profile.plans
            or [value.model_dump(mode='json') for value in profile.plans] != step['expected_plans']
            or [[value.model_dump(mode='json') for value in refs] for refs in profile.plan_slice_refs] != step['expected_plan_slice_refs']
            or len(profile.plans) != len(profile.plan_slice_refs)
            or profile.shipment_ref is not None or profile.replacement_route_ref is not None
            or profile.current_position_ref is not None or profile.replacement_allocation_refs
            or profile.target_kind is not None or profile.target_line_refs or profile.target_shipment_refs
            or profile.proposed_window_ref is not None):
        raise ValueError('V4 logistics request requires its original complete order and exact physical dispatch plan')
    for name in ('dispatchable_refs', 'receiving_window_refs', 'route_candidates', 'capacity_refs',
            'requirement_refs', 'shipment_refs', 'position_refs'):
        values = [Reference.model_validate(value).key() for value in inputs[name]]
        if len(set(values)) != len(values) or name == 'shipment_refs' and values != [ref.key() for ref in order.shipment_refs]:
            raise ValueError('V4 logistics request changes unique supplied sources or complete shipment history')
    dispatchables = {Reference.model_validate(value).key(): SupplierDispatchableView.model_validate(
        originals[Reference.model_validate(value).key()]) for value in inputs['dispatchable_refs']}
    slices = set()
    receivers = [SupplierReceivingWindowView.model_validate(originals[Reference.model_validate(value).key()])
        for value in inputs['receiving_window_refs']]
    for plan, refs in zip(profile.plans, profile.plan_slice_refs):
        if not refs or plan.route_ref.model_dump(mode='json') not in inputs['route_candidates']:
            raise ValueError('V4 logistics request omits original cargo slices or selected received route')
        for ref in refs:
            row = SupplierShipmentSliceView.model_validate(originals[ref.key()])
            stock = dispatchables.get(row.dispatchable_ref.key())
            if (stock is None or stock.order_ref != order.ref or stock.batch_ref != plan.batch_ref
                    or stock.source_ref != plan.source_ref or stock.line_ref not in order.line_refs
                    or row.physical_slice_key in slices):
                raise ValueError('V4 logistics request repeats physical cargo or changes original batch/source/order')
            slices.add(row.physical_slice_key)
        matches = [row for row in receivers if row.window_ref == plan.receiving_window_ref
            and row.destination_ref == plan.destination_ref]
        if (len(matches) != 1 or matches[0].order_ref != order.ref or matches[0].receiver_id != order.buyer_id
                or matches[0].receiver_id != step['expected_receiver_id']
                or matches[0].author_organization_id != order.buyer_id or order.buyer_id == order.supplier_id):
            raise ValueError('V4 logistics request requires its independently supplied original buyer receiving window')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_logistics_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 logistics request execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-logistics-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A08', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_plans': deepcopy(step['expected_plans']),
        'source_order_ref': deepcopy(step['expected_order_ref']),
        'source_plan_slice_refs': deepcopy(step['expected_plan_slice_refs']),
        'source_receiver_id': step['expected_receiver_id'],
        'source_quality_selection': deepcopy(configuration['settings'].get('quality_inputs')),
        'limitations': ['Isolated synthetic dispatch request; batch release, receiving window and transport reservations are supplied assumptions.',
            'No actual dispatch, arrival, destination stock, receipt, use approval, title/risk transfer or connected V4 transport chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-logistics-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V4 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A08', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A08'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_logistics_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'dispatch'
                or result['payload']['plans'] != step['expected_plans']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 logistics request did not preserve its exact physical dispatch request and original result without transport')
        quality = configuration['settings'].get('quality_inputs')
        if quality is not None:
            selected = quality['selections'][request['context']['operation_id']]
            basis = configuration['settings']['source_settings']['registration']['basis']
            provenance = evidence.get('quality_input')
            if (not isinstance(provenance, dict) or provenance.get('kind') != 'prepared'
                    or provenance.get('quality_identity') != selected['quality_identity']
                    or provenance.get('basis_sha256') != task_digest(basis)
                    or provenance.get('quality_record_sha256') != basis['quality_record_sha256']
                    or provenance.get('quality_result_sha256') != basis['quality_result_sha256']):
                raise ValueError('V4 connected logistics lost its original quality provenance')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original Supplier logistics input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result), 'real_model_calls': 0}
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
    print(run_v4_supplier_logistics_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
