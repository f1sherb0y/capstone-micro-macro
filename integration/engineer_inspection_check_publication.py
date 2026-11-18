"""Retain original A08 observation check proofs for authorized publication."""
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from integration.engineer_inspection_actions import validate_engineer_inspection_check_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.engineer_inspection_objects import (
    EngineerInspectionCheckPreparation, EngineerInspectionResultView, engineer_inspection_schemas,
)
from src.actions.roles.engineer_inspection import prepare_engineer_inspection_check_input


class EngineerInspectionCheckPublicationStore(EngineerInterfaceCheckPublicationStore):
    """Keep original A08 records, direct projections and authority separate.

    Caller holds the actual source guard. Independent source gates apply on
    save, publication and read. Reconstruct original design/content, executed
    observation, required site access, actual work and unresolved issues.
    Limited code findings create no observation, zero-defect claim or approval.
    """
    SCHEMA = 'engineer-inspection-check-record.v1'
    PUBLICATION_SCHEMA = 'engineer-inspection-check-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-inspection-check-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A08'
    RECORDS_TABLE = 'engineer_inspection_check_records'
    PUBLICATIONS_TABLE = 'engineer_inspection_check_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_inspection_schemas)
    PREPARATION_MODEL = EngineerInspectionCheckPreparation
    RESULT_MODEL = EngineerInspectionResultView
    PROJECTION_MODEL = EngineerInspectionResultView
    VALIDATE_SOURCES = staticmethod(validate_engineer_inspection_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_inspection_check_input)

    def _projection_result(self, projection):
        return projection

    def _result_matches_input(self, value, original, data):
        return (value.applicable_design_ref == original['design'].ref
            and value.design_content_sha256 == original['design'].content_sha256
            and value.check_spec_ref == original['spec'].ref and value.observation_ref == original['observation'].ref
            and value.ref == original['observation'].check_result_ref
            and value.author_organization_id == original['task'].organization_id)


class EngineerInspectionCheckPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerInspectionCheckPublicationStore):
            raise ValueError('Inspection check publication requires its original Engineer A08 result store')
        super().__init__(provider=provider, publications=publications)
