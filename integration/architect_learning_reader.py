"""Read actual private A12 histories for guarded original learning recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.architect_learning_actions import ArchitectLearningActionAssembler, validate_architect_learning_sources
from integration.architect_submission_receipt_reader import ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.architect_learning_objects import architect_learning_types
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.contractor_objects import QualificationView
from src.coordination.architect_learning_conditions import ArchitectLearningConditionReading, _CODE, _CODES, _CAPACITY_CODE
from src.coordination.architect_learning_execution_query import (
    EXECUTION_CODE, ArchitectLearningExecutionQueryRecord,
    architect_original_learning_execution_profile, check_learning_execution,
)
from src.coordination.architect_learning_applied_feedback import APPLIED_CODE, JUDGMENT_CODE, ArchitectAppliedFeedbackQueryRecord
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class ArchitectLearningCurrentSelection:
    request: RoleContractInvocation
    execution_query: ArchitectLearningExecutionQueryRecord | None = None
    applied_feedback_query: ArchitectAppliedFeedbackQueryRecord | None = None


class ArchitectLearningRecoverySettings(ArchitectSubmissionRecoverySettings):
    """Explicit original private learning source and policy versions."""
    terminal_execution_enabled: bool = False
    terminal_applied_feedback_enabled: bool = False


@dataclass(frozen=True)
class ArchitectLearningRecoveryBindings(ArchitectSubmissionRecoveryBindings):
    """Actual private source selector, guard and independent native validators."""


_HISTORY_SCHEMAS = {**architect_learning_types(), 'Authorization': Authorization,
    'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord, 'Qualification': QualificationView}


class ArchitectLearningReader:
    """Assemble current sources and retain original snapshots without running A12."""
    ACTION_ID = 'ARCHITECT-A12'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    READER_SCHEMA = 'architect-learning-reader.v1'
    ROLE = 'Architect'
    ASSEMBLER_TYPE = ArchitectLearningActionAssembler
    SELECTION_TYPE = ArchitectLearningCurrentSelection
    HISTORY_SCHEMAS = _HISTORY_SCHEMAS
    VALIDATE_SOURCES = staticmethod(validate_architect_learning_sources)
    INPUT_ANCHORS = ('strategy_ref', 'capability_ref')
    EXECUTION_KIND = 'ArchitectLearningExecution'
    EXECUTION_QUERY_TYPE = ArchitectLearningExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(architect_original_learning_execution_profile)
    EXECUTION_CHECKER = staticmethod(check_learning_execution)
    APPLIED_STATE_KIND = 'ArchitectLearningState'
    APPLIED_QUERY_TYPE = ArchitectAppliedFeedbackQueryRecord
    QUALIFICATION_CODE = None
    QUALIFICATION_QUERY_TYPE = None

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.ACTION_ID != self.ACTION_ID
                or assembler.source_mode != 'formal' or not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store.run_id != assembler.organizations.run_id or not callable(select_current)):
            raise ValueError('Architect learning reader requires formal A12 assembler, original snapshots and actual selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_route = (self.ROLE, self.ASSEMBLER_TYPE, self.SELECTION_TYPE, tuple(sorted(self.HISTORY_SCHEMAS.items())),
            self.VALIDATE_SOURCES, self.INPUT_ANCHORS, self.EXECUTION_KIND, self.EXECUTION_QUERY_TYPE,
            self.APPLIED_STATE_KIND, self.APPLIED_QUERY_TYPE, self.QUALIFICATION_CODE, self.QUALIFICATION_QUERY_TYPE)
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            assembler._views.schemas, assembler.methods, assembler.audit_sink, self.snapshots, self.snapshots.store,
            self.select_current, self.EXECUTION_PROFILE_FACTORY, self.EXECUTION_CHECKER,
            *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': self.READER_SCHEMA, 'action_id': self.ACTION_ID,
            'condition_code': self.CONDITION_CODE, 'condition_codes': list(self.CONDITION_CODES),
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'policy_version': self.assembler.policy_version,
            'model_version': self.assembler.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'execution_condition': module_factory_descriptor(self.EXECUTION_PROFILE_FACTORY, 'execution_condition'),
            'execution_checker': module_factory_descriptor(self.EXECUTION_CHECKER, 'execution_checker'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or (self.ROLE, self.ASSEMBLER_TYPE, self.SELECTION_TYPE, tuple(sorted(self.HISTORY_SCHEMAS.items())),
                    self.VALIDATE_SOURCES, self.INPUT_ANCHORS, self.EXECUTION_KIND, self.EXECUTION_QUERY_TYPE,
                    self.APPLIED_STATE_KIND, self.APPLIED_QUERY_TYPE, self.QUALIFICATION_CODE, self.QUALIFICATION_QUERY_TYPE) != self._original_route
                or not isinstance(self.assembler, self.ASSEMBLER_TYPE)
                or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal'
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.macro_version != self.assembler.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('Architect learning reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check, *, execution_terminal=False, feedback_terminal=False, qualification_terminal=False):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        execution_wait = check.condition.condition_code == EXECUTION_CODE
        capacity_wait = check.condition.condition_code == _CAPACITY_CODE
        applied_wait = check.condition.condition_code == APPLIED_CODE
        judgment_wait = check.condition.condition_code == JUDGMENT_CODE
        qualification_wait = self.QUALIFICATION_CODE is not None and check.condition.condition_code == self.QUALIFICATION_CODE
        terminal = execution_terminal or feedback_terminal or qualification_terminal
        if sum((execution_terminal, feedback_terminal, qualification_terminal)) > 1:
            raise TaskConflict('Architect learning reader requires one explicit terminal route')
        if (source['action_id'] != self.ACTION_ID or source['role'] != self.ROLE or source['purpose'] != 'action'
                or check.condition.condition_code not in self.CONDITION_CODES or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != ((self.EXECUTION_KIND,) if execution_wait else
                    ('Authority',) if capacity_wait else (self.APPLIED_STATE_KIND,) if applied_wait or qualification_wait else
                    ('LearningProfile',) if judgment_wait else ('Dependency',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Architect learning reader replaces original training wait or private firm')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        original_context = ActionContext.model_validate(snapshot['context']).model_copy(deep=True)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if (task_digest(snapshot['context']) != source['context_sha256']
                or task_digest(snapshot['action_input']) != source['input_sha256']):
            raise TaskConflict('Architect learning reader changes the original invocation digest')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, self.SELECTION_TYPE):
            raise TaskConflict('Architect learning recovery requires a typed independently authorized current invocation')
        query = None if getattr(selected, 'execution_query', None) is None else self.EXECUTION_QUERY_TYPE.model_validate(
            selected.execution_query).model_copy(deep=True)
        if query is not None and not execution_wait or execution_terminal and not execution_wait:
            raise TaskConflict('Learning execution query/reconciliation belongs only to original execution waits')
        applied_query = None if getattr(selected, 'applied_feedback_query', None) is None else self.APPLIED_QUERY_TYPE.model_validate(
            selected.applied_feedback_query).model_copy(deep=True)
        if applied_query is not None and not applied_wait or feedback_terminal and not applied_wait:
            raise TaskConflict('Applied-feedback query/reconciliation belongs only to original applied-feedback waits')
        qualification_query = getattr(selected, 'qualification_application_query', None)
        if qualification_query is not None and not qualification_wait or qualification_terminal and not qualification_wait:
            raise TaskConflict('Qualification query/reconciliation belongs only to original qualification event waits')
        if qualification_query is not None:
            qualification_query = self.QUALIFICATION_QUERY_TYPE.model_validate(qualification_query).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time
                or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
                or terminal and current_input != original_input
                or context.scope != original_context.scope or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field in self.INPUT_ANCHORS)
                or (original_input.learning_profile_ref is None) != (current_input.learning_profile_ref is None)
                or original_input.learning_profile_ref is not None
                    and original_input.learning_profile_ref.key()[:2] != current_input.learning_profile_ref.key()[:2]
                or not execution_wait and not qualification_wait and original_input.learning_profile_ref is None
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input),
                    *((ref for ref in walk_references(query) if ref.kind == 'Evidence') if query is not None else ()))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Architect learning reader replaces original scope/profile or authorized historical/current visibility')
        if applied_query is not None and not {ref.key() for ref in walk_references(applied_query)} <= {ref.key() for ref in context.visible_refs}:
            raise TaskConflict('Applied-feedback reader requires explicitly authorized actual query sources')
        if qualification_query is not None and not {ref.key() for ref in walk_references(qualification_query)} <= {ref.key() for ref in context.visible_refs}:
            raise TaskConflict('Qualification reader requires explicitly authorized actual issuer query sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Architect learning assembly changes original source snapshot or private recipient')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Architect learning history lacks an exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            if query is not None:
                for ref in walk_references(query):
                    if ref.kind == 'Evidence':
                        read(ref, EvidenceRecord)
            if applied_query is not None:
                for ref in walk_references(applied_query):
                    if ref.kind in self.HISTORY_SCHEMAS:
                        read(ref, self.HISTORY_SCHEMAS[ref.kind])
                        pending.append(ref)
            if qualification_query is not None:
                for ref in walk_references(qualification_query):
                    if ref.kind in self.HISTORY_SCHEMAS:
                        read(ref, self.HISTORY_SCHEMAS[ref.kind])
                        pending.append(ref)
            for action_input, invocation in ((original_input, original_context), (prepared.action_input, context)):
                for ref in walk_references(action_input):
                    if ref.kind in self.HISTORY_SCHEMAS:
                        read(ref, self.HISTORY_SCHEMAS[ref.kind])
                        pending.append(ref)
                function = read(invocation.function_ref, RoleAssignment)
                if function.role != self.ROLE:
                    raise TaskConflict('Architect learning history borrows another firm or function')
                pending.append(invocation.function_ref)
                for ref in invocation.authorization_refs:
                    grant = read(ref, Authorization)
                    if (grant.organization_id != source['organization_id'] or grant.actor_id != invocation.actor_id
                            or grant.function_ref != invocation.function_ref):
                        raise TaskConflict('Architect learning history borrows another firm/actor/function authorization')
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
                row = read(ref, self.HISTORY_SCHEMAS[ref.kind])
                if hasattr(row, 'author_authority_ref'):
                    grant = read(row.author_authority_ref, Authorization)
                    read(row.author_function_ref, RoleAssignment)
                    if (grant.actor_id != row.author_actor_id or grant.organization_id != row.author_organization_id
                            or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids):
                        raise TaskConflict('Architect learning history substitutes actual source author/action authority')
                    pending.extend((row.author_authority_ref, row.author_function_ref))
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in self.HISTORY_SCHEMAS)
            for action_input, invocation in ((original_input, original_context), (prepared.action_input, context)):
                self.VALIDATE_SOURCES(action_input, context=invocation,
                    organization_id=source['organization_id'], sources=typed_sources)
            return ArchitectLearningConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=deepcopy(snapshot['action_input']), action_input=prepared.action_input.model_dump(mode='json'),
                original_context=original_context, learning_sources=deepcopy(list(sources.values())),
                unavailable_targets=deepcopy(list(missing.values())),
                execution_query=None if query is None else query.model_dump(mode='json'),
                applied_feedback_query=None if applied_query is None else applied_query.model_dump(mode='json'),
                qualification_application_query=None if qualification_query is None else qualification_query.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection'] for row in reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Architect learning reader changes original snapshot or current assembled sources/input/context')


def build_assembled_architect_learning_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    """Hold the actual private source/authority/journal guard through recovery."""
    from integration.task_continuation import build_architect_learning_continuation_dispatcher

    return _build_assembled_learning_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader,
        reader_type=ArchitectLearningReader, dispatcher_factory=build_architect_learning_continuation_dispatcher)


def _build_assembled_learning_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader, reader_type, dispatcher_factory):
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Architect learning recovery requires actual same-run guard and native/successor validators')
    if reader is None:
        reader = reader_type(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if (type(reader) is not reader_type or reader.assembler is not assembler
            or reader.snapshots.store is not store or reader.select_current is not select_current):
        raise ValueError('Architect learning recovery requires its original declared reader and snapshot journal')
    reader._check()
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
            raise TaskConflict('Architect learning successor substitutes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = dispatcher_factory(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_revalidate = dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({reader.ACTION_ID})):
            raise TaskConflict('Architect learning recovery changed original snapshot/journal/recipient/callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Architect learning recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id=reader.ACTION_ID, role=reader.ROLE)
