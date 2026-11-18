"""Retain immutable QS A13 normalization proof for separate authorized publication."""
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from integration.qs_research_actions import validate_qs_research_sources
from integration.qs_research_normalization_calculations import _normalization_preparation_payload
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.qs_research_objects import (
    QSResearchMethodProjection, QSResearchTaskView, qs_research_schemas,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_research import prepare_qs_research_normalization_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_research import (
    RESEARCH_NORMALIZE_METHOD, ResearchNormalizationInput, ResearchNormalizationReport, normalize_plans,
)
from src.organization.models import Authorization


class QSResearchNormalizationPublicationStore(QSCostCalculationPublicationStore):
    """Reuse immutable journal transactions with separate A13 normalization tables.

    The caller holds the actual source guard. Save, publish and provider read
    each require independent current source validation. Arithmetic is checked
    from retained proof and its pure rule; the registered method is not replayed.
    This publishes comparison values and creates no new A04 cost plan or spend.
    """
    SCHEMA = 'qs-research-normalization-record.v1'
    PUBLICATION_SCHEMA = 'qs-research-normalization-publication.v1'
    ACTION_ID = 'QS-A13'
    METHOD_REF = RESEARCH_NORMALIZE_METHOD
    RECORDS_TABLE = 'qs_research_normalization_records'
    PUBLICATIONS_TABLE = 'qs_research_normalization_publications'
    SOURCE_SCHEMAS = staticmethod(qs_research_schemas)
    RESULT_KIND = 'normalization'
    INPUT_MODEL = ResearchNormalizationInput
    REPORT_MODEL = ResearchNormalizationReport
    PREPARE_INPUT = staticmethod(prepare_qs_research_normalization_input)
    PREPARATION_PAYLOAD = staticmethod(_normalization_preparation_payload)
    PURE_REPORT = staticmethod(normalize_plans)

    def __init__(self, **components):
        if getattr(components.get('store'), 'path', None) is None:
            raise ValueError('Research normalization persistence requires its original durable journal')
        super().__init__(**components)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id',
                'context', 'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved research normalization changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', self.RESULT_KIND + '_input_sha256', 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved research normalization substitutes original input, preparation, cache or registry')
        projection = QSResearchMethodProjection.model_validate(saved['projection'])
        comparison = projection.comparison
        execution = saved['method_execution']
        if (comparison is None or not isinstance(execution, dict)
                or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}):
            raise TaskConflict('Saved research normalization lacks its original comparison and complete execution proof')
        data = self.INPUT_MODEL.model_validate(execution['input'])
        result = MethodOk[self.REPORT_MODEL].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Saved research normalization requires its exact original source cache')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Research normalization source cache changes its closed record schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Research normalization cache repeats an immutable source reference')
            value = self.schemas.validate_projection(ref, row['projection'])
            if value.model_dump(mode='json') != row['projection']:
                raise TaskConflict('Research normalization cache changes its canonical source projection')
            sources[ref.key()], originals[ref.key()] = value, value.model_dump(mode='json')
            resolver.register_projection(ref, value)
            refs.append(ref)
        validate_qs_research_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates, CandidateSet):
            raise TaskConflict('Saved research normalization lacks its original candidate authority')
        candidates.check_context(context, self.registry.get(self.ACTION_ID).contract.choices)
        for candidate in candidates.candidates:
            reading.resolve(candidate.ref)
        original = self.PREPARE_INPUT(context, action_input, reading)
        if (original['kind'] != 'prepared' or original['input'] != data
                or self.PREPARATION_PAYLOAD(original) != saved['preparation']
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or saved[self.RESULT_KIND + '_input_sha256'] != task_digest(data.model_dump(mode='json'))):
            raise TaskConflict('Saved research normalization replaces original cost plans, adjustment bases or prepared input')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution,
            originals=originals, result=result)
        task = sources.get(action_input.task_ref.key())
        grant = sources.get(comparison.author_authority_ref.key())
        now = context.business_time
        if (not isinstance(task, QSResearchTaskView)
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != original['calculation_ref'] or type(projection.ref.version) is not str
                or comparison.kind != self.RESULT_KIND or comparison.method_ref != self.METHOD_REF
                or comparison.status != 'ok' or comparison.scope != context.scope
                or comparison.task_ref != original['task_ref'] or comparison.profile_ref != original['profile_ref']
                or comparison.comparison_basis_ref != original['comparison_basis_ref']
                or comparison.plan_refs != original['plan_refs']
                or comparison.normalization_basis_refs != original['normalization_basis_refs']
                or result.value != self.PURE_REPORT(data)
                or not self._matches_output(comparison, result.value)
                or comparison.calculated_at != now or comparison.available_at != now
                or comparison.effective_window.model_dump(mode='json') != {
                    'start': now.model_dump(mode='json'), 'end': now.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or comparison.author_actor_id != context.actor_id or comparison.author_function_ref != context.function_ref
                or comparison.author_action_id != self.ACTION_ID or comparison.author_authority_ref != task.authority_ref
                or comparison.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or comparison.author_authority_ref not in context.authorization_refs
                or comparison.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved research normalization changes original output, plans, evidence, time or author authority')
        for ref in [*grant.basis_refs, *(ref for ref in walk_references(data) if ref.kind == 'Evidence')]:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
                raise TaskConflict('Saved research normalization lacks current original numeric or authority evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal research normalization cannot retain synthetic evidence')
        reading.recheck()
        return context, projection

    def _matches_output(self, comparison, report):
        return comparison.normalized_costs == report.normalized_costs and not comparison.ranked_groups

    def _publication_refs(self, record, projection):
        return list({ref.key(): ref for ref in [projection.ref, *walk_references(projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['source_reading'])]}.values())


class QSResearchNormalizationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSResearchNormalizationPublicationStore):
            raise ValueError('Research normalization provider requires its original QS A13 publication store')
        super().__init__(provider=provider, publications=publications)
