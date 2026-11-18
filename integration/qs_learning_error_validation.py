"""Validate error sources against independently retained comparable report proof."""
from copy import deepcopy
import json

from integration.module_host import module_factory_descriptor
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
from integration.qs_learning_calculation_validation import QSLearningComparabilitySourceValidator
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.qs_learning_objects import QSComparisonResultView, QSLearningStrategyView, QSLearningDecisionView
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_learning import prepare_qs_forecast_error_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_learning import ERROR_METHOD


class QSLearningErrorSourceValidator(QSLearningComparabilitySourceValidator):
    """Use the actual original provider beneath both publication wrappers.

    An immutable saved comparison is added to the validation resolver only after
    its original proof and independent current-source gate pass. No comparison
    or error method executes and nothing is saved or published by this validator.
    Caller holds the current actual source/authorization writer guard.
    """
    VERSION = 'qs-learning-error-source-validator.v1'
    METHOD_REF = ERROR_METHOD
    PREPARE_INPUT = staticmethod(prepare_qs_forecast_error_input)
    REQUIRE_EMPTY_COMPARISON = False

    def __init__(self, *, comparisons, registry, organizations, provider, macro_version, source_mode):
        if (type(comparisons) is not QSLearningComparabilityPublicationStore
                or comparisons.registry is not registry or comparisons.organizations is not organizations
                or comparisons.store.run_id != organizations.run_id):
            raise ValueError('Error source validation requires the original durable comparability store')
        self.comparisons = comparisons
        self._comparison_components = (comparisons,comparisons.store,comparisons.registry,
            comparisons.organizations,comparisons.methods)
        self._comparison_source = comparisons.validate_source
        super().__init__(registry=registry,organizations=organizations,provider=provider,
            macro_version=macro_version,source_mode=source_mode)
        self._declared['comparison_validation'] = module_factory_descriptor(comparisons._validate,'QS.original_comparison_validation')
        self._declared['comparison_source'] = module_factory_descriptor(comparisons.validate_source,'QS.original_comparison_source')

    def _check(self):
        super()._check()
        if (any(actual is not original for actual,original in zip(
                (self.comparisons,self.comparisons.store,self.comparisons.registry,
                    self.comparisons.organizations,self.comparisons.methods),self._comparison_components))
                or self.comparisons.validate_source != self._comparison_source
                or module_factory_descriptor(self.comparisons._validate,'QS.original_comparison_validation')
                    != self._declared['comparison_validation']
                or module_factory_descriptor(self.comparisons.validate_source,'QS.original_comparison_source')
                    != self._declared['comparison_source']):
            raise TaskConflict('Error source validation changed its original comparison store or source gate')

    def _build_resolver(self,context,action_input):
        self._check()
        ref = action_input.comparability_result_ref
        if ref is None:
            raise TaskConflict('Error source validation requires its explicit original comparable report')
        actual = self._views.assemble(context,self.ACTION_ID,'QS')
        sources = {row.ref.key():row.value for row in actual.objects}
        key = task_digest([context.run_id,self.ACTION_ID,ref.model_dump(mode='json')])
        with self.comparisons.store._lock:
            raw = self.comparisons.store._db.execute(
                f'SELECT record FROM {self.comparisons.RECORDS_TABLE} WHERE ref_key=?',(key,)).fetchone()
        if raw is None:
            raise TaskConflict('Error source validation requires the independently saved comparison execution')
        record = json.loads(raw[0])
        original,comparison = self.comparisons._validate(record)
        if (record['organization_id'] != actual.organization_id or comparison.ref != ref
                or any(getattr(original,name) != getattr(context,name) for name in
                    ('run_id','actor_id','function_ref','contract_ref','scope','execution_mode'))
                or original.business_time.clock_ref != context.business_time.clock_ref
                or original.business_time.offset > context.business_time.offset
                or any(record['action_input'][name] != action_input.model_dump(mode='json')[name] for name in
                    ('scope','forecast_refs','outcome_refs','feedback_refs','learning_profile_ref','strategy_ref'))
                or ref.key() in sources and sources[ref.key()] != comparison):
            raise TaskConflict('Error source validation substitutes the original comparable report or source invocation')
        if self.comparisons.validate_source(deepcopy(record),context.model_copy(deep=True)) is not True:
            raise TaskConflict('Original comparison lost its independently verified current sources')
        sources[ref.key()] = comparison
        resolver = ReferenceResolver(context.run_id,source_mode=self._views.source_mode,schemas=self.SOURCE_SCHEMAS())
        refs = []
        for key,row in sources.items():
            source_ref = Reference(kind=key[0],id=key[1],version=key[2])
            resolver.register_projection(source_ref,row)
            refs.append(source_ref)
        resolver.freeze_read(context.read_token,refs)
        self._check()
        return resolver

    def validate_current(self, *, context, action_input, comparison_input, calculation_ref,
            comparison_dependency, reading):
        if not isinstance(reading,ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Error production changed its original authorized reading')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        dependency = QSComparisonResultView.model_validate(comparison_dependency)
        if (action_input.comparability_result_ref != dependency.ref
                or Reference.model_validate(calculation_ref) == dependency.ref
                or reading.resolve(dependency.ref) != dependency):
            raise TaskConflict('Error production changes the original saved comparable report dependency')
        self._validate_declared_target(action_input,Reference.model_validate(calculation_ref),reading)
        super().validate_current(context=context,action_input=action_input,comparison_input=comparison_input,
            calculation_ref=calculation_ref,reading=reading)

    def validate_source(self,record,context):
        return super().validate_source(record,context)

    def _validate_declared_target(self,action_input,target,reading):
        strategy = reading.resolve(action_input.strategy_ref)
        if not isinstance(strategy,QSLearningStrategyView):
            raise TaskConflict('Error target validation lacks its original QS strategy')
        decision = reading.resolve(strategy.decision_profile_ref)
        if (not isinstance(decision,QSLearningDecisionView)
                or decision.error_result_ref is not None and decision.error_result_ref != target
                or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
            raise TaskConflict('Error source validation changes its predeclared target or consumes its own future report')

    def _validate_dependency(self,record,reading):
        dependency = QSComparisonResultView.model_validate(record['prepared']['comparison_dependency'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        error = QSComparisonResultView.model_validate(record['prepared']['projection'])
        self._validate_declared_target(action_input,error.ref,reading)
        if (action_input.comparability_result_ref != dependency.ref or reading.resolve(dependency.ref) != dependency
                or dependency.data != error.data or dependency.report != error.report or dependency.ref == error.ref
                or record['organization_id'] != reading.organization_id or reading.method_evidence()):
            raise TaskConflict('Saved error changes its actual original comparison input, dependency or declared report')
        reading.recheck()
        self._check()
