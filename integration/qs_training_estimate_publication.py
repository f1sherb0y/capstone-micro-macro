"""Retain QS sourced training estimates for explicit authorized publication."""
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
from src.actions.contracts.architect_learning_objects import ArchitectTrainingEstimateView
from src.actions.roles.qs_learning import prepare_qs_training_estimate_input
from src.coordination.tasks import TaskConflict
from src.methods.architect_learning import (
    TRAINING_METHOD, ArchitectTrainingInput, ArchitectTrainingReport, estimate_declared_training,
)


class QSTrainingEstimatePublicationStore(QSLearningComparabilityPublicationStore):
    """Reuse original immutable save/read and fresh-token journal transactions.

    The original authorized sources reconstruct the declared training input;
    retained method proof and the exact formula are checked without registry
    execution. An independent actual-source gate remains mandatory. Saving or
    publishing an estimate approves no investment, training or capability.
    """
    SCHEMA = 'qs-training-estimate-record.v1'
    PUBLICATION_SCHEMA = 'qs-training-estimate-publication.v1'
    METHOD_REF = TRAINING_METHOD
    RECORDS_TABLE = 'qs_training_estimate_records'
    PUBLICATIONS_TABLE = 'qs_training_estimate_publications'
    PREPARE_INPUT = staticmethod(prepare_qs_training_estimate_input)
    REQUIRE_EMPTY_COMPARISON = False
    PROJECTION_MODEL = ArchitectTrainingEstimateView
    INPUT_MODEL = ArchitectTrainingInput
    REPORT_MODEL = ArchitectTrainingReport
    VERIFY_REPORT = staticmethod(estimate_declared_training)

    def _matches_projection_identity(self,projection,original,context):
        return (projection.ref == original['estimate_ref']
            and projection.work_profile_ref == original['work_profile_ref']
            and projection.executed_at == context.business_time)

    def _matches_projection_input(self,projection,data):
        # TrainingEstimate carries the work ref and input SHA, while the exact
        # typed input stays in the retained method execution and source cache.
        return projection.work_profile_ref == data.work_profile_ref

    def _validate_prepared_dependency(self,prepared,original):
        if any(row['ref'] == prepared['projection']['ref'] for row in prepared['source_reading']):
            raise TaskConflict('Training estimate cannot consume or replace its own future target report')


class QSTrainingEstimatePublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications,QSTrainingEstimatePublicationStore):
            raise ValueError('Training estimate provider requires its original QS training publication store')
        super().__init__(provider=provider,publications=publications)
