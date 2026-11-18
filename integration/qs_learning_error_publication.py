"""Retain QS-A12 errors with original durable comparability execution dependencies."""
import json

from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_learning_objects import QSComparisonResultView
from src.actions.roles.qs_learning import prepare_qs_forecast_error_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_learning import ERROR_METHOD, QSForecastComparisonInput


class QSLearningErrorPublicationStore(QSLearningComparabilityPublicationStore):
    """Save error proof without rerunning error/comparability registered methods.

    The same-journal original comparison must have the exact original input,
    sources and independently retained execution proof. An actual current source
    gate remains mandatory under the caller's source/authorization writer guard.
    """
    SCHEMA = 'qs-learning-error-record.v1'
    PUBLICATION_SCHEMA = 'qs-learning-error-publication.v1'
    METHOD_REF = ERROR_METHOD
    RECORDS_TABLE = 'qs_learning_error_records'
    PUBLICATIONS_TABLE = 'qs_learning_error_publications'
    PREPARE_INPUT = staticmethod(prepare_qs_forecast_error_input)
    EXTRA_FIELDS = frozenset({'comparison_dependency'})
    REQUIRE_EMPTY_COMPARISON = False

    def __init__(self, *, comparisons, store, registry, methods, organizations, validate_source):
        if (type(comparisons) is not QSLearningComparabilityPublicationStore
                or comparisons.store is not store or comparisons.registry is not registry
                or comparisons.methods is not methods or comparisons.organizations is not organizations):
            raise ValueError('Error persistence requires the original same-journal comparability store')
        self.comparisons = comparisons
        super().__init__(store=store,registry=registry,methods=methods,
            organizations=organizations,validate_source=validate_source)

    def _validate_prepared_dependency(self,prepared,original):
        dependency = original['comparison_dependency']
        if (prepared['comparison_dependency'] != dependency.model_dump(mode='json')
                or any(row['ref'] == prepared['projection']['ref'] for row in prepared['source_reading'])):
            raise TaskConflict('Error persistence substitutes its dependency or replaces a supplied target report')

    def _matches_projection_identity(self,projection,original,context):
        return (super()._matches_projection_identity(projection,original,context)
            and (original['error_result_ref'] is None or projection.ref == original['error_result_ref']))

    def _validate_comparison(self,record):
        """Recheck actual saved comparison rows, including inside journal transactions."""
        if (self.comparisons.store is not self.store or self.comparisons.registry is not self.registry
                or self.comparisons.methods is not self.methods or self.comparisons.organizations is not self.organizations):
            raise TaskConflict('Error persistence changed its original comparability store components')
        sources = {Reference.model_validate(row['ref']).key():row for row in record['prepared']['source_reading']}
        dependency = QSComparisonResultView.model_validate(record['prepared']['comparison_dependency'])
        if (record['action_input']['comparability_result_ref'] != dependency.ref.model_dump(mode='json')
                or sources.get(dependency.ref.key(),{}).get('projection') != dependency.model_dump(mode='json')
                or dependency.ref.model_dump(mode='json') == record['prepared']['projection']['ref']):
            raise TaskConflict('Error record omits or replaces the original comparison cache dependency')
        key = task_digest([self.store.run_id,self.ACTION_ID,dependency.ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.comparisons.RECORDS_TABLE} WHERE ref_key=?',(key,)).fetchone()
        if raw is None:
            raise TaskConflict('Error persistence requires its original durable comparability execution')
        comparison = json.loads(raw[0])
        original,projection = self.comparisons._validate(comparison)
        current = ActionContext.model_validate(record['context'])
        if (projection != dependency or comparison['organization_id'] != record['organization_id']
                or any(getattr(original,name) != getattr(current,name) for name in
                    ('run_id','actor_id','function_ref','contract_ref','scope','execution_mode'))
                or original.business_time.clock_ref != current.business_time.clock_ref
                or original.business_time.offset > current.business_time.offset
                or any(comparison['action_input'][name] != record['action_input'][name] for name in
                    ('scope','forecast_refs','outcome_refs','feedback_refs','learning_profile_ref','strategy_ref'))):
            raise TaskConflict('Error persistence substitutes its original comparable report or source invocation')
        data = QSForecastComparisonInput.model_validate(record['prepared']['method_execution']['input'])
        if projection.data != data or projection.report != QSComparisonResultView.model_validate(record['prepared']['projection']).report:
            raise TaskConflict('Error report changes original comparison input or exact declared report')
        originals = {Reference.model_validate(row['ref']).key():row for row in comparison['prepared']['source_reading']}
        for ref in {ref.key():ref for ref in [*data.source_refs,*walk_references(data)]}.values():
            if ref.key() not in originals or sources.get(ref.key()) != originals[ref.key()]:
                raise TaskConflict('Error report changes original frozen forecast, received outcome or comparison sources')

    def _validate(self,record):
        context,projection = super()._validate(record)
        self._validate_comparison(record)
        return context,projection

    def _save_targets(self,record,projection,*,is_new):
        self._validate_comparison(record)

    def _validate_saved_targets(self,record,projection):
        self._validate_comparison(record)

    def _publication_content(self,projection):
        """Carry the saved comparable report to the error's new authorized read point."""
        key = task_digest([self.store.run_id,self.ACTION_ID,projection.ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?',(key,)).fetchone()
        if raw is None:
            raise TaskConflict('Error publication requires its already persisted original execution')
        record = json.loads(raw[0])
        if (record['record_sha256'] != task_digest({name:value for name,value in record.items() if name != 'record_sha256'})
                or record['prepared']['projection'] != projection.model_dump(mode='json')):
            raise TaskConflict('Error publication substitutes its saved original report')
        self._validate_comparison(record)
        dependency = record['prepared']['comparison_dependency']
        return {**super()._publication_content(projection),
            'dependencies':[{'ref':dependency['ref'],'value':dependency}]}

    def _published_objects(self,publication):
        return [publication['object'],*publication['dependencies']]


class QSLearningErrorPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications,QSLearningErrorPublicationStore):
            raise ValueError('Error provider requires its original QS-A12 error publication store')
        super().__init__(provider=provider,publications=publications)
