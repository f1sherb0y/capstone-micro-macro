"""Retain original A09 impact proofs for authorized fresh-token publication."""
from integration.architect_area_calculation_publication import ArchitectAreaCalculationPublicationStore
from integration.architect_change_actions import validate_architect_change_impact_preparation_sources
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.architect_change_objects import (
    ArchitectChangeImpactPreparation, ArchitectChangeImpactResultView, architect_change_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_change import prepare_architect_change_impact_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_change_impact import (
    ARCHITECT_CHANGE_IMPACT_METHOD, ArchitectChangeImpactArithmeticInput,
    ArchitectChangeImpactReport, calculate_declared_change_impact,
)
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectChangeImpactPublicationStore(ArchitectAreaCalculationPublicationStore):
    """Reuse immutable journal boundaries with separate A09 proofs and tables.

    Caller holds the actual source guard. Independent actual-source validation,
    including numeric scope/cost/time conventions, is required on save, publish
    and read. Pure report comparison invokes no registered executor. Unknown
    differences remain intact; publication creates no change or fee entitlement.
    """
    SCHEMA = 'architect-change-impact-record.v1'
    PUBLICATION_SCHEMA = 'architect-change-impact-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'architect-change-impact-batch-publication.v1'
    ACTION_ID = 'ARCHITECT-A09'
    ROLE = 'Architect'
    METHOD_REF = ARCHITECT_CHANGE_IMPACT_METHOD
    RECORDS_TABLE = 'architect_change_impact_records'
    PUBLICATIONS_TABLE = 'architect_change_impact_publications'
    SOURCE_SCHEMAS = staticmethod(architect_change_schemas)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved impact changes original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', 'impact_input_sha256', 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved impact replaces original input, source cache or registry')
        preparation = ArchitectChangeImpactPreparation.model_validate(saved['preparation'])
        projection = ArchitectChangeImpactResultView.model_validate(saved['projection'])
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved impact lacks complete original execution proof')
        data = ArchitectChangeImpactArithmeticInput.model_validate(execution['input'])
        result = MethodOk[ArchitectChangeImpactReport].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Saved impact requires exact original source cache records')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Impact source cache replaces its closed schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Impact source cache repeats an immutable version')
            value = self.schemas.validate_projection(ref, row['projection'])
            sources[ref.key()], originals[ref.key()] = value, value.model_dump(mode='json')
            resolver.register_projection(ref, value)
            refs.append(ref)
        validate_architect_change_impact_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = prepare_architect_change_impact_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or original['arithmetic'] != data or original['method'].ref != self.METHOD_REF
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or saved['impact_input_sha256'] != task_digest(data.model_dump(mode='json'))):
            raise TaskConflict('Saved impact replaces original evaluation, numeric basis or source versions')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution,
            originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        if (projection.model_dump(mode='json') != saved['projection'] or projection.ref != preparation.calculation_ref
                or type(projection.ref.version) is not str
                or projection.issue_ref != original['issue'].ref or projection.used_deliverable_ref != original['original'].ref
                or projection.instruction_ref != action_input.instruction_ref
                or projection.input_sha256 != original['input_sha256'] or projection.input_sha256 != data.input_sha256
                or result.value != calculate_declared_change_impact(data)
                or projection.cost_delta != result.value.cost_delta or projection.duration_delta != result.value.duration_delta
                or projection.method_ref != self.METHOD_REF or projection.status != 'ok' or projection.scope != context.scope
                or projection.executed_at != context.business_time or projection.available_at != context.business_time
                or projection.effective_window.model_dump(mode='json') != {'start': context.business_time.model_dump(mode='json'),
                    'end': context.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or projection.author_organization_id != record['organization_id']
                or projection.author_organization_id not in original['method'].permitted_author_ids
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_action_id != self.ACTION_ID
                or projection.author_authority_ref != original['profile'].authority_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or projection.author_authority_ref not in context.authorization_refs
                or projection.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved impact changes original finding, input, time, author or read authority')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved impact author lacks current original source evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal impact cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection


class ArchitectChangeImpactPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectChangeImpactPublicationStore):
            raise ValueError('Impact publication requires its original Architect A09 impact store')
        super().__init__(provider=provider, publications=publications)
