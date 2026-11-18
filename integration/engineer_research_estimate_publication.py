"""Retain original A13 cost/work estimates with complete execution evidence."""
from integration.engineer_parameter_publication import EngineerParameterPublicationStore
from integration.engineer_research_actions import validate_engineer_research_estimate_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.common import Known, Measured, Money
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchEstimatePreparation, EngineerResearchEstimateView,
    EngineerResearchMethodProjection, engineer_research_schemas,
)
from src.actions.roles.engineer_research import prepare_engineer_research_estimate_input
from src.methods.engineer_research_estimates import (
    ENGINEER_RESEARCH_ESTIMATE_METHOD, EngineerResearchEstimateInput,
    EngineerResearchEstimateReport, estimate_declared_research,
)


class EngineerResearchEstimatePublicationStore(EngineerParameterPublicationStore):
    """Reuse immutable journal transactions with original estimate associations.

    Caller holds the actual source guard. Independent actual source gates apply
    on save, publish and read. Original transport has no result/author-action
    fields: retain cost/work there, the report in the full method execution and
    author action in the original A13 context. Current grants, actor/function,
    task authority and target read permissions remain independently checked.
    """
    SCHEMA = 'engineer-research-estimate-record.v1'
    PUBLICATION_SCHEMA = 'engineer-research-estimate-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-research-estimate-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A13'
    METHOD_REF = ENGINEER_RESEARCH_ESTIMATE_METHOD
    RECORDS_TABLE = 'engineer_research_estimate_records'
    PUBLICATIONS_TABLE = 'engineer_research_estimate_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)
    PREPARATION_MODEL = EngineerResearchEstimatePreparation
    INPUT_MODEL = EngineerResearchEstimateInput
    REPORT_MODEL = EngineerResearchEstimateReport
    RESULT_MODEL = EngineerResearchEstimateView
    PROJECTION_MODEL = EngineerResearchMethodProjection
    INPUT_SHA_FIELD = 'estimate_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_research_estimate_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_research_estimate_input)
    REPLAY = staticmethod(estimate_declared_research)

    def _projection_result(self, projection):
        return projection.estimate

    def _result_matches_input(self, value, original, data):
        request = original['request']
        return (value.ref == request.estimate_ref and value.request_profile_ref == request.ref
            and value.input_refs == request.input_refs and value.work_profile_ref == request.work_profile_ref
            and value.work_profile_ref == data.work_profile_ref
            and value.effort_estimate == request.effort_estimate and value.incremental_cost == request.incremental_cost)

    def _result_matches_report(self, value, report, data):
        return (report.source_refs == data.source_refs
            and value.effort_estimate == Known[Measured](state='known', value=report.effort)
            and value.incremental_cost == Known[Money](state='known', value=report.estimated_cost))

    def _result_author_matches(self, value, context):
        # _grants requires the original A13 context; shared validation also
        # matches the saved actor/function and exact original task authority.
        return context.contract_ref.kind == 'ActionContract' and context.contract_ref.id == self.ACTION_ID


class EngineerResearchEstimatePublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerResearchEstimatePublicationStore):
            raise ValueError('Research estimate publication requires its original Engineer A13 estimate store')
        super().__init__(provider=provider, publications=publications)
