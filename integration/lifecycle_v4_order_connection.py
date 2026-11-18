"""Assemble original saved A04 and independently formed effective order into A05."""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path

from integration.lifecycle_v4_logistics_connection import _read
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.sessions import atomic_json
from integration.supplier_order_fixture_sources import SupplierOrderFixtureSettings
from integration.supplier_order_handoff import supplier_order_handoff_schemas
from integration.supplier_order_planning_fixture_sources import DeclaredOrderPlanningRegistration, SupplierOrderPlanningFixtureSettings
from integration.supplier_role_contract_host import SupplierRoleContractSettings
from integration.supplier_saved_result_source import read_original_supplier_result
from src.actions.contracts.common import Known, Reference
from src.actions.contracts.supplier_order_objects import OrderDeliveryLine, OrderProposalView, order_agreement_digest
from src.coordination.tasks import TaskIdentity, task_digest


def assemble_v4_order_connection(*, order_result_path, order_input_path,
        planning_input_path, registration_path, output_directory):
    """Write connection configuration; never create native orders or permissions."""
    files = [_read(path) for path in (order_result_path, order_input_path, planning_input_path, registration_path)]
    output, order_case, planning_case, declaration = [item[2] for item in files]
    for case in (order_case, planning_case):
        if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
                or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
            raise ValueError('Order connection requires original explicit synthetic V4 inputs')
    original_step, step = order_case['steps'][0], planning_case['steps'][0]
    original_request = RoleContractInvocation.model_validate(original_step['request'])
    original_configuration = RoleContractHostConfiguration.model_validate(original_step['configuration'])
    original_settings = SupplierRoleContractSettings.model_validate(original_configuration.settings)
    original_source = SupplierOrderFixtureSettings.model_validate(original_settings.source_settings)
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    registration = DeclaredOrderPlanningRegistration.model_validate(declaration)
    identity = TaskIdentity(**output['execution_evidence']['identity'])
    context = request.context
    if (original_step['action_id'] != 'SUPPLIER-A04' or step['action_id'] != 'SUPPLIER-A05'
            or original_step['host'] != 'integration.supplier_role_contract_host:build_role_host'
            or step['host'] != original_step['host']
            or original_request.context.contract_ref.id != 'SUPPLIER-A04' or context.contract_ref.id != 'SUPPLIER-A05'
            or original_settings.action_id != 'SUPPLIER-A04' or settings.action_id != 'SUPPLIER-A05'
            or original_settings.source_factory != 'integration.supplier_order_fixture_sources:build_sources'
            or original_settings.source_version != 'configured-supplier-order-fixture-sources.v1'
            or settings.source_factory != 'integration.supplier_planning_fixture_sources:build_sources'
            or settings.source_version != 'configured-supplier-planning-fixture-sources.v1'
            or any(getattr(value, name) is not None for value in (original_settings, settings)
                for name in ('feedback_inputs', 'order_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or identity.action_id != 'SUPPLIER-A04' or identity.role != 'Supplier' or identity.purpose != 'action'
            or identity.run_id != context.run_id or original_request.context.run_id != context.run_id
            or order_case['run_id'] != context.run_id or planning_case['run_id'] != context.run_id
            or identity.request_id != original_request.context.operation_id
            or identity.context_sha256 != task_digest(original_request.context.model_dump(mode='json'))
            or identity.input_sha256 != task_digest(original_request.action_input)
            or identity.organization_id != original_source.source_projection['organization_id']
            or identity.organization_id != settings.source_settings['source_projection']['organization_id']
            or original_request.context.scope != context.scope
            or original_request.context.business_time.clock_ref != context.business_time.clock_ref
            or original_request.context.business_time.offset > context.business_time.offset
            or original_request.context.operation_id == context.operation_id
            or original_request.context.execution_mode != 'offline_fixture' or context.execution_mode != 'offline_fixture'
            or original_request.execution_path != 'deterministic' or request.execution_path != 'deterministic'
            or output.get('request_sha256') != task_digest(original_request.model_dump(mode='json'))
            or output.get('configuration', {}).get('sha256') != task_digest(original_configuration.model_dump(mode='json'))):
        raise ValueError('Order connection changes original action, identity, configuration, scope or chronology')
    original_journal = Path(original_source.journal_path).resolve()
    recipient_journal = Path(settings.source_settings['journal_path']).resolve()
    if original_journal == recipient_journal:
        raise ValueError('Order connection requires separate original and recipient journals')
    record = read_original_supplier_result(journal_path=original_journal, output=output, identity=identity)
    basis, formation = registration.basis, registration.formation_record
    order, work = registration.order, registration.work_authority
    retained = {Reference.model_validate(row['ref']).key(): row['projection'] for row in record['source_reading']}
    proposal = OrderProposalView.model_validate(retained[Reference.model_validate(original_request.action_input['order_proposal_ref']).key()])
    expected = {'run_id': context.run_id, 'organization_id': identity.organization_id, 'scope': context.scope,
        'order_task_sha256': identity.key, 'order_record_sha256': record['record_sha256'],
        'order_input_sha256': identity.input_sha256, 'order_context_sha256': identity.context_sha256,
        'order_result_sha256': record['result_sha256'], 'order_audit_sha256': task_digest(record['audit']),
        'order_source_reading_sha256': record['source_reading_sha256'],
        'proposal_agreement_sha256': record['proposal_agreement_sha256']}
    if (registration.current_state != 'recorded' or any(getattr(basis, key) != value for key, value in expected.items())
            or record['result']['payload']['choice'] != 'accept'
            or order_agreement_digest(proposal) != record['proposal_agreement_sha256']
            or basis.formation_record_ref != formation.ref
            or basis.formation_record_sha256 != task_digest(formation.model_dump(mode='json'))
            or formation.run_id != context.run_id or formation.organization_id != identity.organization_id
            or formation.scope != proposal.scope or order.scope != proposal.scope or work.scope != context.scope
            or formation.order_ref != order.ref or formation.order_projection_sha256 != task_digest(order.model_dump(mode='json'))
            or formation.core_event_id != order.core_event_id or formation.as_of != context.business_time
            or formation.proposal_ref != proposal.ref or formation.offer_ref != proposal.offer_ref
            or formation.terms_ref != proposal.terms_ref or formation.condition_refs != proposal.condition_refs
            or formation.agreement_sha256 != record['proposal_agreement_sha256']
            or formation.buyer_id != proposal.buyer_id or formation.payer_id != proposal.payer_id
            or order.buyer_id != proposal.buyer_id or order.supplier_id != identity.organization_id
            or work.ref.key() != Reference.model_validate(request.action_input['work_authority_ref']).key()
            or work.organization_id != identity.organization_id or work.order_ref != order.ref or work.speculative_authority_ref is not None
            or not isinstance(order.effective, Known) or order.effective.value is not True
            or not isinstance(work.permitted, Known) or work.permitted.value is not True):
        raise ValueError('Order relation changes saved agreement, independently effective order or work mandate')
    accepted = [OrderDeliveryLine.model_validate(row) for row in record['result']['payload']['accepted_lines']]
    formed = {row.order_line_ref.key(): row for row in formation.lines}
    native_lines = {row.ref.key(): row for row in registration.lines}
    links = basis.line_links
    if (not accepted or len(formed) != len(formation.lines) or len(native_lines) != len(registration.lines)
            or len(links) != len(accepted) or len(formed) != len(accepted)
            or {row.accepted_line_index for row in links} != set(range(len(accepted)))
            or {row.order_line_ref.key() for row in links} != set(formed) or set(formed) != set(native_lines)
            or {ref.key() for ref in order.line_refs} != set(formed)
            or not work.order_line_refs or not {ref.key() for ref in work.order_line_refs} <= set(formed)):
        raise ValueError('Native order formation drops or duplicates an original accepted line')
    for link in links:
        formed_line, native_line = formed[link.order_line_ref.key()], native_lines[link.order_line_ref.key()]
        original = accepted[link.accepted_line_index]
        if (formed_line.delivery != original or native_line.order_ref != order.ref
                or formed_line.order_line_sha256 != task_digest(native_line.model_dump(mode='json'))
                or native_line.product != original.product or native_line.delivery_window_ref != original.delivery_window_ref
                or native_line.as_of != context.business_time or native_line.remaining_quantity.unit != original.product.quantity.unit
                or not Decimal('0') <= Decimal(native_line.remaining_quantity.value) <= Decimal(original.product.quantity.value)):
            raise ValueError('Native line changes original delivery, quantity or current remaining amount')
    expected_native = {'schema_version': 'supplier-native-order-formation-observation.v1', 'run_id': context.run_id,
        'recorded_at': registration.recorded_at.model_dump(mode='json'), 'producer': registration.producer,
        'core_event_id': formation.core_event_id, 'proposal_ref': formation.proposal_ref.model_dump(mode='json'),
        'agreement_sha256': formation.agreement_sha256, 'order': order.model_dump(mode='json'),
        'lines': [row.model_dump(mode='json') for row in registration.lines], 'work_authority': work.model_dump(mode='json'),
        'confirmations': [row.model_dump(mode='json') for row in registration.confirmations]}
    if registration.native_record != expected_native or task_digest(expected_native) != formation.native_source_sha256:
        raise ValueError('Order connection changes independently declared native formation content')
    current = deepcopy(settings.source_settings)
    rows = {Reference.model_validate(row['ref']).key(): deepcopy(row) for row in current['source_projection']['objects']}
    if len(rows) != len(current['source_projection']['objects']):
        raise ValueError('Order connection repeats current source identities')
    for projection in (basis, formation, order, work, *registration.lines):
        value = projection.model_dump(mode='json')
        if projection.ref.key() in rows:
            if rows[projection.ref.key()]['value'] != value:
                raise ValueError('Order connection replaces an independently declared current source')
        elif projection.ref.key() not in {ref.key() for ref in context.visible_refs}:
            raise ValueError('Planning input must explicitly authorize pending order sources')
        else:
            rows[projection.ref.key()] = {'ref': projection.ref.model_dump(mode='json'), 'value': value}
    if len({ref.key() for ref in context.visible_refs}) != len(context.visible_refs) or set(rows) != {ref.key() for ref in context.visible_refs}:
        raise ValueError('Order connection changes complete explicitly declared current source identities')
    current['source_projection']['objects'] = [rows[ref.key()] for ref in context.visible_refs]
    source = SupplierOrderPlanningFixtureSettings.model_validate({**current,
        'order_history': {'request': original_request.model_dump(mode='json'),
            'source_settings': original_source.model_dump(mode='json'), 'identity': identity.as_dict(),
            **{key: getattr(original_settings, key) for key in ('macro_version', 'client_version', 'policy_version', 'model_version')}},
        'registration': registration.model_dump(mode='json')})
    schemas = supplier_order_handoff_schemas()
    for row in source.source_projection['objects']:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
    connected = deepcopy(planning_case)
    linked = connected['steps'][0]['configuration']['settings']
    linked.update(source_factory='integration.supplier_order_planning_fixture_sources:build_sources',
        source_version='configured-supplier-order-planning-fixture-sources.v1', source_settings=source.model_dump(mode='json'),
        order_inputs={'version': 'v4-order-planning-selection.v1', 'selections': {context.operation_id:
            {'order_identity': identity.as_dict(), 'basis_ref': basis.ref.model_dump(mode='json')}}})
    SupplierRoleContractSettings.model_validate(linked)
    connected['status'] = 'input_prepared_execution_pending'
    inputs = [{'path': str(path), 'sha256': digest} for path, digest, _ in files]
    connected['source_declaration']['order_connection_inputs'] = inputs
    directory = Path(output_directory).resolve()
    if any(directory == root or directory in root.parents or root in directory.parents
            for root in (original_journal.parent, recipient_journal.parent)):
        raise ValueError('Order configuration output must be separate from action journals')
    directory.mkdir(parents=True, exist_ok=False)
    attempt = {'status': 'started', 'automatic_retry': False, 'action_execution': 'not_performed', 'inputs': inputs}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Order connection original inputs changed before saving')
        atomic_json(directory / 'planning-input.json', connected)
        result = {'schema_version': 'lifecycle-v4-order-connection-assembly.v1', 'status': 'assembled_unverified',
            'order_identity': identity.as_dict(), 'registration_sha256': task_digest(registration.model_dump(mode='json')),
            'planning_input_path': str(directory / 'planning-input.json'), 'action_execution': 'not_performed', 'inputs': inputs}
        atomic_json(directory / 'assembly.json', result)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest, _ in files):
            raise ValueError('Order connection inputs changed while saving configuration')
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return result
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('order-result', 'order-input', 'planning-input', 'registration', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    assemble_v4_order_connection(order_result_path=args.order_result, order_input_path=args.order_input,
        planning_input_path=args.planning_input, registration_path=args.registration, output_directory=args.output)


if __name__ == '__main__':
    main()
