"""Read original QS-A12 cost-error, execution, training and feedback waits with private history."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
from pydantic import model_serializer

from integration.module_host import module_factory_descriptor
from integration.qs_learning_actions import QSLearningActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId, walk_references
from src.coordination.qs_learning_execution_query import EXECUTION_CODE, QSLearningExecutionQueryRecord
from src.coordination.qs_learning_applied_feedback import QSAppliedFeedbackQueryRecord
from src.actions.contracts.qs_learning_objects import (
    QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView, QSLearningExecutionView,
    QSHistoricalCostPlanView, QSFrozenForecastView, QSForecastInformationView,
    QSReceivedOutcomeView, QSOutcomeAccessView, QSComparisonResultView, QSLearningAssessmentView,
    QSExperienceDimensionView,
)
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningCapabilityView, ArchitectLearningFeedbackView, ArchitectLearningProfileView,
    ArchitectLearningValueView, ArchitectLearningRuleView,
)
from src.actions.roles.qs_change import content_digest
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_learning_conditions import (
    QSLearningConditionReading, _CODE,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSLearningCurrentSelection:
    request: RoleContractInvocation
    execution_query: QSLearningExecutionQueryRecord | None = None
    applied_feedback_query: QSAppliedFeedbackQueryRecord | None = None


class QSLearningRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_execution_enabled: bool = False
    terminal_applied_feedback_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_execution_enabled:
            result.pop('terminal_execution_enabled', None)
        if not self.terminal_applied_feedback_enabled:
            result.pop('terminal_applied_feedback_enabled', None)
        return result


@dataclass(frozen=True)
class QSLearningRecoveryBindings:
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
            raise ValueError('QS learning recovery requires actual source selection and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSLearningReader:
    """Assemble current A12 sources while retaining the immutable original input."""
    ACTION_ID = 'QS-A12'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSLearningActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS learning reader requires actual formal assembler, snapshot store and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        from integration.qs_learning_execution_reader import QSLearningExecutionReader
        self._execution_reader = QSLearningExecutionReader(assembler=assembler, snapshots=snapshots,
            select_current=select_current)
        self._original_components = self._components(); self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, self._execution_reader,
            *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-learning-reader.v1', 'action_id': self.ACTION_ID,
            'condition_code': _CODE,
            'execution_reader': self._execution_reader.configuration_evidence(),
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode,
            'macro_version': a.macro_version, 'policy_version': a.policy_version, 'model_version': a.model_version,
            'snapshot_schema': self.snapshots.SCHEMA, 'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        self._execution_reader._check()
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A12' or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal' or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not self.assembler.provider or self.assembler._views.macro_version != self.assembler.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS learning reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check(); return deepcopy(self._declared)

    def __call__(self, check, *, execution_terminal=False, feedback_terminal=False):
        self._check()
        if check.condition.condition_code in self._execution_reader.CONDITION_CODES:
            try:
                return self._execution_reader(check, execution_terminal=execution_terminal, feedback_terminal=feedback_terminal)
            finally:
                self._check()
        if execution_terminal or feedback_terminal:
            raise TaskConflict('QS terminal archive belongs only to original execution or applied-feedback query waits')
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(waited) != 1 or waited[0].kind != 'QSLearningState'):
            raise TaskConflict('QS learning reader replaces original applied-pair wait or recipient')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, QSLearningCurrentSelection) or selected.execution_query is not None
                or selected.applied_feedback_query is not None):
            raise TaskConflict('QS learning reader requires typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or current_input.strategy_ref.key()[:2] != original_input.strategy_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS learning reader changes original scope/strategy or current visible sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading = prepared.reading
        baseline = deepcopy(reading.evidence())
        sources, missing = {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS learning assembly changes original source snapshot or recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def authority(authority_ref, function_ref):
                grant, assignment = reading.resolve(authority_ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or grant.ref != authority_ref
                        or not isinstance(assignment, RoleAssignment) or assignment.function_ref != function_ref):
                    raise TaskConflict('QS learning history lacks exact original author authority/function')
                for ref in (*grant.basis_refs, *assignment.basis_refs):
                    reading.resolve(ref)
                sources[grant.ref.key()] = grant.model_dump(mode='json')
                sources[assignment.function_ref.key()] = assignment.model_dump(mode='json')

            def read(ref, schema, *, own=False):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
                    raise TaskConflict('QS learning reader lacks an exact original/current source')
                if own and getattr(row, 'organization_id', source['organization_id']) != source['organization_id']:
                    raise TaskConflict('QS learning recovery borrows another private source')
                for evidence_ref in walk_references(row):
                    if evidence_ref.kind == 'Evidence':
                        reading.resolve(evidence_ref)
                if hasattr(row, 'author_authority_ref'):
                    authority(row.author_authority_ref, row.author_function_ref)
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            def supplied(ref):
                if ref.key() in reading._resolver._objects:
                    return True
                missing[ref.key()] = ref.model_dump(mode='json')
                return False

            def feedback(ref):
                row = read(ref, ArchitectLearningFeedbackView)
                if row.recipient_organization_id != source['organization_id'] or row.event_sha256 != content_digest(row.event):
                    raise TaskConflict('QS learning feedback changes its actual event content or private recipient')
                return row

            for action_input in (original_input, prepared.action_input):
                strategy = read(action_input.strategy_ref, QSLearningStrategyView, own=True)
                state = read(strategy.learning_state_ref, QSLearningStateView, own=True)
                decision = read(strategy.decision_profile_ref, QSLearningDecisionView, own=True)
                if state.strategy_ref != strategy.ref or decision.strategy_ref != strategy.ref:
                    raise TaskConflict('QS learning sources borrow another original private strategy')
                authority(decision.authority_ref, decision.function_ref)
                read(state.capability_ref, ArchitectLearningCapabilityView, own=True)
                for ref in state.execution_refs:
                    execution = read(ref, QSLearningExecutionView, own=True)
                    original_decision = read(execution.decision_ref, QSLearningDecisionView, own=True)
                    if (execution.run_id != source['run_id'] or execution.strategy_ref.key()[:2] != strategy.ref.key()[:2]
                            or execution.business_key != original_decision.business_key
                            or execution.decision_sha256 != content_digest(original_decision)):
                        raise TaskConflict('QS learning execution changes original run/strategy/decision content')
                for ref in set(action_input.feedback_refs) | set(state.received_feedback_refs) | set(state.applied_feedback_refs):
                    feedback(ref)
                for ref in set(action_input.forecast_refs) | set(state.forecast_refs):
                    forecast = read(ref, QSHistoricalCostPlanView, own=True)
                    frozen = read(forecast.immutable_source_ref, QSFrozenForecastView, own=True)
                    if (forecast.immutable_source_sha256 != content_digest(frozen) or frozen.forecast_ref != forecast.ref
                            or any(getattr(frozen, name) != getattr(forecast, name) for name in (
                                'organization_id','forecast_key','information_refs','comparison_basis','predicted_total','frozen_at'))
                            or frozen.available_at.clock_ref != forecast.frozen_at.clock_ref
                            or frozen.available_at.offset > forecast.frozen_at.offset):
                        raise TaskConflict('QS learning recovery rewrites its immutable original prediction')
                    for information_ref in forecast.information_refs:
                        information = read(information_ref, QSForecastInformationView, own=True)
                        original = read(information.original_source_ref, StrictRecord)
                        if (information.forecast_ref != forecast.ref or information.original_source_sha256 != content_digest(original)
                                or information.received_at.clock_ref != forecast.frozen_at.clock_ref
                                or information.available_at.clock_ref != forecast.frozen_at.clock_ref
                                or not information.available_at.offset <= information.received_at.offset <= forecast.frozen_at.offset
                                or hasattr(original, 'available_at') and (original.available_at.clock_ref != information.received_at.clock_ref
                                    or original.available_at.offset > information.received_at.offset)):
                            raise TaskConflict('QS forecast information changes its original source or prediction')
                for ref in set(action_input.outcome_refs) | set(state.outcome_refs):
                    outcome = read(ref, QSReceivedOutcomeView)
                    access = read(outcome.access_basis_ref, QSOutcomeAccessView)
                    if (outcome.recipient_organization_id != source['organization_id']
                            or outcome.author_organization_id != outcome.provider_organization_id
                            or access.outcome_ref != outcome.ref or access.provider_organization_id != outcome.provider_organization_id
                            or access.author_organization_id != outcome.provider_organization_id
                            or access.recipient_organization_id != source['organization_id']):
                        raise TaskConflict('QS outcome/access history borrows another original provider, recipient or permission')
                if action_input.comparability_result_ref is not None:
                    read(action_input.comparability_result_ref, QSComparisonResultView, own=True)
                if decision.error_result_ref is not None and supplied(decision.error_result_ref):
                    read(decision.error_result_ref, QSComparisonResultView, own=True)
                if action_input.learning_profile_ref is not None:
                    profile = read(action_input.learning_profile_ref, ArchitectLearningProfileView, own=True)
                    if profile.strategy_ref != strategy.ref or state.learning_profile_ref != profile.ref:
                        raise TaskConflict('QS learning recovery substitutes its original selected rules/profile')
                    for ref in profile.dimension_refs:
                        dimension = read(ref, QSExperienceDimensionView, own=True)
                        if dimension.learning_profile_ref != profile.ref:
                            raise TaskConflict('QS judgment dimension changes its original learning profile')
                        for value_ref in dimension.value_refs:
                            value = read(value_ref, ArchitectLearningValueView, own=True)
                            if value.dimension_ref != dimension.ref:
                                raise TaskConflict('QS judgment value borrows another original dimension')
                    for ref in profile.rule_refs:
                        rule = read(ref, ArchitectLearningRuleView, own=True)
                        if rule.learning_profile_ref != profile.ref or rule.rule.rule_ref != rule.ref:
                            raise TaskConflict('QS learning rule substitutes its original profile or finite rule')
                    if decision.assessment_ref is not None and supplied(decision.assessment_ref):
                        assessment = read(decision.assessment_ref, QSLearningAssessmentView, own=True)
                        if assessment.strategy_ref != strategy.ref or assessment.learning_profile_ref != profile.ref:
                            raise TaskConflict('QS learning assessment borrows another original strategy/profile')
            original_strategy = read(original_input.strategy_ref, QSLearningStrategyView, own=True)
            if original_strategy.learning_state_ref != waited[0]:
                raise TaskConflict('QS applied-error wait differs from its original private learning state')
            return QSLearningConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'), action_input=prepared.action_input.model_dump(mode='json'),
                learning_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS learning reader changed original snapshot or assembled sources/context/input')


def build_assembled_qs_learning_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_learning_continuation_dispatcher
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS learning recovery requires actual same-run guards and validators')
    reader = reader or QSLearningReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if (not isinstance(reader, QSLearningReader) or reader.assembler is not assembler
            or reader.snapshots.store is not store or reader.select_current is not select_current):
        raise ValueError('QS learning recovery requires its original same-store reader and selector')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding(); result = prepare(deepcopy(source), signal.model_copy(deep=True)); check_binding(); return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('QS learning successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)); check_binding(); return result

    dispatcher = build_qs_learning_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry, original_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({'QS-A12'})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS learning recovery changed original journal, snapshots or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS learning recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding(); return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id='QS-A12', role='QS')
