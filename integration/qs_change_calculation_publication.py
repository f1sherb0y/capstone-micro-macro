"""Retain original QS-A07 executions and publish them without recalculation."""
from integration.qs_change_actions import validate_qs_change_sources
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_change_objects import (
    QSChangeClaimView, QSChangeResultView, qs_change_schemas,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.pricing import decimal_fraction
from src.methods.qs_change import CHANGE_METHOD, ChangeArithmeticInput, ChangeArithmeticReport
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSChangeCalculationPublicationStore(QSCostCalculationPublicationStore):
    """Reuse original save/publish/read transactions with change-specific checks.

    The host supplies validate_source(record, current_context), returning True
    only after independently checking original quantities, rates, history and
    authors under its actual source writer guard. No retained method is rerun.
    """
    SCHEMA = 'qs-change-calculation-record.v1'
    PUBLICATION_SCHEMA = 'qs-change-calculation-publication.v1'
    ACTION_ID = 'QS-A07'
    METHOD_REF = CHANGE_METHOD
    RECORDS_TABLE = 'qs_change_calculation_records'
    PUBLICATIONS_TABLE = 'qs_change_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(qs_change_schemas)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'} or record['schema_version'] != self.SCHEMA
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['binding'] != self._binding()):
            raise TaskConflict('Saved change execution changes its schema, binding or original digest')
        context = ActionContext.model_validate(record['context'])
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved change execution belongs to another original invocation')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        expected = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256', 'source_mode',
            'source_reading', 'reading_sha256', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != expected or prepared['kind'] != 'prepared'
                or action_input.valuation_result_ref is not None or action_input.scope != context.scope
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved change execution changes original input, reading or method registry')
        projection = QSChangeResultView.model_validate(prepared['projection'])
        execution = prepared['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved change requires the complete original method execution')
        arithmetic = ChangeArithmeticInput.model_validate(execution['input'])
        result = MethodOk[ChangeArithmeticReport].model_validate(execution['result'])
        originals, sources = {}, {}
        for item in prepared['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Change execution cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in sources:
                raise TaskConflict('Change execution repeats an original source reference')
            sources[ref.key()] = self.schemas.validate_projection(ref, item['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
        validate_qs_change_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        contract = sources[action_input.contract_ref.key()]
        claim = sources[action_input.claim_or_change_ref.key()]
        lines = [sources[ref.key()] for ref in claim.line_refs]
        statements = [sources[ref.key()] for ref in claim.prior_statement_refs]
        if claim.status != 'submitted' or sorted(row.sequence for row in statements) != list(range(1, len(statements) + 1)):
            raise TaskConflict('Saved change loses its original submitted claim or complete consecutive history')
        prior_refs = set()
        for statement in statements:
            original = sources[statement.calculation_ref.key()]
            if (original.ref == projection.ref or original.ref.key() in prior_refs or original.status != 'ok'
                    or original.method_ref != CHANGE_METHOD or original.contract_ref != contract.ref
                    or original.claim_ref != statement.claim_ref or original.period_delta is None
                    or original.period_delta.currency != statement.period_delta.currency
                    or decimal_fraction(original.period_delta.value) != decimal_fraction(statement.period_delta.value)
                    or original.authored_at.clock_ref != context.business_time.clock_ref
                    or statement.authored_at.clock_ref != context.business_time.clock_ref
                    or statement.available_at.clock_ref != context.business_time.clock_ref
                    or original.authored_at.offset > statement.authored_at.offset
                    or statement.available_at.offset > context.business_time.offset):
                raise TaskConflict('Saved change substitutes its original prior calculation or period delta')
            prior_refs.add(original.ref.key())
        source_refs = [contract.ref, claim.ref, *claim.line_refs, *claim.prior_statement_refs, *action_input.evidence_refs]
        if action_input.instruction_ref is not None:
            source_refs.append(action_input.instruction_ref)
        original_input = ChangeArithmeticInput(currency=contract.currency, decimal_places=contract.decimal_places,
            basis=claim.basis, lines=[row.calculation_line for row in lines],
            prior_amounts=[row.period_delta for row in sorted(statements, key=lambda row: row.sequence)], source_refs=source_refs)
        if arithmetic != original_input:
            raise TaskConflict('Saved change arithmetic substitutes original quantities, rates or cumulative history')
        self._validate_method_execution(context=context, arithmetic=arithmetic,
            execution=execution, originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        evidence_refs = [Reference.model_validate(item['ref']) for item in prepared['source_reading']
            if item['ref']['kind'] == 'Evidence']
        if (projection.method_ref != CHANGE_METHOD or projection.status != 'ok' or type(projection.ref.version) is not str
                or projection.contract_ref != contract.ref or projection.claim_ref != claim.ref
                or projection.input_sha256 != content_digest(arithmetic)
                or projection.assessed_amount != result.value.assessed_amount or projection.period_delta != result.value.period_delta
                or projection.scope != context.scope or projection.authored_at != context.business_time
                or projection.available_at != context.business_time or not projection.effective_window.contains(context.business_time)
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref not in context.authorization_refs or projection.author_action_id != self.ACTION_ID
                or projection.evidence_refs != evidence_refs
                or task_digest(projection.model_dump(mode='json')) != prepared['projection_sha256']
                or not isinstance(grant, Authorization) or grant.organization_id != record['organization_id']
                or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or self.ACTION_ID not in grant.action_ids or not grant.validity.contains(context.business_time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *arithmetic.source_refs]} <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Saved change projection substitutes its original output, author or input versions')
        return context, projection

    def _publication_refs(self, record, projection):
        """Retain input/history read permissions beyond the small result projection."""
        arithmetic = ChangeArithmeticInput.model_validate(record['prepared']['method_execution']['input'])
        sources = {Reference.model_validate(item['ref']).key(): item['projection']
            for item in record['prepared']['source_reading']}
        refs = [*super()._publication_refs(record, projection), *walk_references(arithmetic)]
        claim = QSChangeClaimView.model_validate(sources[projection.claim_ref.key()])
        history = [Reference.model_validate(sources[ref.key()]['calculation_ref']) for ref in claim.prior_statement_refs]
        refs.extend(history)
        for ref in [*arithmetic.source_refs, *history]:
            row = sources[ref.key()]
            for name in ('author_function_ref', 'author_authority_ref', 'instruction_authority_ref'):
                if name in row:
                    refs.append(Reference.model_validate(row[name]))
        return list({ref.key(): ref for ref in refs}.values())


class QSChangeCalculationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSChangeCalculationPublicationStore):
            raise ValueError('Change provider requires its original QS-A07 publication store')
        super().__init__(provider=provider, publications=publications)
