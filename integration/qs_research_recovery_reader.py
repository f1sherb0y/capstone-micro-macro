"""Read the original QS research task and actual current task authorization."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_research_actions import QSResearchActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_cost_objects import QSCostScopeView, QSQuantityBasisView, QSCostPriceView
from src.actions.contracts.qs_research_objects import (
    QSResearchOptionView, QSResearchAssessmentView, QSResearchCostPlanView, QSResearchProfileView,
    QSResearchExpenseView, QSResearchCostFactView, QSResearchRequestView, QSResearchReferenceView,
    QSResearchGapView, QSResearchResponseView, QSResearchNormalizationView, QSResearchMethodProjection,
)
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_research_conditions import QSResearchConditionReading, _CODE, _BASES
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSResearchCurrentSelection:
    request: RoleContractInvocation


class QSResearchRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSResearchRecoveryBindings:
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
            raise ValueError('QS research recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSResearchRecoveryReader:
    """Assemble a fresh research judgment using the same journal's immutable snapshot.

    Actual history is read under the caller's source/authority/journal guard.
    Native validation authenticates task readiness and complete research/cost/expense history;
    no research processor, calculation, additional spending or service effect executes here.
    """
    ACTION_ID = 'QS-A13'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSResearchActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS research reader requires actual formal assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-research-recovery-reader.v1', 'action_id': self.ACTION_ID, 'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode, 'macro_version': a.macro_version,
            'policy_version': a.policy_version, 'model_version': a.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current, a = self._components(), self.assembler
        if (len(current) != len(self._original_components) or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A13' or a.ACTION_ID != self.ACTION_ID or a.source_mode != 'formal'
                or a._views.source_mode != 'formal' or a._views.organizations is not a.organizations
                or a._views.provider is not a.provider or a._views.macro_version != a.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS research reader changed original source/model/snapshot bindings')

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
            raise TaskConflict('QS research reader replaces original task wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if original_input.task_ref.key() != old_refs[0].key():
            raise TaskConflict('QS research wait differs from its original invocation snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSResearchCurrentSelection):
            raise TaskConflict('QS research reader requires a typed explicit current invocation')
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
            raise TaskConflict('QS research reader substitutes original research task/scope or authorized historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS research assembly changed original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def read_authority(authority_ref, function_ref):
                grant, function = reading.resolve(authority_ref), reading.resolve(function_ref)
                if not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment):
                    raise TaskConflict('QS research history requires actual author/client/QS grants and functions')
                for ref in (*grant.basis_refs, *function.basis_refs):
                    reading.resolve(ref)

            def source_row(row):
                if row.scope != original_input.scope:
                    raise TaskConflict('QS research history changes original comparison coverage')
                for evidence_ref in row.evidence_refs:
                    reading.resolve(evidence_ref)
                if hasattr(row, 'author_authority_ref'):
                    read_authority(row.author_authority_ref, row.author_function_ref)
                return row

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('QS research reader lacks an exact typed original/current source')
                return source_row(row)

            def value_basis(value):
                if value.state == 'known':
                    reading.resolve(value.value.basis_ref)

            def original_method(ref):
                projection = reading.resolve(ref)
                if not isinstance(projection, QSResearchMethodProjection) or projection.ref != ref:
                    raise TaskConflict('QS research history requires its exact original A04/A13 saved calculation')
                row = source_row(projection.cost or projection.comparison)
                if projection.cost is not None:
                    read(row.cost_scope_ref, QSCostScopeView)
                    read(row.option_ref, QSResearchOptionView)
                    read(row.comparison_basis_ref, type(basis))
                    for quantity_ref in row.quantity_basis_refs:
                        value_basis(read(quantity_ref, QSQuantityBasisView).quantity)
                    for price_ref in row.price_refs:
                        value_basis(read(price_ref, QSCostPriceView).unit_rate)
                    for line in row.lines:
                        for evidence_ref in line.basis_refs:
                            reading.resolve(evidence_ref)
                        value_basis(line.quantity); value_basis(line.amount)
                    value_basis(row.known_subtotal)
                    if row.complete_total is not None:
                        reading.resolve(row.complete_total.basis_ref)
                    # A04 task/schedule refs retain their saved identities.
                    # A13 reads actual quantities/prices through its closed
                    # registry without fabricating those foreign projections.
                else:
                    if (row.task_ref != task.ref or profile is None or row.profile_ref != profile.ref
                            or row.comparison_basis_ref != basis.ref):
                        raise TaskConflict('QS research calculation substitutes its original task/profile/comparison')
                    for plan_ref in row.plan_refs:
                        read(plan_ref, QSResearchCostPlanView)
                    for basis_ref in row.normalization_basis_refs:
                        normalization(basis_ref)
                    for value in row.normalized_costs:
                        read(value.plan_ref, QSResearchCostPlanView)
                        reading.resolve(value.amount.basis_ref)
                    for group in row.ranked_groups:
                        for option_ref in group:
                            read(option_ref, QSResearchOptionView)
                return projection

            def normalization(ref):
                row = read(ref, QSResearchNormalizationView)
                if row.comparison_basis_ref != basis.ref:
                    raise TaskConflict('QS research adjustment substitutes original comparison basis')
                read(row.plan_ref, QSResearchCostPlanView)
                for evidence_ref in [row.original_amount.basis_ref, row.fx_basis_ref,
                        *[adjustment.amount.basis_ref for adjustment in row.adjustments]]:
                    reading.resolve(evidence_ref)
                return row

            for action_input in (original_input, prepared.action_input):
                bases = {field: read(getattr(action_input, field), schema) for field, _, schema in _BASES}
                brief, task, delegation, basis, limit = (bases[field] for field, _, _ in _BASES)
                profile = None
                if (task.brief_ref != brief.ref or task.comparison_basis_ref != basis.ref or task.expenditure_limit_ref != limit.ref
                        or task.organization_id != source['organization_id'] or limit.task_ref != task.ref
                        or limit.organization_id != source['organization_id'] or delegation.brief_ref != brief.ref
                        or delegation.task_ref != task.ref or delegation.delegate_organization_id != source['organization_id']):
                    raise TaskConflict('QS research reader substitutes original task, client delegation, comparison or expenditure limit')
                read_authority(task.authority_ref, task.function_ref)
                read_authority(limit.authority_ref, task.function_ref)
                read_authority(delegation.client_authority_ref, delegation.client_function_ref)
                for field, schema in (('option_refs', QSResearchOptionView), ('assessment_refs', QSResearchAssessmentView),
                        ('cost_plan_refs', QSResearchCostPlanView)):
                    refs = {ref.key(): ref for ref in [*getattr(task, field), *getattr(action_input, field)]}
                    for ref in refs.values():
                        row = read(ref, schema)
                        if row.brief_ref != brief.ref:
                            raise TaskConflict('QS research option/assessment/plan borrows another original brief')
                        if isinstance(row, QSResearchAssessmentView):
                            read(row.option_ref, QSResearchOptionView)
                        elif isinstance(row, QSResearchCostPlanView):
                            read(row.draft.option_ref, QSResearchOptionView)
                            read(row.draft.cost_scope_ref, QSCostScopeView)
                            read(row.draft.comparison_basis_ref, type(basis))
                            for line in row.draft.lines:
                                for evidence_ref in line.basis_refs:
                                    reading.resolve(evidence_ref)
                                value_basis(line.quantity); value_basis(line.amount)
                                if line.price_ref is not None:
                                    value_basis(read(line.price_ref, QSCostPriceView).unit_rate)
                                if line.calculation_ref is not None:
                                    original_method(line.calculation_ref)
                            if row.draft.calculation_ref is not None:
                                saved = original_method(row.draft.calculation_ref)
                                cost = saved.cost
                                if (cost is None or cost.brief_ref != brief.ref or cost.option_ref != row.draft.option_ref
                                        or cost.cost_scope_ref != row.draft.cost_scope_ref
                                        or cost.comparison_basis_ref != row.draft.comparison_basis_ref
                                        or cost.quantity_schedule_ref != row.draft.quantity_schedule_ref):
                                    raise TaskConflict('QS research plan replaces its original A04 calculation inputs')
                            value_basis(row.draft.known_subtotal); value_basis(row.uncertainty)
                            if row.draft.complete_total is not None:
                                reading.resolve(row.draft.complete_total.basis_ref)
                            for gap in row.draft.missing_items:
                                for evidence_ref in gap.evidence_refs:
                                    reading.resolve(evidence_ref)
                for expense_ref in limit.expense_refs:
                    expense = read(expense_ref, QSResearchExpenseView)
                    fact = read(expense.cost_fact_ref, QSResearchCostFactView)
                    if (expense.task_ref != task.ref or fact.task_ref != task.ref or fact.organization_id != source['organization_id']
                            or expense.status != fact.status or expense.amount != fact.amount or expense.effort != fact.effort):
                        raise TaskConflict('QS research expenditure substitutes original task, cost fact, amount or effort')
                    reading.resolve(expense.amount.basis_ref); reading.resolve(expense.effort.basis_ref)
                reading.resolve(limit.budget_cap.basis_ref); reading.resolve(limit.effort_cap.basis_ref)
                for question_ref in task.question_refs:
                    question = read(question_ref, QSResearchGapView)
                    response = read(question.response_requirement_ref, QSResearchResponseView)
                    if question.task_ref != task.ref or question.brief_ref != brief.ref or response.task_ref != task.ref:
                        raise TaskConflict('QS research question/response substitutes original task or brief')
                if task.request_profile_ref is not None:
                    request = read(task.request_profile_ref, QSResearchRequestView)
                    if request.task_ref != task.ref:
                        raise TaskConflict('QS research request borrows another original task')
                    for ref in request.input_refs:
                        read(ref, QSResearchReferenceView)
                    for ref in [*request.output_requirement_refs, *request.dependency_refs,
                            *([request.work_profile_ref] if request.work_profile_ref is not None else [])]:
                        if read(ref, QSResearchReferenceView).task_ref != task.ref:
                            raise TaskConflict('QS research request work/requirement/dependency substitutes original task')
                    for ref in request.authority_basis_refs:
                        read(ref, type(delegation))
                    value_basis(request.effort_estimate); value_basis(request.incremental_budget)
                if basis.comparison_profile_ref is not None:
                    profile = read(basis.comparison_profile_ref, QSResearchProfileView)
                    if profile.task_ref != task.ref or profile.comparison_basis_ref != basis.ref:
                        raise TaskConflict('QS research profile replaces original task or comparison basis')
                    for ref in profile.selected_plan_refs:
                        read(ref, QSResearchCostPlanView)
                    for ref in profile.normalization_basis_refs:
                        normalization(ref)
                    for criterion in profile.criteria:
                        reading.resolve(criterion.basis_ref)
                    for ref in (profile.normalization_result_ref, profile.ranking_result_ref):
                        # Declarations are not saved executions. Native history
                        # validation must authenticate omitted/future targets;
                        # their absence supplies no successful calculation.
                        if ref is not None and ref.key() in reading._resolver._objects:
                            original_method(ref)
            return QSResearchConditionReading(prepared.context, reading, deepcopy(snapshot['action_input']),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck(); self._check()
            current = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot or any(current.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS research reader changed original snapshot or assembled context/input/source reading')


def build_assembled_qs_research_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one actual source/authority/inbox/journal guard across QS recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_research_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS research recovery requires actual same-run guard and validators')
    reader = QSResearchRecoveryReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
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
            raise TaskConflict('QS research successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_qs_research_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    journal, registry, final_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not journal
                or journal.store is not store or journal.registry is not registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not final_revalidate
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS research recovery changed original journal/recipient/source callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS research recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role='QS')
