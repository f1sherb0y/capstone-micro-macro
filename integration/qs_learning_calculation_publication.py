"""Retain original QS-A12 comparison execution for explicit authorized publication."""
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from integration.qs_learning_actions import validate_qs_learning_sources
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_learning_objects import QSComparisonResultView, qs_learning_schemas
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_learning import prepare_qs_forecast_comparison_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_learning import (
    COMPARABILITY_METHOD, QSForecastComparisonInput, QSForecastComparisonReport, compare_original_forecast,
)
from src.organization.models import Authorization


class QSLearningComparabilityPublicationStore(QSCostCalculationPublicationStore):
    """Reuse immutable same-run save/publication transactions for private reports.

    The independent validate_source(record, current_context) gate checks actual
    frozen forecast and received outcome provenance under the caller's source
    writer guard. Stored method proof is checked without registry execution.
    Publication neither applies learning nor grants access to another firm.
    """
    SCHEMA = 'qs-learning-comparability-record.v1'
    PUBLICATION_SCHEMA = 'qs-learning-comparability-publication.v1'
    ACTION_ID = 'QS-A12'
    METHOD_REF = COMPARABILITY_METHOD
    RECORDS_TABLE = 'qs_learning_comparability_records'
    PUBLICATIONS_TABLE = 'qs_learning_comparability_publications'
    SOURCE_SCHEMAS = staticmethod(qs_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_qs_learning_sources)
    PREPARE_INPUT = staticmethod(prepare_qs_forecast_comparison_input)
    EXTRA_FIELDS = frozenset()
    REQUIRE_EMPTY_COMPARISON = True
    PROJECTION_MODEL = QSComparisonResultView
    INPUT_MODEL = QSForecastComparisonInput
    REPORT_MODEL = QSForecastComparisonReport
    VERIFY_REPORT = staticmethod(compare_original_forecast)

    def _matches_projection_identity(self,projection,original,context):
        return projection.method_ref == self.METHOD_REF and projection.executed_at == context.business_time

    def _matches_projection_input(self,projection,data):
        return projection.data == data

    def __init__(self, *, store, registry, methods, organizations, validate_source):
        if getattr(store,'path',None) is None:
            raise ValueError('Forecast comparison persistence requires the original durable journal')
        super().__init__(store=store,registry=registry,methods=methods,
            organizations=organizations,validate_source=validate_source)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version','organization_id',
                'context','action_input','prepared','binding','record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({key:value for key,value in record.items() if key != 'record_sha256'})):
            raise TaskConflict('Saved forecast comparison changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        if record['organization_id'] != grants[0].organization_id:
            raise TaskConflict('Saved forecast comparison belongs to another original private organization')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        fields = {'kind','projection','projection_sha256','context_sha256','input_sha256',
            'source_mode','source_reading','reading_sha256','author_authority_ref',
            'method_execution','method_registry_sha256','limitations'}
        fields.update(self.EXTRA_FIELDS)
        if (not isinstance(prepared, dict) or set(prepared) != fields or prepared['kind'] != 'prepared'
                or self.REQUIRE_EMPTY_COMPARISON and action_input.comparability_result_ref is not None
                or action_input.scope != context.scope
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved forecast comparison substitutes its original input, reading or registry')
        projection = self.PROJECTION_MODEL.model_validate(prepared['projection'])
        execution = prepared['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref','registry_digest','input','result'}:
            raise TaskConflict('Saved forecast comparison lacks its original complete method execution')
        data = self.INPUT_MODEL.model_validate(execution['input'])
        result = MethodOk[self.REPORT_MODEL].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=prepared['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(prepared['source_reading'], list):
            raise TaskConflict('Forecast comparison requires exact original source cache records')
        for row in prepared['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref','projection'}:
                raise TaskConflict('Forecast comparison source cache changes its closed record schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Forecast comparison repeats an original immutable source version')
            sources[ref.key()] = self.schemas.validate_projection(ref,row['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref,sources[ref.key()])
            refs.append(ref)
        self.VALIDATE_SOURCES(action_input,context=context,
            organization_id=record['organization_id'],sources=sources)
        resolver.freeze_read(context.read_token,refs)
        reading = ActionReadView(context,resolver,self.organizations,self.ACTION_ID,self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = self.PREPARE_INPUT(context,action_input,reading)
        if (original['kind'] != 'prepared' or original['input'] != data
                or reading.organization_id != record['organization_id'] or reading.method_evidence()
                or reading.evidence() != prepared['source_reading']):
            raise TaskConflict('Saved comparison substitutes original immutable forecast or lawfully received outcome inputs')
        self._validate_prepared_dependency(prepared,original)
        self._validate_method_execution(context=context,arithmetic=data,execution=execution,originals=originals,result=result)
        grant = sources.get(projection.author_authority_ref.key())
        if (projection.model_dump(mode='json') != prepared['projection']
                or not self._matches_projection_identity(projection,original,context)
                or not self._matches_projection_input(projection,data)
                or projection.input_sha256 != task_digest(data.model_dump(mode='json'))
                or projection.report != result.value or result.value != self.VERIFY_REPORT(data)
                or projection.status != 'ok' or type(projection.ref.version) is not str
                or projection.organization_id != record['organization_id'] or projection.scope != context.scope
                or any(getattr(projection,name) != context.business_time for name in ('authored_at','available_at'))
                or not projection.effective_window.contains(context.business_time)
                or projection.author_actor_id != context.actor_id or projection.author_organization_id != record['organization_id']
                or projection.author_function_ref != context.function_ref or projection.author_action_id != self.ACTION_ID
                or projection.author_authority_ref.model_dump(mode='json') != prepared['author_authority_ref']
                or projection.author_authority_ref not in context.authorization_refs
                or projection.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(prepared['projection']) != prepared['projection_sha256']
                or not isinstance(grant,Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved comparison changes original report, calculation, author or target read authority')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence,EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved comparison author lacks current original evidence')
        if prepared['source_mode'] == 'formal' and any(isinstance(row,EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal forecast comparison cannot retain synthetic source evidence')
        reading.recheck()
        return context,projection

    def _validate_prepared_dependency(self,prepared,original):
        """Comparability reports have no predecessor report dependency."""

    def _publication_refs(self,record,projection):
        return list({ref.key():ref for ref in [projection.ref,*walk_references(projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['source_reading'])]}.values())


class QSLearningComparabilityPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications,QSLearningComparabilityPublicationStore):
            raise ValueError('Comparison provider requires its original QS-A12 publication store')
        super().__init__(provider=provider,publications=publications)
