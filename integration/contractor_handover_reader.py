"""Read original formal Contractor handover decisions for independent Owner reception."""
from copy import deepcopy
from dataclasses import replace
from typing import Annotated

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_closeout_actions import ContractorCloseoutActionAssembler
from integration.contractor_closeout_results import ContractorCloseoutResultWorker, SavedContractorCloseout
from integration.contractor_owner_handover import bind_owner_handover_sources
from integration.module_host import module_factory_descriptor
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ContractorHandoverReaderSettings(StrictRecord):
    contractor_request: RoleContractInvocation
    recipient_context: ActionContext
    identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    sharing_authorized: bool
    current_guard_covers_history: bool = False

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ContractorHandoverReader:
    """Borrow the original worker, snapshots and currently authorized Contractor view.

    The sharing validator authorizes the complete returned original record and
    selected configuration/evidence for the exact current Owner recipient. Owner
    reception, configuration mapping, acceptance and continuing duties stay in
    the existing handoff and its independent actual receiver validator. Reading
    creates no handover registration, use permission, acceptance or debt release.
    Standalone reads acquire the original Contractor source guard. An explicit
    current_guard_covers_history declaration lets the Owner source binding borrow
    its caller-held boundary, which must also cover Contractor sources, journal
    reads and disclosure authority. Both paths retain all history checks.
    """
    def __init__(self, *, settings, worker, assembler, read_guard, validate_sharing):
        self.settings = ContractorHandoverReaderSettings.model_validate(settings).model_copy(deep=True)
        if (not isinstance(worker, ContractorCloseoutResultWorker)
                or not isinstance(assembler, ContractorCloseoutActionAssembler)
                or not callable(read_guard) or not callable(validate_sharing)):
            raise ValueError('Handover reader requires original Contractor worker/assembler, source guard and sharing validator')
        self.worker, self.assembler = worker, assembler
        self.read_guard, self.validate_sharing = read_guard, validate_sharing
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._original_components = self._components()
        self._callbacks = self._descriptors()
        self._check()

    def _components(self):
        return (self.worker, self.assembler, self.worker.store, self.worker.snapshots, self.worker.registry,
            self.assembler.registry, self.assembler.organizations, self.assembler.provider,
            self.read_guard, self.validate_sharing)

    def _descriptors(self):
        return {name: module_factory_descriptor(callback, name) for name, callback in (
            ('read_guard', self.read_guard), ('validate_sharing', self.validate_sharing),
            ('read_original', self.worker.read_completed), ('assemble_history', self.assembler.build),
            ('read_current_guard', self.read_with_current_guard))}

    def configuration_evidence(self):
        """Declare original history dependencies without reading a business record."""
        self._check()
        return {'settings_sha256': self._settings_sha256, 'callbacks': deepcopy(self._callbacks),
            'worker_client_version': self.worker.client_version, 'worker_model_version': self.worker.model_version,
            'assembler_macro_version': self.assembler.macro_version, 'assembler_model_version': self.assembler.model_version,
            'worker_validators': {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in (('invocation', self.worker.validate_invocation),
                    ('wait', self.worker.validate_wait), ('recovery', self.worker.validate_recovery))}}

    def _check(self):
        settings, worker, assembler = self.settings, self.worker, self.assembler
        own, recipient, identity = settings.contractor_request.context, settings.recipient_context, settings.identity
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256 or self._descriptors() != self._callbacks
                or worker.ACTION_ID != 'CONTRACTOR-A11' or assembler.ACTION_ID != 'CONTRACTOR-A11'
                or assembler.source_mode != 'formal' or assembler.registry is not worker.registry
                or assembler._views.provider is not assembler.provider or worker.snapshots.store is not worker.store
                or worker.store.path is None or worker.store.run_id != identity.run_id
                or assembler.organizations.run_id != identity.run_id or own.run_id != identity.run_id
                or recipient.run_id != identity.run_id or identity.action_id != 'CONTRACTOR-A11'
                or identity.role != 'Contractor' or identity.purpose != 'action'
                or own.contract_ref.id != 'CONTRACTOR-A11' or recipient.contract_ref.id != 'OWN-A12'
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or settings.contractor_request.execution_path == 'deterministic'
                or own.business_time != recipient.business_time
                or settings.sharing_authorized is not True
                or len({ref.key() for ref in settings.shared_source_refs}) != len(settings.shared_source_refs)):
            raise TaskConflict('Handover reader changes original Contractor components, authority or explicit sharing declaration')
        grants = assembler.organizations.grants(own, 'CONTRACTOR-A11', 'Contractor')
        if grants[0].organization_id != identity.organization_id:
            raise TaskConflict('Handover reader substitutes the original authorized Contractor organization')

    def _validate_saved(self, saved, reading):
        settings = self.settings
        disclosed = {ref.key() for ref in settings.shared_source_refs}
        originals = {Reference.model_validate(row['ref']).key() for row in saved.source_reading}
        if (not isinstance(saved, SavedContractorCloseout) or saved.identity.as_dict() != settings.identity.as_dict()
                or saved.current_context != settings.contractor_request.context
                or saved.action_input.model_dump(mode='json') != settings.contractor_request.action_input
                or saved.record_sha256 != settings.source_record_sha256
                or task_digest(saved.result.model_dump(mode='json')) != settings.source_result_sha256
                or saved.source_reading_sha256 != settings.source_reading_sha256
                or saved.audit.get('reading', {}).get('source_mode') != 'formal'
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'submit_handover'
                # The returned saved record contains every original source.
                or len(originals) != len(saved.source_reading) or disclosed != originals):
            raise TaskConflict('Handover reader substitutes original completed submit decision, lineage or disclosed source versions')
        required = {saved.action_input.contract_ref.key(), saved.action_input.handover_profile_ref.key(),
            *(ref.key() for ref in saved.action_input.as_built_refs), *(ref.key() for ref in saved.result.payload.evidence_refs)}
        if not required <= disclosed:
            raise TaskConflict('Handover disclosure omits original contract, profile, complete configuration or supporting evidence')
        for row in saved.source_reading:
            if reading.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                raise TaskConflict('Original Contractor handover source differs from current authorized original source version')
        reading.recheck()
        if self.validate_sharing(saved=deepcopy(saved), context=settings.recipient_context.model_copy(deep=True),
                shared_source_refs=deepcopy(settings.shared_source_refs)) is not True:
            raise TaskConflict('Application did not authorize original Contractor handover disclosure to the current Owner')
        self._check()
        return True

    def read(self, *, context, source_task_sha256):
        """Standalone reading owns the configured Contractor source boundary."""
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Handover reader requires exact current Owner recipient and original Contractor task')
        with self.read_guard(settings.contractor_request.context.model_copy(deep=True)):
            return self._read_guarded(context=context, source_task_sha256=source_task_sha256)

    def read_with_current_guard(self, *, context, source_task_sha256):
        """Caller holds an explicitly declared Owner/Contractor history boundary."""
        self._check()
        if self.settings.current_guard_covers_history is not True:
            raise TaskConflict('Borrowing current handover history guard requires an explicit coverage declaration')
        return self._read_guarded(context=context, source_task_sha256=source_task_sha256)

    def _read_guarded(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Handover reader requires exact current Owner recipient and original Contractor task')
        prepared = self.assembler.build(settings.contractor_request.context,
            **deepcopy(settings.contractor_request.action_input))
        try:
            return deepcopy(self.worker.read_completed(settings.identity, current_context=prepared.context,
                reading=prepared.reading, execution_versions=prepared_action_execution_versions(prepared,
                    client_version=self.worker.client_version, model_version=self.worker.model_version),
                validate_current=lambda saved: self._validate_saved(saved, prepared.reading)))
        finally:
            prepared.reading.recheck()
            self._check()
            if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                raise TaskConflict('Handover reader changed its original current Contractor source snapshot')


def bind_contractor_handover_reader_sources(*, sources, reader, validate_reception, version):
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(reader, ContractorHandoverReader)
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Handover binding requires actual Owner sources, original Contractor reader, native validator and version')
    recipient = reader.settings.recipient_context.model_copy(deep=True)
    original_reader_configuration = reader.configuration_evidence()

    def check_binding():
        reader._check()
        if reader.configuration_evidence() != original_reader_configuration:
            raise TaskConflict('Handover binding changes original history worker versions or validators')
        registration = sources.registry.get('OWN-A12')
        grants = sources.organizations.grants(recipient, 'OWN-A12', 'Owner')
        if (sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id
                or registration.role != 'Owner' or not registration.implemented or registration.skill is None
                or grants[0].organization_id == reader.settings.identity.organization_id):
            raise TaskConflict('Handover binding changes current Owner authority or original run/Contractor relation')
        return grants[0].organization_id

    recipient_organization = check_binding()
    callback = reader.read_with_current_guard if reader.settings.current_guard_covers_history else reader.read
    bound = bind_owner_handover_sources(sources, read_contractor_closeout=callback, validate_reception=validate_reception)
    declaration = {'schema_version': 'contractor-handover-reader-binding.v1',
        'settings_sha256': reader._settings_sha256, 'reader_callbacks': deepcopy(reader._callbacks),
        'original_reader_configuration': deepcopy(original_reader_configuration),
        'source_identity': reader.settings.identity.as_dict(), 'recipient_organization_id': recipient_organization,
        'bound_source_version': version,
        'current_guard_covers_history': reader.settings.current_guard_covers_history}

    def evidence():
        if check_binding() != recipient_organization:
            raise TaskConflict('Handover reader binding changed the original Owner recipient')
        original = bound.evidence()
        if not isinstance(original, dict) or 'contractor_handover_reader' in original:
            raise TaskConflict('Handover reader binding requires original provenance without collision')
        if check_binding() != recipient_organization:
            raise TaskConflict('Handover source evidence changed current Owner recipient authority')
        return {**deepcopy(original), 'contractor_handover_reader': deepcopy(declaration)}

    return replace(bound, version=version, evidence=evidence)
