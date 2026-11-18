"""Wire original command journals and actual native financial observations to Owner sources."""
from copy import deepcopy
from dataclasses import replace

from integration.module_host import module_factory_descriptor
from integration.owner_payment_actions import PreparedOwnerPayment
from integration.owner_payment_command_host import OwnerPaymentCommandHost
from integration.owner_payment_execution_reception import (
    OwnerPaymentExecutionReception, bind_owner_payment_execution_sources,
)
from integration.owner_payment_settlement import OwnerPaymentSettlementReconciler
from integration.owner_payment_submission import OwnerPaymentExecutionObservation
from integration.owner_role_contract_host import OwnerRoleContractSources
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class _CommandReceptionSources:
    VERSION = 'owner-payment-command-reception-sources.v1'

    def __init__(self, sources, command_host, reconciler, histories, prepare_current, validate_history):
        self.sources, self.command_host, self.reconciler = sources, command_host, reconciler
        self.histories = {key: TaskIdentity(**identity.as_dict()) for key, identity in histories.items()}
        self.prepare_current, self.validate_history = prepare_current, validate_history
        self.worker = command_host.submission.worker
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        return (self.sources, self.sources.store, self.sources.registry,
            self.sources.organizations, self.sources.provider, self.sources.read_guard,
            self.sources.validators, self.sources.evidence, self.command_host,
            self.reconciler, self.worker, self.prepare_current, self.validate_history)

    def _check_components(self):
        if any(current is not original for current, original in
                zip(self._components(), self._original_components)):
            raise TaskConflict('Payment reception replaced original current sources or command components')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'owner_source_version': self.sources.version,
            'command_configuration_sha256': task_digest(self.command_host._declared),
            'source_identities': {key: identity.as_dict() for key, identity in sorted(self.histories.items())},
            'prepare_current': module_factory_descriptor(self.prepare_current, 'prepare_current'),
            'validate_history': module_factory_descriptor(self.validate_history, 'validate_history'),
            'native_settlement_reader': module_factory_descriptor(self.reconciler.read_native_settlement, 'read_native_settlement'),
            'native_settlement_validator': module_factory_descriptor(self.reconciler.validate_native_settlement, 'validate_native_settlement')}

    def _check(self, context):
        self._check_components()
        self.command_host._check()
        self.reconciler._check()
        if (self.command_host.submission is not self.reconciler.submission
                or self.worker is not self.command_host.submission.worker
                or self.worker.store is not self.sources.store or self.worker.registry is not self.sources.registry
                or self._configuration() != self._declared
                or context.execution_mode == 'offline_fixture' or context.run_id != self.sources.store.run_id
                or context.contract_ref.id != 'OWN-A06'):
            raise TaskConflict('Payment reception replaced original source, journal, command/settlement binding or formal context')

    def read(self, *, context, source_task_sha256):
        """Read original history and native observations; never submit or recover.

        The Owner host holds sources.read_guard(context) throughout this
        callback, during both preparation and execution. Borrow that current
        source boundary instead of reentering a potentially non-reentrant lock.
        Original command history still requires command_host.read_guard(identity).
        """
        self._check(context)
        identity = self.histories.get(source_task_sha256)
        if identity is None:
            raise TaskConflict('Payment reception requires an explicitly declared original task')
        prepared = self.prepare_current(context=context.model_copy(deep=True))
        if (not isinstance(prepared, PreparedOwnerPayment) or prepared.context != context
                or prepared.runner.registry is not self.sources.registry
                or prepared.runner.organizations is not self.sources.organizations
                or prepared.reading.organization_id != identity.organization_id):
            raise TaskConflict('Original history reader requires the current actual Owner prepared source snapshot')
        before = (task_digest(prepared.context.model_dump(mode='json')),
            task_digest(prepared.action_input.model_dump(mode='json')), task_digest(prepared.reading.evidence()))
        if before != (prepared.context_sha256, prepared.input_sha256, prepared.reading_sha256):
            raise TaskConflict('Current payment history sources were modified before authorized reading')
        try:
            saved = self.worker.read_completed(identity, current_context=context, reading=prepared.reading,
                execution_versions=deepcopy(identity.versions),
                validate_current=lambda original: self.validate_history(saved=original,
                    prepared=prepared, context=context.model_copy(deep=True)))
            with self.command_host.read_guard(TaskIdentity(**identity.as_dict())):
                progress = self.command_host._read_progress_guarded(identity)
                if not progress['commands'] or any(row['submission'] is None for row in progress['commands']):
                    return None
                settlement = self.reconciler.query(identity)
                issued = (deepcopy(settlement['issued_reception']) if settlement is not None
                    else self.command_host.submission.query_execution(identity))
                if issued is None:
                    return None
                observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
                lines = sorted(observation.lines, key=lambda value: value.line_index)
                rows = progress['commands']
                if len(rows) != len(lines):
                    raise TaskConflict('Native observation omits an original journal command')
                for row, line in zip(rows, lines):
                    output = row['output']
                    if (output['line_index'] != line.line_index
                            or output['command_id'] != line.execution.command_id
                            or output['business_key'] != line.execution.business_key
                            or output['source_identity'] != saved.identity.as_dict()
                            or output['source_record_sha256'] != saved.record_sha256
                            or output['source_result_sha256'] != task_digest(saved.result.model_dump(mode='json'))
                            or output['source_reading_sha256'] != saved.source_reading_sha256):
                        raise TaskConflict('Native issuance replaces its original command/business identity or journal provenance')
                    if (row['state'] == 'reconciled' and row['receipt']['disposition'] == 'rejected'
                            and line.execution.status != 'rejected'):
                        raise TaskConflict('Rejected native command registration cannot become a successful or uncertain payment')
                if settlement is None and all(line.execution.status not in {'unknown', 'pending'} for line in lines):
                    return None
                if self.command_host._read_progress_guarded(identity) != progress:
                    raise TaskConflict('Original native command journal changed during actual financial observation')
                current = self.worker.read_completed(identity, current_context=context, reading=prepared.reading,
                    execution_versions=deepcopy(identity.versions),
                    validate_current=lambda original: self.validate_history(saved=original,
                        prepared=prepared, context=context.model_copy(deep=True)))
                if current != saved:
                    raise TaskConflict('Original payment decision changed during authorized native observation')
                return OwnerPaymentExecutionReception(saved=deepcopy(saved), issued_reception=deepcopy(issued),
                    settlement=deepcopy(settlement))
        finally:
            prepared.reading.recheck()
            if before != (task_digest(prepared.context.model_dump(mode='json')),
                    task_digest(prepared.action_input.model_dump(mode='json')), task_digest(prepared.reading.evidence())):
                raise TaskConflict('Native command reception changed the current Owner source snapshot')
            self._check(context)

    def evidence(self):
        self._check_components()
        if self._configuration() != self._declared:
            raise TaskConflict('Native command reception configuration changed')
        return {**deepcopy(self.sources.evidence()), 'native_payment_command_sources': deepcopy(self._declared)}


