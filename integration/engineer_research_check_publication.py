"""Retain original A13 check proofs for separate authorized publication."""
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from integration.engineer_research_actions import validate_engineer_research_check_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchCheckPreparation, EngineerResearchCheckResultView,
    EngineerResearchMethodProjection, engineer_research_schemas,
)
from src.actions.roles.engineer_research import prepare_engineer_research_check_input


class EngineerResearchCheckPublicationStore(EngineerInterfaceCheckPublicationStore):
    """Keep A13 records, authorization and original check associations separate.

    Caller holds the actual source guard. Independent source gates apply on
    save, publication and read. Reconstruct original accepted delegation, actual
    cost/work limits and sourced facts; preserve unknown/conflict/out-of-scope
    findings without creating an assessment or approved professional design.
    """
    SCHEMA = 'engineer-research-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-research-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-research-check-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A13'
    RECORDS_TABLE = 'engineer_research_check_records'
    PUBLICATIONS_TABLE = 'engineer_research_check_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)
    PREPARATION_MODEL = EngineerResearchCheckPreparation
    RESULT_MODEL = EngineerResearchCheckResultView
    PROJECTION_MODEL = EngineerResearchMethodProjection
    VALIDATE_SOURCES = staticmethod(validate_engineer_research_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_research_check_input)

    def _projection_result(self, projection):
        return projection.check

    def _result_matches_input(self, value, original, data):
        return (value.brief_ref == original['brief'].ref and value.check_spec_ref == original['spec'].ref
            and value.target_ref == original['target_ref'] and value.input_fact_refs == original['input_fact_refs'])


class EngineerResearchCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerResearchCheckPublicationStore):
            raise ValueError('Research check publication requires its original Engineer A13 result store')
        super().__init__(provider=provider, publications=publications)
