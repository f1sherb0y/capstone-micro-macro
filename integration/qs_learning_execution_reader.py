"""Read original QS-A12 execution, training and feedback waits through the protected learning reader."""
from integration.architect_learning_reader import ArchitectLearningReader
from integration.qs_learning_actions import QSLearningActionAssembler, validate_qs_learning_sources
from integration.qs_learning_reader import QSLearningCurrentSelection
from src.actions.contracts.qs_learning_objects import qs_learning_types
from src.actions.contracts.common import EvidenceRecord
from src.coordination.qs_learning_execution_query import (
    EXECUTION_CODE, QSLearningExecutionQueryRecord, qs_original_learning_execution_profile,
)
from src.coordination.architect_learning_conditions import _CODE, _CAPACITY_CODE
from src.coordination.qs_learning_applied_feedback import APPLIED_CODE, JUDGMENT_CODE, QSAppliedFeedbackQueryRecord
from src.organization.models import Authorization, RoleAssignment


_NAMES = {'ArchitectLearningState': 'QSLearningState', 'ArchitectLearningDecision': 'QSLearningDecision',
    'ArchitectLearningAssessment': 'QSLearningAssessment', 'ArchitectLearningExecution': 'QSLearningExecution'}


class QSLearningExecutionReader(ArchitectLearningReader):
    ACTION_ID = 'QS-A12'
    ROLE = 'QS'
    CONDITION_CODE = EXECUTION_CODE
    CONDITION_CODES = (EXECUTION_CODE, _CODE, _CAPACITY_CODE, APPLIED_CODE, JUDGMENT_CODE)
    READER_SCHEMA = 'qs-learning-execution-reader.v1'
    ASSEMBLER_TYPE = QSLearningActionAssembler
    SELECTION_TYPE = QSLearningCurrentSelection
    INPUT_ANCHORS = ('strategy_ref',)
    EXECUTION_KIND = 'QSLearningExecution'
    EXECUTION_QUERY_TYPE = QSLearningExecutionQueryRecord
    EXECUTION_PROFILE_FACTORY = staticmethod(qs_original_learning_execution_profile)
    APPLIED_STATE_KIND = 'QSLearningState'
    APPLIED_QUERY_TYPE = QSAppliedFeedbackQueryRecord
    VALIDATE_SOURCES = staticmethod(validate_qs_learning_sources)
    HISTORY_SCHEMAS = {**{_NAMES.get(kind, kind): schema for kind, schema in qs_learning_types().items()},
        'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord}
