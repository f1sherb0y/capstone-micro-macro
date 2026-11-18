"""Recheck original A06 review sources without executing the saved check again."""
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_review_actions import validate_engineer_review_check_preparation_sources
from integration.module_host import module_factory_descriptor
from src.actions.contracts.engineer_review_objects import (
    EngineerReviewCheckPreparation, EngineerReviewResultView, engineer_review_schemas,
)
from src.actions.roles.engineer_review import prepare_engineer_review_check_input
from src.coordination.tasks import TaskConflict
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD


class EngineerReviewCheckSourceValidator(EngineerParameterSourceValidator):
    """Read the original provider beneath every publication wrapper.

    Caller holds its actual source guard. Rebuild the exact original review
    input, reviewer independence and full open-issue cache while isolating
    future results. Retain the direct A06 result projection and current reviewer
    authority; source validation runs no method or professional assessment.
    """
    VERSION = 'engineer-review-check-source-validator.v1'
    ACTION_ID = 'ENGINEER-A06'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_review_schemas)
    PREPARATION_MODEL = EngineerReviewCheckPreparation
    RESULT_MODEL = EngineerReviewResultView
    PROJECTION_MODEL = EngineerReviewResultView
    METHOD_REF = ENGINEER_INTERFACE_METHOD
    INPUT_SHA_FIELD = 'check_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_review_check_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_review_check_input)

    def __init__(self, **components):
        super().__init__(**components)
        self._declared['source_runtime'] = module_factory_descriptor(
            EngineerParameterSourceValidator.validate_source, 'Engineer.review_check_source_runtime')

    def _check(self):
        super()._check()
        if module_factory_descriptor(EngineerParameterSourceValidator.validate_source,
                'Engineer.review_check_source_runtime') != self._declared['source_runtime']:
            raise TaskConflict('Original Engineer review-check source runtime changed')

    def _projection_result(self, projection):
        return projection

    def _result_matches_input(self, value, original, preparation):
        return (value.review_request_ref == original['request'].ref
            and value.target_ref == original['target'].ref and value.content_sha256 == original['target'].content_sha256
            and value.check_spec_ref == original['spec'].ref and value.requested_use == original['request'].requested_use
            and value.input_fact_refs == original['input_fact_refs'] and value.issue_refs == original['issue_refs']
            and value.author_organization_id == original['task'].organization_id)

    def validate_source(self, record, context):
        """Bind the A06 specialization and inherited runtime to source code."""
        return super().validate_source(record, context)
