"""Read actual current A04 bid command sources through the original assembler."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from pydantic import model_validator

from integration.contractor_formation_actions import ContractorFormationActionAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentBidView, ContractorAmendmentSubmissionView
from src.actions.contracts.contractor_formation_objects import ContractorFormationOfferView, ContractorFormationTermsView
from src.coordination.contractor_formation_conditions import ContractorFormationCommandConditionReading
from src.coordination.tasks import TaskConflict, task_digest, _text


@dataclass(frozen=True)
class ContractorFormationCommandCurrentSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class ContractorFormationRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    command_ids: list[TextId]

    @model_validator(mode='after')
    def explicit_distinct_commands(self):
        if not self.command_ids or len(set(self.command_ids)) != len(self.command_ids):
            raise ValueError('Formation recovery requires nonempty distinct original command IDs')
        return self


@dataclass(frozen=True)
class ContractorFormationRecoveryBindings:
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
            raise ValueError('Formation recovery requires actual selection, guard, query and successor callbacks')

    def configuration_evidence(self):
        return {name: module_factory_descriptor(getattr(self, name), name) for name in (
            'select_current', 'read_guard', 'validate_relation', 'project_signal', 'prepare', 'revalidate')}


class ContractorFormationCommandReader:
    """Assemble a fresh A04 request without running its processor or submitting.

    Original/current bid and submission versions must be explicitly visible.
    A current bid may point to a newer result of the same command, while its
    entire draft, package, round, scope and reservation references stay fixed.
    The surrounding host guard covers sources, authority, inbox and journal.
    """
    ACTION_ID = 'CONTRACTOR-A04'
    ASSEMBLER_TYPE = ContractorFormationActionAssembler
    SELECTION_TYPE = ContractorFormationCommandCurrentSelection
    SCHEMA_VERSION = 'contractor-formation-command-reader.v1'

    def __init__(self, *, assembler, command_ids, select_current):
        if (not isinstance(assembler, self.ASSEMBLER_TYPE) or assembler.source_mode != 'formal'
                or not isinstance(command_ids, (tuple, list)) or not command_ids or not callable(select_current)):
            raise ValueError('Formation recovery requires original formal A04 assembler, commands and selector')
        for command_id in command_ids:
            _text(command_id)
        if len(set(command_ids)) != len(command_ids):
            raise ValueError('Formation recovery cannot repeat an original command')
        self.assembler, self.command_ids, self.select_current = assembler, tuple(command_ids), select_current
        self._original_components = self._components()
        self._declared = self._configuration()
        self._check()

    def _components(self):
        assembler = self.assembler
        return (assembler, assembler.registry, assembler.organizations, assembler.provider, assembler._views,
            assembler._views.schemas, assembler.methods, self.select_current, *assembler.decision_strategies)

    def _configuration(self):
        return {'schema_version': self.SCHEMA_VERSION, 'action_id': self.ACTION_ID,
            'run_id': self.assembler.organizations.run_id, 'source_mode': self.assembler.source_mode,
            'macro_version': self.assembler.macro_version, 'policy_version': self.assembler.policy_version,
            'model_version': self.assembler.model_version, 'command_ids': list(self.command_ids),
            'select_current': module_factory_descriptor(self.select_current, 'select_current'),
            'assemble_current': module_factory_descriptor(self.assembler.build, 'assemble_current'),
            'select_bid_sources': module_factory_descriptor(type(self)._current_bid, 'select_bid_sources'),
            'condition_reading': module_factory_descriptor(type(self)._condition_reading, 'condition_reading'),
            'condition_codes': module_factory_descriptor(type(self)._condition_codes, 'condition_codes'),
            'original_command': module_factory_descriptor(type(self)._matches_original_command, 'original_command'),
            'wait_refs': module_factory_descriptor(type(self)._valid_wait_refs, 'wait_refs'),
            'original_bid_refs': module_factory_descriptor(type(self)._original_bid_refs, 'original_bid_refs'),
            'read_current': module_factory_descriptor(type(self).__call__, 'read_current')}

    def _check(self):
        current = self._components()
        if (len(current) != len(self._original_components)
                or any(now is not original for now, original in zip(current, self._original_components))
                or self.assembler.ACTION_ID != self.ACTION_ID or self.assembler.source_mode != 'formal'
                or self.assembler._views.provider is not self.assembler.provider
                or self.assembler._views.organizations is not self.assembler.organizations
                or self.assembler._views.macro_version != self.assembler.macro_version
                or self.assembler._views.source_mode != 'formal' or self._configuration() != self._declared):
            raise TaskConflict('Formation command reader changed original assembler, bindings or source declarations')

    def configuration_evidence(self):
        self._check()
        return deepcopy(self._declared)

    def _current_bid(self, prepared, current_execution):
        reading = prepared.reading
        offer = reading.resolve(prepared.action_input.offer_ref)
        terms = reading.resolve(prepared.action_input.terms_ref)
        if (not isinstance(offer, ContractorFormationOfferView) or not isinstance(terms, ContractorFormationTermsView)
                or terms.bid_ref.key() != offer.bid_ref.key()
                or offer.package_ref.key() != current_execution.package_ref.key()
                or terms.package_ref.key() != current_execution.package_ref.key()
                or offer.round_ref.key() != current_execution.round_ref.key()
                or terms.round_ref.key() != current_execution.round_ref.key()):
            raise TaskConflict('Formation reader lacks the actual selected offer, agreement or original package/round')
        return reading.resolve(offer.bid_ref), offer.bid_ref

    def _condition_reading(self, prepared, ref, bid_ref):
        return ContractorFormationCommandConditionReading(prepared.context, prepared.reading, ref, bid_ref)

    def _condition_codes(self):
        return frozenset('query_original_command:' + command for command in self.command_ids)

    def _matches_original_command(self, condition, original):
        return (original.command_id in self.command_ids
            and condition.condition_code == 'query_original_command:' + original.command_id)

    def _valid_wait_refs(self, check):
        refs = check.condition.object_refs
        return len(refs) == 2 and refs[0].kind == 'SubmissionExecution' and refs[1].kind == 'Bid'

    def _original_bid_refs(self, check, reading):
        return check.condition.object_refs

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Contractor' or source['purpose'] != 'action'
                or check.condition.trigger != 'event'
                or check.condition.condition_code not in self._condition_codes()
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not self._valid_wait_refs(check)):
            raise TaskConflict('Formation reader changes original condition, command, recipient or selected bid')
        selected = self.select_current(deepcopy(check))
        self._check()
        if (not isinstance(selected, self.SELECTION_TYPE)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Formation reader requires typed current invocation and explicit execution version')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context, ref = request.context, selected.execution_ref.model_copy(deep=True)
        registration = self.assembler.registry.get(self.ACTION_ID)
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or not {item.key() for item in (*old_refs, ref)} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Formation reader requires visible original/current versions and fresh formal context')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        try:
            reading = prepared.reading
            old_ref, bid_ref = self._original_bid_refs(check, reading)
            if ((ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                    or not {old_ref.key(), bid_ref.key()} <= {item.key() for item in context.visible_refs}):
                raise TaskConflict('Contractor command reader substitutes hidden original bid or execution identity')
            bid = reading.resolve(bid_ref)
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if not isinstance(current, ContractorAmendmentSubmissionView):
                raise TaskConflict('Contractor command reader lacks the actual submission result schema')
            current_bid, current_bid_ref = self._current_bid(prepared, current)
            if (reading.organization_id != source['organization_id']
                    or not isinstance(bid, ContractorAmendmentBidView) or bid.ref.key() != bid_ref.key()
                    or bid.organization_id != source['organization_id'] or bid.submission_ref.key() != old_ref.key()
                    or not isinstance(current_bid, ContractorAmendmentBidView) or current_bid.ref.key() != current_bid_ref.key()
                    or (current_bid.ref.kind, current_bid.ref.id) != (bid_ref.kind, bid_ref.id)
                    or current_bid.ref.key() not in {item.key() for item in context.visible_refs}
                    or current_bid.submission_ref.key() != ref.key()
                    or any(getattr(bid, field) != getattr(current_bid, field) for field in (
                        'organization_id', 'round_ref', 'draft', 'reservation_refs', 'scope'))
                    or not isinstance(original, ContractorAmendmentSubmissionView)
                    or not isinstance(current, ContractorAmendmentSubmissionView)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or original.bid_ref.key() != bid_ref.key() or current.bid_ref.key() != current_bid.ref.key()
                    or not self._matches_original_command(check.condition, original)
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'package_ref', 'round_ref', 'command_id', 'scope'))
                    or current.organization_id != source['organization_id']
                    or current.package_ref.key() != bid.draft.package_ref.key()
                    or current.round_ref.key() != bid.round_ref.key()):
                raise TaskConflict('Formation reader changes original bid payload, package, round, command or result versions')
            return self._condition_reading(prepared, ref, current_bid.ref.model_copy(deep=True))
        finally:
            prepared.reading.recheck()
            self._check()
            if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Formation reader changed its assembled context, input or source snapshot')


def build_assembled_contractor_formation_command_dispatcher(*, inbox, store, assembler, command_ids,
        select_current, read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the original read_guard once across feedback, queries and queue writes."""
    from integration.task_continuation import build_contractor_formation_command_dispatcher

    reader = ContractorFormationCommandReader(assembler=assembler, command_ids=command_ids, select_current=select_current)
    return _build_protected_bid_command_dispatcher(inbox=inbox, store=store, reader=reader,
        build_dispatcher=build_contractor_formation_command_dispatcher, read_guard=read_guard,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate)


