"""Synthetic A06 sources from saved A05 and independent native task formation."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_planning_fixture_sources import SupplierPlanningFixtureSettings, build_sources as build_planning_sources
from integration.supplier_order_planning_fixture_sources import (
    SupplierOrderPlanningFixtureSettings, build_sources as build_linked_planning_sources,
)
from integration.supplier_planning_handoff import SupplierPlanningHandoffBasisView, SupplierTaskFormationRecordView
from integration.supplier_planning_results import SupplierPlanningResultWorker
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings, build_sources as build_production_sources
from src.actions.contracts.common import EvidenceRecord, Known, Reference, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualInventoryAllocationView, SupplierActualMaterialView, SupplierExecutionTaskView,
    SupplierExecutionProfileView, SupplierProductionMethodView, SupplierProductionReleaseView,
    SupplierExecutionOrderView, SupplierGoodsReceiptRuleView,
)
from src.actions.contracts.supplier_planning_objects import SupplierInventoryAllocationView, SupplierPlanningMethodView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.pricing import decimal_fraction


class SupplierPlanningHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierPlanningFixtureSettings | SupplierOrderPlanningFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredPlanningMaterialLineage(StrictRecord):
    """Native correspondence preserves original planning stock identity and quantity."""
    planning_allocation_ref: ref_type('InventoryAllocation')
    planning_batch_ref: ref_type('ProductBatch')
    material: SupplierActualMaterialView
    allocation: SupplierActualInventoryAllocationView


class DeclaredFormedProductionTask(StrictRecord):
    task: SupplierExecutionTaskView
    planning_method_ref: ref_type('SupplyMethod')
    output_product_ref: ref_type('ProductSpecification')
    method: SupplierProductionMethodView
    release: SupplierProductionReleaseView
    material_lineage: list[DeclaredPlanningMaterialLineage]


class DeclaredFormedPurchaseTask(StrictRecord):
    """Independent upstream order linkage; a plan never creates received stock."""
    task: SupplierExecutionTaskView
    planning_method_ref: ref_type('SupplyMethod')
    output_product_ref: ref_type('ProductSpecification')
    upstream_order: SupplierExecutionOrderView
    order_line_ref: ref_type('OrderLine')
    receipt_rule: SupplierGoodsReceiptRuleView


FormedPlanningTask = DeclaredFormedProductionTask | DeclaredFormedPurchaseTask


class DeclaredPlanningProductionRegistration(StrictRecord):
    schema_version: Literal['supplier-planning-production-registration.v1']
    registration_id: TextId
    basis: SupplierPlanningHandoffBasisView
    formation_record: SupplierTaskFormationRecordView
    tasks: Annotated[list[FormedPlanningTask], Field(min_length=1)]
    recorded_at: TimePoint
    producer: Literal['core']
    native_record: dict
    current_state: Literal['recorded', 'withdrawn', 'superseded']


class SupplierPlanningProductionFixtureSettings(SupplierProductionFixtureSettings):
    planning_history: SupplierPlanningHistorySettings
    registration: DeclaredPlanningProductionRegistration


def check_planning_connection_selection(*, request, settings, source):
    """Check explicit host selection before executing a connected A06 input."""
    selection = settings.planning_inputs
    if (settings.source_factory != 'integration.supplier_planning_production_fixture_sources:build_sources'
            or settings.source_version != _PlanningProductionReception.VERSION
            or selection is None or set(selection.selections) != {request.context.operation_id}):
        raise ValueError('Connected production requires its explicit original planning selection and factory')
    selected = selection.selections[request.context.operation_id]
    if (selected.planning_identity.as_dict() != source.planning_history.identity.as_dict()
            or selected.basis_ref.key() != source.registration.basis.ref.key()):
        raise ValueError('Connected production changes selected original A05 identity or relation')


def check_planning_connection_provenance(*, request, source, evidence):
    """Retain exact original planning handoff in a saved connected A06 output."""
    basis, formation = source.registration.basis, source.registration.formation_record
    provenance = evidence.get('planning_input')
    expected = {'kind': 'prepared', 'task_ref': request.action_input['task_ref'],
        'planning_identity': source.planning_history.identity.as_dict(),
        'planning_record_sha256': basis.planning_record_sha256,
        'planning_result_sha256': basis.planning_result_sha256,
        'basis_sha256': task_digest(basis.model_dump(mode='json')),
        'formation_record_sha256': basis.formation_record_sha256,
        'native_task_source_sha256': formation.native_source_sha256}
    if not isinstance(provenance, dict) or any(provenance.get(key) != value for key, value in expected.items()):
        raise ValueError('Connected production lost its exact original planning/task formation provenance')


class _PlanningProductionReception:
    VERSION = 'configured-supplier-planning-production-fixture-sources.v1'

    def __init__(self, request, settings, production, planning):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.production, self.planning = production, planning
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.planning_history
        self.worker = SupplierPlanningResultWorker(store=planning.store,
            snapshots=InvocationSnapshotStore(planning.store), registry=production.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=planning.validators.invocation, validate_wait=planning.validators.wait,
            validate_recovery=planning.validators.recovery)
        self._input = production.registry.get('SUPPLIER-A05').contract.validate_input(history.request.action_input)
        self._originals = self._projections(history.source_settings.source_projection['objects'])
        self._current = self._projections(settings.source_projection['objects'])

    @staticmethod
    def _projections(rows):
        result = {}
        for row in rows:
            if set(row) != {'ref', 'value'}:
                raise ValueError('Planning reception requires exact supplied ref/value records')
            key = Reference.model_validate(row['ref']).key()
            if key in result:
                raise ValueError('Planning reception repeats an original source identity')
            result[key] = row['value']
        return result

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Planning reception changes recipient or independent declarations')
        self.production.evidence()
        self.planning.evidence()

    @contextmanager
    def read_guard(self, context):
        with self.production.read_guard(context), self.planning.read_guard(self.settings.planning_history.request.context):
            self._check(context)
            try:
                yield
            finally:
                self._check(context)

    def validate_history(self, saved):
        self._check(saved.current_context)
        history, basis = self.settings.planning_history, self.settings.registration.basis
        if (saved.identity.as_dict() != history.identity.as_dict() or saved.context != history.request.context
                or saved.action_input != self._input or saved.result.kind != 'completed'
                or any(self._originals.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in saved.source_reading)
                or basis.planning_task_sha256 != saved.identity.key or basis.planning_record_sha256 != saved.record_sha256
                or basis.planning_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                or basis.planning_audit_sha256 != task_digest(saved.audit)
                or basis.planning_source_reading_sha256 != saved.source_reading_sha256):
            raise TaskConflict('Planning reception substitutes original A05 result or retained sources')
        return True

    def validate_execution(self, *, saved, context, basis, source, task, release):
        self._check(context)
        self.validate_history(saved)
        registration = self.settings.registration
        formed = {row.task.ref.key(): row for row in registration.tasks}
        lines = {row.task_ref.key(): row for row in source.lines}
        selected = formed.get(task.ref.key())
        if (registration.current_state != 'recorded' or basis != registration.basis
                or source != registration.formation_record or len(formed) != len(registration.tasks)
                or len(lines) != len(source.lines) or set(formed) != set(lines)
                or task.ref.key() not in formed or task != formed[task.ref.key()].task
                or isinstance(selected, DeclaredFormedProductionTask) and (release is None or release != selected.release)
                or isinstance(selected, DeclaredFormedPurchaseTask) and release is not None
                or registration.recorded_at.clock_ref != context.business_time.clock_ref
                or not saved.context.business_time.offset <= registration.recorded_at.offset <= context.business_time.offset):
            raise TaskConflict('Planning reception substitutes complete current native task formation or release')

        def evidence_at(refs, at):
            if at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset:
                raise TaskConflict('Planning reception changes original evidence use clock or time')
            for ref in {ref.key(): ref for ref in refs}.values():
                evidence = EvidenceRecord.model_validate(self._current.get(ref.key()))
                if (evidence.ref != ref or evidence.source_kind != 'synthetic'
                        or evidence.effective_window is not None and not evidence.effective_window.contains(at)):
                    raise TaskConflict('Planning reception lacks explicit synthetic evidence valid at use')

        def current(row, *, evidence_time=None):
            if (self._current.get(row.ref.key()) != row.model_dump(mode='json')
                    or row.available_at.clock_ref != context.business_time.clock_ref
                    or not registration.recorded_at.offset <= row.available_at.offset <= context.business_time.offset
                    or not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Planning reception changes current registered source or applicability')
            evidence_at(row.evidence_refs, context.business_time if evidence_time is None else evidence_time)

        def original(ref, schema):
            retained = [row['projection'] for row in saved.source_reading if Reference.model_validate(row['ref']).key() == ref.key()]
            if len(retained) != 1:
                raise TaskConflict('Planning reception omits original retained method or stock allocation')
            return schema.model_validate(retained[0])

        current(basis, evidence_time=basis.authored_at)
        evidence_at(basis.relation_evidence_refs, basis.authored_at)
        current(source)
        evidence_at([source.native_evidence_ref], context.business_time)
        used_allocations, native_allocations, native_events = set(), set(), set()
        batch_correspondence = {}
        purchased_quantities, purchased_capacities = {}, {}
        for key, formed_task in formed.items():
            planned = lines[key].planned_task
            if isinstance(formed_task, DeclaredFormedPurchaseTask):
                native_task, order, rule = formed_task.task, formed_task.upstream_order, formed_task.receipt_rule
                profile = SupplierExecutionProfileView.model_validate(self._current.get(native_task.profile_ref.key()))
                for row in (native_task, order, rule, profile):
                    current(row)
                planning_method = original(planned.method_ref, SupplierPlanningMethodView)
                order_lines = {row.line_ref.key(): row for row in order.lines}
                order_line = order_lines.get(formed_task.order_line_ref.key())
                if (planned.mode != 'purchase' or native_task.mode != 'purchase' or planning_method.mode != 'purchase'
                        or planned.planned_inputs or planned.resources or planning_method.material_inputs
                        or planning_method.procurement_basis_ref is None or planning_method.purchase_window_ref is None
                        or formed_task.planning_method_ref != planned.method_ref
                        or formed_task.output_product_ref != planned.target.product_ref
                        or planning_method.product_ref != planned.target.product_ref
                        or planning_method.quantity_unit != planned.target.quantity.unit
                        or native_task.production_method_ref is not None or native_task.source_rework_batch_refs
                        or native_task.prior_execution_refs or native_task.purchase_order_ref != order.ref
                        or native_task.scope != planned.scope_ref or native_task.organization_id != saved.identity.organization_id
                        or lines[key].task_sha256 != task_digest(native_task.model_dump(mode='json'))
                        or lines[key].core_event_id in native_events or lines[key].core_event_id == order.core_event_id
                        or native_task.as_of != context.business_time or native_task.history_coverage != 'complete'
                        or native_task.remaining_target.unit != planned.target.quantity.unit
                        or not 0 <= decimal_fraction(native_task.remaining_target.value) <= decimal_fraction(planned.target.quantity.value)
                        or order.buyer_id != native_task.organization_id or order.supplier_id == order.buyer_id
                        or not isinstance(order.effective, Known) or order.effective.value is not True
                        or order.scope != native_task.scope or order.as_of != context.business_time
                        or order.history_coverage != 'complete' or len(order_lines) != len(order.lines) or order_line is None
                        or rule.order_ref != order.ref or rule.buyer_id != order.buyer_id
                        or not isinstance(rule.permitted, Known) or rule.permitted.value is not True
                        or not isinstance(rule.supported, Known) or rule.supported.value is not True
                        or len({ref.key() for ref in native_task.upstream_delivery_refs}) != len(native_task.upstream_delivery_refs)
                        or len({ref.key() for ref in order.delivery_refs}) != len(order.delivery_refs)
                        or not {ref.key() for ref in native_task.upstream_delivery_refs} <= {ref.key() for ref in order.delivery_refs}
                        or profile.task_ref != native_task.ref or profile.organization_id != native_task.organization_id
                        or profile.scope != native_task.scope or profile.choice != 'reconcile_upstream'
                        or profile.inputs or profile.resources):
                    raise TaskConflict('Purchase formation changes original plan or independent upstream order/receipt rule')
                native_events.add(lines[key].core_event_id)
                if (order_line.product.model_dump(mode='json', exclude={'quantity'}) != planned.target.model_dump(mode='json', exclude={'quantity'})
                        or order_line.product.quantity.unit != planned.target.quantity.unit):
                    raise TaskConflict('Purchase formation changes original target product, scope or requirements')
                purchase_key = (order.ref.key(), order_line.line_ref.key())
                purchased_quantities[purchase_key] = purchased_quantities.get(purchase_key, 0) + decimal_fraction(planned.target.quantity.value)
                purchased_capacities[purchase_key] = decimal_fraction(order_line.product.quantity.value)
                if task.ref.key() == key:
                    setup = self.request.action_input['execution_setup']
                    if (setup.get('kind') != 'purchase'
                            or Reference.model_validate(setup['purchase_order_ref']).key() != order.ref.key()
                            or Reference.model_validate(setup['receipt_rule_ref']).key() != rule.ref.key()):
                        raise TaskConflict('Selected purchase setup changes registered upstream order or receipt rule')
                continue
            native_task, method, native_release = formed_task.task, formed_task.method, formed_task.release
            for row in (native_task, method, native_release):
                current(row)
            planning_method = original(planned.method_ref, SupplierPlanningMethodView)
            recipe = lambda rows: sorted((row.product_ref.key(), row.unit, row.quantity_per_output) for row in rows)
            if (native_task.mode not in {'manufacture', 'rework'} or native_task.mode != planned.mode
                    or formed_task.planning_method_ref != planned.method_ref
                    or formed_task.output_product_ref != planned.target.product_ref
                    or native_task.scope != planned.scope_ref or native_task.organization_id != saved.identity.organization_id
                    or lines[key].task_sha256 != task_digest(native_task.model_dump(mode='json'))
                    or lines[key].core_event_id in native_events
                    or native_release.core_event_id in native_events
                    or native_task.as_of != context.business_time
                    or native_task.remaining_target.unit != planned.target.quantity.unit
                    or not 0 <= decimal_fraction(native_task.remaining_target.value) <= decimal_fraction(planned.target.quantity.value)
                    or native_task.production_method_ref != method.ref or method.mode != planned.mode
                    or method.output_unit != planned.target.quantity.unit or method.resource_kind != planning_method.resource_kind
                    or method.minimum_resource.unit != planning_method.capacity_unit
                    or recipe(method.input_recipe) != recipe(planning_method.material_inputs)
                    or not isinstance(method.supported, Known) or method.supported.value is not True
                    or native_release.task_ref != native_task.ref or native_release.method_ref != method.ref
                    or native_release.organization_id != native_task.organization_id or native_release.status != 'released'
                    or native_release.core_event_id == lines[key].core_event_id):
                raise TaskConflict('Native task registration changes original product, recipe, method or independent release')
            native_events.add(lines[key].core_event_id)
            native_events.add(native_release.core_event_id)
            expected_allocations = {ref.key() for row in planned.planned_inputs for ref in row.available_allocation_refs}
            mappings = {row.planning_allocation_ref.key(): row for row in formed_task.material_lineage}
            if len(mappings) != len(formed_task.material_lineage) or set(mappings) != expected_allocations:
                raise TaskConflict('Native task registration drops or repeats original material allocation lineage')
            for allocation_key, mapping in mappings.items():
                prior = original(mapping.planning_allocation_ref, SupplierInventoryAllocationView)
                material, allocation = mapping.material, mapping.allocation
                for row in (material, allocation):
                    current(row)
                if (allocation_key in used_allocations or allocation.ref.key() in native_allocations
                        or prior.organization_id != native_task.organization_id
                        or prior.work_authority_ref != source.work_authority_ref or prior.status != 'reserved'
                        or prior.batch_ref != mapping.planning_batch_ref
                        or material.product_ref != prior.product_ref or material.organization_id != prior.organization_id
                        or not isinstance(material.actual_received, Known) or material.actual_received.value is not True
                        or allocation.batch_ref != material.ref or allocation.task_ref != native_task.ref
                        or allocation.organization_id != prior.organization_id or allocation.purpose != planned.mode
                        or allocation.quantity.unit != prior.quantity.unit
                        or decimal_fraction(allocation.quantity.value) != decimal_fraction(prior.quantity.value)
                        or allocation.status != 'reserved' or allocation.as_of != context.business_time
                        or decimal_fraction(allocation.used_quantity.value) != 0
                        or allocation.used_quantity.unit != allocation.quantity.unit
                        or material.actual_quantity.unit != allocation.quantity.unit
                        or decimal_fraction(material.actual_quantity.value) < decimal_fraction(allocation.quantity.value)):
                    raise TaskConflict('Native material registration changes original reserved quantity or batch lineage')
                used_allocations.add(allocation_key)
                native_allocations.add(allocation.ref.key())
                previous_batch = batch_correspondence.setdefault(material.ref.key(), prior.batch_ref)
                if previous_batch != prior.batch_ref:
                    raise TaskConflict('Native material correspondence merges distinct original physical batches')
            profile = SupplierExecutionProfileView.model_validate(self._current.get(native_task.profile_ref.key()))
            current(profile)
            if (profile.task_ref != native_task.ref or profile.organization_id != native_task.organization_id
                    or profile.scope != native_task.scope):
                raise TaskConflict('Native task registration substitutes its production input profile')
            mapped_inputs = {row.allocation.ref.key(): row for row in mappings.values()}
            requested = set()
            for use in profile.inputs:
                mapping = mapped_inputs.get(use.allocation_ref.key())
                if (mapping is None or use.allocation_ref.key() in requested
                        or use.batch_ref != mapping.material.ref or use.quantity.unit != mapping.allocation.quantity.unit
                        or not 0 < decimal_fraction(use.quantity.value) <= decimal_fraction(mapping.allocation.quantity.value)):
                    raise TaskConflict('Production profile invents material outside original registered plan allocations')
                requested.add(use.allocation_ref.key())
            allocation_signature = lambda rows: sorted((row.resource_ref.key(), task_digest(row.scope_ref.model_dump(mode='json')),
                row.window_ref.key(), row.quantity.unit, decimal_fraction(row.quantity.value)) for row in rows)
            if allocation_signature(profile.resources) != allocation_signature(planned.resources):
                raise TaskConflict('Production profile changes the original planned resource pools, windows or quantities')
        if any(quantity <= 0 or quantity > purchased_capacities[key] for key, quantity in purchased_quantities.items()):
            raise TaskConflict('Purchase formation repeats or exceeds the original upstream ordered quantity')
        expected_native = {'schema_version': 'supplier-native-task-formation-observation.v1', 'run_id': context.run_id,
            'work_authority_ref': source.work_authority_ref.model_dump(mode='json'),
            'recorded_at': registration.recorded_at.model_dump(mode='json'), 'producer': registration.producer,
            'formation_lines': [row.model_dump(mode='json') for row in source.lines],
            'tasks': [row.model_dump(mode='json') for row in registration.tasks]}
        if registration.native_record != expected_native or task_digest(expected_native) != source.native_source_sha256:
            raise TaskConflict('Planning reception substitutes exact native task/method/material registration content')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**self.production.evidence(), 'schema_version': self.VERSION,
            'planning_history_task_sha256': self.settings.planning_history.identity.key,
            'planning_history_journal': str(self.planning.store.path),
            'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
            'limitations': ['Explicit synthetic native production or purchase task correspondence from saved A05.',
                'No task, release, reservation, inventory or production effect is created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.planning.close()
            finally:
                self.production.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierPlanningProductionFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.planning_history
    journal = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or settings.action_id != 'SUPPLIER-A06' or history.source_settings.action_id != 'SUPPLIER-A05'
            or history.identity.action_id != 'SUPPLIER-A05' or history.identity.role != 'Supplier'
            or history.identity.purpose != 'action' or history.identity.run_id != request.context.run_id
            or history.request.context.run_id != request.context.run_id
            or history.identity.organization_id != settings.source_projection['organization_id']
            or history.identity.organization_id != history.source_settings.source_projection['organization_id']
            or history.identity.request_id != history.request.context.operation_id
            or history.identity.context_sha256 != task_digest(history.request.context.model_dump(mode='json'))
            or history.identity.input_sha256 != task_digest(history.request.action_input)
            or history.request.context.contract_ref.id != 'SUPPLIER-A05'
            or history.request.context.scope != request.context.scope
            or history.request.context.business_time.clock_ref != request.context.business_time.clock_ref
            or history.request.context.business_time.offset > request.context.business_time.offset
            or history.source_settings.source_projection['macro_version'] != history.macro_version
            or history.identity.versions['client'] != history.client_version
            or history.identity.versions['model'] != history.model_version
            or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
        raise ValueError('Planning reception requires original same-run A05 and a separate existing journal')
    production = planning = None
    try:
        production = build_production_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'planning_history', 'registration'}))
        planning_factory = (build_linked_planning_sources if isinstance(history.source_settings,
            SupplierOrderPlanningFixtureSettings) else build_planning_sources)
        planning = planning_factory(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _PlanningProductionReception(request, settings, production, planning)
        return replace(production, version=binding.VERSION, planning_worker=binding.worker,
            validate_planning_history=binding.validate_history, validate_planning_execution=binding.validate_execution,
            read_guard=binding.read_guard, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if planning is not None:
                planning.close()
        finally:
            if production is not None:
                production.close()
        raise
