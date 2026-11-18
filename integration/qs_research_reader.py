"""Read original formal QS research under current producer and recipient authority."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Annotated, Callable, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.module_host import module_factory_descriptor
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.qs_research_actions import QSResearchActionAssembler
from integration.qs_research_results import QSResearchResultWorker, SavedQSResearch
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class QSResearchReaderSettings(StrictRecord):
    qs_request: RoleContractInvocation
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


class QSResearchReader:
    """Borrow the actual QS journal, assembler, guard and sharing validator.

    A saved comparison proves no publication or investment approval. Actual
    research reception and exact option mapping remain separately checked by
    OwnerRoleContractSources.validate_research_reception. No model, replay,
    receipt creation, transport or native mutation occurs here.

    The original archive is returned intact. shared_source_refs must therefore
    list every archived source; validate_sharing must authorize the complete
    saved record and audit for the exact current recipient.
    """

    SETTINGS_TYPE = QSResearchReaderSettings
    WORKER_TYPE = QSResearchResultWorker
    ASSEMBLER_TYPE = QSResearchActionAssembler
    SAVED_TYPE = SavedQSResearch
    SOURCE_ACTION_ID = 'QS-A13'
    RECIPIENT_ACTION_ID = 'OWN-A03'
    EXPECTED_CHOICES = frozenset({'compare', 'cannot_rank', 'deliver_at_limit'})

    def __init__(self, *, settings, worker, assembler, read_guard, validate_sharing):
        self.settings = self.SETTINGS_TYPE.model_validate(settings).model_copy(deep=True)
        self.worker, self.assembler = worker, assembler
        self.read_guard, self.validate_sharing = read_guard, validate_sharing
        if (not isinstance(worker, self.WORKER_TYPE)
                or not isinstance(assembler, self.ASSEMBLER_TYPE)
                or not callable(read_guard) or not callable(validate_sharing)):
            raise ValueError('QS research reader requires original formal components and independent sharing validation')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = self._current_components()
        self._check()

    def _current_components(self):
        worker, assembler = self.worker, self.assembler
        return (worker, assembler, worker.store, worker.snapshots, worker.registry,
            assembler.organizations, assembler.provider, self.read_guard, self.validate_sharing)

    def _check(self):
        settings, worker, assembler = self.settings, self.worker, self.assembler
        own, recipient, identity = settings.qs_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(self._current_components(), self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or worker.ACTION_ID != self.SOURCE_ACTION_ID or assembler.ACTION_ID != self.SOURCE_ACTION_ID
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider or worker.snapshots.store is not worker.store
                or worker.store.path is None or worker.store.run_id != identity.run_id
                or assembler.organizations.run_id != identity.run_id or own.run_id != identity.run_id
                or recipient.run_id != identity.run_id or identity.role != 'QS'
                or identity.action_id != self.SOURCE_ACTION_ID or identity.purpose != 'action'
                or own.contract_ref.id != self.SOURCE_ACTION_ID or recipient.contract_ref.id != self.RECIPIENT_ACTION_ID
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or own.scope != recipient.scope or own.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Formal research reader changes original components, authority or sharing selection')
        producer_grants = assembler.organizations.grants(own, self.SOURCE_ACTION_ID, 'QS')
        if producer_grants[0].organization_id != identity.organization_id:
            raise TaskConflict('Research reader changes the original authorized QS organization')

    def required_shared_refs(self, saved):
        return {ref.key() for ref in saved.result.payload.comparison.option_refs}

    def _validate_saved(self, saved, reading):
        settings = self.settings
        refs = {ref.key() for ref in settings.shared_source_refs}
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        if (not isinstance(saved, self.SAVED_TYPE) or saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.qs_request.context
                or saved.action_input.model_dump(mode='json') != settings.qs_request.action_input
                or saved.record_sha256 != settings.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or saved.audit['reading'].get('source_mode') != 'formal'
                or saved.result.kind != 'completed'
                or saved.result.payload.choice not in self.EXPECTED_CHOICES
                or refs != originals
                or not self.required_shared_refs(saved) <= refs):
            raise TaskConflict('Formal research reader substitutes original report or selected shared options')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original research source differs from current authorized QS source')
        reading.recheck()
        if self.validate_sharing(saved=deepcopy(saved), context=settings.recipient_context.model_copy(deep=True),
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not confirm actual current QS research sharing permission')
        self._check()
        return True

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Formal research reader requires its exact Owner recipient and original task')
        with self.read_guard(settings.qs_request.context.model_copy(deep=True)):
            self._check()
            prepared = self.assembler.build(settings.qs_request.context, **deepcopy(settings.qs_request.action_input))
            try:
                saved = self.worker.read_completed(settings.identity,
                    current_context=settings.qs_request.context, reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda value: self._validate_saved(value, prepared.reading))
                return deepcopy(saved)
            finally:
                prepared.reading.recheck()
                self._check()
                if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                    raise TaskConflict('Research reader changed the original current QS source snapshot')


def bind_research_reception_sources(*, sources, reader, validate_reception, version):
    """Attach the original reader and independent receiver validator to Owner sources."""
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(reader, QSResearchReader)
            or reader.SOURCE_ACTION_ID != 'QS-A13' or reader.RECIPIENT_ACTION_ID != 'OWN-A03'
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Research binding requires Owner sources, original QS reader, receiver validator and version')
    if sources.read_qs_research is not None or sources.validate_research_reception is not None:
        raise TaskConflict('Research binding cannot replace an existing application reader or validator')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Research binding changes the original recipient run')
        registration = sources.registry.get('OWN-A03')
        grants = sources.organizations.grants(recipient, 'OWN-A03', 'Owner')
        organization = grants[0].organization_id
        if (registration.role != 'Owner' or not registration.implemented or registration.skill is None
                or organization == reader.settings.identity.organization_id):
            raise TaskConflict('Research binding requires current Owner authority and an independent QS party')
        return organization

    recipient_org = check_binding()
    declaration = {'schema_version': 'v1-research-source-binding.v1', 'run_id': recipient.run_id,
        'recipient_organization_id': recipient_org,
        'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, 'read_qs_research'),
        'receiver_validator': module_factory_descriptor(validate_reception, 'validate_research_reception'),
        'bound_source_version': version}

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Research binding changes the original recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or 'v1_research_binding' in original:
            raise TaskConflict('Research binding requires original application evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Research source evidence changed recipient authority')
        return {**deepcopy(original), 'v1_research_binding': deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        read_qs_research=reader.read, validate_research_reception=validate_reception)


_SOURCE_VERSION = 'configured-v1-formal-research-sources.v1'


class V1ResearchSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v1-research-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V1ResearchApplication:
    """Actual application components; sources.close owns all returned resources.

    The application owns partial cleanup before successful return, including
    producer resources used by the borrowed reader. No model is called while
    opening these sources or assembling the reader.
    """
    version: str
    sources: OwnerRoleContractSources
    reader: QSResearchReader
    validate_reception: Callable

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, OwnerRoleContractSources)
                or not isinstance(self.reader, QSResearchReader) or not callable(self.validate_reception)):
            raise ValueError('V1 application requires actual Owner sources, original QS reader and reception validator')


def build_sources(*, request, output_directory, offline, settings):
    """Source-factory entry point for the existing formal Owner role host.

    Load one explicitly configured actual application; retain its resources,
    guards and source evidence. Actual reception remains independently checked
    by the original Owner host, rather than inferred from successful assembly.
    """
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V1ResearchSourceSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != 'OWN-A03' or request.execution_path == 'deterministic'):
        raise ValueError('V1 research sources require an explicit formal Owner A03 invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V1 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V1 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V1 research sources require a distinct actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V1ResearchApplication):
        raise ValueError('V1 factory must return V1ResearchApplication and own partial cleanup')
    try:
        if (application.version != settings.application_version
                or application.reader.settings.recipient_context != request.context
                or module_factory_descriptor(factory, specification) != descriptor):
            raise TaskConflict('V1 application changes declared version, recipient or original factory')
        bound = bind_research_reception_sources(sources=application.sources, reader=application.reader,
            validate_reception=application.validate_reception, version=_SOURCE_VERSION)
        declaration = {'schema_version': 'lifecycle-v1-application-source.v1',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'source_settings_sha256': settings_sha256,
            'request_sha256': task_digest(request.model_dump(mode='json'))}

        def evidence():
            if (application.version != settings.application_version
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor):
                raise TaskConflict('V1 actual application source configuration or factory changed')
            original = bound.evidence()
            if 'v1_application_source' in original:
                raise TaskConflict('V1 source evidence cannot replace original application provenance')
            return {**original, 'v1_application_source': deepcopy(declaration)}

        return replace(bound, evidence=evidence)
    except Exception:
        application.sources.close()
        raise
