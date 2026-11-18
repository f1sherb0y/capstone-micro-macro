"""Retain original A09 issue/version recheck proofs for authorized publication."""
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from integration.engineer_change_actions import validate_engineer_change_check_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeCheckPreparation, EngineerChangeCheckResultView,
    EngineerChangeMethodProjection, engineer_change_schemas,
)
from src.actions.roles.engineer_change import prepare_engineer_change_check_input


class EngineerChangeCheckPublicationStore(EngineerInterfaceCheckPublicationStore):
    """Keep A09 records, original issue/content and current authority separate.

    Caller holds the actual source guard. Independent source gates apply on
    save, publication and read. Reconstruct original obligation, reassessment
    task, required independence, actual work and versioned facts. Retain limited
    findings without issue closure, obligation discharge or use permission.
    """
    SCHEMA = 'engineer-change-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-change-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-change-check-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A09'
    RECORDS_TABLE = 'engineer_change_check_records'
    PUBLICATIONS_TABLE = 'engineer_change_check_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    PREPARATION_MODEL = EngineerChangeCheckPreparation
    RESULT_MODEL = EngineerChangeCheckResultView
    PROJECTION_MODEL = EngineerChangeMethodProjection
    VALIDATE_SOURCES = staticmethod(validate_engineer_change_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_change_check_input)

    def _result_matches_input(self, value, original, data):
        return (value.issue_ref == original['issue'].ref
            and value.original_content_sha256 == original['original'].content_sha256
            and value.target_ref == original['original'].ref and value.brief_ref == original['original'].brief_ref
            and value.check_spec_ref == original['spec'].ref and value.input_fact_refs == original['input_fact_refs'])


class EngineerChangeCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerChangeCheckPublicationStore):
            raise ValueError('Change check publication requires its original Engineer A09 result store')
        super().__init__(provider=provider, publications=publications)
