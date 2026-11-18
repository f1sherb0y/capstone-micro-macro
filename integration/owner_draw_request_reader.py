"""Read an original Owner draw instruction for actual Bank draw-request intake."""
from copy import deepcopy
from dataclasses import replace

from integration.action_versions import prepared_action_execution_versions
from integration.bank_role_contract_host import BankRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.owner_payment_actions import OwnerPaymentActionAssembler
from integration.owner_payment_results import OwnerPaymentResultWorker
from integration.owner_publication_reader import OwnerPublicationReader, OwnerPublicationReaderSettings
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class OwnerDrawRequestReaderSettings(OwnerPublicationReaderSettings):
    """owner_request is current Owner A06 history; recipient is current Bank A06."""


class OwnerDrawRequestReader(OwnerPublicationReader):
    """Reuse original Owner snapshots, versions, current authority and sharing gate.

    Borrow the original worker, assembler and submission host's source guard,
    but read no publication receipt or transport. The existing Bank handoff
    independently requires actual DrawRequest reception, exact amount/party/
    destination mapping, original authorization, conditions and request history.
    Reading a draw instruction creates no request registration, approval or cash.
    """
    SETTINGS_TYPE = OwnerDrawRequestReaderSettings
    WORKER_TYPE = OwnerPaymentResultWorker
    ASSEMBLER_TYPE = OwnerPaymentActionAssembler
    ACTION_ID = 'OWN-A06'
    RECIPIENT_ACTION_ID = 'BANK-A06'
    EXPECTED_CHOICES = frozenset({'draw_request'})

    def required_shared_refs(self, saved):
        return {saved.action_input.scope_ref.ref.key(), saved.result.payload.arrangement_ref.key()}

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Draw reader requires exact current Bank recipient and original Owner task')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            prepared = self.assembler.build(settings.owner_request.context, **deepcopy(settings.owner_request.action_input))
            try:
                saved = self.worker.read_completed(settings.identity, current_context=settings.owner_request.context,
                    reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda value: self._validate_saved(value, prepared.reading))
                return deepcopy(saved)
            finally:
                prepared.reading.recheck()
                self._check()
                if task_digest(prepared.reading.evidence()) != prepared.reading_sha256:
                    raise TaskConflict('Draw reader changed original current Owner source snapshot')


def bind_owner_draw_request_sources(*, sources, reader, validate_reception, version):
    """Pair original Owner instruction reading and actual Bank request validation."""
    if (not isinstance(sources, BankRoleContractSources) or not isinstance(reader, OwnerDrawRequestReader)
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Draw binding requires actual Bank sources, original Owner reader, validator and version')
    if sources.read_owner_payment is not None or sources.validate_owner_draw_request_reception is not None:
        raise TaskConflict('Draw binding cannot replace existing application callbacks')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Draw binding changes original recipient run')
        registration = sources.registry.get('BANK-A06')
        grants = sources.organizations.grants(recipient, 'BANK-A06', 'Bank')
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Draw binding requires current Bank draw authority and original Skill')
        return grants[0].organization_id

    recipient_org = check_binding()
    declaration = {'schema_version': 'v5-owner-draw-source-binding.v1', 'run_id': recipient.run_id,
        'recipient_organization_id': recipient_org,
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, 'read_owner_payment'),
        'receiver_validator': module_factory_descriptor(validate_reception, 'validate_owner_draw_request_reception'),
        'bound_source_version': version}

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Draw binding changes original recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or 'v5_owner_draw_binding' in original:
            raise TaskConflict('Draw binding requires original application evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Draw source evidence changed current recipient authority')
        return {**deepcopy(original), 'v5_owner_draw_binding': deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        read_owner_payment=reader.read, validate_owner_draw_request_reception=validate_reception)
