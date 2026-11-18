"""Retain original A09 revision parameter proofs for authorized publication."""
from integration.engineer_parameter_publication import EngineerParameterPublicationStore
from integration.engineer_change_actions import validate_engineer_change_parameter_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeParameterPreparation, EngineerChangeMethodProjection, engineer_change_schemas,
)
from src.actions.roles.engineer_change import prepare_engineer_change_parameter_input


class EngineerChangeParameterPublicationStore(EngineerParameterPublicationStore):
    """Keep revision parameter records separate from A05 and A09 rechecks.

    Caller holds the actual source guard. Rebuild the original revision issue,
    obligation, own parent, change basis and permitted parameter changes, then
    validate original professional terms, actual work, catalog/value/input and
    current A09 author. Require independent source gates on save, publication
    and read; retain full immutable execution proof and limited findings.
    Publication grants no revision registration, issue closure or use right.
    """
    SCHEMA = 'engineer-change-parameter-record.v1'
    PUBLICATION_SCHEMA = 'engineer-change-parameter-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-change-parameter-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A09'
    RECORDS_TABLE = 'engineer_change_parameter_records'
    PUBLICATIONS_TABLE = 'engineer_change_parameter_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    PREPARATION_MODEL = EngineerChangeParameterPreparation
    PROJECTION_MODEL = EngineerChangeMethodProjection
    VALIDATE_SOURCES = staticmethod(validate_engineer_change_parameter_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_change_parameter_input)


class EngineerChangeParameterPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerChangeParameterPublicationStore):
            raise ValueError('Revision parameter publication requires its original Engineer A09 parameter store')
        super().__init__(provider=provider, publications=publications)
