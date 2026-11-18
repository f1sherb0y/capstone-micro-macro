"""Retain original A13 investigation estimates for authorized publication."""
from integration.architect_area_calculation_publication import ArchitectAreaCalculationPublicationStore
from integration.architect_research_actions import validate_architect_research_estimate_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchEstimatePreparation, ArchitectResearchEstimateView, architect_research_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_research import prepare_architect_research_estimate_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_research_estimates import (
    ARCHITECT_RESEARCH_ESTIMATE_METHOD, ArchitectResearchEstimateInput,
    ArchitectResearchEstimateReport, estimate_declared_architect_research,
)
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectResearchEstimatePublicationStore(ArchitectAreaCalculationPublicationStore):
    """Reuse immutable journal transactions with separate A13 estimate tables.

    Caller holds the actual source guard. Save, publication and read each require
    independent actual-source validation, including numeric coverage and rates.
    Retained execution proof and pure report comparison are checked separately.
    Publication creates no investigation task, resource, work, fee or cash.
    """
    SCHEMA = 'architect-research-estimate-record.v1'
    PUBLICATION_SCHEMA = 'architect-research-estimate-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'architect-research-estimate-batch-publication.v1'
    ACTION_ID = 'ARCHITECT-A13'
    ROLE = 'Architect'
    METHOD_REF = ARCHITECT_RESEARCH_ESTIMATE_METHOD
    RECORDS_TABLE = 'architect_research_estimate_records'
    PUBLICATIONS_TABLE = 'architect_research_estimate_publications'
    SOURCE_SCHEMAS = staticmethod(architect_research_schemas)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved research estimate changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', 'estimate_input_sha256', 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved research estimate replaces original input, source cache or method registry')
        preparation = ArchitectResearchEstimatePreparation.model_validate(saved['preparation'])
        projection = ArchitectResearchEstimateView.model_validate(saved['projection'])
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved research estimate lacks complete original execution proof')
        data = ArchitectResearchEstimateInput.model_validate(execution['input'])
        result = MethodOk[ArchitectResearchEstimateReport].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Saved research estimate requires exact original cache records')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Research source cache replaces its closed schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Research source cache repeats an immutable version')
            value = self.schemas.validate_projection(ref, row['projection'])
            sources[ref.key()], originals[ref.key()] = value, value.model_dump(mode='json')
            resolver.register_projection(ref, value)
            refs.append(ref)
        validate_architect_research_estimate_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = prepare_architect_research_estimate_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or preparation.input != data or original['method'].ref != self.METHOD_REF
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or saved['estimate_input_sha256'] != task_digest(data.model_dump(mode='json'))):
            raise TaskConflict('Saved research estimate replaces original sourced work, request or preparation')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution,
            originals=originals, result=result)
        task, request = original['task'], original['request']
        grant = sources.get(projection.author_authority_ref.key())
        if (projection.model_dump(mode='json') != saved['projection'] or projection.ref != preparation.calculation_ref
                or type(projection.ref.version) is not str or projection.task_ref != task.ref
                or projection.request_profile_ref != request.ref or projection.ref != request.estimate_ref
                or projection.work_profile_ref != request.work_profile_ref or projection.input_refs != request.input_refs
                or result.value != estimate_declared_architect_research(data)
                or projection.effort_estimate.state != 'known' or projection.incremental_cost.state != 'known'
                or projection.effort_estimate.value != result.value.effort
                or projection.incremental_cost.value != result.value.estimated_cost
                or projection.effort_estimate != request.effort_estimate
                or projection.incremental_cost != request.incremental_cost
                or projection.method_ref != self.METHOD_REF or projection.status != 'ok' or projection.scope != context.scope
                or projection.available_at != context.business_time
                or projection.effective_window.model_dump(mode='json') != {'start': context.business_time.model_dump(mode='json'),
                    'end': context.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref != task.authority_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or projection.author_authority_ref not in context.authorization_refs
                or projection.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved research estimate changes original amount, effort, basis, request, time or author')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved research estimate author lacks current original authority evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal research estimate cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection


class ArchitectResearchEstimatePublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectResearchEstimatePublicationStore):
            raise ValueError('Research publication requires its original Architect A13 estimate store')
        super().__init__(provider=provider, publications=publications)
