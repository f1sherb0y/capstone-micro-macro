"""Reread original A13 research sources without executing the retained check."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_research_actions import validate_engineer_research_check_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchCheckPreparation, EngineerResearchCheckResultView,
    EngineerResearchMethodProjection, engineer_research_schemas,
)
from src.actions.roles.engineer_research import prepare_engineer_research_check_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD


class EngineerResearchCheckSourceValidator(EngineerParameterSourceValidator):
    """Read the original actual provider beneath publication layers.

    Caller holds its actual source guard. Rebuild accepted delegation,
    independence, actual expenditure limits and original target/spec/facts.
    Isolate every future result and match the exact original cache, author and
    current read authority; no method or research assessment executes here.
    """
    VERSION = 'engineer-research-check-source-validator.v1'
    ACTION_ID = 'ENGINEER-A13'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)
    PREPARATION_MODEL = EngineerResearchCheckPreparation
    RESULT_MODEL = EngineerResearchCheckResultView
    PROJECTION_MODEL = EngineerResearchMethodProjection
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_research_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_research_check_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.research_check_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.research_check_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer research-check source runtime changed')

    def _projection_result(self, projection):
        return projection.check

    def _result_matches_input(self, value, original, preparation):
        return (value.brief_ref == original['brief'].ref and value.check_spec_ref == original['spec'].ref
            and value.target_ref == original['target_ref'] and value.input_fact_refs == original['input_fact_refs'])

    def validate_source(self, record, context):
        """Bind the original A13 specialization and shared source runtime."""
        return super().validate_source(record, context)
