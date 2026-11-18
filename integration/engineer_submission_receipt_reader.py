"""Assemble current authorized ENGINEER-A07 sources for original query waits."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from integration.engineer_deliverable_actions import EngineerDeliverableActionAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.engineer_submission_objects import (
    EngineerSubmissionDeliverableView, EngineerSubmissionProfileView, EngineerSubmissionSavedView,
)
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.coordination.engineer_submission_conditions import EngineerSubmissionReceiptConditionReading
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class EngineerSubmissionReceiptCurrentSelection:
    request: RoleContractInvocation
    submission_ref: Reference


class EngineerSubmissionRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class EngineerSubmissionRecoveryBindings:
    """Actual callbacks; the formal app binds its final authorized provider."""
    select_current: Callable
    read_guard: Callable
    validate_relation: Callable
    project_signal: Callable
    prepare: Callable
    revalidate: Callable

    def components(self):
        return (self.select_current, self.read_guard, self.validate_relation,
            self.project_signal, self.prepare, self.revalidate)

    def __post_init__(self):
        if not all(callable(callback) for callback in self.components()):
            raise ValueError('Engineer receipt recovery requires actual current selection, guard and validators')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class EngineerSubmissionReceiptReader:
    """Read explicit original/current versions through the original A07 assembler.

    The host holds source/authorization/journal guards throughout evaluation.
    The selector supplies a complete current invocation and explicit execution
    version. Signals never supply projections or establish which version is
    current. Assembly runs no action, native query, model or publication.
    """
    def __init__(self, *, assembler, select_current):
        if (not isinstance(assembler, EngineerDeliverableActionAssembler) or assembler.source_mode != 'formal'
                or not callable(select_current)):
            raise ValueError('Engineer submission recovery requires the original formal A07 assembler and current selector')
        self.assembler, self.select_current = assembler, select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            self.select_current)

    def _configuration(self):
        return {'schema_version': 'engineer-submission-receipt-reader.v1',
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'model_version': self.assembler.model_version,
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'read_sources': module_factory_descriptor(self.assembler.build_result_reading, 'read_sources'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        if (any(now is not original for now, original in zip(self._components(), self._original_components))
                or self.assembler.ACTION_ID != 'ENGINEER-A07' or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self._configuration() != self._declared):
            raise TaskConflict('Engineer submission reader changed original assembler, selector or source declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'ENGINEER-A07' or source['role'] != 'Engineer' or source['purpose'] != 'action'
                or check.condition.condition_code != 'original_command_receipt_resolved_without_duplicate_version_work_or_fee'
                or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'DeliverableSubmission'):
            raise TaskConflict('Engineer submission reader changes original condition, recipient or execution selection')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, EngineerSubmissionReceiptCurrentSelection)
                or not isinstance(selected.submission_ref, Reference)):
            raise TaskConflict('Engineer submission reader requires a typed current request and explicit execution version')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref, old_ref = request.context, selected.submission_ref.model_copy(deep=True), old_refs[0]
        registration = self.assembler.registry.get('ENGINEER-A07')
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != 'ENGINEER-A07' or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {old_ref.key(), ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Engineer submission reader requires visible original/current versions and a fresh formal context')
        action_input = registration.contract.validate_input(deepcopy(request.action_input))
        context_sha256 = task_digest(context.model_dump(mode='json'))
        input_sha256 = task_digest(action_input.model_dump(mode='json'))
        reading = self.assembler.build_result_reading(context)
        try:
            if reading.organization_id != source['organization_id']:
                raise TaskConflict('Engineer receipt reader substitutes another authorized organization')
            deliverable = reading.resolve(action_input.deliverable_ref)
            if (not isinstance(deliverable, EngineerSubmissionDeliverableView)
                    or deliverable.ref.key() != action_input.deliverable_ref.key()
                    or deliverable.author_organization_id != source['organization_id']):
                raise TaskConflict('Engineer receipt reader lacks the exact original authored deliverable')
            profile = reading.resolve(deliverable.submission_profile_ref)
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if (not isinstance(profile, EngineerSubmissionProfileView)
                    or profile.ref.key() != deliverable.submission_profile_ref.key()
                    or profile.organization_id != source['organization_id']
                    or profile.deliverable_ref.key() != deliverable.ref.key() or profile.history_coverage != 'complete'
                    or old_ref.key() not in {item.key() for item in profile.submission_refs}
                    or not isinstance(original, EngineerSubmissionSavedView)
                    or not isinstance(current, EngineerSubmissionSavedView)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or any(row.organization_id != source['organization_id']
                        or row.deliverable_ref.key() != deliverable.ref.key()
                        or row.command_id != profile.command_id or row.business_key != profile.business_key
                        or row.operation_id != profile.operation_id or row.choice != profile.choice
                        for row in (original, current))):
                raise TaskConflict('Engineer receipt reader changes exact version, original submission history or command')
            reading.recheck()
            return EngineerSubmissionReceiptConditionReading(context, reading, ref)
        finally:
            reading.recheck()
            self._check()
            if (task_digest(context.model_dump(mode='json')) != context_sha256
                    or task_digest(action_input.model_dump(mode='json')) != input_sha256):
                raise TaskConflict('Engineer receipt reader changed current query context or supplied input')


def build_assembled_engineer_submission_receipt_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Hold read_guard(run_id, organization_id) through original wait wakeup.

    The guard covers inbox, original/current sources, authority and journal.
    Application preparation and revalidation remain responsible for independent
    successor facts, preserved obligations and a distinct current business plan.
    """
    from integration.task_continuation import build_engineer_submission_receipt_dispatcher

    reader = EngineerSubmissionReceiptReader(assembler=assembler, select_current=select_current)
    if not callable(read_guard) or reader.assembler.organizations.run_id != store.run_id:
        raise ValueError('Engineer submission recovery requires its same-run source/authority/journal guard')
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()):
        raise ValueError('Engineer submission recovery requires actual query and successor validation callbacks')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

    def check_callbacks():
        reader._check()
        if any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items()):
            raise TaskConflict('Engineer submission recovery callback declarations changed')

    def prepare_current(source, signal):
        check_binding()
        result = prepare(deepcopy(source), signal.model_copy(deep=True))
        check_binding()
        return result

    def revalidate_current(source, preparation, signal):
        check_binding()
        result = revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
        check_binding()
        return result

    dispatcher = build_engineer_submission_receipt_dispatcher(inbox=inbox, store=store, read_current=reader,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare_current,
        revalidate=revalidate_current, extra_profiles=extra_profiles)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry

    def check_binding():
        check_callbacks()
        if (dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not revalidate_current or dispatcher.action_ids != frozenset({'ENGINEER-A07'})):
            raise TaskConflict('Engineer submission recovery changed original journal, recipient or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Engineer submission recovery requires its original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id='ENGINEER-A07', role='Engineer')
