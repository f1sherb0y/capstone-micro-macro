"""Select actual original A07 review submissions for the existing A08 intake gates."""
from copy import deepcopy
from dataclasses import replace

from pydantic import field_validator

from integration.architect_deliverable_results import ArchitectDeliverableResultWorker, SavedArchitectDeliverable
from integration.architect_role_contract_host import ArchitectRoleContractSources
from integration.architect_submission import ArchitectResultSubmission
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, StrictRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ArchitectReviewTaskReaderSettings(StrictRecord):
    identity: TaskIdentity
    submission_read_context: ActionContext
    recipient_context: ActionContext
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    publication_receipt_sha256: Digest

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ArchitectReviewTaskReader:
    """Return original components and guarded validation callbacks, never replay.

    The existing reviewer assembler reads the original worker/receipt using
    separately authorized A07 history, then checks actual task registration and
    personnel independence. Application validators retain sharing, intake and
    receipt-relation decisions; a publication receipt is not review authority.
    All submission resources remain application-owned.
    """

    SETTINGS_TYPE = ArchitectReviewTaskReaderSettings
    WORKER_TYPE = ArchitectDeliverableResultWorker
    SAVED_TYPE = SavedArchitectDeliverable
    SOURCE_ACTION_ID = 'ARCHITECT-A07'
    EXPECTED_CHOICE = 'request_review'
    RECEIPT_SCHEMA = 'architect-deliverable-saved-receipt.v1'
    PARAMETER_PREFIX = 'deliverable'
    READ_CONTEXT_PARAMETER = 'submission_read_context'

    def __init__(self, *, settings, submission, validate_history, validate_current, validate_receipt_relation):
        self.settings = self.SETTINGS_TYPE.model_validate(settings).model_copy(deep=True)
        self.submission = submission
        self.validate_history, self.validate_current = validate_history, validate_current
        self.validate_receipt_relation = validate_receipt_relation
        if (not isinstance(submission, ArchitectResultSubmission)
                or not isinstance(submission.worker, self.WORKER_TYPE)
                or not all(callable(f) for f in (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Review source reader requires original submission and independent application validators')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = self._current_components()
        self._check()

    def _current_components(self):
        submission = self.submission
        return (submission, submission.worker, submission.worker.store, submission.worker.snapshots,
            submission.registry, self.validate_history, self.validate_current, self.validate_receipt_relation)

    def _check(self):
        settings, submission = self.settings, self.submission
        identity, own, recipient = settings.identity, settings.submission_read_context, settings.recipient_context
        if (any(now is not original for now, original in zip(self._current_components(), self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or submission.ACTION_ID != self.SOURCE_ACTION_ID or identity.action_id != self.SOURCE_ACTION_ID
                or identity.role != 'Architect' or identity.purpose != 'action'
                or submission.worker.store.path is None or submission.worker.store.run_id != identity.run_id
                or own.run_id != identity.run_id or recipient.run_id != identity.run_id
                or own.contract_ref.id != self.SOURCE_ACTION_ID or recipient.contract_ref.id != 'ARCHITECT-A08'
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or own.scope != recipient.scope or own.business_time != recipient.business_time):
            raise TaskConflict('Review task reader changes original submission, identity or current reading contexts')
        submission._check_binding()

    def _check_saved(self, saved):
        self._check()
        settings = self.settings
        if (not isinstance(saved, self.SAVED_TYPE) or saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.submission_read_context
                or saved.record_sha256 != settings.source_record_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != self.EXPECTED_CHOICE
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or task_digest(list(saved.source_reading)) != settings.source_reading_sha256
                or saved.audit['reading'].get('source_mode') != 'formal'):
            raise TaskConflict('Review source reader substitutes original result or source history')

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Review source reader requires exact current recipient context and original task')

        def history(saved):
            self._check_saved(saved)
            try:
                return self.validate_history(deepcopy(saved)) is True
            finally:
                self._check_saved(saved)

        def current(**sources):
            self._check_saved(sources['saved'])
            try:
                return self.validate_current(**sources) is True
            finally:
                self._check_saved(sources['saved'])

        def relation(*, receipt, **sources):
            self._check_saved(sources['saved'])
            native = receipt.get('receipt', {})
            if (receipt.get('schema_version') != self.RECEIPT_SCHEMA
                    or receipt.get('identity') != settings.identity.as_dict()
                    or receipt.get('record_sha256') != settings.source_record_sha256
                    or receipt.get('receipt_sha256') != settings.publication_receipt_sha256
                    or task_digest(native) != settings.publication_receipt_sha256
                    or native.get('disposition') != 'accepted'):
                raise TaskConflict('Review task reader substitutes the original confirmed publication receipt')
            receipt_sha256 = task_digest(receipt)
            try:
                return self.validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True
            finally:
                self._check_saved(sources['saved'])
                if task_digest(receipt) != receipt_sha256:
                    raise TaskConflict('Review task relation validator changed its original publication receipt')

        prefix = self.PARAMETER_PREFIX
        return {prefix + '_submission': self.submission,
            prefix + '_identity': TaskIdentity(**settings.identity.as_dict()),
            prefix + '_execution_versions': deepcopy(settings.identity.versions),
            self.READ_CONTEXT_PARAMETER: settings.submission_read_context.model_copy(deep=True),
            'validate_history': history, 'validate_current': current, 'validate_receipt_relation': relation}


def bind_review_task_sources(*, sources, reader, validate_mapping, version):
    """Pair actual source selection and independent reviewer-input mapping."""
    return _bind_review_sources(sources=sources, reader=reader, validate_mapping=validate_mapping, version=version,
        source_action='ARCHITECT-A07', reader_field='read_review_task', validator_field='validate_review_task_mapping',
        schema_version='v3-review-task-source-binding.v1', evidence_field='v3_review_task_binding')


def _bind_review_sources(*, sources, reader, validate_mapping, version,
        source_action, reader_field, validator_field, schema_version, evidence_field):
    if (not isinstance(sources, ArchitectRoleContractSources) or not isinstance(reader, ArchitectReviewTaskReader)
            or reader.SOURCE_ACTION_ID != source_action
            or not callable(validate_mapping) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Review task binding requires actual Architect sources, original reader, mapping and version')
    if getattr(sources, reader_field) is not None or getattr(sources, validator_field) is not None:
        raise TaskConflict('Review task binding cannot replace existing application callbacks')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if (sources.registry is not reader.submission.registry
                or sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id):
            raise TaskConflict('Review task binding changes original registry or recipient run')
        registration = sources.registry.get('ARCHITECT-A08')
        grants = sources.organizations.grants(recipient, 'ARCHITECT-A08', 'Architect')
        own_grants = sources.organizations.grants(reader.settings.submission_read_context, source_action, 'Architect')
        if (registration.role != 'Architect' or not registration.implemented or registration.skill is None
                or own_grants[0].organization_id != reader.settings.identity.organization_id):
            raise TaskConflict('Review task binding changes current separately authorized producer or reviewer')
        return grants[0].organization_id

    recipient_org = check_binding()
    declaration = {'schema_version': schema_version, 'run_id': recipient.run_id,
        'recipient_organization_id': recipient_org,
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, reader_field),
        'mapping_validator': module_factory_descriptor(validate_mapping, validator_field),
        'bound_source_version': version}

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Review task binding changes current recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or evidence_field in original:
            raise TaskConflict('Review task binding requires original source evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Review task evidence changed current recipient authority')
        return {**deepcopy(original), evidence_field: deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        **{reader_field: reader.read, validator_field: validate_mapping})
