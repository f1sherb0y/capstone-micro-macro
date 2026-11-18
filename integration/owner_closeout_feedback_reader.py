"""Read original own-Owner closeout feedback through a separate authorized A12 view."""
from copy import deepcopy
from dataclasses import replace

from pydantic import field_validator

from integration.module_host import module_factory_descriptor
from integration.owner_closeout_actions import OwnerCloseoutActionAssembler
from integration.owner_closeout_continuation_handoff import bind_owner_closeout_continuation_sources
from integration.owner_closeout_feedback import OwnerCloseoutSubmissionFeedback
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerCloseoutFeedbackReaderSettings(StrictRecord):
    owner_request: RoleContractInvocation
    recipient_context: ActionContext
    identity: TaskIdentity
    feedback_record_sha256: Digest
    current_guard_covers_history: bool = False

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerCloseoutFeedbackReader:
    """Borrow the original feedback protocol without retyping history as A13 sources.

    Current A12 reading retains the feedback protocol's own authorization,
    inbox event/digest checks and validate_read gate. validate_history separately
    authorizes the selected original record for the exact current A13 context,
    including any case/project relation. The existing continuation handoff still
    authenticates the independent current native mapping and every disposition.
    Reading creates no task, feedback event, source fact or business transition.
    The supplied A12 read_guard also protects original receipt-read authority;
    receipt reads borrow that boundary rather than acquiring it again. With
    current_guard_covers_history explicitly enabled, the source binder uses
    the caller-held A13 boundary instead; it must protect both A12 history and
    original receipt access. A12/A13 grants and history validators still run.
    """
    def __init__(self, *, settings, feedback, assembler, read_guard, validate_history):
        self.settings = OwnerCloseoutFeedbackReaderSettings.model_validate(settings).model_copy(deep=True)
        if (not isinstance(feedback, OwnerCloseoutSubmissionFeedback)
                or not isinstance(assembler, OwnerCloseoutActionAssembler)
                or not callable(read_guard) or not callable(validate_history)):
            raise ValueError('Closeout history requires original feedback, formal A12 assembler and independent history gate')
        self.feedback, self.assembler = feedback, assembler
        self.read_guard, self.validate_history = read_guard, validate_history
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._original_components = self._components()
        self._callbacks = self._descriptors()
        self._check()

    def _components(self):
        return (self.feedback, self.feedback.host, self.feedback.host.store, self.feedback.host.registry,
            self.feedback.inbox, self.assembler, self.assembler.registry, self.assembler.organizations,
            self.assembler.provider, self.read_guard, self.validate_history)

    def _descriptors(self):
        return {name: module_factory_descriptor(callback, name) for name, callback in (
            ('read_guard', self.read_guard), ('validate_history', self.validate_history),
            ('feedback_read', self.feedback.read), ('assemble_history', self.assembler.build))}

    def configuration_evidence(self):
        """Retain original history declaration without reading a feedback event."""
        self._check()
        return {'settings_sha256': self._settings_sha256,
            'feedback_configuration_sha256': task_digest(self.feedback._declared),
            'submission_host_configuration_sha256': task_digest(self.feedback.host._declared),
            'callbacks': deepcopy(self._callbacks)}

    def _check(self):
        settings, host, assembler = self.settings, self.feedback.host, self.assembler
        identity, own, recipient = settings.identity, settings.owner_request.context, settings.recipient_context
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or task_digest(settings.model_dump(mode='json')) != self._settings_sha256
                or self._descriptors() != self._callbacks
                or assembler.ACTION_ID != 'OWN-A12' or assembler.source_mode != 'formal'
                or assembler.registry is not host.registry or assembler._views.provider is not assembler.provider
                or assembler.organizations.run_id != host.store.run_id
                or identity.action_id != 'OWN-A12' or identity.role != 'Owner' or identity.purpose != 'action'
                or identity.run_id != host.store.run_id or own.run_id != identity.run_id or recipient.run_id != identity.run_id
                or own.contract_ref.id != 'OWN-A12' or recipient.contract_ref.id != 'OWN-A13'
                or own.execution_mode != 'llm' or recipient.execution_mode != 'llm'
                or settings.owner_request.execution_path == 'deterministic'
                or own.business_time != recipient.business_time or own.operation_id == recipient.operation_id
                or own.read_token == recipient.read_token or own.task_ref == recipient.task_ref):
            raise TaskConflict('Closeout history changes original feedback/components or distinct current formal A12/A13 declarations')
        self.feedback._check()
        for context, action_id in ((own, 'OWN-A12'), (recipient, 'OWN-A13')):
            grants = assembler.organizations.grants(context, action_id, 'Owner')
            if grants[0].organization_id != identity.organization_id:
                raise TaskConflict('Closeout history changes original own-Owner history or current recipient authority')

    def read(self, *, context, feedback_record_sha256):
        """Standalone reading owns the configured A12 source boundary."""
        self._check()
        if (ActionContext.model_validate(context) != self.settings.recipient_context
                or feedback_record_sha256 != self.settings.feedback_record_sha256):
            raise TaskConflict('Closeout history requires the exact selected original feedback and current Owner recipient')
        with self.read_guard(self.settings.owner_request.context.model_copy(deep=True)):
            return self._read_guarded(context=context, feedback_record_sha256=feedback_record_sha256)

    def read_with_current_guard(self, *, context, feedback_record_sha256):
        """Caller holds a boundary covering current A13 and original A12 access."""
        self._check()
        if self.settings.current_guard_covers_history is not True:
            raise TaskConflict('Borrowing current closeout history guard requires an explicit coverage declaration')
        return self._read_guarded(context=context, feedback_record_sha256=feedback_record_sha256)

    def _read_guarded(self, *, context, feedback_record_sha256):
        self._check()
        settings = self.settings
        if (ActionContext.model_validate(context) != settings.recipient_context
                or feedback_record_sha256 != settings.feedback_record_sha256):
            raise TaskConflict('Closeout history requires the exact selected original feedback and current Owner recipient')
        prepared = self.assembler.build(settings.owner_request.context, **deepcopy(settings.owner_request.action_input))
        try:
            records = self.feedback.read(context=prepared.context, reading=prepared.reading)
            matches = [record for record in records if record['record_sha256'] == feedback_record_sha256]
            if len(matches) != 1:
                raise TaskConflict('Selected original closeout feedback is missing or duplicated in the authorized own inbox')
            record = matches[0]
            receipt = self.feedback.host._read_receipt_guarded(settings.identity)
            recorded = ActionContext.model_validate(record['context'])
            if (record['identity'] != settings.identity.as_dict() or record['receipt'] != receipt
                    or record['observation']['target_action_id'] != 'OWN-A12'
                    or receipt['receipt']['disposition'] != 'accepted'
                    or recorded.business_time.clock_ref != settings.recipient_context.business_time.clock_ref
                    or recorded.business_time.offset > settings.recipient_context.business_time.offset
                    or self.validate_history(record=deepcopy(record),
                        history_context=prepared.context.model_copy(deep=True),
                        context=settings.recipient_context.model_copy(deep=True)) is not True):
                raise TaskConflict('Closeout history lacks its original durable receipt or independent current history permission')
            if self.feedback.host._read_receipt_guarded(settings.identity) != receipt:
                raise TaskConflict('Original closeout receipt changed during historical reading')
            return deepcopy(record)
        finally:
            prepared.reading.recheck()
            self._check()
            if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                raise TaskConflict('Closeout historical reading changed its original authorized source snapshot')


