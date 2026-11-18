"""Relate original Supplier A09 receipt evidence to actual Contractor A07 stock."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

from integration.supplier_receiving_results import SavedSupplierReceiving
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_execution_objects import (
    ContractorExecutionTaskView, ContractorExecutionProfileView,
    ContractorInventoryView, ContractorReceivedMaterialView,
)
from src.actions.contracts.contractor_readiness_objects import ContractorReadyInputView
from src.actions.contracts.supplier_receiving_objects import (
    SupplierCustomerReceiptView, SupplierGoodsUseReleaseView, SupplierReceiptComponentView,
    SupplierReceiptInspectionView, SupplierReceivingPartyView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.actions.roles.supplier_receiving import _check_receipt_arrival_capacity
from src.organization.registry import scope_covers


def read_received_contractor_materials(prepared, *, source_task_sha256, material_basis_refs,
        read_receiving, validate_reception):
    """Read the explicitly selected Supplier result through its authorized owner."""
    if not callable(read_receiving) or not callable(validate_reception):
        raise TaskConflict('Contractor materials require original Supplier journal reader and receiver validator')
    try:
        saved = read_receiving(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedSupplierReceiving) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Material reader substituted the explicitly selected original Supplier task')
        validate_received_contractor_materials(saved, prepared=prepared, material_basis_refs=material_basis_refs,
            validate_reception=validate_reception)
        return {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'material_basis_refs': [Reference.model_validate(r).model_dump(mode='json') for r in material_basis_refs],
            'material_basis_sha256': task_digest([prepared.reading.resolve(Reference.model_validate(ref)).model_dump(mode='json')
                for ref in material_basis_refs]),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
            raise TaskConflict('Supplier material reader changed original Contractor input or sources')


def validate_received_contractor_materials(saved, *, prepared, material_basis_refs, validate_reception):
    """Validate source lineage only; create no receipt, allocation or usable stock.

    The receiver independently confirms actual core stock, full source mapping,
    inspection/release authority, use compatibility and privacy. Supplier's
    response cannot grant the contractor a construction or material-use right.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedSupplierReceiving) or prepared.ACTION_ID != 'CONTRACTOR-A07'
            or saved.identity.action_id != 'SUPPLIER-A09' or saved.identity.role != 'Supplier'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'SUPPLIER-A09' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Material reception requires original saved Supplier response and independent receiver validation')
    reading.check_method_context(context, 'CONTRACTOR-A07')
    operation = prepared.action_input.execution_context
    if not hasattr(operation, 'inventory_refs'):
        raise TaskConflict('Received material handoff requires the original current inventory execution branch')
    refs = [Reference.model_validate(ref) for ref in material_basis_refs]
    if not refs or len({r.key() for r in refs}) != len(refs):
        raise TaskConflict('Received material mapping requires explicit distinct original basis references')
    before = task_digest(reading.evidence())
    if before != prepared.reading_sha256:
        raise TaskConflict('Received material mapping changed original Contractor source snapshot')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'SUPPLIER-A09',
            'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
            'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Material mapping substitutes the original Supplier audit')
    originals = {}
    for row in saved.source_reading:
        key = Reference.model_validate(row['ref']).key()
        if key in originals:
            raise TaskConflict('Material mapping repeats an original Supplier source')
        originals[key] = row['projection']

    def original(ref, schema):
        row = schema.model_validate(originals[ref.key()])
        if row.ref != ref:
            raise TaskConflict('Material mapping substitutes the original source version')
        return row

    def amount(measured, unit):
        if measured.unit != unit:
            raise TaskConflict('Received material quantities require original units without conversion')
        value = Fraction(Decimal(measured.value))
        if value < 0:
            raise TaskConflict('Received material quantity cannot be negative')
        return value

    mapped, component_totals, release_totals, native_events, release_demands = set(), {}, {}, {}, {}
    try:
        task = reading.resolve(operation.task_ref)
        if (not isinstance(task, ContractorExecutionTaskView) or task.ref != operation.task_ref
                or task.organization_id != reading.organization_id or task.scope != context.scope):
            raise TaskConflict('Material mapping requires the original current Contractor execution task')
        profile = reading.resolve(task.execution_profile_ref)
        if (not isinstance(profile, ContractorExecutionProfileView) or profile.ref != task.execution_profile_ref
                or profile.task_ref != task.ref or profile.organization_id != reading.organization_id
                or profile.scope != context.scope or profile.authority_ref not in context.authorization_refs
                or profile.choice not in {'execute', 'rebalance'}):
            raise TaskConflict('Material mapping requires the original authorized material input profile')
        # Selected mappings must cover the actual proposed inputs. Spare stock
        # can remain visible without being used or acquiring a Supplier lineage.
        inventory_by_batch = {}
        inventory_refs = set()
        for inventory_ref in operation.inventory_refs:
            inventory = reading.resolve(inventory_ref)
            if (not isinstance(inventory, ContractorInventoryView) or inventory.ref != inventory_ref
                    or inventory_ref.key() in inventory_refs
                    or inventory.batch_ref.key() in inventory_by_batch):
                raise TaskConflict('Material inputs require distinct original batch inventory projections')
            inventory_refs.add(inventory_ref.key())
            inventory_by_batch[inventory.batch_ref.key()] = inventory
        required_inventory_refs = set()
        for material in profile.materials:
            inventory = inventory_by_batch.get(material.batch_ref.key())
            if (material.task_ref != task.ref or inventory is None
                    or material.allocation_ref not in inventory.allocation_refs):
                raise TaskConflict('Proposed material input lacks its original task inventory and allocation')
            required_inventory_refs.add(inventory.ref.key())
        for ref in refs:
            basis = reading.resolve(ref)
            if (not isinstance(basis, ContractorReceivedMaterialView) or basis.ref != ref
                    or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                    or basis.supplier_organization_id != saved.identity.organization_id
                    or basis.receiving_task_sha256 != saved.identity.key
                    or basis.receiving_record_sha256 != saved.record_sha256
                    or basis.receiving_result_sha256 != result_sha
                    or basis.receiving_source_reading_sha256 != saved.source_reading_sha256
                    or not scope_covers(context.scope, basis.scope)
                    or not basis.effective_window.contains(context.business_time)
                    or basis.inventory_ref not in operation.inventory_refs or basis.inventory_ref.key() in mapped):
                raise TaskConflict('Material basis changes original Supplier, receiver, scope, result or inventory')
            receipt = original(basis.receipt_ref, SupplierCustomerReceiptView)
            component = original(basis.component_ref, SupplierReceiptComponentView)
            party = original(receipt.receiving_party_ref, SupplierReceivingPartyView)
            if (receipt.status != 'recorded' or receipt.ref not in saved.action_input.receipt_refs
                    or receipt.shipment_ref != saved.action_input.shipment_ref
                    or component.ref not in receipt.component_refs or component.receipt_ref != receipt.ref
                    or component.shipment_ref != receipt.shipment_ref or component.physical_slice_key != basis.physical_slice_key
                    or party.organization_id != reading.organization_id or party.ref != receipt.receiving_party_ref
                    or not basis.use_release_refs or len({r.key() for r in basis.use_release_refs}) != len(basis.use_release_refs)
                    or not set(basis.use_release_refs) <= set(component.use_release_refs)):
                raise TaskConflict('Material basis lacks original recorded receipt, physical component or independent use release')
            inventory = reading.resolve(basis.inventory_ref)
            batch = reading.resolve(basis.batch_ref)
            now = context.business_time
            if (not isinstance(inventory, ContractorInventoryView) or not isinstance(batch, ContractorReadyInputView)
                    or inventory.organization_id != reading.organization_id or batch.organization_id != reading.organization_id
                    or inventory.batch_ref != batch.ref or inventory.product_ref != component.product_ref
                    or inventory.as_of != now or batch.as_of != now or inventory.coverage != 'complete'
                    or not scope_covers(context.scope, inventory.scope) or not scope_covers(context.scope, batch.scope)
                    or not inventory.effective_window.contains(now) or not batch.effective_window.contains(now)
                    or task_digest(inventory.model_dump(mode='json')) != basis.inventory_sha256
                    or task_digest(batch.model_dump(mode='json')) != basis.batch_sha256
                    or inventory.usable.state != 'known' or batch.actual_available.state != 'known'
                    or batch.accepted.state != 'known' or batch.accepted.value is not True):
                raise TaskConflict('Material mapping substitutes actual same-version accepted batch or current usable inventory')
            unit = component.usable_quantity.unit
            quantity = amount(inventory.usable.value, unit)
            if quantity > amount(batch.actual_available.value, unit):
                raise TaskConflict('Mapped usable inventory exceeds actual available receiver batch')
            released = Fraction()
            for release_ref in basis.use_release_refs:
                release = original(release_ref, SupplierGoodsUseReleaseView)
                inspection = original(release.inspection_ref, SupplierReceiptInspectionView)
                if (release.component_ref != component.ref or release.shipment_ref != receipt.shipment_ref
                        or release.receiving_party_ref != party.ref or release.permitted.state != 'known'
                        or release.permitted.value is not True or basis.use_code not in release.use_codes
                        or inspection.ref not in component.inspection_refs or component.ref not in inspection.component_refs
                        or inspection.shipment_ref != receipt.shipment_ref or inspection.status != 'ok'
                        or inspection.passed.state != 'known' or inspection.passed.value is not True
                        or basis.use_code not in inspection.use_codes):
                    raise TaskConflict('Material mapping lacks actual independent inspection and original use permission')
                key = (release.core_event_id, component.ref.key())
                if key in native_events and native_events[key] != release.ref:
                    raise TaskConflict('Material mapping duplicates a physical use release event')
                native_events[key] = release.ref
                released += amount(release.quantity, unit)
                release_totals[release.ref.key()] = release
            if quantity > released:
                raise TaskConflict('Mapped inventory exceeds its explicitly referenced use releases')
            key = component.ref.key()
            prior = component_totals.get(key, (Fraction(), set(), unit))
            if prior[2] != unit:
                raise TaskConflict('Material mapping changes original component units')
            component_totals[key] = (prior[0] + quantity, prior[1] | {r.key() for r in basis.use_release_refs}, unit)
            release_demands.setdefault(key, []).append(({r.key() for r in basis.use_release_refs}, quantity))
            times = [saved.context.business_time, basis.received_at, basis.available_at, now]
            if (any(p.clock_ref != now.clock_ref for p in times)
                    or any(a.offset > b.offset for a, b in zip(times, times[1:]))
                    or inventory.available_at.clock_ref != now.clock_ref or inventory.available_at.offset > now.offset
                    or batch.available_at.clock_ref != now.clock_ref or batch.available_at.offset > now.offset):
                raise TaskConflict('Material mapping changes original response/reception/stock chronology')
            for evidence_ref, expected in [(basis.native_evidence_ref, basis.native_record_sha256),
                    (inventory.usable.value.basis_ref, None), (batch.actual_available.value.basis_ref, None)]:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.basis_kind != 'observed'
                        or expected is not None and evidence.content_hash != expected
                        or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                        or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
                    raise TaskConflict('Actual received stock requires original observed native and quantity evidence')
            if validate_reception(saved=deepcopy(saved), basis=basis.model_copy(deep=True),
                    receipt=receipt.model_copy(deep=True), component=component.model_copy(deep=True),
                    inventory=inventory.model_copy(deep=True), batch=batch.model_copy(deep=True),
                    context=context.model_copy(deep=True)) is not True:
                raise TaskConflict('Receiver did not confirm actual core inventory, full mapping, use authority and privacy')
            mapped.add(basis.inventory_ref.key())
        if not required_inventory_refs <= mapped:
            raise TaskConflict('Supplier material mappings do not cover all proposed Contractor material inputs')
        for key, (total, release_keys, unit) in component_totals.items():
            component = original(Reference(kind=key[0], id=key[1], version=key[2]), SupplierReceiptComponentView)
            if (total > amount(component.usable_quantity, unit)
                    or total > sum((amount(release_totals[k].quantity, unit) for k in release_keys), Fraction())):
                raise TaskConflict('Multiple inventory mappings reuse the same original receipt or released quantity')
            # Reuse exact linked-source feasibility for overlapping release sets.
            # Each mapping can use only its declared releases, counted once.
            try:
                _check_receipt_arrival_capacity({k: amount(release_totals[k].quantity, unit)
                    for k in release_keys}, release_demands[key])
            except ValueError as exc:
                raise TaskConflict('Inventory mappings exceed their referenced independent use releases') from exc
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != before
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Material reception changed original execution inputs or sources')
