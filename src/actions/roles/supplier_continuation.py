"""SUPPLIER-A12 proposes transitions without erasing original goods or debts."""
from decimal import Decimal

from src.actions.contracts.common import Known
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
from src.actions.roles.commercial_continuation import transition_commercial_business
from src.actions.roles.owner import _needs


def continue_supplier_business(context, action_input, reading):
    types = supplier_continuation_types()
    rights = []

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def true(value):
        return isinstance(value, Known) and value.value is True

    def check(profile, state, basis, materials, read, author, evidence, clock, wait):
        org, now = reading.organization_id, context.business_time
        for field in ('work_in_progress_refs', 'shipment_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(state, field)):
                _needs('complete_original_supplier_' + field)
        plan = read(basis.material_plan_ref, types['MaterialDispositionPlan'], evidence_at_field='authored_at')
        if not keys(state.production_line_commitment_refs) <= keys(state.commitment_refs):
            raise ValueError('Supplier continuation replaces original production-line commitments')
        items = {item.position_ref.key(): item for item in plan.items}
        physical = {row.physical_position_key for row in materials.values()}
        goods = list(materials.values())
        rights.extend(row.right_ref for row in goods)
        for ref in [*state.work_in_progress_refs, *state.shipment_refs]:
            row = read(ref, types[ref.kind], linked=True)
            clock(row.as_of)
            if (row.organization_id != org or row.custodian_organization_id != org
                    or row.coverage != 'complete' or row.as_of != now):
                _needs('current_complete_original_supplier_goods', [ref])
            if row.physical_position_key in physical:
                raise ValueError('Supplier continuation counts the same physical goods twice')
            physical.add(row.physical_position_key)
            item = items[ref.key()]
            right = read(item.right_ref, types['AssetRight'], linked=True, evidence_at_field='authored_at')
            author(right)
            if (row.right_ref != right.ref or right.position_ref != row.ref
                    or right.owner_organization_id != row.owner_organization_id
                    or right.custodian_organization_id != org
                    or right.author_organization_id != row.owner_organization_id
                    or not true(right.permitted) or item.choice not in right.permitted_choices
                    or item.recipient_organization_id not in right.allowed_recipient_organization_ids):
                _needs('actual_owner_supplier_goods_disposition_right', [ref])
            if profile.choice in {'protect', 'suspend'} and item.choice not in {'preserve','retain_custody','query_original'}:
                raise ValueError('Supplier protection/suspension cannot dispose of goods')
            unknown = row.status in {'unknown', 'submitted_unknown'}
            query_ref = ref
            if ref.kind == 'ProductionPosition':
                execution = read(row.execution_ref, types['ProductionExecution'], historic=True, linked=True,
                    evidence_at_field='recorded_at')
                if execution.organization_id != org or execution.run_id != context.run_id or execution.task_ref != row.task_ref:
                    raise ValueError('Supplier continuation substitutes original production execution')
                if execution.status == 'recorded' and (execution.query_status != 'present'
                        or execution.core_event_id is None or execution.recorded_at is None):
                    _needs('original_actual_recorded_supplier_production', [execution.ref])
                unknown = unknown or execution.status == 'submitted_unknown'
                query_ref = execution.ref
                if row.status == 'completed' and (execution.status != 'recorded' or execution.core_event_id is None):
                    raise ValueError('Supplier continuation invents completed production')
            elif row.run_id != context.run_id:
                raise ValueError('Supplier continuation substitutes original shipment run')
            if unknown:
                if item.choice != 'query_original':
                    _needs('query_original_supplier_goods_disposition', [query_ref])
                if profile.choice not in {'protect','suspend','record_lesson'} or profile.release_candidate_refs:
                    return wait(query_ref, 'query_original_late_supplier_execution')
            goods.append(row)
            rights.append(right.ref)
        unique_refs(rights)
        if profile.choice == 'resume':
            if state.work_in_progress_refs and not state.production_line_commitment_refs:
                _needs('explicit_original_supplier_production_line_commitments')
            if not keys(state.production_line_commitment_refs) <= keys(profile.retain_resource_refs):
                raise ValueError('Supplier resume cannot release the production line it requires')
            for ref in state.production_line_commitment_refs:
                line = read(ref, types['ResourceCommitment'], linked=True)
                if line.status != 'held':
                    return wait(ref, 'supplier_resume_original_production_line_unavailable')
            # Family coverage alone cannot substitute a production-line check.
            required = {'production':keys([*state.work_in_progress_refs,*state.production_line_commitment_refs]), 'logistics':keys(state.shipment_refs),
                        'materials':keys(state.material_refs), 'resources':keys(state.commitment_refs)}
            covered = {family:set() for family in required}
            for ref in profile.readiness_refs:
                verification = read(ref, types['Verification'])
                if verification.family in covered:
                    covered[verification.family].update(keys([source.source_ref for source in verification.source_digests]))
            if any(not refs <= covered[family] for family, refs in required.items()):
                _needs('current_supplier_material_production_line_and_logistics_verification')
        if profile.choice == 'close_cleared_scope':
            if state.obligation_refs or profile.release_candidate_refs:
                _needs('actually_cleared_specific_supplier_scope')
            for ref in state.commitment_refs:
                commitment = read(ref, types['ResourceCommitment'], linked=True)
                if commitment.status not in {'released','consumed'}:
                    return wait(ref, 'supplier_scope_has_actual_occupied_resources')
            for row in goods:
                if not isinstance(row.total_remaining, Known) or Decimal(row.total_remaining.value.value) != 0:
                    _needs('actually_cleared_original_supplier_goods', [row.ref])
                evidence([row.total_remaining.value.basis_ref])
            for ref in state.responsibility_refs:
                duty = read(ref, types['ContinuingResponsibility'], linked=True)
                if duty.status != 'complete': _needs('supplier_quality_and_dispute_duties_cleared', [ref])
            for ref in state.work_record_refs:
                work = read(ref, types['OriginalWorkRecord'], historic=True, linked=True)
                if (work.status != 'completed' or not isinstance(work.remaining_quantity, Known)
                        or Decimal(work.remaining_quantity.value.value) != 0):
                    _needs('supplier_original_work_actually_cleared', [ref])
                evidence([work.remaining_quantity.value.basis_ref], historic=True)
            for ref in basis.protection_task_refs:
                task = read(ref, types['ProtectionTask'])
                if task.status != 'complete': _needs('supplier_protection_duties_cleared', [ref])

    def fields(profile, state, output):
        if profile.choice != 'record_lesson':
            output['retained_obligation_refs'] = output.pop('remaining_obligation_refs')
            output.pop('retain_resource_refs')
            output.pop('transfer_evidence_refs', None)
            output['disposition_basis_refs'] = rights
        return output

    return transition_commercial_business(context, action_input, reading, action_id='SUPPLIER-A12',
        continuation_types=types, commitment_input='commitment_refs', material_input='inventory_refs',
        check_extra=check, result_fields=fields,
        readiness_families={'resources','materials','production','logistics','funding','safety'},
        extra_source_fields=('work_in_progress_refs','shipment_refs'),
        extra_transfer_fields=('work_in_progress_refs','shipment_refs'),
        extra_material_fields=('work_in_progress_refs','shipment_refs'))
