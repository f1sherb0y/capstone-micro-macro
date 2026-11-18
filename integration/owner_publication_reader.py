"""Shared guarded reader for original formal Owner publications and saved receipts."""
from copy import deepcopy
from typing import Annotated

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.owner_observation_actions import OwnerObservationActionAssembler
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.owner_submission_host import OwnerSubmissionHost
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerPublicationReaderSettings(StrictRecord):
    """Current Owner authority and independently declared sharing selection."""
    owner_request: RoleContractInvocation
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


class OwnerPublicationReader:
    """Borrow original components; run no processor, transport or ledger write.

    Concrete readers declare their original action and recipient route. The Owner
    submission host supplies the original current source/authority guard. The
    independent validate_sharing callback confirms actual recipient visibility;
    Contractor reception and agreement mapping retain their separate validator.
    Application resources remain owned and closed by the application.

    Returned sources carry the complete original archive, so shared_source_refs
    must cover every archived source. validate_sharing authorizes the complete
    saved record, including its audit, for the exact current recipient.
    """

    ACTION_ID = None
    RECIPIENT_ACTION_ID = None
    EXPECTED_CHOICES = frozenset()
    RECEIPT_SCHEMA = None
    PUBLICATION_SOURCE_TYPE = None
    SETTINGS_TYPE = OwnerPublicationReaderSettings
    WORKER_TYPE = OwnerObservationResultWorker
    ASSEMBLER_TYPE = OwnerObservationActionAssembler

    def required_shared_refs(self, saved):
        return set()

    def __init__(self, *, settings, worker, assembler, submission_host, validate_sharing):
        self.settings = self.SETTINGS_TYPE.model_validate(settings).model_copy(deep=True)
        self.worker, self.assembler, self.submission_host = worker, assembler, submission_host
        self.validate_sharing = validate_sharing
        if (not isinstance(worker, self.WORKER_TYPE)
                or not isinstance(assembler, self.ASSEMBLER_TYPE)
                or not isinstance(submission_host, OwnerSubmissionHost) or not callable(validate_sharing)):
            raise ValueError('Owner publication reader requires original formal components and sharing validator')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = (worker, assembler, submission_host, worker.store, worker.snapshots, worker.registry, assembler.organizations,
            assembler.provider, validate_sharing)
        self._check()

    def _check(self):
        settings, worker, assembler, host = self.settings, self.worker, self.assembler, self.submission_host
        current = (worker, assembler, host, worker.store, worker.snapshots, worker.registry, assembler.organizations,
            assembler.provider, self.validate_sharing)
        owner, recipient, identity = settings.owner_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(current, self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider
                or host.store is not worker.store or host.registry is not worker.registry
                or host.workers.get(self.ACTION_ID) is not worker or worker.snapshots.store is not worker.store
                or worker.store.path is None or assembler.organizations.run_id != identity.run_id
                or host.store.run_id != identity.run_id or owner.run_id != identity.run_id
                or recipient.run_id != identity.run_id or identity.role != 'Owner'
                or identity.action_id != self.ACTION_ID or identity.purpose != 'action'
                or owner.contract_ref.id != self.ACTION_ID or recipient.contract_ref.id != self.RECIPIENT_ACTION_ID
                or owner.execution_mode == 'offline_fixture' or recipient.execution_mode == 'offline_fixture'
                or owner.scope != recipient.scope or owner.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Formal Owner publication reader changed original components, current authority or sharing selection')
        host._check()

    def _validate_saved(self, saved, reading):
        settings = self.settings
        refs = {ref.key() for ref in settings.shared_source_refs}
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        if (saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.owner_request.context
                or saved.action_input.model_dump(mode='json') != settings.owner_request.action_input
                or saved.record_sha256 != settings.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or saved.audit['reading'].get('source_mode') != 'formal'
                or saved.result.kind != 'completed' or saved.result.payload.choice not in self.EXPECTED_CHOICES
                or refs != originals
                or not self.required_shared_refs(saved) <= refs):
            raise TaskConflict('Formal Owner publication reader substitutes original decision or shared agreement sources')
        self._validate_current_sources(saved, reading)
        reading.recheck()
        if self.validate_sharing(saved=deepcopy(saved), context=settings.recipient_context.model_copy(deep=True),
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not confirm actual current Owner publication sharing permission')
        return True

    def _validate_current_sources(self, saved, reading):
        """Default publications require unchanged original authorized projections."""
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original Owner publication source differs from current authorized Owner source')

    def read(self, *, context, source_task_sha256):
        self._check()
        recipient = ActionContext.model_validate(context).model_copy(deep=True)
        settings = self.settings
        if recipient != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Formal Owner publication reader requires its exact current recipient and original task')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            prepared = self.assembler.build(settings.owner_request.context,
                **deepcopy(settings.owner_request.action_input))
            try:
                saved = self.worker.read_completed(settings.identity,
                    current_context=settings.owner_request.context, reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda saved: self._validate_saved(saved, prepared.reading))
            finally:
                prepared.reading.recheck()
                self._check()
        # read_receipt owns its guard; do not require an application lock to be reentrant.
        publication = self.submission_host.read_receipt(settings.identity)
        receipt = publication.get('receipt', {})
        if (publication.get('schema_version') != self.RECEIPT_SCHEMA
                or publication.get('identity') != saved.identity.as_dict()
                or publication.get('record_sha256') != saved.record_sha256
                or publication.get('receipt_sha256') != task_digest(receipt)
                or receipt.get('disposition') != 'accepted'
                or any(receipt.get(key) != value for key, value in {
                    'run_id': saved.identity.run_id, 'organization_id': saved.identity.organization_id,
                    'request_id': saved.identity.request_id, 'task_sha256': task_digest(saved.identity.as_dict()),
                    'output_sha256': settings.source_result_sha256}.items())):
            raise TaskConflict('Formal Owner publication reader lacks its original confirmed accepted publication receipt')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            self._validate_saved(saved, prepared.reading)
            return self.PUBLICATION_SOURCE_TYPE(saved=saved, submission_host=self.submission_host)
