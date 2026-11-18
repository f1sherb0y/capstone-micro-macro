"""Read the original QS cost task and actual current task authorization."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_cost_actions import QSCostActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_cost_objects import (
    QSCostOptionView, QSCostComponentView, QSQuantityBasisView,
    QSQuantityScheduleView, QSCostPriceView, QSCostCalculationView, QSCostQuestionView,
    QSCostResponseRequirementView, QSCostMethodView,
)
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_cost_conditions import QSCostConditionReading, _CODE, _BASES
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSCostCurrentSelection:
    request: RoleContractInvocation


class QSCostRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSCostRecoveryBindings:
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
            raise ValueError('QS cost recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSCostReader:
    """Assemble a fresh costing using the same journal's immutable snapshot.

    Actual history is read under the caller's source/authority/journal guard.
    Native validation authenticates task authorization and complete cost history;
    no costing processor, calculation, budget or expense effect executes here.
    """
    ACTION_ID = 'QS-A04'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSCostActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS cost reader requires actual formal assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-cost-reader.v1', 'action_id': self.ACTION_ID, 'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode, 'macro_version': a.macro_version,
            'policy_version': a.policy_version, 'model_version': a.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current, a = self._components(), self.assembler
        if (len(current) != len(self._original_components) or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A04' or a.ACTION_ID != self.ACTION_ID or a.source_mode != 'formal'
                or a._views.source_mode != 'formal' or a._views.organizations is not a.organizations
                or a._views.provider is not a.provider or a._views.macro_version != a.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS cost reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'Task'):
            raise TaskConflict('QS cost reader replaces original task wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if original_input.task_ref.key() != old_refs[0].key():
            raise TaskConflict('QS cost wait differs from its original invocation snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSCostCurrentSelection):
            raise TaskConflict('QS cost reader requires a typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope'] or current_input.scope != original_input.scope
                or any(getattr(current_input, field).key()[:2] != getattr(original_input, field).key()[:2]
                    for field, _, _ in _BASES)
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS cost reader substitutes original costing task/scope or authorized historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS cost assembly changed original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != original_input.scope:
                    raise TaskConflict('QS cost reader lacks an exact scoped original/current source')
                for evidence_ref in row.evidence_refs:
                    reading.resolve(evidence_ref)
                if isinstance(row, (QSCostOptionView, QSQuantityBasisView, QSCostCalculationView)):
                    read_authority(row.author_authority_ref, row.author_function_ref)
                return row

            def read_authority(authority_ref, function_ref):
                grant, function = reading.resolve(authority_ref), reading.resolve(function_ref)
                if not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment):
                    raise TaskConflict('QS cost history requires actual author/task grants and functions')
                for ref in (*grant.basis_refs, *function.basis_refs):
                    reading.resolve(ref)

            for action_input in (original_input, prepared.action_input):
                bases = {field: read(getattr(action_input, field), schema) for field, _, schema in _BASES}
                brief, option, task, cost_scope, comparison = (bases[field] for field, _, _ in _BASES)
                if (option.brief_ref != brief.ref or task.brief_ref != brief.ref or task.option_ref != option.ref
                        or cost_scope.option_ref != option.ref or task.cost_scope_ref != cost_scope.ref
                        or task.comparison_basis_ref != comparison.ref or task.organization_id != source['organization_id']):
                    raise TaskConflict('QS cost reader changes original task, brief, design, coverage or comparison association')
                read_authority(task.authority_ref, task.function_ref)

                def schedule(ref):
                    row = read(ref, QSQuantityScheduleView)
                    if row.option_ref != option.ref:
                        raise TaskConflict('QS cost history borrows another original design quantity schedule')
                    for quantity_ref in row.quantity_basis_refs:
                        quantity(quantity_ref, with_schedule=False)
                    return row

                def quantity(ref, *, with_schedule=True):
                    row = read(ref, QSQuantityBasisView)
                    if row.option_ref != option.ref:
                        raise TaskConflict('QS cost history borrows another original design quantity')
                    read(row.cost_component_ref, QSCostComponentView)
                    if row.quantity.state == 'known':
                        reading.resolve(row.quantity.value.basis_ref)
                    if with_schedule and row.quantity_schedule_ref is not None:
                        declared = schedule(row.quantity_schedule_ref)
                        if row.ref not in declared.quantity_basis_refs:
                            raise TaskConflict('QS cost quantity is absent from its declared original schedule')
                    if row.proxy_method_ref is not None:
                        profile = reading.resolve(row.proxy_method_ref)
                        if not isinstance(profile, QSCostMethodView) or profile.ref != row.proxy_method_ref:
                            raise TaskConflict('QS cost proxy quantity requires its actual declared method profile')
                        for evidence_ref in profile.evidence_refs:
                            reading.resolve(evidence_ref)
                    return row

                def price(ref):
                    row = read(ref, QSCostPriceView)
                    read(row.cost_component_ref, QSCostComponentView)
                    if row.unit_rate.state == 'known':
                        reading.resolve(row.unit_rate.value.basis_ref)
                    return row

                # Read both declared and selected histories. Original waiting
                # can precede the processor's quantity/price completeness check.
                for ref in action_input.quantity_basis_refs:
                    quantity(ref)
                for ref in action_input.price_refs:
                    price(ref)
                for item in cost_scope.items:
                    read(item.cost_component_ref, QSCostComponentView)
                    if item.quantity_basis_ref is not None:
                        row = quantity(item.quantity_basis_ref)
                        if row.line_key != item.line_key or row.cost_component_ref != item.cost_component_ref:
                            raise TaskConflict('QS cost history replaces original line/component quantity coverage')
                    if item.price_ref is not None:
                        price(item.price_ref)
                    for ref, issue in ((item.quantity_question_ref, 'quantity'), (item.price_question_ref, 'price'),
                            (item.coverage_question_ref, 'coverage')):
                        question = read(ref, QSCostQuestionView)
                        response = read(question.response_requirement_ref, QSCostResponseRequirementView)
                        if (question.task_ref != task.ref or question.line_key != item.line_key or question.issue != issue
                                or response.task_ref != task.ref):
                            raise TaskConflict('QS cost history substitutes original task, question line or response')
                for ref in action_input.method_result_refs:
                    saved = read(ref, QSCostCalculationView)
                    if any(getattr(saved, field) != getattr(action_input, field) for field, _, _ in _BASES):
                        raise TaskConflict('QS cost saved calculation replaces its exact original task/input versions')
                    for quantity_ref in saved.quantity_basis_refs:
                        quantity(quantity_ref)
                    for price_ref in saved.price_refs:
                        price(price_ref)
                    if saved.quantity_schedule_ref is not None:
                        schedule(saved.quantity_schedule_ref)
                    for line in saved.lines:
                        for evidence_ref in line.basis_refs:
                            reading.resolve(evidence_ref)
                        for value in (line.quantity, line.amount):
                            if value.state == 'known':
                                reading.resolve(value.value.basis_ref)
                    if saved.known_subtotal.state == 'known':
                        reading.resolve(saved.known_subtotal.value.basis_ref)
                    if saved.complete_total is not None:
                        reading.resolve(saved.complete_total.basis_ref)
            return QSCostConditionReading(prepared.context, reading, deepcopy(snapshot['action_input']),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck(); self._check()
            current = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot or any(current.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS cost reader changed original snapshot or assembled context/input/source reading')


def build_assembled_qs_cost_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one actual source/authority/inbox/journal guard across QS recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_cost_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS cost recovery requires actual same-run guard and validators')
    reader = QSCostReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
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
            raise TaskConflict('QS cost successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_qs_cost_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    journal, registry, final_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not journal
                or journal.store is not store or journal.registry is not registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not final_revalidate
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS cost recovery changed original journal/recipient/source callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS cost recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role='QS')
