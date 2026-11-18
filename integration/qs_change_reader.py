"""Read the original QS change claim and actual current resubmission."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_change_actions import QSChangeActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_change_objects import (
    ChangeAuthored, QSChangeClaimView, QSChangeContractView, QSChangeInstructionView,
    QSChangeLineView, QSChangeStatementView, QSChangeResultView, QSChangeAuthorityView,
    QSChangeEntitlementView, QSChangeDeterminationView, QSChangeQuestionView, QSChangeResponseView,
)
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_change_conditions import QSChangeConditionReading, _CODE
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSChangeCurrentSelection:
    request: RoleContractInvocation


class QSChangeRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSChangeRecoveryBindings:
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
            raise ValueError('QS change recovery requires actual source selection, guard and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSChangeReader:
    """Assemble a fresh valuation using the same journal's immutable snapshot.

    Actual history is read under the caller's source/authority/journal guard.
    Native validation authenticates resubmission and complete valuation history;
    no valuation processor, calculation, entitlement or contract effect executes here.
    """
    ACTION_ID = 'QS-A07'

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSChangeActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS change reader requires actual formal assembler, original snapshots and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components()
        self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-change-reader.v1', 'action_id': self.ACTION_ID, 'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode, 'macro_version': a.macro_version,
            'policy_version': a.policy_version, 'model_version': a.model_version, 'snapshot_schema': self.snapshots.SCHEMA,
            'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current, a = self._components(), self.assembler
        if (len(current) != len(self._original_components) or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A07' or a.ACTION_ID != self.ACTION_ID or a.source_mode != 'formal'
                or a._views.source_mode != 'formal' or a._views.organizations is not a.organizations
                or a._views.provider is not a.provider or a._views.macro_version != a.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS change reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'ChangeClaim'):
            raise TaskConflict('QS change reader replaces original claim wait or recipient')
        identity = TaskIdentity(**deepcopy(source)); snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if original_input.claim_or_change_ref.key() != old_refs[0].key():
            raise TaskConflict('QS change wait differs from its original invocation snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSChangeCurrentSelection):
            raise TaskConflict('QS change reader requires a typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope'] or current_input.scope != original_input.scope
                or current_input.claim_or_change_ref.key()[:2] != original_input.claim_or_change_ref.key()[:2]
                or current_input.contract_ref.key()[:2] != original_input.contract_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS change reader substitutes original contract/claim/scope or authorized historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS change assembly changed original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)
            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != original_input.scope:
                    raise TaskConflict('QS change reader lacks an exact scoped history source')
                for evidence_ref in row.evidence_refs:
                    reading.resolve(evidence_ref)
                if isinstance(row, ChangeAuthored):
                    grant = reading.resolve(row.author_authority_ref)
                    function = reading.resolve(row.author_function_ref)
                    if not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment):
                        raise TaskConflict('QS change history requires actual author grants and functions')
                    for basis_ref in (*grant.basis_refs, *function.basis_refs):
                        reading.resolve(basis_ref)
                return row

            for action_input in (original_input, prepared.action_input):
                claim = read(action_input.claim_or_change_ref, QSChangeClaimView)
                contract = read(action_input.contract_ref, QSChangeContractView)
                if (claim.contract_ref != contract.ref or claim.instruction_ref != action_input.instruction_ref
                        or claim.claimant_id != claim.author_actor_id or claim.claimant_id not in contract.party_ids
                        or contract.valuation_organization_id != source['organization_id']):
                    raise TaskConflict('QS change reader changes original claimant, instruction or contract association')
                grant = reading.resolve(contract.valuation_authority_ref)
                function = reading.resolve(contract.valuation_function_ref)
                if not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment):
                    raise TaskConflict('QS change contract requires its original appointed QS grant and function')
                for ref in (*grant.basis_refs, *function.basis_refs):
                    reading.resolve(ref)

                def related(ref, schema, *, historical=False):
                    row = read(ref, schema)
                    if (row.contract_ref != contract.ref or row.claim_ref.key()[:2] != claim.ref.key()[:2]
                            or (not historical and row.claim_ref != claim.ref)):
                        raise TaskConflict('QS change history substitutes original contract or claim version')
                    return row

                def result(ref, *, historical=False):
                    row = related(ref, QSChangeResultView, historical=historical)
                    for amount in (row.assessed_amount, row.period_delta):
                        if amount is not None:
                            reading.resolve(amount.basis_ref)
                    return row

                # Withdrawal may have returned before these declared records
                # were read. Read both complete histories independently now.
                for ref in claim.line_refs:
                    line = related(ref, QSChangeLineView)
                    reading.resolve(line.calculation_line.quantity_delta.basis_ref)
                    reading.resolve(line.calculation_line.unit_rate.basis_ref)
                for ref in claim.prior_statement_refs:
                    statement = related(ref, QSChangeStatementView, historical=True)
                    saved = result(statement.calculation_ref, historical=True)
                    if saved.claim_ref != statement.claim_ref:
                        raise TaskConflict('QS change prior valuation substitutes its original statement claim version')
                    reading.resolve(statement.period_delta.basis_ref)
                if action_input.instruction_ref is not None:
                    instruction = related(action_input.instruction_ref, QSChangeInstructionView)
                    related(instruction.instruction_authority_ref, QSChangeAuthorityView)
                if action_input.valuation_result_ref is not None:
                    result(action_input.valuation_result_ref)
                if action_input.entitlement_ref is not None:
                    entitlement = related(action_input.entitlement_ref, QSChangeEntitlementView)
                    related(entitlement.decision_authority_ref, QSChangeAuthorityView)
                    if entitlement.calculation_ref is not None:
                        result(entitlement.calculation_ref)
                    for amount in (entitlement.recognized_amount, entitlement.disputed_amount):
                        if amount.state == 'known':
                            reading.resolve(amount.value.basis_ref)
                for ref in claim.question_refs:
                    question = related(ref, QSChangeQuestionView)
                    related(question.response_requirement_ref, QSChangeResponseView)
                if claim.determination_basis_ref is not None:
                    determination = related(claim.determination_basis_ref, QSChangeDeterminationView)
                    related(determination.determination_authority_ref, QSChangeAuthorityView)
                    result(determination.calculation_ref)
            return QSChangeConditionReading(prepared.context, reading, deepcopy(snapshot['action_input']),
                prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck(); self._check()
            current = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot or any(current.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS change reader changed original snapshot or assembled context/input/source reading')


def build_assembled_qs_change_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one actual source/authority/inbox/journal guard across QS recovery."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_change_continuation_dispatcher

    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS change recovery requires actual same-run guard and validators')
    reader = QSChangeReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
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
            raise TaskConflict('QS change successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_qs_change_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    journal, registry, final_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not journal
                or journal.store is not store or journal.registry is not registry or dispatcher.project_signal is not project_signal
                or dispatcher.prepare is not prepare_current or dispatcher.revalidate is not final_revalidate
                or dispatcher.action_ids != frozenset({reader.ACTION_ID})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS change recovery changed original journal/recipient/source callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS change recovery changes original run or recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id=reader.ACTION_ID, role='QS')
