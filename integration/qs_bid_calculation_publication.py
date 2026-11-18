"""Retain QS-A06 normalization executions and expose their original results."""
from integration.qs_bid_actions import validate_qs_bid_sources
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_bid_objects import QSBidMethodResultView, qs_bid_schemas
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_bid import prepare_bid_normalization, prepare_bid_ranking
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_bid import NORMALIZE_METHOD, NormalizeInput, NormalizeReport
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSBidNormalizationPublicationStore(QSCostCalculationPublicationStore):
    """Persist one original comparison calculation without rerunning arithmetic.

    validate_source(record, current_context) independently checks actual original
    sources under the caller's source/authorization writer guard. A publication
    exposes comparison prices only; bidder prices, exclusions and awards remain
    separate. The existing save/publish/read transactions prevent replacement.
    """
    SCHEMA = 'qs-bid-normalization-record.v1'
    PUBLICATION_SCHEMA = 'qs-bid-normalization-publication.v1'
    ACTION_ID = 'QS-A06'
    METHOD_REF = NORMALIZE_METHOD
    RECORDS_TABLE = 'qs_bid_normalization_records'
    PUBLICATIONS_TABLE = 'qs_bid_normalization_publications'
    SOURCE_SCHEMAS = staticmethod(qs_bid_schemas)
    RESULT_KIND = 'normalization'
    INPUT_MODEL = NormalizeInput
    REPORT_MODEL = NormalizeReport
    PREPARE_INPUT = staticmethod(prepare_bid_normalization)
    REQUIRE_EMPTY_RESULTS = True

    def _matches_output(self, projection, report):
        return projection.prices == report.prices and not projection.ranked_groups

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id',
                'context', 'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved bid normalization changes its original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved bid normalization belongs to another original invocation')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'source_mode', 'source_reading', 'reading_sha256', 'method_execution',
            'method_registry_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != fields or prepared['kind'] != 'prepared'
                or (self.REQUIRE_EMPTY_RESULTS and action_input.method_result_refs) or action_input.scope != context.scope
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved bid normalization changes original input, reading or method registry')
        projection = QSBidMethodResultView.model_validate(prepared['projection'])
        execution = prepared['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved bid normalization lacks its complete original registered execution')
        arithmetic = self.INPUT_MODEL.model_validate(execution['input'])
        result = MethodOk[self.REPORT_MODEL].model_validate(execution['result'])
        originals, sources, refs = {}, {}, []
        resolver = ReferenceResolver(context.run_id, source_mode=prepared['source_mode'], schemas=self.schemas)
        if not isinstance(prepared['source_reading'], list):
            raise TaskConflict('Saved bid normalization requires its original source records')
        for row in prepared['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Bid normalization cache changes its closed original source schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Bid normalization repeats an original immutable source reference')
            sources[ref.key()] = self.schemas.validate_projection(ref, row['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        validate_qs_bid_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        original = self.PREPARE_INPUT(context, action_input, reading)
        if (original['kind'] != 'prepared' or original['input'] != arithmetic
                or original['calculation_ref'] != projection.ref
                or reading.organization_id != record['organization_id'] or reading.method_evidence()):
            raise TaskConflict('Saved bid normalization substitutes original bids, eligibility or adjustment inputs')
        self._validate_method_execution(context=context, arithmetic=arithmetic,
            execution=execution, originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        evidence_refs = [ref for ref in refs if ref.kind == 'Evidence']
        if (projection.model_dump(mode='json') != prepared['projection']
                or projection.method_ref != self.METHOD_REF or projection.kind != self.RESULT_KIND
                or projection.status != 'ok' or type(projection.ref.version) is not str
                or projection.round_ref != original['round_ref'] or projection.document_ref != original['document_ref']
                or projection.profile_ref != original['profile_ref'] or projection.basis_refs != original['basis_refs']
                or projection.bid_refs != [row.bid_ref for row in arithmetic.bids]
                or not self._matches_output(projection, result.value)
                or projection.scope != context.scope or projection.calculated_at != context.business_time
                or projection.available_at != context.business_time or not projection.effective_window.contains(context.business_time)
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref not in context.authorization_refs or projection.author_action_id != self.ACTION_ID
                or projection.evidence_refs != evidence_refs
                or task_digest(prepared['projection']) != prepared['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in self._grants(context)
                or grant.organization_id != record['organization_id'] or grant.actor_id != context.actor_id
                or grant.function_ref != context.function_ref or self.ACTION_ID not in grant.action_ids
                or not grant.validity.contains(context.business_time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *arithmetic.source_refs]} <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Saved normalization projection changes its original method output, author or source versions')
        for ref in grant.basis_refs:
            basis = sources.get(ref.key())
            if (not isinstance(basis, EvidenceRecord)
                    or basis.effective_window is not None and not basis.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved bid normalization author lacks current original evidence')
        if prepared['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal bid normalization cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection

    def _publication_refs(self, record, projection):
        return list({ref.key(): ref for ref in [projection.ref, *walk_references(projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['source_reading'])]}.values())


class QSBidNormalizationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSBidNormalizationPublicationStore):
            raise ValueError('Bid normalization provider requires its original QS-A06 publication store')
        super().__init__(provider=provider, publications=publications)
