"""Read original payment issuance and verified settlement for Contractor intake."""
from copy import deepcopy
from dataclasses import replace
from typing import Annotated

from pydantic import Field

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_role_contract_host import ContractorRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.owner_contractor_payment_handoff import bind_contractor_received_payment_sources
from integration.owner_draw_request_reader import OwnerDrawRequestReader, OwnerDrawRequestReaderSettings
from integration.owner_payment_execution_reception import (
    PAYMENT_SETTLEMENT_RECEPTION_VERSION, OwnerPaymentExecutionReception,
)
from integration.owner_payment_settlement import OwnerPaymentSettlementReconciler
from integration.owner_payment_submission import OwnerPaymentExecutionObservation, OwnerPaymentSubmission
from src.actions.contracts.common import ActionContext, ref_type
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class OwnerPaymentExecutionReaderSettings(OwnerDrawRequestReaderSettings):
    execution_refs: Annotated[list[ref_type('PaymentExecution')], Field(min_length=1)]
    current_owner_input: dict | None = None


class OwnerPaymentExecutionReader(OwnerDrawRequestReader):
    """Borrow original Owner journal, native observer and settlement reconciler.

    query_execution/query preserve complete original command groups and unknown
    states without submitting or applying effects. Independent disclosure must
    authorize the full returned evidence for the selected Contractor commands.
    Fully final groups are returned only with their independent settlement;
    use its embedded issued observation to keep one coherent native interval.
    The receiver still checks beneficiary credit separately from payer debit.
    Application resources and guards remain owned by the application.

    Set current_owner_input and supply validate_history(saved, reading, context,
    current_owner_input) together to read later authorized balances while
    retaining the original owner_request input and journal hashes. The callback
    must authenticate the full original-to-current relation and current own
    history access, including unavailable historical projections. It cannot
    establish payment effects; native settlement and recipient validation stay
    independent. Without this explicit mode, original projections must match.
    """
    SETTINGS_TYPE = OwnerPaymentExecutionReaderSettings
    RECIPIENT_ACTION_ID = 'CONTRACTOR-A10'
    EXPECTED_CHOICES = frozenset({'pay'})

    def __init__(self, *, submission, settlement_reconciler, validate_disclosure,
            validate_history=None, **original_reader):
        if (not isinstance(submission, OwnerPaymentSubmission)
                or not isinstance(settlement_reconciler, OwnerPaymentSettlementReconciler)
                or settlement_reconciler.submission is not submission or not callable(validate_disclosure)):
            raise ValueError('Payment reader requires original issuance/settlement components and disclosure validator')
        self.submission, self.settlement_reconciler = submission, settlement_reconciler
        self.validate_disclosure = validate_disclosure
        self.validate_history = validate_history
        self._payment_components = (submission, settlement_reconciler, validate_disclosure, validate_history)
        self._history_descriptor = (module_factory_descriptor(validate_history, 'validate_payment_current_history')
            if validate_history is not None else None)
        super().__init__(**original_reader)

    def _check(self):
        super()._check()
        current = (self.submission, self.settlement_reconciler, self.validate_disclosure, self.validate_history)
        if (any(now is not original for now, original in zip(current, self._payment_components))
                or self.submission.worker is not self.worker
                or self.settlement_reconciler.submission is not self.submission
                or len({ref.key() for ref in self.settings.execution_refs}) != len(self.settings.execution_refs)
                or self.settings.current_owner_input is not None and not callable(self.validate_history)
                or self.settings.current_owner_input is None and self.validate_history is not None
                or (module_factory_descriptor(self.validate_history, 'validate_payment_current_history')
                    if self.validate_history is not None else None) != self._history_descriptor):
            raise TaskConflict('Payment reader changes original issuance/settlement components or selected commands')
        self.submission._check_binding()
        self.settlement_reconciler._check()

    def _validate_current_sources(self, saved, reading):
        if self.settings.current_owner_input is None:
            return super()._validate_current_sources(saved, reading)
        # Immutable original identity/input/result/source hashes are checked by
        # _validate_saved. Current balances need independent history mapping,
        # not equality to the pre-payment account/obligation projections.
        reading.recheck()
        if self.validate_history(saved=deepcopy(saved), reading=reading,
                context=self.settings.owner_request.context.model_copy(deep=True),
                current_owner_input=deepcopy(self.settings.current_owner_input)) is not True:
            raise TaskConflict('Payment reader lacks current authority and authentic original-to-current source mapping')
        reading.recheck()
        self._check()

    def required_shared_refs(self, saved):
        return {saved.action_input.scope_ref.ref.key()}

    def configuration_evidence(self):
        """Describe checked original dependencies; no native query or decision."""
        self._check()
        implementations = {
            'read': self.read, 'execution_selection': self.check_execution_selection,
            'original_history': self._validate_saved, 'current_sources': self._validate_current_sources,
            'shared_sources': self.required_shared_refs,
            'native_execution': self.submission.read_native_execution,
            'query_transport': self.submission.callbacks.query,
            'query_authority': self.submission.callbacks.validate_query,
            'receipt_validator': self.submission.callbacks.validate_receipt,
            'native_settlement': self.settlement_reconciler.read_native_settlement,
            'settlement_validator': self.settlement_reconciler.validate_native_settlement,
            'sharing': self.validate_sharing, 'disclosure': self.validate_disclosure,
            'current_history': self.validate_history,
        }
        return {'schema_version': 'owner-payment-execution-reader-config.v2',
            'settlement_reception_version': PAYMENT_SETTLEMENT_RECEPTION_VERSION,
            'reader_settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'reader': module_factory_descriptor(self.read, 'read_owner_payment'),
            'execution_selection': module_factory_descriptor(self.check_execution_selection, 'check_execution_selection'),
            'implementations': {name: callable_implementation(callback)
                for name, callback in implementations.items() if callback is not None},
            'submission_configuration_sha256': task_digest(self.submission._declared),
            'submission_host_configuration_sha256': task_digest(self.submission_host._declared),
            'settlement_reader': module_factory_descriptor(self.settlement_reconciler.read_native_settlement,
                'read_native_settlement'),
            'settlement_validator': module_factory_descriptor(self.settlement_reconciler.validate_native_settlement,
                'validate_native_settlement'),
            'sharing_validator': module_factory_descriptor(self.validate_sharing, 'validate_sharing'),
            'disclosure_validator': module_factory_descriptor(self.validate_disclosure, 'validate_disclosure'),
            'current_history_validator': module_factory_descriptor(self.validate_history,
                'validate_payment_current_history') if self.validate_history is not None else None}

    def check_execution_selection(self, observation):
        if not {ref.key() for ref in self.settings.execution_refs} <= {line.execution.ref.key() for line in observation.lines}:
            raise TaskConflict('Payment reader selects a command outside the original complete issuance group')

    def read(self, *, context, source_task_sha256):
        self._check()
        settings = self.settings
        if ActionContext.model_validate(context) != settings.recipient_context or source_task_sha256 != settings.identity.key:
            raise TaskConflict('Payment reader requires exact Contractor context and original Owner payment task')
        with self.submission_host.read_guard(TaskIdentity(**settings.identity.as_dict())):
            self._check()
            current_input = (settings.owner_request.action_input if settings.current_owner_input is None
                else settings.current_owner_input)
            prepared = self.assembler.build(settings.owner_request.context, **deepcopy(current_input))

            def read_original():
                return self.worker.read_completed(settings.identity,
                    current_context=settings.owner_request.context, reading=prepared.reading,
                    execution_versions=prepared_action_execution_versions(prepared,
                        client_version=self.worker.client_version, model_version=self.worker.model_version),
                    validate_current=lambda value: self._validate_saved(value, prepared.reading))

            try:
                saved = read_original()
                # Use the issued observation authenticated by the settlement
                # itself. A second native query can lawfully have a later
                # timestamp/version and cannot identify the earlier ledger.
                settlement = self.settlement_reconciler.query(TaskIdentity(**settings.identity.as_dict()))
                issued = (deepcopy(settlement['issued_reception']) if settlement is not None
                    else self.submission.query_execution(TaskIdentity(**settings.identity.as_dict())))
                if issued is None:
                    return None
                expected = {'schema_version': 'owner-payment-issued-reception.v1',
                    'source_identity': settings.identity.as_dict(), 'source_record_sha256': settings.source_record_sha256,
                    'source_result_sha256': settings.source_result_sha256, 'source_reading_sha256': settings.source_reading_sha256}
                if any(issued.get(key) != value for key, value in expected.items()):
                    raise TaskConflict('Payment reader substitutes original issued command group provenance')
                observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
                self.check_execution_selection(observation)
                if settlement is None and all(line.execution.status not in {'pending', 'unknown'} for line in observation.lines):
                    return None
                if settlement is not None and (
                        settlement.get('schema_version') != OwnerPaymentSettlementReconciler.VERSION
                        or any(settlement.get(key) != value for key, value in expected.items() if key != 'schema_version')
                        or settlement.get('issued_reception_sha256') != task_digest(issued)):
                    raise TaskConflict('Payment settlement observation differs from the original issued command group')
                reception = OwnerPaymentExecutionReception(saved=deepcopy(saved),
                    issued_reception=deepcopy(issued), settlement=deepcopy(settlement))
                if self.validate_disclosure(reception=deepcopy(reception),
                        context=settings.recipient_context.model_copy(deep=True),
                        execution_refs=deepcopy(settings.execution_refs)) is not True:
                    raise TaskConflict('Application did not authorize complete payment/native evidence disclosure to Contractor')
                if read_original() != saved:
                    raise TaskConflict('Original Owner payment decision changed during Contractor native observation')
                return reception
            finally:
                prepared.reading.recheck()
                self._check()
                if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                        or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                        or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                    raise TaskConflict('Payment native observation changed the original current Owner source snapshot')


