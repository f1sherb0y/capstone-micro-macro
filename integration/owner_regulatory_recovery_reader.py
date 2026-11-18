"""Assemble original A08 event waits with actual native query/disposition sources."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import Field, model_validator

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from integration.owner_regulatory_actions import OwnerRegulatoryActionAssembler, validate_owner_regulatory_sources
from integration.owner_regulatory_results import OwnerRegulatoryResultWorker
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from src.actions.contracts.common import Reference, TextId
from src.actions.contracts.owner_regulatory_objects import OwnerRegulatoryRecoveryDispositionView
from src.actions.roles.owner_regulatory import handle_regulatory
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_regulatory_conditions import (
    FIXED_CODES, QUERY_PREFIX, OwnerRegulatoryConditionReading, owner_original_regulatory_profile, regulatory_wait_kinds,
)
from src.coordination.tasks import TaskConflict, _text


class OwnerRegulatoryRecoverySettings(OwnerContinuationRecoverySettings):
    command_ids: list[TextId] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct_original_commands(self):
        if len(set(self.command_ids)) != len(self.command_ids):
            raise ValueError('Regulatory recovery cannot repeat an original command ID')
        return self


@dataclass(frozen=True)
class OwnerRegulatoryCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current first dependency and a separately issued native disposition, if required."""
    disposition_ref: Reference | None = None


@dataclass(frozen=True)
class OwnerRegulatoryRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerRegulatoryActionAssembler
    snapshots: InvocationSnapshotStore
    command_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (type(self.assembler) is not OwnerRegulatoryActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not isinstance(self.command_ids, tuple)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Regulatory recovery requires its actual assembler, same journal and independent callbacks')
        object.__setattr__(self, '_reader', OwnerRegulatoryRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, command_ids=self.command_ids, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store, self.command_ids)


class OwnerRegulatoryRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A08'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerRegulatoryActionAssembler
    SELECTION_TYPE = OwnerRegulatoryCurrentSelection
    READING_TYPE = OwnerRegulatoryConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_regulatory_profile)
    RESULT_WORKER_TYPE = OwnerRegulatoryResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_regulatory_sources)
    ROOT_FIELD = 'regulatory_requirement_ref'
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'owner-regulatory-event-recovery-reader.v1'
    CONDITION_TRIGGER = 'event'
    _same_scope = staticmethod(same_closeout_scope)

    def __init__(self, *, assembler, snapshots, command_ids=(), select_current):
        if not isinstance(command_ids, (tuple, list)) or len(set(command_ids)) != len(command_ids):
            raise ValueError('Regulatory recovery requires explicit distinct original command IDs')
        for command_id in command_ids:
            _text(command_id)
        self.command_ids = tuple(command_ids)
        self.CONDITION_CODES = (*FIXED_CODES, *(QUERY_PREFIX + command_id for command_id in self.command_ids))
        self.CONDITION_KINDS = {code: regulatory_wait_kinds(code) for code in self.CONDITION_CODES}
        self.CONDITION_REF_KIND_SEQUENCES = deepcopy(self.CONDITION_KINDS)
        super().__init__(assembler=assembler, snapshots=snapshots, select_current=select_current)

    def _components(self):
        return (*super()._components(), handle_regulatory, self.command_ids)

    def _configuration(self):
        result = super()._configuration()
        result['command_ids'] = list(self.command_ids)
        result['regulatory_checks'] = module_factory_descriptor(handle_regulatory, 'regulatory_checks')
        result['condition_reference_kinds'] = module_factory_descriptor(regulatory_wait_kinds, 'condition_reference_kinds')
        return result

    def _condition_reading(self, prepared, original_context, snapshot, ref, selected):
        disposition_ref = selected.disposition_ref
        if disposition_ref is not None:
            if not isinstance(disposition_ref, Reference) or disposition_ref.kind != 'RegulatoryRecoveryDisposition':
                raise TaskConflict('Regulatory recovery requires an explicit typed actual native disposition')
            disposition_ref = disposition_ref.model_copy(deep=True)
            disposition = prepared.reading.resolve(disposition_ref)
            if not isinstance(disposition, OwnerRegulatoryRecoveryDispositionView) or disposition.ref != disposition_ref:
                raise TaskConflict('Regulatory recovery lacks its actual authorized native disposition schema')
        return self.READING_TYPE(prepared.context, prepared.reading, original_context,
            deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'), ref,
            disposition_ref=disposition_ref)


def build_assembled_owner_regulatory_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None, command_ids=None):
    reader = reader or OwnerRegulatoryRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), command_ids=command_ids or (), select_current=select_current)
    if (not isinstance(reader, OwnerRegulatoryRecoveryReader)
            or command_ids is not None and tuple(command_ids) != reader.command_ids):
        raise ValueError('Regulatory recovery requires its original same-journal reader and command selection')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
