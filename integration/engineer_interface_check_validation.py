"""Recheck original A05 check task/facts without repeating interface arithmetic."""
from integration.engineer_design_actions import validate_engineer_check_preparation_sources
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_design_objects import EngineerDesignCheckPreparation, EngineerResearchCheckResultView
from src.actions.roles.engineer_design import prepare_engineer_interface_check_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD


class EngineerInterfaceCheckSourceValidator(EngineerParameterSourceValidator):
    """Reuse exact cache/source gates with the original check/spec/fact associations.

    Caller holds its actual source guard. Reads original provider versions beneath
    publication; excludes every future MethodResult. Unknown facts remain unknown
    and no code rule, professional finding or registered method executes here.
    """
    VERSION = 'engineer-interface-check-source-validator.v1'
    PREPARATION_MODEL = EngineerDesignCheckPreparation
    RESULT_MODEL = EngineerResearchCheckResultView
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_interface_check_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.check_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.check_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer interface-check source runtime changed')

    def _result_matches_input(self, value, original, preparation):
        return (value.brief_ref == original['task'].brief_ref and value.check_spec_ref == original['spec'].ref
            and value.target_ref == original['target_ref'] and value.input_fact_refs == original['input_fact_refs'])

    def validate_source(self, record, context):
        """Bind the check specialization and inherited runtime to their source code."""
        return super().validate_source(record, context)
