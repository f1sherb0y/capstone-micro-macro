"""Persist finite QS learning assessments with original cost-report dependencies."""
import json

from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
from integration.qs_learning_error_publication import QSLearningErrorPublicationStore
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_learning_objects import QSLearningAssessmentView, QSComparisonResultView
from src.actions.roles.qs_learning import prepare_qs_learning_assessment_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_learning import (
    LEARNING_METHOD, ArchitectFeedbackInput, ArchitectFeedbackReport, apply_declared_feedback_rules,
)


class QSLearningAssessmentPublicationStore(QSLearningComparabilityPublicationStore):
    """Reuse immutable save/read/publication and original method-proof validation.

    Cost-dependent assessments require original same-journal error/comparison
    executions. Noncost assessments may omit those stores. The independent
    actual-source gate is mandatory under the caller's source/authority guard.
    Saving a report applies no strategy, feedback history, capability or cash.
    """
    SCHEMA = 'qs-learning-assessment-record.v1'
    PUBLICATION_SCHEMA = 'qs-learning-assessment-publication.v1'
    METHOD_REF = LEARNING_METHOD
    RECORDS_TABLE = 'qs_learning_assessment_records'
    PUBLICATIONS_TABLE = 'qs_learning_assessment_publications'
    PREPARE_INPUT = staticmethod(prepare_qs_learning_assessment_input)
    EXTRA_FIELDS = frozenset({'dependencies'})
    REQUIRE_EMPTY_COMPARISON = False
    PROJECTION_MODEL = QSLearningAssessmentView
    INPUT_MODEL = ArchitectFeedbackInput
    REPORT_MODEL = ArchitectFeedbackReport
    VERIFY_REPORT = staticmethod(apply_declared_feedback_rules)

    def __init__(self, *, store, registry, methods, organizations, validate_source, errors=None):
        if errors is not None and (type(errors) is not QSLearningErrorPublicationStore
                or errors.store is not store or errors.registry is not registry
                or errors.methods is not methods or errors.organizations is not organizations):
            raise ValueError('Learning assessment requires its original same-journal error store when configured')
        self.errors=errors
        self._error_components=None if errors is None else (errors,errors.store,errors.registry,errors.methods,errors.organizations)
        super().__init__(store=store,registry=registry,methods=methods,
            organizations=organizations,validate_source=validate_source)

    def _matches_projection_identity(self,projection,original,context):
        return (projection.strategy_ref==original['strategy_ref']
            and projection.learning_profile_ref==original['learning_profile_ref']
            and (original['assessment_ref'] is None or projection.ref==original['assessment_ref']))

    def _validate_prepared_dependency(self,prepared,original):
        expected={name:row.model_dump(mode='json') for name,row in original['dependencies'].items()}
        if (prepared['dependencies']!=expected
                or any(row['ref']==prepared['projection']['ref'] for row in prepared['source_reading'])):
            raise TaskConflict('Learning assessment substitutes its dependencies or replaces a supplied target report')

    def _validate_dependencies(self,record):
        if self._error_components is None:
            if self.errors is not None:
                raise TaskConflict('Learning assessment substituted its original absent error store')
        elif (self.errors is None or any(actual is not original for actual,original in zip(
                (self.errors,self.errors.store,self.errors.registry,self.errors.methods,self.errors.organizations),
                self._error_components))):
            raise TaskConflict('Learning assessment changed original error store components')
        dependencies=record['prepared']['dependencies']
        if not isinstance(dependencies,dict) or set(dependencies) not in (set(),{'comparison_dependency','error_dependency'}):
            raise TaskConflict('Learning assessment changes its closed report-dependency schema')
        if not dependencies:
            return
        if self.errors is None:
            raise TaskConflict('Cost learning assessment requires original independently persisted error/comparison executions')
        sources={Reference.model_validate(row['ref']).key():row for row in record['prepared']['source_reading']}
        current=ActionContext.model_validate(record['context'])
        records={}
        for name,store in [('error_dependency',self.errors),('comparison_dependency',self.errors.comparisons)]:
            dependency=QSComparisonResultView.model_validate(dependencies[name])
            key=task_digest([self.store.run_id,self.ACTION_ID,dependency.ref.model_dump(mode='json')])
            with self.store._lock:
                raw=self.store._db.execute(f'SELECT record FROM {store.RECORDS_TABLE} WHERE ref_key=?',(key,)).fetchone()
            if raw is None:
                raise TaskConflict('Learning assessment report dependency lacks its original durable method execution')
            saved=json.loads(raw[0])
            original,projection=store._validate(saved)
            if (projection!=dependency or saved['organization_id']!=record['organization_id']
                    or sources.get(dependency.ref.key(),{}).get('projection')!=dependency.model_dump(mode='json')
                    or any(getattr(original,field)!=getattr(current,field) for field in
                        ('run_id','actor_id','function_ref','contract_ref','scope','execution_mode'))
                    or original.business_time.clock_ref!=current.business_time.clock_ref
                    or original.business_time.offset>current.business_time.offset):
                raise TaskConflict('Learning assessment changes original report, private organization or execution identity')
            originals={Reference.model_validate(row['ref']).key():row for row in saved['prepared']['source_reading']}
            for ref in {ref.key():ref for ref in [*dependency.data.source_refs,*walk_references(dependency.data)]}.values():
                if ref.key() not in originals or sources.get(ref.key())!=originals[ref.key()]:
                    raise TaskConflict('Learning assessment changes original immutable forecast/outcome report sources')
            records[name]=saved
        if records['error_dependency']['prepared']['comparison_dependency']!=dependencies['comparison_dependency']:
            raise TaskConflict('Learning assessment combines an error with another original comparison')

    def _validate(self,record):
        context,projection=super()._validate(record)
        self._validate_dependencies(record)
        return context,projection

    def _save_targets(self,record,projection,*,is_new):
        self._validate_dependencies(record)

    def _validate_saved_targets(self,record,projection):
        self._validate_dependencies(record)

    def _publication_content(self,projection):
        key=task_digest([self.store.run_id,self.ACTION_ID,projection.ref.model_dump(mode='json')])
        with self.store._lock:
            raw=self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?',(key,)).fetchone()
        if raw is None:
            raise TaskConflict('Learning assessment publication requires its saved original report')
        record=json.loads(raw[0])
        if (record['record_sha256']!=task_digest({name:value for name,value in record.items() if name!='record_sha256'})
                or record['prepared']['projection']!=projection.model_dump(mode='json')):
            raise TaskConflict('Learning assessment publication changes its saved original projection')
        self._validate_dependencies(record)
        dependencies=record['prepared']['dependencies']
        return {**super()._publication_content(projection),
            'dependencies':[{'ref':row['ref'],'value':row} for row in dependencies.values()]}

    def _published_objects(self,publication):
        return [publication['object'],*publication['dependencies']]


class QSLearningAssessmentPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications,QSLearningAssessmentPublicationStore):
            raise ValueError('Learning assessment provider requires its original QS assessment store')
        super().__init__(provider=provider,publications=publications)
