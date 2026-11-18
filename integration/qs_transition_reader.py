"""Read actual original/current QS transition sources under the host guard."""
from dataclasses import dataclass

from integration.architect_learning_reader import _build_assembled_learning_dispatcher
from integration.architect_transition_reader import ArchitectTransitionReader, ArchitectTransitionCurrentSelection
from integration.qs_payment_reader import QSPaymentRecoverySettings, QSPaymentRecoveryBindings
from integration.qs_transition_actions import QSTransitionActionAssembler, validate_qs_transition_sources
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_transition_objects import qs_transition_types
from src.coordination.qs_transition_conditions import _CODE, _CODES
from src.coordination.qs_transition_execution_query import (
    QSTransitionExecutionQueryRecord, qs_original_transition_execution_profile,
)
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class QSTransitionCurrentSelection(ArchitectTransitionCurrentSelection):
    """Independently selected current QS invocation; only declared waits are accepted."""
    execution_query: QSTransitionExecutionQueryRecord | None = None


class QSTransitionRecoverySettings(QSPaymentRecoverySettings):
    """Original QS service-transition sources and policy versions."""
    terminal_execution_enabled: bool = False


@dataclass(frozen=True)
class QSTransitionRecoveryBindings(QSPaymentRecoveryBindings):
    """Actual source selector, guard and independent native QS validation."""


class QSTransitionReader(ArchitectTransitionReader):
    ACTION_ID = 'QS-A11'
    ROLE = 'QS'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    READER_SCHEMA = 'qs-transition-reader.v1'
    ASSEMBLER_TYPE = QSTransitionActionAssembler
    SELECTION_TYPE = QSTransitionCurrentSelection
    EXECUTION_QUERY_TYPE = QSTransitionExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(qs_original_transition_execution_profile)
    VALIDATE_SOURCES = staticmethod(validate_qs_transition_sources)
    HISTORY_SCHEMAS = {**qs_transition_types(), 'Evidence': EvidenceRecord,
        'Authorization': Authorization, 'FunctionAssignment': RoleAssignment}


def build_assembled_qs_transition_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.task_continuation import build_qs_transition_continuation_dispatcher
    return _build_assembled_learning_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader,
        reader_type=QSTransitionReader, dispatcher_factory=build_qs_transition_continuation_dispatcher)