def _build_protected_bid_command_dispatcher(*, inbox, store, reader, build_dispatcher,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Reuse the same protected journal boundary for original A03/A04 readers."""
    from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge

    assembler, action_id = reader.assembler, reader.ACTION_ID
    callbacks = {'read_guard': read_guard, 'validate_relation': validate_relation,
        'project_signal': project_signal, 'prepare': prepare, 'revalidate': revalidate}
    if not all(callable(callback) for callback in callbacks.values()) or assembler.organizations.run_id != store.run_id:
        raise ValueError('Formation recovery requires actual same-run source/authority/journal guard and callbacks')
    declared = {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}

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

    dispatcher = build_dispatcher(inbox=inbox, store=store,
        command_ids=reader.command_ids, read_current=reader, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare_current, revalidate=revalidate_current)
    original_journal, original_registry = dispatcher.journal, dispatcher.journal.registry
    original_revalidate = dispatcher.revalidate

    def check_binding():
        reader._check()
        if (any(module_factory_descriptor(callback, name) != declared[name] for name, callback in callbacks.items())
                or dispatcher.inbox is not inbox or dispatcher.journal is not original_journal
                or original_journal.store is not store or original_journal.registry is not original_registry
                or dispatcher.project_signal is not project_signal or dispatcher.prepare is not prepare_current
                or dispatcher.revalidate is not original_revalidate or dispatcher.action_ids != frozenset({action_id})):
            raise TaskConflict('Formation recovery changed original journal, recipient, sources or callback boundaries')

    def dispatch(*, run_id, organization_id):
        check_binding()
        if run_id != store.run_id or organization_id not in store.organization_ids:
            raise TaskConflict('Formation recovery requires its original run and recipient')
        with read_guard(run_id=run_id, organization_id=organization_id):
            check_binding()
            result = dispatcher(run_id=run_id, organization_id=organization_id)
            check_binding()
            return result

    return ExecutionWaitRecoveryBridge(dispatch=dispatch, dispatcher=dispatcher,
        read_guard=read_guard, check_binding=check_binding, action_id=action_id, role='Contractor')
