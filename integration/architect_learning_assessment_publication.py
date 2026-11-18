"""Retain Architect feedback assessments for explicit authorized publication."""
from integration.architect_learning_actions import validate_architect_learning_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningAssessmentView, architect_learning_schemas,
)
from src.actions.roles.architect_learning import prepare_architect_learning_assessment_input
from src.coordination.tasks import TaskConflict
from src.methods.architect_learning import (
    LEARNING_METHOD, ArchitectFeedbackInput, ArchitectFeedbackReport, apply_declared_feedback_rules,
)


class ArchitectLearningAssessmentPublicationStore(QSLearningComparabilityPublicationStore):
    """Reuse immutable journal transactions with explicit Architect authority.

    Reconstruct the original finite-rule input and retained method proof without
    executing the registry method. validate_source(record, current_context)
    must independently check actual sources under the caller's writer guard.
    A saved or published assessment applies no judgment or capability change.
    """
    SCHEMA = 'architect-learning-assessment-record.v1'
    PUBLICATION_SCHEMA = 'architect-learning-assessment-publication.v1'
    ACTION_ID = 'ARCHITECT-A12'
    ROLE = 'Architect'
    METHOD_REF = LEARNING_METHOD
    RECORDS_TABLE = 'architect_learning_assessment_records'
    PUBLICATIONS_TABLE = 'architect_learning_assessment_publications'
    SOURCE_SCHEMAS = staticmethod(architect_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_architect_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_architect_learning_assessment_input)
    EXTRA_FIELDS = frozenset({'dependencies'})
    REQUIRE_EMPTY_COMPARISON = False
    PROJECTION_MODEL = ArchitectLearningAssessmentView
    INPUT_MODEL = ArchitectFeedbackInput
    REPORT_MODEL = ArchitectFeedbackReport
    VERIFY_REPORT = staticmethod(apply_declared_feedback_rules)

    def _matches_projection_identity(self, projection, original, context):
        return (projection.strategy_ref == original['strategy_ref']
            and projection.learning_profile_ref == original['learning_profile_ref']
            and (original['assessment_ref'] is None or projection.ref == original['assessment_ref']))

    def _validate_prepared_dependency(self, prepared, original):
        if (prepared['dependencies'] != {} or original['dependencies'] != {}
                or any(row['ref'] == prepared['projection']['ref'] for row in prepared['source_reading'])):
            raise TaskConflict('Architect assessment cannot substitute dependencies or consume its own future report')


class ArchitectLearningAssessmentPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectLearningAssessmentPublicationStore):
            raise ValueError('Architect assessment provider requires its original Architect publication store')
        super().__init__(provider=provider, publications=publications)
