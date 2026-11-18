"""Read original native payment/settlement history for current Owner reception."""
from copy import deepcopy
from dataclasses import replace

from integration.module_host import module_factory_descriptor
from integration.owner_payment_actions import PreparedOwnerPayment
from integration.owner_payment_execution_reception import (
    OWNER_PAYMENT_EXECUTION_SOURCE_VERSION, OwnerPaymentExecutionReception, bind_owner_payment_execution_sources,
)
from integration.owner_payment_submission import OwnerPaymentExecutionObservation, OwnerPaymentSubmission
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.owner_submission_host import OwnerSubmissionHost
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class _NativePaymentReception:
    VERSION = 'owner-native-payment-reception-sources.v1'

    def __init__(self, sources, host, histories, prepare_current, validate_history):
        self.sources, self.host = sources, host
        self.submission = host.routes['OWN-A06']
        self.reconciler = host.payment_settlements['OWN-A06']
        self.worker = self.submission.worker
        self.histories = {key: TaskIdentity(**identity.as_dict()) for key, identity in histories.items()}
        self.prepare_current, self.validate_history = prepare_current, validate_history
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        return (self.sources, self.sources.store, self.sources.registry, self.sources.organizations,
            self.sources.provider, self.sources.read_guard, self.sources.validators, self.sources.evidence,
            self.host, self.submission, self.reconciler, self.worker, self.prepare_current, self.validate_history)

    def _configuration(self):
        return {'schema_version': self.VERSION, 'owner_source_version': self.sources.version,
            'submission_host_sha256': task_digest(self.host._declared),
            'source_identities': {key: identity.as_dict() for key, identity in sorted(self.histories.items())},
            'prepare_current': module_factory_descriptor(self.prepare_current, 'prepare_payment_reception'),
            'validate_history': module_factory_descriptor(self.validate_history, 'validate_payment_history')}

    def _check_binding(self):
        if (any(current is not original for current, original in zip(self._components(), self._original_components))
                or self.host.routes.get('OWN-A06') is not self.submission
                or self.host.payment_settlements.get('OWN-A06') is not self.reconciler
                or self.reconciler.submission is not self.submission
                or self.submission.worker is not self.worker or self.worker.store is not self.sources.store
                or self.worker.registry is not self.sources.registry or self._configuration() != self._declared):
            raise TaskConflict('Native Owner reception replaced original sources, payment route or declared history')
        self.host._check()

    def read(self, *, context, source_task_sha256):
        """Caller holds current sources.read_guard; no guard reentry or submission.

        prepare_current only assembles the current snapshot under that boundary.
        validate_history independently authorizes original own-history access.
        The native route still checks original query permission; it is called
        directly under the held current boundary, without nesting host guards.
        """
        self._check_binding()
        identity = self.histories.get(source_task_sha256)
        if (identity is None or context.execution_mode == 'offline_fixture'
                or context.run_id != self.sources.store.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'OWN-A06'):
            raise TaskConflict('Native reception requires a current formal Owner context and declared original task')
        prepared = self.prepare_current(context=context.model_copy(deep=True))
        if (not isinstance(prepared, PreparedOwnerPayment) or prepared.context != context
                or prepared.runner.registry is not self.sources.registry
                or prepared.runner.organizations is not self.sources.organizations
                or prepared.reading.organization_id != identity.organization_id
                or prepared.reading._resolver.source_mode != 'formal'):
            raise TaskConflict('Native reception requires the actual current Owner prepared source snapshot')

        def snapshot():
            return (task_digest(prepared.context.model_dump(mode='json')),
                task_digest(prepared.action_input.model_dump(mode='json')), task_digest(prepared.reading.evidence()))

        before = snapshot()
        if before != (prepared.context_sha256, prepared.input_sha256, prepared.reading_sha256):
            raise TaskConflict('Current native payment reception sources changed before reading')

        def read_original():
            return self.worker.read_completed(TaskIdentity(**identity.as_dict()), current_context=context,
                reading=prepared.reading, execution_versions=deepcopy(identity.versions),
                validate_current=lambda saved: self.validate_history(saved=saved,
                    prepared=prepared, context=context.model_copy(deep=True)))

        try:
            saved = read_original()
            settlement = self.reconciler.query(TaskIdentity(**identity.as_dict()))
            issued = (deepcopy(settlement['issued_reception']) if settlement is not None
                else self.submission.query_execution(TaskIdentity(**identity.as_dict())))
            if issued is None:
                return None
            observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
            if settlement is None and all(line.execution.status not in {'unknown', 'pending'} for line in observation.lines):
                return None
            if read_original() != saved:
                raise TaskConflict('Original Owner decision changed during native payment reception')
            return OwnerPaymentExecutionReception(saved=deepcopy(saved),
                issued_reception=deepcopy(issued), settlement=deepcopy(settlement))
        finally:
            prepared.reading.recheck()
            if snapshot() != before:
                raise TaskConflict('Native reception changed the current Owner input or source snapshot')
            self._check_binding()

    def evidence(self):
        self._check_binding()
        return {**deepcopy(self.sources.evidence()), 'native_payment_reception': deepcopy(self._declared)}


def native_payment_reception_source_version(base_version):
    """Declare the actual enriched version without constructing a native host."""
    return base_version + '+' + _NativePaymentReception.VERSION + '+' + OWNER_PAYMENT_EXECUTION_SOURCE_VERSION


def bind_owner_native_payment_reception(sources, *, submission_host, histories,
        prepare_current, validate_history, validate_reception):
    """Borrow original formal native routes and attach mandatory current reception.

    No child command host is assumed: aggregate native payment routes retain
    their own real transport semantics. This binder reads original history and
    independent settlement only, under the caller's current source guard.
    That guard must also protect the original task's native query and ledger
    access; validate_history checks its current authority. The binder does not
    assume a second guard can safely nest under the current boundary.
    The complete-group receiver still authenticates native evidence, receipts
    and current private ledger mappings. Resources remain application-owned.
    """
    if (not isinstance(sources, OwnerRoleContractSources) or not isinstance(submission_host, OwnerSubmissionHost)
            or not isinstance(submission_host.routes.get('OWN-A06'), OwnerPaymentSubmission)
            or 'OWN-A06' not in submission_host.payment_settlements
            or submission_host.store is not sources.store or submission_host.registry is not sources.registry
            or not isinstance(histories, dict) or not histories
            or not all(isinstance(identity, TaskIdentity) and key == identity.key and identity.role == 'Owner'
                and identity.action_id == 'OWN-A06' and identity.purpose == 'action'
                and identity.run_id == sources.store.run_id and identity.organization_id in sources.store.organization_ids
                for key, identity in histories.items())
            or not all(callable(callback) for callback in (prepare_current, validate_history, validate_reception))):
        raise ValueError('Native reception requires original Owner routes, explicit own histories and current validators')
    binding = _NativePaymentReception(sources, submission_host, histories, prepare_current, validate_history)
    binding._check_binding()
    enriched = replace(sources, version=sources.version + '+' + binding.VERSION, evidence=binding.evidence)
    return bind_owner_payment_execution_sources(enriched, read_owner_payment_execution=binding.read,
        validate_reception=validate_reception)
