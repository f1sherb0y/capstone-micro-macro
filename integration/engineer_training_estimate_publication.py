"""Persist original Engineer training estimates for explicit publication."""
from integration.engineer_learning_actions import validate_engineer_learning_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_training_estimate_publication import QSTrainingEstimatePublicationStore
from src.actions.contracts.engineer_learning_objects import engineer_learning_schemas
from src.actions.roles.engineer_learning import prepare_engineer_training_estimate_input


class EngineerTrainingEstimatePublicationStore(QSTrainingEstimatePublicationStore):
    """Reuse immutable training evidence with explicit Engineer role bindings.

    Original qualification/work preparation reconstructs the retained input.
    Inherited checks preserve target/work identity, execution time, full method
    proof and formula without registry execution. Independent actual source
    validation is mandatory under the caller's source/authorization guard.
    Saving and publishing approve no investment, training or qualification.
    """
    SCHEMA = 'engineer-training-estimate-record.v1'
    PUBLICATION_SCHEMA = 'engineer-training-estimate-publication.v1'
    ACTION_ID = 'ENGINEER-A12'
    ROLE = 'Engineer'
    RECORDS_TABLE = 'engineer_training_estimate_records'
    PUBLICATIONS_TABLE = 'engineer_training_estimate_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_engineer_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_training_estimate_input)


class EngineerTrainingEstimatePublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerTrainingEstimatePublicationStore):
            raise ValueError('Engineer training publication requires its original Engineer estimate store')
        super().__init__(provider=provider, publications=publications)
