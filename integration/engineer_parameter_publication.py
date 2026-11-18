"""Retain original finite parameter results for fresh-token publication."""
from integration.architect_area_calculation_publication import ArchitectAreaCalculationPublicationStore
from integration.engineer_design_actions import validate_engineer_parameter_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignParameterPreparation, EngineerDesignMethodProjection, EngineerParameterResultView,
    engineer_design_schemas,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.engineer_design import prepare_engineer_parameter_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.engineer_parameters import PARAMETER_METHOD, EngineerParameterInput, EngineerParameterReport, validate_parameter
from src.methods.models import MethodOk
from src.organization.models import Authorization


class EngineerParameterPublicationStore(ArchitectAreaCalculationPublicationStore):
    """Reuse immutable single/multi-result journal transactions with Engineer checks.

    Caller holds its actual source guard. Independent source validation is
    required on save, publication and read. Retained reports preserve unknown
    and outside-domain findings; validation never invokes a registered method.
    """
    SCHEMA = 'engineer-parameter-record.v1'
    PUBLICATION_SCHEMA = 'engineer-parameter-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'engineer-parameter-batch-publication.v1'
    ACTION_ID = 'ENGINEER-A05'
    ROLE = 'Engineer'
    METHOD_REF = PARAMETER_METHOD
    RECORDS_TABLE = 'engineer_parameter_records'
    PUBLICATIONS_TABLE = 'engineer_parameter_publications'
    SOURCE_SCHEMAS = staticmethod(engineer_design_schemas)
    PREPARATION_MODEL = EngineerDesignParameterPreparation
    INPUT_MODEL = EngineerParameterInput
    REPORT_MODEL = EngineerParameterReport
    RESULT_MODEL = EngineerParameterResultView
    PROJECTION_MODEL = EngineerDesignMethodProjection
    INPUT_SHA_FIELD = 'parameter_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_parameter_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_parameter_input)
    REPLAY = staticmethod(validate_parameter)

    def _result_matches_input(self, value, original, data):
        return value.engineering_profile_ref == original['profile'].ref and value.input == data

    def _projection_result(self, projection):
        return projection.record

    def _result_matches_report(self, value, report, data):
        return value.result == report

    def _result_author_matches(self, value, context):
        return value.author_action_id == self.ACTION_ID

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved parameter result changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', self.INPUT_SHA_FIELD, 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved parameter result substitutes original input, reading or method registry')
        preparation = self.PREPARATION_MODEL.model_validate(saved['preparation'])
        projection = self.PROJECTION_MODEL.model_validate(saved['projection'])
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved parameter result lacks its complete original execution')
        data = self.INPUT_MODEL.model_validate(execution['input'])
        result = MethodOk[self.REPORT_MODEL].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Parameter result requires exact original source cache records')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Parameter source cache changes its closed schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Parameter result repeats an original immutable source version')
            sources[ref.key()] = self.schemas.validate_projection(ref, row['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        self.VALIDATE_SOURCES(action_input, preparation=preparation,
            context=context, organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = self.PREPARE_INPUT(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or preparation.input != data or saved[self.INPUT_SHA_FIELD] != task_digest(data.model_dump(mode='json'))):
            raise TaskConflict('Saved parameter result replaces original task, catalog, value, sources or reserved target')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution, originals=originals, result=result)
        value = self._projection_result(projection)
        if not isinstance(value, self.RESULT_MODEL):
            raise TaskConflict('Saved parameter projection substitutes an unrelated professional check')
        grant = sources.get(value.author_authority_ref.key())
        if (projection.model_dump(mode='json') != saved['projection'] or projection.ref != preparation.calculation_ref
                or value.ref != projection.ref or type(projection.ref.version) is not str
                or value.task_ref != original['task'].ref or not self._result_matches_input(value, original, data)
                or not self._result_matches_report(value, result.value, data) or result.value != self.REPLAY(data)
                or value.method_ref != self.METHOD_REF or value.status != 'ok' or value.scope != context.scope
                or value.executed_at != context.business_time or value.available_at != context.business_time
                or value.effective_window.model_dump(mode='json') != {'start':context.business_time.model_dump(mode='json'),
                    'end':context.business_time.model_dump(mode='json'), 'bounds':'closed_closed'}
                or value.author_actor_id != context.actor_id or value.author_function_ref != context.function_ref
                or not self._result_author_matches(value, context) or value.author_authority_ref != original['task'].authority_ref
                or value.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or value.author_authority_ref not in context.authorization_refs
                or value.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved parameter result changes original finding, input, time or author/read authority')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved parameter author lacks current original evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row,EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal parameter result cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection


class EngineerParameterPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, EngineerParameterPublicationStore):
            raise ValueError('Parameter publication requires its original Engineer A05 result store')
        super().__init__(provider=provider, publications=publications)
