"""Select complete original pay/repay command groups for Owner reconciliation."""
from copy import deepcopy
from dataclasses import replace

from integration.module_host import module_factory_descriptor
from integration.owner_payment_execution_reader import OwnerPaymentExecutionReader, OwnerPaymentExecutionReaderSettings
from integration.owner_role_contract_host import OwnerRoleContractSources
from src.actions.contracts.common import ActionContext
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest


class OwnerPaymentReconciliationReaderSettings(OwnerPaymentExecutionReaderSettings):
    """Both history and recipient contexts belong to the same original Owner journal."""


class OwnerPaymentReconciliationReader(OwnerPaymentExecutionReader):
    """Reuse verified issuance/settlement queries, preserving unknown and pending.

    Current own disclosure and receiver validators authenticate complete native
    groups and their current private financial-source mapping. Neither reading
    a terminal command nor observing a payer debit applies financial effects.
    """
    SETTINGS_TYPE = OwnerPaymentReconciliationReaderSettings
    RECIPIENT_ACTION_ID = 'OWN-A06'
    EXPECTED_CHOICES = frozenset({'pay', 'repay'})

    def check_execution_selection(self, observation):
        if {ref.key() for ref in self.settings.execution_refs} != {line.execution.ref.key() for line in observation.lines}:
            raise TaskConflict('Own payment reconciliation must retain every original issued command')


def bind_own_payment_reconciliation_sources(*, sources, readers, validate_reception, version):
    """Bind distinct original groups from the same Owner journal to current input."""
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(readers, (list, tuple)) or not readers
            or any(not isinstance(reader, OwnerPaymentReconciliationReader) for reader in readers)
            or not callable(validate_reception) or not isinstance(version, str) or not version.strip()):
        raise ValueError('Own reconciliation binding requires original Owner readers, sources, validator and version')
    if sources.read_owner_payment_execution is not None or sources.validate_owner_payment_execution_reception is not None:
        raise TaskConflict('Own payment binding cannot replace existing application callbacks')
    selected = tuple(readers)
    tasks = {reader.settings.identity.key: reader for reader in selected}
    refs = [ref.key() for reader in selected for ref in reader.settings.execution_refs]
    if len(tasks) != len(selected) or len(set(refs)) != len(refs):
        raise TaskConflict('Own reconciliation binding repeats an original task or issued command')
    recipient = selected[0].settings.recipient_context.model_copy(deep=True)

    def components():
        return (sources, sources.store, sources.registry, sources.organizations,
            sources.provider, sources.read_guard, sources.validators, sources.evidence,
            sources.model_host, validate_reception, *selected)

    original_components = components()

    def declaration():
        return {'schema_version': 'v5-own-payment-reconciliation-binding.v2', 'run_id': recipient.run_id,
            'recipient_organization_id': selected[0].settings.identity.organization_id,
            'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
            'readers': [{'source_task_sha256': reader.settings.identity.key,
                'original_reader_configuration': reader.configuration_evidence()} for reader in selected],
            'receiver_validator': module_factory_descriptor(validate_reception, 'validate_owner_payment_execution_reception'),
            'receiver_validator_implementation': callable_implementation(validate_reception),
            'bound_source_version': version}

    declared = declaration()

    def check_binding():
        if (any(current is not original for current, original in zip(components(), original_components))
                or declaration() != declared):
            raise TaskConflict('Own payment binding changed original sources, readers or actual dependency declarations')
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Own payment binding changes original recipient run')
        registration = sources.registry.get('OWN-A06')
        grants = sources.organizations.grants(recipient, 'OWN-A06', 'Owner')
        organization = grants[0].organization_id
        if registration.role != 'Owner' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Own payment binding requires current Owner payment authority and original Skill')
        for reader in selected:
            reader._check()
            if (reader.settings.recipient_context != recipient or reader.settings.identity.organization_id != organization
                    or reader.worker.store is not sources.store or reader.worker.registry is not sources.registry):
                raise TaskConflict('Own payment reader changes original Owner party, journal, registry or current context')
        return organization

    recipient_org = check_binding()

    def read(*, context, source_task_sha256):
        if check_binding() != recipient_org or ActionContext.model_validate(context) != recipient:
            raise TaskConflict('Own payment selection changes original current Owner authority')
        reader = tasks.get(source_task_sha256)
        if reader is None:
            raise TaskConflict('Own payment selection names an undeclared original task')
        try:
            return reader.read(context=context, source_task_sha256=source_task_sha256)
        finally:
            if check_binding() != recipient_org:
                raise TaskConflict('Own payment reading changed original recipient authority')

    def reception(**payment):
        if check_binding() != recipient_org or payment['context'] != recipient:
            raise TaskConflict('Own payment reception changes original current Owner authority')
        selected_tasks = [item.saved.identity.key for item in payment['receptions']]
        if len(set(selected_tasks)) != len(selected_tasks) or not set(selected_tasks) <= tasks.keys():
            raise TaskConflict('Own payment reception repeats or substitutes an original declared group')
        expected_refs = {ref.key() for key in selected_tasks for ref in tasks[key].settings.execution_refs}
        if {execution.ref.key() for execution in payment['executions']} != expected_refs:
            raise TaskConflict('Own payment reception omits or substitutes an original complete command group')
        try:
            return validate_reception(**payment) is True
        finally:
            if check_binding() != recipient_org:
                raise TaskConflict('Own payment reception changed original recipient authority')

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Own payment binding changes original recipient organization')
        original = sources.evidence()
        if not isinstance(original, dict) or 'v5_own_payment_reconciliation_binding' in original:
            raise TaskConflict('Own payment binding requires original source evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Own payment source evidence changed current recipient authority')
        return {**deepcopy(original), 'v5_own_payment_reconciliation_binding': deepcopy(declared)}

    return replace(sources, version=version, evidence=evidence, read_owner_payment_execution=read,
        validate_owner_payment_execution_reception=reception)
