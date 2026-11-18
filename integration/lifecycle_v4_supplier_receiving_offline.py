"""Plan or explicitly evaluate one synthetic V4 Supplier independent receipt acknowledgement."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_receiving_fixture_sources import SupplierReceivingFixtureSettings
from integration.supplier_logistics_receiving_fixture_sources import SupplierLogisticsReceivingFixtureSettings
from integration.supplier_logistics_handoff import supplier_logistics_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_receiving_objects import (
    SupplierReceivingShipmentView, SupplierDeliveryResponseProfileView,
    SupplierCustomerReceiptView, SupplierReceiptComponentView, SupplierReceivingPartyView,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_receiving_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_logistics_receiving_fixture_sources:build_sources'
_LINKED_VERSION = 'configured-supplier-logistics-receiving-fixture-sources.v1'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 receiving response requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierLogisticsReceivingFixtureSettings if linked else SupplierReceivingFixtureSettings).model_validate(settings.source_settings)
    if linked:
        selection = settings.logistics_inputs
        if (settings.source_version != _LINKED_VERSION or selection is None
                or set(selection.selections) != {request.context.operation_id}
                or selection.selections[request.context.operation_id].logistics_identity.as_dict() != source.logistics_history.identity.as_dict()
                or selection.selections[request.context.operation_id].basis_ref != source.registration.basis.ref):
            raise ValueError('V4 connected receiving requires its exact original A08 selection and independent relation')
    elif settings.logistics_inputs is not None:
        raise ValueError('V4 standalone receiving cannot silently declare a logistics connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A09' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'acknowledge_receipt'
            or context.contract_ref.id != 'SUPPLIER-A09' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A09'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-receiving-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A09' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 receiving response alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 receiving response aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 receiving response alters complete original visible projection identities')
    schemas = supplier_logistics_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline receiving evidence must declare its synthetic origin')
    inputs = request.action_input
    shipment = SupplierReceivingShipmentView.model_validate(originals[Reference.model_validate(inputs['shipment_ref']).key()])
    profile = SupplierDeliveryResponseProfileView.model_validate(originals[shipment.response_profile_ref.key()])
    if (shipment.organization_id != projection['organization_id'] or shipment.run_id != context.run_id
            or shipment.history_coverage != 'complete' or shipment.as_of != context.business_time
            or shipment.status != 'arrived' or shipment.query_status != 'present'
            or profile.shipment_ref != shipment.ref or profile.organization_id != shipment.organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or profile.choice != 'acknowledge_receipt' or profile.receipt_ref is None
            or profile.receipt_ref.model_dump(mode='json') != step['expected_receipt_ref']
            or [value.model_dump(mode='json') for value in profile.accepted_fact_refs] != step['expected_accepted_fact_refs']
            or not profile.accepted_fact_refs or profile.supplement_ref is not None or profile.issue_ref is not None
            or profile.replacement_ref is not None or profile.component_refs or profile.evidence_refs_received):
        raise ValueError('V4 receiving response requires its original arrived shipment and selected independent receipt facts')
    for name in ('arrival_refs', 'receipt_refs', 'inspection_refs', 'discrepancy_refs', 'receiving_party_refs'):
        values = [Reference.model_validate(value).key() for value in inputs[name]]
        if len(set(values)) != len(values) or values != [ref.key() for ref in getattr(shipment, name)]:
            raise ValueError('V4 receiving response changes its complete original receiving history')
    if inputs['discrepancy_refs'] != step['expected_discrepancy_refs'] or not inputs['discrepancy_refs']:
        raise ValueError('V4 receiving response omits the retained original delivery discrepancy')
    receipt = SupplierCustomerReceiptView.model_validate(originals[profile.receipt_ref.key()])
    party = SupplierReceivingPartyView.model_validate(originals[receipt.receiving_party_ref.key()])
    if (receipt.status != 'recorded' or receipt.shipment_ref != shipment.ref
            or not set(profile.accepted_fact_refs) <= set(receipt.component_refs)
            or party.organization_id != step['expected_receiver_id'] or party.organization_id == shipment.organization_id
            or receipt.author_organization_id != party.organization_id
            or receipt.author_actor_id != party.actor_id or receipt.author_function_ref != party.function_ref
            or receipt.author_authority_ref != party.authority_ref):
        raise ValueError('V4 receiving response substitutes the independent original customer receipt or its author')
    declared_components = step.get('expected_receipt_components')
    if declared_components is not None:
        if not isinstance(declared_components, list) or not declared_components:
            raise ValueError('V4 receiving response requires explicit nonempty expected receipt components')
        declared_components = [SupplierReceiptComponentView.model_validate(value) for value in declared_components]
        if [value.ref for value in declared_components] != receipt.component_refs:
            raise ValueError('V4 receiving response changes complete expected component identities or order')
    for index, ref in enumerate(receipt.component_refs):
        component = SupplierReceiptComponentView.model_validate(originals[ref.key()])
        if component.shipment_ref != shipment.ref or component.receipt_ref != receipt.ref:
            raise ValueError('V4 receiving response substitutes original receipt component provenance')
        if declared_components is not None:
            if component != declared_components[index]:
                raise ValueError('V4 receiving response alters explicitly supplied receipt quantities or inspection/use sources')
        elif component.usable_quantity.value != '0' or component.inspection_refs or component.use_release_refs:
            raise ValueError('V4 receiving response alters original non-usable facts or introduces undeclared inspection/use approval')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_receiving_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 receiving response execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-receiving-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A09', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_receipt_ref': deepcopy(step['expected_receipt_ref']),
        'expected_accepted_fact_refs': deepcopy(step['expected_accepted_fact_refs']),
        'source_discrepancy_refs': deepcopy(step['expected_discrepancy_refs']),
        'source_receiver_id': step['expected_receiver_id'],
        'source_expected_receipt_components': deepcopy(step.get('expected_receipt_components')),
        'source_logistics_selection': deepcopy(configuration['settings'].get('logistics_inputs')),
        'limitations': ['Isolated synthetic acknowledgement; original partial receipt, damage, quarantine and discrepancy remain sourced facts.',
            'No customer signature, passed inspection, use approval, usable stock, cash, completed work or connected V4 receiving chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-receiving-attempt.v1', 'status': 'started',
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
            'role': 'Supplier', 'action_id': 'SUPPLIER-A09', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A09'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_receiving_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'acknowledge_receipt'
                or result['payload']['receipt_ref'] != step['expected_receipt_ref']
                or result['payload']['accepted_fact_refs'] != step['expected_accepted_fact_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 receiving response did not preserve its exact independent receipt acknowledgement and original result without transport')
        logistics = configuration['settings'].get('logistics_inputs')
        if logistics is not None:
            selected = logistics['selections'][request['context']['operation_id']]
            basis = configuration['settings']['source_settings']['registration']['basis']
            provenance = evidence.get('logistics_input')
            if (not isinstance(provenance, dict) or provenance.get('kind') != 'prepared'
                    or provenance.get('logistics_identity') != selected['logistics_identity']
                    or provenance.get('shipment_ref') != request['action_input']['shipment_ref']
                    or provenance.get('basis_sha256') != task_digest(basis)
                    or provenance.get('logistics_record_sha256') != basis['logistics_record_sha256']
                    or provenance.get('logistics_result_sha256') != basis['logistics_result_sha256']):
                raise ValueError('V4 connected receiving lost its selected original A08 provenance')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original Supplier receiving input changed during evaluation')
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
    print(run_v4_supplier_receiving_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
