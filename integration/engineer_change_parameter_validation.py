"""Reread original A09 revision sources without calculating saved parameters."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_change_actions import validate_engineer_change_parameter_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeParameterPreparation, EngineerChangeMethodProjection, engineer_change_schemas,
)
from src.actions.contracts.engineer_design_objects import EngineerParameterResultView
from src.actions.roles.engineer_change import prepare_engineer_change_parameter_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_parameters import PARAMETER_METHOD


class EngineerChangeParameterSourceValidator(EngineerParameterSourceValidator):
    """Read original actual sources beneath every publication wrapper.

    Caller holds its actual source guard. Rebuild original issue, obligation,
    own parent/content, instruction and change basis, permitted parameter
    changes and affected dependencies. Recheck original professional task,
    accepted terms, actual work, catalog/value/input and current A09 authority.
    Isolate all future method results and compare the exact source cache.
    No parameter formula, revision, registration or issue closure executes here.
    """
    VERSION = 'engineer-change-parameter-source-validator.v1'
    ACTION_ID = 'ENGINEER-A09'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    PREPARATION_MODEL = EngineerChangeParameterPreparation
    RESULT_MODEL = EngineerParameterResultView
    PROJECTION_MODEL = EngineerChangeMethodProjection
    METHOD_REF = PARAMETER_METHOD
    INPUT_SHA_FIELD = 'parameter_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_change_parameter_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_change_parameter_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.change_parameter_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.change_parameter_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer revision parameter source runtime changed')

    def validate_source(self, record, context):
        """Bind the original A09 specialization and shared source runtime."""
        return super().validate_source(record, context)
