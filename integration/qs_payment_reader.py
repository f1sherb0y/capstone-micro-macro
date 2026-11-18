"""Read the original QS payment application and actual current resubmission."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_payment_objects import QSPaymentApplicationView, QSPaymentContractView, QSPaymentCertificateView, QSPaymentReceiptView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_payment_conditions import QSPaymentConditionReading, _CODE
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSPaymentCurrentSelection:
    request: RoleContractInvocation


class QSPaymentRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSPaymentRecoveryBindings:
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable

    def components(self):
        return tuple(getattr(self, name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate'))

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()):
            raise ValueError('QS payment recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSPaymentReader:
    """Assemble a fresh valuation using the same journal's immutable snapshot.

    Actual history is read under the caller's source/authority/journal guard.
    Native validation authenticates resubmission and superseded certificates;
    no valuation processor, calculation, certificate or payment executes here.
    """
    ACTION_ID = 'QS-A08'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSPaymentActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS payment reader requires actual formal assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-payment-reader.v1', 'action_id': self.ACTION_ID, 'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode, 'macro_version': a.macro_version,
            'policy_version': a.policy_version, 'model_version': a.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current, a = self._components(), self.assembler
        if (len(current) != len(self._original_components) or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A08' or a.ACTION_ID != self.ACTION_ID or a.source_mode != 'formal'
                or a._views.source_mode != 'formal' or a._views.organizations is not a.organizations
                or a._views.provider is not a.provider or a._views.macro_version != a.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS payment reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'PaymentApplication'):
            raise TaskConflict('QS payment reader replaces original application wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if original_input.application_ref.key() != old_refs[0].key():
            raise TaskConflict('QS payment wait differs from its original invocation snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSPaymentCurrentSelection):
            raise TaskConflict('QS payment reader requires a typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope'] or current_input.scope != original_input.scope
                or current_input.application_ref.key()[:2] != original_input.application_ref.key()[:2]
                or current_input.contract_ref.key()[:2] != original_input.contract_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS payment reader substitutes original contract/application/scope or authorized historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS payment assembly changed original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)
            for action_input in (original_input, prepared.action_input):
                application, contract = reading.resolve(action_input.application_ref), reading.resolve(action_input.contract_ref)
                if (not isinstance(application, QSPaymentApplicationView) or not isinstance(contract, QSPaymentContractView)
                        or application.contract_ref != contract.ref or application.applicant_id != contract.beneficiary_id
                        or contract.valuation_organization_id != source['organization_id']):
                    raise TaskConflict('QS payment reader changes original beneficiary or contract association')
                # Read declared histories even when withdrawal originally
                # prevented them from being selected in the action input.
                for refs in (application.work_refs, contract.active_certificate_refs, contract.receipt_refs,
                        contract.advance_credit_refs, contract.deduction_refs, contract.rate_refs):
                    for ref in refs:
                        reading.resolve(ref)
                for ref in contract.active_certificate_refs:
                    certificate = reading.resolve(ref)
                    if not isinstance(certificate, QSPaymentCertificateView) or certificate.contract_ref != contract.ref:
                        raise TaskConflict('QS payment reader substitutes original certificate history')
                for ref in contract.receipt_refs:
                    receipt = reading.resolve(ref)
                    if (not isinstance(receipt, QSPaymentReceiptView) or receipt.contract_ref != contract.ref
                            or receipt.payer_id != contract.payer_id or receipt.beneficiary_id != contract.beneficiary_id):
                        raise TaskConflict('QS payment reader substitutes original payment receipt parties or contract')
            return QSPaymentConditionReading(prepared.context, reading, deepcopy(snapshot['action_input']),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck(); self._check()
            current = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot or any(current.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS payment reader changed original snapshot or assembled context/input/source reading')


def build_assembled_qs_payment_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one actual source/authority/inbox/journal guard across QS recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_payment_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS payment recovery requires actual same-run guard and validators')
    reader = QSPaymentReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('QS payment successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_qs_payment_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    journal, registry, final_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not journal
                or journal.store is not store or journal.registry is not registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not final_revalidate
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS payment recovery changed original journal/recipient/source callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS payment recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role='QS')
