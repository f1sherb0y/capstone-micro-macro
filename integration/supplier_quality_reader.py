"""Read original Supplier A07 batch dispositions for guarded wait recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_quality_actions import SupplierQualityActionAssembler
from integration.supplier_resource_reader import _build_assembled_supplier_input_dispatcher
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings, SupplierTransportRecoverySettings
from src.actions.contracts.common import Reference
from src.actions.roles.supplier_quality_history import validate_isolation_release_recheck
from src.actions.contracts.supplier_quality_objects import (
    SupplierBatchDispositionExecutionView, SupplierBatchLineageLedgerView, SupplierQualityBatchView, SupplierQualityProfileView,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_quality_conditions import SupplierQualityConditionReading, _CODES
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class SupplierQualityCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class SupplierQualityRecoverySettings(SupplierTransportRecoverySettings):
    """Original A07 quality source, policy and binding versions."""


@dataclass(frozen=True)
class SupplierQualityRecoveryBindings(SupplierTransportRecoveryBindings):
    """Actual quality selector, original guard and native/successor validators."""


class SupplierQualityReader:
    """Assemble a fresh quality judgment without replaying disposition effects.

    The original batch/profile/input is recovered from the same task journal.
    Current batch and execution versions must be explicitly authorized. Native
    condition validation authenticates full stock/isolation/recheck history and
    the current independent decision; the ordinary processor retains its gates.
    Reading creates no inspection result, disposition permission or stock change.
    """
    ACTION_ID = 'SUPPLIER-A07'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, SupplierQualityActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id or not callable(select_current)):
            raise ValueError('Supplier quality reader requires original formal A07 assembler, snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.view_provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.snapshots, self.snapshots.store,
            self.select_current, validate_isolation_release_recheck, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': 'supplier-quality-reader.v2', 'action_id': self.ACTION_ID,
            'condition_codes': list(_CODES), 'run_id': self.assembler.organizations.run_id,
            'source_mode': self.assembler.source_mode, 'macro_version': self.assembler._views.macro_version,
            'policy_version': self.assembler.policy_version, 'model_version': self.assembler.model_version,
            'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'release_recheck': module_factory_descriptor(validate_isolation_release_recheck, 'release_recheck'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.ACTION_ID != 'SUPPLIER-A07' or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self._configuration() != self._declared):
            raise TaskConflict('Supplier quality reader changed original source/model/snapshot components or declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Supplier' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'BatchDispositionExecution' for ref in old_refs)
                or len({ref.key()[:2] for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Supplier quality reader replaces original disposition wait, recipient or commands')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, SupplierQualityCurrentSelection) or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Supplier quality reader requires typed current request and explicit disposition versions')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        refs = tuple(ref.model_copy(deep=True) for ref in selected.execution_refs)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or len(refs) != len(old_refs) or len({ref.key()[:2] for ref in refs}) != len(refs)
                or {ref.key()[:2] for ref in refs} != {ref.key()[:2] for ref in old_refs}
                or not {ref.key() for ref in (*old_refs, *refs, original_input.batch_ref, original_input.inspection_profile_ref)}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Supplier quality reader requires original scope, visible history and fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Supplier quality assembly changes original snapshot or authorized recipient')
            original_batch = reading.resolve(original_input.batch_ref)
            batch = reading.resolve(prepared.action_input.batch_ref)
            profile = reading.resolve(prepared.action_input.inspection_profile_ref)
            if (not isinstance(original_batch, SupplierQualityBatchView) or not isinstance(batch, SupplierQualityBatchView)
                    or original_batch.ref.key()[:2] != batch.ref.key()[:2]
                    or any(getattr(original_batch, field) != getattr(batch, field) for field in (
                        'organization_id', 'owner_id', 'product_ref', 'physical_batch_key', 'scope'))
                    or not isinstance(profile, SupplierQualityProfileView) or profile.batch_ref != batch.ref):
                raise TaskConflict('Supplier quality reader replaces original physical batch, title, product or current profile')
            ledger = reading.resolve(batch.lineage_ledger_ref)
            if (not isinstance(ledger, SupplierBatchLineageLedgerView) or ledger.physical_batch_key != batch.physical_batch_key
                    or ledger.organization_id != source['organization_id'] or ledger.coverage != 'complete'
                    or ledger.as_of != context.business_time
                    or len({ref.key()[:2] for ref in ledger.execution_refs}) != len(ledger.execution_refs)
                    or not {ref.key() for ref in refs} <= {ref.key() for ref in ledger.execution_refs}):
                raise TaskConflict('Supplier quality reader requires complete current original batch disposition ledger')
            current_refs = {ref.key()[:2]: ref for ref in refs}
            for old_ref in old_refs:
                ref = current_refs[old_ref.key()[:2]]
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if (not isinstance(original, SupplierBatchDispositionExecutionView) or not isinstance(current, SupplierBatchDispositionExecutionView)
                        or original.ref != old_ref or current.ref != ref
                        or current.organization_id != source['organization_id'] or current.physical_batch_key != batch.physical_batch_key
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'physical_batch_key', 'organization_id', 'operation_id', 'business_key', 'choice', 'quantity', 'scope'))
                        or original.status != 'submitted_unknown' and current.status != original.status
                        or original.status == 'recorded' and any(getattr(original, field) != getattr(current, field) for field in (
                            'core_event_id', 'isolated_quantity_decrease', 'release_basis_ref'))):
                    raise TaskConflict('Supplier quality reader replaces original disposition command, quantity or known effects')
            return SupplierQualityConditionReading(prepared.context, reading, refs,
                deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck()
            self._check()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Supplier quality reader changed original snapshot or assembled input/context/source reading')


def build_assembled_supplier_quality_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one original source/authority/inbox/journal guard across quality recovery."""
    from integration.task_continuation import build_supplier_quality_continuation_dispatcher

    return _build_assembled_supplier_input_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=SupplierQualityReader, dispatcher_factory=build_supplier_quality_continuation_dispatcher)
