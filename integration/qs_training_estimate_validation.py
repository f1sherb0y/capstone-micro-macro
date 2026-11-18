"""Recheck actual QS training sources without replaying their estimate method."""
from integration.qs_learning_calculation_validation import QSLearningComparabilitySourceValidator
from src.actions.contracts.architect_learning_objects import ArchitectTrainingEstimateView, ArchitectTrainingProfileView
from src.actions.contracts.common import ref_type
from src.actions.contracts.qs_learning_objects import QSLearningDecisionView, QSLearningStrategyView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_learning import prepare_qs_training_estimate_input
from src.coordination.tasks import TaskConflict
from src.methods.architect_learning import ArchitectTrainingInput, TRAINING_METHOD


class QSTrainingEstimateSourceValidator(QSLearningComparabilitySourceValidator):
    """Read the original provider below the training publication wrapper.

    Shared preparation checks actual history, feedback, sourced work,
    participants, independent authority and output requirements. Exact source
    versions and target identity must survive save, publication and read. The
    caller holds the source/authorization guard. No estimate, investment or
    training method executes here and no capability or history is changed.
    """
    VERSION = 'qs-training-estimate-source-validator.v1'
    METHOD_REF = TRAINING_METHOD
    PROJECTION_MODEL = ArchitectTrainingEstimateView
    STRATEGY_MODEL = QSLearningStrategyView
    DECISION_MODEL = QSLearningDecisionView
    PREPARE_INPUT = staticmethod(prepare_qs_training_estimate_input)
    REQUIRE_EMPTY_COMPARISON = False

    def _matches_projection_identity(self, projection, action_input):
        return projection.author_action_id == self.ACTION_ID and projection.scope == action_input.scope

    def _matches_projection_input(self, projection, data):
        # Full typed input is retained in method_execution, not on this view.
        return projection.work_profile_ref == data.work_profile_ref

    def _validate_target(self, action_input, target, work_ref, reading):
        strategy = reading.resolve(action_input.strategy_ref)
        if not isinstance(strategy, self.STRATEGY_MODEL):
            raise TaskConflict('Training source validation lacks its original role strategy')
        decision = reading.resolve(strategy.decision_profile_ref)
        if (not isinstance(decision, self.DECISION_MODEL) or decision.choice != 'propose_training'
                or decision.training_profile_ref is None):
            raise TaskConflict('Training source validation lacks its original training proposal decision')
        training = reading.resolve(decision.training_profile_ref)
        if (not isinstance(training, ArchitectTrainingProfileView)
                or training.estimate_ref != target or training.request.work_profile_ref != work_ref
                or training.organization_id != reading.organization_id
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Training source validation changes its predeclared target/work or consumes its future report')

    def validate_current(self, *, context, action_input, training_input, estimate_ref, reading):
        """Match independently reread originals before the producer's one method call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Training production changed its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        current, original_input, fresh, data = self._reading(context, action_input, reading.evidence())
        target = ref_type('TrainingEstimate').model_validate(estimate_ref)
        grants = self.organizations.grants(current, self.ACTION_ID, self.ROLE)
        if (data != ArchitectTrainingInput.model_validate(training_input)
                or fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Training production changes original work input, target authority or future-report isolation')
        self._validate_target(original_input, target, data.work_profile_ref, fresh)
        if fresh.method_evidence() or reading.method_evidence():
            raise TaskConflict('Training source validation must not execute registered methods')
        fresh.recheck()
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Reuse original cache/author/time/input checks and pin this code binding."""
        return super().validate_source(record, context)

    def _validate_dependency(self, record, reading):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        projection = self.PROJECTION_MODEL.model_validate(record['prepared']['projection'])
        if projection.executed_at != reading._context.business_time:
            raise TaskConflict('Saved training estimate changes its original execution time')
        self._validate_target(action_input, projection.ref, projection.work_profile_ref, reading)
        if reading.method_evidence():
            raise TaskConflict('Saved training source validation executed a registered method')
        reading.recheck()
        self._check()
