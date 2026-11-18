"""Synthetic A09 sources bound to an existing same-run original A08 journal."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_logistics_fixture_sources import (
    SupplierLogisticsFixtureSettings, build_sources as build_logistics_sources,
)
from integration.supplier_logistics_handoff import (
    SupplierLogisticsHandoffBasisView, supplier_logistics_handoff_schemas,
)
from integration.supplier_logistics_results import SupplierLogisticsResultWorker
from integration.supplier_quality_logistics_fixture_sources import (
    SupplierQualityLogisticsFixtureSettings, build_sources as build_linked_logistics_sources,
)
from integration.supplier_receiving_fixture_sources import (
    SupplierReceivingFixtureSettings, build_sources as build_receiving_sources,
)
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.contracts.supplier_receiving_objects import SupplierReceivingShipmentView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class SupplierLogisticsHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierLogisticsFixtureSettings | SupplierQualityLogisticsFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredNativeShipmentObservation(StrictRecord):
    """Independent supplied synthetic state; no native shipment is generated."""
    shipment: SupplierReceivingShipmentView
    native_record: dict
    transport_sources: list[dict]


class DeclaredLogisticsReceivingRegistration(StrictRecord):
    schema_version: Literal['supplier-logistics-receiving-registration.v1']
    registration_id: TextId
    basis: SupplierLogisticsHandoffBasisView
    observations: Annotated[list[DeclaredNativeShipmentObservation], Field(min_length=1)]
    current_state: Literal['observed', 'withdrawn', 'superseded']


class SupplierLogisticsReceivingFixtureSettings(SupplierReceivingFixtureSettings):
    logistics_history: SupplierLogisticsHistorySettings
    registration: DeclaredLogisticsReceivingRegistration


class _LogisticsReception:
    VERSION = 'configured-supplier-logistics-receiving-fixture-sources.v1'

    def __init__(self, request, settings, receiving, logistics):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.receiving, self.logistics = receiving, logistics
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.logistics_history
        self.worker = SupplierLogisticsResultWorker(store=logistics.store,
            snapshots=InvocationSnapshotStore(logistics.store), registry=receiving.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=logistics.validators.invocation, validate_wait=logistics.validators.wait,
            validate_recovery=logistics.validators.recovery)
        self._input = receiving.registry.get('SUPPLIER-A08').contract.validate_input(history.request.action_input)
        self._originals = self._projections(history.source_settings.source_projection['objects'])
        self._current = self._projections(self.settings.source_projection['objects'])
        observations = self.settings.registration.observations
        self._observations = {row.shipment.ref.key(): row for row in observations}
        if len(self._observations) != len(observations):
            raise ValueError('Logistics reception repeats an independent shipment observation')

    @staticmethod
    def _projections(rows):
        result = {}
        for row in rows:
            if set(row) != {'ref', 'value'}:
                raise ValueError('Logistics reception requires exact supplied ref/value projections')
            key = Reference.model_validate(row['ref']).key()
            if key in result:
                raise ValueError('Logistics reception repeats a source identity')
            result[key] = row['value']
        return result

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Logistics reception changes the original receiving context or declarations')
        self.receiving.evidence()
        self.logistics.evidence()

    @contextmanager
    def read_guard(self, context):
        with self.receiving.read_guard(context), self.logistics.read_guard(self.settings.logistics_history.request.context):
            self._check(context)
            try:
                yield
            finally:
                self._check(context)

    def validate_history(self, saved):
        self._check(saved.current_context)
        history = self.settings.logistics_history
        if (saved.identity.as_dict() != history.identity.as_dict()
                or saved.context != history.request.context or saved.action_input != self._input
                or saved.result.kind != 'completed'
                or any(self._originals.get(Reference.model_validate(row['ref']).key()) != row['projection']
                    for row in saved.source_reading)):
            raise TaskConflict('Logistics reception changes the selected original A08 result or retained sources')
        basis = self.settings.registration.basis
        if (basis.logistics_task_sha256 != saved.identity.key
                or basis.logistics_record_sha256 != saved.record_sha256
                or basis.logistics_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                or basis.logistics_audit_sha256 != task_digest(saved.audit)
                or basis.logistics_source_reading_sha256 != saved.source_reading_sha256):
            raise TaskConflict('Independent logistics registration changes original saved evidence')
        return True

    def validate_receiving(self, *, saved, context, basis, shipments):
        self._check(context)
        self.validate_history(saved)
        registration = self.settings.registration
        if (registration.current_state != 'observed' or basis != registration.basis
                or self._current.get(basis.ref.key()) != basis.model_dump(mode='json')
                or {row.ref.key() for row in shipments} != set(self._observations)):
            raise TaskConflict('Logistics reception changes the independent current relation or shipment set')
        links = {link.shipment_ref.key(): link for link in basis.shipment_links}
        schemas = supplier_logistics_handoff_schemas()
        for shipment in shipments:
            observation = self._observations[shipment.ref.key()]
            link = links[shipment.ref.key()]
            expected = {'schema_version': 'supplier-native-shipment-observation.v1',
                'run_id': context.run_id, 'shipment': shipment.model_dump(mode='json')}
            if (observation.shipment != shipment or observation.native_record != expected
                    or self._current.get(shipment.ref.key()) != expected['shipment']
                    or task_digest(expected) != link.native_record_sha256):
                raise TaskConflict('Logistics reception substitutes independent native shipment content')
            transport = self._projections(observation.transport_sources)
            for row in observation.transport_sources:
                ref = Reference.model_validate(row['ref'])
                if (ref.kind not in {'TransportPosition', 'TransportTraversal', 'TransportRoute', 'TransportMethod'}
                        or self._current.get(ref.key()) != row['value']):
                    raise TaskConflict('Logistics reception changes supplied current native transport sources')
                schemas.validate_projection(ref, row['value'])
            required = set()
            if shipment.status in {'arrived', 'received'}:
                if shipment.current_position_ref is None or not shipment.traversal_refs:
                    raise TaskConflict('Native arrival observation lacks original position or actual travel')
                required.add(shipment.current_position_ref.key())
                for ref in shipment.traversal_refs:
                    required.add(ref.key())
                    traversal = transport.get(ref.key())
                    if traversal is None:
                        raise TaskConflict('Native arrival observation omits actual traversal')
                    route_ref = Reference.model_validate(traversal['route_ref'])
                    required.add(route_ref.key())
                    route = transport.get(route_ref.key())
                    if route is None:
                        raise TaskConflict('Native arrival observation omits actual route')
                    required.add(Reference.model_validate(route['method_ref']).key())
            if not required <= set(transport):
                raise TaskConflict('Native arrival observation omits elapsed transport method or position')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**self.receiving.evidence(), 'schema_version': self.VERSION,
            'logistics_history_task_sha256': self.settings.logistics_history.identity.key,
            'logistics_history_journal': str(self.logistics.store.path),
            'registration_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
            'limitations': ['Explicit synthetic declarations from an existing same-run A08 journal.',
                'No native dispatch, travel, arrival, receipt or stock is created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.logistics.close()
            finally:
                self.receiving.close()


def build_sources(*, request, output_directory, offline, settings):
    """Bind existing A08 evidence and current independent synthetic transport state."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = SupplierLogisticsReceivingFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.logistics_history
    journal = Path(history.source_settings.journal_path).resolve()
    if (offline is not True or settings.action_id != 'SUPPLIER-A09'
            or history.source_settings.action_id != 'SUPPLIER-A08'
            or request.context.run_id != history.request.context.run_id
            or request.context.run_id != history.identity.run_id
            or history.identity.action_id != 'SUPPLIER-A08' or history.identity.role != 'Supplier'
            or settings.source_projection['organization_id'] != history.identity.organization_id
            or history.source_settings.source_projection['organization_id'] != history.identity.organization_id
            or history.request.context.contract_ref.id != 'SUPPLIER-A08'
            or history.identity.request_id != history.request.context.operation_id
            or history.identity.context_sha256 != task_digest(history.request.context.model_dump(mode='json'))
            or history.identity.input_sha256 != task_digest(history.request.action_input)
            or request.context.scope != history.request.context.scope
            or history.request.context.business_time.clock_ref != request.context.business_time.clock_ref
            or history.request.context.business_time.offset > request.context.business_time.offset
            or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
        raise ValueError('Logistics reception requires original same-run A08, separate existing journal and A09 sources')
    receiving, logistics = None, None
    try:
        receiving = build_receiving_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'logistics_history', 'registration'}))
        logistics_factory = (build_linked_logistics_sources if isinstance(history.source_settings,
            SupplierQualityLogisticsFixtureSettings) else build_logistics_sources)
        logistics = logistics_factory(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _LogisticsReception(request, settings, receiving, logistics)
        return replace(receiving, version=binding.VERSION, logistics_worker=binding.worker,
            validate_logistics_history=binding.validate_history, validate_logistics_receiving=binding.validate_receiving,
            read_guard=binding.read_guard, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if logistics is not None:
                logistics.close()
        finally:
            if receiving is not None:
                receiving.close()
        raise
