"""Recheck original QS feedback/rules and durable cost-report dependencies."""
from copy import deepcopy
import json

from integration.module_host import module_factory_descriptor
from integration.qs_learning_calculation_validation import QSLearningComparabilitySourceValidator
from integration.qs_learning_error_publication import QSLearningErrorPublicationStore
from src.actions.contracts.common import ActionContext, Reference, ref_type
from src.actions.contracts.qs_learning_objects import (
    QSLearningAssessmentView, QSLearningDecisionView, QSLearningStrategyView, QSComparisonResultView,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_learning import prepare_qs_learning_assessment_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_learning import ArchitectFeedbackInput, LEARNING_METHOD


class QSLearningAssessmentSourceValidator(QSLearningComparabilitySourceValidator):
    """Read the original provider below publication wrappers without methods.

    Noncost feedback needs no error store. Cost feedback must retain the actual
    same-journal error/comparison executions and pass their independent source
    gate before the reports enter the resolver. The caller holds the source and
    authority guard. Validation applies no strategy or feedback history.
    """
    VERSION = 'qs-learning-assessment-source-validator.v1'
    METHOD_REF = LEARNING_METHOD
    PROJECTION_MODEL = QSLearningAssessmentView
    PREPARE_INPUT = staticmethod(prepare_qs_learning_assessment_input)
    REQUIRE_EMPTY_COMPARISON = False

    def __init__(self, *, registry, organizations, provider, macro_version, source_mode, errors=None):
        if errors is not None and (type(errors) is not QSLearningErrorPublicationStore
                or errors.registry is not registry or errors.organizations is not organizations
                or errors.store.run_id != organizations.run_id
                or errors.comparisons.store is not errors.store
                or errors.comparisons.registry is not registry
                or errors.comparisons.organizations is not organizations
                or errors.comparisons.methods is not errors.methods):
            raise ValueError('Assessment source validation requires original same-journal cost report stores')
        self.errors = errors
        self._error_components = None if errors is None else self._dependency_components()
        self._source_gates = None if errors is None else (errors.validate_source, errors.comparisons.validate_source)
        super().__init__(registry=registry, organizations=organizations, provider=provider,
            macro_version=macro_version, source_mode=source_mode)
        if errors is not None:
            self._declared['dependency_code'] = self._dependency_code()

    def _dependency_components(self):
        errors = self.errors
        comparisons = errors.comparisons
        return (errors, errors.store, errors.registry, errors.methods, errors.organizations,
            comparisons, comparisons.store, comparisons.registry, comparisons.methods, comparisons.organizations)

    def _dependency_code(self):
        return [module_factory_descriptor(callback, name) for store, prefix in
            ((self.errors, 'QS.original_error'), (self.errors.comparisons, 'QS.original_comparison'))
            for callback, name in ((store._validate, prefix + '_validation'),
                (store.validate_source, prefix + '_source'))]

    def _check(self):
        super()._check()
        if self._error_components is None:
            if self.errors is not None:
                raise TaskConflict('Assessment source validation substituted its absent cost report stores')
        elif (self.errors is None or any(actual is not original for actual, original in
                zip(self._dependency_components(), self._error_components))
                or (self.errors.validate_source, self.errors.comparisons.validate_source) != self._source_gates
                or self._dependency_code() != self._declared['dependency_code']):
            raise TaskConflict('Assessment source validation changed original cost stores or source gates')

    def _build_resolver(self, context, action_input):
        self._check()
        actual = self._views.assemble(context, self.ACTION_ID, 'QS')
        sources = {row.ref.key(): row.value for row in actual.objects}
        strategy = sources.get(action_input.strategy_ref.key())
        if not isinstance(strategy, QSLearningStrategyView):
            raise TaskConflict('Assessment source validation lacks its original current QS strategy')
        decision = sources.get(strategy.decision_profile_ref.key())
        if not isinstance(decision, QSLearningDecisionView):
            raise TaskConflict('Assessment source validation lacks its original current QS decision')
        if (decision.choice == 'update_judgment' and (action_input.forecast_refs or action_input.outcome_refs)
                and action_input.comparability_result_ref is not None and decision.error_result_ref is not None):
            if self.errors is None:
                raise TaskConflict('Cost assessment requires independently saved original error/comparison executions')
            dependencies = {}
            error_record = None
            for name, ref, store in (
                    ('error_dependency', decision.error_result_ref, self.errors),
                    ('comparison_dependency', action_input.comparability_result_ref, self.errors.comparisons)):
                key = task_digest([context.run_id, self.ACTION_ID, ref.model_dump(mode='json')])
                with store.store._lock:
                    raw = store.store._db.execute(
                        f'SELECT record FROM {store.RECORDS_TABLE} WHERE ref_key=?', (key,)).fetchone()
                if raw is None:
                    raise TaskConflict('Assessment dependency lacks its original durable cost report execution')
                record = json.loads(raw[0])
                original, projection = store._validate(record)
                if (projection.ref != ref or record['organization_id'] != actual.organization_id
                        or any(getattr(original, field) != getattr(context, field) for field in
                            ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                        or original.business_time.clock_ref != context.business_time.clock_ref
                        or original.business_time.offset > context.business_time.offset
                        or ref.key() in sources and sources[ref.key()] != projection):
                    raise TaskConflict('Assessment dependency substitutes original report, author, scope or source version')
                dependencies[name] = projection
                sources[ref.key()] = projection
                if name == 'error_dependency':
                    error_record = record
            if (error_record['prepared']['comparison_dependency']
                    != dependencies['comparison_dependency'].model_dump(mode='json')):
                raise TaskConflict('Assessment combines an original error with another comparable report')
            # The error gate independently rechecks its comparison gate as well.
            if self.errors.validate_source(deepcopy(error_record), context.model_copy(deep=True)) is not True:
                raise TaskConflict('Assessment error/comparison dependencies lost their actual current sources')
        resolver = ReferenceResolver(context.run_id, source_mode=self._views.source_mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for key, projection in sources.items():
            ref = Reference(kind=key[0], id=key[1], version=key[2])
            resolver.register_projection(ref, projection)
            refs.append(ref)
        resolver.freeze_read(context.read_token, refs)
        self._check()
        return resolver

    def _matches_projection_identity(self, projection, action_input):
        return (projection.strategy_ref == action_input.strategy_ref
            and projection.learning_profile_ref == action_input.learning_profile_ref)

    def validate_source(self, record, context):
        """Pin this validator's own implementation in the original code binding."""
        return super().validate_source(record, context)

    def _validate_dependencies(self, dependencies, expected, reading):
        if (not isinstance(dependencies, dict)
                or set(dependencies) not in (set(), {'comparison_dependency', 'error_dependency'})):
            raise TaskConflict('Assessment source validation changes its closed report dependency schema')
        dependencies = {name: QSComparisonResultView.model_validate(row) for name, row in dependencies.items()}
        if dependencies != expected or any(reading.resolve(row.ref) != row for row in dependencies.values()):
            raise TaskConflict('Assessment source validation substitutes its original required cost reports')

    def validate_current(self, *, context, action_input, assessment_input, assessment_ref, dependencies, reading):
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Assessment production changed its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        current, original_input, fresh, data = self._reading(context, action_input, reading.evidence())
        target = ref_type('QSLearningAssessment').model_validate(assessment_ref)
        grants = self.organizations.grants(current, self.ACTION_ID, 'QS')
        if (data != ArchitectFeedbackInput.model_validate(assessment_input)
                or fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)):
            raise TaskConflict('Assessment production changes original feedback/rules or target read authority')
        prepared = self.PREPARE_INPUT(current, original_input, fresh)
        if (prepared['assessment_ref'] is not None and prepared['assessment_ref'] != target
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Assessment production changes its predeclared target or replaces a supplied report')
        self._validate_dependencies(dependencies, prepared['dependencies'], fresh)
        if reading.method_evidence() or fresh.method_evidence():
            raise TaskConflict('Assessment source validation must not execute learning or cost methods')
        fresh.recheck()
        reading.recheck()
        self._check()

    def _validate_dependency(self, record, reading):
        current = reading._context
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = self.PREPARE_INPUT(current, action_input, reading)
        if prepared['kind'] != 'prepared':
            raise TaskConflict('Saved assessment lost its original feedback/rule input')
        target = QSLearningAssessmentView.model_validate(record['prepared']['projection']).ref
        if (prepared['assessment_ref'] is not None and prepared['assessment_ref'] != target
                or any(row['ref'] == target.model_dump(mode='json') for row in record['prepared']['source_reading'])):
            raise TaskConflict('Saved assessment changes its predeclared target or consumes its own future report')
        self._validate_dependencies(record['prepared']['dependencies'], prepared['dependencies'], reading)
        if reading.method_evidence():
            raise TaskConflict('Saved assessment source validation executed a registered method')
        reading.recheck()
        self._check()
