"""Reread original A09 revision sources without executing retained checks."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_change_actions import validate_engineer_change_revision_check_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeRevisionCheckPreparation, EngineerChangeCheckResultView,
    EngineerChangeMethodProjection, engineer_change_schemas,
)
from src.actions.roles.engineer_change import prepare_engineer_change_revision_check_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD


class EngineerChangeRevisionCheckSourceValidator(EngineerParameterSourceValidator):
    """Read original actual sources beneath every publication wrapper.

    Caller holds the actual source guard. Rebuild the authorized revision,
    original issue/obligation, own parent/content, instruction and change basis,
    permitted parameter changes and affected dependencies. Recheck professional
    task/terms, actual work, declared spec/result mapping, scope and input facts.
    Isolate all future method results and match the exact original source cache,
    parent-option target and current A09 author. No formula, revision, result
    production, registration, issue closure or obligation discharge runs here.
    """
    VERSION = 'engineer-change-revision-check-source-validator.v1'
    ACTION_ID = 'ENGINEER-A09'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)
    PREPARATION_MODEL = EngineerChangeRevisionCheckPreparation
    RESULT_MODEL = EngineerChangeCheckResultView
    PROJECTION_MODEL = EngineerChangeMethodProjection
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_change_revision_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_change_revision_check_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.change_revision_check_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.change_revision_check_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer revision-check source runtime changed')

    def _result_matches_input(self, value, original, preparation):
        return (value.issue_ref == original['issue'].ref
            and value.original_content_sha256 == original['original'].content_sha256
            and value.target_ref == original['target_ref']
            and value.target_ref == original['original'].option_ref
            and value.brief_ref == original['original'].brief_ref
            and value.check_spec_ref == original['spec'].ref
            and value.input_fact_refs == original['input_fact_refs'])

    def validate_source(self, record, context):
        """Bind the original revision specialization and shared source runtime."""
        return super().validate_source(record, context)
