"""Retain original A06 author-reference reports for fresh-token publication."""
from integration.architect_area_calculation_publication import ArchitectAreaCalculationPublicationStore
from integration.architect_integration_actions import validate_architect_consistency_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationConsistencyInput, ArchitectIntegrationConsistencyPreparation,
    ArchitectIntegrationConsistencyReport, ArchitectIntegrationConsistencyView, architect_integration_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_integration import prepare_architect_interface_consistency_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_interfaces import INTERFACE_CONSISTENCY_METHOD, check_original_interface_references
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectInterfaceConsistencyPublicationStore(ArchitectAreaCalculationPublicationStore):
    """Reuse immutable single/multi-report journal transactions with A06 checks.

    Caller holds its actual source/authorization guard. Independent source
    validation runs on save, publication and read. Unknown reports stay unknown;
    no registered method replays and no issue closes or approval is inferred.
    """
    SCHEMA = 'architect-interface-consistency-record.v1'
    PUBLICATION_SCHEMA = 'architect-interface-consistency-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'architect-interface-consistency-batch-publication.v1'
    ACTION_ID = 'ARCHITECT-A06'
    METHOD_REF = INTERFACE_CONSISTENCY_METHOD
    RECORDS_TABLE = 'architect_interface_consistency_records'
    PUBLICATIONS_TABLE = 'architect_interface_consistency_publications'
    SOURCE_SCHEMAS = staticmethod(architect_integration_schemas)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved consistency report changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', 'consistency_input_sha256', 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved consistency report substitutes original input, reading or method registry')
        preparation = ArchitectIntegrationConsistencyPreparation.model_validate(saved['preparation'])
        projection = ArchitectIntegrationConsistencyView.model_validate(saved['projection'])
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved consistency report lacks its complete original method execution')
        data = ArchitectIntegrationConsistencyInput.model_validate(execution['input'])
        result = MethodOk[ArchitectIntegrationConsistencyReport].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Consistency report requires exact original source cache records')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Consistency source cache changes its closed record schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Consistency report repeats an original immutable source version')
            sources[ref.key()] = self.schemas.validate_projection(ref, row['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        validate_architect_consistency_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = prepare_architect_interface_consistency_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation or original['input'] != data
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or saved['consistency_input_sha256'] != task_digest(data.model_dump(mode='json'))
                or any(sources.get(row.ref.key()) != row for row in data.original_objects)):
            raise TaskConflict('Saved consistency report replaces original author objects, mapped input or delegation')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution, originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        report = result.value
        if (projection.model_dump(mode='json') != saved['projection'] or projection.ref != preparation.calculation_ref
                or type(projection.ref.version) is not str or projection.option_ref != original['option'].ref
                or projection.method_ref != preparation.method_ref or preparation.method_ref != original['method'].ref
                or report != check_original_interface_references(data) or report.technical_approval is not False
                or report.option_ref != data.option_ref or projection.option_ref != report.option_ref
                or projection.input_digests != report.input_digests or projection.interface_refs != report.interface_refs
                or projection.retained_issue_refs != report.retained_issue_refs or projection.status != report.status
                or projection.scope != context.scope or projection.executed_at != context.business_time
                or projection.available_at != context.business_time
                or projection.effective_window.model_dump(mode='json') != {'start': context.business_time.model_dump(mode='json'),
                    'end': context.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or projection.author_authority_ref not in context.authorization_refs
                or projection.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved consistency report changes original result, method declaration, issues or author/read authority')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved consistency author lacks current original evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal consistency report cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection


class ArchitectInterfaceConsistencyPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectInterfaceConsistencyPublicationStore):
            raise ValueError('Consistency publication requires its original Architect A06 report store')
        super().__init__(provider=provider, publications=publications)
