"""Read original formal Owner financing applications for independent Bank intake."""
from copy import deepcopy
from dataclasses import replace

from integration.bank_role_contract_host import BankRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.owner_draw_request_reader import OwnerDrawRequestReader, OwnerDrawRequestReaderSettings
from integration.owner_financing_actions import OwnerFinancingActionAssembler
from integration.owner_financing_results import OwnerFinancingResultWorker
from src.actions.contracts.common import ActionContext, walk_references
from src.coordination.tasks import TaskConflict, task_digest


class OwnerFinancingApplicationReaderSettings(OwnerDrawRequestReaderSettings):
    """Original Owner A05 history and exact current Bank A02 recipient context."""


class OwnerFinancingApplicationReader(OwnerDrawRequestReader):
    """Borrow original worker/snapshot/guard; actual registration stays independent.

    Reading accepts only apply, preserves its complete original draft and uses
    the existing independent sharing validator. No receipt query, registration,
    credit approval, action execution or model invocation occurs here.
    """
    SETTINGS_TYPE = OwnerFinancingApplicationReaderSettings
    WORKER_TYPE = OwnerFinancingResultWorker
    ASSEMBLER_TYPE = OwnerFinancingActionAssembler
    ACTION_ID = 'OWN-A05'
    RECIPIENT_ACTION_ID = 'BANK-A02'
    EXPECTED_CHOICES = frozenset({'apply'})

    def required_shared_refs(self, saved):
        draft = saved.result.payload.application
        if draft is None:
            raise TaskConflict('Original apply decision lacks its complete financing application draft')
        return {saved.action_input.scope_ref.ref.key(), saved.action_input.funding_profile_ref.key(),
            *(ref.key() for ref in walk_references(draft))}


def bind_owner_financing_application_sources(*, sources, reader, validate_reception, version):
    return _bind_owner_financing_bank_sources(sources=sources, reader=reader,
        validate_reception=validate_reception, version=version, recipient_action='BANK-A02',
        validator_field='validate_owner_application_reception', evidence_field='v5_owner_application_binding')


def _bind_owner_financing_bank_sources(*, sources, reader, validate_reception, version,
        recipient_action, validator_field, evidence_field):
    if (not isinstance(sources, BankRoleContractSources) or not isinstance(reader, OwnerFinancingApplicationReader)
            or reader.ACTION_ID != 'OWN-A05' or reader.RECIPIENT_ACTION_ID != recipient_action
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Owner financing binding requires matching original reader, actual Bank sources and receiver validator')
    if sources.read_owner_financing is not None or getattr(sources, validator_field) is not None:
        raise TaskConflict('Owner financing binding cannot replace existing application callbacks')
    recipient = reader.settings.recipient_context.model_copy(deep=True)

    def check_binding():
        reader._check()
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Owner financing binding changes original recipient run')
        registration = sources.registry.get(recipient_action)
        grants = sources.organizations.grants(recipient, recipient_action, 'Bank')
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Owner financing binding requires current Bank authority and original Skill')
        return grants[0].organization_id

    organization = check_binding()
    declaration = {'schema_version': evidence_field + '.v1', 'run_id': recipient.run_id,
        'recipient_organization_id': organization, 'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
        'reader_settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, 'read_owner_financing'),
        'validator': module_factory_descriptor(validate_reception, validator_field), 'bound_source_version': version}

    def read(*, context, source_task_sha256):
        if check_binding() != organization or ActionContext.model_validate(context) != recipient:
            raise TaskConflict('Owner financing selection changes original current Bank authority')
        try:
            return reader.read(context=context, source_task_sha256=source_task_sha256)
        finally:
            if check_binding() != organization:
                raise TaskConflict('Owner financing reading changed original current Bank authority')

    def evidence():
        if check_binding() != organization:
            raise TaskConflict('Owner financing source binding changes original Bank party')
        original = sources.evidence()
        if not isinstance(original, dict) or evidence_field in original:
            raise TaskConflict('Owner financing binding requires original provenance without collision')
        if check_binding() != organization:
            raise TaskConflict('Owner financing source evidence changed current Bank authority')
        return {**deepcopy(original), evidence_field: deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        read_owner_financing=read, **{validator_field: validate_reception})
