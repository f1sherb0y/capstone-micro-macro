"""Read original/current service handover sources under the actual host guard."""
from copy import deepcopy
from dataclasses import dataclass

from integration.architect_learning_reader import ArchitectLearningReader, _build_assembled_learning_dispatcher
from integration.architect_submission_receipt_reader import ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings
from integration.architect_transition_actions import ArchitectTransitionActionAssembler, validate_architect_transition_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_transition_objects import architect_transition_types
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.coordination.architect_transition_conditions import (
    ArchitectTransitionConditionReading, _CODE, _CODES, _ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE,
)
from src.coordination.architect_transition_execution_query import (
    EXECUTION_CODE, ArchitectTransitionExecutionQueryRecord,
    architect_original_transition_execution_profile, check_transition_execution,
)
from src.coordination.architect_transition_allocation_query import ArchitectTransitionAllocationQueryRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class ArchitectTransitionCurrentSelection:
    request: RoleContractInvocation
    execution_query: ArchitectTransitionExecutionQueryRecord | None = None
    allocation_query: ArchitectTransitionAllocationQueryRecord | None = None


class ArchitectTransitionRecoverySettings(ArchitectSubmissionRecoverySettings):
    """Original Architect service-transition sources and policy versions."""
    terminal_execution_enabled: bool = False


@dataclass(frozen=True)
class ArchitectTransitionRecoveryBindings(ArchitectSubmissionRecoveryBindings):
    """Actual source selection, guard and independent native acceptance checks."""


class ArchitectTransitionReader(ArchitectLearningReader):
    ACTION_ID = 'ARCHITECT-A11'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    READER_SCHEMA = 'architect-transition-reader.v1'
    ASSEMBLER_TYPE = ArchitectTransitionActionAssembler
    SELECTION_TYPE = ArchitectTransitionCurrentSelection
    INPUT_ANCHORS = ('engagement_ref', 'transition_basis_ref')
    EXECUTION_KIND = 'ServiceTransitionExecution'
    EXECUTION_QUERY_TYPE = ArchitectTransitionExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(architect_original_transition_execution_profile)
    EXECUTION_CHECKER = staticmethod(check_transition_execution)
    VALIDATE_SOURCES = staticmethod(validate_architect_transition_sources)
    HISTORY_SCHEMAS = {**architect_transition_types(), 'Evidence': EvidenceRecord,
        'Authorization': Authorization, 'FunctionAssignment': RoleAssignment}

    def __call__(self, check, *, execution_terminal=False):
        self._check()
        source = check.source['identity']
        execution_wait = check.condition.condition_code == EXECUTION_CODE
        allocation_wait = check.condition.condition_code in _ALLOCATION_CODES
        dependency_wait = check.condition.condition_code == _DEPENDENCY_CODE
        capacity_wait = check.condition.condition_code == _CAPACITY_CODE
        if (source['action_id'] != self.ACTION_ID or source['role'] != self.ROLE or source['purpose'] != 'action'
                or check.condition.condition_code not in self.CONDITION_CODES or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != (('ServiceTransitionExecution',) if execution_wait else
                    ('ResourceAllocation',) if allocation_wait else ('Dependency',) if dependency_wait else
                    ('WorkProfile',) if capacity_wait else ('ServiceTransitionBasis',))
                or execution_terminal and not execution_wait
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Architect handover reader replaces original wait or authorized recipient')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        original_context = ActionContext.model_validate(snapshot['context']).model_copy(deep=True)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Architect transition reader changes original invocation digests')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE):
            raise TaskConflict('Architect handover reader requires typed independent current invocation')
        query = None if selected.execution_query is None else self.EXECUTION_QUERY_TYPE.model_validate(
            selected.execution_query).model_copy(deep=True)
        if query is not None and not execution_wait:
            raise TaskConflict('Service execution query belongs only to the original execution wait')
        allocation_query = None if selected.allocation_query is None else ArchitectTransitionAllocationQueryRecord.model_validate(
            selected.allocation_query).model_copy(deep=True)
        if allocation_query is not None and not allocation_wait:
            raise TaskConflict('Service allocation query belongs only to an original allocation wait')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, current_input = request.context, registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time
                or (context.operation_id != source['request_id'] if execution_terminal else context.operation_id == source['request_id'])
                or execution_terminal and current_input != original_input
                or context.scope != original_context.scope or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2] for field in self.INPUT_ANCHORS)
                or not execution_wait and not allocation_wait and not dependency_wait and not capacity_wait
                    and tuple(check.condition.object_refs) != (original_input.transition_basis_ref,)
                or allocation_wait and check.condition.object_refs[0] not in original_input.allocation_refs
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Architect handover reader replaces scope/service/package or historical/current source visibility')
        if query is not None and not {ref.key() for ref in walk_references(query)} <= {ref.key() for ref in context.visible_refs}:
            raise TaskConflict('Service execution reader requires authorized actual query evidence/history visibility')
        if allocation_query is not None and not {ref.key() for ref in walk_references(allocation_query)} <= {ref.key() for ref in context.visible_refs}:
            raise TaskConflict('Service allocation reader requires authorized actual query evidence/resource visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        typed, missing = {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Architect handover assembly substitutes the original source snapshot or organization')

            def read(ref):
                row = reading.resolve(ref)
                if not isinstance(row, self.HISTORY_SCHEMAS[ref.kind]) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
                    raise TaskConflict('Architect handover history lacks an exact typed source')
                typed[ref.key()] = row
                return row

            pending = []
            for inputs, invocation in ((original_input, original_context), (prepared.action_input, context)):
                for ref in (*walk_references(inputs), invocation.function_ref, *invocation.authorization_refs):
                    if ref.kind in self.HISTORY_SCHEMAS:
                        read(ref)
                        pending.append(ref)
            for actual_query in (query, allocation_query):
                for ref in walk_references(actual_query):
                    if ref.kind == 'Evidence':
                        read(ref)
                        pending.append(ref)
            visited = set()
            while pending:
                ref = pending.pop()
                if ref.key() in visited:
                    continue
                visited.add(ref.key())
                if ref.key() not in reading._resolver._objects:
                    missing[ref.key()] = ref.model_dump(mode='json')
                    continue
                row = read(ref)
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in self.HISTORY_SCHEMAS)
            for inputs, invocation in ((original_input, original_context), (prepared.action_input, context)):
                self.VALIDATE_SOURCES(inputs, context=invocation, organization_id=source['organization_id'], sources=typed)
            return ArchitectTransitionConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_context=original_context, original_action_input=deepcopy(snapshot['action_input']),
                action_input=prepared.action_input.model_dump(mode='json'),
                transition_sources=[row.model_dump(mode='json') for row in typed.values()], unavailable_targets=list(missing.values()),
                execution_query=None if query is None else query.model_dump(mode='json'),
                allocation_query=None if allocation_query is None else allocation_query.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            evidence = {Reference.model_validate(row['ref']).key(): row['projection'] for row in reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Architect handover reader changed original snapshot or current assembled sources/input/context')


def build_assembled_architect_transition_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.task_continuation import build_architect_transition_continuation_dispatcher
    return _build_assembled_learning_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader,
        reader_type=ArchitectTransitionReader, dispatcher_factory=build_architect_transition_continuation_dispatcher)
