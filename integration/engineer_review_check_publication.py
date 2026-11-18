"""Retain original A06 reviewer findings for a fresh authorized read token."""
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from integration.engineer_review_actions import validate_engineer_review_check_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_review_objects import (
    EngineerReviewCheckPreparation, EngineerReviewResultView, engineer_review_schemas,
)
from src.actions.roles.engineer_review import prepare_engineer_review_check_input


class EngineerReviewCheckPublicationStore(EngineerInterfaceCheckPublicationStore):
    """Reuse immutable journal and proof gates with separate A06 authorization.

    Caller holds the actual source guard. Independent validation on save,
    publication and read preserves original reviewer independence and sources.
    Conflict/unknown/out-of-scope findings and all original issues stay intact.
    """
    SCHEMA = 'engineer-review-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-review-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-review-check-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A06'
    RECORDS_TABLE = 'engineer_review_check_records'
    PUBLICATIONS_TABLE = 'engineer_review_check_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_review_schemas)
    PREPARATION_MODEL = EngineerReviewCheckPreparation
    RESULT_MODEL = EngineerReviewResultView
    PROJECTION_MODEL = EngineerReviewResultView
    VALIDATE_SOURCES = staticmethod(validate_engineer_review_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_review_check_input)

    def _projection_result(self, projection):
        return projection

    def _result_matches_input(self, value, original, data):
        return (value.review_request_ref == original['request'].ref
            and value.target_ref == original['target'].ref and value.content_sha256 == original['target'].content_sha256
            and value.check_spec_ref == original['spec'].ref and value.requested_use == original['request'].requested_use
            and value.input_fact_refs == original['input_fact_refs'] and value.issue_refs == original['issue_refs']
            and value.author_organization_id == original['task'].organization_id)


class EngineerReviewCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerReviewCheckPublicationStore):
            raise ValueError('Review check publication requires original Engineer A06 result store')
        super().__init__(provider=provider, publications=publications)
