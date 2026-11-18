"""Recheck actual Architect training sources without executing the estimator."""
from integration.architect_learning_actions import validate_architect_learning_sources
from integration.qs_training_estimate_validation import QSTrainingEstimateSourceValidator
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningDecisionView, ArchitectLearningStrategyView, architect_learning_schemas,
)
from src.actions.roles.architect_learning import prepare_architect_training_estimate_input


class ArchitectTrainingEstimateSourceValidator(QSTrainingEstimateSourceValidator):
    """Read original actual sources beneath the training publication wrapper.

    Shared preparation checks history, work, participants, authority and output
    requirements. Inherited gates retain exact source/input versions, current
    target read rights, the predeclared estimate/work and execution time. Full
    method proof is separately checked by the publication store. The caller
    holds its actual source/authorization guard; no method or training runs.
    """
    VERSION = 'architect-training-estimate-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A12'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_architect_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_architect_training_estimate_input)
    STRATEGY_MODEL = ArchitectLearningStrategyView
    DECISION_MODEL = ArchitectLearningDecisionView

    def validate_source(self, record, context):
        """Pin this role-specific source validator's implementation binding."""
        return super().validate_source(record, context)