def bind_contractor_payment_reader(*, sources, reader, validate_reception):
    """Use the existing Contractor payment source binder with concrete authority checks."""
    if (not isinstance(sources, ContractorRoleContractSources) or not isinstance(reader, OwnerPaymentExecutionReader)
            or not callable(validate_reception)):
        raise ValueError('Payment binding requires actual Contractor sources, original payment reader and receiver validator')
    recipient = reader.settings.recipient_context.model_copy(deep=True)
    original_components = (sources, sources.store, sources.registry, sources.organizations,
        sources.provider, sources.read_guard, sources.validators, sources.evidence, reader, validate_reception)

    def declaration():
        return {'schema_version': 'contractor-original-payment-reader-binding.v1',
            'recipient_source_version': sources.version,
            **reader.configuration_evidence(),
            'receiver_validator': module_factory_descriptor(validate_reception, 'validate_received_payments'),
            'receiver_validator_implementation': callable_implementation(validate_reception)}

    declared = declaration()

    def check_binding():
        current_components = (sources, sources.store, sources.registry, sources.organizations,
            sources.provider, sources.read_guard, sources.validators, sources.evidence, reader, validate_reception)
        if (any(current is not original for current, original in zip(current_components, original_components))
                or declaration() != declared):
            raise TaskConflict('Contractor payment binding changed original sources or reader declaration')
        if sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id:
            raise TaskConflict('Contractor payment binding changes original recipient run')
        registration = sources.registry.get('CONTRACTOR-A10')
        grants = sources.organizations.grants(recipient, 'CONTRACTOR-A10', 'Contractor')
        if registration.role != 'Contractor' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Payment binding requires current Contractor payment authority and original Skill')
        return grants[0].organization_id

    recipient_org = check_binding()

    def read(*, context, source_task_sha256):
        if check_binding() != recipient_org:
            raise TaskConflict('Contractor payment binding changes original recipient organization')
        try:
            return reader.read(context=context, source_task_sha256=source_task_sha256)
        finally:
            if check_binding() != recipient_org:
                raise TaskConflict('Contractor payment reading changed original recipient authority')

    def reception(**payment):
        if check_binding() != recipient_org or payment['context'] != recipient:
            raise TaskConflict('Contractor payment reception changes original current recipient authority')
        if (payment['reception'].saved.identity.as_dict() != reader.settings.identity.as_dict()
                or not {execution.ref.key() for execution in payment['executions']}
                    <= {ref.key() for ref in reader.settings.execution_refs}):
            raise TaskConflict('Contractor payment reception selects commands outside the authorized original disclosure')
        try:
            return validate_reception(**payment) is True
        finally:
            if check_binding() != recipient_org:
                raise TaskConflict('Contractor payment reception changed original recipient authority')

    def evidence():
        if check_binding() != recipient_org:
            raise TaskConflict('Contractor payment evidence changed original recipient authority')
        original = sources.evidence()
        if not isinstance(original, dict) or 'original_owner_payment_reader' in original:
            raise TaskConflict('Contractor payment binding requires original source evidence without collision')
        if check_binding() != recipient_org:
            raise TaskConflict('Contractor payment source evidence changed original binding')
        return {**deepcopy(original), 'original_owner_payment_reader': deepcopy(declared)}

    enriched = replace(sources, evidence=evidence)
    return bind_contractor_received_payment_sources(enriched,
        read_owner_payment=read, validate_reception=reception)
