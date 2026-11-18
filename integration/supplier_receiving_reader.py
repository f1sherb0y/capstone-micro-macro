"""Borrow original formal Supplier receiving evidence for authorized Contractor use."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Annotated, Callable, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_role_contract_host import ContractorRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_receiving_actions import SupplierReceivingActionAssembler
from integration.supplier_receiving_results import SupplierReceivingResultWorker, SavedSupplierReceiving
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class SupplierReceivingReaderSettings(StrictRecord):
    supplier_request: RoleContractInvocation
    recipient_context: ActionContext
    identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    sharing_authorized: bool

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class SupplierReceivingReader:
    """Read the original journal through the application's Supplier source guard.

    This reader creates no delivery, receipt, inspection, release, inventory or
    allocation. Supplier response choices do not grant material-use rights.
    Original independent customer receipts and actual Contractor stock/mapping
    remain checked by the existing material handoff and receiver validator.
    """

    def __init__(self, *, settings, worker, assembler, read_guard, validate_sharing):
        self.settings = SupplierReceivingReaderSettings.model_validate(settings).model_copy(deep=True)
        self.worker, self.assembler = worker, assembler
        self.read_guard, self.validate_sharing = read_guard, validate_sharing
        if (not isinstance(worker, SupplierReceivingResultWorker)
                or not isinstance(assembler, SupplierReceivingActionAssembler)
                or not callable(read_guard) or not callable(validate_sharing)):
            raise ValueError('Material reader requires original formal Supplier components and sharing validator')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = self._current_components()
        self._check()

    def _current_components(self):
        worker, assembler = self.worker, self.assembler
        return (worker, assembler, worker.store, worker.snapshots, worker.registry,
            assembler.organizations, assembler.provider, self.read_guard, self.validate_sharing)

    def _check(self):
        settings, worker, assembler = self.settings, self.worker, self.assembler
        own, recipient, identity = settings.supplier_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(self._current_components(), self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or worker.ACTION_ID != 'SUPPLIER-A09' or assembler.ACTION_ID != 'SUPPLIER-A09'
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider or worker.snapshots.store is not worker.store
                or worker.store.path is None or worker.store.run_id != identity.run_id
                or assembler.organizations.run_id != identity.run_id or own.run_id != identity.run_id
                or recipient.run_id != identity.run_id or identity.role != 'Supplier'
                or identity.action_id != 'SUPPLIER-A09' or identity.purpose != 'action'
                or own.contract_ref.id != 'SUPPLIER-A09' or recipient.contract_ref.id != 'CONTRACTOR-A07'
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or own.scope != recipient.scope or own.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Material reader changes original components, authority or sharing selection')
        grants = assembler.organizations.grants(own, 'SUPPLIER-A09', 'Supplier')
        if grants[0].organization_id != identity.organization_id:
            raise TaskConflict('Material reader changes original authorized Supplier organization')

    def _validate_saved(self, saved, reading):
        settings = self.settings
        refs = {ref.key() for ref in settings.shared_source_refs}
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        if (not isinstance(saved, SavedSupplierReceiving) or saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.supplier_request.context
                or saved.action_input.model_dump(mode='json') != settings.supplier_request.action_input
                or saved.record_sha256 != settings.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or saved.audit['reading'].get('source_mode') != 'formal' or saved.result.kind != 'completed'
                # The returned saved record contains every original source.
                or refs != originals
                or not refs.intersection(ref.key() for ref in saved.action_input.receipt_refs)):
            raise TaskConflict('Material reader substitutes original Supplier response or shared receipt sources')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original receiving source differs from current authorized Supplier source')
        reading.recheck()
        if self.validate_sharing(saved=deepcopy(saved), context=settings.recipient_context.model_copy(deep=True),
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not confirm actual Supplier receipt sharing permission')
        self._check()
        return True

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Material reader requires exact current Contractor recipient and original Supplier task')
        with self.read_guard(settings.supplier_request.context.model_copy(deep=True)):
            self._check()
            prepared = self.assembler.build(settings.supplier_request.context, **deepcopy(settings.supplier_request.action_input))
            try:
                saved = self.worker.read_completed(settings.identity, current_context=settings.supplier_request.context,
                    reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda value: self._validate_saved(value, prepared.reading))
                return deepcopy(saved)
            finally:
                prepared.reading.recheck()
                self._check()
                if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                    raise TaskConflict('Material reader changed original current Supplier source snapshot')


def bind_received_material_sources(*, sources, reader, validate_reception, version):
    """Bind original receiving evidence and actual Contractor stock/use validation."""
    if (not isinstance(sources, ContractorRoleContractSources) or not isinstance(reader, SupplierReceivingReader)
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Material binding requires actual Contractor sources, original reader, validator and version')
    if sources.read_supplier_receiving is not None or sources.validate_received_materials is not None:
        raise TaskConflict('Material binding cannot replace existing application callbacks')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Material binding changes original recipient run')
        registration = sources.registry.get('CONTRACTOR-A07')
        grants = sources.organizations.grants(recipient, 'CONTRACTOR-A07', 'Contractor')
        organization = grants[0].organization_id
        if (registration.role != 'Contractor' or not registration.implemented or registration.skill is None
                or organization == reader.settings.identity.organization_id):
            raise TaskConflict('Material binding requires current independent Contractor authority')
        return organization

    recipient_org = check_binding()
    declaration = {'schema_version': 'v4-received-material-source-binding.v1', 'run_id': recipient.run_id,
        'recipient_organization_id': recipient_org,
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, 'read_supplier_receiving'),
        'receiver_validator': module_factory_descriptor(validate_reception, 'validate_received_materials'),
        'bound_source_version': version}

    def reception(**material):
        if check_binding() != recipient_org or material['context'] != recipient:
            raise TaskConflict('Material receiver changed original current Contractor authority')
        saved = material['saved']
        if saved.identity.as_dict() != reader.settings.identity.as_dict():
            raise TaskConflict('Material receiver substituted selected original Supplier task')
        required = {material['receipt'].ref.key(), material['component'].ref.key(),
            material['receipt'].receiving_party_ref.key(), *(ref.key() for ref in material['basis'].use_release_refs)}
        if not required <= {ref.key() for ref in reader.settings.shared_source_refs}:
            raise TaskConflict('Material receiver selected original receipt/component/use sources outside authorized sharing')
        try:
            return validate_reception(**material) is True
        finally:
            if check_binding() != recipient_org:
                raise TaskConflict('Material receiver validation changed original recipient authority')

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Material binding changes original recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or 'v4_received_material_binding' in original:
            raise TaskConflict('Material binding requires original application evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Material evidence changed current recipient authority')
        return {**deepcopy(original), 'v4_received_material_binding': deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        read_supplier_receiving=reader.read, validate_received_materials=reception)


_SOURCE_VERSION = 'configured-v4-formal-material-sources.v1'


class V4MaterialSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v4-material-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V4MaterialApplication:
    """Actual application resources; sources.close owns all successful returns.

    The application owns partial cleanup before returning, including original
    Supplier resources borrowed by the reader. Source assembly calls no action
    or model and creates no receiving, inventory, release or allocation fact.
    """
    version: str
    sources: ContractorRoleContractSources
    reader: SupplierReceivingReader
    validate_reception: Callable

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, ContractorRoleContractSources)
                or not isinstance(self.reader, SupplierReceivingReader) or not callable(self.validate_reception)):
            raise ValueError('V4 application requires actual Contractor sources, original Supplier reader and material validator')


def build_sources(*, request, output_directory, offline, settings):
    """Configured formal source-factory entry point for the original Contractor host."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V4MaterialSourceSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != 'CONTRACTOR-A07' or request.execution_path == 'deterministic'):
        raise ValueError('V4 material factory requires an explicit formal Contractor A07 invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V4 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V4 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V4 source factory requires a distinct actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V4MaterialApplication):
        raise ValueError('V4 application must return V4MaterialApplication and own partial cleanup')
    original_sources = application.sources
    components = (original_sources, application.reader, application.validate_reception)
    try:
        if (application.version != settings.application_version
                or application.reader.settings.recipient_context != request.context
                or module_factory_descriptor(factory, specification) != descriptor):
            raise TaskConflict('V4 application changes declared version, recipient or original factory')
        bound = bind_received_material_sources(sources=original_sources, reader=application.reader,
            validate_reception=application.validate_reception, version=_SOURCE_VERSION)
        declaration = {'schema_version': 'lifecycle-v4-application-source.v1',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'source_settings_sha256': settings_sha256,
            'request_sha256': task_digest(request.model_dump(mode='json'))}

        def evidence():
            current = (application.sources, application.reader, application.validate_reception)
            if (any(now is not original for now, original in zip(current, components))
                    or application.version != settings.application_version
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor):
                raise TaskConflict('V4 actual application components, configuration or factory changed')
            original = bound.evidence()
            if 'v4_application_source' in original:
                raise TaskConflict('V4 source evidence cannot replace original application provenance')
            return {**original, 'v4_application_source': deepcopy(declaration)}

        return replace(bound, evidence=evidence)
    except Exception:
        original_sources.close()
        raise
