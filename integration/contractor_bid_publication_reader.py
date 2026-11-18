"""Borrow formal original Contractor bid evidence for authorized Owner intake."""
from copy import deepcopy
from typing import Annotated

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_owner_tender_handoff import ContractorBidJournalSource
from integration.contractor_submission_host import ContractorSubmissionHost
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ContractorBidSourceRecord(StrictRecord):
    ref: Reference
    projection: dict


class ContractorBidPublicationReaderSettings(StrictRecord):
    contractor_request: RoleContractInvocation
    recipient_context: ActionContext
    identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_snapshot_sha256: Digest
    source_audit_reading_sha256: Digest
    original_source_reading: Annotated[list[ContractorBidSourceRecord], Field(min_length=1)]
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    sharing_authorized: bool

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ContractorBidPublicationReader:
    """Wire ``read`` to OwnerRoleContractSources.read_contractor_bid.

    Application supplies original persistent components and independent sharing
    validation. The A02 witness comes from its original execution output, since
    its journal retains only the audit digest. No source reconstruction, bid
    replay, submission, query transport or resource ownership is introduced.
    Owner intake retains its separate actual native-bid/evidence validator.
    """

    def __init__(self, *, settings, worker, assembler, submission_host, validate_sharing):
        self.settings = ContractorBidPublicationReaderSettings.model_validate(settings).model_copy(deep=True)
        self.worker, self.assembler, self.submission_host = worker, assembler, submission_host
        self.validate_sharing = validate_sharing
        if (not isinstance(worker, ContractorBidResultWorker) or worker.ACTION_ID != 'CONTRACTOR-A02'
                or not isinstance(assembler, ContractorBidActionAssembler)
                or not isinstance(submission_host, ContractorSubmissionHost) or not callable(validate_sharing)):
            raise ValueError('Bid publication reader requires original formal components and sharing validator')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._components = (worker, assembler, submission_host, worker.store, worker.snapshots, worker.registry,
            assembler.organizations, assembler.provider, validate_sharing)
        self._check()

    def _check(self):
        settings, worker, assembler, host = self.settings, self.worker, self.assembler, self.submission_host
        current = (worker, assembler, host, worker.store, worker.snapshots, worker.registry,
            assembler.organizations, assembler.provider, self.validate_sharing)
        own, recipient, identity = settings.contractor_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(current, self._components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider
                or host.store is not worker.store or host.registry is not worker.registry
                or host.workers.get('CONTRACTOR-A02') is not worker or worker.snapshots.store is not worker.store
                or worker.store.path is None or worker.store.run_id != identity.run_id
                or assembler.organizations.run_id != identity.run_id or own.run_id != identity.run_id
                or recipient.run_id != identity.run_id or identity.role != 'Contractor'
                or identity.action_id != 'CONTRACTOR-A02' or identity.purpose != 'action'
                or own.contract_ref.id != 'CONTRACTOR-A02' or recipient.contract_ref.id != 'OWN-A09'
                or own.execution_mode == 'offline_fixture' or recipient.execution_mode == 'offline_fixture'
                or own.scope != recipient.scope or own.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Formal bid reader changed original components, current authority or sharing selection')
        host._check()

    def _validate_saved(self, prepared):
        settings, worker = self.settings, self.worker
        with worker.store._lock:
            record, task, snapshot = worker.get_record(settings.identity), worker.store.get(settings.identity), worker.snapshots.get(settings.identity)
        context = settings.contractor_request.context
        if record is None:
            raise TaskConflict('Formal bid reader requires its original existing saved result')
        original = ActionContext.model_validate(snapshot['context'])
        if (record['result']['kind'] != 'completed' or record['result']['payload']['choice'] != 'submit_bid'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                or task['revision'] < record['attempt_revision']
                or record['record_sha256'] != settings.source_record_sha256
                or record['result_sha256'] != settings.source_result_sha256
                or task_digest(snapshot) != settings.source_snapshot_sha256
                or task_digest(record['audit']['reading']) != settings.source_audit_reading_sha256
                or record['audit']['reading'].get('source_mode') != 'formal'
                or snapshot['action_input'] != settings.contractor_request.action_input
                or prepared.action_input.model_dump(mode='json') != snapshot['action_input']
                or prepared.reading.organization_id != settings.identity.organization_id
                or prepared_action_execution_versions(prepared, client_version=worker.client_version,
                    model_version=worker.model_version) != settings.identity.versions
                or any(getattr(original, key) != getattr(context, key)
                    for key in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                or original.business_time.clock_ref != context.business_time.clock_ref
                or original.business_time.offset > context.business_time.offset):
            raise TaskConflict('Formal bid reader changes finalized original bid, source history or execution versions')
        witness = [row.model_dump(mode='json') for row in settings.original_source_reading]
        refs = {row.ref.key() for row in settings.original_source_reading}
        if (len(refs) != len(witness) or task_digest(witness) != record['audit']['reading'].get('sha256')
                or not {ref.key() for ref in settings.shared_source_refs} <= refs):
            raise TaskConflict('Formal bid witness or sharing scope differs from original execution source digest')
        for row in settings.original_source_reading:
            if prepared.reading.resolve(row.ref).model_dump(mode='json') != row.projection:
                raise TaskConflict('Original bid witness differs from current authorized Contractor sources')
        if prepared.reading.evidence() != witness:
            raise TaskConflict('Formal bid witness omits or reorders original source reads')
        prepared.reading.recheck()
        if self.validate_sharing(identity=settings.identity.as_dict(), record=deepcopy(record),
                snapshot=deepcopy(snapshot), context=settings.recipient_context.model_copy(deep=True),
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not confirm actual current Contractor bid sharing permission')
        return record

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Formal bid reader requires its exact current Owner recipient and original task')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            supplied = settings.contractor_request.action_input
            prepared = self.assembler.build(settings.contractor_request.context, **{key: deepcopy(supplied[key])
                for key in ('pricing_profile_ref', 'capacity_ref', 'cost_refs', 'allowed_method_refs')})
            try:
                record = self._validate_saved(prepared)
            finally:
                prepared.reading.recheck()
                self._check()
        publication = self.submission_host.read_receipt(settings.identity)
        receipt = publication.get('receipt', {})
        if (publication.get('schema_version') != 'contractor-bid-saved-receipt.v1'
                or publication.get('identity') != settings.identity.as_dict()
                or publication.get('record_sha256') != record['record_sha256']
                or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                or any(receipt.get(key) != value for key, value in {
                    'run_id': settings.identity.run_id, 'organization_id': settings.identity.organization_id,
                    'request_id': settings.identity.request_id, 'task_sha256': task_digest(settings.identity.as_dict()),
                    'output_sha256': settings.source_result_sha256}.items())):
            raise TaskConflict('Formal bid reader lacks its original confirmed accepted publication receipt')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            self._validate_saved(prepared)
            return ContractorBidJournalSource(worker=self.worker, identity=TaskIdentity(**settings.identity.as_dict()),
                submission_host=self.submission_host)
