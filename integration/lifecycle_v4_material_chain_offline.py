"""Plan or explicitly evaluate connected synthetic Supplier-to-Contractor material inputs."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.contractor_role_contract_host import ContractorRoleContractSettings
from integration.lifecycle_v4_contractor_material import run_v4_contractor_material
from integration.lifecycle_v4_material_connection import _read
from integration.lifecycle_v4_material_registration import MaterialConnectionSeed, bind_v4_material_registration
from integration.lifecycle_v4_logistics_registration import LogisticsConnectionSeed, bind_v4_logistics_registration
from integration.lifecycle_v4_quality_registration import QualityConnectionSeed, bind_v4_quality_registration
from integration.lifecycle_v4_production_registration import ProductionConnectionSeed, bind_v4_production_registration
from integration.lifecycle_v4_planning_registration import PlanningConnectionSeed, bind_v4_planning_registration
from integration.lifecycle_v4_order_registration import OrderConnectionSeed, bind_v4_order_registration
from integration.lifecycle_v4_supplier_order_offline import _prepare as prepare_order, run_v4_supplier_order_offline
from integration.lifecycle_v4_supplier_planning_offline import _prepare as prepare_planning, run_v4_supplier_planning_offline
from integration.lifecycle_v4_supplier_production_offline import _prepare as prepare_production, run_v4_supplier_production_offline
from integration.lifecycle_v4_supplier_quality_offline import _prepare as prepare_quality, run_v4_supplier_quality_offline
from integration.lifecycle_v4_supplier_logistics_offline import _prepare as prepare_logistics, run_v4_supplier_logistics_offline
from integration.lifecycle_v4_supplier_receiving_offline import _prepare as prepare_receiving, run_v4_supplier_receiving_offline
from integration.role_contract_host import RoleContractInvocation
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_execution_objects import ContractorExecutionTaskView, ContractorExecutionProfileView
from src.coordination.tasks import TaskIdentity, task_digest


def run_v4_material_chain_offline(*, seed_path, output_directory, execute=False,
        logistics_seed_path=None, quality_seed_path=None, production_seed_path=None, planning_seed_path=None,
        order_seed_path=None):
    if type(execute) is not bool:
        raise ValueError('Material chain execution selection must be an explicit boolean')
    if quality_seed_path is not None and logistics_seed_path is None:
        raise ValueError('Connected quality stage requires an explicit original logistics connection seed')
    if production_seed_path is not None and quality_seed_path is None:
        raise ValueError('Connected production stage requires an explicit original quality connection seed')
    if planning_seed_path is not None and production_seed_path is None:
        raise ValueError('Connected planning stage requires an explicit original production connection seed')
    if order_seed_path is not None and planning_seed_path is None:
        raise ValueError('Connected order stage requires an explicit original planning connection seed')
    seed_file = _read(seed_path)
    seed = MaterialConnectionSeed.model_validate(seed_file[2])
    supplier_file = prepare_receiving(seed.supplier_input_path)
    if supplier_file[1] != seed.supplier_input_sha256:
        raise ValueError('Material chain seed changes its original Supplier input')
    request = RoleContractInvocation.model_validate(seed.contractor['request'])
    settings = ContractorRoleContractSettings.model_validate(seed.contractor['configuration']['settings'])
    context = request.context
    supplier_context = RoleContractInvocation.model_validate(supplier_file[3]).context
    logistics_seed_file = logistics_file = receiving_seed_file = None
    logistics_seed = None
    if logistics_seed_path is not None:
        logistics_seed_file = _read(logistics_seed_path)
        logistics_seed = LogisticsConnectionSeed.model_validate(logistics_seed_file[2])
        logistics_file = prepare_logistics(logistics_seed.logistics_input_path)
        receiving_seed_file = _read(logistics_seed.receiving_input_path)
        if (logistics_file[1] != logistics_seed.logistics_input_sha256
                or receiving_seed_file[1] != logistics_seed.receiving_input_sha256
                or len(receiving_seed_file[2]['steps']) != 1):
            raise ValueError('Material chain changes original logistics or pending receiving seed input')
        pending = RoleContractInvocation.model_validate(receiving_seed_file[2]['steps'][0]['request'])
        pending_context = pending.context.model_dump(mode='json')
        original_context = supplier_context.model_dump(mode='json')
        if (pending.action_input != RoleContractInvocation.model_validate(supplier_file[3]).action_input
                or pending.execution_path != 'deterministic'
                or {key: value for key, value in pending_context.items() if key != 'visible_refs'} !=
                    {key: value for key, value in original_context.items() if key != 'visible_refs'}
                or not {ref.key() for ref in supplier_context.visible_refs} <= {ref.key() for ref in pending.context.visible_refs}
                or logistics_seed.relation.scope != supplier_context.scope
                or logistics_seed.relation.run_id != context.run_id
                or logistics_seed.relation.ref.key() not in {ref.key() for ref in pending.context.visible_refs}):
            raise ValueError('Connected logistics seed replaces the selected original receiving task or authority')
    quality_seed_file = quality_file = logistics_seed_input = None
    quality_seed = None
    if quality_seed_path is not None:
        quality_seed_file = _read(quality_seed_path)
        quality_seed = QualityConnectionSeed.model_validate(quality_seed_file[2])
        quality_file = prepare_quality(quality_seed.quality_input_path)
        logistics_seed_input = _read(quality_seed.logistics_input_path)
        if (quality_file[1] != quality_seed.quality_input_sha256
                or logistics_seed_input[1] != quality_seed.logistics_input_sha256
                or len(logistics_seed_input[2]['steps']) != 1):
            raise ValueError('Material chain changes original quality or pending logistics seed input')
        pending = RoleContractInvocation.model_validate(logistics_seed_input[2]['steps'][0]['request'])
        original = RoleContractInvocation.model_validate(logistics_file[3])
        pending_context, original_context = pending.context.model_dump(mode='json'), original.context.model_dump(mode='json')
        if (pending.action_input != original.action_input or pending.execution_path != 'deterministic'
                or {key: value for key, value in pending_context.items() if key != 'visible_refs'} !=
                    {key: value for key, value in original_context.items() if key != 'visible_refs'}
                or not {ref.key() for ref in original.context.visible_refs} <= {ref.key() for ref in pending.context.visible_refs}
                or quality_seed.relation.scope != original.context.scope
                or quality_seed.relation.run_id != context.run_id
                or quality_seed.relation.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or quality_seed.release_record.ref.key() not in {ref.key() for ref in pending.context.visible_refs}):
            raise ValueError('Connected quality seed replaces original logistics input, scope or authority')
    production_seed_file = production_file = quality_seed_input = None
    production_seed = None
    if production_seed_path is not None:
        production_seed_file = _read(production_seed_path)
        production_seed = ProductionConnectionSeed.model_validate(production_seed_file[2])
        production_file = prepare_production(production_seed.production_input_path)
        quality_seed_input = _read(production_seed.quality_input_path)
        if (production_file[1] != production_seed.production_input_sha256
                or quality_seed_input[1] != production_seed.quality_input_sha256
                or len(quality_seed_input[2]['steps']) != 1):
            raise ValueError('Material chain changes original production or pending quality seed input')
        pending = RoleContractInvocation.model_validate(quality_seed_input[2]['steps'][0]['request'])
        original = RoleContractInvocation.model_validate(quality_file[3])
        pending_context, original_context = pending.context.model_dump(mode='json'), original.context.model_dump(mode='json')
        production_context = RoleContractInvocation.model_validate(production_file[3]).context
        if (pending.action_input != original.action_input or pending.execution_path != 'deterministic'
                or {key: value for key, value in pending_context.items() if key != 'visible_refs'} !=
                    {key: value for key, value in original_context.items() if key != 'visible_refs'}
                or not {ref.key() for ref in original.context.visible_refs} <= {ref.key() for ref in pending.context.visible_refs}
                or production_seed.relation.scope != original.context.scope
                or production_seed.relation.run_id != context.run_id
                or production_seed.relation.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or production_context.scope != original.context.scope or production_context.run_id != context.run_id
                or production_context.business_time.clock_ref != original.context.business_time.clock_ref
                or production_context.business_time.offset > original.context.business_time.offset):
            raise ValueError('Connected production seed replaces original quality task, scope, clock or authority')
    planning_seed_file = planning_file = production_seed_input = None
    planning_seed = None
    if planning_seed_path is not None:
        planning_seed_file = _read(planning_seed_path)
        planning_seed = PlanningConnectionSeed.model_validate(planning_seed_file[2])
        planning_file = prepare_planning(planning_seed.planning_input_path)
        production_seed_input = _read(planning_seed.production_input_path)
        if (planning_file[1] != planning_seed.planning_input_sha256
                or production_seed_input[1] != planning_seed.production_input_sha256
                or len(production_seed_input[2]['steps']) != 1):
            raise ValueError('Material chain changes original planning or pending production input')
        pending_step = production_seed_input[2]['steps'][0]
        pending = RoleContractInvocation.model_validate(pending_step['request'])
        original = RoleContractInvocation.model_validate(production_file[3])
        pending_context, original_context = pending.context.model_dump(mode='json'), original.context.model_dump(mode='json')
        planning_context = RoleContractInvocation.model_validate(planning_file[3]).context
        if (pending.action_input != original.action_input or pending.execution_path != 'deterministic'
                or {key: value for key, value in pending_context.items() if key != 'visible_refs'} !=
                    {key: value for key, value in original_context.items() if key != 'visible_refs'}
                or not {ref.key() for ref in original.context.visible_refs} <= {ref.key() for ref in pending.context.visible_refs}
                or planning_seed.relation.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or planning_seed.formation_record.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or planning_seed.relation.scope != original.context.scope or planning_seed.relation.run_id != context.run_id
                or planning_context.scope != original.context.scope or planning_context.run_id != context.run_id
                or planning_context.business_time.clock_ref != original.context.business_time.clock_ref
                or planning_context.business_time.offset > original.context.business_time.offset
                or any(pending_step.get(key) != production_file[2]['steps'][0].get(key)
                    for key in ('action_id', 'host', 'operation_id', 'expected_kind', 'expected_choice',
                        'expected_task_ref', 'expected_inputs', 'expected_resources'))):
            raise ValueError('Connected planning seed changes original production intent, task, scope, clock or authority')
    order_seed_file = order_file = planning_seed_input = None
    order_seed = None
    if order_seed_path is not None:
        order_seed_file = _read(order_seed_path)
        order_seed = OrderConnectionSeed.model_validate(order_seed_file[2])
        order_file = prepare_order(order_seed.order_input_path)
        planning_seed_input = _read(order_seed.planning_input_path)
        if (order_file[1] != order_seed.order_input_sha256
                or planning_seed_input[1] != order_seed.planning_input_sha256
                or len(planning_seed_input[2]['steps']) != 1):
            raise ValueError('Material chain changes original order or pending planning input')
        pending_step = planning_seed_input[2]['steps'][0]
        pending = RoleContractInvocation.model_validate(pending_step['request'])
        original = RoleContractInvocation.model_validate(planning_file[3])
        pending_context, original_context = pending.context.model_dump(mode='json'), original.context.model_dump(mode='json')
        order_context = RoleContractInvocation.model_validate(order_file[3]).context
        if (pending.action_input != original.action_input or pending.execution_path != 'deterministic'
                or {key: value for key, value in pending_context.items() if key != 'visible_refs'} !=
                    {key: value for key, value in original_context.items() if key != 'visible_refs'}
                or not {ref.key() for ref in original.context.visible_refs} <= {ref.key() for ref in pending.context.visible_refs}
                or order_seed.relation.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or order_seed.formation_record.ref.key() not in {ref.key() for ref in pending.context.visible_refs}
                or order_seed.relation.scope != original.context.scope or order_seed.relation.run_id != context.run_id
                or order_context.scope != original.context.scope or order_context.run_id != context.run_id
                or order_context.business_time.clock_ref != original.context.business_time.clock_ref
                or order_context.business_time.offset > original.context.business_time.offset
                or order_context.operation_id == original.context.operation_id
                or any(pending_step.get(key) != planning_file[2]['steps'][0].get(key)
                    for key in ('action_id', 'host', 'operation_id', 'expected_kind', 'expected_choice',
                        'expected_work_authority_ref', 'expected_plan_ref', 'expected_tasks'))):
            raise ValueError('Connected order seed changes original planning intent, task, scope, clock or authority')
    if (context.run_id != supplier_context.run_id or context.scope != supplier_context.scope
            or seed.contractor['run_id'] != context.run_id or settings.action_id != 'CONTRACTOR-A07'
            or context.contract_ref.id != 'CONTRACTOR-A07' or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic'
            or settings.source_factory != 'integration.contractor_execution_fixture_sources:build_sources'
            or settings.source_version != 'configured-contractor-execution-fixture-sources.v1'
            or context.operation_id == supplier_context.operation_id
            or seed.mapping.sharing_authorized is not True):
        raise ValueError('Material chain requires explicitly independent same-run original offline inputs')
    operation = request.action_input['execution_context']
    if operation.get('kind') != 'ready':
        raise ValueError('Material chain requires its original ready Contractor material-input branch')
    rows = settings.source_settings['source_projection']['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    task = ContractorExecutionTaskView.model_validate(originals[Reference.model_validate(operation['task_ref']).key()])
    profile = ContractorExecutionProfileView.model_validate(originals[task.execution_profile_ref.key()])
    if (profile.choice not in {'execute', 'rebalance'} or not profile.materials or not profile.allocations
            or task.organization_id != seed.contractor['contractor_organization_id']
            or profile.task_ref != task.ref or profile.organization_id != task.organization_id):
        raise ValueError('Material chain requires original concrete Contractor material/resource intentions')
    expected_payload = {'choice': profile.choice, 'task_ref': task.ref.model_dump(mode='json'),
        'materials': [value.model_dump(mode='json') for value in profile.materials],
        'allocations': [value.model_dump(mode='json') for value in profile.allocations]}
    directory = Path(output_directory).resolve()
    supplier_directory = Path(supplier_file[2]['steps'][0]['output_directory']).resolve()
    supplier_journal = Path(supplier_file[4]['settings']['source_settings']['journal_path']).resolve()
    if logistics_seed is not None:
        pending_step = receiving_seed_file[2]['steps'][0]
        supplier_directory = Path(pending_step['output_directory']).resolve()
        supplier_journal = Path(pending_step['configuration']['settings']['source_settings']['journal_path']).resolve()
    contractor_journal = Path(settings.source_settings['journal_path']).resolve()
    contractor_directory = contractor_journal.parent
    roots = (directory, supplier_directory, contractor_directory)
    logistics_directory = None
    if logistics_seed is not None:
        logistics_stage = logistics_seed_input[2]['steps'][0] if quality_seed is not None else logistics_file[2]['steps'][0]
        logistics_directory = Path(logistics_stage['output_directory']).resolve()
        logistics_journal = Path(logistics_stage['configuration']['settings']['source_settings']['journal_path']).resolve()
        if logistics_journal != logistics_directory / 'journal.sqlite':
            raise ValueError('Connected logistics stage changes its original declared journal')
        roots += (logistics_directory,)
    quality_directory = None
    if quality_seed is not None:
        quality_stage = quality_seed_input[2]['steps'][0] if production_seed is not None else quality_file[2]['steps'][0]
        quality_directory = Path(quality_stage['output_directory']).resolve()
        quality_journal = Path(quality_stage['configuration']['settings']['source_settings']['journal_path']).resolve()
        if quality_journal != quality_directory / 'journal.sqlite':
            raise ValueError('Connected quality stage changes its original declared journal')
        roots += (quality_directory,)
    production_directory = None
    if production_seed is not None:
        production_stage = production_seed_input[2]['steps'][0] if planning_seed is not None else production_file[2]['steps'][0]
        production_directory = Path(production_stage['output_directory']).resolve()
        production_journal = Path(production_stage['configuration']['settings']['source_settings']['journal_path']).resolve()
        if production_journal != production_directory / 'journal.sqlite':
            raise ValueError('Connected production stage changes its original declared journal')
        roots += (production_directory,)
    planning_directory = None
    if planning_seed is not None:
        planning_stage = planning_seed_input[2]['steps'][0] if order_seed is not None else planning_file[2]['steps'][0]
        planning_directory = Path(planning_stage['output_directory']).resolve()
        planning_journal = Path(planning_stage['configuration']['settings']['source_settings']['journal_path']).resolve()
        if planning_journal != planning_directory / 'journal.sqlite':
            raise ValueError('Connected planning stage changes its declared original journal')
        roots += (planning_directory,)
    order_directory = None
    if order_seed is not None:
        order_directory = Path(order_file[2]['steps'][0]['output_directory']).resolve()
        order_journal = Path(order_file[4]['settings']['source_settings']['journal_path']).resolve()
        if order_journal != order_directory / 'journal.sqlite':
            raise ValueError('Connected order stage changes its declared original journal')
        roots += (order_directory,)
    if (supplier_journal != supplier_directory / 'journal.sqlite' or contractor_journal.name != 'journal.sqlite'
            or len(set(roots)) != len(roots)
            or any(first in second.parents for first in roots for second in roots if first != second)):
        raise ValueError('Material chain requires separate declared stage directories and exact journal paths')
    if execute and any(path.exists() for path in roots):
        raise FileExistsError('Material chain requires new stage directories; existing journals or attempts need explicit review')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-material-chain-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': context.run_id, 'mode': 'execute_offline' if execute else 'plan_only',
        'inputs': [{'path': str(seed_file[0]), 'sha256': seed_file[1]},
            {'path': str(supplier_file[0]), 'sha256': supplier_file[1]}],
        'stages': [{'action_id': 'SUPPLIER-A09', 'output_directory': str(supplier_directory)},
            {'kind': 'bind_original_result', 'output_directory': str(directory / 'binding')},
            {'action_id': 'CONTRACTOR-A07', 'output_directory': str(contractor_directory)}],
        'expected_contractor_payload': expected_payload, 'real_model_calls': 0,
        'limitations': ['Connected local synthetic receiving/mapping/material-input path only.',
            'No upstream production/logistics chain, native stock effect, actual inspection, consumption, MaterialUse, work quantity or cost proven.']}
    if logistics_seed is not None:
        plan['inputs'].extend({'path': str(item[0]), 'sha256': item[1]}
            for item in (logistics_seed_file, logistics_file, receiving_seed_file))
        plan['stages'] = [{'action_id': 'SUPPLIER-A08', 'output_directory': str(logistics_directory)},
            {'kind': 'bind_original_logistics', 'output_directory': str(directory / 'logistics-binding')},
            *plan['stages']]
        plan['limitations'] = ['Local synthetic original A08-to-A09-to-Contractor material-input path only.',
            'Upstream order/production/quality, actual native transport/stock, inspection, consumption, work quantity and cost remain unproven.']
    if quality_seed is not None:
        plan['inputs'].extend({'path': str(item[0]), 'sha256': item[1]}
            for item in (quality_seed_file, quality_file, logistics_seed_input))
        plan['stages'] = [{'action_id': 'SUPPLIER-A07', 'output_directory': str(quality_directory)},
            {'kind': 'bind_original_quality', 'output_directory': str(directory / 'quality-binding')}, *plan['stages']]
        plan['limitations'] = ['Local synthetic original A07-to-A08-to-A09-to-Contractor material-input path only.',
            'Upstream order/production and actual professional, defect closure, native release/transport/stock, work quantity and cost remain unproven.']
    if production_seed is not None:
        plan['inputs'].extend({'path': str(item[0]), 'sha256': item[1]}
            for item in (production_seed_file, production_file, quality_seed_input))
        plan['stages'] = [{'action_id': 'SUPPLIER-A06', 'output_directory': str(production_directory)},
            {'kind': 'bind_original_production', 'output_directory': str(directory / 'production-binding')}, *plan['stages']]
        plan['limitations'] = ['Local synthetic original A06-to-A07-to-A08-to-A09-to-Contractor material-input path only.',
            'Upstream order/task/planning, actual native production/consumption, professional confirmation, stock, work quantity and cost remain unproven.']
    if planning_seed is not None:
        plan['inputs'].extend({'path': str(item[0]), 'sha256': item[1]}
            for item in (planning_seed_file, planning_file, production_seed_input))
        plan['stages'] = [{'action_id': 'SUPPLIER-A05', 'output_directory': str(planning_directory)},
            {'kind': 'bind_original_planning', 'output_directory': str(directory / 'planning-binding')}, *plan['stages']]
        plan['limitations'] = ['Local synthetic original A05-to-A06-to-A07-to-A08-to-A09-to-Contractor material-input path only.',
            'Upstream A04/effective order, actual native task formation/production/consumption, professional confirmation, stock, work quantity and cost remain unproven.']
    if order_seed is not None:
        plan['inputs'].extend({'path': str(item[0]), 'sha256': item[1]}
            for item in (order_seed_file, order_file, planning_seed_input))
        plan['stages'] = [{'action_id': 'SUPPLIER-A04', 'output_directory': str(order_directory)},
            {'kind': 'bind_original_order', 'output_directory': str(directory / 'order-binding')}, *plan['stages']]
        plan['limitations'] = ['Local synthetic original A04-to-A05-to-A06-to-A07-to-A08-to-A09-to-Contractor material-input path only.',
            'Effective order/task formation and all professional/native observations are independent synthetic declarations; actual effects, consumption, work quantity and cost remain unproven.']
    atomic_json(directory / 'plan.json', plan)
    atomic_json(directory / 'seed-input.json', seed_file[2])
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-material-chain-attempt.v1', 'status': 'started',
        'stage': 'supplier_order' if order_seed is not None else 'supplier_planning' if planning_seed is not None else 'supplier_production' if production_seed is not None else 'supplier_quality' if quality_seed is not None else
            ('supplier_logistics' if logistics_seed is not None else 'supplier_receiving'), 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)

    derived_inputs = []
    stage_results = []

    def unchanged():
        if any(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']
                for row in [*plan['inputs'], *derived_inputs]):
            raise ValueError('Material chain original input changed; no replay')

    try:
        unchanged()
        active_supplier_path, active_seed_path = supplier_file[0], seed_file[0]
        active_logistics_path = logistics_file[0] if logistics_file is not None else None
        active_logistics_seed_path = logistics_seed_file[0] if logistics_seed_file is not None else None
        active_quality_path = quality_file[0] if quality_file is not None else None
        active_quality_seed_path = quality_seed_file[0] if quality_seed_file is not None else None
        active_production_path = production_file[0] if production_file is not None else None
        active_production_seed_path = production_seed_file[0] if production_seed_file is not None else None
        active_planning_path = planning_file[0] if planning_file is not None else None
        active_planning_seed_path = planning_seed_file[0] if planning_seed_file is not None else None
        if order_seed is not None:
            run_v4_supplier_order_offline(case_path=order_file[0], output_directory=order_directory, execute=True)
            order_result = _read(order_directory / 'supplier' / 'result.json')
            stage_results.append(order_result)
            derived_inputs.append({'path': str(order_result[0]), 'sha256': order_result[1]})
            attempt = {**attempt, 'stage': 'bind_original_order'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            order_binding = bind_v4_order_registration(seed_path=order_seed_file[0],
                order_result_path=order_result[0], output_directory=directory / 'order-binding')
            active_planning_path = Path(order_binding['planning_input_path']).resolve()
            connected_planning = _read(active_planning_path)
            linked_planning_seed = planning_seed.model_dump(mode='json')
            linked_planning_seed['planning_input_path'] = str(active_planning_path)
            linked_planning_seed['planning_input_sha256'] = connected_planning[1]
            linked_planning_seed['assumptions'].append('Explicitly derived from original planning seed and original A04 effective-order binding; use only saved assembled A05 configuration.')
            PlanningConnectionSeed.model_validate(linked_planning_seed)
            active_planning_seed_path = directory / 'connected-planning-seed.json'
            atomic_json(active_planning_seed_path, linked_planning_seed)
            connected_planning_seed = _read(active_planning_seed_path)
            derived_inputs.extend({'path': str(item[0]), 'sha256': item[1]}
                for item in (connected_planning, connected_planning_seed))
            attempt = {**attempt, 'stage': 'supplier_planning'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if planning_directory.exists():
                raise FileExistsError('Connected planning stage appeared during order binding; no replay')
        if planning_seed is not None:
            run_v4_supplier_planning_offline(case_path=active_planning_path, output_directory=planning_directory, execute=True)
            planning_result = _read(planning_directory / 'supplier' / 'result.json')
            stage_results.append(planning_result)
            derived_inputs.append({'path': str(planning_result[0]), 'sha256': planning_result[1]})
            attempt = {**attempt, 'stage': 'bind_original_planning'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            planning_binding = bind_v4_planning_registration(seed_path=active_planning_seed_path,
                planning_result_path=planning_result[0], output_directory=directory / 'planning-binding')
            active_production_path = Path(planning_binding['production_input_path']).resolve()
            connected_production = _read(active_production_path)
            linked_production_seed = production_seed.model_dump(mode='json')
            linked_production_seed['production_input_path'] = str(active_production_path)
            linked_production_seed['production_input_sha256'] = connected_production[1]
            linked_production_seed['assumptions'].append('Explicitly derived from original production seed and original A05 task-formation binding; use only saved assembled A06 configuration.')
            ProductionConnectionSeed.model_validate(linked_production_seed)
            active_production_seed_path = directory / 'connected-production-seed.json'
            atomic_json(active_production_seed_path, linked_production_seed)
            connected_production_seed = _read(active_production_seed_path)
            derived_inputs.extend({'path': str(item[0]), 'sha256': item[1]}
                for item in (connected_production, connected_production_seed))
            attempt = {**attempt, 'stage': 'supplier_production'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if production_directory.exists():
                raise FileExistsError('Connected production stage appeared during planning binding; no replay')
        if production_seed is not None:
            run_v4_supplier_production_offline(case_path=active_production_path, output_directory=production_directory, execute=True)
            production_result = _read(production_directory / 'supplier' / 'result.json')
            stage_results.append(production_result)
            derived_inputs.append({'path': str(production_result[0]), 'sha256': production_result[1]})
            attempt = {**attempt, 'stage': 'bind_original_production'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            production_binding = bind_v4_production_registration(seed_path=active_production_seed_path,
                production_result_path=production_result[0], output_directory=directory / 'production-binding')
            active_quality_path = Path(production_binding['quality_input_path']).resolve()
            connected_quality = _read(active_quality_path)
            linked_quality_seed = quality_seed.model_dump(mode='json')
            linked_quality_seed['quality_input_path'] = str(active_quality_path)
            linked_quality_seed['quality_input_sha256'] = connected_quality[1]
            linked_quality_seed['assumptions'].append('Explicitly derived from original quality seed and original A06 production binding; use only the saved assembled A07 configuration.')
            QualityConnectionSeed.model_validate(linked_quality_seed)
            active_quality_seed_path = directory / 'connected-quality-seed.json'
            atomic_json(active_quality_seed_path, linked_quality_seed)
            connected_quality_seed = _read(active_quality_seed_path)
            derived_inputs.extend({'path': str(item[0]), 'sha256': item[1]}
                for item in (connected_quality, connected_quality_seed))
            attempt = {**attempt, 'stage': 'supplier_quality'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if quality_directory.exists():
                raise FileExistsError('Connected quality stage appeared during production binding; no replay')
        if quality_seed is not None:
            run_v4_supplier_quality_offline(case_path=active_quality_path, output_directory=quality_directory, execute=True)
            quality_result = _read(quality_directory / 'supplier' / 'result.json')
            stage_results.append(quality_result)
            derived_inputs.append({'path': str(quality_result[0]), 'sha256': quality_result[1]})
            attempt = {**attempt, 'stage': 'bind_original_quality'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            quality_binding = bind_v4_quality_registration(seed_path=active_quality_seed_path,
                quality_result_path=quality_result[0], output_directory=directory / 'quality-binding')
            active_logistics_path = Path(quality_binding['logistics_input_path']).resolve()
            connected_logistics = _read(active_logistics_path)
            linked_logistics_seed = logistics_seed.model_dump(mode='json')
            linked_logistics_seed['logistics_input_path'] = str(active_logistics_path)
            linked_logistics_seed['logistics_input_sha256'] = connected_logistics[1]
            linked_logistics_seed['assumptions'].append('Explicitly derived from original logistics seed and original A07 quality binding; use only the saved assembled A08 configuration.')
            LogisticsConnectionSeed.model_validate(linked_logistics_seed)
            active_logistics_seed_path = directory / 'connected-logistics-seed.json'
            atomic_json(active_logistics_seed_path, linked_logistics_seed)
            connected_logistics_seed = _read(active_logistics_seed_path)
            derived_inputs.extend({'path': str(item[0]), 'sha256': item[1]}
                for item in (connected_logistics, connected_logistics_seed))
            attempt = {**attempt, 'stage': 'supplier_logistics'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if logistics_directory.exists():
                raise FileExistsError('Connected logistics stage appeared during quality binding; no replay')
        if logistics_seed is not None:
            run_v4_supplier_logistics_offline(case_path=active_logistics_path, output_directory=logistics_directory, execute=True)
            logistics_result = _read(logistics_directory / 'supplier' / 'result.json')
            stage_results.append(logistics_result)
            derived_inputs.append({'path': str(logistics_result[0]), 'sha256': logistics_result[1]})
            attempt = {**attempt, 'stage': 'bind_original_logistics'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            binding = bind_v4_logistics_registration(seed_path=active_logistics_seed_path,
                logistics_result_path=logistics_result[0], output_directory=directory / 'logistics-binding')
            active_supplier_path = Path(binding['receiving_input_path']).resolve()
            connected_supplier = _read(active_supplier_path)
            linked_seed = seed.model_dump(mode='json')
            linked_seed['supplier_input_path'] = str(active_supplier_path)
            linked_seed['supplier_input_sha256'] = connected_supplier[1]
            linked_seed['assumptions'].append('Explicitly derived from the original material seed and original A08 logistics binding; source input is the saved assembled A09 configuration.')
            MaterialConnectionSeed.model_validate(linked_seed)
            active_seed_path = directory / 'connected-material-seed.json'
            atomic_json(active_seed_path, linked_seed)
            connected_seed = _read(active_seed_path)
            derived_inputs.extend({'path': str(item[0]), 'sha256': item[1]} for item in (connected_supplier, connected_seed))
            attempt = {**attempt, 'stage': 'supplier_receiving'}
            atomic_json(directory / 'attempt.json', attempt)
            unchanged()
            if supplier_directory.exists():
                raise FileExistsError('Connected receiving stage appeared during binding; no replay')
        supplier = run_v4_supplier_receiving_offline(case_path=active_supplier_path, output_directory=supplier_directory, execute=True)
        supplier_result_path = supplier_directory / 'supplier' / 'result.json'
        supplier_result = _read(supplier_result_path)
        stage_results.append(supplier_result)
        derived_inputs.append({'path': str(supplier_result[0]), 'sha256': supplier_result[1]})
        attempt = {**attempt, 'stage': 'bind_original_result'}
        atomic_json(directory / 'attempt.json', attempt)
        unchanged()
        bind_v4_material_registration(seed_path=active_seed_path, supplier_result_path=supplier_result_path,
            output_directory=directory / 'binding')
        material_input_path = directory / 'binding' / 'connection' / 'material-input.json'
        attempt = {**attempt, 'stage': 'contractor_material_inputs'}
        atomic_json(directory / 'attempt.json', attempt)
        unchanged()
        if contractor_directory.exists():
            raise FileExistsError('Contractor stage appeared during binding; no journal replay')
        contractor = run_v4_contractor_material(input_path=material_input_path,
            output_directory=contractor_directory, execute=True)
        contractor_result = _read(contractor_directory / 'contractor' / 'result.json')
        stage_results.append(contractor_result)
        output = contractor_result[2]
        evidence = output['execution_evidence']
        result, durable_task = output['result'], evidence['task']
        if (output['source_mode'] != 'fixture' or output['macro_execution'] != 'not_performed'
                or evidence['model_host'] is not None or result['kind'] != 'completed'
                or any(result['payload'].get(key) != value for key, value in expected_payload.items())
                or durable_task['state'] != 'output_formed' or durable_task['output'] != result
                or durable_task['output_sha256'] != task_digest(result)
                or durable_task['submission'] is not None or durable_task['receipt'] is not None
                or contractor['received_material_input']['source_task_sha256'] != TaskIdentity(**supplier['identity']).key
                or contractor['received_material_input']['source_record_sha256'] != supplier['record_sha256']):
            raise ValueError('Material chain does not preserve connected original provenance and exact material-input result')
        unchanged()
        if hashlib.sha256(supplier_result_path.read_bytes()).hexdigest() != supplier_result[1]:
            raise ValueError('Material chain original Supplier result changed during connection')
        summary = {**plan, 'mode': 'executed_offline', 'status': 'local_path_completed',
            'supplier_identity': deepcopy(supplier['identity']), 'contractor_identity': deepcopy(contractor['identity']),
            'received_material_input': deepcopy(contractor['received_material_input']), 'result': deepcopy(result),
            'derived_inputs': deepcopy(derived_inputs),
            'outputs': [{'path': str(item[0]), 'sha256': item[1]} for item in stage_results]}
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
    parser.add_argument('--logistics-seed', type=Path)
    parser.add_argument('--quality-seed', type=Path)
    parser.add_argument('--production-seed', type=Path)
    parser.add_argument('--planning-seed', type=Path)
    parser.add_argument('--order-seed', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_material_chain_offline(seed_path=args.seed, output_directory=args.output,
        execute=args.execute, logistics_seed_path=args.logistics_seed, quality_seed_path=args.quality_seed,
        production_seed_path=args.production_seed, planning_seed_path=args.planning_seed,
        order_seed_path=args.order_seed)['mode'])


if __name__ == '__main__':
    main()
