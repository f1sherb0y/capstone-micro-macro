"""Reread original A08 observation sources without executing a saved check."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_inspection_actions import validate_engineer_inspection_check_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_inspection_objects import (
    EngineerInspectionCheckPreparation, EngineerInspectionResultView, engineer_inspection_schemas,
)
from src.actions.roles.engineer_inspection import prepare_engineer_inspection_check_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD


class EngineerInspectionCheckSourceValidator(EngineerParameterSourceValidator):
    """Read original actual sources beneath every publication wrapper.

    Caller holds its actual source guard. Rebuild original report task/terms,
    applicable design/content, executed observation, required access, actual
    invested work and unresolved issues. Isolate the original observation's
    future result; match its exact original cache and current A08 authority.
    No observation, method, formula replay or assessment executes here.
    """
    VERSION = 'engineer-inspection-check-source-validator.v1'
    ACTION_ID = 'ENGINEER-A08'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_inspection_schemas)
    PREPARATION_MODEL = EngineerInspectionCheckPreparation
    RESULT_MODEL = EngineerInspectionResultView
    PROJECTION_MODEL = EngineerInspectionResultView
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_inspection_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_inspection_check_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.inspection_check_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.inspection_check_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer inspection-check source runtime changed')

    def _projection_result(self, projection):
        return projection

    def _future_result_keys(self, action_input, preparation):
        return {preparation.calculation_ref.key()}

    def _result_matches_input(self, value, original, preparation):
        return (value.applicable_design_ref == original['design'].ref
            and value.design_content_sha256 == original['design'].content_sha256
            and value.check_spec_ref == original['spec'].ref and value.observation_ref == original['observation'].ref
            and value.ref == original['observation'].check_result_ref
            and value.author_organization_id == original['task'].organization_id)

    def validate_source(self, record, context):
        """Bind the A08 specialization and shared source runtime."""
        return super().validate_source(record, context)
