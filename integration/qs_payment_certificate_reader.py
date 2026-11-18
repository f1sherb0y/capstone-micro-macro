"""Read original QS certification decisions for independent Owner reception.

The QS A08 wait/recovery reader remains in qs_payment_reader. This module
borrows completed decisions only; it neither issues a certificate nor creates
an Owner obligation or a financial effect.
"""
from copy import deepcopy
from dataclasses import replace

from integration.module_host import module_factory_descriptor
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.qs_payment_results import QSPaymentResultWorker, SavedQSPayment
from integration.qs_research_reader import QSResearchReader, QSResearchReaderSettings
from src.actions.contracts.common import ActionContext
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest


class QSPaymentCertificateReaderSettings(QSResearchReaderSettings):
    """Original QS read invocation, hashes and current Owner recipient/sharing."""


class QSPaymentCertificateReader(QSResearchReader):
    """Reuse original journal, seven-version and current source/permission checks.

    validate_sharing must authorize disclosure of the entire returned saved
    decision to this exact current Owner, including its original source
    evidence; shared_source_refs explicitly include the contract/application.
    Native issuance, correction history, registration and complete financial
    mapping still require independent receiver validation through the handoff.
    Application resources remain owned by their original source factory.
    """
    SETTINGS_TYPE = QSPaymentCertificateReaderSettings
    WORKER_TYPE = QSPaymentResultWorker
    ASSEMBLER_TYPE = QSPaymentActionAssembler
    SAVED_TYPE = SavedQSPayment
    SOURCE_ACTION_ID = 'QS-A08'
    RECIPIENT_ACTION_ID = 'OWN-A06'
    EXPECTED_CHOICES = frozenset({'certify', 'correct_certificate'})

    def required_shared_refs(self, saved):
        return {saved.action_input.contract_ref.key(), saved.action_input.application_ref.key()}

    def configuration_evidence(self):
        """Describe actual original dependencies without reading a result."""
        self._check()
        callbacks = {'read': self.read, 'saved_validation': self._validate_saved,
            'required_shared_refs': self.required_shared_refs, 'read_guard': self.read_guard,
            'sharing': self.validate_sharing, 'assembly': self.assembler.build,
            'completed_result': self.worker.read_completed}
        return {'schema_version': 'qs-payment-certificate-reader-config.v1',
            'reader_settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'source_action_id': self.SOURCE_ACTION_ID, 'recipient_action_id': self.RECIPIENT_ACTION_ID,
            'implementations': {name: callable_implementation(callback) for name, callback in callbacks.items()}}


