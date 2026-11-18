"""Recheck Engineer feedback, rules and qualification history without methods."""
from integration.architect_learning_assessment_validation import ArchitectLearningAssessmentSourceValidator
from integration.engineer_learning_actions import validate_engineer_learning_sources
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningAssessmentView, EngineerLearningDecisionView, EngineerLearningStrategyView,
    engineer_learning_schemas,
)
from src.actions.roles.engineer_learning import prepare_engineer_learning_assessment_input


class EngineerLearningAssessmentSourceValidator(ArchitectLearningAssessmentSourceValidator):
    """Reread original actual sources beneath the assessment publication wrapper.

    Engineer input preparation preserves qualification holder/issuer/history
    checks alongside feedback chronology, selected rules and authority. Gates
    retain exact source/input versions, current target rights, the predeclared
    assessment and original author/time identity. Full method proof remains
    independently checked by the publication store. The caller holds its actual
    source/authorization guard; no method or qualification update runs here.
    """
    VERSION = 'engineer-learning-assessment-source-validator.v1'
    ACTION_ID = 'ENGINEER-A12'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_engineer_learning_sources)
    PROJECTION_MODEL = EngineerLearningAssessmentView
    STRATEGY_MODEL = EngineerLearningStrategyView
    DECISION_MODEL = EngineerLearningDecisionView
    ASSESSMENT_KIND = 'EngineerLearningAssessment'
    PREPARE_INPUT = staticmethod(prepare_engineer_learning_assessment_input)

    def validate_source(self, record, context):
        """Pin this Engineer implementation in the original source code binding."""
        return super().validate_source(record, context)
