"""Persist original Architect training estimates for explicit publication."""
from integration.architect_learning_actions import validate_architect_learning_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_training_estimate_publication import QSTrainingEstimatePublicationStore
from src.actions.contracts.architect_learning_objects import architect_learning_schemas
from src.actions.roles.architect_learning import prepare_architect_training_estimate_input


class ArchitectTrainingEstimatePublicationStore(QSTrainingEstimatePublicationStore):
    """Reuse immutable training evidence with explicit Architect role bindings.

    The inherited training checks retain the original work, predeclared target,
    execution time, complete method proof and formula. The independent actual
    source validator must succeed under the caller's source/authority guard.
    Saving and publishing approve no investment, training or capability change.
    """
    SCHEMA = 'architect-training-estimate-record.v1'
    PUBLICATION_SCHEMA = 'architect-training-estimate-publication.v1'
    ACTION_ID = 'ARCHITECT-A12'
    ROLE = 'Architect'
    RECORDS_TABLE = 'architect_training_estimate_records'
    PUBLICATIONS_TABLE = 'architect_training_estimate_publications'
    SOURCE_SCHEMAS = staticmethod(architect_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_architect_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_architect_training_estimate_input)


class ArchitectTrainingEstimatePublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectTrainingEstimatePublicationStore):
            raise ValueError('Architect training publication requires its original Architect estimate store')
        super().__init__(provider=provider, publications=publications)