def bind_payment_certificate_sources(*, sources, readers, validate_reception, validate_mapping, version):
    """Select one or more original QS tasks without replacing receiver callbacks."""
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(readers, (list, tuple)) or not readers
            or any(not isinstance(reader, QSPaymentCertificateReader) for reader in readers)
            or any(callback is not None and not callable(callback)
                for callback in (validate_reception, validate_mapping))
            or validate_reception is None and validate_mapping is None
            or not isinstance(version, str) or not version.strip()):
        raise ValueError('Certificate binding requires original QS readers, Owner sources and independent validators')
    if any(callback is not None for callback in (sources.read_qs_payment,
            sources.validate_payment_certificate_reception, sources.validate_payment_certificate_mapping)):
        raise TaskConflict('Certificate binding cannot replace existing application callbacks')
    selected = tuple(readers)
    tasks = {reader.settings.identity.key: reader for reader in selected}
    if len(tasks) != len(selected):
        raise TaskConflict('Certificate binding repeats an original QS task')
    recipient = selected[0].settings.recipient_context.model_copy(deep=True)

    def components():
        return (sources.store, sources.registry, sources.organizations, sources.provider,
            sources.read_guard, sources.validators, sources.evidence, sources.model_host,
            validate_reception, validate_mapping, *selected)

    original_components = components()

    def declaration():
        callbacks = {'reception': validate_reception, 'mapping': validate_mapping}
        return {'schema_version': 'v5-payment-certificate-source-binding.v2',
            'run_id': recipient.run_id,
            'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
            'readers': [{'source_task_sha256': reader.settings.identity.key,
                'original_reader_configuration': reader.configuration_evidence()} for reader in selected],
            'validators': {name: module_factory_descriptor(callback, 'validate_payment_certificate_' + name)
                for name, callback in callbacks.items() if callback is not None},
            'validator_implementations': {name: callable_implementation(callback)
                for name, callback in callbacks.items() if callback is not None},
            'bound_source_version': version}

    declared = declaration()

    def check_binding():
        if (any(current is not original for current, original in zip(components(), original_components))
                or declaration() != declared):
            raise TaskConflict('Certificate binding changed original resources or actual dependency declarations')
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Certificate binding changes original recipient run')
        registration = sources.registry.get('OWN-A06')
        grants = sources.organizations.grants(recipient, 'OWN-A06', 'Owner')
        if registration.role != 'Owner' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Certificate binding requires current Owner payment authority and original Skill')
        for reader in selected:
            reader._check()
            if reader.settings.recipient_context != recipient:
                raise TaskConflict('Certificate binding mixes current Owner recipients')
        return grants[0].organization_id

    recipient_org = check_binding()

    def check_context(context):
        if check_binding() != recipient_org or ActionContext.model_validate(context) != recipient:
            raise TaskConflict('Certificate selection changes original current Owner authority')

    def read(*, context, source_task_sha256):
        check_context(context)
        reader = tasks.get(source_task_sha256)
        if reader is None:
            raise TaskConflict('Certificate selection names an undeclared original QS task')
        try:
            return reader.read(context=context, source_task_sha256=source_task_sha256)
        finally:
            check_context(context)

    def check_decisions(saved_decisions, context):
        if (not saved_decisions or any(not isinstance(saved, SavedQSPayment) for saved in saved_decisions)
                or len({saved.identity.key for saved in saved_decisions}) != len(saved_decisions)):
            raise TaskConflict('Certificate reception requires distinct original QS decisions')
        for saved in saved_decisions:
            if saved != read(context=context, source_task_sha256=saved.identity.key):
                raise TaskConflict('Certificate reception substitutes an original authorized QS decision')

    # The Owner host already holds sources.read_guard while invoking these
    # callbacks. Borrow that boundary; an actual source guard need not reenter.
    def reception(*, saved, receipt, certificate, obligation, context):
        check_context(context)
        check_decisions([saved], context)
        try:
            return validate_reception(saved=deepcopy(saved), receipt=deepcopy(receipt),
                certificate=deepcopy(certificate), obligation=deepcopy(obligation),
                context=recipient.model_copy(deep=True)) is True
        finally:
            check_decisions([saved], context)
            check_context(context)

    def mapping(*, saved_decisions, receipts, obligations, components, context):
        check_context(context)
        check_decisions(saved_decisions, context)
        try:
            return validate_mapping(saved_decisions=deepcopy(saved_decisions), receipts=deepcopy(receipts),
                obligations=deepcopy(obligations), components=deepcopy(components),
                context=recipient.model_copy(deep=True)) is True
        finally:
            check_decisions(saved_decisions, context)
            check_context(context)

    def evidence():
        check_context(recipient)
        original = sources.evidence()
        if not isinstance(original, dict) or 'v5_payment_certificate_binding' in original:
            raise TaskConflict('Certificate binding requires original source evidence without collision')
        check_context(recipient)
        return {**deepcopy(original), 'v5_payment_certificate_binding': {
            **deepcopy(declared), 'recipient_organization_id': recipient_org}}

    return replace(sources, version=version, evidence=evidence, read_qs_payment=read,
        validate_payment_certificate_reception=reception if validate_reception is not None else None,
        validate_payment_certificate_mapping=mapping if validate_mapping is not None else None)
