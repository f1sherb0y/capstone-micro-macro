"""Retain original A09 revision interface proofs for fresh-token publication."""
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from integration.engineer_change_actions import validate_engineer_change_revision_check_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeRevisionCheckPreparation, EngineerChangeCheckResultView,
    EngineerChangeMethodProjection, engineer_change_schemas,
)
from src.actions.roles.engineer_change import prepare_engineer_change_revision_check_input


class EngineerChangeRevisionCheckPublicationStore(EngineerInterfaceCheckPublicationStore):
    """Keep revision checks separate from parameters and deliverable rechecks.

    Caller holds its actual source guard. Rebuild the authorized revision,
    issue/content, own parent, instruction, basis and affected dependencies;
    recheck professional task/terms, actual work, spec, mapping and input facts.
    Retain full immutable execution proofs with current A09 author identity.
    Independent source gates apply on save, publication and read. Limited
    findings grant no revision registration, professional approval or use right.
    """
    SCHEMA = 'engineer-change-revision-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-change-revision-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-change-revision-check-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A09'
    RECORDS_TABLE = 'engineer_change_revision_check_records'
    PUBLICATIONS_TABLE = 'engineer_change_revision_check_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    PREPARATION_MODEL = EngineerChangeRevisionCheckPreparation
    RESULT_MODEL = EngineerChangeCheckResultView
    PROJECTION_MODEL = EngineerChangeMethodProjection
    VALIDATE_SOURCES = staticmethod(validate_engineer_change_revision_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_change_revision_check_input)

    def _result_matches_input(self, value, original, data):
        return (value.issue_ref == original['issue'].ref
            and value.original_content_sha256 == original['original'].content_sha256
            and value.target_ref == original['target_ref']
            and value.target_ref == original['original'].option_ref
            and value.brief_ref == original['original'].brief_ref
            and value.check_spec_ref == original['spec'].ref
            and value.input_fact_refs == original['input_fact_refs'])


class EngineerChangeRevisionCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerChangeRevisionCheckPublicationStore):
            raise ValueError('Revision check publication requires its original Engineer A09 revision-check store')
        super().__init__(provider=provider, publications=publications)
