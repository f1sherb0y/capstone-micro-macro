"""Recheck actual Architect feedback and rules without executing their method."""
from integration.architect_learning_actions import validate_architect_learning_sources
from integration.qs_learning_calculation_validation import QSLearningComparabilitySourceValidator
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningAssessmentView, ArchitectLearningDecisionView, ArchitectLearningStrategyView,
    architect_learning_schemas,
)
from src.actions.contracts.common import ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_learning import prepare_architect_learning_assessment_input
from src.coordination.tasks import TaskConflict
from src.methods.architect_learning import ArchitectFeedbackInput, LEARNING_METHOD


class ArchitectLearningAssessmentSourceValidator(QSLearningComparabilitySourceValidator):
    """Reread the original provider beneath the assessment publication wrapper.

    Shared preparation checks original history, feedback chronology, rules and
    authority. Exact input and source versions must survive production, save,
    publication and read under the caller's actual source/authorization guard.
    No registered method executes and no strategy or feedback is applied here.
    """
    VERSION = 'architect-learning-assessment-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A12'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_architect_learning_sources)
    METHOD_REF = LEARNING_METHOD
    PROJECTION_MODEL = ArchitectLearningAssessmentView
    STRATEGY_MODEL = ArchitectLearningStrategyView
    DECISION_MODEL = ArchitectLearningDecisionView
    ASSESSMENT_KIND = 'ArchitectLearningAssessment'
    PREPARE_INPUT = staticmethod(prepare_architect_learning_assessment_input)
    REQUIRE_EMPTY_COMPARISON = False

    def _matches_projection_identity(self, projection, action_input):
        return (projection.strategy_ref == action_input.strategy_ref
            and projection.learning_profile_ref == action_input.learning_profile_ref
            and projection.author_action_id == self.ACTION_ID and projection.scope == action_input.scope)

    def _validate_target(self, action_input, target, dependencies, reading):
        strategy = reading.resolve(action_input.strategy_ref)
        if not isinstance(strategy, self.STRATEGY_MODEL):
            raise TaskConflict('Learning assessment lacks its original current role strategy')
        decision = reading.resolve(strategy.decision_profile_ref)
        if (not isinstance(decision, self.DECISION_MODEL) or decision.choice != 'update_judgment'
                or decision.strategy_ref != strategy.ref
                or decision.organization_id != reading.organization_id
                or decision.assessment_ref is not None and decision.assessment_ref != target
                or dependencies != {}
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Architect assessment changes its predeclared target/dependencies or consumes its future report')

    def validate_current(self, *, context, action_input, assessment_input, assessment_ref, dependencies, reading):
        """Independently match actual sources before the producer's one method call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Architect assessment production changed its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        current, original_input, fresh, data = self._reading(context, action_input, reading.evidence())
        target = ref_type(self.ASSESSMENT_KIND).model_validate(assessment_ref)
        grants = self.organizations.grants(current, self.ACTION_ID, self.ROLE)
        if (data != ArchitectFeedbackInput.model_validate(assessment_input)
                or fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Architect assessment changes original feedback/rules or target read authority')
        self._validate_target(original_input, target, dependencies, fresh)
        if reading.method_evidence() or fresh.method_evidence():
            raise TaskConflict('Architect assessment source validation must not execute registered methods')
        fresh.recheck()
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Pin this code binding and reuse saved source/input/author/time checks."""
        return super().validate_source(record, context)

    def _validate_dependency(self, record, reading):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        projection = self.PROJECTION_MODEL.model_validate(record['prepared']['projection'])
        self._validate_target(action_input, projection.ref, record['prepared']['dependencies'], reading)
        if reading.method_evidence():
            raise TaskConflict('Saved Architect assessment source validation executed a registered method')
        reading.recheck()
        self._check()