def bind_closeout_feedback_reader_sources(*, sources, reader, validate_relation, version):
    """Attach selected original own history and independent actual A13 mapping."""
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(reader, OwnerCloseoutFeedbackReader)
            or not callable(validate_relation) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Closeout history binding requires original Owner sources, reader, actual mapping validator and version')

    def check_binding():
        reader._check()
        if (reader.feedback.host.store is not sources.store or reader.feedback.host.registry is not sources.registry
                or reader.assembler.organizations is not sources.organizations):
            raise TaskConflict('Closeout history binding changes original same-Owner journal, registry or authority')

    check_binding()
    callback = reader.read_with_current_guard if reader.settings.current_guard_covers_history else reader.read
    bound = bind_owner_closeout_continuation_sources(sources,
        read_closeout_feedback=callback, validate_relation=validate_relation)
    declaration = {'schema_version': 'owner-closeout-feedback-reader-binding.v1',
        'settings_sha256': reader._settings_sha256, 'source_identity': reader.settings.identity.as_dict(),
        'feedback_record_sha256': reader.settings.feedback_record_sha256,
        'reader_callbacks': deepcopy(reader._callbacks), 'bound_source_version': version,
        'current_guard_covers_history': reader.settings.current_guard_covers_history}

    def evidence():
        check_binding()
        original = bound.evidence()
        if not isinstance(original, dict) or 'closeout_history_reader' in original:
            raise TaskConflict('Closeout history binding requires original provenance without collision')
        check_binding()
        return {**deepcopy(original), 'closeout_history_reader': deepcopy(declaration)}

    return replace(bound, version=version, evidence=evidence)
