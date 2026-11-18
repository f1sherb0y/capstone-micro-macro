"""Read actual Engineer A12 training and independent issuer qualification histories."""
from dataclasses import dataclass

from integration.architect_learning_reader import ArchitectLearningReader, _build_assembled_learning_dispatcher
from integration.engineer_learning_actions import EngineerLearningActionAssembler, validate_engineer_learning_sources
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoveryBindings, EngineerSubmissionRecoverySettings
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.engineer_learning_objects import engineer_learning_types
from src.coordination.engineer_learning_conditions import _CODE, _CODES
from src.coordination.engineer_learning_execution_query import (
    EngineerLearningExecutionQueryRecord, engineer_original_learning_execution_profile,
)
from src.coordination.engineer_learning_applied_feedback import EngineerAppliedFeedbackQueryRecord
from src.coordination.engineer_qualification_conditions import QUALIFICATION_CODE, EngineerQualificationApplicationQueryRecord
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class EngineerLearningCurrentSelection:
    request: RoleContractInvocation
    execution_query: EngineerLearningExecutionQueryRecord | None = None
    applied_feedback_query: EngineerAppliedFeedbackQueryRecord | None = None
    qualification_application_query: EngineerQualificationApplicationQueryRecord | None = None


class EngineerLearningRecoverySettings(EngineerSubmissionRecoverySettings):
    """Original Engineer learning source and policy versions."""
    terminal_execution_enabled: bool = False
    terminal_applied_feedback_enabled: bool = False
    terminal_qualification_enabled: bool = False


@dataclass(frozen=True)
class EngineerLearningRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual current source selection, guard and independent native validation."""


_NAMES = {'ArchitectLearningState': 'EngineerLearningState', 'ArchitectLearningDecision': 'EngineerLearningDecision',
    'ArchitectLearningAssessment': 'EngineerLearningAssessment', 'ArchitectLearningExecution': 'EngineerLearningExecution'}


class EngineerLearningReader(ArchitectLearningReader):
    ACTION_ID = 'ENGINEER-A12'
    ROLE = 'Engineer'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    READER_SCHEMA = 'engineer-learning-reader.v1'
    ASSEMBLER_TYPE = EngineerLearningActionAssembler
    SELECTION_TYPE = EngineerLearningCurrentSelection
    INPUT_ANCHORS = ('strategy_ref',)
    EXECUTION_KIND = 'EngineerLearningExecution'
    EXECUTION_QUERY_TYPE = EngineerLearningExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(engineer_original_learning_execution_profile)
    APPLIED_STATE_KIND = 'EngineerLearningState'
    APPLIED_QUERY_TYPE = EngineerAppliedFeedbackQueryRecord
    QUALIFICATION_CODE = QUALIFICATION_CODE
    QUALIFICATION_QUERY_TYPE = EngineerQualificationApplicationQueryRecord
    VALIDATE_SOURCES = staticmethod(validate_engineer_learning_sources)
    HISTORY_SCHEMAS = {**{_NAMES.get(kind, kind): schema for kind, schema in engineer_learning_types().items()},
        'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord}


def build_assembled_engineer_learning_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    from integration.task_continuation import build_engineer_learning_continuation_dispatcher
    return _build_assembled_learning_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader,
        reader_type=EngineerLearningReader, dispatcher_factory=build_engineer_learning_continuation_dispatcher)
