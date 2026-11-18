"""Recheck Engineer work and qualification sources without estimator execution."""
from integration.engineer_learning_actions import validate_engineer_learning_sources
from integration.qs_training_estimate_validation import QSTrainingEstimateSourceValidator
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningDecisionView, EngineerLearningStrategyView, engineer_learning_schemas,
)
from src.actions.roles.engineer_learning import prepare_engineer_training_estimate_input


class EngineerTrainingEstimateSourceValidator(QSTrainingEstimateSourceValidator):
    """Read original actual sources beneath the training publication wrapper.

    Engineer preparation retains qualification holder/issuer/history checks and
    shared work, participant, independent authority and output requirements.
    Inherited gates preserve exact source/input versions, current author/target
    rights, predeclared estimate/work and execution time. The store separately
    checks full method proof. The caller holds its source/authorization guard;
    no registered method, training or qualification update executes here.
    """
    VERSION = 'engineer-training-estimate-source-validator.v1'
    ACTION_ID = 'ENGINEER-A12'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_engineer_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_training_estimate_input)
    STRATEGY_MODEL = EngineerLearningStrategyView
    DECISION_MODEL = EngineerLearningDecisionView

    def validate_source(self, record, context):
        """Pin the Engineer implementation in the original source code binding."""
        return super().validate_source(record, context)
