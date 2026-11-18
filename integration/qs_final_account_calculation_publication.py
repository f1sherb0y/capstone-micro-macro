"""Retain original QS-A09 reconciliation executions for fresh-token publication."""
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from integration.qs_final_account_actions import validate_qs_final_account_sources
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_final_account_objects import QSFinalResultView, qs_final_account_schemas
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_change import content_digest
from src.actions.roles.qs_final_account import prepare_final_account_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_final_account import FINAL_ACCOUNT_METHOD, FinalAccountInput, FinalAccountReport
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSFinalAccountCalculationPublicationStore(QSCostCalculationPublicationStore):
    """Technical evidence only; retained calculations never determine clearance.

    The host supplies an independent validate_source(record, current_context)
    gate returning True under the actual source and authorization writer guard.
    Validation prepares the original input without invoking its executor.
    """
    SCHEMA = 'qs-final-account-calculation-record.v1'
    PUBLICATION_SCHEMA = 'qs-final-account-calculation-publication.v1'
    ACTION_ID = 'QS-A09'
    METHOD_REF = FINAL_ACCOUNT_METHOD
    RECORDS_TABLE = 'qs_final_account_calculation_records'
    PUBLICATIONS_TABLE = 'qs_final_account_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(qs_final_account_schemas)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'} or record['schema_version'] != self.SCHEMA
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['binding'] != self._binding()):
            raise TaskConflict('Saved final reconciliation changes its schema, binding or original digest')
        context = ActionContext.model_validate(record['context'])
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved final reconciliation belongs to another original invocation')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        expected = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256', 'source_mode',
            'source_reading', 'reading_sha256', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != expected or prepared['kind'] != 'prepared'
                or action_input.reconciliation_result_ref is not None or action_input.scope != context.scope
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved final reconciliation changes original input, reading or method registry')
        projection = QSFinalResultView.model_validate(prepared['projection'])
        execution = prepared['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved final reconciliation requires its complete original method execution')
        arithmetic = FinalAccountInput.model_validate(execution['input'])
        result = MethodOk[FinalAccountReport].model_validate(execution['result'])
        originals, sources, refs = {}, {}, []
        resolver = ReferenceResolver(context.run_id, source_mode=prepared['source_mode'], schemas=self.schemas)
        for item in prepared['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Final reconciliation cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in sources:
                raise TaskConflict('Final reconciliation repeats an original source reference')
            sources[ref.key()] = self.schemas.validate_projection(ref, item['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        validate_qs_final_account_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        original = prepare_final_account_arithmetic(context, action_input, reading)
        if (original['kind'] != 'prepared' or original['input'] != arithmetic
                or reading.organization_id != record['organization_id'] or reading.method_evidence()):
            raise TaskConflict('Saved reconciliation substitutes original price, certificates, cash or settlement histories')
        self._validate_method_execution(context=context, arithmetic=arithmetic,
            execution=execution, originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        evidence_refs = [ref for ref in refs if ref.kind == 'Evidence']
        if (projection.method_ref != FINAL_ACCOUNT_METHOD or projection.status != 'ok' or type(projection.ref.version) is not str
                or projection.contract_ref != original['contract_ref'] or projection.data != arithmetic
                or projection.input_sha256 != content_digest(arithmetic) or projection.report != result.value
                or projection.scope != context.scope or projection.executed_at != context.business_time
                or projection.authored_at != context.business_time or projection.available_at != context.business_time
                or not projection.effective_window.contains(context.business_time)
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_organization_id != record['organization_id']
                or projection.author_authority_ref not in context.authorization_refs or projection.author_action_id != self.ACTION_ID
                or projection.evidence_refs != evidence_refs
                or task_digest(projection.model_dump(mode='json')) != prepared['projection_sha256']
                or not isinstance(grant, Authorization) or grant.organization_id != record['organization_id']
                or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or self.ACTION_ID not in grant.action_ids or not grant.validity.contains(context.business_time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *arithmetic.source_refs]} <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Saved final projection substitutes its original output, author or source versions')
        for ref in grant.basis_refs:
            basis = sources.get(ref.key())
            if (not isinstance(basis, EvidenceRecord)
                    or basis.effective_window is not None and not basis.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved final reconciliation author lacks current original evidence')
        reading.recheck()
        return context, projection

    def _publication_refs(self, record, projection):
        refs = super()._publication_refs(record, projection)
        independent = {'FinalAccountProfile', 'ChangeClaim', 'Authority', 'Authorization', 'FunctionAssignment',
            'FinalAccountAdjustmentBasis', 'SettlementMechanism', 'SettlementConsent', 'SettlementPowerBasis', 'FinalAccountExecution'}
        for item in record['prepared']['source_reading']:
            ref = Reference.model_validate(item['ref'])
            if ref.kind in independent:
                refs.append(ref)
        return list({ref.key(): ref for ref in refs}.values())


class QSFinalAccountCalculationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSFinalAccountCalculationPublicationStore):
            raise ValueError('Final-account provider requires its original QS-A09 publication store')
        super().__init__(provider=provider, publications=publications)
