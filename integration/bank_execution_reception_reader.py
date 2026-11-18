"""Authenticate actual original Bank execution/receipt sources for existing processing."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace

from integration.bank_execution_reception import BankExecutionReceptionSettings, _ExecutionReception
from integration.bank_execution_results import BankExecutionResultWorker
from integration.bank_role_contract_host import BankRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import EvidenceRecord
from src.coordination.tasks import TaskConflict, task_digest


class BankExecutionReceptionReaderSettings(BankExecutionReceptionSettings):
    request: RoleContractInvocation

    @property
    def recipient_context(self):
        return self.request.context


class BankExecutionReceptionReader(_ExecutionReception):
    """Borrow the original worker and observations; never submit or query commands.

    The caller holds sources.read_guard, as the Bank host does during both
    preparation and execution. The independent application validator must
    authenticate native command history, complete coverage and its mapping to
    current authorized sources, including uncertain and partial outcomes.
    """
    VERSION = 'formal-bank-execution-reception-reader.v1'

    def __init__(self, *, settings, sources, worker, validate_reception):
        settings = BankExecutionReceptionReaderSettings.model_validate(settings).model_copy(deep=True)
        if (not isinstance(sources, BankRoleContractSources)
                or not isinstance(worker, BankExecutionResultWorker) or not callable(validate_reception)):
            raise ValueError('Execution reception requires actual Bank sources, original worker and native validator')
        super().__init__(settings.request, settings, sources, worker)
        self.validate_reception = validate_reception
        self._original_components = self._components()
        self._validator_descriptor = module_factory_descriptor(validate_reception, 'validate_reception')
        self._check_binding()

    @property
    def reception(self):
        return self.settings

    def _components(self):
        return (self.sources, self.worker, self.worker.store, self.worker.snapshots,
            self.worker.registry, self.sources.registry, self.sources.organizations,
            self.sources.provider, self.sources.read_guard, self.sources.validators,
            self.sources.evidence, self.validate_reception)

    def _check_binding(self):
        identity, context = self.settings.identity, self.request.context
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or task_digest(self.settings.model_dump(mode='json')) != self._configuration_sha256
                or self.request != self.settings.request
                or module_factory_descriptor(self.validate_reception, 'validate_reception') != self._validator_descriptor
                or self.worker.ACTION_ID != 'BANK-A07' or identity.action_id != 'BANK-A07'
                or identity.role != 'Bank' or identity.purpose != 'action'
                or context.contract_ref.id != 'BANK-A07' or context.execution_mode != 'llm'
                or self.request.action_input.get('operation_context', {}).get('kind') != 'existing'
                or identity.request_id == context.operation_id
                or identity.run_id != context.run_id or self.sources.store.run_id != context.run_id
                or self.sources.organizations.run_id != context.run_id
                or self.worker.store is not self.sources.store or self.worker.registry is not self.sources.registry
                or self.worker.snapshots.store is not self.sources.store):
            raise TaskConflict('Execution reception changes original formal Bank journal, components or current declaration')
        registration = self.sources.registry.get('BANK-A07')
        grants = self.sources.organizations.grants(context, 'BANK-A07', 'Bank')
        if (registration.role != 'Bank' or not registration.implemented or registration.skill is None
                or grants[0].organization_id != identity.organization_id):
            raise TaskConflict('Execution reception requires original current same-Bank authority and Skill')

    def _guard(self, context):
        # The host already holds the current boundary; do not reenter an
        # application's potentially non-reentrant guard.
        return nullcontext()

    def _check(self, prepared):
        self._check_binding()
        super()._check(prepared)
        if (prepared.runner.registry is not self.sources.registry
                or prepared.runner.organizations is not self.sources.organizations
                or prepared.reading._resolver.source_mode != 'formal'
                or prepared.reading.organization_id != self.settings.identity.organization_id
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Execution reception changes the current Bank authority, input or formal reading')

    def _validate_history(self, saved):
        super()._validate_history(saved)
        if (saved.context.execution_mode != 'llm'
                or saved.audit.get('reading', {}).get('source_mode') != 'formal'):
            raise TaskConflict('Actual execution reception cannot use a synthetic initiation history')
        return True

    def _validate_evidence(self, observed, payload, prepared):
        return (isinstance(observed, EvidenceRecord) and observed.source_kind != 'synthetic'
            and observed.basis_kind == 'observed' and observed.content_hash == task_digest(payload)
            and (observed.effective_window is None
                or observed.effective_window.contains(prepared.context.business_time)))

    def _validate_observation(self, saved, original_approval, prepared):
        reception, reading = self.settings, prepared.reading
        if self.validate_reception(saved=deepcopy(saved), original_approval=original_approval.model_copy(deep=True),
                executions=deepcopy(reception.executions), receipts=deepcopy(reception.receipts),
                native_payload=deepcopy(reception.native_payload), relation_payload=deepcopy(reception.relation_payload),
                native_evidence=reading.resolve(reception.native_evidence_ref).model_copy(deep=True),
                relation_evidence=reading.resolve(reception.relation_evidence_ref).model_copy(deep=True),
                context=prepared.context.model_copy(deep=True)) is not True:
            raise TaskConflict('Bank did not authenticate original native commands, complete receipt coverage and current mapping')

    def read(self, prepared, *, source_task_sha256):
        return self.prepare(prepared, source_task_sha256=source_task_sha256)

    def evidence(self):
        self._check_binding()
        original = self.sources.evidence()
        if not isinstance(original, dict) or 'bank_execution_reception' in original:
            raise TaskConflict('Actual execution reception requires original provenance without collision')
        declaration = {'schema_version': self.VERSION,
            'identity': self.settings.identity.as_dict(),
            'configuration_sha256': self._configuration_sha256,
            'native_payload_sha256': task_digest(self.settings.native_payload),
            'relation_payload_sha256': task_digest(self.settings.relation_payload),
            'validator': deepcopy(self._validator_descriptor),
            'limitations': ['Observed history only; no dispatch, query, replay or inferred cash/debt.']}
        self._check_binding()
        return {**deepcopy(original), 'bank_execution_reception': declaration}


def bind_bank_execution_reception_sources(*, sources, reader, validate_reception, version):
    """Attach original same-journal observations to the Bank host's existing callback."""
    if (not isinstance(sources, BankRoleContractSources) or not isinstance(reader, BankExecutionReceptionReader)
            or reader.sources is not sources or reader.validate_reception is not validate_reception
            or not isinstance(version, str) or not version.strip()):
        raise ValueError('Execution reception binding requires its original Bank sources, reader, validator and version')
    if sources.prepare_execution_reception is not None:
        raise TaskConflict('Execution reception binding cannot replace an existing application callback')
    reader._check_binding()
    return replace(sources, version=version, prepare_execution_reception=reader.read, evidence=reader.evidence)
