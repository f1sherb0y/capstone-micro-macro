"""Synthetic A07 sources from saved A06 and independently observed production."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_execution_handoff import SupplierExecutionHandoffBasisView
from integration.supplier_execution_results import SupplierExecutionResultWorker
from integration.supplier_production_fixture_sources import SupplierProductionFixtureSettings, build_sources as build_production_sources
from integration.supplier_planning_production_fixture_sources import (
    SupplierPlanningProductionFixtureSettings, build_sources as build_linked_production_sources,
)
from integration.supplier_quality_fixture_sources import SupplierQualityFixtureSettings, build_sources as build_quality_sources
from src.actions.contracts.common import StrictRecord, Reference, TextId, ref_type
from src.actions.contracts.supplier_execution_objects import (
    SupplierProductionRequestView, SupplierProductionExecutionView, SupplierStockMovementView,
    SupplierActualInputUse,
)
from src.actions.contracts.supplier_quality_objects import SupplierQualityBatchView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskIdentity, TaskConflict, task_digest
from src.methods.pricing import decimal_fraction


class SupplierProductionHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierProductionFixtureSettings | SupplierPlanningProductionFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredProductionConsumption(StrictRecord):
    movement_ref: ref_type('StockMovement')
    inputs: Annotated[list[SupplierActualInputUse], Field(min_length=1)]


class DeclaredProductionQualityRegistration(StrictRecord):
    """Supplied current native receipt and lineage; never a second stock ledger."""
    schema_version: Literal['supplier-production-quality-registration.v1']
    registration_id: TextId
    basis: SupplierExecutionHandoffBasisView
    request: SupplierProductionRequestView
    execution: SupplierProductionExecutionView
    movements: Annotated[list[SupplierStockMovementView], Field(min_length=1)]
    batches: Annotated[list[SupplierQualityBatchView], Field(min_length=1)]
    consumption_attributions: list[DeclaredProductionConsumption]
    native_receipt: dict
    current_state: Literal['recorded', 'withdrawn', 'superseded']


class SupplierProductionQualityFixtureSettings(SupplierQualityFixtureSettings):
    production_history: SupplierProductionHistorySettings
    registration: DeclaredProductionQualityRegistration


class _ProductionQualityReception:
    VERSION = 'configured-supplier-production-quality-fixture-sources.v1'

    def __init__(self, request, settings, quality, production):
        self.request, self.settings = request.model_copy(deep=True), settings.model_copy(deep=True)
        self.quality, self.production = quality, production
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.production_history
        self.worker = SupplierExecutionResultWorker(store=production.store,
            snapshots=InvocationSnapshotStore(production.store), registry=quality.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=production.validators.invocation, validate_wait=production.validators.wait,
            validate_recovery=production.validators.recovery)
        self._input = quality.registry.get('SUPPLIER-A06').contract.validate_input(history.request.action_input)
        self._originals = self._projections(history.source_settings.source_projection['objects'])
        self._current = self._projections(self.settings.source_projection['objects'])

    @staticmethod
    def _projections(rows):
        result = {}
        for row in rows:
            if set(row) != {'ref', 'value'}:
                raise ValueError('Production reception requires exact supplied ref/value projections')
            key = Reference.model_validate(row['ref']).key()
            if key in result:
                raise ValueError('Production reception repeats an original source identity')
            result[key] = row['value']
        return result

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Production reception changes original quality context or declarations')
        self.quality.evidence()
        self.production.evidence()

    @contextmanager
    def read_guard(self, context):
        with self.quality.read_guard(context), self.production.read_guard(self.settings.production_history.request.context):
            self._check(context)
            try:
                yield
            finally:
                self._check(context)

    def validate_history(self, saved):
        self._check(saved.current_context)
        history, basis = self.settings.production_history, self.settings.registration.basis
        if (saved.identity.as_dict() != history.identity.as_dict() or saved.context != history.request.context
                or saved.action_input != self._input or saved.result.kind != 'completed'
                or any(self._originals.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in saved.source_reading)
                or basis.execution_task_sha256 != saved.identity.key or basis.execution_record_sha256 != saved.record_sha256
                or basis.execution_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                or basis.execution_audit_sha256 != task_digest(saved.audit)
                or basis.execution_source_reading_sha256 != saved.source_reading_sha256):
            raise TaskConflict('Production reception changes the selected original A06 result or retained sources')
        return True

    def validate_quality(self, *, saved, context, basis, execution, request, movements, batches):
        self._check(context)
        self.validate_history(saved)
        registration = self.settings.registration
        if (registration.current_state != 'recorded' or basis != registration.basis
                or execution != registration.execution or request != registration.request
                or {row.ref.key(): row for row in movements} != {row.ref.key(): row for row in registration.movements}
                or {row.ref.key(): row for row in batches} != {row.ref.key(): row for row in registration.batches}
                or len({row.ref.key() for row in registration.movements}) != len(registration.movements)
                or len({row.ref.key() for row in registration.batches}) != len(registration.batches)):
            raise TaskConflict('Production reception substitutes independent native receipt or output set')
        for row in (basis, execution, request, *movements, *batches):
            if self._current.get(row.ref.key()) != row.model_dump(mode='json'):
                raise TaskConflict('Production reception changes current native request, movements or pending batch')
        if (execution.recorded_at is None or execution.recorded_at.clock_ref != context.business_time.clock_ref
                or execution.available_at.clock_ref != context.business_time.clock_ref
                or not execution.recorded_at.offset <= execution.available_at.offset <= context.business_time.offset
                or saved.result.payload.choice != 'reconcile_execution' and execution.recorded_at.offset < saved.context.business_time.offset
                or request.available_at.clock_ref != context.business_time.clock_ref
                or request.available_at.offset > execution.recorded_at.offset):
            raise TaskConflict('Native production receipt precedes the original local request or submission')
        allocations = {}
        for use in request.inputs:
            if use.allocation_ref.key() in allocations:
                raise TaskConflict('Native production request repeats a physical input allocation')
            allocations[use.allocation_ref.key()] = use
        consumed = {}
        attributions = {row.movement_ref.key(): row for row in registration.consumption_attributions}
        if (len(attributions) != len(registration.consumption_attributions)
                or set(attributions) != {row.ref.key() for row in movements if row.kind == 'input_consumed'}):
            raise TaskConflict('Native receipt requires exact attribution for every original consumption movement')
        for movement in movements:
            if (movement.available_at.clock_ref != context.business_time.clock_ref
                    or not execution.recorded_at.offset <= movement.available_at.offset <= context.business_time.offset
                    or decimal_fraction(movement.quantity.value) < 0
                    or len(set(movement.source_allocation_refs)) != len(movement.source_allocation_refs)
                    or len(set(movement.lineage_batch_refs)) != len(movement.lineage_batch_refs)):
                raise TaskConflict('Native production movement changes time or duplicates physical lineage')
            related = [allocations.get(ref.key()) for ref in movement.source_allocation_refs]
            if (not related or any(use is None for use in related)
                    or set(movement.lineage_batch_refs) != {use.batch_ref for use in related}):
                raise TaskConflict('Native production movement substitutes original material allocations or batch lineage')
            if movement.kind == 'input_consumed':
                actual = attributions[movement.ref.key()].inputs
                if (len({use.allocation_ref for use in actual}) != len(actual)
                        or {use.allocation_ref for use in actual} != set(movement.source_allocation_refs)
                        or any(use.quantity.unit != movement.quantity.unit for use in actual)
                        or sum((decimal_fraction(use.quantity.value) for use in actual), 0) != decimal_fraction(movement.quantity.value)):
                    raise TaskConflict('Native consumption attribution changes original movement quantities or allocations')
                for use in actual:
                    original_use = allocations[use.allocation_ref.key()]
                    amount = decimal_fraction(use.quantity.value)
                    if (use.batch_ref != original_use.batch_ref or use.quantity.unit != original_use.quantity.unit or amount < 0):
                        raise TaskConflict('Native consumption attribution substitutes original material batch or unit')
                    key = use.allocation_ref.key()
                    consumed[key] = consumed.get(key, 0) + amount
                    if consumed[key] > decimal_fraction(original_use.quantity.value):
                        raise TaskConflict('Native consumption exceeds the original requested allocation')
        for batch in batches:
            if (batch.state != 'pending_inspection'
                    or batch.core_event_id != execution.core_event_id
                    or batch.available_at.clock_ref != context.business_time.clock_ref
                    or not execution.recorded_at.offset <= batch.available_at.offset <= context.business_time.offset):
                raise TaskConflict('Native production output cannot become usable or change original event/time')
        expected = {'schema_version': 'supplier-native-production-receipt-observation.v1', 'run_id': context.run_id,
            'request': request.model_dump(mode='json'), 'execution': execution.model_dump(mode='json'),
            'movements': [row.model_dump(mode='json') for row in registration.movements],
            'batches': [row.model_dump(mode='json') for row in registration.batches],
            'consumption_attributions': [row.model_dump(mode='json') for row in registration.consumption_attributions]}
        if registration.native_receipt != expected or task_digest(expected) != basis.native_receipt_sha256:
            raise TaskConflict('Production reception changes exact native receipt/material-to-product content')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**self.quality.evidence(), 'schema_version': self.VERSION,
            'production_history_task_sha256': self.settings.production_history.identity.key,
            'production_history_journal': str(self.production.store.path),
            'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
            'limitations': ['Explicit synthetic native production declarations from saved A06.',
                'No native input consumption, production, pending batch or quality approval is created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.production.close()
            finally:
                self.quality.close()


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierProductionQualityFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.production_history
    journal = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or settings.action_id != 'SUPPLIER-A07' or history.source_settings.action_id != 'SUPPLIER-A06'
            or history.identity.action_id != 'SUPPLIER-A06' or history.identity.role != 'Supplier'
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.identity.organization_id != settings.source_projection['organization_id']
            or history.identity.organization_id != history.source_settings.source_projection['organization_id']
            or history.identity.request_id != history.request.context.operation_id
            or history.identity.context_sha256 != task_digest(history.request.context.model_dump(mode='json'))
            or history.identity.input_sha256 != task_digest(history.request.action_input)
            or history.request.context.contract_ref.id != 'SUPPLIER-A06'
            or history.request.context.scope != request.context.scope
            or history.request.context.business_time.clock_ref != request.context.business_time.clock_ref
            or history.request.context.business_time.offset > request.context.business_time.offset
            or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
        raise ValueError('Production quality sources require original same-run A06 and a separate existing journal')
    quality = production = None
    try:
        quality = build_quality_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'production_history', 'registration'}))
        production_factory = (build_linked_production_sources if isinstance(history.source_settings,
            SupplierPlanningProductionFixtureSettings) else build_production_sources)
        production = production_factory(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _ProductionQualityReception(request, settings, quality, production)
        return replace(quality, version=binding.VERSION, execution_worker=binding.worker,
            validate_execution_history=binding.validate_history, validate_execution_quality=binding.validate_quality,
            read_guard=binding.read_guard, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if production is not None:
                production.close()
        finally:
            if quality is not None:
                quality.close()
        raise