def bind_owner_payment_command_sources(sources, *, command_host, reconciler, histories,
        prepare_current, validate_history, validate_reception):
    """Connect the actual command host to an existing current Owner source factory.

    histories maps original task keys to TaskIdentity objects from the same
    Owner journal. prepare_current(context) assembles current authorized sources
    without executing the action or reacquiring the caller's current-source
    guard. The attached reader is called under sources.read_guard(context), as
    enforced by the Owner host; direct callers must hold that same boundary.
    The command guard remains independently required for original task access
    and must support acquisition while the current-source boundary is held.
    validate_history(saved, prepared, context) verifies all original execution
    versions and current own-history access.
    validate_reception retains the existing complete receiver mapping protocol.
    This binder only reads. Sending untouched children remains an explicit
    command_host.submit call; recover/query do not occur as implicit mutations.
    """
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(command_host, OwnerPaymentCommandHost)
            or not isinstance(reconciler, OwnerPaymentSettlementReconciler)
            or command_host.submission is not reconciler.submission
            or command_host.store is not sources.store or command_host.submission.worker.registry is not sources.registry
            or not isinstance(histories, dict) or not histories
            or not all(isinstance(identity, TaskIdentity) and key == identity.key
                and identity.role == 'Owner' and identity.action_id == 'OWN-A06' and identity.purpose == 'action'
                and identity.run_id == sources.store.run_id and identity.organization_id in sources.store.organization_ids
                for key, identity in histories.items())
            or not all(callable(callback) for callback in (prepare_current, validate_history, validate_reception))):
        raise ValueError('Actual command sources require shared original journal/registry, explicit histories and authorized readers')
    binding = _CommandReceptionSources(sources, command_host, reconciler, histories, prepare_current, validate_history)
    enriched = replace(sources, version=sources.version + '+' + binding.VERSION, evidence=binding.evidence)
    return bind_owner_payment_execution_sources(enriched, read_owner_payment_execution=binding.read,
        validate_reception=validate_reception)
