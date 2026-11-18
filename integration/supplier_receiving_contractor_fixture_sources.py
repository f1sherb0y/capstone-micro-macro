"""Offline Contractor material intake from existing Supplier A09 journals."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_execution_fixture_sources import (
    ContractorExecutionFixtureSettings, build_sources as build_contractor_sources,
)
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_receiving_actions import SupplierReceivingActionAssembler
from integration.supplier_receiving_fixture_sources import (
    SupplierReceivingFixtureSettings, build_sources as build_supplier_sources,
)
from integration.supplier_receiving_results import SupplierReceivingResultWorker
from integration.supplier_logistics_receiving_fixture_sources import (
    SupplierLogisticsReceivingFixtureSettings, build_sources as build_linked_supplier_sources,
)
from src.actions.contracts.common import Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.contractor_execution_objects import (
    ContractorInventoryView, ContractorReceivedMaterialView,
)
from src.actions.contracts.contractor_readiness_objects import ContractorReadyInputView
from src.actions.contracts.supplier_receiving_objects import (
    SupplierGoodsUseReleaseView, SupplierReceiptInspectionView,
    SupplierReceivingMandateView, SupplierReceivingPartyView,
    SupplierLogisticsOrderView, SupplierGoodsInspectionMethodView,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierReceivingHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: SupplierReceivingFixtureSettings | SupplierLogisticsReceivingFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredReceivedMaterialRegistration(StrictRecord):
    """Independent synthetic receiver declaration; no stock is generated here."""
    schema_version: Literal['contractor-received-material-registration.v1']
    registration_id: TextId
    basis: ContractorReceivedMaterialView
    inventory: ContractorInventoryView
    batch: ContractorReadyInputView
    native_record: dict
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    sharing_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    current_state: Literal['received', 'withdrawn', 'superseded']


class ContractorSupplierReceivingFixtureSettings(ContractorExecutionFixtureSettings):
    supplier_history: SupplierReceivingHistorySettings
    registrations: Annotated[list[DeclaredReceivedMaterialRegistration], Field(min_length=1)]


class _MaterialReception:
    VERSION = 'configured-contractor-supplier-receiving-fixture-sources.v1'

    def __init__(self, request, settings, recipient, supplier):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.recipient, self.supplier = recipient, supplier
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False
        history = self.settings.supplier_history
        self.worker = SupplierReceivingResultWorker(store=supplier.store,
            snapshots=InvocationSnapshotStore(supplier.store), registry=supplier.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=supplier.validators.invocation, validate_wait=supplier.validators.wait,
            validate_recovery=supplier.validators.recovery)
        self.assembler = SupplierReceivingActionAssembler(registry=supplier.registry,
            organizations=supplier.organizations, provider=supplier.provider,
            macro_version=history.macro_version, source_mode='fixture', methods=supplier.methods,
            policy_version=history.policy_version, model_version=history.model_version)
        self._input = supplier.registry.get('SUPPLIER-A09').contract.validate_input(history.request.action_input)
        self.registrations = {row.basis.ref.key(): row for row in self.settings.registrations}

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Material reception changes original recipient or independent declarations')
        self.recipient.evidence()
        self.supplier.evidence()

    def _validate_history(self, saved, reading):
        history = self.settings.supplier_history
        if (saved.identity.as_dict() != history.identity.as_dict()
                or saved.current_context != history.request.context or saved.action_input != self._input
                or saved.result.kind != 'completed'):
            raise TaskConflict('Material reader changes the selected original Supplier response')
        original_refs = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        for registration in self.registrations.values():
            basis = registration.basis
            shared = [ref.key() for ref in registration.shared_source_refs]
            if (registration.sharing_authorized is not True or len(set(shared)) != len(shared)
                    or set(shared) != original_refs
                    or basis.receiving_task_sha256 != saved.identity.key
                    or basis.receiving_record_sha256 != saved.record_sha256
                    or basis.receiving_result_sha256 != task_digest(saved.result.model_dump(mode='json'))
                    or basis.receiving_source_reading_sha256 != saved.source_reading_sha256):
                raise TaskConflict('Material declaration changes original result or lacks explicit whole-source sharing')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original Supplier receiving sources changed at their authorized read boundary')
        reading.recheck()
        return True

    def read_supplier_receiving(self, *, context, source_task_sha256):
        self._check(context)
        history = self.settings.supplier_history
        if source_task_sha256 != history.identity.key:
            raise TaskConflict('Material reader requires the explicitly selected original Supplier task')
        with self.recipient.read_guard(context), self.supplier.read_guard(history.request.context):
            prepared = self.assembler.build(history.request.context, **self._input.model_dump(mode='json'))
            try:
                saved = self.worker.read_completed(history.identity, current_context=history.request.context,
                    reading=prepared.reading, execution_versions=prepared_action_execution_versions(prepared,
                        client_version=history.client_version, model_version=history.model_version),
                    validate_current=lambda value: self._validate_history(value, prepared.reading))
                self._check(context)
                return saved
            finally:
                prepared.reading.recheck()
                self._check(context)

    def validate_reception(self, *, saved, basis, receipt, component, inventory, batch, context):
        self._check(context)
        registration = self.registrations.get(basis.ref.key())
        if registration is None:
            raise TaskConflict('Material reception requires the selected independent receiver registration')
        original = self.read_supplier_receiving(context=context,
            source_task_sha256=self.settings.supplier_history.identity.key)
        expected_native = {
            'schema_version': 'contractor-material-stock-mapping.v1', 'run_id': basis.run_id,
            'organization_id': basis.organization_id, 'receipt_ref': basis.receipt_ref.model_dump(mode='json'),
            'component_ref': basis.component_ref.model_dump(mode='json'), 'physical_slice_key': basis.physical_slice_key,
            'use_release_refs': [ref.model_dump(mode='json') for ref in basis.use_release_refs],
            'use_code': basis.use_code, 'inventory_ref': basis.inventory_ref.model_dump(mode='json'),
            'inventory_sha256': basis.inventory_sha256, 'batch_ref': basis.batch_ref.model_dump(mode='json'),
            'batch_sha256': basis.batch_sha256, 'received_at': basis.received_at.model_dump(mode='json'),
        }
        if (saved != original or registration.current_state != 'received'
                or basis != registration.basis or inventory != registration.inventory or batch != registration.batch
                or basis.organization_id != self.settings.source_projection['organization_id']
                or registration.recipient_actor_id != context.actor_id
                or registration.recipient_function_ref != context.function_ref
                or registration.recipient_authorization_refs != context.authorization_refs
                or registration.native_record != expected_native
                or task_digest(registration.native_record) != basis.native_record_sha256
                or task_digest(inventory.model_dump(mode='json')) != basis.inventory_sha256
                or task_digest(batch.model_dump(mode='json')) != basis.batch_sha256):
            raise TaskConflict('Independent receiver changes its native mapping, current stock or recipient permission')
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}

        def source(ref, schema):
            value = schema.model_validate(originals[ref.key()])
            if value.ref != ref:
                raise TaskConflict('Material authority changes original source identity')
            return value

        party = source(receipt.receiving_party_ref, SupplierReceivingPartyView)
        mandate = source(party.mandate_ref, SupplierReceivingMandateView)
        order = source(party.order_ref, SupplierLogisticsOrderView)
        if (party.organization_id != basis.organization_id or party.authority_ref != receipt.author_authority_ref
                or party.actor_id != receipt.author_actor_id or party.function_ref != receipt.author_function_ref
                or not {'receipt', 'inspection', 'use_release'} <= set(party.allowed_purposes)
                or not {'receipt', 'inspection', 'use_release'} <= set(mandate.allowed_purposes)
                or mandate.receiving_party_ref != party.ref or mandate.recipient_organization_id != party.organization_id
                or mandate.order_ref != order.ref or mandate.author_organization_id != order.buyer_id
                or party.permitted.model_dump() != {'state': 'known', 'value': True}
                or mandate.permitted.model_dump() != {'state': 'known', 'value': True}):
            raise TaskConflict('Material reception lacks independent receiving, inspection and use-release rights')
        roles = {'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'ENGINEER': 'Engineer',
            'ARCHITECT': 'Architect', 'QS': 'QS', 'GOV': 'Government', 'SUPPLIER': 'Supplier'}

        def authorize(record):
            grant = source(record.author_authority_ref, Authorization)
            assignment = originals[record.author_function_ref.key()]
            assignment = RoleAssignment.model_validate(assignment)
            if (grant.organization_id != record.author_organization_id or grant.actor_id != record.author_actor_id
                    or grant.function_ref != record.author_function_ref or record.author_action_id not in grant.action_ids
                    or assignment.function_ref != record.author_function_ref
                    or assignment.role != roles.get(record.author_action_id.split('-')[0])
                    or not grant.validity.contains(record.authored_at)
                    or not any(scope_covers(scope, record.scope) for scope in grant.scopes)):
                raise TaskConflict('Material reception lacks original independent author authority')

        authorize(mandate)
        for ref in basis.use_release_refs:
            release = source(ref, SupplierGoodsUseReleaseView)
            inspection = source(release.inspection_ref, SupplierReceiptInspectionView)
            method = source(inspection.method_ref, SupplierGoodsInspectionMethodView)
            if (method.supported.model_dump() != {'state': 'known', 'value': True}
                    or inspection.author_action_id not in method.allowed_author_action_ids
                    or component.product_ref not in method.product_refs
                    or basis.use_code not in method.use_codes):
                raise TaskConflict('Material reception lacks an applicable independent goods inspection method')
            for record in (receipt, inspection, release):
                if (record.receiving_party_ref != party.ref or record.author_organization_id != party.organization_id
                        or record.author_actor_id != party.actor_id or record.author_function_ref != party.function_ref
                        or record.author_authority_ref != party.authority_ref
                        or record.author_action_id not in party.allowed_action_ids
                        or not scope_covers(party.scope, record.scope)
                        or not mandate.effective_window.contains(record.authored_at)):
                    raise TaskConflict('Material reception substitutes independent actual inspection/use author')
                authorize(record)
            if release.authored_at.offset < inspection.authored_at.offset:
                raise TaskConflict('Material use release predates independent inspection')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.recipient.evidence()), 'schema_version': self.VERSION,
            'configuration_sha256': self._digest,
            'supplier_task_sha256': self.settings.supplier_history.identity.key,
            'registrations_sha256': task_digest([row.model_dump(mode='json') for row in self.settings.registrations]),
            'limitations': ['Explicit synthetic receiver mappings from an existing Supplier journal.',
                'No native receipt, stock, allocation, work or professional result created.']}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self.supplier.close()
            finally:
                self.recipient.close()


def build_sources(*, request, output_directory, offline, settings):
    """Attach original Supplier reader and independent receiver checks without executing actions."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = ContractorSupplierReceivingFixtureSettings.model_validate(settings).model_copy(deep=True)
    history = settings.supplier_history
    supplier_journal = Path(history.source_settings.journal_path).resolve()
    context = request.context
    if (offline is not True or context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or context.contract_ref.id != 'CONTRACTOR-A07' or settings.action_id != 'CONTRACTOR-A07'
            or history.identity.run_id != context.run_id or history.identity.role != 'Supplier'
            or history.identity.action_id != 'SUPPLIER-A09' or history.identity.purpose != 'action'
            or history.source_settings.action_id != 'SUPPLIER-A09'
            or history.request.context.run_id != context.run_id
            or history.request.context.contract_ref.id != 'SUPPLIER-A09'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or history.request.context.scope != context.scope
            or history.request.context.business_time.clock_ref != context.business_time.clock_ref
            or history.request.context.business_time.offset > context.business_time.offset
            or history.identity.organization_id == settings.source_projection['organization_id']
            or supplier_journal == Path(settings.journal_path).resolve() or not supplier_journal.is_file()):
        raise ValueError('Material intake requires a separate existing same-run Supplier A09 journal and Contractor A07')
    if (len({row.basis.ref.key() for row in settings.registrations}) != len(settings.registrations)
            or len({row.registration_id for row in settings.registrations}) != len(settings.registrations)):
        raise ValueError('Material intake repeats independent registration identities')
    recipient, supplier = None, None
    try:
        recipient = build_contractor_sources(request=request, output_directory=output_directory, offline=True,
            settings=settings.model_dump(mode='json', exclude={'supplier_history', 'registrations'}))
        supplier_factory = (build_linked_supplier_sources if isinstance(history.source_settings,
            SupplierLogisticsReceivingFixtureSettings) else build_supplier_sources)
        supplier = supplier_factory(request=history.request, output_directory=output_directory, offline=True,
            settings=history.source_settings)
        binding = _MaterialReception(request, settings, recipient, supplier)
        return replace(recipient, version=binding.VERSION, read_supplier_receiving=binding.read_supplier_receiving,
            validate_received_materials=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if supplier is not None:
                supplier.close()
        finally:
            if recipient is not None:
                recipient.close()
        raise
