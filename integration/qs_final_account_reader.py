"""Read original QS-A09 execution waits and complete supplied settlement history."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.module_host import module_factory_descriptor
from integration.qs_final_account_actions import QSFinalAccountActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId, walk_references
from src.actions.contracts.qs_final_account_objects import (
    QSFinalContractView, QSFinalProfileView, QSFinalExecutionView, QSFinalEntitlementView,
    QSFinalEntitlementAuthorityView, QSFinalCashExecutionView, QSFinalAdjustmentView,
    QSFinalAdjustmentBasisView, QSFinalResultView, QSFinalDeterminationView,
    QSFinalMechanismView, QSFinalConsentView, QSFinalPowerBasisView,
    QSFinalQuestionView, QSFinalResponseView, QSPaymentCertificateView,
    QSPaymentStatementView, QSChangeClaimView,
)
from src.actions.contracts.qs_payment_objects import QSPaymentReceiptView
from src.organization.models import Authorization, RoleAssignment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_final_account_conditions import (
    QSFinalAccountConditionReading, _CODE, qs_original_final_account_execution_profile,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class QSFinalAccountCurrentSelection:
    request: RoleContractInvocation


class QSFinalAccountRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class QSFinalAccountRecoveryBindings:
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
            raise ValueError('QS final account recovery requires actual source selection and native validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class QSFinalAccountReader:
    """Assemble current A09 sources while retaining the immutable original input."""
    ACTION_ID = 'QS-A09'
    EXECUTION_PROFILE_FACTORY = staticmethod(qs_original_final_account_execution_profile)

    def __init__(self, *, assembler, snapshots, select_current):
        if (not isinstance(assembler, QSFinalAccountActionAssembler) or assembler.source_mode != 'formal'
                or not isinstance(snapshots, InvocationSnapshotStore) or not callable(select_current)
                or snapshots.store.run_id != assembler.organizations.run_id):
            raise ValueError('QS final account reader requires actual formal assembler, snapshot store and selector')
        self.assembler, self.snapshots, self.select_current = assembler, snapshots, select_current
        self._original_components = self._components(); self._declared = self._configuration()

    def _components(self):
        a = self.assembler
        return (a, a.registry, a.organizations, a.provider, a._views, a._views.schemas, a.methods,
            a.audit_sink, self.snapshots, self.snapshots.store, self.select_current,
            self.EXECUTION_PROFILE_FACTORY, *a.decision_strategies)

    def _configuration(self):
        a = self.assembler
        return {'schema_version': 'qs-final-account-reader.v1', 'action_id': self.ACTION_ID,
            'condition_code': _CODE,
            'run_id': a.organizations.run_id, 'source_mode': a.source_mode,
            'macro_version': a.macro_version, 'policy_version': a.policy_version, 'model_version': a.model_version,
            'snapshot_schema': self.snapshots.SCHEMA, 'read_original': module_factory_descriptor(self.snapshots.get, 'read_original'),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'execution_condition': module_factory_descriptor(self.EXECUTION_PROFILE_FACTORY, 'execution_condition'),
            'assemble_current': module_factory_descriptor(a.build, 'assemble_current'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not old for now, old in zip(current, self._original_components))
                or self.ACTION_ID != 'QS-A09' or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.source_mode != 'formal' or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.provider is not self.assembler.provider or self.assembler._views.macro_version != self.assembler.macro_version
                or self._configuration() != self._declared):
            raise TaskConflict('QS final account reader changed original source/model/snapshot bindings')

    def configuration_evidence(self):
        self._check(); return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(waited) != 1 or waited[0].kind != 'FinalAccountExecution'):
            raise TaskConflict('QS final-account reader replaces original execution wait or recipient')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, QSFinalAccountCurrentSelection):
            raise TaskConflict('QS final-account reader requires typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or current_input.contract_ref.key()[:2] != original_input.contract_ref.key()[:2]
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('QS final-account reader changes original scope/contract or current authorized sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading = prepared.reading
        baseline = deepcopy(reading.evidence())
        history_rows, missing_targets = {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('QS final-account assembly changes original source snapshot or recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def authority(authority_ref, function_ref):
                grant, assignment = reading.resolve(authority_ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or grant.ref != authority_ref
                        or not isinstance(assignment, RoleAssignment) or assignment.function_ref != function_ref):
                    raise TaskConflict('QS final-account history lacks exact original author authority/function')
                for ref in (*grant.basis_refs, *assignment.basis_refs):
                    reading.resolve(ref)

            def read(ref, schema, *, contract=None, physical=False):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('QS final-account reader lacks an exact supported original/current source')
                if contract is not None:
                    matched = (row.contract_ref.key()[:2] == contract.ref.key()[:2] if physical
                        else row.contract_ref == contract.ref)
                    if not matched:
                        raise TaskConflict('QS final-account history borrows another original contract')
                for evidence_ref in getattr(row, 'evidence_refs', []):
                    reading.resolve(evidence_ref)
                for evidence_ref in walk_references(row):
                    if evidence_ref.kind == 'Evidence':
                        reading.resolve(evidence_ref)
                if hasattr(row, 'author_authority_ref'):
                    authority(row.author_authority_ref, row.author_function_ref)
                history_rows[ref.key()] = row.model_dump(mode='json')
                return row

            def supplied(ref):
                if ref.key() in reading._resolver._objects:
                    return True
                # A wait can precede selection of a future question/decision target.
                # Absence is retained for independent native validation, never success.
                missing_targets[ref.key()] = ref.model_dump(mode='json')
                return False

            def mechanism(ref, contract):
                row = read(ref, QSFinalMechanismView, contract=contract)
                grant = reading.resolve(row.authorization_ref)
                if not isinstance(grant, Authorization) or grant.ref != row.authorization_ref:
                    raise TaskConflict('QS settlement history lacks its exact decision grant')
                authority(grant.ref, grant.function_ref)
                if row.power_basis_ref is not None:
                    power = read(row.power_basis_ref, QSFinalPowerBasisView, contract=contract)
                    if power.mechanism_ref != row.ref:
                        raise TaskConflict('QS settlement power borrows another original mechanism')
                for consent_ref in row.party_consent_refs:
                    consent = read(consent_ref, QSFinalConsentView, contract=contract)
                    if consent.mechanism_ref != row.ref or consent.party_id not in contract.party_ids:
                        raise TaskConflict('QS settlement consent borrows another original mechanism or party')

            for action_input in (original_input, prepared.action_input):
                contract = read(action_input.contract_ref, QSFinalContractView)
                profile = read(contract.final_profile_ref, QSFinalProfileView, contract=contract)
                authority(profile.authority_ref, profile.function_ref)
                for ref in contract.execution_refs:
                    execution = read(ref, QSFinalExecutionView, contract=contract, physical=True)
                    if execution.run_id != source['run_id']:
                        raise TaskConflict('QS final-account execution substitutes another original run')
                    read(execution.profile_ref, QSFinalProfileView, contract=contract, physical=True)
                    if execution.reconciliation_result_ref is not None:
                        read(execution.reconciliation_result_ref, QSFinalResultView, contract=contract, physical=True)
                for ref in set(action_input.determined_change_refs) | set(contract.determined_change_refs):
                    entitlement = read(ref, QSFinalEntitlementView, contract=contract)
                    power = read(entitlement.decision_authority_ref, QSFinalEntitlementAuthorityView, contract=contract)
                    if power.claim_ref != entitlement.claim_ref:
                        raise TaskConflict('QS final entitlement history changes its original claim authority')
                for ref in set(action_input.unresolved_claim_refs) | set(contract.unresolved_claim_refs):
                    read(ref, QSChangeClaimView, contract=contract)
                for ref in set(action_input.certificate_refs) | set(contract.all_certificate_refs):
                    certificate = read(ref, QSPaymentCertificateView, contract=contract)
                    statement = read(certificate.statement_ref, QSPaymentStatementView, contract=contract)
                    if statement.certificate_ref != certificate.ref or statement.calculation_ref != certificate.calculation_ref:
                        raise TaskConflict('QS final certificate history changes original statement/calculation association')
                cash_refs = set(contract.payment_execution_refs)
                for ref in set(action_input.payment_receipt_refs) | set(contract.receipt_refs):
                    receipt = read(ref, QSPaymentReceiptView, contract=contract)
                    if receipt.payer_id != contract.payer_id or receipt.beneficiary_id != contract.beneficiary_id:
                        raise TaskConflict('QS final cash history changes original payer or beneficiary')
                    cash_refs.add(receipt.execution_ref)
                for ref in cash_refs:
                    execution = read(ref, QSFinalCashExecutionView, contract=contract)
                    if execution.run_id != source['run_id']:
                        raise TaskConflict('QS final cash history substitutes another original run')
                    for receipt_ref in execution.receipt_refs:
                        receipt = read(receipt_ref, QSPaymentReceiptView, contract=contract)
                        if (receipt.execution_ref.key()[:2] != execution.ref.key()[:2]
                                or receipt.payer_id != execution.payer_id or receipt.beneficiary_id != execution.beneficiary_id):
                            raise TaskConflict('QS final cash history borrows another execution receipt')
                for ref in contract.adjustment_refs:
                    adjustment = read(ref, QSFinalAdjustmentView, contract=contract)
                    basis = read(adjustment.authority_ref, QSFinalAdjustmentBasisView, contract=contract)
                    if basis.adjustment_ref != adjustment.ref or basis.kind != adjustment.kind:
                        raise TaskConflict('QS final adjustment history changes original applied basis')
                    mechanism(basis.mechanism_ref, contract)
                if action_input.reconciliation_result_ref is not None:
                    read(action_input.reconciliation_result_ref, QSFinalResultView, contract=contract)
                if profile.determination_basis_ref is not None and supplied(profile.determination_basis_ref):
                    basis = read(profile.determination_basis_ref, QSFinalDeterminationView, contract=contract)
                    mechanism(basis.mechanism_ref, contract)
                for ref in profile.question_refs:
                    if not supplied(ref):
                        continue
                    question = read(ref, QSFinalQuestionView, contract=contract)
                    if supplied(question.response_requirement_ref):
                        read(question.response_requirement_ref, QSFinalResponseView, contract=contract)
            original_contract = read(original_input.contract_ref, QSFinalContractView)
            if waited[0] not in original_contract.execution_refs:
                raise TaskConflict('QS final-account wait differs from its original contract history')
            return QSFinalAccountConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                original_context=ActionContext.model_validate(snapshot['context']).model_copy(deep=True),
                settlement_sources=deepcopy(list(history_rows.values())),
                unavailable_targets=deepcopy(list(missing_targets.values())))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('QS final-account reader changed original snapshot or assembled sources/context/input')


def build_assembled_qs_final_account_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge
    from integration.task_continuation import build_qs_final_account_continuation_dispatcher
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('QS final account recovery requires actual same-run guards and validators')
    reader = QSFinalAccountReader(assembler=assembler, snapshots=InvocationSnapshotStore(store), select_current=select_current)
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def prepare_current(source, signal):
        check_binding(); result = prepare(deepcopy(source), signal.model_copy(deep=True)); check_binding(); return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        validated = assembler.registry.get(reader.ACTION_ID).contract.validate_input(deepcopy(preparation.next_input))
        if validated.model_dump(mode='json') != preparation.next_input:
            raise TaskConflict('QS final account successor changes its current closed input')
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)); check_binding(); return result

    dispatcher = build_qs_final_account_continuation_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry, original_revalidate = dispatcher.journal, dispatcher.journal.registry, dispatcher.revalidate

    def check_binding():
        reader._check()
        if (reader.snapshots.store is not store or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({'QS-A09'})
                or any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())):
            raise TaskConflict('QS final account recovery changed original journal, snapshots or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('QS final account recovery requires original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding(); result = dispatcher(run_id=run_id, organization_id=organization_id); check_binding(); return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher, read_guard=read_guard,
        check_binding=check_binding, action_id='QS-A09', role='QS')
