"""Borrow original formal Architect A07 results and receipts for Government intake."""
from copy import deepcopy
from dataclasses import replace
from typing import Annotated

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.architect_deliverable_actions import ArchitectDeliverableActionAssembler
from integration.architect_deliverable_results import ArchitectDeliverableResultWorker, SavedArchitectDeliverable
from integration.architect_submission_host import ArchitectSubmissionHost
from integration.government_role_contract_host import GovernmentRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ArchitectPublicationReaderSettings(StrictRecord):
    architect_request: RoleContractInvocation
    recipient_context: ActionContext
    identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    publication_receipt_sha256: Digest
    publication_recipient_id: TextId
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    sharing_authorized: bool

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ArchitectPublicationReader:
    """Original producer components remain owned by the actual application.

    Read only saved results and confirmed receipts; never execute, submit,
    recover or query transport. The independent Government reception validator
    still checks native material, recipient mapping and authority. Publication
    acceptance supplies no regulatory approval, registered case or use release.
    """

    def __init__(self, *, settings, worker, assembler, submission_host, validate_sharing):
        self.settings = ArchitectPublicationReaderSettings.model_validate(settings).model_copy(deep=True)
        self.worker, self.assembler, self.submission_host = worker, assembler, submission_host
        self.validate_sharing = validate_sharing
        if (not isinstance(worker, ArchitectDeliverableResultWorker)
                or not isinstance(assembler, ArchitectDeliverableActionAssembler)
                or not isinstance(submission_host, ArchitectSubmissionHost) or not callable(validate_sharing)):
            raise ValueError('Architect publication reader requires original formal components and sharing validator')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = self._current_components()
        self._check()

    def _current_components(self):
        worker, assembler = self.worker, self.assembler
        return (worker, assembler, self.submission_host, worker.store, worker.snapshots, worker.registry,
            assembler.organizations, assembler.provider, self.validate_sharing)

    def _check(self):
        settings, worker, assembler, host = self.settings, self.worker, self.assembler, self.submission_host
        own, recipient, identity = settings.architect_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(self._current_components(), self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or worker.ACTION_ID != 'ARCHITECT-A07' or assembler.ACTION_ID != 'ARCHITECT-A07'
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider or worker.snapshots.store is not worker.store
                or host.store is not worker.store or host.registry is not worker.registry
                or host.workers.get('ARCHITECT-A07') is not worker or worker.store.path is None
                or worker.store.run_id != identity.run_id or assembler.organizations.run_id != identity.run_id
                or own.run_id != identity.run_id or recipient.run_id != identity.run_id
                or identity.role != 'Architect' or identity.action_id != 'ARCHITECT-A07' or identity.purpose != 'action'
                or own.contract_ref.id != 'ARCHITECT-A07' or recipient.contract_ref.id != 'GOV-A02'
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or own.scope != recipient.scope or own.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Architect publication reader changes original components, authority or sharing selection')
        host._check()
        grants = assembler.organizations.grants(own, 'ARCHITECT-A07', 'Architect')
        if grants[0].organization_id != identity.organization_id:
            raise TaskConflict('Architect publication reader changes its original producer organization')

    def _validate_saved(self, saved, reading):
        settings = self.settings
        refs = {ref.key() for ref in settings.shared_source_refs}
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        if (not isinstance(saved, SavedArchitectDeliverable) or saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.architect_request.context
                or saved.action_input.model_dump(mode='json') != settings.architect_request.action_input
                or saved.record_sha256 != settings.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or saved.audit['reading'].get('source_mode') != 'formal'
                or saved.result.kind != 'completed' or saved.result.payload.choice not in {'submit', 'request_review'}
                or settings.publication_recipient_id not in saved.result.payload.recipient_ids
                # The returned saved record contains every original source.
                or refs != originals or saved.action_input.deliverable_ref.key() not in refs):
            raise TaskConflict('Architect publication reader substitutes original deliverable, recipient or shared sources')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original deliverable source differs from current authorized Architect source')
        reading.recheck()
        if self.validate_sharing(saved=deepcopy(saved), context=settings.recipient_context.model_copy(deep=True),
                publication_recipient_id=settings.publication_recipient_id,
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not confirm actual Architect publication recipient and sharing permission')
        self._check()
        return True

    def read(self, *, context, source_task_sha256, publication_receipt_sha256):
        self._check()
        settings = self.settings
        if (ActionContext.model_validate(context) != settings.recipient_context
                or source_task_sha256 != settings.identity.key
                or publication_receipt_sha256 != settings.publication_receipt_sha256):
            raise TaskConflict('Architect reader requires exact Government recipient, task and publication receipt')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            prepared = self.assembler.build(settings.architect_request.context, **deepcopy(settings.architect_request.action_input))
            try:
                saved = self.worker.read_completed(settings.identity,
                    current_context=settings.architect_request.context, reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda value: self._validate_saved(value, prepared.reading))
            finally:
                prepared.reading.recheck()
                self._check()
        # read_receipt owns its own guard; the application's lock need not be reentrant.
        publication = self.submission_host.read_receipt(settings.identity)
        native = publication.get('receipt', {})
        if (publication.get('schema_version') != 'architect-deliverable-saved-receipt.v1'
                or publication.get('identity') != settings.identity.as_dict()
                or publication.get('record_sha256') != settings.source_record_sha256
                or publication.get('receipt_sha256') != settings.publication_receipt_sha256
                or task_digest(native) != settings.publication_receipt_sha256
                or not native.get('receipt_id') or 'original_receipt' not in native
                or any(native.get(key) != value for key, value in {
                    'run_id': settings.identity.run_id, 'organization_id': settings.identity.organization_id,
                    'request_id': settings.identity.request_id, 'task_sha256': task_digest(settings.identity.as_dict()),
                    'output_sha256': settings.source_result_sha256, 'disposition': 'accepted'}.items())):
            raise TaskConflict('Architect reader lacks original confirmed accepted publication receipt')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            try:
                self._validate_saved(saved, prepared.reading)
                return deepcopy(saved), deepcopy(publication)
            finally:
                prepared.reading.recheck()
                self._check()
                if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                    raise TaskConflict('Architect reader changed original current source snapshot')


def bind_architect_material_sources(*, sources, reader, validate_reception, version):
    """Bind the original publication reader and independent Government validator."""
    if (not isinstance(sources, GovernmentRoleContractSources) or not isinstance(reader, ArchitectPublicationReader)
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Material binding requires Government sources, original Architect reader, validator and version')
    if sources.read_architect_publication is not None or sources.validate_architect_reception is not None:
        raise TaskConflict('Material binding cannot replace original application callbacks')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Architect material binding changes the original recipient run')
        registration = sources.registry.get('GOV-A02')
        grants = sources.organizations.grants(recipient, 'GOV-A02', 'Government')
        organization = grants[0].organization_id
        if (registration.role != 'Government' or not registration.implemented or registration.skill is None
                or organization == reader.settings.identity.organization_id):
            raise TaskConflict('Material binding requires current independent Government recipient authority')
        return organization

    recipient_org = check_binding()
    declaration = {'schema_version': 'v3-architect-material-binding.v1', 'run_id': recipient.run_id,
        'recipient_organization_id': recipient_org,
        'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, 'read_architect_publication'),
        'receiver_validator': module_factory_descriptor(validate_reception, 'validate_architect_reception'),
        'bound_source_version': version}

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Material binding changes original recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or 'v3_architect_material_binding' in original:
            raise TaskConflict('Material binding requires original application evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Material source evidence changed current recipient authority')
        return {**deepcopy(original), 'v3_architect_material_binding': deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        read_architect_publication=reader.read, validate_architect_reception=validate_reception)
