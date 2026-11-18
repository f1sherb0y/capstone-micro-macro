"""Reread original A13 investigation sources without recalculating cost/work."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_research_actions import validate_engineer_research_estimate_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchEstimatePreparation, EngineerResearchEstimateView,
    EngineerResearchMethodProjection, engineer_research_schemas,
)
from src.actions.roles.engineer_research import prepare_engineer_research_estimate_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_research_estimates import ENGINEER_RESEARCH_ESTIMATE_METHOD


class EngineerResearchEstimateSourceValidator(EngineerParameterSourceValidator):
    """Read original actual sources beneath every publication wrapper.

    Caller holds its actual source guard. Rebuild delegated research/request,
    independence, remaining actual cost/work limits and sourced numeric input.
    Retain existing checks and isolate only the future request estimate. Match
    the exact original cache, request values/basis and current author authority;
    full report/execution proof verification remains in the publication store.
    """
    VERSION = 'engineer-research-estimate-source-validator.v1'
    ACTION_ID = 'ENGINEER-A13'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)
    PREPARATION_MODEL = EngineerResearchEstimatePreparation
    RESULT_MODEL = EngineerResearchEstimateView
    PROJECTION_MODEL = EngineerResearchMethodProjection
    METHOD_REF = ENGINEER_RESEARCH_ESTIMATE_METHOD
    INPUT_SHA_FIELD = 'estimate_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_research_estimate_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_research_estimate_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.research_estimate_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.research_estimate_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer research-estimate source runtime changed')

    def _projection_result(self, projection):
        return projection.estimate

    def _future_result_keys(self, action_input, preparation):
        return {preparation.calculation_ref.key()}

    def _result_matches_input(self, value, original, preparation):
        request = original['request']
        return (value.ref == request.estimate_ref and value.request_profile_ref == request.ref
            and value.input_refs == request.input_refs and value.work_profile_ref == request.work_profile_ref
            and value.work_profile_ref == preparation.input.work_profile_ref
            and value.effort_estimate == request.effort_estimate and value.incremental_cost == request.incremental_cost)

    def _result_author_matches(self, value, context):
        # Original estimate transport lacks author_action_id. The shared gate
        # separately matches saved/current action, actor/function, task authority
        # and current actual A13 grant; a missing field creates no permission.
        return context.contract_ref.kind == 'ActionContract' and context.contract_ref.id == self.ACTION_ID

    def validate_source(self, record, context):
        """Bind the A13 estimate specialization and shared source runtime."""
        return super().validate_source(record, context)
