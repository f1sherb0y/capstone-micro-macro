"""Read the original QS procurement task and actual current task/round readiness."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_procurement_actions import QSProcurementActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementScopeView, QSProcurementTaskView, QSProcurementRoundView, QSProcurementTemplateView,
    QSProcurementDesignView, QSMeasurementRuleView, QSPricingRuleView, QSProcurementQuantityView,
    QSProcurementDocumentView, QSProcurementGapView, QSProcurementResponseView, QSProcurementExclusionView,
    QSProcurementRevisionView, QSProcurementPackageView, QSProcurementPublicationAuthorityView, QSPublicationBasisView,
)
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_procurement_conditions import QSProcurementConditionReading, _CODE
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSProcurementCurrentSelection:
    request: RoleContractInvocation


class QSProcurementRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSProcurementRecoveryBindings:
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
            raise ValueError('QS procurement recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSProcurementReader:
    """Assemble a fresh procurement judgment using the same journal's immutable snapshot.

    Actual history is read under the caller's source/authority/journal guard.
    Native validation authenticates joint task/round readiness and complete procurement history;
    no procurement processor, quantity production, document publication or tender approval executes here.
    """
    ACTION_ID = 'QS-A05'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSProcurementActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS procurement reader requires actual formal assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-procurement-reader.v1', 'action_id': self.ACTION_ID, 'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode, 'macro_version': a.macro_version,
            'policy_version': a.policy_version, 'model_version': a.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current, a = self._components(), self.assembler
        if (len(current) != len(self._original_components) or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A05' or a.ACTION_ID != self.ACTION_ID or a.source_mode != 'formal'
                or a._views.source_mode != 'formal' or a._views.organizations is not a.organizations
                or a._views.provider is not a.provider or a._views.macro_version != a.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS procurement reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 2 or [ref.kind for ref in old_refs] != ['Task', 'ProcurementRound']):
            raise TaskConflict('QS procurement reader replaces original joint task/round wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSProcurementCurrentSelection):
            raise TaskConflict('QS procurement reader requires a typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope'] or current_input.scope != original_input.scope
                or current_input.procurement_scope_ref.key()[:2] != original_input.procurement_scope_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS procurement reader substitutes original procurement scope/task or authorized historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS procurement assembly changed original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def read_authority(authority_ref, function_ref):
                grant, function = reading.resolve(authority_ref), reading.resolve(function_ref)
                if not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment):
                    raise TaskConflict('QS procurement history requires actual author/task/buyer grants and functions')
                for ref in (*grant.basis_refs, *function.basis_refs):
                    reading.resolve(ref)

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != original_input.scope:
                    raise TaskConflict('QS procurement reader lacks an exact scoped original/current source')
                for evidence_ref in row.evidence_refs:
                    reading.resolve(evidence_ref)
                if isinstance(row, (QSProcurementDesignView, QSProcurementQuantityView, QSProcurementDocumentView)):
                    read_authority(row.author_authority_ref, row.author_function_ref)
                return row

            original_scope = read(original_input.procurement_scope_ref, QSProcurementScopeView)
            if original_scope.task_ref != old_refs[0] or original_scope.round_ref != old_refs[1]:
                raise TaskConflict('QS procurement joint wait differs from its original snapshot scope/task/round')
            for action_input in (original_input, prepared.action_input):
                procurement = read(action_input.procurement_scope_ref, QSProcurementScopeView)
                task = read(procurement.task_ref, QSProcurementTaskView)
                round_ = read(procurement.round_ref, QSProcurementRoundView)
                template = read(procurement.template_ref, QSProcurementTemplateView)
                if (task.procurement_scope_ref != procurement.ref or task.round_ref != round_.ref
                        or round_.procurement_scope_ref != procurement.ref or round_.template_ref != template.ref
                        or task.organization_id != source['organization_id'] or round_.buyer_id != procurement.buyer_id
                        or round_.buyer_organization_id != procurement.buyer_organization_id):
                    raise TaskConflict('QS procurement reader changes original task, round, buyer or template association')
                read_authority(task.authority_ref, task.function_ref)

                def related(ref, schema, *, scope_ref=None, round_ref=None):
                    row = read(ref, schema)
                    expected_scope = procurement.ref if scope_ref is None else scope_ref
                    expected_round = round_.ref if round_ref is None else round_ref
                    if row.procurement_scope_ref != expected_scope or row.round_ref != expected_round:
                        raise TaskConflict('QS procurement history substitutes its original scope/round version')
                    return row

                def question(ref, *, scope_ref=None, round_ref=None):
                    row = related(ref, QSProcurementGapView, scope_ref=scope_ref, round_ref=round_ref)
                    related(row.response_requirement_ref, QSProcurementResponseView, scope_ref=scope_ref, round_ref=round_ref)
                    return row

                def quantity(ref, *, scope_ref=None, round_ref=None):
                    row = related(ref, QSProcurementQuantityView, scope_ref=scope_ref, round_ref=round_ref)
                    read(row.measurement_rule_ref, QSMeasurementRuleView)
                    for design_ref in row.design_refs:
                        read(design_ref, QSProcurementDesignView)
                    for line in row.lines:
                        read(line.design_ref, QSProcurementDesignView)
                        for evidence_ref in line.basis_refs:
                            reading.resolve(evidence_ref)
                        if line.quantity.state == 'known':
                            reading.resolve(line.quantity.value.basis_ref)
                        if line.provisional_question_ref is not None:
                            question(line.provisional_question_ref, scope_ref=row.procurement_scope_ref, round_ref=row.round_ref)
                    return row

                def pricing(ref, *, scope_ref=None, round_ref=None):
                    row = read(ref, QSPricingRuleView)
                    if row.round_ref != (round_.ref if round_ref is None else round_ref):
                        raise TaskConflict('QS procurement pricing history substitutes its original round')
                    read(row.measurement_rule_ref, QSMeasurementRuleView)
                    for design_ref in row.design_refs:
                        read(design_ref, QSProcurementDesignView)
                    if row.quantity_schedule_ref is not None:
                        quantity(row.quantity_schedule_ref, scope_ref=scope_ref, round_ref=row.round_ref)
                    for exclusion_ref in row.excluded_scope_refs:
                        read(exclusion_ref, QSProcurementExclusionView)
                    return row

                def document(ref):
                    row = read(ref, QSProcurementDocumentView)
                    if row.draft.procurement_scope_ref.key()[:2] != procurement.ref.key()[:2]:
                        raise TaskConflict('QS procurement document history borrows another physical procurement scope')
                    for design_ref in row.draft.design_refs:
                        read(design_ref, QSProcurementDesignView)
                    read(row.draft.measurement_rule_ref, QSMeasurementRuleView)
                    quantity(row.draft.quantity_schedule_ref, scope_ref=row.draft.procurement_scope_ref, round_ref=row.round_ref)
                    pricing(row.draft.pricing_rule_ref, scope_ref=row.draft.procurement_scope_ref, round_ref=row.round_ref)
                    for exclusion_ref in row.draft.exclusions:
                        read(exclusion_ref, QSProcurementExclusionView)
                    for gap in row.draft.open_questions:
                        for evidence_ref in gap.evidence_refs:
                            reading.resolve(evidence_ref)
                        for target_ref in gap.target_refs:
                            question(target_ref, scope_ref=row.draft.procurement_scope_ref, round_ref=row.round_ref)
                        related(gap.response_requirement_ref, QSProcurementResponseView,
                            scope_ref=row.draft.procurement_scope_ref, round_ref=row.round_ref)
                    if row.draft.prior_document_ref is not None:
                        predecessor = read(row.draft.prior_document_ref, QSProcurementDocumentView)
                        if predecessor.ref == row.ref or predecessor.draft.procurement_scope_ref.key()[:2] != procurement.ref.key()[:2]:
                            raise TaskConflict('QS procurement document predecessor substitutes its original lineage')
                    return row

                # Waiting can precede declared source selection/completeness.
                # Read both histories rather than dropping their known records.
                for ref in {ref.key(): ref for ref in [*procurement.design_refs, *action_input.design_refs]}.values():
                    read(ref, QSProcurementDesignView)
                for ref in {procurement.measurement_rule_ref, action_input.measurement_rule_ref}:
                    read(ref, QSMeasurementRuleView)
                for ref in {procurement.quantity_schedule_ref, action_input.quantity_schedule_ref} - {None}:
                    quantity(ref)
                pricing(procurement.pricing_rule_ref)
                for ref in procurement.exclusions:
                    read(ref, QSProcurementExclusionView)
                for ref in procurement.question_refs:
                    question(ref)
                for ref in {procurement.prior_document_ref, action_input.prior_document_ref, procurement.saved_document_ref} - {None}:
                    document(ref)
                if procurement.revision_impact_ref is not None:
                    impact = related(procurement.revision_impact_ref, QSProcurementRevisionView)
                    prior = document(impact.prior_document_ref)
                    quantity(impact.quantity_schedule_ref)
                    pricing(impact.pricing_rule_ref)
                    for ref in impact.design_refs:
                        read(ref, QSProcurementDesignView)
                    for change in impact.changes:
                        package = read(change.package_ref, QSProcurementPackageView)
                        if package.procurement_scope_ref.key()[:2] != procurement.ref.key()[:2] or package.round_ref != prior.round_ref:
                            raise TaskConflict('QS procurement revision borrows another original package or prior round')
                if action_input.publication_authority_ref is not None:
                    power = related(action_input.publication_authority_ref, QSProcurementPublicationAuthorityView)
                    document(power.document_ref)
                    basis = related(power.publication_basis_ref, QSPublicationBasisView)
                    if basis.document_ref != power.document_ref:
                        raise TaskConflict('QS procurement publication basis substitutes its original authorized document')
                    read_authority(power.buyer_authority_ref, power.buyer_function_ref)
                    read_authority(basis.checker_authority_ref, basis.checker_function_ref)
            return QSProcurementConditionReading(prepared.context, reading, deepcopy(snapshot['action_input']),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck(); self._check()
            current = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot or any(current.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS procurement reader changed original snapshot or assembled context/input/source reading')


def build_assembled_qs_procurement_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one actual source/authority/inbox/journal guard across QS recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_procurement_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS procurement recovery requires actual same-run guard and validators')
    reader = QSProcurementReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
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
            raise TaskConflict('QS procurement successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_qs_procurement_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    journal, registry, final_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not journal
                or journal.store is not store or journal.registry is not registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not final_revalidate
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS procurement recovery changed original journal/recipient/source callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS procurement recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role='QS')
