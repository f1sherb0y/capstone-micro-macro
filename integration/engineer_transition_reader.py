"""Read original/current engineering service sources under the actual host guard."""
from dataclasses import dataclass

from integration.architect_transition_reader import ArchitectTransitionReader, ArchitectTransitionCurrentSelection
from integration.architect_learning_reader import _build_assembled_learning_dispatcher
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.engineer_transition_actions import EngineerTransitionActionAssembler, validate_engineer_transition_sources
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.engineer_transition_objects import engineer_transition_types
from src.coordination.engineer_transition_conditions import _CODE, _CODES
from src.coordination.engineer_transition_execution_query import (
    EngineerTransitionExecutionQueryRecord, engineer_original_transition_execution_profile,
)
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class EngineerTransitionCurrentSelection(ArchitectTransitionCurrentSelection):
    """Actual independent engineering invocation; query routes are registered separately."""
    execution_query: EngineerTransitionExecutionQueryRecord | None = None


class EngineerTransitionRecoverySettings(EngineerSubmissionRecoverySettings):
    """Original engineering transition source and policy versions."""
    terminal_execution_enabled: bool = False


@dataclass(frozen=True)
class EngineerTransitionRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual selector, source guard and native independent engineering validation."""


class EngineerTransitionReader(ArchitectTransitionReader):
    ACTION_ID = 'ENGINEER-A11'
    ROLE = 'Engineer'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    READER_SCHEMA = 'engineer-transition-reader.v1'
    ASSEMBLER_TYPE = EngineerTransitionActionAssembler
    SELECTION_TYPE = EngineerTransitionCurrentSelection
    EXECUTION_QUERY_TYPE = EngineerTransitionExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(engineer_original_transition_execution_profile)
    VALIDATE_SOURCES = staticmethod(validate_engineer_transition_sources)
    HISTORY_SCHEMAS = {**engineer_transition_types(), 'Evidence': EvidenceRecord,
        'Authorization': Authorization, 'FunctionAssignment': RoleAssignment}


def build_assembled_engineer_transition_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.task_continuation import build_engineer_transition_continuation_dispatcher
    return _build_assembled_learning_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader,
        reader_type=EngineerTransitionReader, dispatcher_factory=build_engineer_transition_continuation_dispatcher)
