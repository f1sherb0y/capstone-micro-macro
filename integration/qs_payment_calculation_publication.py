"""Save one original payment execution and publish all its measurement results."""
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from integration.qs_payment_actions import validate_qs_payment_sources
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_payment_objects import QSPaymentResultView, qs_payment_schemas
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_change import content_digest
from src.actions.roles.qs_payment import prepare_payment_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_payment import PAYMENT_METHOD, PaymentValuationInput, PaymentValuationReport
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSPaymentCalculationPublicationStore(QSCostCalculationPublicationStore):
    """Atomic measurement bundle; no certificate, cash or method replay.

    validate_source(record, current_context) must independently return True
    under the caller's actual source writer guard. Every declared result ref
    belongs to exactly one saved execution, including overlapping bundles.
    """
    SCHEMA = 'qs-payment-calculation-record.v1'
    PUBLICATION_SCHEMA = 'qs-payment-calculation-publication.v1'
    ACTION_ID = 'QS-A08'
    METHOD_REF = PAYMENT_METHOD
    RECORDS_TABLE = 'qs_payment_calculation_records'
    PUBLICATIONS_TABLE = 'qs_payment_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(qs_payment_schemas)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.store._transaction():
            self.store._db.execute('CREATE TABLE IF NOT EXISTS qs_payment_calculation_targets '
                '(ref_key TEXT PRIMARY KEY, execution_sha256 TEXT NOT NULL)')

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'} or record['schema_version'] != self.SCHEMA
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['binding'] != self._binding()):
            raise TaskConflict('Saved payment execution changes its schema, binding or original digest')
        context = ActionContext.model_validate(record['context'])
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved payment execution belongs to another original invocation')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        expected = {'kind', 'projections', 'projections_sha256', 'context_sha256', 'input_sha256', 'source_mode',
            'source_reading', 'reading_sha256', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != expected or prepared['kind'] != 'prepared'
                or action_input.measurement_result_refs or action_input.scope != context.scope
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')
                or not isinstance(prepared['projections'], list) or not prepared['projections']
                or prepared['projections_sha256'] != task_digest(prepared['projections'])):
            raise TaskConflict('Saved payment bundle changes original input, reading, results or method registry')
        projections = [QSPaymentResultView.model_validate(row) for row in prepared['projections']]
        execution = prepared['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved payment requires the complete original method execution')
        arithmetic = PaymentValuationInput.model_validate(execution['input'])
        result = MethodOk[PaymentValuationReport].model_validate(execution['result'])
        originals, sources = {}, {}
        resolver = ReferenceResolver(context.run_id, source_mode=prepared['source_mode'], schemas=self.schemas)
        refs = []
        for item in prepared['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Payment execution cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in sources:
                raise TaskConflict('Payment execution repeats an original source reference')
            sources[ref.key()] = self.schemas.validate_projection(ref, item['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        validate_qs_payment_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        original = prepare_payment_arithmetic(context, action_input, reading)
        if (original['kind'] != 'prepared' or original['input'] != arithmetic
                or reading.organization_id != record['organization_id'] or reading.method_evidence()
                or [(row.result_kind, row.ref) for row in projections] != list(original['result_refs'].items())):
            raise TaskConflict('Saved payment substitutes original work, cash/history input or complete result targets')
        self._validate_method_execution(context=context, arithmetic=arithmetic,
            execution=execution, originals=originals, result=result)
        evidence_refs = [ref for ref in refs if ref.kind == 'Evidence']
        authors = {row.author_authority_ref.key() for row in projections}
        if len(authors) != 1:
            raise TaskConflict('One payment execution cannot substitute different result authors')
        for projection in projections:
            grant = sources.get(projection.author_authority_ref.key())
            if (projection.method_ref != PAYMENT_METHOD or projection.status != 'ok' or type(projection.ref.version) is not str
                    or projection.contract_ref != original['contract_ref'] or projection.application_ref != original['application_ref']
                    or projection.valuation_basis != original['valuation_basis'] or projection.correction_of != original['correction_of']
                    or projection.input_sha256 != content_digest(arithmetic) or projection.report != result.value
                    or projection.scope != context.scope or projection.authored_at != context.business_time
                    or projection.available_at != context.business_time or not projection.effective_window.contains(context.business_time)
                    or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                    or projection.author_authority_ref not in context.authorization_refs or projection.author_action_id != self.ACTION_ID
                    or projection.evidence_refs != evidence_refs
                    or not isinstance(grant, Authorization) or grant.organization_id != record['organization_id']
                    or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                    or self.ACTION_ID not in grant.action_ids or not grant.validity.contains(context.business_time)
                    or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
                    or not {ref.key() for ref in [projection.ref, *arithmetic.source_refs]} <= {ref.key() for ref in grant.readable_refs}):
                raise TaskConflict('Saved payment projection substitutes its original output, author or source versions')
            for ref in grant.basis_refs:
                basis = sources.get(ref.key())
                if (not isinstance(basis, EvidenceRecord)
                        or basis.effective_window is not None and not basis.effective_window.contains(context.business_time)):
                    raise TaskConflict('Saved payment author lacks current original evidence')
        reading.recheck()
        return context, projections

    def _result_projections(self, projection):
        return projection

    def _execution_ref(self, projection):
        return [row.ref.model_dump(mode='json') for row in projection]

    def _publication_content(self, projection):
        return {'objects': [{'ref': row.ref.model_dump(mode='json'), 'value': row.model_dump(mode='json')} for row in projection]}

    def _published_objects(self, publication):
        return publication['objects']

    def _publication_refs(self, record, projection):
        refs = [ref for row in projection for ref in [row.ref, *walk_references(row)]]
        arithmetic = PaymentValuationInput.model_validate(record['prepared']['method_execution']['input'])
        refs.extend(walk_references(arithmetic))
        # These historical/authority dependencies are deliberately excluded from
        # the numeric source_refs; the old technical candidate/profile is not one.
        independent = {'Authorization', 'FunctionAssignment', 'Authority', 'MethodResult', 'CorrectionBasis'}
        for item in record['prepared']['source_reading']:
            ref = Reference.model_validate(item['ref'])
            if ref.kind in independent:
                refs.append(ref)
        return list({ref.key(): ref for ref in refs}.values())

    def _target_keys(self, projection):
        return {task_digest([self.store.run_id, self.ACTION_ID, row.ref.model_dump(mode='json')]) for row in projection}

    def _save_targets(self, record, projection, *, is_new):
        if not is_new:
            self._validate_saved_targets(record, projection)
            return
        for key in self._target_keys(projection):
            if self.store._db.execute('SELECT execution_sha256 FROM qs_payment_calculation_targets WHERE ref_key=?', (key,)).fetchone() is not None:
                raise TaskConflict('Payment measurement target already belongs to an original execution')
            self.store._db.execute('INSERT INTO qs_payment_calculation_targets VALUES (?,?)', (key, record['record_sha256']))

    def _validate_saved_targets(self, record, projection):
        with self.store._lock:
            keys = {row[0] for row in self.store._db.execute(
                'SELECT ref_key FROM qs_payment_calculation_targets WHERE execution_sha256=?', (record['record_sha256'],))}
        if keys != self._target_keys(projection):
            raise TaskConflict('Saved payment execution lost its complete immutable measurement target index')


class QSPaymentCalculationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSPaymentCalculationPublicationStore):
            raise ValueError('Payment provider requires its original QS-A08 publication store')
        super().__init__(provider=provider, publications=publications)
