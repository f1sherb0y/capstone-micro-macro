"""Retain original limited interface checks without professional approval effects."""
from integration.engineer_design_actions import validate_engineer_check_preparation_sources
from integration.engineer_parameter_publication import EngineerParameterPublicationStore
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_design_objects import EngineerDesignCheckPreparation, EngineerResearchCheckResultView
from src.actions.roles.engineer_design import prepare_engineer_interface_check_input
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, EngineerInterfaceReport, check_interface


class EngineerInterfaceCheckPublicationStore(EngineerParameterPublicationStore):
    """Reuse exact original input/proof validation and immutable journal transactions.

    Independent actual source gates apply on save, publish and read. Conflict,
    undetermined and out_of_scope stay intact; no registered method is replayed.
    """
    SCHEMA = 'engineer-interface-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-interface-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-interface-check-batch-publication.v1'
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    RECORDS_TABLE = 'engineer_interface_check_records'
    PUBLICATIONS_TABLE = 'engineer_interface_check_publications'
    PREPARATION_MODEL = EngineerDesignCheckPreparation
    INPUT_MODEL = EngineerInterfaceInput
    REPORT_MODEL = EngineerInterfaceReport
    RESULT_MODEL = EngineerResearchCheckResultView
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_interface_check_input)
    REPLAY = staticmethod(check_interface)

    def _result_matches_input(self, value, original, data):
        return (value.brief_ref == original['task'].brief_ref and value.check_spec_ref == original['spec'].ref
            and value.target_ref == original['target_ref'] and value.input_fact_refs == original['input_fact_refs'])


class EngineerInterfaceCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerInterfaceCheckPublicationStore):
            raise ValueError('Check publication requires its original Engineer A05 interface result store')
        super().__init__(provider=provider, publications=publications)
