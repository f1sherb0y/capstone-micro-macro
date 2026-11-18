"""Persist Engineer finite-feedback assessments for explicit publication."""
from integration.architect_learning_assessment_publication import ArchitectLearningAssessmentPublicationStore
from integration.engineer_learning_actions import validate_engineer_learning_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_learning_objects import EngineerLearningAssessmentView, engineer_learning_schemas
from src.actions.roles.engineer_learning import prepare_engineer_learning_assessment_input


class EngineerLearningAssessmentPublicationStore(ArchitectLearningAssessmentPublicationStore):
    """Reuse immutable assessment transactions with original Engineer bindings.

    Input reconstruction retains Engineer qualification checks. Inherited gates
    check predeclared target, strategy/profile, current author/read authority,
    complete method proof and the declared rule formula without registry calls.
    validate_source must independently check actual sources under the caller's
    source/authority guard. No judgment, qualification or capability is changed.
    """
    SCHEMA = 'engineer-learning-assessment-record.v1'
    PUBLICATION_SCHEMA = 'engineer-learning-assessment-publication.v1'
    ACTION_ID = 'ENGINEER-A12'
    ROLE = 'Engineer'
    RECORDS_TABLE = 'engineer_learning_assessment_records'
    PUBLICATIONS_TABLE = 'engineer_learning_assessment_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_engineer_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_learning_assessment_input)
    PROJECTION_MODEL = EngineerLearningAssessmentView


class EngineerLearningAssessmentPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerLearningAssessmentPublicationStore):
            raise ValueError('Engineer assessment publication requires its original Engineer store')
        super().__init__(provider=provider, publications=publications)
