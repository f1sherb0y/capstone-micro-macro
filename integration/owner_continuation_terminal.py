"""Read and archive actual original Owner transitions without repeating a transition."""
from copy import deepcopy
from dataclasses import dataclass

from integration.architect_learning_terminal import _reconcile_learning_wait
from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
from integration.owner_continuation_execution_reader import OwnerContinuationExecutionReader
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.coordination.owner_continuation_terminal import EXECUTION_CODE, OwnerContinuationTerminalReading, check_owner_continuation_terminal
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class OwnerContinuationTerminalSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class OwnerContinuationTerminalReader(OwnerContinuationExecutionReader):
    CONDITION_CODE = EXECUTION_CODE
    EXECUTION_KIND = 'ContinuationExecution'
    SELECTION_TYPE = OwnerContinuationTerminalSelection
    READING_TYPE = OwnerContinuationTerminalReading
    READER_SCHEMA = 'owner-continuation-terminal-reader.v1'
    def __init__(self, *, assembler, snapshots, select_current):
        self.snapshots = snapshots
        if snapshots.store.run_id != assembler.organizations.run_id:
            raise ValueError('Owner terminal archive requires the original run snapshots')
        super().__init__(assembler=assembler, select_current=select_current)

    def _components(self):
        return (*super()._components(), self.snapshots, self.snapshots.store, self.ASSEMBLER_TYPE,
            self.SELECTION_TYPE, self.READING_TYPE,
            self.assembler.methods, self.assembler._views.schemas, *self.assembler.decision_strategies)

    def _configuration(self):
        return super()._configuration() | dict(schema_version=self.READER_SCHEMA,
            action_id=self.ACTION_ID, condition_code=self.CONDITION_CODE, execution_kind=self.EXECUTION_KIND,
            snapshot_schema=self.snapshots.SCHEMA, policy_version=self.assembler.policy_version)

    def __call__(self, check, *, execution_terminal=False):
        self._check()
        source = check.source['identity']
        if (execution_terminal is not True or source['action_id'] != self.ACTION_ID
                or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != self.CONDITION_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != (self.EXECUTION_KIND,)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Owner terminal archive requires original same-business wait and recipient')
        identity = TaskIdentity(**source)
        snapshot = self.snapshots.get(identity)
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Owner terminal archive changes original persisted snapshot')
        original_context = ActionContext.model_validate(snapshot['context'])
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE) or not isinstance(selected.execution_ref, Reference):
            raise TaskConflict('Owner terminal archive requires typed actual original execution selection')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref = request.context, selected.execution_ref.model_copy(deep=True)
        if (request.action_input != snapshot['action_input'] or context.run_id != source['run_id']
                or context.contract_ref != original_context.contract_ref or context.scope != original_context.scope
                or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
                or context.operation_id != source['request_id'] or context.execution_mode != 'llm'
                or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset
                or ref.key()[:2] != check.condition.object_refs[0].key()[:2]
                or request.execution_path not in {None, registration.strategy}
                or not {value.key() for value in (*walk_references(original_input), ref, check.condition.object_refs[0])}
                    <= {value.key() for value in context.visible_refs}):
            raise TaskConflict('Owner terminal archive changes original input/actor/scope or actual query visibility')
        prepared = self.assembler.build(context, **deepcopy(snapshot['action_input']))
        try:
            prepared.reading.resolve(ref)
            return self.READING_TYPE(prepared.context, prepared.reading, original_context,
                original_input, prepared.action_input, ref)
        finally:
            prepared.reading.recheck()
            self._check()
            if self.snapshots.get(identity) != snapshot:
                raise TaskConflict('Owner terminal archive rewrote original persisted invocation')


@dataclass(frozen=True)
class OwnerContinuationTerminalBridge(ExecutionWaitRecoveryBridge):
    terminal_reader: object = None
    native_validator: object = None

    def _components(self):
        return (*super()._components(), self.terminal_reader, self.native_validator)

    def _check(self):
        super()._check()
        self.terminal_reader._check()


def reconcile_owner_continuation_execution(*, identity, signal, bridge, validate_relation):
    return _reconcile_owner_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_owner_continuation_terminal,
        action_id='OWN-A13', condition_code=EXECUTION_CODE)


def _reconcile_owner_terminal_wait(*, identity, signal, bridge, validate_relation, checker, action_id, condition_code):
    bridge._check()
    if validate_relation is not bridge.native_validator:
        raise TaskConflict('Owner terminal archive replaces original native validator')
    reader = bridge.terminal_reader

    def authenticate(**kwargs):
        bridge._check()
        original = TaskIdentity(**kwargs['source_identity'])
        snapshot = reader.snapshots.get(original)
        if (snapshot['context'] != kwargs['original_context'].model_dump(mode='json')
                or snapshot['action_input'] != kwargs['original_action_input']):
            raise TaskConflict('Owner terminal authentication replaces original persisted snapshot')
        try:
            return validate_relation(**kwargs)
        finally:
            bridge._check()
            if reader.snapshots.get(original) != snapshot:
                raise TaskConflict('Owner native authentication rewrote original invocation')

    result = _reconcile_learning_wait(identity=identity, signal=signal, reader=reader,
        dispatcher=bridge.dispatcher, validate_relation=authenticate, condition_code=condition_code,
        checker=checker, reader_options={'execution_terminal': True},
        proof=lambda resolution: resolution['execution'], action_id=action_id, role='Owner')
    bridge._check()
    return result
